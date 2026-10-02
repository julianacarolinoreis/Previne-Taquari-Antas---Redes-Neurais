#!/usr/bin/env python3
"""Refine G040 eventwise parameter donors per target/control.

A single HEC-HMS run yields scores at several controls. For each historical event
we therefore generate a compact local candidate pool around the existing best
target/event seeds, run each candidate once, and then choose a potentially
different best parameter set for each city/control.

This is historical donor-library calibration. It is NOT forecast validation:
pseudo-operational replay must exclude the target event from its donor library.
"""
from __future__ import annotations
import argparse,csv,json,math,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
LIB=BASE/"g040_target_event_parameter_library_latest.json"
RUNNER=ROOT/"scripts/run_hec_hms_g040_e1_hindcast.py"
FORCING=BASE/"historical_calibration_forcing"
RUNROOT=BASE/"g040_target_event_refinement_runs"
OUT=BASE/"g040_target_event_refinement_latest.json"
OUTCSV=BASE/"g040_target_event_refinement_latest.csv"
REQUEST=ROOT/"config/g040_target_event_refinement_request_v1.json"

TARGET_NAMES={
 "86510000":"Muçum","86720000":"Encantado","86879300":"Estrela","86895000":"Porto Mariante"
}

def load(p:Path)->dict[str,Any]: return json.loads(p.read_text(encoding="utf-8"))

def clamp(v,lo,hi): return max(lo,min(hi,v))

def pkey(p):
    return tuple(round(float(p[k]),8) for k in ("cn","lag_min","k_g1","k_g2","k_g3","k_g4","x"))

def variants(seed:dict[str,Any],tag:str)->list[dict[str,Any]]:
    s={k:float(seed[k]) for k in ("cn","lag_min","k_g1","k_g2","k_g3","k_g4","x")}
    specs=[
      ("BASE",{}),
      ("CN_LO",{"cn":s["cn"]*0.90}),
      ("CN_HI",{"cn":s["cn"]*1.10}),
      ("LAG_FAST",{"lag_min":s["lag_min"]*0.80}),
      ("LAG_SLOW",{"lag_min":s["lag_min"]*1.20}),
      ("ROUTE_FAST",{"k_g1":s["k_g1"]*0.82,"k_g2":s["k_g2"]*0.82,"k_g3":s["k_g3"]*0.82,"k_g4":s["k_g4"]*0.82}),
      ("ROUTE_SLOW",{"k_g1":s["k_g1"]*1.18,"k_g2":s["k_g2"]*1.18,"k_g3":s["k_g3"]*1.18,"k_g4":s["k_g4"]*1.18}),
      ("UP_SLOW_DN_FAST",{"k_g1":s["k_g1"]*1.18,"k_g2":s["k_g2"]*1.18,"k_g3":s["k_g3"]*0.85,"k_g4":s["k_g4"]*0.85}),
      ("UP_FAST_DN_SLOW",{"k_g1":s["k_g1"]*0.85,"k_g2":s["k_g2"]*0.85,"k_g3":s["k_g3"]*1.18,"k_g4":s["k_g4"]*1.18}),
      ("X_SHIFT",{"x":clamp(s["x"]-0.03,0.08,0.35)}),
    ]
    out=[]
    for name,chg in specs:
        p=dict(s);p.update(chg)
        p["cn"]=clamp(p["cn"],20,90)
        p["lag_min"]=clamp(p["lag_min"],10,600)
        for k in ("k_g1","k_g2","k_g3","k_g4"):p[k]=clamp(p[k],0.15,18)
        p["x"]=clamp(p["x"],0.05,0.45)
        out.append({"candidate_id":f"{tag}__{name}","parameters":p})
    return out

def event_paths(eid):
    d=FORCING/eid
    return d/"rain.json",d/"hydro.json",d/"scenario.json"

def run(hec,row,eid):
    rain,hydro,scenario=event_paths(eid)
    rid=f"REFINE_{eid}__{row['candidate_id']}"
    p=row["parameters"]
    cmd=[sys.executable,"-B",str(RUNNER),hec,
      "--candidate-id",rid,"--event-id",eid,
      "--rain-file",str(rain),"--hydro-file",str(hydro),"--scenario-file",str(scenario),
      "--output-root",str(RUNROOT),
      "--cn",str(p["cn"]),"--lag-min",str(p["lag_min"]),
      "--k-g1",str(p["k_g1"]),"--k-g2",str(p["k_g2"]),
      "--k-g3",str(p["k_g3"]),"--k-g4",str(p["k_g4"]),"--x",str(p["x"])]
    cp=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=420,check=False)
    rp=RUNROOT/rid/"result.json"
    if not rp.exists():
        return {"candidate_id":row["candidate_id"],"parameters":p,"compute_ok":False,
          "returncode":cp.returncode,"error":"result_missing","stderr_tail":cp.stderr[-1500:]}
    j=load(rp);j["search_candidate_id"]=row["candidate_id"];j["search_parameters"]=p
    return j

def gate(m):
    return bool(
      isinstance(m,dict) and int(m.get("pairs") or 0)>=12
      and m.get("nse") is not None and float(m["nse"])>=0.50
      and m.get("pbias_pct") is not None and abs(float(m["pbias_pct"]))<=20
      and m.get("peak_error_pct") is not None and abs(float(m["peak_error_pct"]))<=20
      and m.get("peak_timing_error_h") is not None and abs(float(m["peak_timing_error_h"]))<=3
      and m.get("rise_fall_sign_skill") is not None and float(m["rise_fall_sign_skill"])>=0.65
    )

