#!/usr/bin/env python3
"""Build true antecedent-rainfall state proxies for fixed G040 benchmark events.

The historical analog selector previously compared current *previous* rainfall
against rain from the first/max 24 h of the historical target event.  That is
not antecedent state.  This builder uses only rainfall strictly before each
event start and publishes 24/72/168 h accumulations plus an exponentially
weighted API diagnostic (tau=72 h).

Research only.  API is a wetness proxy, not a calibrated soil-moisture state.
Missing rainfall is never converted to zero.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.build_g040_historical_calibration_forcing import (
        component_forcing,
        event_window,
        fetch_event_rain,
        historical_hydro,
        hourly_axis,
        rain_candidates,
    )
except ModuleNotFoundError:
    from build_g040_historical_calibration_forcing import (
        component_forcing,
        event_window,
        fetch_event_rain,
        historical_hydro,
        hourly_axis,
        rain_candidates,
    )

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
OUTROOT=BASE/"historical_antecedent_wetness"
DEFAULT_EVENTS=("E22_SEP2023","E24_NOV2023","E27_MAY2024","E28_JUN2024","E2026_JUL")
WINDOW_H=168
API_TAU_H=72.0

def iso(value: datetime) -> str:
    return value.isoformat(timespec="minutes")

def area_weighted_series(components: list[dict[str,Any]]) -> list[dict[str,Any]]:
    if not components:
        return []
    n=max((len(c.get("series") or []) for c in components),default=0)
    out=[]
    for i in range(n):
        num=den=0.0
        stamp=None
        used=0
        for c in components:
            rows=c.get("series") or []
            if i>=len(rows):
                continue
            r=rows[i]
            stamp=stamp or r.get("time_local")
            mm=r.get("mm")
            area=float(c.get("support_area_km2") or 0.0)
            if mm is None or area<=0:
                continue
            num+=float(mm)*area
            den+=area
            used+=1
        out.append({
            "time_local":stamp,
            "mm":None if den<=0 else num/den,
            "component_count":used,
            "area_weight_km2":den,
        })
    return out

def summarize(series: list[dict[str,Any]]) -> dict[str,Any]:
    vals=[r.get("mm") for r in series]
    available=sum(v is not None for v in vals)

    def tail_sum(hours: int) -> float|None:
        block=vals[-hours:]
        if len(block)<hours or any(v is None for v in block):
            return None
        return float(sum(float(v) for v in block))

    api=0.0
    api_complete=True
    # Last item is the hour immediately before event start; age=0.5 h is a
    # midpoint convention for interval precipitation and is fixed in advance.
    for age_idx,v in enumerate(reversed(vals)):
        if v is None:
            api_complete=False
            continue
        age_h=age_idx+0.5
        api+=float(v)*math.exp(-age_h/API_TAU_H)

    return {
        "rain_24h_mm":tail_sum(24),
        "rain_72h_mm":tail_sum(72),
        "rain_168h_mm":tail_sum(168),
        "api_tau_72h_mm":api if api_complete and len(vals)>=168 else None,
        "available_hours":available,
        "expected_hours":len(vals),
        "coverage_ratio":available/len(vals) if vals else 0.0,
    }

def build_event(event_id: str, *, max_workers: int) -> dict[str,Any]:
    event=historical_hydro(event_id)
    event_start,_event_end=event_window(event)
    start=event_start-timedelta(hours=WINDOW_H)
    end=event_start-timedelta(hours=1)
    times=hourly_axis(start,end)
    if len(times)!=WINDOW_H:
        raise RuntimeError(f"{event_id}: expected {WINDOW_H} antecedent hours, got {len(times)}")

    candidates=rain_candidates()
    stations,series_by_code,failures=fetch_event_rain(
        candidates,start,end,max_workers=max_workers
    )
    # All 11 hydrologic components participate in basin antecedent wetness.
    # Observed tributary boundaries affect runoff routing, not whether rain fell
    # over their drainage area.
    components,diagnostics=component_forcing(
        stations,series_by_code,times,active_boundaries=[]
    )
    basin=area_weighted_series(components)
    summary=summarize(basin)
    payload={
        "schema_version":"g040_historical_antecedent_wetness_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "event_id":event_id,
        "event_start_local":iso(event_start),
        "window":{
            "start_local":iso(start),
            "end_local":iso(end),
            "hours":len(times),
            "strictly_pre_event":True,
        },
        "method":{
            "rain_source":"same observed-station acquisition/QC and IDW^2 component forcing used by G040 historical calibration forcing",
            "basin_aggregation":"area-weighted across all 11 hydrologic components",
            "accumulations_h":[24,72,168],
            "api":"sum(P_h * exp(-age_h/72h)); diagnostic antecedent-precipitation proxy only",
            "future_event_rain_used":False,
            "missing_policy":"missing remains missing; no zero fill",
        },
        "summary":summary,
        "rain_diagnostics":diagnostics,
        "network":{
            "eligible_station_count":len(candidates),
            "valid_rain_station_count":len(stations),
            "failures":failures,
        },
        "components":[{
            "component_id":c.get("component_id"),
            "support_area_km2":c.get("support_area_km2"),
            "available_hours":c.get("available_hours"),
            "expected_hours":c.get("expected_hours"),
            "coverage_ratio":c.get("coverage_ratio"),
        } for c in components],
        "basin_series":basin,
    }
    OUTROOT.mkdir(parents=True,exist_ok=True)
    out=OUTROOT/f"{event_id}.json"
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return payload

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--events",default=",".join(DEFAULT_EVENTS))
    ap.add_argument("--max-workers",type=int,default=12)
    args=ap.parse_args()
    events=[x.strip() for x in args.events.split(",") if x.strip()]
    manifest=[]
    for event_id in events:
        p=build_event(event_id,max_workers=max(2,min(24,args.max_workers)))
        manifest.append({
            "event_id":event_id,
            "summary":p["summary"],
            "valid_rain_station_count":p["network"]["valid_rain_station_count"],
            "path":str((OUTROOT/f"{event_id}.json").relative_to(ROOT)),
        })
        print(json.dumps(manifest[-1],ensure_ascii=False),flush=True)
    OUTROOT.mkdir(parents=True,exist_ok=True)
    m={
        "schema_version":"g040_historical_antecedent_wetness_manifest_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "events":manifest,
        "future_event_rain_used":False,
    }
    (OUTROOT/"manifest_latest.json").write_text(
        json.dumps(m,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    return 0

if __name__=="__main__":
    raise SystemExit(main())
