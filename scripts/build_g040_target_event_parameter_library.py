#!/usr/bin/env python3
"""Build a target x event parameter library and historical fingerprints for G040.

This registry intentionally keeps three things separate:
1) target/event-specific candidates selected from real HEC-HMS 4.13 runs;
2) the existing Muçum eventwise research library (Python HEC twin), retained
   as prior evidence and not mislabeled as HEC-HMS binary output;
3) the multi-event HEC candidate as a robust fallback/comparator.

The registry is research-only. Eventwise full-event fits are diagnostic upper
bounds until they pass pseudo-operational replay with the target event excluded.
"""
from __future__ import annotations
import json, math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
CAL=BASE/"g040_e1_multievent_calibration_latest.json"
REFINED=BASE/"g040_target_event_refinement_latest.json"
FORCING=BASE/"historical_calibration_forcing"
ANTECEDENT=BASE/"historical_antecedent_wetness"
MUCUM=ROOT/"assets/data/estudo_bacia_taquari_antas/modelo_mucum_eventwise_v1_fechado_latest.json"
OUT=BASE/"g040_target_event_parameter_library_latest.json"

TARGETS={
 "86510000":"Muçum",
 "86720000":"Encantado",
 "86743000":"Arroio do Meio",
 "86879000":"Lajeado",
 "86879300":"Estrela",
 "86895000":"Porto Mariante",
 "86950000":"Taquari",
 "86996000":"Triunfo",
}

def load(p:Path)->dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8"))

def penalty(m:dict[str,Any])->float|None:
    if not isinstance(m,dict) or int(m.get("pairs") or 0)<4:return None
    vals=[]
    if m.get("nse") is not None: vals.append(max(0.0,1-float(m["nse"])))
    if m.get("kge") is not None: vals.append(max(0.0,1-float(m["kge"])))
    if m.get("normalized_rmse") is not None: vals.append(abs(float(m["normalized_rmse"])))
    if m.get("pbias_pct") is not None: vals.append(abs(float(m["pbias_pct"]))/100)
    if m.get("peak_error_pct") is not None: vals.append(abs(float(m["peak_error_pct"]))/100)
    if m.get("peak_timing_error_h") is not None: vals.append(abs(float(m["peak_timing_error_h"]))/12)
    if m.get("rise_fall_sign_skill") is not None: vals.append(max(0.0,1-float(m["rise_fall_sign_skill"])))
    return sum(vals)/len(vals) if vals else None

def gate(m:dict[str,Any])->bool:
    return bool(
      isinstance(m,dict) and int(m.get("pairs") or 0)>=12
      and m.get("nse") is not None and float(m["nse"])>=0.50
      and m.get("pbias_pct") is not None and abs(float(m["pbias_pct"]))<=20
      and m.get("peak_error_pct") is not None and abs(float(m["peak_error_pct"]))<=20
      and m.get("peak_timing_error_h") is not None and abs(float(m["peak_timing_error_h"]))<=3
      and m.get("rise_fall_sign_skill") is not None and float(m["rise_fall_sign_skill"])>=0.65
    )

def rolling_max(xs:list[float],n:int)->float|None:
    if len(xs)<n:return None
    return max(sum(xs[i:i+n]) for i in range(0,len(xs)-n+1))

def fingerprint(event_id:str)->dict[str,Any]|None:
    p=FORCING/event_id/"rain.json"
    h=FORCING/event_id/"hydro.json"
    if not p.exists() or not h.exists():return None
    rain=load(p); hydro=load(h)
    comps=rain.get("components") or []
    if not comps:return None
    totals={}
    areas={}
    area_total=0.0
    times=None
    weighted=None
    for c in comps:
        cid=str(c.get("component_id"))
        area=float(c.get("support_area_km2") or 0)
        vals=[None if r.get("mm") is None else float(r["mm"]) for r in (c.get("series") or [])]
        good=[v for v in vals if v is not None]
        totals[cid]=sum(good) if good else None
        areas[cid]=area
        if area<=0: continue
        if times is None:
            times=[r.get("time_local") for r in c.get("series") or []]
            weighted=[0.0]*len(vals)
            weights=[0.0]*len(vals)
        for i,v in enumerate(vals):
            if v is not None:
                weighted[i]+=v*area; weights[i]+=area
        area_total+=area
    basin=[]
    if weighted is not None:
        basin=[weighted[i]/weights[i] for i in range(len(weighted)) if weights[i]>0]
    contrib={k:(None if v is None else float(v)*float(areas.get(k) or 0.0)) for k,v in totals.items()}
    s=sum(v for v in contrib.values() if v is not None)
    spatial={k:(None if v is None or s<=0 else v/s) for k,v in contrib.items()}
    controls={}
    for c in hydro.get("controls") or []:
        rows=[r for r in (c.get("recent_rows") or []) if r.get("flow_m3s") is not None]
        if not rows:continue
        q=[float(r["flow_m3s"]) for r in rows]
        controls[str(c.get("code"))]={
          "start_q_m3s":q[0],"peak_q_m3s":max(q),"end_q_m3s":q[-1],
          "early_6h_delta_q_m3s":(q[min(6,len(q)-1)]-q[0]) if len(q)>1 else 0.0
        }
    ant_path=ANTECEDENT/f"{event_id}.json"
    ant=load(ant_path).get("summary") if ant_path.exists() else {}
    return {
      "event_id":event_id,
      "antecedent":{
        "rain_24h_mm":ant.get("rain_24h_mm"),
        "rain_72h_mm":ant.get("rain_72h_mm"),
        "rain_168h_mm":ant.get("rain_168h_mm"),
        "api_tau_72h_mm":ant.get("api_tau_72h_mm"),
        "strictly_pre_event":bool(ant_path.exists()),
        "source":str(ant_path.relative_to(ROOT)) if ant_path.exists() else None,
      },
      "rain":{
        "basin_total_mm":sum(basin) if basin else None,
        "first_24h_mm":sum(basin[:24]) if basin else None,
        "first_48h_mm":sum(basin[:48]) if basin else None,
        "max_6h_mm":rolling_max(basin,6),
        "max_12h_mm":rolling_max(basin,12),
        "max_24h_mm":rolling_max(basin,24),
        "max_48h_mm":rolling_max(basin,48),
        "component_total_mm":totals,
        "component_fraction":spatial,
      },
      "hydrology":controls,
      "source":"historical_calibration_forcing"
    }

