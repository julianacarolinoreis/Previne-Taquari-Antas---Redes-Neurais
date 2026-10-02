#!/usr/bin/env python3
"""Build spatial ECMWF/IFS rainfall forcing for G040 incremental HEC areas.

The fixed BHO6 rain-support mesh is mapped to the native 0.25-degree ECMWF IFS
sampling grid. Local drainage area is aggregated by IFS cell and interval, then
hourly cell precipitation is area-weighted back to each HEC incremental area.

No single basin-wide rainfall series is used as model forcing.
Research only; not an official warning system.
"""
from __future__ import annotations

import csv
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from scripts.g040_rain_grid import (
        GRID_CELL_COUNT, GRID_STEP_DEG, build_grid_cells, grid_contract,
        point_to_grid_index,
    )
except ModuleNotFoundError:
    from g040_rain_grid import (
        GRID_CELL_COUNT, GRID_STEP_DEG, build_grid_cells, grid_contract,
        point_to_grid_index,
    )

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
SUPPORT=BASE/"whole_basin_rain_support_points.csv"
SUPPORT_META=BASE/"whole_basin_rain_support_latest.json"
OUT=BASE/"whole_basin_ifs_forecast_latest.json"
OUTCSV=BASE/"whole_basin_ifs_forecast_hourly.csv"
OUTCOMP=BASE/"whole_basin_ifs_forecast_components_hourly.csv"
OUTGRID=BASE/"whole_basin_ifs_fullgrid_hourly.csv"
SCENARIOS=BASE/"whole_basin_boundary_scenarios_latest.json"

HORIZON_HOURS=120
BATCH_SIZE=40
USER_AGENT="PREVINE-G040-IFS-research/1.0"

def parse_hour(raw: str) -> datetime:
    dt=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def start_hour() -> datetime:
    return datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)

def load_support():
    rows=[]
    with SUPPORT.open(encoding="utf-8",newline="") as fh:
        for r in csv.DictReader(fh):
            rows.append({
                "interval_id":r["interval_id"],
                "lon":float(r["lon"]),
                "lat":float(r["lat"]),
                "area_km2":float(r["local_area_km2"]),
                "tributary_boundary_code":str(r.get("tributary_boundary_code") or "").strip(),
                "component_id":str(r.get("component_id") or "").strip(),
            })
    if not rows:
        raise RuntimeError("G040 rain support mesh is empty")
    return rows

def build_cell_weights(points, active_boundary_codes, grid_cells):
    by_interval={}
    for p in points:
        if p.get("tributary_boundary_code","") in active_boundary_codes:
            continue
        cell=grid_cells[point_to_grid_index(p["lon"],p["lat"])]
        cid=cell["cell_id"]
        bucket=by_interval.setdefault(p["interval_id"],{})
        bucket[cid]=bucket.get(cid,0.0)+float(p["area_km2"])
    summaries={}
    for iid,cells in by_interval.items():
        total=sum(cells.values())
        if total<=0:
            raise RuntimeError(f"{iid}: non-positive support area")
        summaries[iid]={
            "total_area_km2":total,
            "cells":{
                cid:{"area_km2":area,"weight":area/total}
                for cid,area in sorted(cells.items())
            },
        }
    return grid_cells,summaries

def build_component_weights(points, grid_cells):
    by_component={}
    for p in points:
        comp=p.get("component_id")
        if not comp:
            continue
        cell=grid_cells[point_to_grid_index(p["lon"],p["lat"])]
        cid=cell["cell_id"]
        bucket=by_component.setdefault(comp,{})
        bucket[cid]=bucket.get(cid,0.0)+float(p["area_km2"])
    summaries={}
    for comp,cells in by_component.items():
        total=sum(cells.values())
        if total<=0:
            raise RuntimeError(f"{comp}: non-positive support area")
        summaries[comp]={
            "total_area_km2":total,
            "cells":{
                cid:{"area_km2":area,"weight":area/total}
                for cid,area in sorted(cells.items())
            },
        }
    return grid_cells,summaries

