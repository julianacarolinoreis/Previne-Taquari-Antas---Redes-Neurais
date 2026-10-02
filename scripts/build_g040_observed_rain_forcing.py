#!/usr/bin/env python3
"""Build observed hourly rainfall forcing for the G040 HEC branch model.

The rainfall field is not collapsed to one basin-wide series. For each hour:
1. query every eligible ANA/INMET/CEMADEN station inside the G040 basin;
2. aggregate each station to hourly accumulated precipitation;
3. spatially interpolate the observed field with IDW^2;
4. sample that field at the fixed BHO6 support points;
5. integrate each incremental HEC area with official BHO6 local-area weights.

Missing rainfall is never converted to zero. The resulting interval series are
research forcing for the intermediate whole-basin branch model.
"""
from __future__ import annotations

import csv
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import shape
from shapely.ops import unary_union

try:
    from scripts.build_mucum_observed_multistation import (
        BRT, UTC, aggregate_hourly, csv_observed_rain, fetch_network,
        inventory_operational, finite, qc_rain,
    )
except ModuleNotFoundError:
    from build_mucum_observed_multistation import (
        BRT, UTC, aggregate_hourly, csv_observed_rain, fetch_network,
        inventory_operational, finite, qc_rain,
    )

try:
    from scripts.g040_rain_grid import (
        GRID_CELL_COUNT, build_grid_cells, grid_contract, point_to_grid_index,
    )
except ModuleNotFoundError:
    from g040_rain_grid import (
        GRID_CELL_COUNT, build_grid_cells, grid_contract, point_to_grid_index,
    )

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
STUDY=ROOT/"assets/data/estudo_bacia_taquari_antas"
SUPPORT=BASE/"whole_basin_rain_support_points.csv"
SUPPORT_META=BASE/"whole_basin_rain_support_latest.json"
MASK=STUDY/"sub_bacias_q040_enquadramento.geojson"
RAIN_CATALOG=STUDY/"pluviometria_g040.geojson"
FLOW_CATALOG=STUDY/"postos_g040.geojson"
SCENARIOS=BASE/"whole_basin_boundary_scenarios_latest.json"
OUT=BASE/"whole_basin_observed_rain_latest.json"
OUTCSV=BASE/"whole_basin_observed_rain_hourly.csv"
OUTCOMP=BASE/"whole_basin_observed_rain_components_hourly.csv"
OUTGRID=BASE/"whole_basin_observed_rain_fullgrid_hourly.csv"

WINDOW_HOURS=max(24,min(240,int(os.environ.get("G040_OBS_RAIN_HOURS","120"))))
MAX_WORKERS=max(2,min(24,int(os.environ.get("G040_OBS_RAIN_WORKERS","12"))))
ROLLING=(1,3,6,12,24,48,72,120)

def loadj(path: Path) -> dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def basin_mask():
    raw=loadj(MASK)
    geoms=[shape(f["geometry"]) for f in raw.get("features") or [] if f.get("geometry")]
    if not geoms:
        raise RuntimeError("G040 management mask has no geometry")
    return unary_union(geoms)

def catalog(path: Path, basin) -> dict[str,dict[str,Any]]:
    out={}
    raw=loadj(path)
    for f in raw.get("features") or []:
        p=f.get("properties") or {}
        g=f.get("geometry") or {}
        coords=g.get("coordinates") or []
        if len(coords)<2:
            continue
        lon=finite(coords[0]); lat=finite(coords[1])
        code=str(p.get("codigo") or "").strip()
        if not code or lon is None or lat is None:
            continue
        from shapely.geometry import Point
        if not basin.covers(Point(float(lon),float(lat))):
            continue
        item={
            "code":code,
            "name":p.get("nome") or code,
            "network":str(p.get("rede") or "ANA").upper(),
            "lat":float(lat),
            "lon":float(lon),
            "upg":p.get("upg"),
            "station_type":p.get("tipo"),
            "operating_flag":p.get("situacao") if p.get("situacao") is not None else p.get("operando"),
        }
        out[code]=item
    return out

