#!/usr/bin/env python3
"""Quick full-event HEC-HMS search for Muçum, forcing all observed rainfall since 26/09.

Unlike the short restart experiment, this script never overrides HEC_WARM_START_LOCAL.
The HEC dynamic warm-up is therefore 26/09 00:00 local and consumes the full
hourly spatialized observed rainfall history before ECMWF/IFS future rainfall.
"""
from __future__ import annotations
import csv, json, math, os, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import calibrate_hec_hms_live_event as cal

OUT = ROOT / "assets/data/estudo_bacia_taquari_antas"
RESULT = OUT / "hec_hms_full_event_quick_latest.json"
CANDS = OUT / "hec_hms_full_event_quick_candidates.csv"

def f(v, default=1e9):
    try:
        x=float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default

def score(r):
    # Current rising limb is decisive, but whole-event fit remains mandatory.
    s = (
        f(r.get("recent_6h_rmse_cm"))/35.0
        + f(r.get("recent_12h_rmse_cm"))/55.0
        + abs(f(r.get("stage_error_at_t0_cm")))/14.0
        + abs(f(r.get("q_error_pct")))/14.0
        + abs(f(r.get("model_trend_cm_h"))-f(r.get("observed_trend_cm_h")))/3.0
        + f(r.get("event_rmse_cm"))/180.0
    )
    nse=f(r.get("event_nse"),-999)
    if nse < 0.75: s += (0.75-nse)*8.0
    return s

def main():
    if len(sys.argv)<2:
        raise SystemExit("usage: run_hec_hms_mucum_full_event_quick.py /path/to/hec-hms.sh")
    hec=sys.argv[1]
    os.environ.pop("HEC_WARM_START_LOCAL", None)

    candidates=[]
    timing=[(1,1),(2,2),(3,3),(4,4),(5,5),(6,6),(8,8),(10,10),(12,12),(14,14),(16,16),
            (4,6),(6,4),(8,12),(12,8)]
    losses=[(5,0.8),(8,1.0),(10,1.0),(15,1.5),(20,1.5),(20,2.0),(25,2.0),(30,2.0)]
    # focused deterministic set: pair fastest timings with wetter-basin losses,
    # plus moderate timings with stronger losses.
    for tc,st in timing:
        for il,cl in losses:
            if tc <= 6 and il not in (15,20,25,30): 
                continue
            if tc >= 10 and il not in (5,8,10,15,20):
                continue
            candidates.append((tc,st,il,cl))
    # hard cap for operational speed while preserving fast/moderate shapes
    candidates=candidates[:72]

    rows=[]
    for i,(tc,st,il,cl) in enumerate(candidates,1):
        p=cal.rounded_params({
            "initial_loss_mm":il,
            "constant_loss_mm_h":cl,
            "tc_h":tc,
            "storage_h":st,
            "recession":0.90,
            "initial_flow_multiplier":1.0,
        })
        try:
            r=cal.run_one(hec,"E28",p,f"full_{i:02d}")
            r["full_event_score"]=round(score(r),6)
            rows.append(r)
        except Exception as exc:
            rows.append({"label":f"full_{i:02d}","seed_event":"E28",**p,"full_event_score":1e9,"error":str(exc)})

    valid=[r for r in rows if f(r.get("full_event_score"))<1e8]
    if not valid: raise RuntimeError("all full-event candidates failed")
    # Prefer candidates passing the HEC publication guards.
    preferred=[r for r in valid if bool(r.get("publishable"))]
    best=min(preferred or valid,key=lambda r:f(r.get("full_event_score")))
    bp={k:best[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession","initial_flow_multiplier")}

    # Small local refinement including internal initial flow.
    extra=[]
    for dt,ds in [(-2,-2),(-1,0),(0,-1),(1,0),(0,1),(2,2)]:
        p=dict(bp); p["tc_h"]=max(1,p["tc_h"]+dt); p["storage_h"]=max(1,p["storage_h"]+ds); extra.append(p)
    for mult in (0.8,0.9,1.1,1.2):
        p=dict(bp); p["initial_flow_multiplier"]=mult; extra.append(p)
    for j,p0 in enumerate(extra,1):
        p=cal.rounded_params(p0)
        try:
            r=cal.run_one(hec,"E28",p,f"refine_{j:02d}")
            r["full_event_score"]=round(score(r),6)
            rows.append(r)
        except Exception as exc:
            rows.append({"label":f"refine_{j:02d}","seed_event":"E28",**p,"full_event_score":1e9,"error":str(exc)})

    valid=[r for r in rows if f(r.get("full_event_score"))<1e8]
    preferred=[r for r in valid if bool(r.get("publishable"))]
    best=min(preferred or valid,key=lambda r:f(r.get("full_event_score")))
    bp={k:best[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession","initial_flow_multiplier")}
    final=cal.run_one(hec,"E28",bp,"selected_full_event_quick")
    pkg=final.pop("_pkg")
    final["full_event_score"]=round(score(final),6)
    pkg["full_event_quick"]={
        "method":"full observed spatial rainfall warm-up from 2026-09-26 00:00 local + ECMWF/IFS future; no short restart",
        "selected_parameters":bp,
        "selected_metrics":final,
        "candidate_count":len(rows),
    }
    pkg["generated_at_utc"]=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    RESULT.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    clean=[{k:v for k,v in r.items() if k!="_pkg"} for r in rows]
    fields=sorted({k for r in clean for k in r})
    with CANDS.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields,extrasaction="ignore"); w.writeheader()
        for r in clean:
            x=dict(r)
            if isinstance(x.get("blocking_reasons_pt"),list): x["blocking_reasons_pt"]=" | ".join(x["blocking_reasons_pt"])
            w.writerow(x)
    print(json.dumps({"selected_parameters":bp,"selected_metrics":final,"result":str(RESULT.relative_to(ROOT))},ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