def fetch_batch(points,start_utc):
    params={
        "latitude":",".join(f"{p['latitude']:.4f}" for p in points),
        "longitude":",".join(f"{p['longitude']:.4f}" for p in points),
        "models":"ecmwf_ifs025",
        "hourly":"precipitation",
        "forecast_days":7,
        "timezone":"UTC",
    }
    url="https://api.open-meteo.com/v1/forecast?"+urlencode(params)
    req=Request(url,headers={"User-Agent":USER_AGENT})
    payload=None
    last=None
    for attempt in range(1,5):
        try:
            with urlopen(req,timeout=90) as resp:
                payload=json.load(resp)
            break
        except Exception as exc:
            last=exc
            if attempt==4:
                raise RuntimeError(f"Open-Meteo IFS batch failed: {exc}") from exc
            time.sleep(attempt*4)
    if payload is None:
        raise RuntimeError(f"empty IFS payload: {last}")
    if isinstance(payload,dict):
        payload=[payload]
    if not isinstance(payload,list) or len(payload)!=len(points):
        raise RuntimeError(f"IFS response count mismatch: expected {len(points)} got {len(payload) if isinstance(payload,list) else type(payload)}")
    out=[]
    for point,item in zip(points,payload):
        h=item.get("hourly") or {}
        times=list(h.get("time") or [])
        rain=list(h.get("precipitation") or [])
        if len(times)!=len(rain):
            raise RuntimeError(f"{point['cell_id']}: time/rain length mismatch")
        rows=[]
        for t,v in zip(times,rain):
            dt=parse_hour(t)
            if dt<start_utc:
                continue
            if v is None:
                rows.append((dt,None))
            else:
                x=float(v)
                if not math.isfinite(x) or x<0:
                    rows.append((dt,None))
                else:
                    rows.append((dt,x))
        rows=rows[:HORIZON_HOURS]
        if len(rows)<HORIZON_HOURS:
            raise RuntimeError(f"{point['cell_id']}: only {len(rows)} forecast hours")
        if any(v is None for _,v in rows):
            raise RuntimeError(f"{point['cell_id']}: missing IFS precipitation; aborting instead of zero-filling")
        out.append({
            **point,
            "response_latitude":item.get("latitude"),
            "response_longitude":item.get("longitude"),
            "times_utc":[t.isoformat().replace("+00:00","Z") for t,_ in rows],
            "precip_mm":[round(float(v),4) for _,v in rows],
        })
    return out

def fetch_all(cells,start_utc):
    out=[]
    for i in range(0,len(cells),BATCH_SIZE):
        out.extend(fetch_batch(cells[i:i+BATCH_SIZE],start_utc))
        if i+BATCH_SIZE < len(cells):
            time.sleep(0.25)
    return out

def rolling(series,n):
    if len(series)<n:
        return None
    vals=[x["mm"] for x in series[:n]]
    if any(v is None for v in vals):
        return None
    return round(sum(float(v) for v in vals),4)

