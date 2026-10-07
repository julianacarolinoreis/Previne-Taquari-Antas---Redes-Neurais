#!/usr/bin/env python3
"""Curve-independent level validation for frozen causal G040 HEC replays.

HEC-HMS produces discharge at mainstem checkpoints. During disaster-stage
events, high-flow rating curves at some checkpoints are outside their reliable
measurement range. This evaluator therefore does NOT extrapolate a rating curve
to turn simulated Q into stage.

Instead it evaluates information that remains physically interpretable without
a Q->stage conversion:
- timing of the modeled discharge peak versus observed stage peak;
- monotonic shape agreement (Spearman correlation Qsim x observed stage);
- rise/fall sign agreement;
- min-max normalized hydrograph shape error.

Observed stage remains in the ANA/SGB source unit. No assumption that it is cm
or m is made here. Research only; not an operational warning product.
"""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.run_hec_hms_g040_e1_hindcast import read_output_csv, interp
except ModuleNotFoundError:
    from run_hec_hms_g040_e1_hindcast import read_output_csv, interp

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
CASES=BASE/"causal_frozen_benchmark"
CFG=ROOT/"config/g040_causal_frozen_benchmark_v1.json"
OUT=CASES/"causal_level_validation_latest.json"
OUTCSV=CASES/"causal_level_validation.csv"
CHECKPOINTS=("86510000","86720000","86743000","86879000","86879300","86895000")
HORIZONS=(6,12,24,48,72)
PEAK_TIME_ACCEPT_H=3.0

def load(path: Path) -> dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def utc(value: str) -> datetime:
    d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def finite(value: Any) -> float|None:
    try:
        x=float(value)
    except (TypeError,ValueError):
        return None
    return x if math.isfinite(x) else None

def station_level_rows(hydro: dict[str,Any], code: str) -> list[tuple[datetime,float]]:
    control=next((c for c in hydro.get("controls") or [] if str(c.get("code"))==code),None)
    if control is None:
        return []
    rows=[]
    for r in control.get("recent_rows") or []:
        if not r.get("time_utc"):
            continue
        n=finite(r.get("level_source_unit"))
        if n is None:
            continue
        rows.append((utc(r["time_utc"]),n))
    rows.sort()
    return rows

def _corr(a: list[float], b: list[float]) -> float|None:
    if len(a)<2 or len(a)!=len(b):
        return None
    ma=sum(a)/len(a); mb=sum(b)/len(b)
    da=[x-ma for x in a]; db=[x-mb for x in b]
    den=math.sqrt(sum(x*x for x in da)*sum(x*x for x in db))
    return None if den<=0 else sum(x*y for x,y in zip(da,db))/den

def _ranks(values: list[float]) -> list[float]:
    indexed=sorted(enumerate(values),key=lambda x:x[1])
    ranks=[0.0]*len(values)
    i=0
    while i<len(indexed):
        j=i+1
        while j<len(indexed) and indexed[j][1]==indexed[i][1]:
            j+=1
        rank=(i+1+j)/2.0
        for k in range(i,j):
            ranks[indexed[k][0]]=rank
        i=j
    return ranks

def spearman(a: list[float], b: list[float]) -> float|None:
    if len(a)<3 or len(a)!=len(b):
        return None
    return _corr(_ranks(a),_ranks(b))

def minmax(values: list[float]) -> list[float]|None:
    if not values:
        return None
    lo=min(values); hi=max(values)
    if hi<=lo:
        return None
    return [(x-lo)/(hi-lo) for x in values]

def shape_rmse(a: list[float],b: list[float]) -> float|None:
    aa=minmax(a); bb=minmax(b)
    if aa is None or bb is None or len(aa)!=len(bb):
        return None
    return math.sqrt(sum((x-y)**2 for x,y in zip(aa,bb))/len(aa))

def sign_skill(a: list[float],b: list[float]) -> float|None:
    if len(a)<2 or len(a)!=len(b):
        return None
    da=[a[i]-a[i-1] for i in range(1,len(a))]
    db=[b[i]-b[i-1] for i in range(1,len(b))]
    if not da:
        return None
    hits=0
    for x,y in zip(da,db):
        if (x==0 and y==0) or x*y>0:
            hits+=1
    return hits/len(da)

