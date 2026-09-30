#!/usr/bin/env python3
"""Deterministic first-stage parameter search for the G040 E1 HEC hindcast.

This search is deliberately small and source-bounded. It is NOT a calibration
promotion. It tests whether one regional SCS-CN / lag parameterization plus
four aggregate Muskingum travel-time groups can reproduce the current event at
multiple mainstem checkpoints through Porto Mariante.

Bounds are documented in g040_e1_parameter_search_contract_latest.json.
"""
from __future__ import annotations
import argparse, json, math, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
RUNNER=ROOT/"scripts/run_hec_hms_g040_e1_hindcast.py"
OUT=BASE/"g040_e1_search_latest.json"
CANDROOT=BASE/"g040_e1_hindcast"

BOUNDS={
 "cn":(28.505926,73.41799999999999,"linear"),
 "lag_min":(15.847934,465.54599999999976,"log"),
 "k_g1":(1.0,6.0,"linear"),
 "k_g2":(0.5,3.0,"linear"),
 "k_g3":(0.5,10.0,"linear"),
 "k_g4":(0.5,12.0,"linear"),
 "x":(0.10,0.30,"linear"),
}
PRIMES={"cn":2,"lag_min":3,"k_g1":5,"k_g2":7,"k_g3":11,"k_g4":13,"x":17}

def vdc(n,base):
    v=0.0; denom=1.0
    while n:
        n,rem=divmod(n,base); denom*=base; v+=rem/denom
    return v

def scale(u,b):
    lo,hi,mode=b
    if mode=="log": return math.exp(math.log(lo)+u*(math.log(hi)-math.log(lo)))
    return lo+u*(hi-lo)

def design(n):
    rows=[
      {"candidate_id":"ANCHOR_EVENT2_MEDIAN","cn":43.22047,"lag_min":55.11625,
       "k_g1":3.5,"k_g2":1.5,"k_g3":5.0,"k_g4":6.0,"x":0.2},
      {"candidate_id":"ANCHOR_LEGACY_MEDIAN","cn":68.22,"lag_min":187.55,
       "k_g1":3.5,"k_g2":1.5,"k_g3":5.0,"k_g4":6.0,"x":0.2},
    ]
    for i in range(1,n+1):
        r={"candidate_id":f"QMC_{i:02d}"}
        for k,b in BOUNDS.items(): r[k]=scale(vdc(i,PRIMES[k]),b)
        rows.append(r)
    return rows

def run_candidate(hec,row):
    cmd=[sys.executable,"-B",str(RUNNER),hec,
      "--candidate-id",row["candidate_id"],
      "--cn",str(row["cn"]),"--lag-min",str(row["lag_min"]),
      "--k-g1",str(row["k_g1"]),"--k-g2",str(row["k_g2"]),
      "--k-g3",str(row["k_g3"]),"--k-g4",str(row["k_g4"]),
      "--x",str(row["x"])]
    p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=300,check=False)
    result_path=CANDROOT/row["candidate_id"]/"result.json"
    if not result_path.exists():
        return {"candidate_id":row["candidate_id"],"compute_ok":False,"returncode":p.returncode,
                "error":"result.json missing","stdout_tail":p.stdout[-3000:],"stderr_tail":p.stderr[-3000:]}
    j=json.loads(result_path.read_text(encoding="utf-8"))
    j["runner_returncode"]=p.returncode
    return j

def metric_penalty(m):
    if not isinstance(m,dict) or m.get("pairs",0)<4: return None
    terms=[]
    nse=m.get("nse"); kge=m.get("kge"); nr=m.get("normalized_rmse")
    if nse is not None: terms.append(max(0.0,1-float(nse)))
    if kge is not None: terms.append(max(0.0,1-float(kge)))
    if nr is not None: terms.append(abs(float(nr)))
    if m.get("pbias_pct") is not None: terms.append(abs(float(m["pbias_pct"]))/100)
    if m.get("peak_error_pct") is not None: terms.append(abs(float(m["peak_error_pct"]))/100)
    if m.get("peak_timing_error_h") is not None: terms.append(abs(float(m["peak_timing_error_h"]))/12)
    if m.get("rise_fall_sign_skill") is not None: terms.append(max(0.0,1-float(m["rise_fall_sign_skill"])))
    return sum(terms)/len(terms) if terms else None

