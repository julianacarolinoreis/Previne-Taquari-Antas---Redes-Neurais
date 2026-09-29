#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pseudo-operational benchmark of event-conditioned Muçum forecasting.

Research-only. Replays E24, E27 and E28 with frozen forecast cutoffs and
strictly excludes the target event and future events from the candidate library.

Historical forcing scenario implemented here is P2 ("perfect future rainfall"):
fresh ANA rain is used after t0 only to isolate hydrologic/model-selection error.
The real 28/09/2026 case remains the P1 prospective case with ECMWF.

Arms:
A fixed prior-median parameterization
B rainfall-analog family only
C hydrologic lookback family selection
D C + local online recalibration using observations only up to t0

All historical source data are freshly downloaded from ANA on the GitHub runner.
"""
from __future__ import annotations

import copy
import csv
import json
import math
import statistics
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from hec_twin_nested_v17 import NestedParams, ZoneParams
from run_hec_twin_stz_mucum_calibrate import run_network

BASE=ROOT/"assets/data/estudo_bacia_taquari_antas"
MODEL=BASE/"modelo_mucum_eventwise_v1_fechado_latest.json"
STRUCT=BASE/"estrutura_stz_mucum_latest.json"
CURVE=BASE/"curva_chave_86472600/curva_chave_hunt_86472600_latest.json"
OUT=BASE/"scientific_benchmark_v1/pseudo_operational_p2"
OUT.mkdir(parents=True,exist_ok=True)

ANA_PRIMARY="https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ANA_MIRROR="https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/DadosHidrometeorologicos"
UA="PREVINE-mucum-pseudo-operational-benchmark/1.0"

EVENTS={
 "E20":("2023-06-15 20:00:00","2023-06-19 12:00:00"),
 "E21":("2023-07-10 09:00:00","2023-07-16 22:00:00"),
 "E22":("2023-09-04 00:00:00","2023-09-12 07:00:00"),
 "E23":("2023-09-19 19:00:00","2023-09-22 16:00:00"),
 "E24":("2023-11-16 00:00:00","2023-11-25 23:00:00"),
 "E25":("2024-01-18 17:00:00","2024-01-21 06:00:00"),
 "E27":("2024-04-29 16:00:00","2024-05-09 20:00:00"),
 "E28":("2024-06-16 10:00:00","2024-06-25 02:00:00"),
}
TARGETS=("E24","E27","E28")
STATIONS=("86472000","2851072","86507000","86472600","86510000")
RAIN_PREF={
 "SB_PRATA_7868":["86472000","2851072","86507000"],
 "SB_ANTAS_RESIDUAL":["86472000","2851072","86507000"],
 "SB_CARREIRO_7866":["86507000","86472000","86510000","2851072"],
 "SB_STZ_RESIDUAL":["86472600","86472000","86510000","2851072"],
 "SB_INC_MUCUM":["86510000","86472600","86472000"],
}
PAD_H=24

def load(p:Path): return json.loads(p.read_text(encoding="utf-8"))

def lname(tag:str)->str: return tag.rsplit("}",1)[-1]

def fnum(v):
    if v is None:return None
    s=str(v).strip().replace(",",".")
    if not s:return None
    try:x=float(s)
    except ValueError:return None
    return x if math.isfinite(x) else None

def ptime(v):
    s=str(v or "").strip().replace("T"," ")
    for fmt in ("%Y-%m-%d %H:%M:%S","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M"):
        try:return datetime.strptime(s[:19],fmt)
        except ValueError:pass
    return None

def fetch_ana(code,start,end):
    params=urllib.parse.urlencode({"codEstacao":code,"dataInicio":start.strftime("%d/%m/%Y"),"dataFim":end.strftime("%d/%m/%Y")})
    errs=[]
    for base in (ANA_PRIMARY,ANA_MIRROR):
        url=base+"?"+params
        try:
            req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"text/xml,application/xml,*/*"})
            with urllib.request.urlopen(req,timeout=120) as resp: raw=resp.read()
            root=ET.fromstring(raw); roots=[root]
            if (root.text or "").strip().startswith("<"):
                try:roots.append(ET.fromstring(root.text))
                except Exception:pass
            rows={}
            for rt in roots:
                for node in rt.iter():
                    fields={lname(ch.tag):(ch.text or "") for ch in node}
                    ts=ptime(fields.get("DataHora") or fields.get("Data_Hora"))
                    if ts is None or ts<start or ts>end:continue
                    rows[ts]={
                      "rain":fnum(fields.get("Chuva") or fields.get("chuva") or fields.get("Precipitacao")),
                      "q":fnum(fields.get("Vazao") or fields.get("vazao")),
                      "level":fnum(fields.get("Nivel") or fields.get("nivel")),
                    }
            if rows:return rows
            errs.append(base+":empty")
        except Exception as exc:errs.append(base+":"+str(exc))
    raise RuntimeError(code+" "+" | ".join(errs))

def hours(start,end):
    out=[]; t=start.replace(minute=0,second=0,microsecond=0)
    while t<=end.replace(minute=0,second=0,microsecond=0):
        out.append(t); t+=timedelta(hours=1)
    return out

def hourly_sum(rows,field):
    out={}
    for t,v in rows.items():
        x=v.get(field)
        if x is None:continue
        h=t.replace(minute=0,second=0,microsecond=0)
        out[h]=out.get(h,0.0)+float(x)
    return out

def hourly_mean(rows,field):
    tmp={}
    for t,v in rows.items():
        x=v.get(field)
        if x is None:continue
        h=t.replace(minute=0,second=0,microsecond=0)
        tmp.setdefault(h,[]).append(float(x))
    return {h:statistics.fmean(v) for h,v in tmp.items()}

def params(row):
    p=row["params"];u=p["upstream"];d=p["downstream"]
    return NestedParams(
      up=ZoneParams(float(u["initial_loss"]),float(u["constant_loss"]),float(u["tc"]),float(u["storage"]),float(u["recession"]),float(u["initial_flow_ratio"])),
      dn=ZoneParams(float(d["initial_loss"]),float(d["constant_loss"]),float(d["tc"]),float(d["storage"]),float(d["recession"]),float(d["initial_flow_ratio"])),
      k1=float(p["k1"]),k2=float(p["k2"]),k3=float(p["k3"]),x=float(p.get("x",0.2))
    )

def p_dict(p):
    return {
      "upstream":{"initial_loss":p.up.initial_loss,"constant_loss":p.up.constant_loss,"tc":p.up.tc,"storage":p.up.storage,"recession":p.up.recession,"initial_flow_ratio":p.up.initial_flow_ratio},
      "downstream":{"initial_loss":p.dn.initial_loss,"constant_loss":p.dn.constant_loss,"tc":p.dn.tc,"storage":p.dn.storage,"recession":p.dn.recession,"initial_flow_ratio":p.dn.initial_flow_ratio},
      "k1":p.k1,"k2":p.k2,"k3":p.k3,"x":p.x
    }

def median_params(rows):
    ps=[params(r) for r in rows]
    med=lambda xs:float(statistics.median(xs))
    return NestedParams(
      up=ZoneParams(med([p.up.initial_loss for p in ps]),med([p.up.constant_loss for p in ps]),med([p.up.tc for p in ps]),med([p.up.storage for p in ps]),med([p.up.recession for p in ps]),med([p.up.initial_flow_ratio for p in ps])),
      dn=ZoneParams(med([p.dn.initial_loss for p in ps]),med([p.dn.constant_loss for p in ps]),med([p.dn.tc for p in ps]),med([p.dn.storage for p in ps]),med([p.dn.recession for p in ps]),med([p.dn.initial_flow_ratio for p in ps])),
      k1=med([p.k1 for p in ps]),k2=med([p.k2 for p in ps]),k3=med([p.k3 for p in ps]),x=med([p.x for p in ps])
    )

def scale_ic(p,scale):
    q=copy.deepcopy(p)
    q.up.initial_flow_ratio*=scale;q.dn.initial_flow_ratio*=scale
    return q

def rmse(obs,sim):
    return math.sqrt(statistics.fmean([(a-b)**2 for a,b in zip(obs,sim)])) if obs else None

def nse(obs,sim):
    if len(obs)<2:return None
    mean=statistics.fmean(obs); den=sum((x-mean)**2 for x in obs)
    return None if den<=0 else 1-sum((a-b)**2 for a,b in zip(obs,sim))/den

def run_with_ic(p,precip,areas,sim_hours,qobs,event_start):
    idx=sim_hours.index(event_start)
    target=qobs.get(event_start)
    if target is None:
        avail=[t for t in sim_hours[idx:idx+4] if t in qobs]
        target=qobs[avail[0]] if avail else None
        idx=sim_hours.index(avail[0]) if avail else idx
    best=None
    for sc in (0.25,0.5,0.75,1,1.5,2,3,4,6,8,12,16):
        pp=scale_ic(p,sc); net=run_network(precip,areas,pp,include_mucum_increment=True); sim=net["at_mucum"]
        err=0 if target is None else abs(sim[idx]-target)
        if best is None or err<best[0]:best=(err,pp,sim,sc,net)
    return best[1],best[2],best[3],best[4]

def lookback_score(obs,sim,sim_hours,start,t0):
    ts=[t for t in sim_hours if start<=t<=t0 and t in obs]
    if len(ts)<6:return float("inf"),{}
    ov=[obs[t] for t in ts];sv=[sim[sim_hours.index(t)] for t in ts]
    rr=rmse(ov,sv)
    qerr=abs(sv[-1]-ov[-1])/max(abs(ov[-1]),300.0)
    h3=ts[max(0,len(ts)-4)]
    j0=sim_hours.index(h3);j1=sim_hours.index(ts[-1])
    tobs=(ov[-1]-obs[h3])/max(1,(ts[-1]-h3).total_seconds()/3600)
    tsim=(sim[j1]-sim[j0])/max(1,(ts[-1]-h3).total_seconds()/3600)
    terr=abs(tsim-tobs)/max(abs(tobs),200.0)
    rnorm=rr/max(statistics.fmean(ov),500.0)
    score=rnorm+qerr+0.5*terr
    ns=nse(ov,sv)
    if ns is not None and ns<0:score+=abs(ns)
    return score,{"n":len(ts),"rmse":rr,"nse":ns,"q_now_obs":ov[-1],"q_now_sim":sv[-1],"trend_obs":tobs,"trend_sim":tsim}

def fingerprint(rain_hourly,start,end):
    vals=[rain_hourly.get(t,0.0) for t in hours(start,end)]
    def maxwin(n):
        if not vals:return 0.0
        return max(sum(vals[max(0,i-n+1):i+1]) for i in range(len(vals)))
    return {"total":sum(vals),"max6":maxwin(6),"max24":maxwin(24),"duration_h":len(vals)}

def rain_distance(a,b):
    scales={"total":80.0,"max6":40.0,"max24":80.0,"duration_h":120.0}
    return sum(abs(a[k]-b[k])/scales[k] for k in scales)

def q_to_stage(q,segs):
    cand=[]
    for s in segs:
        a=float(s["a"]);n=float(s["n"]);h0=float(s["h0_m"])
        if q<0 or a<=0 or n<=0:continue
        st=(h0+(q/a)**(1/n))*100
        inside=float(s["stage_min_cm"])-1e-6<=st<=float(s["stage_max_cm"])+1e-6
        cand.append((inside,st,s))
    ins=[x for x in cand if x[0]]
    if not ins:return None
    return ins[0][1]

def eval_future(obs_q_raw,obs_q_hour,obs_level_raw,sim,sim_hours,t0,end,segs):
    future_h=[t for t in sim_hours if t0<=t<=end and t in obs_q_hour]
    ov=[obs_q_hour[t] for t in future_h];sv=[sim[sim_hours.index(t)] for t in future_h]
    rawq=[(t,v["q"]) for t,v in obs_q_raw.items() if t0<=t<=end and v.get("q") is not None]
    rawl=[(t,v["level"]) for t,v in obs_level_raw.items() if t0<=t<=end and v.get("level") is not None]
    oqt,oq=max(rawq,key=lambda x:x[1])
    olt,ol=max(rawl,key=lambda x:x[1])
    si=max((sim_hours.index(t) for t in sim_hours if t0<=t<=end),key=lambda i:sim[i])
    sq=sim[si];st=sim_hours[si]
    sstage=q_to_stage(sq,segs)
    out={
      "n_future":len(future_h),"rmse_q":rmse(ov,sv),"mae_q":statistics.fmean([abs(a-b) for a,b in zip(ov,sv)]),
      "nse_future":nse(ov,sv),"obs_peak_q":oq,"obs_peak_q_time":oqt.isoformat(" "),
      "sim_peak_q":sq,"sim_peak_q_time":st.isoformat(" "),
      "peak_q_error_pct":100*(sq-oq)/oq,"peak_time_error_h":(st-oqt).total_seconds()/3600,
      "obs_peak_level_cm":ol,"obs_peak_level_time":olt.isoformat(" "),
      "sim_peak_stage_cm":sstage,
      "peak_stage_error_cm":None if sstage is None else sstage-ol,
    }
    lvl_hour=hourly_mean(obs_level_raw,"level")
    for lead in (2,4,8,12,24):
        t=t0+timedelta(hours=lead)
        if t in sim_hours and t in lvl_hour:
            ss=q_to_stage(sim[sim_hours.index(t)],segs)
            out[f"stage_error_{lead}h_cm"]=None if ss is None else ss-lvl_hour[t]
        else:out[f"stage_error_{lead}h_cm"]=None
    return out

def local_recal(selected,precip,areas,sim_hours,qobs,event_start,t0):
    p=copy.deepcopy(selected)
    bestp,bestsim,bestsc,_=run_with_ic(p,precip,areas,sim_hours,qobs,event_start)
    bestscore,bmeta=lookback_score(qobs,bestsim,sim_hours,event_start,t0)
    for _ in range(2):
      changed=False
      specs=[
        ("up","initial_loss",[-2,-1,0,1,2],0.0),
        ("up","constant_loss",[-1,-0.5,0,0.5,1],0.0),
        ("up","tc",[-5,-2,0,2,5],1.0),
        ("up","storage",[-10,-5,0,5,10],1.0),
        ("dn","initial_loss",[-2,-1,0,1,2],0.0),
        ("dn","constant_loss",[-1,-0.5,0,0.5,1],0.0),
        ("dn","tc",[-5,-2,0,2,5],1.0),
        ("dn","storage",[-10,-5,0,5,10],1.0),
      ]
      for zone,field,deltas,lo in specs:
        basev=float(getattr(getattr(bestp,zone),field))
        local=(bestscore,bestp,bestsim,bestsc,bmeta)
        for d in deltas:
            pp=copy.deepcopy(bestp);setattr(getattr(pp,zone),field,max(lo,basev+d))
            pp2,ss,sc,_=run_with_ic(pp,precip,areas,sim_hours,qobs,event_start)
            score,meta=lookback_score(qobs,ss,sim_hours,event_start,t0)
            if score<local[0]:local=(score,pp2,ss,sc,meta)
        if local[0]<bestscore:
            bestscore,bestp,bestsim,bestsc,bmeta=local;changed=True
      if not changed:break
    return bestp,bestsim,bestsc,bestscore,bmeta

def main():
    model=load(MODEL);rows={r["event_id"]:r for r in model["params_library_eventwise"]}
    struct=load(STRUCT)
    areas={e["id"]:float(e["area_km2"]) for e in struct["models"]["mucum"]["elements"] if e.get("type")=="subbasin"}
    curve=load(CURVE);segs=curve["neighbors_official_curves_NOT_for_STZ"]["86510000"]["segments"]

    # Fresh ANA cache, including target multi-station forcing and prior-event rain fingerprints.
    requests={}
    needed_events=set()
    for target in TARGETS:
        ts=datetime.fromisoformat(EVENTS[target][0]);te=datetime.fromisoformat(EVENTS[target][1])
        for code in STATIONS:requests[(code,target)]=(code,ts-timedelta(hours=PAD_H),te+timedelta(hours=1))
        for ev in rows:
            if ev in EVENTS and datetime.fromisoformat(EVENTS[ev][0])<ts:
                needed_events.add(ev)
    for ev in needed_events:
        es=datetime.fromisoformat(EVENTS[ev][0]);ee=datetime.fromisoformat(EVENTS[ev][1])
        requests[("86472000",ev)]=("86472000",es,ee)
    cache={}
    with ThreadPoolExecutor(max_workers=6) as pool:
        fut={pool.submit(fetch_ana,*args):key for key,args in requests.items()}
        for f in as_completed(fut):
            key=fut[f]
            try:cache[key]=f.result()
            except Exception as exc:
                print("WARN",key,exc);cache[key]={}

    fps={}
    for ev in needed_events:
        es=datetime.fromisoformat(EVENTS[ev][0]);ee=datetime.fromisoformat(EVENTS[ev][1])
        rh=hourly_sum(cache.get(("86472000",ev),{}),"rain")
        fps[ev]=fingerprint(rh,es,ee)

    all_results=[]
    event_reports=[]
    for target in TARGETS:
        es=datetime.fromisoformat(EVENTS[target][0]);ee=datetime.fromisoformat(EVENTS[target][1])
        sim_start=es-timedelta(hours=PAD_H);sim_hours=hours(sim_start,ee)
        station_hourly={code:hourly_sum(cache.get((code,target),{}),"rain") for code in STATIONS}
        precip={}
        missing=[]
        for sb,prefs in RAIN_PREF.items():
            vals=[]
            for h in sim_hours:
                vv=[station_hourly[c][h] for c in prefs if h in station_hourly.get(c,{})]
                if not vv and h in station_hourly["86472000"]:vv=[station_hourly["86472000"][h]]
                if not vv:missing.append((sb,h));vals.append(0.0)
                else:vals.append(statistics.fmean(vv))
            precip[sb]=vals
        if missing:
            raise RuntimeError(f"{target}: missing all rain sources at {missing[:5]} (missing!=zero; abort)")

        raw=cache[("86510000",target)]
        qhour=hourly_mean(raw,"q")
        rawq=raw;rawl=raw
        peak_t,peak_q=max(((t,v["q"]) for t,v in raw.items() if v.get("q") is not None and es<=t<=ee),key=lambda x:x[1])
        target_fp=fingerprint(station_hourly["86472000"],es,ee)

        prior=[rows[e] for e in rows if e in EVENTS and datetime.fromisoformat(EVENTS[e][0])<es]
        if not prior:raise RuntimeError("no prior library for "+target)

        # A fixed expanding-history median.
        pA=median_params(prior)
        pA,simA,scA,_=run_with_ic(pA,precip,areas,sim_hours,qhour,es)

        # B perfect-rain analog baseline.
        analog=sorted(prior,key=lambda r:rain_distance(target_fp,fps.get(r["event_id"],{"total":0,"max6":0,"max24":0,"duration_h":0})))[0]
        pB=params(analog);pB,simB,scB,_=run_with_ic(pB,precip,areas,sim_hours,qhour,es)

        report={"event":target,"observed_peak_q_time":peak_t.isoformat(" "),"observed_peak_q":peak_q,"prior_library":[r["event_id"] for r in prior],"target_rain_fingerprint":target_fp,"rain_analog":analog["event_id"],"cutoffs":[]}
        for lead in (12,6):
            t0=(peak_t-timedelta(hours=lead)).replace(minute=0,second=0,microsecond=0)
            if t0<es:t0=es

            candidates=[]
            for r in prior:
                pp=params(r);pp,ss,sc,_=run_with_ic(pp,precip,areas,sim_hours,qhour,es)
                score,meta=lookback_score(qhour,ss,sim_hours,es,t0)
                candidates.append((score,r,pp,ss,sc,meta))
            candidates.sort(key=lambda x:x[0])
            cscore,crow,pC,simC,scC,cmeta=candidates[0]

            pD,simD,scD,dscore,dmeta=local_recal(pC,precip,areas,sim_hours,qhour,es,t0)

            arms=[
              ("A_fixed_prior_median",pA,simA,scA,None,None),
              ("B_rain_analog",pB,simB,scB,None,{"selected_event":analog["event_id"],"rain_distance":rain_distance(target_fp,fps[analog["event_id"]])}),
              ("C_lookback_select",pC,simC,scC,cscore,{"selected_event":crow["event_id"],**cmeta}),
              ("D_lookback_online_recal",pD,simD,scD,dscore,{"seed_event":crow["event_id"],**dmeta}),
            ]
            cut={"t0":t0.isoformat(" "),"hours_before_observed_peak_nominal":lead,"arms":[]}
            for name,pp,ss,sc,score,meta in arms:
                ev=eval_future(rawq,qhour,rawl,ss,sim_hours,t0,ee,segs)
                row={"event":target,"cutoff_h_before_peak":lead,"t0":t0.isoformat(" "),"arm":name,"ic_scale":sc,"lookback_score":score,**ev}
                all_results.append(row)
                cut["arms"].append({"arm":name,"params":p_dict(pp),"ic_scale":sc,"lookback_score":score,"selection":meta,"future_metrics":ev})
            report["cutoffs"].append(cut)
        event_reports.append(report)

    # Aggregate arm comparisons across all event-cutoff cases.
    arms=sorted(set(r["arm"] for r in all_results))
    agg={}
    for a in arms:
        rr=[r for r in all_results if r["arm"]==a]
        agg[a]={
          "n_cases":len(rr),
          "median_abs_peak_q_error_pct":round(statistics.median([abs(r["peak_q_error_pct"]) for r in rr]),3),
          "median_abs_peak_time_error_h":round(statistics.median([abs(r["peak_time_error_h"]) for r in rr]),3),
          "median_rmse_q":round(statistics.median([r["rmse_q"] for r in rr]),3),
          "median_nse_future":round(statistics.median([r["nse_future"] for r in rr if r["nse_future"] is not None]),4),
          "median_abs_peak_stage_error_cm":(
             round(statistics.median([abs(r["peak_stage_error_cm"]) for r in rr if r["peak_stage_error_cm"] is not None]),2)
             if any(r["peak_stage_error_cm"] is not None for r in rr) else None
          ),
        }

    out={
      "schema_version":"mucum_pseudo_operational_p2_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "status":"research_replay_perfect_future_rain",
      "forcing_scenario":"P2: fresh ANA observed rainfall used after t0 as perfect rainfall forecast; isolates hydrologic/model-selection error",
      "strict_no_target_leakage":True,
      "chronology_rule":"only eventwise families whose event starts before the target event are eligible",
      "state_initialization":"all arms receive the same privilege: one scalar initial-flow-ratio adjustment against target discharge at event start",
      "online_recalibration_rule":"D changes losses and Clark Tc/storage only using lookback; recession and routing K/x remain inherited from C seed",
      "targets":list(TARGETS),
      "aggregate":agg,
      "events":event_reports,
      "interpretation_warning":"P2 is not a weather-forecast skill test. It measures hydrologic transfer/selection skill under perfect future rain.",
    }
    (OUT/"pseudo_operational_p2_latest.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fields=["event","cutoff_h_before_peak","t0","arm","ic_scale","lookback_score","n_future","rmse_q","mae_q","nse_future","obs_peak_q","sim_peak_q","peak_q_error_pct","peak_time_error_h","obs_peak_level_cm","sim_peak_stage_cm","peak_stage_error_cm","stage_error_2h_cm","stage_error_4h_cm","stage_error_8h_cm","stage_error_12h_cm","stage_error_24h_cm"]
    with (OUT/"pseudo_operational_p2_cases.csv").open("w",newline="",encoding="utf-8") as fh:
        w=csv.DictWriter(fh,fieldnames=fields);w.writeheader()
        for r in all_results:w.writerow({k:r.get(k) for k in fields})
    print(json.dumps(agg,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