def median(values):
    z=sorted(x for x in values if x is not None)
    if not z:
        return None
    n=len(z)
    return z[n//2] if n%2 else (z[n//2-1]+z[n//2])/2

def evaluate_case(case: dict[str,Any]) -> dict[str,Any]:
    cid=case["case_id"]
    root=CASES/cid
    score=load(root/"hydro_scoring.json")
    results=list((root/"hec_runs").glob("*/result.json"))
    if len(results)!=1:
        raise RuntimeError(f"{cid}: expected one HEC result, found {len(results)}")
    result=load(results[0])
    output_csv=results[0].parent/"project"/"hec_output_values.csv"
    if not result.get("compute_ok") or not output_csv.exists():
        raise RuntimeError(f"{cid}: HEC output missing")
    sims=read_output_csv(output_csv)
    t0=utc(case["decision_time_utc"])

    stations=[]
    for code in CHECKPOINTS:
        obs=station_level_rows(score,code)
        sim=sims.get("J_"+code) or []
        horizons={}
        for h in HORIZONS:
            end=t0+timedelta(hours=h)
            pairs=[]
            for t,n in obs:
                if t<t0 or t>end:
                    continue
                q=interp(sim,t)
                if q is None or not math.isfinite(float(q)):
                    continue
                pairs.append((t,float(n),float(q)))
            if len(pairs)<4:
                horizons[str(h)]={
                    "pairs":len(pairs),
                    "status":"insufficient_stage_pairs",
                    "rating_curve_used":False,
                }
                continue
            tt=[x[0] for x in pairs]
            nn=[x[1] for x in pairs]
            qq=[x[2] for x in pairs]
            oi=max(range(len(nn)),key=lambda i:nn[i])
            si=max(range(len(qq)),key=lambda i:qq[i])
            lag=(tt[si]-tt[oi]).total_seconds()/3600.0
            horizons[str(h)]={
                "pairs":len(pairs),
                "status":"curve_independent_level_validation",
                "rating_curve_used":False,
                "observed_stage_peak_source_unit":nn[oi],
                "observed_stage_peak_time_utc":tt[oi].isoformat().replace("+00:00","Z"),
                "simulated_q_peak_m3s":qq[si],
                "simulated_q_peak_time_utc":tt[si].isoformat().replace("+00:00","Z"),
                "peak_timing_error_h":lag,
                "peak_timing_within_3h":abs(lag)<=PEAK_TIME_ACCEPT_H,
                "spearman_qsim_vs_stage":spearman(qq,nn),
                "rise_fall_sign_skill":sign_skill(qq,nn),
                "normalized_shape_rmse":shape_rmse(qq,nn),
            }
        stations.append({"code":code,"horizons":horizons})

    return {
        "case_id":cid,
        "event_id":case["event_id"],
        "split":case["split"],
        "decision_time_utc":case["decision_time_utc"],
        "stations":stations,
    }

def main() -> int:
    cfg=load(CFG)
    cases=[evaluate_case(c) for c in cfg.get("cases") or []]

    flat=[]
    for case in cases:
        for st in case["stations"]:
            for h in HORIZONS:
                m=st["horizons"][str(h)]
                if m.get("status")!="curve_independent_level_validation":
                    continue
                flat.append({
                    "case_id":case["case_id"],
                    "event_id":case["event_id"],
                    "split":case["split"],
                    "code":st["code"],
                    "horizon_h":h,
                    **{k:m.get(k) for k in (
                        "pairs","observed_stage_peak_source_unit",
                        "observed_stage_peak_time_utc","simulated_q_peak_m3s",
                        "simulated_q_peak_time_utc","peak_timing_error_h",
                        "peak_timing_within_3h","spearman_qsim_vs_stage",
                        "rise_fall_sign_skill","normalized_shape_rmse"
                    )},
                })

    summary={}
    for h in HORIZONS:
        rows=[r for r in flat if r["horizon_h"]==h]
        summary[str(h)]={
            "station_case_count":len(rows),
            "median_abs_peak_timing_error_h":median([abs(r["peak_timing_error_h"]) for r in rows]),
            "peak_timing_within_3h_count":sum(bool(r["peak_timing_within_3h"]) for r in rows),
            "median_spearman_qsim_vs_stage":median([r["spearman_qsim_vs_stage"] for r in rows]),
            "median_rise_fall_sign_skill":median([r["rise_fall_sign_skill"] for r in rows]),
            "median_normalized_shape_rmse":median([r["normalized_shape_rmse"] for r in rows]),
        }

    payload={
        "schema_version":"g040_causal_level_validation_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"CURVE_INDEPENDENT_LEVEL_VALIDATION_COMPLETE",
        "purpose":"validate flood-wave timing/shape against observed stage without extrapolating high-flow rating curves",
        "rating_curve_used":False,
        "stage_unit_policy":"preserve ANA/SGB level_source_unit exactly; no implicit cm/m conversion",
        "interpretation":{
            "peak_timing_error_h":"modeled-Q peak time minus observed-stage peak time",
            "spearman_qsim_vs_stage":"monotonic wave-shape agreement; amplitude units intentionally ignored",
            "rise_fall_sign_skill":"fraction of paired steps with matching rise/fall direction",
            "normalized_shape_rmse":"min-max normalized Qsim versus observed stage; shape only",
        },
        "summary":summary,
        "cases":cases,
        "limitations":[
            "This does not estimate stage amplitude from HEC discharge.",
            "It does not validate a rating curve outside measured range.",
            "Backwater/hydraulic effects require HEC-RAS or another locally validated hydraulic relation.",
            "Three frozen cases remain insufficient for operational promotion."
        ],
        "promotion_allowed":False,
    }
    CASES.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fields=[
        "case_id","event_id","split","code","horizon_h","pairs",
        "observed_stage_peak_source_unit","observed_stage_peak_time_utc",
        "simulated_q_peak_m3s","simulated_q_peak_time_utc",
        "peak_timing_error_h","peak_timing_within_3h",
        "spearman_qsim_vs_stage","rise_fall_sign_skill","normalized_shape_rmse",
    ]
    with OUTCSV.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader()
        for row in flat:
            w.writerow(row)
    print(json.dumps({"status":payload["status"],"summary":summary},ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
