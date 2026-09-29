#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys, math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import calibrate_hec_hms_live_event as cal
OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
RUNTIME=OUT/"hec_hms_spatial_forecast_mucum"

P=dict(initial_loss_mm=25.0,constant_loss_mm_h=1.5,tc_h=20.0,storage_h=20.0,recession=0.9,initial_flow_multiplier=1.0)
ROUTES=[0.75,1.0,1.5,2.0,2.5,3.0]

def f(v,d=1e9):
 try:
  x=float(v); return x if math.isfinite(x) else d
 except:return d

def route_score(r):
 return (abs(f(r.get("model_trend_cm_h"))-f(r.get("observed_trend_cm_h")))/2
         + abs(f(r.get("stage_error_at_t0_cm")))/8
         + abs(f(r.get("q_error_pct")))/10
         + f(r.get("recent_6h_rmse_cm"))/80)

def main():
 if len(sys.argv)<2: raise SystemExit("hec path")
 hec=sys.argv[1]
 os.environ.pop("HEC_WARM_START_LOCAL",None)
 os.environ["HEC_ROUTE_X"]="0.2"
 rows=[]
 for k in ROUTES:
  os.environ["HEC_ROUTE_K1_H"]=str(k)
  os.environ["HEC_ROUTE_K2_H"]=str(k)
  r=cal.run_one(hec,"E28",P,f"route_{k:g}")
  r["route_each_h"]=k
  r["route_total_nominal_h"]=2*k
  r["route_score"]=route_score(r)
  rows.append(r)
 best=min(rows,key=lambda x:x["route_score"])
 k=float(best["route_each_h"])
 os.environ["HEC_ROUTE_K1_H"]=str(k); os.environ["HEC_ROUTE_K2_H"]=str(k)
 final=cal.run_one(hec,"E28",P,"route_selected")
 pkg=final.pop("_pkg")
 print("ROUTE_TESTS="+json.dumps([{kk:rr.get(kk) for kk in [
   "route_each_h","route_total_nominal_h","stage_error_at_t0_cm","q_error_pct",
   "observed_trend_cm_h","model_trend_cm_h","recent_6h_rmse_cm","recent_6h_nse",
   "event_rmse_cm","event_nse","publishable","route_score"]} for rr in rows],ensure_ascii=False))
 print("ROUTE_SELECTED="+json.dumps({"route_each_h":k,"route_total_nominal_h":2*k,
   "summary":pkg.get("summary"),"validation":pkg.get("validation"),"series":pkg.get("series")},ensure_ascii=False))
 print("PRIMARY_SERIES_BEGIN")
 print((RUNTIME/"primary_series.csv").read_text())
 print("PRIMARY_SERIES_END")
if __name__=="__main__":main()
