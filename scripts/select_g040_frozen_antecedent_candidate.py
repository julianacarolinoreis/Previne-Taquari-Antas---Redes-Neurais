#!/usr/bin/env python3
"""Frozen antecedent-wetness selector for G040 causal HEC replays.

Only calibration donors E22_SEP2023 and E24_NOV2023 may influence selection.
Validation/holdout events contribute strictly pre-event rainfall state only.
No future rainfall, future discharge, or target-event fit metric is used.
"""
from __future__ import annotations
import argparse, json, math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
CAL=BASE/"g040_e1_multievent_calibration_latest.json"
ANT=BASE/"historical_antecedent_wetness"
OUT=BASE/"g040_frozen_antecedent_selection_latest.json"
DONORS=("E22_SEP2023","E24_NOV2023")
TARGETS=("E27_MAY2024","E28_JUN2024","E2026_JUL")
FEATURES=("rain_24h_mm","rain_72h_mm","rain_168h_mm","api_tau_72h_mm")

def load(p:Path)->dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8"))

def event_summary(eid:str)->dict[str,float|None]:
    p=ANT/f"{eid}.json"
    if not p.exists():
        raise FileNotFoundError(f"missing antecedent wetness: {p}")
    j=load(p)
    if not (j.get("window") or {}).get("strictly_pre_event"):
        raise RuntimeError(f"{eid}: antecedent window is not strictly pre-event")
    if (j.get("method") or {}).get("future_event_rain_used") is not False:
        raise RuntimeError(f"{eid}: future event rain entered antecedent state")
    s=j.get("summary") or {}
    return {k:(None if s.get(k) is None else float(s[k])) for k in FEATURES}

def donor_candidate(event_id:str)->dict[str,Any]:
    cal=load(CAL)
    choices=[]
    for row in cal.get("ranked_candidates") or []:
        ev=next((e for e in (row.get("events") or []) if str(e.get("event_id"))==event_id),None)
        if not ev or not ev.get("compute_ok"):
            continue
        n=int(ev.get("valid_checkpoint_count") or 0)
        if n<1:
            continue
        pen=ev.get("mean_multi_metric_penalty")
        if pen is None:
            continue
        choices.append({
            "candidate_id":row.get("candidate_id"),
            "parameters":row.get("parameters"),
            "checkpoint_gate_pass_count":int(ev.get("checkpoint_gate_pass_count") or 0),
            "valid_checkpoint_count":n,
            "mean_multi_metric_penalty":float(pen),
        })
    if not choices:
        raise RuntimeError(f"{event_id}: no donor candidate")
    # Prefer more physically acceptable checkpoints; penalty breaks ties.
    choices.sort(key=lambda x:(-x["checkpoint_gate_pass_count"],x["mean_multi_metric_penalty"]))
    return choices[0]

def distance(a:dict[str,float|None],b:dict[str,float|None])->tuple[float,dict[str,float]]:
    parts={}
    for k in FEATURES:
        x=a.get(k); y=b.get(k)
        if x is None or y is None:
            continue
        # log1p makes wet/dry ratios comparable across 24 h, 7 d and API scales.
        parts[k]=abs(math.log1p(max(x,0.0))-math.log1p(max(y,0.0)))
    if len(parts)<3:
        raise RuntimeError(f"insufficient antecedent features: {sorted(parts)}")
    return sum(parts.values())/len(parts),parts

def build(targets:list[str])->dict[str,Any]:
    donor_state={eid:event_summary(eid) for eid in DONORS}
    donor_models={eid:donor_candidate(eid) for eid in DONORS}
    selections=[]
    for target in targets:
        if target in DONORS:
            raise RuntimeError("target event cannot also be a donor")
        ts=event_summary(target)
        ranked=[]
        for donor in DONORS:
            d,parts=distance(ts,donor_state[donor])
            ranked.append({
                "donor_event_id":donor,
                "distance":d,
                "feature_distance":parts,
                "antecedent":donor_state[donor],
                **donor_models[donor],
            })
        ranked.sort(key=lambda x:x["distance"])
        best=ranked[0]
        selections.append({
            "target_event_id":target,
            "target_antecedent":ts,
            "selected_donor_event_id":best["donor_event_id"],
            "selected_candidate_id":best["candidate_id"],
            "selected_parameters":best["parameters"],
            "distance":best["distance"],
            "ranked_donors":ranked,
            "selection_uses_target_fit_metrics":False,
            "selection_uses_future_event_rain":False,
            "selection_uses_future_discharge":False,
        })
    return {
        "schema_version":"g040_frozen_antecedent_selection_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"FROZEN_ANTECEDENT_SELECTION_READY",
        "donor_events":list(DONORS),
        "forbidden_selection_events":list(TARGETS),
        "features":list(FEATURES),
        "distance":"mean absolute difference in log1p antecedent-rain features",
        "candidate_choice_within_donor":"maximize checkpoint gate passes, then minimize donor-event mean multi-metric penalty",
        "selections":selections,
        "no_validation_leakage":True,
        "promotion_allowed":False,
    }

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--events",default=",".join(TARGETS))
    ap.add_argument("--output",type=Path,default=OUT)
    args=ap.parse_args()
    targets=[x.strip() for x in args.events.split(",") if x.strip()]
    out=build(targets)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":out["status"],
        "selections":[{
            "target_event_id":x["target_event_id"],
            "donor":x["selected_donor_event_id"],
            "candidate":x["selected_candidate_id"],
            "distance":x["distance"],
        } for x in out["selections"]],
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
