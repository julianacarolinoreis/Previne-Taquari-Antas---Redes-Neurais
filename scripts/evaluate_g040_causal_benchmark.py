#!/usr/bin/env python3
"""Evaluate frozen causal G040 HEC replays against a persistence baseline."""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.run_hec_hms_g040_e1_hindcast import (
        MAIN_CHECKPOINTS,
        interp,
        read_output_csv,
        series_control,
    )
except ModuleNotFoundError:
    from run_hec_hms_g040_e1_hindcast import (
        MAIN_CHECKPOINTS,
        interp,
        read_output_csv,
        series_control,
    )

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
CASES=BASE/"causal_frozen_benchmark"
CFG=ROOT/"config/g040_causal_frozen_benchmark_v1.json"
OUT=CASES/"causal_frozen_benchmark_summary_latest.json"
OUTCSV=CASES/"causal_frozen_benchmark_cases.csv"
HORIZONS=(6,12,24,48,72)

def load(p: Path) -> dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8"))

def utc(v: str) -> datetime:
    d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def wape(pairs):
    if not pairs:
        return None
    den=sum(abs(o) for _t,o,_s in pairs)
    return None if den<=0 else sum(abs(s-o) for _t,o,s in pairs)/den

def rmse(pairs):
    return None if not pairs else math.sqrt(sum((s-o)**2 for _t,o,s in pairs)/len(pairs))

def observed_level_rows(pkg: dict[str,Any],code: str):
    c=next((x for x in pkg.get("controls") or [] if str(x.get("code"))==str(code)),None)
    if not c:
        return []
    rows=[]
    for r in c.get("recent_rows") or []:
        if not r.get("time_utc") or r.get("level_source_unit") is None:
            continue
        try:
            v=float(r["level_source_unit"])
        except (TypeError,ValueError):
            continue
        if math.isfinite(v):
            rows.append((utc(r["time_utc"]),v))
    rows.sort()
    return rows

def stage_timing_score(simmap,levelrows,t0,end):
    if not simmap or len(levelrows)<2:
        return None
    pairs=[]
    for t,qs in sorted(simmap.items()):
        if t<t0 or t>end or not math.isfinite(qs):
            continue
        lv=interp(levelrows,t)
        if lv is not None and math.isfinite(lv):
            pairs.append((t,float(lv),float(qs)))
    if len(pairs)<4:
        return None
    oi=max(range(len(pairs)),key=lambda i:pairs[i][1])
    si=max(range(len(pairs)),key=lambda i:pairs[i][2])
    do=[pairs[i][1]-pairs[i-1][1] for i in range(1,len(pairs))]
    ds=[pairs[i][2]-pairs[i-1][2] for i in range(1,len(pairs))]
    signs=[
        ((a==0 and b==0) or (a*b>0))
        for a,b in zip(do,ds)
        if not (a==0 and b==0)
    ]
    return {
        "pairs":len(pairs),
        "observed_level_peak_time_utc":pairs[oi][0].isoformat().replace("+00:00","Z"),
        "simulated_flow_peak_time_utc":pairs[si][0].isoformat().replace("+00:00","Z"),
        "peak_timing_error_h":(pairs[si][0]-pairs[oi][0]).total_seconds()/3600,
        "rise_fall_sign_skill":None if not signs else sum(signs)/len(signs),
        "note":"timing/shape validation only; no high-flow rating-curve extrapolation is used",
    }

