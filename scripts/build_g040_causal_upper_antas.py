#!/usr/bin/env python3
"""Frozen rainfall-runoff forecast for the upper-Antas boundary at 86472000.

Purpose
-------
The G040 downstream HEC model cannot causally reproduce a flood if the
13,000-km2 Linha José Júlio boundary is persisted after decision time. This
module predicts that boundary from rain over the nested Prata + Antas residual
zones.

Calibration is FIXED to E22_SEP2023 + E24_NOV2023. Validation/holdout events
must never influence parameter selection. Observed rain is used only through t0;
exact-run ECMWF rain is used strictly after t0. When an observed 86472000 Q is
available at t0, a decaying state correction is allowed because it is information
available at forecast issue time. No future observed Q is used.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from scripts.hec_twin_nested_v17 import ZoneParams, zone_grid
    from scripts.run_hec_twin_stz_mucum_calibrate import (
        apply_loss, clark_uh, excess_to_flow, recession_baseflow,
    )
except ModuleNotFoundError:
    from hec_twin_nested_v17 import ZoneParams, zone_grid
    from run_hec_twin_stz_mucum_calibrate import (
        apply_loss, clark_uh, excess_to_flow, recession_baseflow,
    )

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
STUDY=ROOT/"assets/data/estudo_bacia_taquari_antas"
OBSROOT=BASE/"historical_calibration_forcing"
HYDRO=BASE/"historical_hydro_events"
CFG=ROOT/"config/g040_causal_frozen_benchmark_v1.json"
STRUCT=STUDY/"estrutura_stz_mucum_latest.json"
MODEL=BASE/"g040_upper_antas_model_frozen_latest.json"
CAL_EVENTS=("E22_SEP2023","E24_NOV2023")
PRIMARY="86472000"
Z_PRATA="SB_PRATA_7868"
Z_ANTAS="SB_ANTAS_RESIDUAL"
BRT=ZoneInfo("America/Sao_Paulo")
UTC=timezone.utc
STATE_CORRECTION_TAU_H=24.0

def load(path:Path)->dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def utc(value:str)->datetime:
    d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if d.tzinfo is None:
        d=d.replace(tzinfo=UTC)
    return d.astimezone(UTC)

def local_to_utc(value:str)->datetime:
    d=datetime.fromisoformat(str(value))
    if d.tzinfo is None:
        d=d.replace(tzinfo=BRT)
    return d.astimezone(UTC)

def iso(t:datetime)->str:
    return t.astimezone(UTC).isoformat().replace("+00:00","Z")

def areas()->dict[str,float]:
    j=load(STRUCT)
    return {
        str(e["id"]):float(e["area_km2"])
        for e in j["models"]["mucum"]["elements"]
        if e.get("type")=="subbasin"
    }

def zone_rows(pkg:dict[str,Any], forecast:bool)->dict[str,dict[datetime,float]]:
    root=(pkg.get("upper_antas_nested_forcing") or {})
    out={}
    for z in root.get("zones") or []:
        sid=str(z.get("subbasin_id") or "")
        rows={}
        for r in z.get("series") or []:
            key="time_utc" if forecast else "time_local"
            if r.get(key) is None or r.get("mm") is None:
                continue
            t=utc(r[key]) if forecast else local_to_utc(r[key])
            x=float(r["mm"])
            if not math.isfinite(x) or x<0:
                continue
            rows[t]=x
        out[sid]=rows
    return out

def hourly_axis(start:datetime,end:datetime)->list[datetime]:
    t=start.replace(minute=0,second=0,microsecond=0)
    end=end.replace(minute=0,second=0,microsecond=0)
    out=[]
    while t<=end:
        out.append(t); t+=timedelta(hours=1)
    return out

def simulate_upper(prata:list[float],antas:list[float],p:ZoneParams,a:dict[str,float])->list[float]:
    if len(prata)!=len(antas):
        raise ValueError("upper-Antas rain lengths differ")
    ap=float(a[Z_PRATA]); aa=float(a[Z_ANTAS]); total=ap+aa
    rain=[(float(x)*ap+float(y)*aa)/total for x,y in zip(prata,antas)]
    excess=apply_loss(rain,float(p.initial_loss),float(p.constant_loss))
    direct=excess_to_flow(excess,total,clark_uh(float(p.tc),float(p.storage)))
    base=recession_baseflow(len(rain),total,float(p.initial_flow_ratio),float(p.recession))
    return [max(0.0,float(d)+float(b)) for d,b in zip(direct,base)]

def primary_station(event_id:str)->dict[str,Any]:
    j=load(HYDRO/f"{event_id}.json")
    return next((s for s in j.get("stations") or [] if str(s.get("code"))==PRIMARY),{})

def observed_q(event_id:str)->dict[datetime,float]:
    st=primary_station(event_id)
    out={}
    for r in st.get("series") or []:
        if not r.get("time_utc") or r.get("flow_m3s") is None:
            continue
        q=float(r["flow_m3s"])
        if math.isfinite(q) and q>=0:
            out[utc(r["time_utc"])]=q
    return out

def calibration_rain(event_id:str)->tuple[list[datetime],list[float],list[float]]:
    pkg=load(OBSROOT/event_id/"rain.json")
    z=zone_rows(pkg,forecast=False)
    if Z_PRATA not in z or Z_ANTAS not in z:
        raise RuntimeError(f"{event_id}: upper nested observed rain missing")
    common=sorted(set(z[Z_PRATA])&set(z[Z_ANTAS]))
    if not common:
        raise RuntimeError(f"{event_id}: no paired upper rain")
    axis=hourly_axis(common[0],common[-1])
    missing=[t for t in axis if t not in z[Z_PRATA] or t not in z[Z_ANTAS]]
    if missing:
        raise RuntimeError(f"{event_id}: upper observed rain has {len(missing)} missing hours; first={iso(missing[0])}")
    return axis,[z[Z_PRATA][t] for t in axis],[z[Z_ANTAS][t] for t in axis]

def metrics(times:list[datetime],sim:list[float],obs:dict[datetime,float])->dict[str,float]:
    pairs=[(i,obs[t]) for i,t in enumerate(times) if t in obs]
    if len(pairs)<24:
        return {"pairs":float(len(pairs)),"nse":float("-inf"),"peak_relative_error":9.0,"peak_lag_hours":99.0,"volume_error":9.0}
    oo=[float(q) for _,q in pairs]; ss=[float(sim[i]) for i,_ in pairs]
    mean=sum(oo)/len(oo)
    den=sum((x-mean)**2 for x in oo) or 1e-9
    nse=1.0-sum((o-s)**2 for o,s in zip(oo,ss))/den
    oi=max(range(len(oo)),key=lambda i:oo[i]); si=max(range(len(ss)),key=lambda i:ss[i])
    peak_err=abs(ss[si]-oo[oi])/max(oo[oi],1e-9)
    lag=(pairs[si][0]-pairs[oi][0])
    vol=(sum(ss)-sum(oo))/max(sum(oo),1e-9)
    return {
        "pairs":float(len(pairs)),
        "nse":float(nse),
        "peak_relative_error":float(peak_err),
        "peak_lag_hours":float(lag),
        "volume_error":float(vol),
        "observed_peak_m3s":float(oo[oi]),
        "simulated_peak_m3s":float(ss[si]),
    }

def score(m:dict[str,float])->float:
    if not math.isfinite(float(m["nse"])):
        return -1e9
    return (
        float(m["nse"])
        -1.25*abs(float(m["peak_relative_error"]))
        -0.02*abs(float(m["peak_lag_hours"]))
        -0.40*abs(float(m["volume_error"]))
    )

def params_dict(p:ZoneParams)->dict[str,float]:
    return {
        "initial_loss":float(p.initial_loss),
        "constant_loss":float(p.constant_loss),
        "tc":float(p.tc),
        "storage":float(p.storage),
        "recession":float(p.recession),
        "initial_flow_ratio":float(p.initial_flow_ratio),
    }

def params_from_dict(d:dict[str,Any])->ZoneParams:
    return ZoneParams(**{k:float(d[k]) for k in (
        "initial_loss","constant_loss","tc","storage","recession","initial_flow_ratio"
    )})

def calibrate()->dict[str,Any]:
    a=areas()
    packs={}
    for eid in CAL_EVENTS:
        times,prata,antas=calibration_rain(eid)
        q=observed_q(eid)
        if len(q)<24:
            raise RuntimeError(f"{eid}: insufficient 86472000 calibration flow")
        packs[eid]=(times,prata,antas,q)

    rows=[]
    for p in zone_grid():
        em={}
        scores=[]
        for eid,(times,prata,antas,q) in packs.items():
            sim=simulate_upper(prata,antas,p,a)
            m=metrics(times,sim,q)
            em[eid]=m; scores.append(score(m))
        rows.append((sum(scores)/len(scores),p,em))
    rows.sort(key=lambda x:x[0],reverse=True)
    best_score,best,best_metrics=rows[0]
    payload={
        "schema_version":"g040_upper_antas_model_frozen_v1",
        "generated_at_utc":datetime.now(UTC).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"UPPER_ANTAS_FROZEN_CALIBRATION_READY",
        "station_code":PRIMARY,
        "calibration_events":list(CAL_EVENTS),
        "validation_events_excluded_from_selection":["E27_MAY2024","E28_JUN2024","E2026_JUL"],
        "candidate_count":len(rows),
        "parameters":params_dict(best),
        "objective":round(float(best_score),6),
        "event_metrics":best_metrics,
        "state_correction_tau_h":STATE_CORRECTION_TAU_H,
        "no_validation_leakage":True,
        "model_structure":"Prata + Antas residual area-weighted rain; Initial+Constant loss; Clark transform; recession baseflow",
        "areas_km2":{Z_PRATA:a[Z_PRATA],Z_ANTAS:a[Z_ANTAS]},
        "promotion_allowed":False,
    }
    MODEL.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return payload

def case_config(case_id:str)->tuple[dict[str,Any],dict[str,Any]]:
    cfg=load(CFG)
    case=next((c for c in cfg.get("cases") or [] if c.get("case_id")==case_id),None)
    if case is None:
        raise KeyError(case_id)
    return cfg,case

def combined_case_rain(event_id:str,forecast:dict[str,Any],t0:datetime,end:datetime):
    obs=load(OBSROOT/event_id/"rain.json")
    oz=zone_rows(obs,forecast=False); fz=zone_rows(forecast,forecast=True)
    for sid in (Z_PRATA,Z_ANTAS):
        if sid not in oz or sid not in fz:
            raise RuntimeError(f"{event_id}: {sid} missing observed or forecast nested forcing")
    start=max(min(oz[Z_PRATA]),min(oz[Z_ANTAS]))
    axis=hourly_axis(start,end)
    p1=[];p2=[];src=[]
    for t in axis:
        if t<=t0:
            a=oz[Z_PRATA].get(t); b=oz[Z_ANTAS].get(t); source="observed"
        else:
            a=fz[Z_PRATA].get(t); b=fz[Z_ANTAS].get(t); source="ecmwf_exact_single_run"
        if a is None or b is None:
            raise RuntimeError(f"{event_id}: upper causal rain missing {iso(t)} source={source}")
        p1.append(float(a));p2.append(float(b));src.append(source)
    return axis,p1,p2,src

def last_q_at_or_before(event_id:str,t0:datetime)->tuple[datetime,float]|None:
    rows=[(t,q) for t,q in observed_q(event_id).items() if t<=t0]
    return max(rows,key=lambda x:x[0]) if rows else None

def forecast_case(case_id:str,forecast_file:Path,output:Path)->dict[str,Any]:
    if not MODEL.exists():
        raise RuntimeError("frozen upper-Antas model missing; run --calibrate")
    model=load(MODEL)
    if model.get("calibration_events")!=list(CAL_EVENTS) or model.get("no_validation_leakage") is not True:
        raise RuntimeError("upper-Antas model does not satisfy frozen split")
    cfg,case=case_config(case_id)
    event_id=str(case["event_id"])
    t0=utc(case["decision_time_utc"])
    end=t0+timedelta(hours=int(cfg["forecast_horizon_hours"]))
    forecast=load(forecast_file)
    if forecast.get("status")!="EXACT_ECMWF_SINGLE_RUN_READY":
        raise RuntimeError("exact ECMWF package not ready")
    axis,prata,antas,sources=combined_case_rain(event_id,forecast,t0,end)
    p=params_from_dict(model["parameters"])
    raw=simulate_upper(prata,antas,p,areas())

    last=last_q_at_or_before(event_id,t0)
    idx0=min(range(len(axis)),key=lambda i:abs((axis[i]-t0).total_seconds()))
    corrected=list(raw)
    correction=None
    if last is not None:
        ot,oq=last
        delta=float(oq)-float(raw[idx0])
        for i,t in enumerate(axis):
            if t<t0:
                continue
            h=max(0.0,(t-t0).total_seconds()/3600.0)
            corrected[i]=max(0.0,float(raw[i])+delta*math.exp(-h/STATE_CORRECTION_TAU_H))
        correction={
            "applied":True,
            "last_observed_q_time_utc":iso(ot),
            "last_observed_q_m3s":round(float(oq),3),
            "raw_model_q_at_t0_m3s":round(float(raw[idx0]),3),
            "initial_additive_error_m3s":round(float(delta),3),
            "tau_h":STATE_CORRECTION_TAU_H,
        }
    else:
        correction={
            "applied":False,
            "reason":"no 86472000 Q available at/before t0; warm-up rainfall-runoff state used without downstream-target substitution",
            "tau_h":STATE_CORRECTION_TAU_H,
        }

    obs=observed_q(event_id)
    verification=metrics(axis,corrected,obs) if obs else None
    rows=[
        {
            "time_utc":iso(t),
            "flow_m3s":round(float(q),3),
            "raw_model_flow_m3s":round(float(qr),3),
            "rain_source":sources[i],
        }
        for i,(t,q,qr) in enumerate(zip(axis,corrected,raw))
    ]
    payload={
        "schema_version":"g040_upper_antas_causal_boundary_v1",
        "generated_at_utc":datetime.now(UTC).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"UPPER_ANTAS_CAUSAL_BOUNDARY_READY",
        "case_id":case_id,
        "event_id":event_id,
        "station_code":PRIMARY,
        "decision_time_utc":iso(t0),
        "forecast_end_utc":iso(end),
        "model_ref":str(MODEL.relative_to(ROOT)),
        "parameters":model["parameters"],
        "calibration_events":model["calibration_events"],
        "validation_event_used_for_selection":False,
        "future_observed_flow_used":False,
        "future_observed_rain_used":False,
        "future_rain_source":"exact ECMWF single run",
        "state_correction":correction,
        "verification_not_used_for_forcing_or_selection":verification,
        "series":rows,
        "promotion_allowed":False,
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return payload

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--calibrate",action="store_true")
    ap.add_argument("--case-id")
    ap.add_argument("--forecast-file",type=Path)
    ap.add_argument("--output",type=Path)
    args=ap.parse_args()
    if args.calibrate:
        print(json.dumps(calibrate(),ensure_ascii=False))
        return 0
    if not args.case_id or not args.forecast_file or not args.output:
        raise SystemExit("forecast mode requires --case-id --forecast-file --output")
    out=forecast_case(args.case_id,args.forecast_file,args.output)
    print(json.dumps({
        "status":out["status"],"case_id":out["case_id"],
        "state_correction":out["state_correction"],
        "verification":out["verification_not_used_for_forcing_or_selection"],
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
