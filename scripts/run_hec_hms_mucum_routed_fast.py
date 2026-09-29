#!/usr/bin/env python3
"""Focused routed HEC-HMS 4.13 calibration for current Muçum flood."""
from __future__ import annotations
import json, math, os, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import calibrate_hec_hms_live_event as cal
OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
RESULT=OUT/"hec_hms_routed_fast_latest.json"

CANDIDATES=[
 dict(initial_loss_mm=5, constant_loss_mm_h=1.0, tc_h=16, storage_h=16, recession=0.9, initial_flow_multiplier=1.0),
 dict(initial_loss_mm=10,constant_loss_mm_h=1.0,tc_h=16,storage_h=16,recession=0.9,initial_flow_multiplier=1.0),
 dict(initial_loss_mm=15,constant_loss_mm_h=1.0,tc_h=16,storage_h=16,recession=0.9,initial_flow_multiplier=1.0),
 dict(initial_loss_mm=15,constant_loss_mm_h=1.5,tc_h=16,storage_h=16,recession=0.9,initial_flow_multiplier=1.0),
 dict(initial_loss_mm=20,constant_loss_mm_h=1.5,tc_h=16,storage_h=16,recession=0.9,initial_flow_multiplier=1.0),
 dict(initial_loss_mm=20,constant_loss_mm_h=2.0,tc_h=18,storage_h=18,recession=0.9,initial_flow_multiplier=1.0),
 dict(initial_loss_mm=25,constant_loss_mm_h=2.0,tc_h=18,storage_h=18,recession=0.9,initial_flow_multiplier=1.0),
 dict(initial_loss_mm=15,constant_loss_mm_h=1.0,tc_h=20,storage_h=20,recession=0.9,initial_flow_multiplier=1.0),
 dict(initial_loss_mm=20,constant_loss_mm_h=1.0,tc_h=20,storage_h=20,recession=0.9,initial_flow_multiplier=1.0),
 dict(initial_loss_mm=25,constant_loss_mm_h=1.5,tc_h=20,storage_h=20,recession=0.9,initial_flow_multiplier=1.0),
 dict(initial_loss_mm=20,constant_loss_mm_h=2.0,tc_h=22,storage_h=22,recession=0.9,initial_flow_multiplier=1.0),
 dict(initial_loss_mm=20,constant_loss_mm_h=2.0,tc_h=26,storage_h=26,recession=0.9,initial_flow_multiplier=1.0),
]

def f(v,d=1e9):
 try:
  x=float(v); return x if math.isfinite(x) else d
 except: return d

def score(r):
 # Must fit current rise; whole-event fit is retained as guard.
 s=(f(r.get("recent_6h_rmse_cm"))/32 + f(r.get("recent_12h_rmse_cm"))/55
    + abs(f(r.get("stage_error_at_t0_cm")))/12 + abs(f(r.get("q_error_pct")))/12
    + abs(f(r.get("model_trend_cm_h"))-f(r.get("observed_trend_cm_h")))/2.5
    + f(r.get("event_rmse_cm"))/220)
 n=f(r.get("event_nse"),-99)
 if n<0.5: s+=(0.5-n)*5
 return s

def main():
 if len(sys.argv)<2: raise SystemExit("usage: routed_fast.py /path/hec-hms.sh")
 hec=sys.argv[1]
 os.environ.pop("HEC_WARM_START_LOCAL",None)
 os.environ["HEC_ROUTE_K1_H"]="1.0"
 os.environ["HEC_ROUTE_K2_H"]="1.0"
 os.environ["HEC_ROUTE_X"]="0.2"
 rows=[]
 for i,p in enumerate(CANDIDATES,1):
  try:
   r=cal.run_one(hec,"E28",p,f"routed_{i:02d}")
   r["routed_score"]=round(score(r),6)
   rows.append(r)
  except Exception as e:
   rows.append({"label":f"routed_{i:02d}",**p,"routed_score":1e9,"error":str(e)})
 valid=[r for r in rows if f(r.get("routed_score"))<1e8]
 if not valid: raise RuntimeError("all routed candidates failed")
 # Prefer publishable; otherwise select best diagnostic but keep its blockers.
 pub=[r for r in valid if bool(r.get("publishable"))]
 best=min(pub or valid,key=lambda r:f(r.get("routed_score")))
 bp={k:best[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession","initial_flow_multiplier")}
 final=cal.run_one(hec,"E28",bp,"selected_routed_fast")
 pkg=final.pop("_pkg")
 final["routed_score"]=round(score(final),6)
 pkg["routed_fast"]={
  "method":"HEC-HMS 4.13 full observed spatial rainfall from 26/09 + ECMWF/IFS future + explicit Muskingum reaches",
  "route":{"k1_h":1.0,"k2_h":1.0,"x":0.2,"observed_lag_basis":"Linha Jose Julio -> Mucum max hourly-flow correlation at ~2 h"},
  "candidate_count":len(rows),
  "selected_parameters":bp,
  "selected_metrics":final,
  "candidates":[{k:v for k,v in r.items() if k!="_pkg"} for r in rows],
 }
 pkg["generated_at_utc"]=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
 RESULT.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"selected":bp,"metrics":final,"result":str(RESULT.relative_to(ROOT))},ensure_ascii=False))
if __name__=="__main__": main()
