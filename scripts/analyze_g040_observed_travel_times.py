#!/usr/bin/env python3
"""Diagnose observed propagation lags between G040 HEC control stations.

Uses only observed ANA discharge from the compact G040 control snapshot.
For each ordered pair, scan integer lags and fit a simple linear transfer
Q_down ~= a + b * Q_up(t-lag). This is a timing diagnostic, NOT a routing
calibration and NOT a claim that Muskingum K equals the best lag.

Research only.
"""
from __future__ import annotations

import json, math
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
HYDRO=BASE/"whole_basin_live_hydro_controls_latest.json"
OUT=BASE/"whole_basin_observed_travel_time_diagnostics_latest.json"

PAIRS=[
 ("86472000","86510000","Linha Jose Julio -> Mucum"),
 ("86510000","86720000","Mucum -> Encantado"),
 ("86720000","86879300","Encantado -> Estrela composite"),
 ("86879300","86895000","Estrela -> Porto Mariante"),
 ("86895000","86950000","Porto Mariante -> Taquari"),
 ("86950000","86996000","Taquari -> Triunfo"),
]
MAX_LAG_H=18

def hourly(rows):
    buckets={}
    for r in rows or []:
        if r.get("flow_m3s") is None: continue
        t=datetime.fromisoformat(str(r["time_utc"]).replace("Z","+00:00")).astimezone(timezone.utc)
        h=t.replace(minute=0,second=0,microsecond=0)
        buckets.setdefault(h,[]).append(float(r["flow_m3s"]))
    return {t:sum(v)/len(v) for t,v in buckets.items()}

def regression(pairs):
    n=len(pairs)
    if n<4: return None
    mx=sum(x for x,_ in pairs)/n; my=sum(y for _,y in pairs)/n
    vx=sum((x-mx)**2 for x,_ in pairs)
    vy=sum((y-my)**2 for _,y in pairs)
    if vx<=0 or vy<=0: return None
    cov=sum((x-mx)*(y-my) for x,y in pairs)
    b=cov/vx; a=my-b*mx
    corr=cov/math.sqrt(vx*vy)
    rmse=math.sqrt(sum((y-(a+b*x))**2 for x,y in pairs)/n)
    nrmse=rmse/(max(abs(my),1e-6))
    return {"n":n,"corr":corr,"intercept":a,"slope":b,"rmse_m3s":rmse,"nrmse":nrmse}

def main():
    h=json.loads(HYDRO.read_text(encoding="utf-8"))
    by={str(x["code"]):x for x in h["controls"]}
    results=[]
    for up,dn,label in PAIRS:
        u=hourly((by.get(up) or {}).get("recent_rows"))
        d=hourly((by.get(dn) or {}).get("recent_rows"))
        trials=[]
        for lag in range(MAX_LAG_H+1):
            pairs=[]
            for td,qd in d.items():
                tu=td.replace()  # preserve timezone
                from datetime import timedelta
                tu=tu-timedelta(hours=lag)
                if tu in u:
                    pairs.append((u[tu],qd))
            fit=regression(pairs)
            if fit:
                trials.append({"lag_h":lag,**fit})
        best=None
        if trials:
            # timing ranking prioritizes correlation, then normalized RMSE.
            best=max(trials,key=lambda x:(x["corr"],-x["nrmse"]))
        results.append({
          "upstream":up,"downstream":dn,"label":label,
          "upstream_points":len(u),"downstream_points":len(d),
          "best":None if best is None else {
            k:(round(v,5) if isinstance(v,float) else v)
            for k,v in best.items()
          },
          "trials":[{
            k:(round(v,5) if isinstance(v,float) else v)
            for k,v in x.items()
          } for x in trials],
          "interpretation":"diagnostic observed lag; do not equate directly to Muskingum K",
        })
    payload={
      "schema_version":"g040_observed_travel_time_diagnostics_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,
      "window_hours":72,
      "max_lag_h":MAX_LAG_H,
      "results":results,
      "routing_policy":"use these lags as empirical constraints during reach calibration; calibrate K/X against full hydrograph and independent events",
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"pairs":[{"label":x["label"],"best":x["best"]} for x in results]},ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