def loss(m,w):
    if not isinstance(m,dict) or int(m.get("pairs") or 0)<12:return None
    vals={}
    vals["nse"]=max(0,1-float(m["nse"])) if m.get("nse") is not None else 1
    vals["kge"]=max(0,1-float(m["kge"])) if m.get("kge") is not None else 1
    vals["pbias"]=abs(float(m["pbias_pct"]))/100 if m.get("pbias_pct") is not None else 1
    vals["peak_error"]=abs(float(m["peak_error_pct"]))/100 if m.get("peak_error_pct") is not None else 1
    vals["peak_timing"]=abs(float(m["peak_timing_error_h"]))/6 if m.get("peak_timing_error_h") is not None else 1
    vals["rise_fall"]=max(0,1-float(m["rise_fall_sign_skill"])) if m.get("rise_fall_sign_skill") is not None else 1
    return sum(float(w[k])*vals[k] for k in vals),vals

def main():
    ap=argparse.ArgumentParser();ap.add_argument("hec_hms_sh");args=ap.parse_args()
    req=load(REQUEST);lib=load(LIB)
    wanted_events=req["events"];wanted_targets=set(req["targets"]);weights=req["objective"]
    rows=[r for r in lib.get("hec_target_event_candidates") or [] if r["event_id"] in wanted_events and r["target_code"] in wanted_targets]
    fallback=(lib.get("robust_fallbacks") or [])
    robust=next((x.get("parameters") for x in fallback if x.get("parameters")),None)

    event_pool={}
    for eid in wanted_events:
        seeds=[]
        for r in rows:
            if r["event_id"]==eid and r.get("parameters"):seeds.append((r["candidate_id"],r["parameters"]))
        if robust:seeds.append(("ROBUST",robust))
        seen=set();pool=[]
        for tag,p in seeds:
            for v in variants(p,tag):
                k=pkey(v["parameters"])
                if k in seen:continue
                seen.add(k);pool.append(v)
        event_pool[eid]=pool

    runs={}
    for eid,pool in event_pool.items():
        print(f"{eid}: {len(pool)} unique refinement candidates",flush=True)
        rr=[]
        for i,row in enumerate(pool,1):
            print(f"  {i}/{len(pool)} {row['candidate_id']}",flush=True)
            try:rr.append(run(args.hec_hms_sh,row,eid))
            except Exception as exc:rr.append({"candidate_id":row["candidate_id"],"parameters":row["parameters"],"compute_ok":False,"error":str(exc)})
        runs[eid]=rr

    selected=[]
    for eid in wanted_events:
        for code in sorted(wanted_targets):
            scored=[]
            for r in runs.get(eid,[]):
                m=(r.get("scores") or {}).get(code)
                z=loss(m,weights)
                if z is None:continue
                l,parts=z
                scored.append({
                  "candidate_id":r.get("search_candidate_id") or r.get("candidate_id"),
                  "parameters":r.get("search_parameters") or r.get("parameters"),
                  "metrics":m,"gate_pass":gate(m),"target_loss":l,"loss_parts":parts
                })
            scored.sort(key=lambda x:(0 if x["gate_pass"] else 1,x["target_loss"]))
            if not scored:continue
            selected.append({
              "event_id":eid,"target_code":code,"target_name":TARGET_NAMES.get(code,code),
              "best":scored[0],"top5":scored[:5],
              "candidate_count_scored":len(scored),
              "fit_role":"target_event_refined_donor",
              "promotion_allowed":False,
              "leakage_warning":"full historical event used in fitting; donor-library calibration only"
            })

    payload={
      "schema_version":"g040_target_event_refinement_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,
      "request":req,
      "events":{eid:{"candidate_count":len(event_pool[eid]),"compute_ok":sum(bool(x.get("compute_ok")) for x in runs[eid])} for eid in wanted_events},
      "selected":selected,
      "method":{
        "engine":"HEC-HMS 4.13 via run_hec_hms_g040_e1_hindcast.py",
        "compute_interval_min":3,
        "selection":"target-specific: prefer gate pass, then target loss",
        "same_run_many_targets":True,
        "pseudo_operational_validation_required":True
      }
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with OUTCSV.open("w",encoding="utf-8",newline="") as fh:
        fields=["event_id","target_code","target_name","candidate_id","gate_pass","target_loss","nse","kge","pbias_pct","peak_error_pct","peak_timing_error_h","cn","lag_min","k_g1","k_g2","k_g3","k_g4","x"]
        w=csv.DictWriter(fh,fieldnames=fields);w.writeheader()
        for row in selected:
            b=row["best"];m=b["metrics"];p=b["parameters"]
            w.writerow({"event_id":row["event_id"],"target_code":row["target_code"],"target_name":row["target_name"],
              "candidate_id":b["candidate_id"],"gate_pass":b["gate_pass"],"target_loss":b["target_loss"],
              "nse":m.get("nse"),"kge":m.get("kge"),"pbias_pct":m.get("pbias_pct"),"peak_error_pct":m.get("peak_error_pct"),
              "peak_timing_error_h":m.get("peak_timing_error_h"),**{k:p.get(k) for k in ("cn","lag_min","k_g1","k_g2","k_g3","k_g4","x")}})
    print(json.dumps({"status":"G040_TARGET_EVENT_REFINEMENT_COMPLETE","rows":len(selected),"gate_pass_rows":sum(x["best"]["gate_pass"] for x in selected)},ensure_ascii=False))
    return 0
if __name__=="__main__":raise SystemExit(main())
