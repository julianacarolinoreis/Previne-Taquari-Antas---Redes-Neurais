#!/usr/bin/env python3
"""Audit independent historical meteorological forcing for G040 using NASA POWER.

This audit samples the verified BHO6 hydrometric-control coordinates. It does
not create MGB mini-basin forcing and does not replace the preferred ERA5-Land
historical source. It only verifies that an independent, open, hourly source
can provide the required meteorological variable classes with explicit UTC
timestamps and missingness accounting.

Research only.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
STACK=ROOT/"assets/data/g040_hydro_stack"
TOPO=BASE/"whole_basin_bho6_topology_latest.json"
OUT=STACK/"mgb_met_nasa_power_audit_latest.json"

API="https://power.larc.nasa.gov/api/temporal/hourly/point"
PARAMETERS=["T2M","RH2M","WS10M","ALLSKY_SFC_SW_DWN","PS"]
USER_AGENT="PREVINE-G040-MGB-met-audit/1.0"
MAX_WORKERS=5

def fetch_point(code: str, item: dict, start: str, end: str) -> dict:
    params={
        "parameters":",".join(PARAMETERS),
        "community":"SB",
        "longitude":str(item["station_lon"]),
        "latitude":str(item["station_lat"]),
        "start":start,
        "end":end,
        "format":"JSON",
        "time-standard":"UTC",
    }
    url=API+"?"+urlencode(params)
    last=None
    for attempt in range(1,5):
        try:
            req=Request(url,headers={"User-Agent":USER_AGENT})
            with urlopen(req,timeout=90) as resp:
                payload=json.load(resp)
            break
        except Exception as exc:
            last=exc
            if attempt==4:
                return {"code":code,"ok":False,"error":str(exc),"url":url}
            time.sleep(attempt*3)
    p=((payload.get("properties") or {}).get("parameter") or {})
    variables={}
    for name in PARAMETERS:
        series=p.get(name) or {}
        vals=[]
        missing=0
        for ts,v in series.items():
            try:
                x=float(v)
            except Exception:
                missing+=1
                continue
            if not math.isfinite(x) or x<=-900:
                missing+=1
                continue
            vals.append(x)
        total=len(series)
        variables[name]={
            "reported_hours":total,
            "valid_hours":len(vals),
            "missing_hours":missing,
            "coverage_ratio":round(len(vals)/total,4) if total else 0.0,
            "min":round(min(vals),4) if vals else None,
            "max":round(max(vals),4) if vals else None,
        }
    return {
        "code":code,
        "name":item.get("station_name"),
        "latitude":item["station_lat"],
        "longitude":item["station_lon"],
        "ok":all(variables[x]["reported_hours"]>0 for x in PARAMETERS),
        "variables":variables,
        "api_header":payload.get("header") or {},
        "api_parameters_metadata":payload.get("parameters") or {},
    }

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",default="20240501")
    ap.add_argument("--end",default="20240503")
    ap.add_argument("--max-points",type=int,default=13)
    args=ap.parse_args()

    topo=json.loads(TOPO.read_text(encoding="utf-8"))
    snapped=topo.get("snapped_stations") or {}
    preferred=[
        "86472000","86500000","86510000","86595000","86720000","86743000",
        "86746000","86879000","86879300","86895000","86950000","86996000",
        "86447000",
    ]
    selected=[(c,snapped[c]) for c in preferred if c in snapped][:args.max_points]
    if not selected:
        raise RuntimeError("no verified G040 control coordinates")

    results=[]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs={pool.submit(fetch_point,c,x,args.start,args.end):c for c,x in selected}
        for fut in as_completed(futs):
            results.append(fut.result())
    results.sort(key=lambda x:x["code"])

    variable_summary={}
    for name in PARAMETERS:
        cov=[
            float((r.get("variables") or {}).get(name,{}).get("coverage_ratio") or 0.0)
            for r in results if r.get("ok")
        ]
        variable_summary[name]={
            "points_with_data":sum(1 for x in cov if x>0),
            "point_count":len(results),
            "minimum_point_coverage":round(min(cov),4) if cov else 0.0,
            "mean_point_coverage":round(sum(cov)/len(cov),4) if cov else 0.0,
        }

    all_classes=all(variable_summary[p]["points_with_data"]==len(results) for p in PARAMETERS)
    payload={
        "schema_version":"g040_mgb_nasa_power_met_audit_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"INDEPENDENT_MET_SOURCE_AUDIT_PASS" if all_classes else "INDEPENDENT_MET_SOURCE_AUDIT_PARTIAL",
        "source":{
            "provider":"NASA POWER",
            "endpoint":"hourly point API",
            "time_standard":"UTC",
            "role":"independent historical meteorological audit; not canonical MGB forcing",
            "parameters":PARAMETERS,
        },
        "audit_window":{"start":args.start,"end":args.end},
        "point_count":len(results),
        "variable_summary":variable_summary,
        "points":results,
        "gates":{
            "all_required_variable_classes_present_at_all_sampled_points":all_classes,
            "canonical_mgb_forcing_ready":False,
            "pet_method_selected":False,
        },
        "limitations":[
            "point audit only; MGB mini-basin interpolation/aggregation is not generated",
            "preferred historical source remains ERA5-Land official CDS until a model experiment justifies a change",
            "source spatial resolutions differ by POWER variable and must not be relabeled as the G040 0.1-degree rainfall grid",
        ],
        "next_step":"compare source continuity against ERA5-Land/INMET on fixed benchmark periods, then generate MGB mini-basin forcing only after DEM/mini-basin geometry is fixed",
        "promotion_allowed":False,
    }
    STACK.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":payload["status"],
        "points":len(results),
        "variable_summary":variable_summary,
    },ensure_ascii=False))
    return 0 if all_classes else 2

if __name__=="__main__":
    raise SystemExit(main())
