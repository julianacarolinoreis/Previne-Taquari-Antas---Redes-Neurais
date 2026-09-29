#!/usr/bin/env python3
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
RESULT=OUT/"hec_hms_dual_boundary_mucum_latest.json"
SCRIPT=ROOT/"scripts/run_hec_hms_mucum_dual_boundary.py"

CANDIDATES=[
    (0.75,0.75,0.75),
    (0.75,1.00,0.75),
    (1.00,0.75,0.75),
    (1.00,1.00,0.75),
    (1.00,1.00,1.00),
    (1.25,1.25,1.00),
    (1.25,1.25,1.25),
    (1.25,1.25,1.50),
    (1.50,1.25,1.00),
    (1.50,1.25,1.25),
    (1.50,1.25,1.50),
    (1.50,1.50,1.00),
    (1.50,1.50,1.25),
    (1.50,1.50,1.50),
    (1.75,1.50,1.00),
    (1.75,1.50,1.25),
    (1.75,1.50,1.50),
    (1.75,1.75,1.00),
    (1.75,1.75,1.25),
    (1.75,1.75,1.50),
    (2.00,1.75,1.50),
    (2.00,1.75,1.00),
    (2.00,2.00,1.00),
    (2.00,2.00,1.25),
    (2.25,2.00,1.00),
    (2.25,2.25,1.00),
    (2.50,2.50,1.00),
]

def score(pkg):
    cur=pkg.get("current") or {}
    fit=pkg.get("recent_fit_6h") or {}
    e=abs(float(cur.get("stage_error_cm") or 999))
    rmse=float(fit.get("raw_rmse_cm") or fit.get("rmse_cm") or 999)
    bias=abs(float(fit.get("raw_bias_cm") or fit.get("bias_cm") or 999))
    slope=abs(float(cur.get("slope_error_cm_h") or 999))
    # Match both current level and current rising/falling rate. A candidate that
    # only crosses the observed point but has the wrong slope is rejected.
    return e + 0.45*rmse + 0.15*bias + 0.80*slope

def run_one(hec,k1,k2,k3):
    env=dict(os.environ)
    env.update({
        "DUAL_K1_H":str(k1),
        "DUAL_K2_H":str(k2),
        "DUAL_K3_H":str(k3),
        "DUAL_X":"0.2",
    })
    cp=subprocess.run([sys.executable,"-B",str(SCRIPT),hec],cwd=ROOT,env=env,text=True,capture_output=True)
    if cp.returncode!=0:
        return {"k1":k1,"k2":k2,"k3":k3,"ok":False,"stderr":cp.stderr[-3000:],"stdout":cp.stdout[-3000:]}
    pkg=json.loads(RESULT.read_text(encoding="utf-8"))
    return {
        "k1":k1,"k2":k2,"k3":k3,"ok":True,
        "score":score(pkg),
        "current":pkg.get("current"),
        "recent_fit_6h":pkg.get("recent_fit_6h"),
        "peak":pkg.get("peak"),
    }

def main():
    if len(sys.argv)<2: raise SystemExit("usage: sweep /path/to/hec-hms.sh")
    hec=sys.argv[1]
    rows=[run_one(hec,*ks) for ks in CANDIDATES]
    valid=[r for r in rows if r.get("ok")]
    if not valid: raise SystemExit("all dual routing candidates failed")
    best=min(valid,key=lambda r:r["score"])

    env=dict(os.environ)
    env.update({
        "DUAL_K1_H":str(best["k1"]),
        "DUAL_K2_H":str(best["k2"]),
        "DUAL_K3_H":str(best["k3"]),
        "DUAL_X":"0.2",
    })
    cp=subprocess.run([sys.executable,"-B",str(SCRIPT),hec],cwd=ROOT,env=env,text=True,capture_output=True)
    print(cp.stdout); print(cp.stderr,file=sys.stderr)
    if cp.returncode!=0: raise SystemExit(cp.returncode)
    pkg=json.loads(RESULT.read_text(encoding="utf-8"))
    pkg["routing_sweep"]={
        "selection_rule":"min |t0 stage error| + 0.45*RMSE6h + 0.15*|bias6h| + 0.80*|current slope error| using current-event observations",
        "candidates":rows,
        "selected":{"k1_h":best["k1"],"k2_h":best["k2"],"k3_h":best["k3"],"x":0.2,"score":best["score"]},
        "note":"Only routing is recalibrated; observed rain and observed discharge states are unchanged."
    }
    RESULT.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("DUAL_ROUTE_SWEEP="+json.dumps(pkg["routing_sweep"],ensure_ascii=False))

if __name__=="__main__":
    main()
