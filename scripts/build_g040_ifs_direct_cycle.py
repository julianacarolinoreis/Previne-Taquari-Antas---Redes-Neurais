#!/usr/bin/env python3
"""Build an exact-cycle ECMWF Open Data rainfall audit for the G040 600-cell grid.

This is isolated from the canonical forcing.  It proves that the same fixed
0.1-degree HEC sampling grid can be sourced from a specific ECMWF IFS cycle
without relabelling retrieval time as model cycle.

Native IFS resolution remains 0.25 degree.  ECMWF tp is cumulative at native
3-hour steps; increments are divided uniformly over each 3-hour block only for
compatibility with the current hourly HEC forcing contract.

Research only; not an official warning system.
"""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError

try:
    from scripts.ecmwf_direct import (
        ROOT as ECMWF_ROOT, _decode_point, _find_cycle, _find_tp_entry, _request,
    )
    from scripts.g040_rain_grid import GRID_CELL_COUNT, build_grid_cells, grid_contract
    from scripts.build_g040_ifs_interval_forcing import (
        load_support, build_cell_weights, build_component_weights,
    )
except ModuleNotFoundError:
    from ecmwf_direct import (
        ROOT as ECMWF_ROOT, _decode_point, _find_cycle, _find_tp_entry, _request,
    )
    from g040_rain_grid import GRID_CELL_COUNT, build_grid_cells, grid_contract
    from build_g040_ifs_interval_forcing import (
        load_support, build_cell_weights, build_component_weights,
    )

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
SCENARIOS=BASE/"whole_basin_boundary_scenarios_latest.json"
OUT=BASE/"whole_basin_ifs_direct_cycle_latest.json"
OUTGRID=BASE/"whole_basin_ifs_direct_cycle_fullgrid_hourly.csv"
OUTINT=BASE/"whole_basin_ifs_direct_cycle_intervals_hourly.csv"
OUTCOMP=BASE/"whole_basin_ifs_direct_cycle_components_hourly.csv"

MAX_STEP_H=max(3,min(120,int(os.environ.get("IFS_MAX_STEP_H","120"))))
if MAX_STEP_H % 3:
    raise SystemExit("IFS_MAX_STEP_H must be a multiple of 3")
CYCLE_RAW=os.environ.get("IFS_CYCLE_UTC","").strip()

def parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z","+00:00")).astimezone(timezone.utc)

def select_cycle() -> tuple[datetime,str]:
    if CYCLE_RAW:
        c=parse_utc(CYCLE_RAW)
        if c.minute or c.second or c.microsecond or c.hour not in (0,6,12,18):
            raise RuntimeError(f"invalid IFS cycle: {CYCLE_RAW}")
        prefix=f"{ECMWF_ROOT}/{c:%Y%m%d}/{c:%Hz}/ifs/0p25/oper"
        # Explicitly verify a required file exists for this cycle.
        step=min(MAX_STEP_H,24)
        url=f"{prefix}/{c:%Y%m%d%H}0000-{step}h-oper-fc.grib2.index"
        _request(url)
        return c,prefix
    c,prefix,_files=_find_cycle(datetime.now(timezone.utc))
    return c,prefix

def polite_request(url: str, *, byte_range=None) -> bytes:
    last=None
    for attempt in range(1,8):
        try:
            time.sleep(0.4 if byte_range is None else 0.6)
            return _request(url,byte_range=byte_range)
        except HTTPError as exc:
            last=exc
            if exc.code!=429 or attempt==7:
                raise
            pause=attempt*5.0
            if exc.headers:
                try:
                    pause=max(pause,float(exc.headers.get("Retry-After") or 0))
                except Exception:
                    pass
            print(f"ECMWF 429; retry {attempt}/7 after {pause:.1f}s",flush=True)
            time.sleep(pause)
    raise RuntimeError(f"ECMWF request failed: {last}")

def step_url(prefix: str, cycle: datetime, step: int) -> str:
    return f"{prefix}/{cycle:%Y%m%d%H}0000-{step}h-oper-fc.grib2"

def read_cumulative(prefix: str, cycle: datetime, step: int, cells: list[dict]) -> dict[str,float]:
    url=step_url(prefix,cycle,step)
    index=polite_request(url.replace(".grib2",".index")).decode("utf-8")
    entry=_find_tp_entry(index,step)
    off,length=int(entry["_offset"]),int(entry["_length"])
    payload=polite_request(url,byte_range=(off,off+length-1))
    out={}
    for cell in cells:
        p=_decode_point(payload,latitude=float(cell["latitude"]),longitude=float(cell["longitude"]))
        mm=p.get("rain_mm")
        if mm is None:
            raise RuntimeError(f"non-finite tp at {cell['cell_id']} +{step}h")
        out[cell["cell_id"]]=float(mm)
    return out

def scenario_active_codes() -> tuple[str,list[str]]:
    raw=json.loads(SCENARIOS.read_text(encoding="utf-8"))
    cur=raw.get("current") or {}
    return str(cur.get("name") or "unknown"),[str(x) for x in (cur.get("active_boundary_codes") or [])]

