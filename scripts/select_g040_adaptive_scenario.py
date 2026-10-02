#!/usr/bin/env python3
"""Select historical analog parameter families for each G040 target.

Transparent research selector:
- reads current observed+forecast rainfall over all 11 G040 branch components;
- reads current target/upstream discharge state from the basin snapshot;
- compares against historical event fingerprints;
- returns top-k compatible target/event parameter sets with soft weights;
- retains the multi-event candidate as fallback.

No LLM judgment is required for the numerical core. The output is auditable and
research-only; it must not directly drive warning/evacuation decisions.
"""
from __future__ import annotations
import json, math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
LIB=BASE/"g040_target_event_parameter_library_latest.json"
RAIN=BASE/"whole_basin_rain_forcing_latest.json"
SNAP=BASE/"g040_basin_snapshot_latest.json"
CFG=ROOT/"config/g040_adaptive_eventwise_selection_v1.json"
OUT=BASE/"g040_adaptive_scenario_latest.json"

def load(p:Path)->dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8"))

def sum_last(rows,source,n):
    vals=[float(r["mm"]) for r in rows if r.get("source")==source and r.get("mm") is not None]
    vals=vals[-n:]
    return sum(vals) if vals else None

def sum_first(rows,source,n):
    vals=[float(r["mm"]) for r in rows if r.get("source")==source and r.get("mm") is not None]
    vals=vals[:n]
    return sum(vals) if vals else None

def live_rain_fingerprint(rain):
    comps=rain.get("components") or []
    comp={}
    for c in comps:
        cid=str(c.get("component_id")); area=float(c.get("support_area_km2") or 0)
        rows=c.get("series") or []
        comp[cid]={
          "area":area,
          "obs24":sum_last(rows,"observed",24),
          "obs72":sum_last(rows,"observed",72),
          "fc24":sum_first(rows,"forecast",24),
          "fc48":sum_first(rows,"forecast",48),
          "fc72":sum_first(rows,"forecast",72),
        }
    def aw(key):
        num=den=0.0
        for x in comp.values():
            v=x.get(key); a=x.get("area") or 0
            if v is None or a<=0: continue
            num+=float(v)*a; den+=a
        return num/den if den else None
    raw={cid:(x.get("fc48") or 0.0)*(x.get("area") or 0.0) for cid,x in comp.items()}
    s=sum(raw.values())
    frac={cid:(v/s if s>0 else 0.0) for cid,v in raw.items()}
    return {
      "observed_24h_basin_mm":aw("obs24"),
      "observed_72h_basin_mm":aw("obs72"),
      "forecast_24h_basin_mm":aw("fc24"),
      "forecast_48h_basin_mm":aw("fc48"),
      "forecast_72h_basin_mm":aw("fc72"),
      "component_forecast_48h_fraction":frac,
      "component_values":comp,
    }

def controls(snapshot):
    block=snapshot.get("calibration_assimilation_controls") or {}
    out={}
    for c in block.get("controls") or []:
        code=str(c.get("code"))
        out[code]={
          "q":c.get("current_flow_m3s"),
          "flow_trend":(c.get("flow_trend") or {}).get("delta"),
          "direction":(c.get("flow_trend") or {}).get("direction"),
          "fresh":c.get("fresh_for_state"),
        }
    return out

def rel(a,b,scale=1.0):
    if a is None or b is None:return None
    a=float(a);b=float(b)
    return abs(a-b)/(abs(b)+scale)

def spatial_l1(a,b):
    keys=set(a)|set(b)
    if not keys:return None
    vals=[]
    for k in keys:
        av=a.get(k);bv=b.get(k)
        if av is None or bv is None:continue
        vals.append(abs(float(av)-float(bv)))
    return None if not vals else sum(vals)/len(vals)

def hydro_distance(target_cfg,live_controls,hist):
    hs=hist.get("hydrology") or {}
    codes=[str(target_cfg["code"]),*[str(x) for x in target_cfg.get("upstream_controls") or []]]
    vals=[]
    trend=[]
    for code in codes:
        lc=live_controls.get(code) or {}
        hc=hs.get(code) or {}
        q=lc.get("q"); q0=hc.get("start_q_m3s")
        if q is not None and q0 is not None:
            vals.append(abs(math.log1p(max(float(q),0))-math.log1p(max(float(q0),0)))/5.0)
        ld=lc.get("flow_trend"); hd=hc.get("early_6h_delta_q_m3s")
        if ld is not None and hd is not None:
            ls=0 if abs(float(ld))<1e-9 else (1 if float(ld)>0 else -1)
            hsx=0 if abs(float(hd))<1e-9 else (1 if float(hd)>0 else -1)
            trend.append(0.0 if ls==hsx else 1.0)
    return (
      None if not vals else sum(vals)/len(vals),
      None if not trend else sum(trend)/len(trend)
    )

