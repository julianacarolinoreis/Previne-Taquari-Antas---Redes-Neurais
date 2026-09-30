#!/usr/bin/env python3
"""Multi-event observed propagation diagnostics for the G040 HEC network.

Uses published historical hourly ANA discharge inputs. For each event/pair it
searches integer lags and an affine transfer Qd ~= a + b*Qu(t-lag). Results are
diagnostic constraints for routing calibration; they are NOT Muskingum K.

Only pairs with enough overlapping discharge data are scored.
"""
from __future__ import annotations

import json, math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
MANIFEST=BASE/"whole_basin_historical_hydro_events_latest.json"
OUT=BASE/"whole_basin_multi_event_propagation_diagnostics_latest.json"

PAIRS=[
 ("86472000","86510000","Linha Jose Julio -> Mucum",0,12),
 ("86510000","86720000","Mucum -> Encantado",0,12),
 ("86720000","86879300","Encantado -> Estrela composite",0,18),
 ("86879300","86895000","Estrela -> Porto Mariante",0,18),
 ("86895000","86950000","Porto Mariante -> Taquari",0,18),
]
MIN_PAIRS=12

def series(st):
    out={}
    for r in st.get("series") or []:
        if r.get("flow_m3s") is None: continue
        t=datetime.fromisoformat(str(r["time_utc"]).replace("Z","+00:00")).astimezone(timezone.utc)
        out[t]=float(r["flow_m3s"])
    return out

def fit(pairs):
    n=len(pairs)
    if n<MIN_PAIRS: return None
    mx=sum(x for x,_ in pairs)/n; my=sum(y for _,y in pairs)/n
    vx=sum((x-mx)**2 for x,_ in pairs)
    vy=sum((y-my)**2 for _,y in pairs)
    if vx<=0 or vy<=0: return None
    cov=sum((x-mx)*(y-my) for x,y in pairs)
    b=cov/vx; a=my-b*mx
    corr=cov/math.sqrt(vx*vy)
    rmse=math.sqrt(sum((y-(a+b*x))**2 for x,y in pairs)/n)
    mae=sum(abs(y-(a+b*x)) for x,y in pairs)/n
    nrmse=rmse/max(abs(my),1e-9)
    return dict(n=n,intercept=a,slope=b,corr=corr,rmse_m3s=rmse,mae_m3s=mae,nrmse=nrmse)

def peak_info(s):
    if not s: return None
    t,q=max(s.items(),key=lambda z:z[1])
    return {"time_utc":t.isoformat().replace("+00:00","Z"),"q_m3s":q}

def coverage_stats(s, expected_hours):
    if not s:
        return {"hours":0,"coverage":0.0,"longest_contiguous_h":0,"max_gap_h":None,
                "peak_near_record_edge":True}
    ts=sorted(s)
    gaps=[(b-a).total_seconds()/3600 for a,b in zip(ts,ts[1:])]
    longest=1; cur=1
    for g in gaps:
        if abs(g-1.0)<1e-6:
            cur+=1; longest=max(longest,cur)
        else:
            cur=1
    pt=max(s.items(),key=lambda z:z[1])[0]
    edge=min((pt-ts[0]).total_seconds()/3600,(ts[-1]-pt).total_seconds()/3600)
    return {
      "hours":len(ts),
      "coverage":round(len(ts)/max(expected_hours,1),5),
      "longest_contiguous_h":longest,
      "max_gap_h":None if not gaps else round(max(gaps),3),
      "peak_near_record_edge":edge<6,
    }

