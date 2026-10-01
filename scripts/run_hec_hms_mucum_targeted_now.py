#!/usr/bin/env python3
"""Targeted live HEC-HMS search for the current Muçum rising limb.

Uses the existing full-basin observed-rain warm-up from 26/09 and latest IFS.
Research only; does not apply a visual stage shift.
"""
from __future__ import annotations
import csv, json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import calibrate_hec_hms_live_event as cal

OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
OUT_JSON=OUT/"hec_hms_targeted_now_latest.json"
OUT_CSV=OUT/"hec_hms_targeted_now_candidates.csv"
CANONICAL=OUT/"hec_hms_spatial_forecast_mucum_latest.json"
CANONICAL_SERIES=OUT/"hec_hms_spatial_forecast_mucum"/"primary_series.csv"

CANDIDATES=[
 ("base",25,2.0,15,15,0.35),
 ("fast01",30,2.5,15,10,0.35),
 ("fast02",35,3.0,15,8,0.35),
 ("fast03",30,2.5,12,10,0.35),
 ("fast04",35,3.0,12,8,0.35),
 ("fast05",40,3.5,12,8,0.35),
 ("fast06",35,3.0,10,10,0.35),
 ("fast07",40,3.5,10,8,0.35),
 ("fast08",30,3.0,18,8,0.35),
 ("fast09",35,3.5,18,8,0.35),
 ("fast10",30,2.5,15,10,0.25),
 ("fast11",35,3.0,12,8,0.25),
]

def targeted_score(r):
    def f(k,default=1e6):
        try:return float(r.get(k))
        except:return default
    stage=abs(f("stage_error_at_t0_cm"))
    qerr=abs(f("q_error_pct"))
    trend=abs(f("model_trend_cm_h")-f("observed_trend_cm_h"))
    rmse6=f("recent_6h_rmse_cm")
    rmse12=f("recent_12h_rmse_cm")
    # Current launch state and rising-limb dynamics dominate.
    return stage/18 + qerr/18 + trend/5 + rmse6/80 + rmse12/140

def main():
    if len(sys.argv)<2:
        raise SystemExit("usage: run_hec_hms_mucum_targeted_now.py /path/to/hec-hms.sh")
    hec=sys.argv[1]
    # The targeted search is diagnostic. Preserve the already-produced
    # operational baseline so repeated candidate runs cannot contaminate the
    # canonical product consumed by the platform.
    canonical_backup = CANONICAL.read_bytes() if CANONICAL.exists() else None
    series_backup = CANONICAL_SERIES.read_bytes() if CANONICAL_SERIES.exists() else None
    rows=[]
    pkgs={}
    for label,il,cl,tc,st,ifm in CANDIDATES:
        p={
          "initial_loss_mm":il,
          "constant_loss_mm_h":cl,
          "tc_h":tc,
          "storage_h":st,
          "recession":0.9,
          "initial_flow_multiplier":ifm,
        }
        try:
            r=cal.run_one(hec,"E28",p,label)
            pkg=r.pop("_pkg")
            r["targeted_score"]=round(targeted_score(r),6)
            rows.append(r); pkgs[label]=pkg
        except Exception as exc:
            rows.append({"label":label,**p,"targeted_score":1e9,"error":str(exc)})
    valid=[r for r in rows if float(r.get("targeted_score",1e9))<1e8]
    if not valid:
        raise RuntimeError("all targeted candidates failed")
    best=min(valid,key=lambda r:float(r["targeted_score"]))
    bp={k:best[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession","initial_flow_multiplier")}
    final=cal.run_one(hec,"E28",bp,"targeted_selected")
    pkg=final.pop("_pkg")
    pkg["targeted_live_search"]={
      "method":"focused_fast_response_high_loss_search",
      "selected_parameters":bp,
      "selected_metrics":final,
      "candidate_count":len(rows),
      "objective":"current state + current trend + recent 6h/12h fit; full-basin observed-rain warm-up retained",
      "visual_stage_shift":False,
      "research_only":True,
    }
    OUT_JSON.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fields=sorted({k for r in rows for k in r})
    with OUT_CSV.open("w",newline="",encoding="utf-8") as fh:
        w=csv.DictWriter(fh,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
    # Restore the baseline generated immediately before this diagnostic search.
    if canonical_backup is not None:
        CANONICAL.write_bytes(canonical_backup)
    if series_backup is not None:
        CANONICAL_SERIES.write_bytes(series_backup)
    print(json.dumps({
      "selected":bp,
      "metrics":final,
      "targeted_score":best["targeted_score"],
      "artifact":str(OUT_JSON.relative_to(ROOT)),
      "canonical_restored": canonical_backup is not None
    },ensure_ascii=False))
if __name__=="__main__":
    main()
