#!/usr/bin/env python3
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
RESULT=OUT/"hec_hms_dual_boundary_mucum_latest.json"
SCRIPT=ROOT/"scripts/run_hec_hms_mucum_dual_boundary.py"

# Promising routing families from the 19:45 audit, crossed with warm-up length.
CANDIDATES=[]
for warm in (4,6,8,10,12):
    CANDIDATES += [
        (1.00,1.00,0.75,warm),
        (1.00,1.00,1.00,warm),
        (1.25,1.25,1.00,warm),
        (1.25,1.25,1.25,warm),
        (1.50,1.50,1.00,warm),
    ]

def score(pkg):
    cur=pkg.get("current") or {}
    fit=pkg.get("recent_fit_6h") or {}
    e=abs(float(cur.get("stage_error_cm") if cur.get("stage_error_cm") is not None else 999))
    slope=abs(float(cur.get("slope_error_cm_h") if cur.get("slope_error_cm_h") is not None else 999))
    rmse=float(fit.get("raw_rmse_cm") if fit.get("raw_rmse_cm") is not None else 999)
    bias=abs(float(fit.get("raw_bias_cm") if fit.get("raw_bias_cm") is not None else 999))
    # Operational goal: native state + native slope must both resemble reality.
    return 1.0*e + 1.1*slope + 0.35*rmse + 0.10*bias

def run_one(hec,k1,k2,k3,warm):
    env=dict(os.environ)
    env.update({
      "DUAL_K1_H":str(k1),"DUAL_K2_H":str(k2),"DUAL_K3_H":str(k3),
      "DUAL_X":"0.2","DUAL_WARMUP_H":str(warm)
    })
    cp=subprocess.run([sys.executable,"-B",str(SCRIPT),hec],cwd=ROOT,env=env,text=True,capture_output=True)
    if cp.returncode!=0:
      return {"k1":k1,"k2":k2,"k3":k3,"warmup_h":warm,"ok":False,"stderr":cp.stderr[-2000:]}
    pkg=json.loads(RESULT.read_text(encoding="utf-8"))
    return {
      "k1":k1,"k2":k2,"k3":k3,"warmup_h":warm,"ok":True,
      "score":score(pkg),"current":pkg.get("current"),"recent_fit_6h":pkg.get("recent_fit_6h"),
      "peak":pkg.get("peak"),"publishable":pkg.get("publishable")
    }

def main():
    if len(sys.argv)<2: raise SystemExit("usage: state_sweep /path/to/hec-hms.sh")
    hec=sys.argv[1]
    rows=[run_one(hec,*x) for x in CANDIDATES]
    valid=[x for x in rows if x.get("ok")]
    if not valid: raise SystemExit("all state candidates failed")
    best=min(valid,key=lambda x:x["score"])
    env=dict(os.environ)
    env.update({
      "DUAL_K1_H":str(best["k1"]),"DUAL_K2_H":str(best["k2"]),"DUAL_K3_H":str(best["k3"]),
      "DUAL_X":"0.2","DUAL_WARMUP_H":str(best["warmup_h"])
    })
    cp=subprocess.run([sys.executable,"-B",str(SCRIPT),hec],cwd=ROOT,env=env,text=True,capture_output=True)
    print(cp.stdout); print(cp.stderr,file=sys.stderr)
    if cp.returncode!=0: raise SystemExit(cp.returncode)
    pkg=json.loads(RESULT.read_text(encoding="utf-8"))
    pkg["state_routing_sweep"]={
      "selection_rule":"min |current stage error| + 1.1*|current slope error| + 0.35*RMSE6h + 0.10*|bias6h|",
      "candidates":rows,
      "selected":{"k1_h":best["k1"],"k2_h":best["k2"],"k3_h":best["k3"],"x":0.2,"warmup_h":best["warmup_h"],"score":best["score"]},
      "note":"Observed rain and observed upstream discharge are unchanged. Only routing and model warm-up/state are recalibrated."
    }
    RESULT.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("STATE_ROUTING_SWEEP="+json.dumps(pkg["state_routing_sweep"],ensure_ascii=False))

if __name__=="__main__":
    main()