def main() -> int:
    meta=json.loads(SUPPORT_META.read_text(encoding="utf-8"))
    if meta.get("status")!="RAIN_SUPPORT_READY_DYNAMIC_SCENARIO":
        raise RuntimeError("scenario-aware BHO6 rain support not ready")
    scenarios=json.loads(SCENARIOS.read_text(encoding="utf-8"))
    current=scenarios.get("current") or {}
    active_boundary_codes={str(x) for x in current.get("active_boundary_codes") or []}
    expected_area={
        str(x["interval_id"]):float(x["effective_rainfall_runoff_area_km2"])
        for x in current.get("intervals") or []
    }
    points=load_support()
    grid_cells=build_grid_cells()
    if len(grid_cells)!=GRID_CELL_COUNT:
        raise RuntimeError(f"fixed G040 forecast grid must contain {GRID_CELL_COUNT} cells")
    cells_all,_gross_weights=build_cell_weights(points,set(),grid_cells)
    _component_cells,component_weights=build_component_weights(points,grid_cells)
    cells=cells_all
    _scenario_cells,weights=build_cell_weights(points,active_boundary_codes,grid_cells)
    for iid,info in weights.items():
        exp=expected_area.get(iid)
        if exp is None:
            raise RuntimeError(f"{iid}: no effective area in current boundary scenario")
        got=float(info["total_area_km2"])
        if abs(got-exp)>max(0.05,0.0005*exp):
            raise RuntimeError(f"{iid}: scenario IFS support area {got:.6f} != effective area {exp:.6f}")
    start=start_hour()
    fetched=fetch_all(cells,start)
    if len(fetched)!=GRID_CELL_COUNT:
        raise RuntimeError(f"forecast grid incomplete: expected {GRID_CELL_COUNT}, got {len(fetched)}")
    by_cell={x["cell_id"]:x for x in fetched}
    if len(by_cell)!=GRID_CELL_COUNT:
        raise RuntimeError("duplicate or missing fixed-grid cell identifiers")
    times=fetched[0]["times_utc"]
    if len(times)!=HORIZON_HOURS:
        raise RuntimeError(f"expected {HORIZON_HOURS} forecast hours, found {len(times)}")
    if any(x["times_utc"]!=times for x in fetched):
        raise RuntimeError("IFS cell time axes differ")

    interval_series={}
    for iid,info in weights.items():
        series=[]
        for h,t in enumerate(times):
            total=0.0
            for cid,w in info["cells"].items():
                total+=float(by_cell[cid]["precip_mm"][h])*float(w["weight"])
            series.append({"time_utc":t,"mm":round(total,4)})
        interval_series[iid]=series

    components=[]
    component_series={}
    for comp,info in component_weights.items():
        series=[]
        for h,t in enumerate(times):
            total=0.0
            for cid,w in info["cells"].items():
                total+=float(by_cell[cid]["precip_mm"][h])*float(w["weight"])
            series.append({"time_utc":t,"mm":round(total,4)})
        component_series[comp]=series
        branch_code=comp.replace("BRANCH_","",1) if comp.startswith("BRANCH_") else None
        components.append({
            "component_id":comp,
            "component_type":"tributary_branch" if branch_code else "mainstem_core_increment",
            "tributary_boundary_code":branch_code,
            "used_as_rainfall_runoff_in_current_scenario":not branch_code or branch_code not in active_boundary_codes,
            "support_area_km2":round(info["total_area_km2"],6),
            "ifs_cell_count":len(info["cells"]),
            "forecast_accumulations":{
                "6h_mm":rolling(series,6),"12h_mm":rolling(series,12),
                "24h_mm":rolling(series,24),"48h_mm":rolling(series,48),
                "72h_mm":rolling(series,72),"120h_mm":rolling(series,120),
            },
            "series":series,
        })

    intervals=[]
    for iid in sorted(interval_series):
        series=interval_series[iid]
        info=weights[iid]
        intervals.append({
            "interval_id":iid,
            "support_area_km2":round(info["total_area_km2"],6),
            "ifs_cell_count":len(info["cells"]),
            "cell_weights":{
                cid:{
                    "area_km2":round(v["area_km2"],6),
                    "weight":round(v["weight"],10),
                }
                for cid,v in info["cells"].items()
            },
            "forecast_accumulations":{
                "6h_mm":rolling(series,6),
                "12h_mm":rolling(series,12),
                "24h_mm":rolling(series,24),
                "48h_mm":rolling(series,48),
                "72h_mm":rolling(series,72),
                "120h_mm":rolling(series,120),
            },
            "series":series,
        })

    with OUTCSV.open("w",encoding="utf-8",newline="") as fh:
        interval_ids=sorted(interval_series)
        fields=["time_utc",*interval_ids]
        w=csv.DictWriter(fh,fieldnames=fields)
        w.writeheader()
        for h,t in enumerate(times):
            row={"time_utc":t}
            for iid in interval_ids:
                row[iid]=interval_series[iid][h]["mm"]
            w.writerow(row)

    with OUTCOMP.open("w",encoding="utf-8",newline="") as fh:
        component_ids=sorted(component_series)
        fields=["time_utc",*component_ids]
        w=csv.DictWriter(fh,fieldnames=fields)
        w.writeheader()
        for h,t in enumerate(times):
            row={"time_utc":t}
            for cid in component_ids:
                row[cid]=component_series[cid][h]["mm"]
            w.writerow(row)

    grid_cell_ids=[c["cell_id"] for c in grid_cells]
    with OUTGRID.open("w",encoding="utf-8",newline="") as fh:
        fields=["time_utc",*grid_cell_ids]
        w=csv.DictWriter(fh,fieldnames=fields)
        w.writeheader()
        for h,t in enumerate(times):
            row={"time_utc":t}
            for cid in grid_cell_ids:
                row[cid]=by_cell[cid]["precip_mm"][h]
            w.writerow(row)

    response_native_coords={
        (round(float(x["response_latitude"]),4),round(float(x["response_longitude"]),4))
        for x in fetched
        if x.get("response_latitude") is not None and x.get("response_longitude") is not None
    }
    support_used_cells={
        cid for info in _gross_weights.values() for cid in info["cells"]
    }

    payload={
        "schema_version":"g040_ifs_interval_forcing_v2",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"IFS_FULLGRID_FORCING_READY_CYCLE_ID_UNVERIFIED",
        "source":{
            "provider":"Open-Meteo ECMWF endpoint",
            "model":"ECMWF IFS",
            "model_query":"ecmwf_ifs025",
            "native_model_resolution_deg":0.25,
            "sampling_grid_resolution_deg":GRID_STEP_DEG,
            "variable":"hourly precipitation",
            "exact_ecmwf_cycle_id":None,
            "cycle_provenance_gate":False,
            "cycle_note":"this endpoint does not expose an exact ECMWF cycle identifier; retrieval time is not relabeled as model cycle",
            "missing_policy":"abort instead of replacing missing forecast precipitation with zero",
            "neighbor_fill_used":False,
        },
        "window":{
            "start_utc":times[0],
            "end_utc":times[-1],
            "hours":len(times),
        },
        "boundary_scenario":{
            "name":scenarios.get("current_scenario"),
            "active_boundary_codes":sorted(active_boundary_codes),
            "effective_rainfall_runoff_area_km2":current.get("effective_rainfall_runoff_area_km2"),
        },
        "spatial_method":{
            "support":"BHO6 reach-midpoint drainage support mesh",
            "forecast_field":"complete fixed 0.1-degree HEC sampling grid",
            "support_to_grid":"containing fixed-grid cell",
            "integration":"BHO6 local-area weighted mean per incremental HEC interval",
            "collapsed_to_single_basin_series":False,
        },
        "grid":{
            **grid_contract(),
            "requested_cells":len(fetched),
            "support_used_cells":len(support_used_cells),
            "response_native_coordinate_count":len(response_native_coords),
            "all_cells_120h_complete":all(len(x["precip_mm"])==HORIZON_HOURS for x in fetched),
            "cell_metadata":[{
                "cell_id":c["cell_id"],
                "row":c["row"],
                "col":c["col"],
                "latitude":c["latitude"],
                "longitude":c["longitude"],
                "response_latitude":c.get("response_latitude"),
                "response_longitude":c.get("response_longitude"),
                "total_120h_mm":round(sum(c["precip_mm"]),3),
            } for c in fetched],
        },
        "gates":{
            "full_600_cell_grid":len(fetched)==GRID_CELL_COUNT,
            "120h_each_cell":all(len(x["precip_mm"])==HORIZON_HOURS for x in fetched),
            "zero_missing_or_nodata":all(all(v is not None for v in x["precip_mm"]) for x in fetched),
            "neighbor_fill_used":False,
            "exact_cycle_id_available":False,
            "operational_promotion_allowed":False,
        },
        "intervals":intervals,
        "components":components,
        "artifacts":{
            "hourly_interval_csv":str(OUTCSV.relative_to(ROOT)),
            "hourly_component_csv":str(OUTCOMP.relative_to(ROOT)),
            "full_grid_hourly_csv":str(OUTGRID.relative_to(ROOT)),
        },
        "next_step":"merge with the matching observed 600-cell field; keep research-only until exact ECMWF cycle provenance is attached",
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":payload["status"],
        "grid_cells":len(fetched),
        "response_native_coordinates":len(response_native_coords),
        "exact_cycle_id_available":False,
        "intervals":len(intervals),
        "start_utc":times[0],
        "end_utc":times[-1],
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
