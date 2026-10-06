#!/usr/bin/env python3
"""Build one causal G040 replay package from observed history + exact ECMWF run.

Causality rules:
- observed component rainfall is used only through t0;
- exact archived ECMWF rainfall is used strictly after t0;
- observed Source discharge is used only through t0;
- Source discharge after t0 is persisted from the last observation, never read
  from the verifying future hydrograph;
- untouched future hydrograph is kept as a separate score-only artifact.

The output is compatible with run_hec_hms_g040_e1_hindcast.py.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
CONFIG=ROOT/"config/g040_causal_frozen_benchmark_v1.json"
OBSROOT=BASE/"historical_calibration_forcing"
OUTROOT=BASE/"causal_frozen_benchmark"
BRT=timezone(timedelta(hours=-3))
PRIMARY="86472000"
OPTIONAL=("86500000","86595000","86746000")
MIN_FLOW_HOURS=18

def load(path: Path) -> dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def utc(value: str) -> datetime:
    d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def local_rain_time(value: str) -> datetime:
    d=datetime.fromisoformat(str(value))
    if d.tzinfo is None:
        d=d.replace(tzinfo=BRT)
    return d.astimezone(timezone.utc)

def iso_utc(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def iso_local(d: datetime) -> str:
    return d.astimezone(BRT).replace(tzinfo=None).isoformat(timespec="minutes")

def floor_hour(d: datetime) -> datetime:
    return d.replace(minute=0,second=0,microsecond=0)

def hourly_axis(start: datetime,end: datetime) -> list[datetime]:
    start=floor_hour(start); end=floor_hour(end)
    out=[]; t=start
    while t<=end:
        out.append(t); t+=timedelta(hours=1)
    return out

def case_config(case_id: str) -> tuple[dict[str,Any],dict[str,Any]]:
    cfg=load(CONFIG)
    case=next((x for x in cfg.get("cases") or [] if x.get("case_id")==case_id),None)
    if not case:
        raise KeyError(f"unknown case_id {case_id}")
    return cfg,case

def flow_hour_count(control: dict[str,Any],t0: datetime) -> int:
    seen=set()
    lo=t0-timedelta(hours=24)
    for r in control.get("recent_rows") or []:
        if r.get("flow_m3s") is None or not r.get("time_utc"):
            continue
        t=utc(r["time_utc"])
        if lo<=t<=t0:
            seen.add(floor_hour(t))
    return len(seen)

def last_flow(control: dict[str,Any],t0: datetime) -> tuple[datetime,float]|None:
    rows=[]
    for r in control.get("recent_rows") or []:
        if r.get("flow_m3s") is None or not r.get("time_utc"):
            continue
        t=utc(r["time_utc"])
        q=float(r["flow_m3s"])
        if t<=t0 and math.isfinite(q) and q>=0:
            rows.append((t,q))
    return max(rows,key=lambda x:x[0]) if rows else None

def active_sources(hydro: dict[str,Any],t0: datetime) -> tuple[list[str],dict[str,Any]]:
    by={str(c.get("code")):c for c in hydro.get("controls") or []}
    if PRIMARY not in by or last_flow(by[PRIMARY],t0) is None:
        raise RuntimeError(f"primary source {PRIMARY} has no observed flow at/before t0")
    active=[]
    audit={}
    for code in OPTIONAL:
        c=by.get(code) or {}
        n=flow_hour_count(c,t0)
        lf=last_flow(c,t0)
        ok=n>=MIN_FLOW_HOURS and lf is not None
        audit[code]={
            "observed_flow_hours_last_24h":n,
            "minimum_required":MIN_FLOW_HOURS,
            "last_observation_utc":iso_utc(lf[0]) if lf else None,
            "eligible":ok,
        }
        if ok:
            active.append(code)
    return active,audit

def build_causal_hydro(hydro: dict[str,Any],t0: datetime,end: datetime,active: list[str]) -> dict[str,Any]:
    sources={PRIMARY,*active}
    controls=[]
    for c in hydro.get("controls") or []:
        code=str(c.get("code") or "")
        kept=[]
        for r in c.get("recent_rows") or []:
            if not r.get("time_utc"):
                continue
            t=utc(r["time_utc"])
            if t<=t0:
                kept.append(dict(r))
        if code in sources:
            lf=last_flow(c,t0)
            if lf is None:
                raise RuntimeError(f"{code}: no flow to persist at t0")
            last_t,last_q=lf
            # Explicit t0 anchor avoids any interpolation through future truth.
            if not any(r.get("time_utc") and utc(r["time_utc"])==t0 and r.get("flow_m3s") is not None for r in kept):
                kept.append({"time_utc":iso_utc(t0),"flow_m3s":last_q,"level_source_unit":None})
            t=floor_hour(t0)+timedelta(hours=1)
            while t<=end:
                kept.append({"time_utc":iso_utc(t),"flow_m3s":last_q,"level_source_unit":None})
                t+=timedelta(hours=1)
        kept.sort(key=lambda r:utc(r["time_utc"]))
        controls.append({**{k:v for k,v in c.items() if k!="recent_rows"},"recent_rows":kept})
    return {
        "schema_version":"g040_causal_hydro_forcing_v1",
        "event_id":hydro.get("event_id"),
        "research_only":True,
        "source":hydro.get("source"),
        "decision_time_utc":iso_utc(t0),
        "future_boundary_policy":"last observation persisted after t0",
        "future_observed_discharge_used":False,
        "controls":controls,
    }

def component_maps(pkg: dict[str,Any], forecast: bool) -> dict[str,dict[datetime,float]]:
    out={}
    for c in pkg.get("components") or []:
        m={}
        for r in c.get("series") or []:
            if r.get("mm") is None:
                continue
            key="time_utc" if forecast else "time_local"
            if not r.get(key):
                continue
            t=utc(r[key]) if forecast else local_rain_time(r[key])
            m[floor_hour(t)]=float(r["mm"])
        out[str(c.get("component_id"))]=m
    return out

def build_causal_rain(
    observed: dict[str,Any],
    forecast: dict[str,Any],
    t0: datetime,
    end: datetime,
    active: list[str],
    scenario_name: str,
) -> dict[str,Any]:
    om=component_maps(observed,False)
    fm=component_maps(forecast,True)
    obs_components={str(c.get("component_id")):c for c in observed.get("components") or []}
    fc_components={str(c.get("component_id")):c for c in forecast.get("components") or []}
    ids=sorted(set(obs_components)&set(fc_components))
    if len(ids)!=11:
        raise RuntimeError(f"expected 11 shared hydrologic components, found {len(ids)}")
    starts=[]
    for cid in ids:
        if om.get(cid):
            starts.append(min(om[cid]))
    if len(starts)!=len(ids):
        raise RuntimeError("one or more observed components have no rainfall rows")
    start=max(starts)
    axis=hourly_axis(start,end)
    active_set=set(active)
    components=[]
    for cid in ids:
        meta=obs_components[cid]
        branch=cid.replace("BRANCH_","",1) if cid.startswith("BRANCH_") else None
        used=not branch or branch not in active_set
        rows=[]
        missing=[]
        for t in axis:
            if t<=t0:
                mm=(om.get(cid) or {}).get(t)
                source="observed"
            else:
                mm=(fm.get(cid) or {}).get(t)
                source="ecmwf_exact_single_run"
            if mm is None and used:
                missing.append(iso_utc(t))
            rows.append({
                "time_local":iso_local(t),
                "mm":None if mm is None else round(float(mm),4),
                "source":source,
            })
        if missing:
            raise RuntimeError(f"{cid}: causal rain has {len(missing)} missing used hours; first={missing[0]}")
        components.append({
            "component_id":cid,
            "component_type":meta.get("component_type"),
            "tributary_boundary_code":branch,
            "used_as_rainfall_runoff_in_current_scenario":used,
            "support_area_km2":float(meta.get("support_area_km2") or fc_components[cid].get("support_area_km2") or 0),
            "expected_hours":len(axis),
            "available_hours":sum(r["mm"] is not None for r in rows),
            "coverage_ratio":sum(r["mm"] is not None for r in rows)/len(rows),
            "series":rows,
        })
    return {
        "schema_version":"g040_causal_rain_forcing_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"CAUSAL_FORECAST_RAIN_READY",
        "decision_time_utc":iso_utc(t0),
        "transition":{
            "observed_through_utc":iso_utc(t0),
            "forecast_strictly_after_utc":iso_utc(t0),
            "future_observed_rain_used":False,
            "missing_zero_filled":False,
        },
        "forecast_source":forecast.get("source"),
        "window":{
            "start_utc":iso_utc(axis[0]),
            "end_utc":iso_utc(axis[-1]),
            "hours":len(axis),
        },
        "boundary_scenario":{"name":scenario_name,"active_boundary_codes":sorted(active)},
        "components":components,
    }

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--case-id",required=True)
    ap.add_argument("--forecast-file",type=Path,required=True)
    args=ap.parse_args()
    cfg,case=case_config(args.case_id)
    event=str(case["event_id"])
    t0=utc(case["decision_time_utc"])
    run=utc(case["ecmwf_run_utc"])
    lag=(t0-run).total_seconds()/3600
    if abs(lag-float(cfg["ecmwf_availability_lag_hours"]))>1e-6:
        raise RuntimeError("decision time does not match frozen ECMWF availability lag")
    horizon=int(cfg["forecast_horizon_hours"])
    end=t0+timedelta(hours=horizon)

    d=OBSROOT/event
    observed=load(d/"rain.json")
    score_hydro=load(d/"hydro.json")
    forecast=load(args.forecast_file)
    if forecast.get("status")!="EXACT_ECMWF_SINGLE_RUN_READY":
        raise RuntimeError("exact ECMWF forecast package is not ready")
    if utc((forecast.get("source") or {}).get("run_initialization_utc"))!=run:
        raise RuntimeError("forecast run does not match frozen case")

    active,audit=active_sources(score_hydro,t0)
    scenario_name=f"causal_{args.case_id}"
    causal_hydro=build_causal_hydro(score_hydro,t0,end,active)
    causal_rain=build_causal_rain(observed,forecast,t0,end,active,scenario_name)
    scenario={
        "schema_version":"g040_causal_boundary_scenario_v1",
        "research_only":True,
        "current_scenario":scenario_name,
        "current":{
            "name":scenario_name,
            "active_boundary_codes":sorted(active),
            "selection_time_utc":iso_utc(t0),
            "selection_uses_future_observations":False,
        },
    }

    out=OUTROOT/args.case_id
    out.mkdir(parents=True,exist_ok=True)
    (out/"rain.json").write_text(json.dumps(causal_rain,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"hydro_forcing.json").write_text(json.dumps(causal_hydro,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"hydro_scoring.json").write_text(json.dumps(score_hydro,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"scenario.json").write_text(json.dumps(scenario,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    manifest={
        "schema_version":"g040_causal_case_manifest_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "case":case,
        "score_end_utc":iso_utc(end),
        "active_optional_boundaries":active,
        "boundary_eligibility_audit":audit,
        "causality_gates":{
            "future_observed_rain_used":False,
            "future_observed_boundary_flow_used":False,
            "target_future_observations_separate_score_file":True,
            "parameters_frozen_before_validation":True,
            "ecmwf_run_explicit":True,
        },
        "files":{
            "rain":"rain.json",
            "hydro_forcing":"hydro_forcing.json",
            "hydro_scoring":"hydro_scoring.json",
            "scenario":"scenario.json",
        },
    }
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":"G040_CAUSAL_CASE_READY",
        "case_id":args.case_id,
        "event_id":event,
        "decision_time_utc":iso_utc(t0),
        "score_end_utc":iso_utc(end),
        "active_optional_boundaries":active,
        "rain_hours":causal_rain["window"]["hours"],
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
