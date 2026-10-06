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

def parse_utc(value):
    if not value:
        return None
    d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def window_sum(rows,kind,n,now):
    selected=[]
    for r in rows:
        if r.get("mm") is None or not r.get("time_utc"):
            continue
        t=parse_utc(r["time_utc"])
        if kind=="observed":
            if r.get("source")!="observed" or t>now:
                continue
        else:
            # Forecast source names are provider-specific. Anything non-observed
            # in the merged forcing is forecast and must have valid time >= now.
            if r.get("source")=="observed" or t<now:
                continue
        selected.append((t,float(r["mm"])))
    selected.sort(key=lambda x:x[0])
    if kind=="observed":
        selected=selected[-n:]
    else:
        selected=selected[:n]
    return {
      "mm":sum(v for _,v in selected) if selected else None,
      "count":len(selected),
      "complete":len(selected)>=n,
      "first_time_utc":selected[0][0].isoformat().replace("+00:00","Z") if selected else None,
      "last_time_utc":selected[-1][0].isoformat().replace("+00:00","Z") if selected else None,
    }

def live_rain_fingerprint(rain):
    now=datetime.now(timezone.utc)
    comps=rain.get("components") or []
    comp={}
    latest_obs=[]
    first_future=[]
    for c in comps:
        cid=str(c.get("component_id")); area=float(c.get("support_area_km2") or 0)
        rows=c.get("series") or []
        o24=window_sum(rows,"observed",24,now)
        o72=window_sum(rows,"observed",72,now)
        o168=window_sum(rows,"observed",168,now)
        f24=window_sum(rows,"forecast",24,now)
        f48=window_sum(rows,"forecast",48,now)
        f72=window_sum(rows,"forecast",72,now)
        if o24["last_time_utc"]: latest_obs.append(parse_utc(o24["last_time_utc"]))
        if f24["first_time_utc"]: first_future.append(parse_utc(f24["first_time_utc"]))
        comp[cid]={
          "area":area,
          "obs24":o24["mm"] if o24["complete"] else None,"obs24_count":o24["count"],
          "obs72":o72["mm"] if o72["complete"] else None,"obs72_count":o72["count"],
          "obs168":o168["mm"] if o168["complete"] else None,"obs168_count":o168["count"],
          "fc24":f24["mm"] if f24["complete"] else None,"fc24_count":f24["count"],
          "fc48":f48["mm"] if f48["complete"] else None,"fc48_count":f48["count"],
          "fc72":f72["mm"] if f72["complete"] else None,"fc72_count":f72["count"],
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

    generated=parse_utc(rain.get("generated_at_utc"))
    obs_last=max(latest_obs) if latest_obs else None
    forcing_age=(now-generated).total_seconds()/3600 if generated else None
    obs_age=(now-obs_last).total_seconds()/3600 if obs_last else None
    gates=rain.get("gates") or {}
    stale_reasons=[]
    if obs_age is None or obs_age>6:
        stale_reasons.append("observed_rain_older_than_6h")
    if forcing_age is None or forcing_age>18:
        stale_reasons.append("merged_forcing_older_than_18h")
    forecast48=aw("fc48")
    if forecast48 is None:
        stale_reasons.append("future_48h_forecast_incomplete")

    return {
      "as_of_utc":now.isoformat().replace("+00:00","Z"),
      "observed_24h_basin_mm":aw("obs24"),
      "observed_72h_basin_mm":aw("obs72"),
      "observed_168h_basin_mm":aw("obs168"),
      "forecast_24h_basin_mm":aw("fc24"),
      "forecast_48h_basin_mm":forecast48,
      "forecast_72h_basin_mm":aw("fc72"),
      "component_forecast_48h_fraction":frac,
      "component_values":comp,
      "freshness":{
        "forcing_generated_at_utc":rain.get("generated_at_utc"),
        "forcing_age_hours":forcing_age,
        "latest_observed_rain_utc":obs_last.isoformat().replace("+00:00","Z") if obs_last else None,
        "observed_rain_age_hours":obs_age,
        "first_future_forecast_utc":min(first_future).isoformat().replace("+00:00","Z") if first_future else None,
        "exact_ecmwf_cycle_id_available":gates.get("exact_ecmwf_cycle_id_available"),
        "stale_reasons":stale_reasons,
        "critical_stale":bool(stale_reasons),
      }
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

    # Compare like with like: rainfall strictly BEFORE the historical event.
    # Never use first/max event rainfall as an antecedent-state proxy.
    wet_live=live_rain.get("observed_72h_basin_mm")
    wet_hist=(hist.get("antecedent") or {}).get("rain_72h_mm")
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
            conf_raw="high"
        elif topd is not None and topd<0.75:
            conf_raw="medium"
        else:
            conf_raw="low"

        freshness=lr.get("freshness") or {}
        if freshness.get("critical_stale"):
            conf="low"
            confidence_cap_reason="critical_input_freshness"
        elif freshness.get("exact_ecmwf_cycle_id_available") is False and conf_raw=="high":
            conf="medium"
            confidence_cap_reason="ecmwf_cycle_id_unverified"
        else:
            conf=conf_raw
            confidence_cap_reason=None

        fallback=fallbacks.get(code)
        use_fallback=not chosen or conf=="low"
        target_results.append({
          "target_code":code,"target_name":target.get("name"),
          "library_status":target.get("status"),
          "confidence":conf,
          "confidence_before_data_quality_cap":conf_raw,
          "confidence_cap_reason":confidence_cap_reason,
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