def main()->int:
    cal=load(CAL)
    refined=load(REFINED) if REFINED.exists() else {}
    refined_by={(str(x.get("target_code")),str(x.get("event_id"))):x for x in (refined.get("selected") or []) if x.get("target_code") and x.get("event_id")}
    rows=cal.get("ranked_candidates") or []
    events=sorted({e.get("event_id") for r in rows for e in (r.get("events") or []) if e.get("event_id")})
    fps={eid:fingerprint(eid) for eid in events}
    fps={k:v for k,v in fps.items() if v}

    target_event=[]
    for eid in events:
        for code,name in TARGETS.items():
            choices=[]
            for r in rows:
                ev=next((e for e in (r.get("events") or []) if e.get("event_id")==eid),None)
                if not ev:continue
                m=(ev.get("scores") or {}).get(code)
                p=penalty(m)
                if p is None:continue
                choices.append({
                  "candidate_id":r.get("candidate_id"),"parameters":r.get("parameters"),
                  "metrics":m,"checkpoint_gate_pass":gate(m),"penalty":p
                })
            if not choices:continue
            choices.sort(key=lambda x:(0 if x["checkpoint_gate_pass"] else 1,x["penalty"]))
            best=choices[0]
            source="initial_multievent_candidate_pool"
            fit_role="target_event_diagnostic_candidate"

            rr=refined_by.get((code,eid))
            if rr and isinstance(rr.get("best"),dict):
                rb=rr["best"]
                rm=rb.get("metrics") or {}
                rp=penalty(rm)
                if rp is not None:
                    refined_choice={
                      "candidate_id":rb.get("candidate_id"),
                      "parameters":rb.get("parameters"),
                      "metrics":rm,
                      "checkpoint_gate_pass":bool(rb.get("gate_pass")),
                      "penalty":float(rb.get("target_loss") if rb.get("target_loss") is not None else rp),
                    }
                    # Refinement was target-specific by construction. Prefer it
                    # when it passes the gate or improves target-specific fit.
                    if (
                        refined_choice["checkpoint_gate_pass"]
                        or not best["checkpoint_gate_pass"]
                        or refined_choice["penalty"] < best["penalty"]
                    ):
                        best=refined_choice
                        source="target_event_refinement"
                        fit_role="target_event_refined_donor"

            target_event.append({
              "target_code":code,"target_name":name,"event_id":eid,
              "model_family":"hec_hms_4_13_bho6_e1",
              "fit_role":fit_role,
              "selection_source":source,
              **best,
              "promotion_allowed":False,
              "leakage_warning":"selected using the full historical event; must not be interpreted as pseudo-operational forecast skill"
            })

    robust=cal.get("best_calibration_candidate") or {}
    fallbacks=[]
    for code,name in TARGETS.items():
        fallbacks.append({
          "target_code":code,"target_name":name,
          "model_family":"hec_hms_4_13_bho6_e1",
          "role":"multi_event_robust_fallback",
          "candidate_id":robust.get("candidate_id"),
          "parameters":robust.get("parameters"),
          "promotion_allowed":False,
        })

    muc=load(MUCUM)
    legacy=[]
    for r in muc.get("params_library_eventwise") or []:
        legacy.append({
          "target_code":"86510000","target_name":"Muçum","event_id":r.get("event_id"),
          "model_family":"python_hms_twin_ic_clark_recession_muskingum",
          "fit_role":"legacy_eventwise_research_library",
          "nse":r.get("nse"),"research_score":r.get("research_score"),
          "metrics":r.get("metrics"),"parameters":r.get("params"),
          "promotion_allowed":False,
          "engine_note":"existing Muçum eventwise evidence; not HEC-HMS 4.13 binary"
        })

    payload={
      "schema_version":"g040_target_event_parameter_library_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,
      "policy":{
        "primary":"target x event libraries plus analog selection",
        "common_parameterization":"fallback/comparator only",
        "pseudo_operational_requirement":"target event excluded from donor library; observations after t0 forbidden",
      },
      "historical_fingerprints":fps,
      "hec_target_event_candidates":target_event,
      "robust_fallbacks":fallbacks,
      "existing_mucum_eventwise_library":legacy,
      "coverage":{
        "targets_with_hec_eventwise_candidates":sorted({x["target_code"] for x in target_event}),
        "events_with_full_basin_fingerprints":sorted(fps),
        "events_with_true_antecedent_wetness":sorted(k for k,v in fps.items() if (v.get("antecedent") or {}).get("strictly_pre_event")),
        "mucum_existing_eventwise_events":[x["event_id"] for x in legacy],
        "refined_target_event_rows_used":sum(x.get("selection_source")=="target_event_refinement" for x in target_event),
      }
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"G040_TARGET_EVENT_LIBRARY_READY","hec_rows":len(target_event),"fingerprints":len(fps),"mucum_legacy_rows":len(legacy)},ensure_ascii=False))
    return 0
if __name__=="__main__": raise SystemExit(main())
