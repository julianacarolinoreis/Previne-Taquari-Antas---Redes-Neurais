#!/usr/bin/env python3
"""Retrieve an exact archived ECMWF run on the fixed 600-cell G040 rain grid.

Uses Open-Meteo Single Runs API with an explicit UTC initialization time.  The
script preserves run provenance and area-weights the 600-cell field to the same
11 hydrologic components used by the observed G040 forcing.

Research/backtest only.  This is deliberately different from the live endpoint,
which stitches the latest forecast and does not identify an exact ECMWF cycle.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from scripts.build_g040_ifs_interval_forcing import (
        BATCH_SIZE,
        USER_AGENT,
        build_component_weights,
        load_support,
        parse_hour,
    )
    from scripts.g040_rain_grid import GRID_CELL_COUNT, build_grid_cells, grid_contract
    from scripts.g040_nested_zone_rain import aggregate_grid_by_zone, audit_summary as nested_grid_audit
except ModuleNotFoundError:
    from build_g040_ifs_interval_forcing import (
        BATCH_SIZE,
        USER_AGENT,
        build_component_weights,
        load_support,
        parse_hour,
    )
    from g040_rain_grid import GRID_CELL_COUNT, build_grid_cells, grid_contract
    from g040_nested_zone_rain import aggregate_grid_by_zone, audit_summary as nested_grid_audit

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
ENDPOINT="https://single-runs-api.open-meteo.com/v1/forecast"
MODEL_CANDIDATES=("ecmwf_ifs","ecmwf_ifs025")
FORECAST_DAYS=10
AVAILABILITY_LAG_H=6

def parse_run(value: str) -> datetime:
    d=datetime.fromisoformat(value.replace("Z","+00:00"))
    if d.tzinfo is None:
        d=d.replace(tzinfo=timezone.utc)
    d=d.astimezone(timezone.utc).replace(second=0,microsecond=0)
    if d.minute!=0 or d.hour not in (0,6,12,18):
        raise ValueError("ECMWF run must be a 00/06/12/18 UTC initialization")
    return d

def request_batch(points,run_utc,model_query,forecast_days=FORECAST_DAYS):
    params={
        "latitude":",".join(f"{p['latitude']:.4f}" for p in points),
        "longitude":",".join(f"{p['longitude']:.4f}" for p in points),
        "models":model_query,
        "hourly":"precipitation",
        "run":run_utc.strftime("%Y-%m-%dT%H:%M"),
        "forecast_days":forecast_days,
        "timezone":"UTC",
    }
    req=Request(ENDPOINT+"?"+urlencode(params),headers={"User-Agent":USER_AGENT+" exact-run"})
    last=None
    for attempt in range(1,5):
        try:
            with urlopen(req,timeout=120) as resp:
                payload=json.load(resp)
            if isinstance(payload,dict) and payload.get("error"):
                raise RuntimeError(str(payload.get("reason") or payload))
            if isinstance(payload,dict):
                payload=[payload]
            if not isinstance(payload,list) or len(payload)!=len(points):
                raise RuntimeError(
                    f"response count mismatch: expected {len(points)}, got "
                    f"{len(payload) if isinstance(payload,list) else type(payload)}"
                )
            return payload
        except Exception as exc:
            last=exc
            if attempt==4:
                raise
            time.sleep(attempt*3)
    raise RuntimeError(str(last))

def select_model_query(run_utc,cells):
    errors={}
    for model in MODEL_CANDIDATES:
        try:
            p=request_batch(cells[:1],run_utc,model,forecast_days=2)
            h=(p[0].get("hourly") or {})
            if h.get("time") and h.get("precipitation"):
                return model
            errors[model]="empty hourly payload"
        except Exception as exc:
            errors[model]=str(exc)
    raise RuntimeError(f"no archived ECMWF model query succeeded for {run_utc}: {errors}")

def fetch_all(cells,run_utc,model_query):
    out=[]
    usable_after=run_utc+timedelta(hours=AVAILABILITY_LAG_H)
    for i in range(0,len(cells),BATCH_SIZE):
        batch=cells[i:i+BATCH_SIZE]
        payload=request_batch(batch,run_utc,model_query)
        for point,item in zip(batch,payload):
            h=item.get("hourly") or {}
            tt=list(h.get("time") or [])
            vv=list(h.get("precipitation") or [])
            if len(tt)!=len(vv):
                raise RuntimeError(f"{point['cell_id']}: time/rain length mismatch")
            rows=[]
            for t,v in zip(tt,vv):
                dt=parse_hour(t)
                # A run is not operationally available at initialization.  For
                # the frozen replay we conservatively expose only valid times
                # strictly after run+6 h.  Null precipitation at initialization
                # is therefore outside the usable forecast and must not fail the
                # causal package.
                if dt<=usable_after:
                    continue
                if v is None:
                    raise RuntimeError(f"{point['cell_id']}: missing usable precipitation at {t}")
                x=float(v)
                if not math.isfinite(x) or x<0:
                    raise RuntimeError(f"{point['cell_id']}: invalid precipitation {v} at {t}")
                rows.append((dt,x))
            if not rows:
                raise RuntimeError(f"{point['cell_id']}: no forecast rows")
            out.append({
                **point,
                "response_latitude":item.get("latitude"),
                "response_longitude":item.get("longitude"),
                "rows":rows,
            })
        if i+BATCH_SIZE<len(cells):
            time.sleep(0.25)
    return out

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--run",required=True,help="ECMWF initialization, e.g. 2024-05-01T00:00")
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()

    run_utc=parse_run(args.run)
    cells=build_grid_cells()
    if len(cells)!=GRID_CELL_COUNT:
        raise RuntimeError("G040 fixed grid is incomplete")
    model_query=select_model_query(run_utc,cells)
    fetched=fetch_all(cells,run_utc,model_query)
    if len(fetched)!=GRID_CELL_COUNT:
        raise RuntimeError(f"expected {GRID_CELL_COUNT} grid cells, got {len(fetched)}")

    axes=[[t for t,_v in x["rows"]] for x in fetched]
    times=axes[0]
    if any(a!=times for a in axes[1:]):
        raise RuntimeError("exact-run grid cells returned different time axes")
    by_cell={x["cell_id"]:x for x in fetched}

    points=load_support()
    _grid,component_weights=build_component_weights(points,cells)
    components=[]
    for comp,info in sorted(component_weights.items()):
        series=[]
        for h,t in enumerate(times):
            total=0.0
            for cid,w in info["cells"].items():
                total+=float(by_cell[cid]["rows"][h][1])*float(w["weight"])
            series.append({
                "time_utc":t.isoformat().replace("+00:00","Z"),
                "mm":round(total,4),
            })
        branch=comp.replace("BRANCH_","",1) if comp.startswith("BRANCH_") else None
        components.append({
            "component_id":comp,
            "component_type":"tributary_branch" if branch else "mainstem_core_increment",
            "tributary_boundary_code":branch,
            "support_area_km2":round(float(info["total_area_km2"]),6),
            "cell_count":len(info["cells"]),
            "series":series,
        })

    nested_rows={}
    for h,t in enumerate(times):
        zone_values=aggregate_grid_by_zone({
            cid:float(item["rows"][h][1])
            for cid,item in by_cell.items()
        })
        for sid,mm in zone_values.items():
            nested_rows.setdefault(sid,[]).append({
                "time_utc":t.isoformat().replace("+00:00","Z"),
                "mm":round(float(mm),4),
            })
    nested_zones=[
        {
            "subbasin_id":sid,
            "expected_hours":len(times),
            "available_hours":len(rows),
            "coverage_ratio":1.0 if len(rows)==len(times) else len(rows)/max(len(times),1),
            "series":rows,
        }
        for sid,rows in sorted(nested_rows.items())
    ]

    payload={
        "schema_version":"g040_ecmwf_exact_single_run_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"EXACT_ECMWF_SINGLE_RUN_READY",
        "source":{
            "provider":"Open-Meteo Single Runs API",
            "endpoint":ENDPOINT,
            "model_query":model_query,
            "model_family":"ECMWF IFS",
            "run_initialization_utc":run_utc.isoformat().replace("+00:00","Z"),
            "run_is_explicit":True,
            "availability_assumption_hours_after_initialization":AVAILABILITY_LAG_H,
            "note":"6 h availability lag is a conservative frozen backtest convention; only valid times strictly after that decision time are exposed",
        },
        "grid":{
            **grid_contract(),
            "requested_cells":len(fetched),
            "complete":len(fetched)==GRID_CELL_COUNT,
            "time_axis_hours":len(times),
        },
        "window":{
            "first_valid_utc":times[0].isoformat().replace("+00:00","Z"),
            "last_valid_utc":times[-1].isoformat().replace("+00:00","Z"),
            "hours":len(times),
        },
        "components":components,
        "upper_antas_nested_forcing":{
            "purpose":"exact ECMWF rain for predictive 86472000 boundary",
            "spatial_support":"fixed 600-cell G040 grid integrated over Muçum twin hydrologic zones",
            "grid_overlap":nested_grid_audit(),
            "zones":nested_zones,
        },
        "gates":{
            "full_600_cell_grid":len(fetched)==GRID_CELL_COUNT,
            "single_explicit_run":True,
            "missing_zero_filled":False,
            "forecast_after_decision_only_required_by_merger":True,
            "pre_availability_hours_discarded":True,
        },
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":payload["status"],
        "run":payload["source"]["run_initialization_utc"],
        "model_query":model_query,
        "grid_cells":len(fetched),
        "hours":len(times),
        "components":len(components),
        "nested_zones":len(nested_zones),
        "output":str(args.output),
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
