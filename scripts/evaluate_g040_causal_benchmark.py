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
    aggregate_by_h={h:[] for h in HORIZONS}
    persistence_by_h={h:[] for h in HORIZONS}
    for code in MAIN_CHECKPOINTS:
        try:
            _c,obsrows=series_control(score_hydro,code)
        except Exception:
            continue
        q0=interp(obsrows,t0)
        if q0 is None:
            continue
        simmap={t:q for t,q in sims.get("J_"+code,[])}
        pairs=[]
        ppairs=[]
        for t,qs in sorted(simmap.items()):
            if t<t0 or t>end:
                continue
            qo=interp(obsrows,t)
            if qo is None or not math.isfinite(qs):
                continue
            pairs.append((t,float(qo),float(qs)))
            ppairs.append((t,float(qo),float(q0)))
        if not pairs:
            continue
        by_h={}
        for h in HORIZONS:
            lim=t0+timedelta(hours=h)
            hp=[x for x in pairs if x[0]<=lim]
            pp=[x for x in ppairs if x[0]<=lim]
            hw=wape(hp); pw=wape(pp)
            by_h[str(h)]={
                "pairs":len(hp),
                "hec_wape":hw,
                "persistence_wape":pw,
                "hec_rmse_m3s":rmse(hp),
                "persistence_rmse_m3s":rmse(pp),
                "skill_vs_persistence_pct":None if hw is None or pw in (None,0) else 100*(1-hw/pw),
            }
            aggregate_by_h[h].extend(hp)
            persistence_by_h[h].extend(pp)
        station_rows.append({
            "code":code,
            "q_at_t0_m3s":q0,
            "available_future_pairs":len(pairs),
            "horizons":by_h,
        })

    aggregate={}
    for h in HORIZONS:
        hw=wape(aggregate_by_h[h]); pw=wape(persistence_by_h[h])
        aggregate[str(h)]={
            "pairs":len(aggregate_by_h[h]),
            "hec_wape":hw,
            "persistence_wape":pw,
            "skill_vs_persistence_pct":None if hw is None or pw in (None,0) else 100*(1-hw/pw),
        }
    return {
        "case_id":case_id,
        "event_id":case["event_id"],
        "split":case["split"],
        "ecmwf_run_utc":case["ecmwf_run_utc"],
        "decision_time_utc":case["decision_time_utc"],
        "score_end_utc":manifest["score_end_utc"],
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
        hv=[r["aggregate"][str(h)]["hec_wape"] for r in rows if r["aggregate"][str(h)]["hec_wape"] is not None]
        pv=[r["aggregate"][str(h)]["persistence_wape"] for r in rows if r["aggregate"][str(h)]["persistence_wape"] is not None]
        skills=[r["aggregate"][str(h)]["skill_vs_persistence_pct"] for r in rows if r["aggregate"][str(h)]["skill_vs_persistence_pct"] is not None]
        def median(v):
            if not v:return None
            z=sorted(v); n=len(z)
            return z[n//2] if n%2 else (z[n//2-1]+z[n//2])/2
        grand[str(h)]={
            "case_count":len(hv),
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
        "future_source_boundary_flow":"persistence from last observation at t0",
        "model_parameters":"best calibration candidate; validation/holdout excluded from fitting",
        "metric":"WAPE = sum(|forecast-observed|)/sum(|observed|), evaluated only after t0",
        "grand_summary":grand,
        "cases":rows,
        "limitations":[
            "E1 remains an intermediate BHO6 branch model, not the final verified 145-subbasin HEC model",
            "boundary discharge after t0 is persisted; a future upstream-flow forecast model may improve or worsen results",
            "high-flow discharge verification remains sensitive to rating-curve limits; disaster-stage validation must also be performed in level",
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
                    "skill_vs_persistence_pct":a["skill_vs_persistence_pct"],"pairs":a["pairs"],
                })
    print(json.dumps({"status":payload["status"],"grand_summary":grand},ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