def read_support():
    rows=[]
    with SUPPORT.open(encoding="utf-8",newline="") as fh:
        for r in csv.DictReader(fh):
            rows.append({
                "interval_id":r["interval_id"],
                "lon":float(r["lon"]),
                "lat":float(r["lat"]),
                "local_area_km2":float(r["local_area_km2"]),
                "fid":int(r["fid"]),
                "tributary_boundary_code":str(r.get("tributary_boundary_code") or "").strip(),
                "component_id":str(r.get("component_id") or "").strip(),
            })
    if not rows:
        raise RuntimeError("BHO6 rainfall support mesh is empty")
    return rows

def hourly_axis(start: datetime,end: datetime) -> list[datetime]:
    a=start.replace(minute=0,second=0,microsecond=0)
    b=end.replace(minute=0,second=0,microsecond=0)
    out=[]
    t=a
    while t<=b:
        out.append(t)
        t+=timedelta(hours=1)
    return out

def vectorized_idw_matrix(
    points: list[dict[str,Any]],
    stations: list[dict[str,Any]],
) -> np.ndarray:
    plon=np.array([p["lon"] for p in points],dtype=float)[:,None]
    plat=np.array([p["lat"] for p in points],dtype=float)[:,None]
    slon=np.array([s["lon"] for s in stations],dtype=float)[None,:]
    slat=np.array([s["lat"] for s in stations],dtype=float)[None,:]
    dx=(slon-plon)*np.cos(np.deg2rad(plat))
    dy=slat-plat
    return dx*dx+dy*dy

def interpolate_points(d2: np.ndarray, station_values: np.ndarray) -> np.ndarray:
    """IDW^2 using every station with a finite value in the current hour."""
    valid=np.isfinite(station_values)
    if not valid.any():
        return np.full(d2.shape[0],np.nan,dtype=float)
    dd=d2[:,valid]
    vv=station_values[valid]
    nearest_idx=np.argmin(dd,axis=1)
    nearest_d=dd[np.arange(dd.shape[0]),nearest_idx]
    exact=nearest_d < 1e-12
    safe=np.maximum(dd,1e-12)
    weights=1.0/safe
    pred=(weights @ vv)/np.sum(weights,axis=1)
    if exact.any():
        pred[exact]=vv[nearest_idx[exact]]
    return pred

def rolling_summary(series: list[dict[str,Any]]) -> dict[str,Any]:
    out={}
    for n in ROLLING:
        sub=series[-n:] if len(series)>=n else list(series)
        vals=[x["mm"] for x in sub if x.get("mm") is not None]
        complete=len(sub)==n and len(vals)==n
        out[f"{n}h"]={
            "mm":round(sum(float(v) for v in vals),4) if complete else None,
            "available_hours":len(vals),
            "required_hours":n,
            "complete":complete,
        }
    return out

def iso(t: datetime) -> str:
    return t.isoformat(timespec="minutes")

