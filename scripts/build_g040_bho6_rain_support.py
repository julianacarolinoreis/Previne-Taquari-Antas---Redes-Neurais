#!/usr/bin/env python3
"""Build BHO6 area-weighted rainfall support points for G040 residual catchments.

Why this exists
---------------
The current residual-area budget is already physically closed from BHO6 local
catchment areas, but the polygon crosswalk is blocked because BHO2017 polygon
codes do not match BHO6/2022 Otto codes. This script avoids inventing polygon
matches: each BHO6 residual drainage element is represented by the midpoint of
its own drainage reach and weighted by its official local area (nuareacont).

Any spatial rainfall field can later be sampled at these support points:
- observed IDW/radar/gauge field;
- ECMWF/IFS 0.25°;
- ECMWF/IFS 0.1° or another verified grid.

The interval rainfall is the area-weighted mean over all support points. This
keeps the same mass-balance area used by the HEC branch skeleton while the
native ANADEM/BHO6 polygons are still being recovered.

Research only; not an official warning system.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from shapely.geometry import shape

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
TOPO=BASE/"whole_basin_bho6_topology_latest.json"
BUDGET=BASE/"whole_basin_incremental_area_budget_latest.json"
OUT=BASE/"whole_basin_rain_support_latest.json"
OUTCSV=BASE/"whole_basin_rain_support_points.csv"

BHO6_QUERY=(
    "https://portal1.snirh.gov.br/server/rest/services/Hosted/"
    "main_geoft_bho6_trecho_drenagem/FeatureServer/0/query"
)
FIELDS=(
    "fid,cotrecho,noorigem,nodestino,cocursodag,cobacia,"
    "nuareamont,nuareacont,nucomptrec,dsversao"
)

def get_json(session: requests.Session, params: dict[str, Any]) -> dict[str, Any]:
    r=session.get(BHO6_QUERY,params=params,timeout=120)
    r.raise_for_status()
    p=r.json()
    if "error" in p:
        raise RuntimeError(json.dumps(p["error"],ensure_ascii=False))
    return p

def fetch_attributes(session: requests.Session) -> list[dict[str,Any]]:
    rows=[]; offset=0
    while True:
        p=get_json(session,{
            "where":"cocursodag LIKE '786%'",
            "outFields":FIELDS,
            "returnGeometry":"false",
            "resultOffset":offset,
            "resultRecordCount":2000,
            "orderByFields":"fid",
            "f":"json",
        })
        page=[x["attributes"] for x in p.get("features",[])]
        rows.extend(page)
        if len(page)<2000:
            break
        offset+=len(page)
    if not rows:
        raise RuntimeError("BHO6 family 786 returned no records")
    return rows

def fetch_geometries(session: requests.Session, fids: list[int]) -> dict[int,dict[str,Any]]:
    out={}
    for i in range(0,len(fids),100):
        batch=fids[i:i+100]
        where="fid IN ("+",".join(str(int(x)) for x in batch)+")"
        p=get_json(session,{
            "where":where,
            "outFields":FIELDS,
            "returnGeometry":"true",
            "outSR":"4326",
            "resultRecordCount":200,
            "f":"geojson",
        })
        for f in p.get("features",[]):
            props=f.get("properties") or {}
            if props.get("fid") is None or not f.get("geometry"):
                continue
            out[int(props["fid"])]=f
    return out

def upstream_set(by_dest: dict[int,list[dict[str,Any]]], start_fid: int, by_fid: dict[int,dict[str,Any]]) -> set[int]:
    start=by_fid[int(start_fid)]
    selected={int(start["fid"])}
    pending=[int(start["noorigem"])]
    visited=set()
    while pending:
        node=pending.pop()
        if node in visited:
            continue
        visited.add(node)
        for s in by_dest.get(node,[]):
            fid=int(s["fid"])
            if fid in selected:
                continue
            selected.add(fid)
            pending.append(int(s["noorigem"]))
    return selected

def midpoint_lonlat(feature: dict[str,Any]) -> tuple[float,float]:
    g=shape(feature["geometry"])
    if g.is_empty:
        raise RuntimeError("empty BHO6 geometry")
    p=g.interpolate(0.5,normalized=True)
    return float(p.x),float(p.y)

def main() -> int:
    topo=json.loads(TOPO.read_text(encoding="utf-8"))
    budget=json.loads(BUDGET.read_text(encoding="utf-8"))
    if not topo.get("topology_pass"):
        raise RuntimeError("BHO6 topology has not passed")
    if budget.get("status")!="AREA_BUDGET_CLOSED":
        raise RuntimeError("incremental area budget is not closed")

    with requests.Session() as session:
        session.headers.update({"User-Agent":"PREVINE-G040-rain-support/1.0"})
        segs=fetch_attributes(session)
        by_fid={int(x["fid"]):x for x in segs}
        by_dest={}
        for x in segs:
            by_dest.setdefault(int(x["nodestino"]),[]).append(x)

        snapped=topo["snapped_stations"]
        cache={}
        def U(code: str) -> set[int]:
            if code not in cache:
                cache[code]=upstream_set(
                    by_dest,
                    int(snapped[code]["segment"]["fid"]),
                    by_fid,
                )
            return cache[code]

        residual_by_interval={}
        all_fids=set()
        budget_by_id={x["interval_id"]:x for x in budget["intervals"]}
        for item in budget["intervals"]:
            iid=item["interval_id"]
            up=item["upstream_station"]; down=item["downstream_station"]
            residual=set(U(down))-set(U(up))
            for b in item.get("entering_observed_boundaries") or []:
                residual-=set(U(str(b["station_code"])))
            residual_by_interval[iid]=residual
            all_fids.update(residual)

        geom=fetch_geometries(session,sorted(all_fids))

    missing_geom=sorted(all_fids-set(geom))
    if missing_geom:
        raise RuntimeError(f"missing BHO6 geometries for {len(missing_geom)} residual segments")

    rows=[]
    summaries=[]
    for iid,residual in residual_by_interval.items():
        b=budget_by_id[iid]
        expected=float(b["residual_rainfall_runoff_area_km2"])
        local_sum=sum(float(by_fid[f].get("nuareacont") or 0.0) for f in residual)
        if expected<=0:
            raise RuntimeError(f"{iid}: non-positive expected area")
        area_error=local_sum-expected
        if abs(area_error)>max(0.05,0.0005*expected):
            raise RuntimeError(f"{iid}: support area does not close: {local_sum} vs {expected}")
        interval_rows=[]
        for fid in sorted(residual):
            attrs=by_fid[fid]
            a=float(attrs.get("nuareacont") or 0.0)
            if a<=0:
                continue
            lon,lat=midpoint_lonlat(geom[fid])
            row={
                "interval_id":iid,
                "upstream_station":b["upstream_station"],
                "downstream_station":b["downstream_station"],
                "fid":fid,
                "cobacia":str(attrs.get("cobacia") or ""),
                "lon":round(lon,7),
                "lat":round(lat,7),
                "local_area_km2":a,
                "weight":a/local_sum if local_sum else 0.0,
            }
            interval_rows.append(row)
            rows.append(row)
        weight_sum=sum(x["weight"] for x in interval_rows)
        summaries.append({
            "interval_id":iid,
            "support_points":len(interval_rows),
            "budget_area_km2":round(expected,6),
            "support_area_km2":round(local_sum,6),
            "area_error_km2":round(area_error,6),
            "weight_sum":round(weight_sum,12),
            "pass":abs(area_error)<=max(0.05,0.0005*expected) and abs(weight_sum-1.0)<=1e-9,
        })

    if not rows:
        raise RuntimeError("no support points generated")
    if not all(x["pass"] for x in summaries):
        raise RuntimeError("one or more support intervals failed closure")

    with OUTCSV.open("w",encoding="utf-8",newline="") as fh:
        fields=[
            "interval_id","upstream_station","downstream_station","fid","cobacia",
            "lon","lat","local_area_km2","weight",
        ]
        w=csv.DictWriter(fh,fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k:row[k] for k in fields})

    payload={
        "schema_version":"g040_bho6_rain_support_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"RAIN_SUPPORT_READY",
        "method":{
            "geometry":"BHO6 reach midpoint",
            "weight":"BHO6 local drainage area nuareacont",
            "rainfall_operator":"sample/interpolate spatial rainfall at each support point, then area-weight within interval",
            "polygon_dependency":False,
            "reason":"BHO2017 polygon codes are incompatible with BHO6/2022 Otto codes; no guessed crosswalk is used",
        },
        "source":{
            "provider":"ANA/SNIRH",
            "dataset":"BHO6 trecho drenagem",
            "version":next((str(x.get("dsversao")) for x in segs if x.get("dsversao")),None),
        },
        "intervals":summaries,
        "total_support_points":len(rows),
        "total_support_area_km2":round(sum(x["support_area_km2"] for x in summaries),6),
        "expected_residual_area_km2":round(float(budget["residual_rainfall_runoff_area_km2"]),6),
        "all_intervals_close":True,
        "usage_contract":{
            "observed":"IDW/other audited observed rainfall field sampled at support points",
            "forecast":"ECMWF/IFS field sampled at support points without collapsing the spatial field first",
            "missing":"missing meteorological input is never coerced to zero",
            "validation":"compare later against native ANADEM/BHO6 polygons when recovered",
        },
        "artifacts":{"support_points_csv":str(OUTCSV.relative_to(ROOT))},
        "next_step":"build observed and forecast hourly rainfall series per interval from this fixed support mesh",
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":payload["status"],
        "total_support_points":payload["total_support_points"],
        "total_support_area_km2":payload["total_support_area_km2"],
        "expected_residual_area_km2":payload["expected_residual_area_km2"],
        "intervals":len(summaries),
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