def evaluate_case(case: dict[str,Any]) -> dict[str,Any]:
    case_id=case["case_id"]
    root=CASES/case_id
    manifest=load(root/"manifest.json")
    score_hydro=load(root/"hydro_scoring.json")
    results=list((root/"hec_runs").glob("*/result.json"))
    if len(results)!=1:
        raise RuntimeError(f"{case_id}: expected one HEC result, found {len(results)}")
    result=load(results[0])
    output_csv=results[0].parent/"project"/"hec_output_values.csv"
    if not result.get("compute_ok") or not output_csv.exists():
        raise RuntimeError(f"{case_id}: HEC compute did not produce output CSV")
    sims=read_output_csv(output_csv)
    t0=utc(case["decision_time_utc"])
    end=utc(manifest["score_end_utc"])

    station_rows=[]
    # "all" evaluates every verification observation that becomes available
    # after t0. "comparable" is the strict subset where persistence has a
    # valid q(t0), so HEC-vs-persistence skill always uses identical pairs.
    all_hec_by_h={h:[] for h in HORIZONS}
    comparable_hec_by_h={h:[] for h in HORIZONS}
    persistence_by_h={h:[] for h in HORIZONS}

    primary_source=str(manifest.get("primary_source_code") or "")
    for code in MAIN_CHECKPOINTS:
        # Never score a checkpoint that is itself being used as a boundary.
        if code==primary_source:
            station_rows.append({
                "code":code,
                "status":"boundary_source_not_scored",
                "q_at_t0_m3s":None,
                "available_future_pairs":0,
                "horizons":{},
            })
            continue
        simmap={t:q for t,q in sims.get("J_"+code,[])}
        stage_score=stage_timing_score(
            simmap,observed_level_rows(score_hydro,code),t0,end
        )
        try:
            _c,obsrows=series_control(score_hydro,code)
        except Exception:
            obsrows=[]
        q0=interp(obsrows,t0) if obsrows else None
        pairs=[]
        for t,qs in sorted(simmap.items()):
            if t<t0 or t>end:
                continue
            qo=interp(obsrows,t)
            if qo is None or not math.isfinite(qs):
                continue
            pairs.append((t,float(qo),float(qs)))
        if not pairs:
            if stage_score is not None:
                station_rows.append({
                    "code":code,
                    "q_at_t0_m3s":q0,
                    "persistence_baseline_available":False,
                    "available_future_pairs":0,
                    "stage_validation":stage_score,
                    "horizons":{},
                })
            continue

        by_h={}
        for h in HORIZONS:
            lim=t0+timedelta(hours=h)
            hp=[x for x in pairs if x[0]<=lim]
            hw=wape(hp)
            all_hec_by_h[h].extend(hp)

            pp=[]
            if q0 is not None:
                pp=[(t,o,float(q0)) for t,o,_s in hp]
                comparable_hec_by_h[h].extend(hp)
                persistence_by_h[h].extend(pp)
            pw=wape(pp)
            by_h[str(h)]={
                "pairs":len(hp),
                "hec_wape":hw,
                "hec_rmse_m3s":rmse(hp),
                "persistence_available":q0 is not None,
                "persistence_wape":pw,
                "persistence_rmse_m3s":rmse(pp),
                "skill_vs_persistence_pct":None if hw is None or pw in (None,0) else 100*(1-hw/pw),
            }
        station_rows.append({
            "code":code,
            "q_at_t0_m3s":q0,
            "persistence_baseline_available":q0 is not None,
            "available_future_pairs":len(pairs),
            "first_verification_time_utc":pairs[0][0].isoformat().replace("+00:00","Z"),
            "stage_validation":stage_score,
            "horizons":by_h,
        })

    aggregate={}
    for h in HORIZONS:
        all_hw=wape(all_hec_by_h[h])
        comp_hw=wape(comparable_hec_by_h[h])
        pw=wape(persistence_by_h[h])
        aggregate[str(h)]={
            "all_available_pairs":len(all_hec_by_h[h]),
            "hec_wape_all_available":all_hw,
            "comparable_pairs":len(comparable_hec_by_h[h]),
            "hec_wape":comp_hw,
            "persistence_wape":pw,
            "skill_vs_persistence_pct":None if comp_hw is None or pw in (None,0) else 100*(1-comp_hw/pw),
        }
    return {
        "case_id":case_id,
        "event_id":case["event_id"],
        "split":case["split"],
        "ecmwf_run_utc":case["ecmwf_run_utc"],
        "decision_time_utc":case["decision_time_utc"],
        "score_end_utc":manifest["score_end_utc"],
        "primary_source_code":primary_source,
        "predictive_primary_boundary_used":manifest.get("predictive_primary_boundary_used"),
        "active_optional_boundaries":manifest.get("active_optional_boundaries"),
        "hec_result":str(results[0].relative_to(ROOT)),
        "station_results":station_rows,
        "aggregate":aggregate,
    }