def main() -> int:
    if not SUPPORT.exists() or not SUPPORT_META.exists():
        raise RuntimeError("rain support mesh has not been built")
    support_meta=loadj(SUPPORT_META)
    if support_meta.get("status")!="RAIN_SUPPORT_READY_DYNAMIC_SCENARIO":
        raise RuntimeError("scenario-aware rain support mesh is not ready")
    scenarios=loadj(SCENARIOS)
    current=scenarios.get("current") or {}
    active_boundary_codes={str(x) for x in current.get("active_boundary_codes") or []}
    expected_area={
        str(x["interval_id"]):float(x["effective_rainfall_runoff_area_km2"])
        for x in current.get("intervals") or []
    }

    end=datetime.now(BRT).replace(tzinfo=None)
    start=end-timedelta(hours=WINDOW_HOURS-1)
    basin=basin_mask()
    rain_catalog=catalog(RAIN_CATALOG,basin)
    flow_catalog=catalog(FLOW_CATALOG,basin)

    candidates={}
    for src in (rain_catalog,flow_catalog):
        for code,st in src.items():
            if inventory_operational(st):
                candidates.setdefault(code,st)

    fetched={}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures={pool.submit(fetch_network,st,start,end):code for code,st in candidates.items()}
        for fut in as_completed(futures):
            code=futures[fut]
            try:
                fetched[code]=fut.result()
            except Exception as exc:
                fetched[code]={"ok":False,"rows":[],"source":candidates[code].get("network"),"error":str(exc)}

    archived=csv_observed_rain(start,end)
    rain_series={}
    rain_stations=[]
    for code,st in candidates.items():
        series=dict(archived.get(code) or {})
        hourly=aggregate_hourly((fetched.get(code) or {}).get("rows") or [])
        for t,v in hourly.items():
            rv=qc_rain(v.get("rain_mm"))
            if rv is not None:
                series[t.replace(minute=0,second=0,microsecond=0)]=float(rv)
        if not series:
            continue
        rain_series[code]=series
        rain_stations.append({
            **st,
            "source":(fetched.get(code) or {}).get("source"),
            "valid_hours":len(series),
            "archive_contributed":bool(archived.get(code)),
        })

    points=read_support()
    intervals=sorted({p["interval_id"] for p in points})
    group_indices={
        iid:np.array([
            i for i,p in enumerate(points)
            if p["interval_id"]==iid
            and p.get("tributary_boundary_code","") not in active_boundary_codes
        ],dtype=int)
        for iid in intervals
    }
    for iid,idx in group_indices.items():
        got=float(sum(points[int(i)]["local_area_km2"] for i in idx))
        exp=expected_area.get(iid)
        if exp is None:
            raise RuntimeError(f"{iid}: no effective area in current boundary scenario")
        if abs(got-exp)>max(0.05,0.0005*exp):
            raise RuntimeError(f"{iid}: scenario support area {got:.6f} != effective area {exp:.6f}")
    point_area=np.array([p["local_area_km2"] for p in points],dtype=float)
    component_ids=sorted({p["component_id"] for p in points if p.get("component_id")})
    component_indices={
        cid:np.array([i for i,p in enumerate(points) if p.get("component_id")==cid],dtype=int)
        for cid in component_ids
    }
    component_area={cid:float(point_area[idx].sum()) for cid,idx in component_indices.items()}
    used_component={
        cid:(not cid.startswith("BRANCH_") or cid.replace("BRANCH_","",1) not in active_boundary_codes)
        for cid in component_ids
    }
    used_component_area=sum(component_area[cid] for cid in component_ids if used_component[cid])
    scenario_total=float(current.get("effective_rainfall_runoff_area_km2") or 0.0)
    if abs(used_component_area-scenario_total)>max(0.05,0.0005*scenario_total):
        raise RuntimeError(
            f"scenario component area {used_component_area:.6f} != effective rainfall-runoff area {scenario_total:.6f}"
        )

    grid_cells=build_grid_cells()
    if len(grid_cells)!=GRID_CELL_COUNT:
        raise RuntimeError("fixed G040 rainfall grid is incomplete")
    grid_points=[{"lon":c["longitude"],"lat":c["latitude"]} for c in grid_cells]
    support_grid_idx=np.array([point_to_grid_index(p["lon"],p["lat"]) for p in points],dtype=int)

    hours=hourly_axis(start,end)
    station_codes=[s["code"] for s in rain_stations]
    if rain_stations:
        d2=vectorized_idw_matrix(grid_points,rain_stations)
    else:
        d2=np.empty((GRID_CELL_COUNT,0),dtype=float)

    interval_series={iid:[] for iid in intervals}
    component_series={cid:[] for cid in component_ids}
    hourly_rows=[]
    component_rows=[]
    grid_rows=[]
    grid_cell_ids=[c["cell_id"] for c in grid_cells]
    for hour in hours:
        vals=np.array([
            rain_series.get(code,{}).get(hour,np.nan)
            for code in station_codes
        ],dtype=float)
        valid_count=int(np.isfinite(vals).sum())
        if valid_count:
            grid_rain=interpolate_points(d2,vals)
        else:
            grid_rain=np.full(GRID_CELL_COUNT,np.nan,dtype=float)
        point_rain=grid_rain[support_grid_idx]

        grow={"time_local":iso(hour),"valid_station_count":valid_count}
        for gi,cid in enumerate(grid_cell_ids):
            grow[cid]=None if not np.isfinite(grid_rain[gi]) else round(float(grid_rain[gi]),4)
        grid_rows.append(grow)

        row={"time_local":iso(hour),"valid_station_count":valid_count}
        for iid in intervals:
            idx=group_indices[iid]
            pv=point_rain[idx]
            aa=point_area[idx]
            good=np.isfinite(pv) & np.isfinite(aa) & (aa>0)
            if not good.any():
                mm=None
            else:
                mm=float(np.sum(pv[good]*aa[good])/np.sum(aa[good]))
            interval_series[iid].append({"time_local":iso(hour),"mm":None if mm is None else round(mm,4),"valid_station_count":valid_count})
            row[iid]=None if mm is None else round(mm,4)
        hourly_rows.append(row)
        crow={"time_local":iso(hour),"valid_station_count":valid_count}
        for cid in component_ids:
            idx=component_indices[cid]
            pv=point_rain[idx]
            aa=point_area[idx]
            good=np.isfinite(pv) & np.isfinite(aa) & (aa>0)
            mm=None if not good.any() else float(np.sum(pv[good]*aa[good])/np.sum(aa[good]))
            component_series[cid].append({
                "time_local":iso(hour),
                "mm":None if mm is None else round(mm,4),
                "valid_station_count":valid_count,
            })
            crow[cid]=None if mm is None else round(mm,4)
        component_rows.append(crow)

    with OUTCSV.open("w",encoding="utf-8",newline="") as fh:
        fields=["time_local","valid_station_count",*intervals]
        w=csv.DictWriter(fh,fieldnames=fields)
        w.writeheader()
        for row in hourly_rows:
            w.writerow({k:"" if row.get(k) is None else row.get(k) for k in fields})

    with OUTCOMP.open("w",encoding="utf-8",newline="") as fh:
        fields=["time_local","valid_station_count",*component_ids]
        w=csv.DictWriter(fh,fieldnames=fields)
        w.writeheader()
        for row in component_rows:
            w.writerow({k:"" if row.get(k) is None else row.get(k) for k in fields})

    with OUTGRID.open("w",encoding="utf-8",newline="") as fh:
        fields=["time_local","valid_station_count",*grid_cell_ids]
        w=csv.DictWriter(fh,fieldnames=fields)
        w.writeheader()
        for row in grid_rows:
            w.writerow({k:"" if row.get(k) is None else row.get(k) for k in fields})

    failures=[
        {"code":code,"network":st.get("network"),"error":(fetched.get(code) or {}).get("error")}
        for code,st in candidates.items()
        if not (fetched.get(code) or {}).get("ok")
    ]

    interval_payload=[]
    for iid in intervals:
        series=interval_series[iid]
        available=sum(x.get("mm") is not None for x in series)
        interval_payload.append({
            "interval_id":iid,
            "support_points":len(group_indices[iid]),
            "support_area_km2":round(float(point_area[group_indices[iid]].sum()),6),
            "available_hours":available,
            "expected_hours":len(hours),
            "coverage_ratio":round(available/len(hours),4) if hours else 0.0,
            "rolling_accumulations":rolling_summary(series),
            "series":series,
        })

    component_payload=[]
    for cid in component_ids:
        series=component_series[cid]
        branch_code=cid.replace("BRANCH_","",1) if cid.startswith("BRANCH_") else None
        component_payload.append({
            "component_id":cid,
            "component_type":"tributary_branch" if branch_code else "mainstem_core_increment",
            "tributary_boundary_code":branch_code,
            "used_as_rainfall_runoff_in_current_scenario":used_component[cid],
            "support_points":len(component_indices[cid]),
            "support_area_km2":round(component_area[cid],6),
            "available_hours":sum(x.get("mm") is not None for x in series),
            "expected_hours":len(hours),
            "rolling_accumulations":rolling_summary(series),
            "series":series,
        })

    station_payload=[]
    for st in rain_stations:
        code=st["code"]
        s=rain_series[code]
        station_payload.append({
            **st,
            "first_observation_local":iso(min(s)),
            "last_observation_local":iso(max(s)),
            "accum_mm":round(sum(s.values()),3),
            "series":[{"time_local":iso(t),"mm":round(v,4)} for t,v in sorted(s.items())],
        })

    status="OBSERVED_RAIN_READY" if rain_stations and all(x["available_hours"]>0 for x in interval_payload) else "OBSERVED_RAIN_PARTIAL"
    payload={
        "schema_version":"g040_observed_rain_forcing_v2",
        "generated_at_utc":datetime.now(UTC).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":status,
        "window":{
            "start_local":iso(start),
            "end_local":iso(end),
            "timezone":"America/Sao_Paulo",
            "hours":len(hours),
        },
        "method":{
            "station_temporal_semantics":"hourly accumulated precipitation per station",
            "spatial_interpolation":"IDW^2 using every station with a valid value in each hour",
            "station_scope":"all_valid_stations_each_hour",
            "cross_station_sum":False,
            "full_grid_preserved":True,
            "integration":"sample fixed 0.1-degree grid at BHO6 support points, then BHO6 local-area weighted mean per HEC incremental interval",
            "missing_policy":"missing remains missing; never zero-filled",
            "support_reference":str(SUPPORT.relative_to(ROOT)),
            "boundary_scenario":scenarios.get("current_scenario"),
            "active_observed_boundary_codes":sorted(active_boundary_codes),
        },
        "grid":{
            **grid_contract(),
            "complete_grid_hours":sum(
                1 for row in grid_rows
                if all(row[cid] is not None for cid in grid_cell_ids)
            ),
            "expected_hours":len(hours),
            "missing_cell_policy":"no zero fill; an hour with no valid stations remains missing on all 600 cells",
        },
        "boundary_scenario":{
            "name":scenarios.get("current_scenario"),
            "active_boundary_codes":sorted(active_boundary_codes),
            "effective_rainfall_runoff_area_km2":current.get("effective_rainfall_runoff_area_km2"),
        },
        "network":{
            "eligible_station_count":len(candidates),
            "valid_rain_station_count":len(rain_stations),
            "valid_by_network":{
                net:sum(str(s.get("network") or "").upper()==net for s in rain_stations)
                for net in ("ANA","INMET","CEMADEN")
            },
        },
        "intervals":interval_payload,
        "components":component_payload,
        "component_area_gate":{
            "used_component_area_km2":round(used_component_area,6),
            "scenario_effective_rainfall_runoff_area_km2":round(scenario_total,6),
            "error_km2":round(used_component_area-scenario_total,6),
            "pass":True,
        },
        "stations":station_payload,
        "fetch_audit":{
            "queried":len(candidates),
            "successful_with_any_response":sum(bool((fetched.get(c) or {}).get("ok")) for c in candidates),
            "failed_count":len(failures),
            "failures":failures,
        },
        "artifacts":{
            "hourly_interval_csv":str(OUTCSV.relative_to(ROOT)),
            "hourly_component_csv":str(OUTCOMP.relative_to(ROOT)),
            "full_grid_hourly_csv":str(OUTGRID.relative_to(ROOT)),
        },
        "next_step":"merge with spatial ECMWF/IFS forecast after the latest observed forcing hour and run branch-wise HEC calibration/replay",
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":status,
        "valid_rain_stations":len(rain_stations),
        "valid_by_network":payload["network"]["valid_by_network"],
        "intervals":len(intervals),
        "hours":len(hours),
        "failed_queries":len(failures),
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