def weighted_series(weights: dict, hourly: dict[str,dict[datetime,float]], times: list[datetime]) -> dict[str,list[float]]:
    out={}
    for key,info in weights.items():
        vals=[]
        for t in times:
            vals.append(sum(hourly[cid][t]*float(meta["weight"]) for cid,meta in info["cells"].items()))
        out[key]=vals
    return out

def write_matrix(path: Path, times: list[datetime], series: dict[str,list[float]], first="time_utc"):
    keys=sorted(series)
    with path.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=[first,*keys]); w.writeheader()
        for i,t in enumerate(times):
            row={first:t.isoformat().replace("+00:00","Z")}
            for k in keys: row[k]=round(float(series[k][i]),4)
            w.writerow(row)

def main() -> int:
    cycle,prefix=select_cycle()
    cells=build_grid_cells()
    if len(cells)!=GRID_CELL_COUNT:
        raise RuntimeError(f"expected 600 sampling cells, got {len(cells)}")
    support=load_support()
    scenario,active=scenario_active_codes()
    _grid,interval_weights=build_cell_weights(support,set(active),cells)
    _grid2,component_weights=build_component_weights(support,cells)

    hourly={c["cell_id"]:{} for c in cells}
    previous={c["cell_id"]:0.0 for c in cells}
    steps=list(range(3,MAX_STEP_H+1,3))
    for step in steps:
        cumulative=read_cumulative(prefix,cycle,step,cells)
        start=cycle+timedelta(hours=step-3)
        for cid,total in cumulative.items():
            inc=float(total)-previous[cid]
            if inc < -0.05:
                raise RuntimeError(f"negative tp increment {inc:.3f} mm at {cid} +{step}h")
            inc=max(0.0,inc)
            each=inc/3.0
            for k in range(3):
                hourly[cid][start+timedelta(hours=k)]=each
            previous[cid]=float(total)

    times=[cycle+timedelta(hours=h) for h in range(MAX_STEP_H)]
    for cid in hourly:
        if any(t not in hourly[cid] for t in times):
            raise RuntimeError(f"{cid}: incomplete exact-cycle hourly field")

    cell_series={cid:[hourly[cid][t] for t in times] for cid in sorted(hourly)}
    interval_series=weighted_series(interval_weights,hourly,times)
    component_series=weighted_series(component_weights,hourly,times)

    write_matrix(OUTGRID,times,cell_series)
    write_matrix(OUTINT,times,interval_series)
    write_matrix(OUTCOMP,times,component_series)

    cell_totals={cid:sum(v) for cid,v in cell_series.items()}
    payload={
        "schema_version":"g040_ifs_direct_cycle_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"EXACT_CYCLE_FULLGRID_READY",
        "source":{
            "provider":"ECMWF Open Data",
            "model":"IFS",
            "native_model_resolution_deg":0.25,
            "sampling_grid_resolution_deg":0.1,
            "variable":"tp",
            "cycle_time_utc":cycle.isoformat().replace("+00:00","Z"),
            "cycle_locked":True,
            "source_root":ECMWF_ROOT,
            "fallback_used":False,
            "native_temporal_resolution_h":3,
            "hourly_disaggregation":"each 3-hour tp increment divided uniformly over the block",
        },
        "window":{
            "start_utc":times[0].isoformat().replace("+00:00","Z"),
            "end_utc":times[-1].isoformat().replace("+00:00","Z"),
            "hours":len(times),
        },
        "boundary_scenario":{"name":scenario,"active_boundary_codes":active},
        "grid":{
            **grid_contract(),
            "complete_cells":len(cell_series),
            "min_total_mm":round(min(cell_totals.values()),3),
            "max_total_mm":round(max(cell_totals.values()),3),
        },
        "interval_count":len(interval_series),
        "component_count":len(component_series),
        "gates":{
            "full_600_cell_grid":len(cell_series)==600,
            "all_hours_complete":all(len(v)==MAX_STEP_H for v in cell_series.values()),
            "exact_cycle_id_available":True,
            "cycle_locked":True,
            "fallback_used":False,
            "negative_increment_detected":False,
        },
        "artifacts":{
            "full_grid_hourly_csv":str(OUTGRID.relative_to(ROOT)),
            "interval_hourly_csv":str(OUTINT.relative_to(ROOT)),
            "component_hourly_csv":str(OUTCOMP.relative_to(ROOT)),
        },
        "promotion_note":"This closes cycle provenance only. Hydrologic-model operational promotion remains subject to independent validation and all other gates.",
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":payload["status"],
        "cycle":payload["source"]["cycle_time_utc"],
        "hours":MAX_STEP_H,
        "cells":len(cell_series),
        "intervals":len(interval_series),
        "components":len(component_series),
        "min_total_mm":payload["grid"]["min_total_mm"],
        "max_total_mm":payload["grid"]["max_total_mm"],
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