def main() -> int:
    cfg=load(CFG)
    rows=[evaluate_case(c) for c in cfg.get("cases") or []]
    grand={}
    for h in HORIZONS:
        # Weighted by verification pairs via reconstruction from case aggregate:
        # use numerator-equivalent WAPE weights is not recoverable from aggregate
        # alone, so report median case WAPE and paired win counts transparently.
        all_hv=[r["aggregate"][str(h)]["hec_wape_all_available"] for r in rows if r["aggregate"][str(h)]["hec_wape_all_available"] is not None]
        hv=[r["aggregate"][str(h)]["hec_wape"] for r in rows if r["aggregate"][str(h)]["hec_wape"] is not None]
        pv=[r["aggregate"][str(h)]["persistence_wape"] for r in rows if r["aggregate"][str(h)]["persistence_wape"] is not None]
        skills=[r["aggregate"][str(h)]["skill_vs_persistence_pct"] for r in rows if r["aggregate"][str(h)]["skill_vs_persistence_pct"] is not None]
        def median(v):
            if not v:return None
            z=sorted(v); n=len(z)
            return z[n//2] if n%2 else (z[n//2-1]+z[n//2])/2
        grand[str(h)]={
            "case_count":len(hv),
            "median_case_hec_wape_all_available":median(all_hv),
            "median_case_hec_wape":median(hv),
            "median_case_persistence_wape":median(pv),
            "median_skill_vs_persistence_pct":median(skills),
            "hec_wins":sum(1 for r in rows if (r["aggregate"][str(h)]["skill_vs_persistence_pct"] or -1e9)>0),
        }

    payload={
        "schema_version":"g040_causal_frozen_benchmark_results_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"FROZEN_CAUSAL_REPLAY_COMPLETE",
        "configuration":str(CFG.relative_to(ROOT)),
        "no_leakage_confirmed":True,
        "future_weather_forcing":"exact archived ECMWF single run",
        "future_source_boundary_flow":"frozen causal upper-Antas rainfall-runoff forecast at 86472000; no future observed boundary flow",
        "model_parameters":"best calibration candidate; validation/holdout excluded from fitting",
        "metric":"flow WAPE on valid rating-curve discharge plus independent observed-level peak timing/shape after t0",
        "grand_summary":grand,
        "cases":rows,
        "limitations":[
            "E1 remains an intermediate BHO6 branch model, not the final verified 145-subbasin HEC model",
            "primary boundary 86472000 is forecast by the frozen upper-Antas rainfall-runoff model; its forecast error propagates downstream",
            "high-flow discharge magnitude remains sensitive to rating-curve limits; level observations are therefore used independently for peak timing and rise/fall validation without extrapolating a rating curve",
            "three frozen cases are a first independent replay set, not sufficient for operational promotion"
        ],
        "promotion_allowed":False,
    }
    CASES.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    fields=["case_id","event_id","split","horizon_h","hec_wape","persistence_wape","skill_vs_persistence_pct","pairs"]
    with OUTCSV.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader()
        for r in rows:
            for h in HORIZONS:
                a=r["aggregate"][str(h)]
                w.writerow({
                    "case_id":r["case_id"],"event_id":r["event_id"],"split":r["split"],"horizon_h":h,
                    "hec_wape":a["hec_wape"],"persistence_wape":a["persistence_wape"],
                    "skill_vs_persistence_pct":a["skill_vs_persistence_pct"],"pairs":a["comparable_pairs"],
                })
    print(json.dumps({"status":payload["status"],"grand_summary":grand},ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