def event_distance(target_cfg,live_rain,live_controls,hist,weights):
    hr=(hist.get("rain") or {})
    live_mag=(live_rain.get("forecast_48h_basin_mm") or 0.0)
    hist_mag=hr.get("max_48h_mm") or hr.get("basin_total_mm")
    dmag=rel(live_mag,hist_mag,10.0)

    dsp=spatial_l1(
      live_rain.get("component_forecast_48h_fraction") or {},
      hr.get("component_fraction") or {}
    )

    wet_live=live_rain.get("observed_24h_basin_mm")
    wet_hist=hr.get("first_24h_mm") or hr.get("max_24h_mm")
    dwet=rel(wet_live,wet_hist,10.0)

    dh,dtrend=hydro_distance(target_cfg,live_controls,hist)
    parts={
      "rain_magnitude":dmag,
      "spatial_rain_pattern":dsp,
      "antecedent_wetness":dwet,
      "upstream_hydrologic_state":dh,
      "trend":dtrend,
    }
    num=den=0.0
    for k,v in parts.items():
        if v is None:continue
        w=float(weights.get(k) or 0)
        num+=w*float(v);den+=w
    return (None if den<=0 else num/den),parts,den

def main()->int:
    lib=load(LIB); rain=load(RAIN); snap=load(SNAP); cfg=load(CFG)
    lr=live_rain_fingerprint(rain); lc=controls(snap)
    fps=lib.get("historical_fingerprints") or {}
    target_rows=lib.get("hec_target_event_candidates") or []
    fallbacks={x["target_code"]:x for x in lib.get("robust_fallbacks") or []}
    weights=cfg.get("distance_weights") or {}
    top_k=int((cfg.get("selector") or {}).get("top_k") or 3)

    target_results=[]
    for target in cfg.get("targets") or []:
        code=str(target["code"])
        compatible={r["event_id"]:r for r in target_rows if str(r.get("target_code"))==code}
        scored=[]
        for eid,row in compatible.items():
            hist=fps.get(eid)
            if not hist:continue
            d,detail,wused=event_distance(target,lr,lc,hist,weights)
            if d is None:continue
            scored.append({
              "event_id":eid,"distance":d,"distance_detail":detail,
              "evidence_weight_sum":wused,
              "candidate_id":row.get("candidate_id"),
              "parameters":row.get("parameters"),
              "historical_metrics":row.get("metrics"),
              "checkpoint_gate_pass":row.get("checkpoint_gate_pass"),
              "model_family":row.get("model_family"),
            })
        scored.sort(key=lambda x:x["distance"])
        chosen=scored[:top_k]
        inv=[1.0/(0.05+x["distance"]) for x in chosen]
        ss=sum(inv)
        for x,v in zip(chosen,inv):
            x["analog_weight"]=v/ss if ss else 0.0

        topd=chosen[0]["distance"] if chosen else None
        gap=(chosen[1]["distance"]-topd) if len(chosen)>1 else None
        if topd is not None and topd<0.35 and (gap is None or gap>0.08):
            conf="high"
        elif topd is not None and topd<0.75:
            conf="medium"
        else:
            conf="low"

        fallback=fallbacks.get(code)
        use_fallback=not chosen or conf=="low"
        target_results.append({
          "target_code":code,"target_name":target.get("name"),
          "library_status":target.get("status"),
          "confidence":conf,
          "top_analogs":chosen,
          "fallback":fallback,
          "selection_mode":"robust_fallback" if use_fallback else "analog_ensemble",
          "hard_parameter_pick":False,
          "note":(
             "No sufficiently supported target/event analog; retain robust fallback."
             if use_fallback else
             "Run/compare the weighted analog members; do not collapse to one set before benchmark gates."
          )
        })

    payload={
      "schema_version":"g040_adaptive_scenario_selection_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,
      "live_feature_source":{
        "rain":str(RAIN.relative_to(ROOT)),
        "snapshot":str(SNAP.relative_to(ROOT)),
      },
      "live_fingerprint":{"rain":lr,"controls":lc},
      "targets":target_results,
      "governance":{
        "warning_or_evacuation_authority":False,
        "target_event_full_fit_is_not_forecast_validation":True,
        "pseudo_operational_validation_required":True,
        "observations_after_t0_forbidden_for_selection":True,
      }
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
      "status":"G040_ADAPTIVE_SCENARIO_SELECTION_READY",
      "targets":len(target_results),
      "analog_targets":sum(x["selection_mode"]=="analog_ensemble" for x in target_results),
      "fallback_targets":sum(x["selection_mode"]=="robust_fallback" for x in target_results),
    },ensure_ascii=False))
    return 0
if __name__=="__main__":raise SystemExit(main())