def checkpoint_gate(m):
    if not isinstance(m,dict) or m.get("pairs",0)<4: return False
    return (
      m.get("nse") is not None and float(m["nse"])>=0.50 and
      m.get("pbias_pct") is not None and abs(float(m["pbias_pct"]))<=20 and
      m.get("peak_error_pct") is not None and abs(float(m["peak_error_pct"]))<=20 and
      m.get("peak_timing_error_h") is not None and abs(float(m["peak_timing_error_h"]))<=3 and
      m.get("rise_fall_sign_skill") is not None and float(m["rise_fall_sign_skill"])>=0.65
    )

def summarize(j):
    scores=j.get("scores") or {}
    valid={k:v for k,v in scores.items() if isinstance(v,dict) and v.get("pairs",0)>=4}
    pens=[metric_penalty(v) for v in valid.values()]
    pens=[x for x in pens if x is not None]
    return {
      "candidate_id":j.get("candidate_id"),"compute_ok":bool(j.get("compute_ok")),
      "parameters":j.get("parameters"),"window":j.get("window"),
      "valid_checkpoint_count":len(valid),
      "checkpoint_gate_pass_count":sum(checkpoint_gate(v) for v in valid.values()),
      "mean_multi_metric_penalty":sum(pens)/len(pens) if pens else None,
      "scores":scores,
    }

def rank_key(x):
    # Primary: more checkpoint gates. Secondary: lower multi-metric penalty.
    return (-int(x.get("checkpoint_gate_pass_count") or 0),
            float("inf") if x.get("mean_multi_metric_penalty") is None else float(x["mean_multi_metric_penalty"]))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("hec_hms_sh"); ap.add_argument("--qmc",type=int,default=16)
    args=ap.parse_args()
    candidates=design(max(4,min(32,args.qmc)))
    results=[]
    for i,row in enumerate(candidates,1):
        print(f"[{i}/{len(candidates)}] {row['candidate_id']}",flush=True)
        try: j=run_candidate(args.hec_hms_sh,row)
        except Exception as exc:
            j={"candidate_id":row["candidate_id"],"compute_ok":False,"error":str(exc)}
        results.append(summarize(j) if j.get("scores") is not None else j)
    ranked=sorted(results,key=rank_key)
    best=ranked[0] if ranked else None
    payload={"schema_version":"g040_e1_first_stage_search_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,"status":"SEARCH_COMPLETE_NO_PROMOTION",
      "method":{"candidate_count":len(candidates),"design":"2 report-derived anchors + deterministic Van der Corput/QMC coverage",
        "bounds":BOUNDS,
        "ranking":"maximize count of checkpoint gates, then minimize mean multi-metric penalty",
        "checkpoint_gate":"NSE>=0.50, |PBIAS|<=20%, |peak error|<=20%, |peak timing|<=3h, rise/fall sign skill>=0.65"},
      "best_diagnostic_candidate":best,"ranked_candidates":ranked,
      "promotion_allowed":False,
      "next_step":"refine around Pareto/best candidates, then repeat on independent historical events before any parameter promotion"}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":payload["status"],"best":None if not best else {
      "candidate_id":best.get("candidate_id"),"gate_passes":best.get("checkpoint_gate_pass_count"),
      "penalty":best.get("mean_multi_metric_penalty")}},ensure_ascii=False))
    return 0 if any(x.get("compute_ok") for x in results) else 2
if __name__=="__main__": raise SystemExit(main())