def main():
    mf=json.loads(MANIFEST.read_text(encoding="utf-8"))
    event_results=[]
    pair_pool={label:[] for _,_,label,_,_ in PAIRS}

    for e in mf["events"]:
        p=ROOT/e["path"]
        j=json.loads(p.read_text(encoding="utf-8"))
        by={str(s["code"]):s for s in j["stations"]}
        w=j.get("window_local") or {}
        try:
            ws=datetime.fromisoformat(str(w["start"])).replace(tzinfo=timezone(timedelta(hours=-3)))
            we=datetime.fromisoformat(str(w["end"])).replace(tzinfo=timezone(timedelta(hours=-3)))
            expected_hours=max(1,int((we-ws).total_seconds()/3600)+1)
        except Exception:
            expected_hours=max([len(series(s)) for s in j["stations"]] or [1])
        er={"event_id":e["event_id"],"expected_hours":expected_hours,"pairs":[]}
        for up,dn,label,l0,l1 in PAIRS:
            su=series(by.get(up,{}) ); sd=series(by.get(dn,{}))
            trials=[]
            for lag in range(l0,l1+1):
                pairs=[]
                dt=timedelta(hours=lag)
                for td,qd in sd.items():
                    tu=td-dt
                    if tu in su: pairs.append((su[tu],qd))
                f=fit(pairs)
                if f: trials.append({"lag_h":lag,**f})
            best=max(trials,key=lambda x:(x["corr"],-x["nrmse"])) if trials else None
            pu=peak_info(su); pd=peak_info(sd)
            peak_lag=None
            if pu and pd:
                tu=datetime.fromisoformat(pu["time_utc"].replace("Z","+00:00"))
                td=datetime.fromisoformat(pd["time_utc"].replace("Z","+00:00"))
                peak_lag=(td-tu).total_seconds()/3600
            us=coverage_stats(su,expected_hours); ds=coverage_stats(sd,expected_hours)
            fit_quality="none"
            if best:
                if best["n"]>=48 and best["corr"]>=0.90 and us["coverage"]>=0.60 and ds["coverage"]>=0.60:
                    fit_quality="high"
                elif best["n"]>=24 and best["corr"]>=0.80 and us["coverage"]>=0.35 and ds["coverage"]>=0.35:
                    fit_quality="medium"
                else:
                    fit_quality="low"
            peak_reliable=bool(
              peak_lag is not None and
              us["coverage"]>=0.80 and ds["coverage"]>=0.80 and
              not us["peak_near_record_edge"] and not ds["peak_near_record_edge"]
            )
            rec={
              "upstream":up,"downstream":dn,"label":label,
              "upstream_hours":len(su),"downstream_hours":len(sd),
              "upstream_coverage":us,"downstream_coverage":ds,
              "best":None if best is None else {k:(round(v,5) if isinstance(v,float) else v) for k,v in best.items()},
              "fit_quality":fit_quality,
              "observed_peak_lag_h":None if peak_lag is None else round(peak_lag,3),
              "observed_peak_lag_reliable":peak_reliable,
              "upstream_peak":pu,"downstream_peak":pd,
              "trials":[{k:(round(v,5) if isinstance(v,float) else v) for k,v in x.items()} for x in trials],
            }
            er["pairs"].append(rec)
            if best:
                pair_pool[label].append({
                  "event_id":e["event_id"],"best_lag_h":best["lag_h"],
                  "corr":best["corr"],"nrmse":best["nrmse"],"n":best["n"],
                  "fit_quality":fit_quality,
                  "observed_peak_lag_h":peak_lag,
                  "observed_peak_lag_reliable":peak_reliable,
                })
        event_results.append(er)

    summaries=[]
    for up,dn,label,l0,l1 in PAIRS:
        rows=pair_pool[label]
        usable=[r for r in rows if r.get("fit_quality") in {"high","medium"}]
        if usable:
            # Weighted robust center from only medium/high quality fits.
            expanded=[]
            for r in usable:
                expanded.extend([int(r["best_lag_h"])]*max(1,int(r["n"]//12)))
            expanded.sort()
            robust=expanded[len(expanded)//2]
            lag_min=min(r["best_lag_h"] for r in usable)
            lag_max=max(r["best_lag_h"] for r in usable)
            strong=[r for r in usable if r["corr"]>=0.8]
        else:
            robust=lag_min=lag_max=None; strong=[]
        summaries.append({
          "upstream":up,"downstream":dn,"label":label,
          "events_with_fit":len(rows),
          "events_usable_medium_or_high":len(usable),
          "events_corr_ge_0_8":len(strong),
          "diagnostic_lag_center_h":robust,
          "diagnostic_lag_range_h":None if lag_min is None else [lag_min,lag_max],
          "event_fits":[{
            **r,
            "corr":round(r["corr"],5),"nrmse":round(r["nrmse"],5),
            "observed_peak_lag_h":None if r["observed_peak_lag_h"] is None else round(r["observed_peak_lag_h"],3)
          } for r in rows],
          "routing_use":"search-window constraint only; never direct K assignment",
        })

    payload={
      "schema_version":"g040_multi_event_propagation_diagnostics_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,
      "events":[x["event_id"] for x in event_results],
      "pair_summaries":summaries,
      "event_results":event_results,
      "method":"hourly observed Q, integer lag scan, affine transfer fit; best by correlation then normalized RMSE",
      "limitations":[
        "tributary inflows between gauges can change hydrograph magnitude/shape",
        "partial station records can bias event-specific fit; medium/high quality gates are used for routing windows",
        "best statistical lag is not Muskingum K",
        "routing parameters still require HEC multi-event hydrograph calibration",
      ],
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"pair_summaries":summaries},ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
