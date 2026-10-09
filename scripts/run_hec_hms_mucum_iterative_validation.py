#!/usr/bin/env python3
"""Iterative operational calibration for Muçum.

A failed candidate is not the end of the workflow. The controller keeps the
observed rainfall and observed discharge boundaries fixed, searches only
physically interpretable HEC-HMS state/routing/loss parameters, and reruns the
model until the objective launch-state and recent-hydrograph criteria pass.

If the search budget is exhausted, the best candidate is retained internally
with status RECALIBRATING and becomes the seed of the next fresh-data cycle.
It is never relabeled as validated by relaxing the acceptance thresholds.

Research/decision-support only; not an official alert.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
RESULT=OUT/"hec_hms_dual_boundary_mucum_latest.json"
SCRIPT=ROOT/"scripts/run_hec_hms_mucum_dual_boundary.py"

LIMITS={
    "abs_stage_error_cm": 10.0,
    "abs_slope_error_cm_h": 12.0,
    "rmse6h_cm": 35.0,
    "abs_bias6h_cm": 15.0,
    "min_nse6h": 0.50,
    "min_nse12h": 0.75,
    "min_lag_corr": 0.98,
    "max_lag_rmse_m3s": 150.0,
    "min_rain_stations": 40,
    "min_flow_q_stations": 30,
    "max_boundary_age_h": 2.0,
    "max_live_obs_age_minutes": 45.0,
    "max_live_t0_lag_minutes": 15.0,
    "max_latest_stage_error_cm": 10.0,
    "max_live_boundary_age_h": 2.0,
    "max_ifs_age_h": 15.0,
}
MAX_CANDIDATES=240

DEFAULT={
    "k1":1.25,"k2":1.25,"k3":1.00,"x":0.20,"warmup_h":8,
    "memory_tau_h":3.0,
    "dn_initial_loss_scale":1.0,
    "dn_constant_loss_scale":1.0,
    "dn_tc_scale":1.0,
    "dn_storage_scale":1.0,
    "dn_recession_scale":1.0,
    "dn_flow_ratio_scale":1.0,
}

def clamp(v,lo,hi):
    return max(lo,min(hi,float(v)))

def norm(c):
    # Keep only actual parameter keys. Candidate rows also carry score,
    # accepted/current/metrics metadata; letting those fields survive here
    # caused an old score/accepted flag to overwrite the newly computed result
    # when **c was expanded in run_one.
    src=c or {}
    x=dict(DEFAULT)
    for k in DEFAULT:
        if k in src and src.get(k) is not None:
            x[k]=src[k]
    x["k1"]=round(clamp(x["k1"],0.50,4.00),3)
    x["k2"]=round(clamp(x["k2"],0.50,4.00),3)
    x["k3"]=round(clamp(x["k3"],0.40,3.00),3)
    x["x"]=round(clamp(x["x"],0.05,0.35),3)
    x["warmup_h"]=int(round(clamp(x["warmup_h"],3,24)))
    x["memory_tau_h"]=round(clamp(x["memory_tau_h"],0.75,8.0),3)
    for k in ("dn_initial_loss_scale","dn_constant_loss_scale","dn_tc_scale","dn_storage_scale"):
        x[k]=round(clamp(x[k],0.45,1.80),3)
    x["dn_recession_scale"]=round(clamp(x["dn_recession_scale"],0.75,1.20),3)
    # Initial residual flow is an event-state variable, not a fixed historical
    # calibration coefficient. During a wet/flood recession, the observed
    # ungauged incremental contribution can be tens of times the dry-event
    # library seed (0.005 m3/s/km2). Allow the optimizer to represent that
    # stored water explicitly instead of compensating with a vertical stage shift.
    x["dn_flow_ratio_scale"]=round(clamp(x["dn_flow_ratio_scale"],0.20,80.0),3)
    return x

PARAM_KEYS=tuple(DEFAULT.keys())

def ckey(c):
    c=norm(c)
    return tuple(c[k] for k in PARAM_KEYS)

def val(x, default=999.0):
    try:
        if x is None: return default
        v=float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default

def boundary_age_h(pkg, key):
    from datetime import datetime
    cur=(pkg.get("current") or {}).get("observed_time_local")
    b=((pkg.get("boundary_audit") or {}).get(key) or {}).get("last_observed_local")
    if not cur or not b: return 999.0
    try:
        return max(0.0,(datetime.fromisoformat(cur)-datetime.fromisoformat(b)).total_seconds()/3600.0)
    except Exception:
        return 999.0


def latest_live_audit(pkg):
    """Post-run audit: independently recheck fresh Muçum, upstream and IFS inputs."""
    result={"live_obs_age_minutes":999.0,"t0_lag_minutes":999.0,
            "latest_stage_error_cm":999.0,"ljj_age_h_live":999.0,
            "carreiro_age_h_live":999.0,"ifs_age_h":999.0,
            "rain_antecedent_representative":False,"spatial_residual_rain":False}
    try:
        live=json.loads((ROOT/"previsao_ao_vivo_mucum.json").read_text(encoding="utf-8"))
        future=json.loads((OUT/"hec_twin_ifs_spatial_forcing_5d_latest.json").read_text(encoding="utf-8"))
        latest=datetime.fromisoformat(str(live["telemetria_ultima_em"]))
        at_t0=datetime.fromisoformat(str((pkg.get("current") or {})["observed_time_local"]))
        now=datetime.now(timezone.utc)
        local_now=now.astimezone(timezone(timedelta(hours=-3))).replace(tzinfo=None)
        age=(local_now-latest).total_seconds()/60.0
        if age < -15.0: return result
        result["live_obs_age_minutes"]=max(0.0,age)
        result["t0_lag_minutes"]=abs((latest-at_t0).total_seconds())/60.0
        result["spatial_residual_rain"]=bool((pkg.get("observed_network_audit") or {}).get("rain_future_by_residual_subbasin"))
        result["rain_antecedent_representative"]=bool((future.get("antecedent_rain") or {}).get("representative"))
        ifs_at=datetime.fromisoformat(str(future["generated_at_utc"]).replace("Z","+00:00"))
        result["ifs_age_h"]=max(0.0,(now-ifs_at).total_seconds()/3600.0)
        for source,key in (("linha_jose_julio","ljj_age_h_live"),("passo_carreiro","carreiro_age_h_live")):
            b=(pkg.get("boundary_audit") or {}).get(source) or {}
            when=datetime.fromisoformat(str(b["last_observed_local"]))
            result[key]=max(0.0,(latest-when).total_seconds()/3600.0)
        times=[datetime.fromisoformat(t) for t in pkg.get("times_local") or []]
        stages=pkg.get("stage_cm_raw") or []
        if len(times)==len(stages) and times and times[0]<=latest<=times[-1]:
            if latest in times:
                mod=float(stages[times.index(latest)])
            else:
                i=next(i for i in range(len(times)-1) if times[i]<latest<times[i+1])
                w=(latest-times[i]).total_seconds()/(times[i+1]-times[i]).total_seconds()
                mod=float(stages[i])*(1-w)+float(stages[i+1])*w
            result["latest_stage_error_cm"]=abs(mod-float(live["telemetria_ultima_nivel_cm"]))
    except (ValueError,KeyError,TypeError,IndexError,OSError,StopIteration):
        return result
    return result

def checks(pkg):
    cur=pkg.get("current") or {}
    fit6=pkg.get("recent_fit_6h") or {}
    fit12=pkg.get("recent_fit_12h") or {}
    net=pkg.get("observed_network_audit") or {}
    lag=(((pkg.get("boundary_audit") or {}).get("observed_event_lag") or {}).get("best") or {})
    values={
      "abs_stage_error_cm":abs(val(cur.get("stage_error_cm"))),
      "abs_slope_error_cm_h":abs(val(cur.get("slope_error_cm_h"))),
      "rmse6h_cm":val(fit6.get("raw_rmse_cm")),
      "abs_bias6h_cm":abs(val(fit6.get("raw_bias_cm"))),
      "nse6h":val(fit6.get("nse"),-999),
      "nse12h":val(fit12.get("nse"),-999),
      "lag_corr":val(lag.get("corr"),-999),
      "lag_rmse_m3s":val(lag.get("rmse_m3s")),
      "rain_station_count":int(net.get("rain_valid_station_count") or 0),
      "flow_q_station_count":int(net.get("flow_stations_with_q") or 0),
      "ljj_age_h":boundary_age_h(pkg,"linha_jose_julio"),
      "carreiro_age_h":boundary_age_h(pkg,"passo_carreiro"),
      **latest_live_audit(pkg),
    }
    passed={
      "stage":values["abs_stage_error_cm"]<=LIMITS["abs_stage_error_cm"],
      "slope":values["abs_slope_error_cm_h"]<=LIMITS["abs_slope_error_cm_h"],
      "rmse6h":values["rmse6h_cm"]<=LIMITS["rmse6h_cm"],
      "bias6h":values["abs_bias6h_cm"]<=LIMITS["abs_bias6h_cm"],
      "nse6h":values["nse6h"]>=LIMITS["min_nse6h"],
      "nse12h":values["nse12h"]>=LIMITS["min_nse12h"],
      "lag_corr":values["lag_corr"]>=LIMITS["min_lag_corr"],
      "lag_rmse":values["lag_rmse_m3s"]<=LIMITS["max_lag_rmse_m3s"],
      "rain_network":values["rain_station_count"]>=LIMITS["min_rain_stations"],
      "flow_network":values["flow_q_station_count"]>=LIMITS["min_flow_q_stations"],
      "ljj_fresh":values["ljj_age_h"]<=LIMITS["max_boundary_age_h"],
      "carreiro_fresh":values["carreiro_age_h"]<=LIMITS["max_boundary_age_h"],
      "live_observation_fresh":values["live_obs_age_minutes"]<=LIMITS["max_live_obs_age_minutes"],
      "t0_is_latest":values["t0_lag_minutes"]<=LIMITS["max_live_t0_lag_minutes"],
      "latest_observed_stage_match":values["latest_stage_error_cm"]<=LIMITS["max_latest_stage_error_cm"],
      "ljj_fresh_live":values["ljj_age_h_live"]<=LIMITS["max_live_boundary_age_h"],
      "carreiro_fresh_live":values["carreiro_age_h_live"]<=LIMITS["max_live_boundary_age_h"],
      "ifs_fresh":values["ifs_age_h"]<=LIMITS["max_ifs_age_h"],
      "rain_antecedent_representative":values["rain_antecedent_representative"],
      "spatial_residual_rain":values["spatial_residual_rain"],
    }
    return values,passed,all(passed.values())

def score(pkg):
    values,passed,_=checks(pkg)
    s=(
      values["abs_stage_error_cm"]
      +1.35*values["abs_slope_error_cm_h"]
      +0.35*values["rmse6h_cm"]
      +0.12*values["abs_bias6h_cm"]
    )
    if values["nse6h"]<LIMITS["min_nse6h"]:
        s += 55.0*(LIMITS["min_nse6h"]-values["nse6h"])
    if values["nse12h"]<LIMITS["min_nse12h"]:
        s += 45.0*(LIMITS["min_nse12h"]-values["nse12h"])
    # Data freshness is not calibrated away; penalize it so the audit remains
    # obvious, but never modify observations to make the model pass.
    for k in ("rain_network","flow_network","ljj_fresh","carreiro_fresh","lag_corr","lag_rmse",
              "live_observation_fresh","t0_is_latest","latest_observed_stage_match",
              "ljj_fresh_live","carreiro_fresh_live","ifs_fresh",
              "rain_antecedent_representative","spatial_residual_rain"):
        if not passed[k]: s += 25.0
    return s

def env_for(c):
    c=norm(c)
    env=dict(os.environ)
    env.update({
      "DUAL_K1_H":str(c["k1"]),
      "DUAL_K2_H":str(c["k2"]),
      "DUAL_K3_H":str(c["k3"]),
      "DUAL_X":str(c["x"]),
      "DUAL_WARMUP_H":str(c["warmup_h"]),
      "DUAL_MEMORY_TAU_H":str(c["memory_tau_h"]),
      "DUAL_DN_INITIAL_LOSS_SCALE":str(c["dn_initial_loss_scale"]),
      "DUAL_DN_CONSTANT_LOSS_SCALE":str(c["dn_constant_loss_scale"]),
      "DUAL_DN_TC_SCALE":str(c["dn_tc_scale"]),
      "DUAL_DN_STORAGE_SCALE":str(c["dn_storage_scale"]),
      "DUAL_DN_RECESSION_SCALE":str(c["dn_recession_scale"]),
      "DUAL_DN_FLOW_RATIO_SCALE":str(c["dn_flow_ratio_scale"]),
    })
    return env

def run_one(hec,c):
    c=norm(c)
    cp=subprocess.run([sys.executable,"-B",str(SCRIPT),hec],cwd=ROOT,env=env_for(c),text=True,capture_output=True)
    if cp.returncode!=0:
        return {"ok":False,**c,"stderr":cp.stderr[-1600:]}
    pkg=json.loads(RESULT.read_text(encoding="utf-8"))
    values,passed,accepted=checks(pkg)
    return {
      "ok":True,"accepted":accepted,"score":round(score(pkg),6),
      **c,"values":values,"passed":passed,
      "current":pkg.get("current"),
      "recent_fit_6h":pkg.get("recent_fit_6h"),
      "recent_fit_12h":pkg.get("recent_fit_12h"),
      "peak":pkg.get("peak"),
    }

def rerun_selected(hec,row):
    cp=subprocess.run([sys.executable,"-B",str(SCRIPT),hec],cwd=ROOT,env=env_for(row),text=True,capture_output=True)
    print(cp.stdout); print(cp.stderr,file=sys.stderr)
    if cp.returncode!=0: raise SystemExit(cp.returncode)
    return json.loads(RESULT.read_text(encoding="utf-8"))

def previous_seed():
    if not RESULT.exists(): return None
    try:
        old=json.loads(RESULT.read_text(encoding="utf-8"))
        sel=((old.get("operational_validation") or {}).get("selected") or {})
        topo=((old.get("topology") or {}).get("live_calibration_controls") or {})
        if not sel: return None
        return norm({
          "k1":sel.get("k1_h"),"k2":sel.get("k2_h"),"k3":sel.get("k3_h"),
          "x":sel.get("x"),"warmup_h":sel.get("warmup_h"),
          "memory_tau_h":sel.get("memory_tau_h",topo.get("memory_tau_h",3.0)),
          "dn_initial_loss_scale":sel.get("dn_initial_loss_scale",topo.get("dn_initial_loss_scale",1.0)),
          "dn_constant_loss_scale":sel.get("dn_constant_loss_scale",topo.get("dn_constant_loss_scale",1.0)),
          "dn_tc_scale":sel.get("dn_tc_scale",topo.get("dn_tc_scale",1.0)),
          "dn_storage_scale":sel.get("dn_storage_scale",topo.get("dn_storage_scale",1.0)),
          "dn_recession_scale":sel.get("dn_recession_scale",topo.get("dn_recession_scale",1.0)),
          "dn_flow_ratio_scale":sel.get("dn_flow_ratio_scale",topo.get("dn_flow_ratio_scale",1.0)),
        })
    except Exception:
        return None

def base_candidates():
    out=[]
    prev=previous_seed()
    if prev: out.append(prev)
    for k1,k2,k3 in [
      (1.00,1.00,0.75),(1.00,1.00,1.00),(1.25,1.25,1.00),
      (1.25,1.25,1.25),(1.50,1.50,1.00)
    ]:
      for warm in (4,6,8,10,12):
        out.append(norm({"k1":k1,"k2":k2,"k3":k3,"warmup_h":warm}))
    return out

def route_refine(best,step=0.12):
    if not best:return []
    b=norm(best);out=[]
    for d1,d2,d3 in [
      (-step,-step,0),(step,step,0),(0,0,-step),(0,0,step),
      (-step,0,0),(step,0,0),(0,-step,0),(0,step,0),
      (-step,-step,-step),(step,step,step)
    ]:
      x=dict(b);x["k1"]+=d1;x["k2"]+=d2;x["k3"]+=d3;out.append(norm(x))
    for dw in (-2,-1,1,2):
      x=dict(b);x["warmup_h"]+=dw;out.append(norm(x))
    return out

def memory_x_candidates(best):
    if not best:return []
    b=norm(best);out=[]
    for x in (0.10,0.15,0.20,0.25,0.30):
      q=dict(b);q["x"]=x;out.append(norm(q))
    for tau in (1.0,1.5,2.0,3.0,4.5,6.0):
      q=dict(b);q["memory_tau_h"]=tau;out.append(norm(q))
    for x,tau in ((0.15,1.5),(0.15,4.5),(0.25,1.5),(0.25,4.5),(0.30,3.0)):
      q=dict(b);q["x"]=x;q["memory_tau_h"]=tau;out.append(norm(q))
    return out

def joint_wave_candidates(best):
    """Search state+travel-time together, not only along one coordinate.

    A fast current rising limb after a deep recession cannot be identified by
    changing a constant baseflow term alone. The observed Antas/Carreiro waves
    constrain travel time; wet-state flow and retention remain bounded HEC
    state parameters. All candidates still face the unmodified full audit.
    """
    b=norm(best or previous_seed() or DEFAULT)
    out=[]
    for k1,k2,k3 in (
        (0.75,0.75,0.75),(1.00,1.00,0.75),
        (1.25,1.25,1.00),(1.80,1.80,1.25),
        (2.50,2.50,1.00),(3.20,3.20,1.50)):
        for fr in (8,18,30,42,52):
            q=dict(b)
            q.update(k1=k1,k2=k2,k3=k3,warmup_h=12,
                     dn_flow_ratio_scale=fr)
            out.append(norm(q))
    # Joint adjustments of recession and routing; not vertical stage-shifting.
    for k,fr,rec in ((0.75,8,0.75),(1.25,18,0.85),(1.80,25,0.85),
                     (2.50,30,0.95),(3.20,45,0.95),
                     (1.25,42,0.75),(2.50,52,0.75)):
        q=dict(b)
        q.update(k1=k,k2=k,k3=1.0,warmup_h=12,
                 dn_flow_ratio_scale=fr,dn_recession_scale=rec)
        out.append(norm(q))
    return out

def residual_state_candidates(best):
    """Search the live residual/baseflow state before retuning event physics.

    The current Muçum residual is diagnosed from past observations as a nearly
    constant missing discharge while the hydrograph slope is already correct.
    Therefore initial residual flow is searched over a broad wet-state range
    before changing losses/Clark timing.
    """
    if not best:return []
    b=norm(best);out=[]
    for fr in (3,5,8,12,16,20,25,30,35,40,42,44,45,46,47,48,49,50,51,52,53,55,60,70):
      q=dict(b);q["dn_flow_ratio_scale"]=fr;out.append(norm(q))
    # Recession controls how quickly that assimilated stored-water state decays.
    # Focus tightly around the 45–52 range indicated by the current mass-balance
    # residual, while still keeping broader wet-state candidates.
    for fr,rec in (
      (40,0.95),(42,0.95),(44,0.95),(45,0.95),(46,0.95),(48,0.95),(50,0.95),(52,0.95),
      (42,0.97),(44,0.97),(45,0.97),(46,0.97),(47,0.97),(48,0.97),(49,0.97),(50,0.97),(51,0.97),(52,0.97),
      (42,0.98),(44,0.98),(45,0.98),(46,0.98),(47,0.98),(48,0.98),(49,0.98),(50,0.98),(51,0.98),(52,0.98),
      (44,0.99),(45,0.99),(46,0.99),(47,0.99),(48,0.99),(49,0.99),(50,0.99),(51,0.99),(52,0.99),
      (45,1.0),(46,1.0),(47,1.0),(48,1.0),(49,1.0),(50,1.0),(51,1.0),(52,1.0)
    ):
      q=dict(b);q["dn_flow_ratio_scale"]=fr;q["dn_recession_scale"]=rec;out.append(norm(q))
    return out

def residual_coordinate_candidates(best):
    if not best:return []
    b=norm(best);out=[]
    choices={
      "dn_initial_loss_scale":(0.65,0.80,1.0,1.20,1.40),
      "dn_constant_loss_scale":(0.65,0.80,1.0,1.20,1.40),
      "dn_tc_scale":(0.65,0.80,1.0,1.20,1.40),
      "dn_storage_scale":(0.65,0.80,1.0,1.20,1.40),
      "dn_recession_scale":(0.85,0.95,1.0,1.05,1.12),
      "dn_flow_ratio_scale":(10,20,30,40,45,50,55,60,70),
    }
    for name,vals in choices.items():
      for v in vals:
        q=dict(b);q[name]=v;out.append(norm(q))
    return out

def residual_mixed_candidates(best):
    if not best:return []
    b=norm(best);out=[]
    combos=[
      (0.80,0.80,0.80,0.80),(1.20,1.20,0.80,0.80),
      (0.80,0.80,1.20,1.20),(1.20,1.20,1.20,1.20),
      (0.70,1.15,0.80,0.80),(1.15,0.70,0.80,0.80),
      (0.85,1.25,1.15,0.85),(1.25,0.85,0.85,1.15),
      (0.90,0.90,0.70,1.10),(1.10,1.10,1.10,0.70),
    ]
    for il,cl,tc,st in combos:
      q=dict(b);q.update(dn_initial_loss_scale=il,dn_constant_loss_scale=cl,dn_tc_scale=tc,dn_storage_scale=st);out.append(norm(q))
    for fr,rec in ((20,0.90),(30,0.95),(40,0.98),(45,1.0),(50,1.0),(55,1.0),(60,1.02),(70,1.05)):
      q=dict(b);q["dn_flow_ratio_scale"]=fr;q["dn_recession_scale"]=rec;out.append(norm(q))
    return out

def fine_candidates(best):
    if not best:return []
    b=norm(best);out=[]
    perturb={
      "k1":(-0.06,0.06),"k2":(-0.06,0.06),"k3":(-0.05,0.05),
      "x":(-0.03,0.03),"memory_tau_h":(-0.5,0.5),
      "dn_initial_loss_scale":(-0.10,0.10),
      "dn_constant_loss_scale":(-0.10,0.10),
      "dn_tc_scale":(-0.10,0.10),
      "dn_storage_scale":(-0.10,0.10),
      "dn_flow_ratio_scale":(-5.0,-2.0,2.0,5.0),
    }
    for name,ds in perturb.items():
      for d in ds:
        q=dict(b);q[name]+=d;out.append(norm(q))
    return out

def best_executed(rows):
    xs=[x for x in rows if x.get("ok")]
    return min(xs,key=lambda x:x["score"],default=None)

def main():
    if len(sys.argv)<2: raise SystemExit("usage: iterative_validation /path/to/hec-hms.sh")
    hec=sys.argv[1]
    all_rows=[];accepted=[];seen=set()
    data_blocked=False
    input_gates=("live_observation_fresh","t0_is_latest","ljj_fresh_live",
                 "carreiro_fresh_live","ifs_fresh","rain_antecedent_representative",
                 "spatial_residual_rain")

    stage_builders=[
      lambda best: base_candidates(),
      joint_wave_candidates,
      residual_state_candidates,
      lambda best: route_refine(best,0.15),
      memory_x_candidates,
      residual_coordinate_candidates,
      residual_mixed_candidates,
      fine_candidates,
      lambda best: route_refine(best,0.06)+fine_candidates(best),
    ]

    for stage_i,builder in enumerate(stage_builders,1):
        best_so_far=best_executed(all_rows)
        candidates=builder(best_so_far)
        stage_rows=[]
        for cand in candidates:
            if len(all_rows)>=MAX_CANDIDATES: break
            k=ckey(cand)
            if k in seen: continue
            seen.add(k)
            row=run_one(hec,cand);row["stage"]=stage_i
            stage_rows.append(row);all_rows.append(row)
            if row.get("ok") and any(not row["passed"].get(k,False) for k in input_gates):
                data_blocked=True
                print("BLOCKED_INPUTS="+json.dumps({
                    "failed":[k for k in input_gates if not row["passed"].get(k,False)],
                    "values":row.get("values")},ensure_ascii=False))
                break
            if row.get("accepted"):
                accepted.append(row)
                break
        if accepted or data_blocked or len(all_rows)>=MAX_CANDIDATES:
            break
        best_so_far=best_executed(all_rows)
        print("CALIBRATION_CONTINUES="+json.dumps({
          "stage":stage_i,"candidate_count":len(all_rows),"best":best_so_far,
          "next_action":"expand_search_without_relaxing_validation"
        },ensure_ascii=False))

    valid=[x for x in all_rows if x.get("ok")]
    if not valid: raise SystemExit("all calibration candidates failed to execute")
    selected=min(accepted,key=lambda x:x["score"]) if accepted else min(valid,key=lambda x:x["score"])

    pkg=rerun_selected(hec,selected)
    values,passed,accepted_now=checks(pkg)
    final_status=("BLOCKED_INPUTS" if data_blocked else
                  ("VALIDATED" if accepted_now else "RECALIBRATING"))

    selected_payload={
      "k1_h":selected["k1"],"k2_h":selected["k2"],"k3_h":selected["k3"],
      "x":selected["x"],"warmup_h":selected["warmup_h"],
      "memory_tau_h":selected["memory_tau_h"],
      "dn_initial_loss_scale":selected["dn_initial_loss_scale"],
      "dn_constant_loss_scale":selected["dn_constant_loss_scale"],
      "dn_tc_scale":selected["dn_tc_scale"],
      "dn_storage_scale":selected["dn_storage_scale"],
      "dn_recession_scale":selected["dn_recession_scale"],
      "dn_flow_ratio_scale":selected["dn_flow_ratio_scale"],
      "score":selected["score"],
    }
    pkg["operational_validation"]={
      "status":final_status,
      "policy":"failed candidates trigger automatic recalibration; thresholds are never loosened merely to obtain a publishable result",
      "limits":LIMITS,
      "values":values,
      "checks":passed,
      "selected":selected_payload,
      "stages_attempted":max(x.get("stage",0) for x in all_rows),
      "candidate_count":len(all_rows),
      "search_budget":MAX_CANDIDATES,
      "accepted_candidate_count":sum(1 for x in all_rows if x.get("accepted")),
      "next_cycle_action":None if accepted_now else "resume from best candidate with fresh observations and re-optimize",
      "candidates":all_rows,
    }
    pkg["publishable"]=bool(accepted_now and not data_blocked)
    if data_blocked:
        pkg["last_unvalidated_peak_for_audit"]=pkg.pop("peak",None)
        pkg["peak"]=None
        pkg["warning_pt"]="HEC bloqueado por telemetria/chuva ou fronteira de montante defasada: nenhuma previsão liberada."
    pkg["interdisciplinary_audit"]={
        "hydrometeorology":{"rain_representative":values["rain_antecedent_representative"],
            "spatial_residual_rain":values["spatial_residual_rain"],"ifs_fresh":passed["ifs_fresh"]},
        "upstream_hydrology":{"ljj_fresh":passed["ljj_fresh_live"],
            "carreiro_fresh":passed["carreiro_fresh_live"],"lag_corr":values["lag_corr"]},
        "forecast_validation":{"latest_observation_fresh":passed["live_observation_fresh"],
            "t0_is_latest":passed["t0_is_latest"],
            "stage_matches_latest_obs":passed["latest_observed_stage_match"],
            "nse6h":values["nse6h"],"nse12h":values["nse12h"]},
        "all_gates_passed":bool(accepted_now and not data_blocked),
    }
    RESULT.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("OPERATIONAL_VALIDATION="+json.dumps({
      "status":final_status,"selected":selected_payload,
      "values":values,"checks":passed,"peak":pkg.get("peak"),
      "candidate_count":len(all_rows)
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
