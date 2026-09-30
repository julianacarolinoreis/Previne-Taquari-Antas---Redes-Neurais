#!/usr/bin/env python3
"""Iterative operational calibration for Muçum.

A candidate is never treated as final merely because HEC-HMS completed.
The loop keeps observed forcing/boundaries fixed and iterates only over
permitted internal state/routing parameters until objective hydrologic
acceptance criteria are met.

Research/decision-support only; not an official alert.
"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
RESULT=OUT/"hec_hms_dual_boundary_mucum_latest.json"
SCRIPT=ROOT/"scripts/run_hec_hms_mucum_dual_boundary.py"

# Acceptance criteria for a FINAL operational candidate.
LIMITS={
    "abs_stage_error_cm": 10.0,
    "abs_slope_error_cm_h": 12.0,
    "rmse6h_cm": 35.0,
    "abs_bias6h_cm": 15.0,
    "min_lag_corr": 0.98,
    "max_lag_rmse_m3s": 150.0,
    "min_rain_stations": 40,
    "min_flow_q_stations": 30,
    "max_boundary_age_h": 2.0,
}

# Stage 1: physically plausible coarse neighborhood around the current event.
BASE_STAGE=[
  (1.00,1.00,0.75,w) for w in (4,6,8,10,12)
] + [
  (1.00,1.00,1.00,w) for w in (4,6,8,10,12)
] + [
  (1.25,1.25,1.00,w) for w in (4,6,8,10,12)
] + [
  (1.25,1.25,1.25,w) for w in (4,6,8,10,12)
] + [
  (1.50,1.50,1.00,w) for w in (4,6,8,10,12)
]

def adaptive_candidates(best, k_step, warm_step):
    """Refine deterministically around the best executed candidate."""
    if not best:
        return []
    ks1=[round(max(0.6,best["k1"]+d),2) for d in (-k_step,0,k_step)]
    ks2=[round(max(0.6,best["k2"]+d),2) for d in (-k_step,0,k_step)]
    ks3=[round(max(0.5,best["k3"]+d),2) for d in (-k_step,0,k_step)]
    warms=sorted(set(max(3,min(12,int(round(best["warmup_h"]+d)))) for d in (-warm_step,0,warm_step)))
    out=[]
    for k1 in ks1:
        for k2 in ks2:
            if abs(k1-k2)>0.45:
                continue
            for k3 in ks3:
                for warm in warms:
                    out.append((k1,k2,k3,warm))
    return out

def val(x, default=999.0):
    try:
        if x is None: return default
        return float(x)
    except Exception:
        return default

def score(pkg):
    cur=pkg.get("current") or {}
    fit=pkg.get("recent_fit_6h") or {}
    e=abs(val(cur.get("stage_error_cm")))
    slope=abs(val(cur.get("slope_error_cm_h")))
    rmse=val(fit.get("raw_rmse_cm"))
    bias=abs(val(fit.get("raw_bias_cm")))
    # Emphasize present state and current derivative, then recent-shape fit.
    return e + 1.35*slope + 0.35*rmse + 0.12*bias

def boundary_age_h(pkg, key):
    from datetime import datetime
    cur=(pkg.get("current") or {}).get("observed_time_local")
    b=((pkg.get("boundary_audit") or {}).get(key) or {}).get("last_observed_local")
    if not cur or not b: return 999.0
    return max(0.0,(datetime.fromisoformat(cur)-datetime.fromisoformat(b)).total_seconds()/3600.0)

def checks(pkg):
    cur=pkg.get("current") or {}
    fit=pkg.get("recent_fit_6h") or {}
    net=pkg.get("observed_network_audit") or {}
    lag=(((pkg.get("boundary_audit") or {}).get("observed_event_lag") or {}).get("best") or {})

    values={
      "abs_stage_error_cm":abs(val(cur.get("stage_error_cm"))),
      "abs_slope_error_cm_h":abs(val(cur.get("slope_error_cm_h"))),
      "rmse6h_cm":val(fit.get("raw_rmse_cm")),
      "abs_bias6h_cm":abs(val(fit.get("raw_bias_cm"))),
      "lag_corr":val(lag.get("corr"),-999),
      "lag_rmse_m3s":val(lag.get("rmse_m3s")),
      "rain_station_count":int(net.get("rain_valid_station_count") or 0),
      "flow_q_station_count":int(net.get("flow_stations_with_q") or 0),
      "ljj_age_h":boundary_age_h(pkg,"linha_jose_julio"),
      "carreiro_age_h":boundary_age_h(pkg,"passo_carreiro"),
    }
    passed={
      "stage":values["abs_stage_error_cm"]<=LIMITS["abs_stage_error_cm"],
      "slope":values["abs_slope_error_cm_h"]<=LIMITS["abs_slope_error_cm_h"],
      "rmse6h":values["rmse6h_cm"]<=LIMITS["rmse6h_cm"],
      "bias6h":values["abs_bias6h_cm"]<=LIMITS["abs_bias6h_cm"],
      "lag_corr":values["lag_corr"]>=LIMITS["min_lag_corr"],
      "lag_rmse":values["lag_rmse_m3s"]<=LIMITS["max_lag_rmse_m3s"],
      "rain_network":values["rain_station_count"]>=LIMITS["min_rain_stations"],
      "flow_network":values["flow_q_station_count"]>=LIMITS["min_flow_q_stations"],
      "ljj_fresh":values["ljj_age_h"]<=LIMITS["max_boundary_age_h"],
      "carreiro_fresh":values["carreiro_age_h"]<=LIMITS["max_boundary_age_h"],
    }
    return values,passed,all(passed.values())

def run_one(hec,k1,k2,k3,warm):
    env=dict(os.environ)
    env.update({
      "DUAL_K1_H":str(k1),"DUAL_K2_H":str(k2),"DUAL_K3_H":str(k3),
      "DUAL_X":"0.2","DUAL_WARMUP_H":str(warm)
    })
    cp=subprocess.run([sys.executable,"-B",str(SCRIPT),hec],cwd=ROOT,env=env,text=True,capture_output=True)
    if cp.returncode!=0:
        return {"ok":False,"k1":k1,"k2":k2,"k3":k3,"warmup_h":warm,
                "stderr":cp.stderr[-1500:]}
    pkg=json.loads(RESULT.read_text(encoding="utf-8"))
    values,passed,accepted=checks(pkg)
    return {
      "ok":True,"accepted":accepted,"score":score(pkg),
      "k1":k1,"k2":k2,"k3":k3,"warmup_h":warm,
      "values":values,"passed":passed,
      "current":pkg.get("current"),"recent_fit_6h":pkg.get("recent_fit_6h"),
      "peak":pkg.get("peak"),
    }

def rerun_selected(hec,row):
    env=dict(os.environ)
    env.update({
      "DUAL_K1_H":str(row["k1"]),"DUAL_K2_H":str(row["k2"]),"DUAL_K3_H":str(row["k3"]),
      "DUAL_X":"0.2","DUAL_WARMUP_H":str(row["warmup_h"])
    })
    cp=subprocess.run([sys.executable,"-B",str(SCRIPT),hec],cwd=ROOT,env=env,text=True,capture_output=True)
    print(cp.stdout)
    print(cp.stderr,file=sys.stderr)
    if cp.returncode!=0: raise SystemExit(cp.returncode)
    return json.loads(RESULT.read_text(encoding="utf-8"))

def main():
    if len(sys.argv)<2: raise SystemExit("usage: iterative_validation /path/to/hec-hms.sh")
    hec=sys.argv[1]
    all_rows=[]
    accepted=[]
    seen=set()
    candidates=BASE_STAGE

    for stage_i in (1,2,3):
        stage_rows=[]
        for cand in candidates:
            if cand in seen: continue
            seen.add(cand)
            row=run_one(hec,*cand)
            row["stage"]=stage_i
            stage_rows.append(row); all_rows.append(row)
            if row.get("accepted"):
                accepted.append(row)

        if accepted:
            break

        executed=[x for x in all_rows if x.get("ok")]
        best_so_far=min(executed,key=lambda x:x["score"],default=None)
        print("CALIBRATION_STAGE_INCOMPLETE="+json.dumps({
          "stage":stage_i,
          "best":best_so_far,
          "next_action":"refine_internal_state_and_routing_around_best"
        },ensure_ascii=False))

        if stage_i==1:
            candidates=adaptive_candidates(best_so_far,0.15,1)
        elif stage_i==2:
            candidates=adaptive_candidates(best_so_far,0.08,1)

    valid=[x for x in all_rows if x.get("ok")]
    if not valid: raise SystemExit("all calibration candidates failed to execute")

    if accepted:
        selected=min(accepted,key=lambda x:x["score"])
        status="VALIDATED"
    else:
        selected=min(valid,key=lambda x:x["score"])
        status="CALIBRATION_PENDING"

    pkg=rerun_selected(hec,selected)
    values,passed,accepted_now=checks(pkg)
    final_status="VALIDATED" if accepted_now else "CALIBRATION_PENDING"

    pkg["operational_validation"]={
      "status":final_status,
      "policy":"iterate candidates until objective hydrologic criteria pass; do not treat incomplete calibration as a final operational forecast",
      "limits":LIMITS,
      "values":values,
      "checks":passed,
      "selected":{
        "k1_h":selected["k1"],"k2_h":selected["k2"],"k3_h":selected["k3"],
        "x":0.2,"warmup_h":selected["warmup_h"],"score":selected["score"],
      },
      "stages_attempted":max(x.get("stage",0) for x in all_rows),
      "candidate_count":len(all_rows),
      "accepted_candidate_count":sum(1 for x in all_rows if x.get("accepted")),
      "candidates":all_rows,
    }

    # "publishable" now means objective validation completed, not just executable.
    pkg["publishable"]=bool(accepted_now)
    RESULT.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("OPERATIONAL_VALIDATION="+json.dumps({
      "status":final_status,
      "selected":pkg["operational_validation"]["selected"],
      "values":values,"checks":passed,
      "peak":pkg.get("peak")
    },ensure_ascii=False))

    # Exit 0 even when calibration remains pending so the workflow can publish
    # diagnostics and the next automated cycle can continue from fresh data.
    # Final chart generation must require status == VALIDATED.

if __name__=="__main__":
    main()
