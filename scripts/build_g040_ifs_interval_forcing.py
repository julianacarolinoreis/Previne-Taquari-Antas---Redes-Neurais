#!/usr/bin/env python3
"""Build the full-grid ECMWF/IFS rainfall forcing for G040.

The operational research contract is the same rectangle used by the HEC-HMS
packages: 0.1-degree sampling grid, 30 longitude columns x 20 latitude rows
(600 cells), 120 hourly records, no NoData/NaN and no neighbor filling.

The Open-Meteo endpoint exposes ECMWF IFS 0.25-degree model data.  We query it
at all 600 fixed 0.1-degree cell centers and preserve those requested cells as
our HEC sampling grid.  Therefore 0.1 degree is the HEC sampling-grid spacing,
not a false claim about the native IFS model resolution.

An exact ECMWF cycle identifier is not exposed by this endpoint; that
provenance limitation is explicit and blocks operational promotion, but the
field remains usable for research comparison/replay.

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
OUTGRIDCSV=BASE/"whole_basin_ifs_fullgrid_hourly.csv"

HORIZON_HOURS=120
BATCH_SIZE=40
USER_AGENT="PREVINE-G040-IFS-fullgrid-research/2.0"
MODEL_QUERY="ecmwf_ifs025"

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
            })
    if not rows:
        raise RuntimeError("G040 rain support mesh is empty")
    return rows

def build_cell_weights(points,grid_cells):
    by_interval={}
    used=set()
    for p in points:
        idx=point_to_grid_index(p["lon"],p["lat"])
        cell=grid_cells[idx]
        cid=cell["cell_id"]
        used.add(cid)
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
    return summaries,used

def fetch_batch(points,start_utc):
    params={
        "latitude":",".join(f"{p['latitude']:.4f}" for p in points),
        "longitude":",".join(f"{p['longitude']:.4f}" for p in points),
        "models":MODEL_QUERY,
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
                raise RuntimeError(f"Open-Meteo ECMWF batch failed: {exc}") from exc
            time.sleep(attempt*4)
    if payload is None:
        raise RuntimeError(f"empty ECMWF payload: {last}")
    if isinstance(payload,dict):
        payload=[payload]
    if not isinstance(payload,list) or len(payload)!=len(points):
        got=len(payload) if isinstance(payload,list) else type(payload)
        raise RuntimeError(f"ECMWF response count mismatch: expected {len(points)} got {got}")

    out=[]
    for point,item in zip(points,payload):
        hourly=item.get("hourly") or {}
        times=list(hourly.get("time") or [])
        rain=list(hourly.get("precipitation") or [])
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
                rows.append((dt,x if math.isfinite(x) and x>=0 else None))
        rows=rows[:HORIZON_HOURS]
        if len(rows)<HORIZON_HOURS:
            raise RuntimeError(f"{point['cell_id']}: only {len(rows)} forecast hours")
        if any(v is None for _,v in rows):
            raise RuntimeError(f"{point['cell_id']}: missing ECMWF precipitation; aborting instead of zero-filling")
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
    if meta.get("status")!="RAIN_SUPPORT_READY":
        raise RuntimeError("BHO6 rain support not ready")

    support=load_support()
    grid_cells=build_grid_cells()
    if len(grid_cells)!=GRID_CELL_COUNT:
        raise RuntimeError(f"full grid must have {GRID_CELL_COUNT} cells")

    weights,used_cells=build_cell_weights(support,grid_cells)
    start=start_hour()
    fetched=fetch_all(grid_cells,start)
    if len(fetched)!=GRID_CELL_COUNT:
        raise RuntimeError(f"forecast grid incomplete: expected {GRID_CELL_COUNT}, got {len(fetched)}")

    by_cell={x["cell_id"]:x for x in fetched}
    if len(by_cell)!=GRID_CELL_COUNT:
        raise RuntimeError("duplicate or missing fixed-grid cell identifiers")
    times=fetched[0]["times_utc"]
    if len(times)!=HORIZON_HOURS:
        raise RuntimeError(f"expected {HORIZON_HOURS} forecast hours, found {len(times)}")
    if any(x["times_utc"]!=times for x in fetched):
        raise RuntimeError("ECMWF cell time axes differ")

    # Persist the complete field, not only the cells touched by residual support.
    cell_ids=[c["cell_id"] for c in grid_cells]
    with OUTGRIDCSV.open("w",encoding="utf-8",newline="") as fh:
        fields=["time_utc",*cell_ids]
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader()
        for h,t in enumerate(times):
            row={"time_utc":t}
            for cid in cell_ids:
                row[cid]=by_cell[cid]["precip_mm"][h]
            w.writerow(row)

    interval_series={}
    for iid,info in weights.items():
        series=[]
        for h,t in enumerate(times):
            total=sum(
                float(by_cell[cid]["precip_mm"][h])*float(v["weight"])
                for cid,v in info["cells"].items()
            )
            series.append({"time_utc":t,"mm":round(total,4)})
        interval_series[iid]=series

    intervals=[]
    for iid in sorted(interval_series):
        series=interval_series[iid]
        info=weights[iid]
        intervals.append({
            "interval_id":iid,
            "support_area_km2":round(info["total_area_km2"],6),
            "sampling_grid_cell_count":len(info["cells"]),
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
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader()
        for h,t in enumerate(times):
            row={"time_utc":t}
            for iid in interval_ids:
                row[iid]=interval_series[iid][h]["mm"]
            w.writerow(row)

    response_native_coords={
        (round(float(x["response_latitude"]),4),round(float(x["response_longitude"]),4))
        for x in fetched
        if x.get("response_latitude") is not None and x.get("response_longitude") is not None
    }
    retrieval=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    payload={
        "schema_version":"g040_ifs_interval_forcing_v2",
        "generated_at_utc":retrieval,
        "research_only":True,
        "status":"IFS_FULLGRID_FORCING_READY_CYCLE_ID_UNVERIFIED",
        "source":{
            "provider":"Open-Meteo ECMWF endpoint",
            "model":"ECMWF IFS",
            "model_query":MODEL_QUERY,
            "native_model_resolution_deg":0.25,
            "sampling_grid_resolution_deg":GRID_STEP_DEG,
            "variable":"hourly precipitation",
            "retrieval_time_utc":retrieval,
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
        "spatial_method":{
            "support":"BHO6 reach-midpoint drainage support mesh",
            "forecast_field":"complete fixed 0.1-degree HEC sampling grid",
            "support_to_grid":"containing fixed-grid cell; no nearest-station or basin-mean collapse",
            "integration":"BHO6 local-area weighted mean per incremental HEC interval",
            "collapsed_to_single_basin_series":False,
        },
        "grid":{
            **grid_contract(),
            "requested_cells":len(fetched),
            "support_used_cells":len(used_cells),
            "response_native_coordinate_count":len(response_native_coords),
            "all_cells_120h_complete":all(len(x["precip_mm"])==HORIZON_HOURS for x in fetched),
            "cells":[{
                "cell_id":x["cell_id"],
                "row":x["row"],
                "col":x["col"],
                "latitude":x["latitude"],
                "longitude":x["longitude"],
                "response_latitude":x.get("response_latitude"),
                "response_longitude":x.get("response_longitude"),
                "total_120h_mm":round(sum(x["precip_mm"]),3),
            } for x in fetched],
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
        "artifacts":{
            "interval_hourly_csv":str(OUTCSV.relative_to(ROOT)),
            "full_grid_hourly_csv":str(OUTGRIDCSV.relative_to(ROOT)),
        },
        "next_step":"merge with the matching observed 600-cell field; for operational promotion replace/augment source provenance with an exact ECMWF cycle identifier",
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":payload["status"],
        "grid_cells":len(fetched),
        "native_response_coordinates":len(response_native_coords),
        "support_used_cells":len(used_cells),
        "intervals":len(intervals),
        "start_utc":times[0],
        "end_utc":times[-1],
        "exact_cycle_id_available":False,
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
