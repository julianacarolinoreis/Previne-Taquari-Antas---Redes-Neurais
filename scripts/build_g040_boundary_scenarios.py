#!/usr/bin/env python3
"""Build dynamic observed-boundary scenarios for the G040 branch HEC model.

The full architecture has preferred independent observed boundaries, but a live
HEC run may use only those with fresh observed discharge. When a boundary is
inactive, its upstream area is returned to the rainfall-runoff residual of the
mainstem interval where it enters. No synthetic discharge is inserted.

Research only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
BUDGET=BASE/"whole_basin_incremental_area_budget_latest.json"
HYDRO=BASE/"whole_basin_live_hydro_controls_latest.json"
OUT=BASE/"whole_basin_boundary_scenarios_latest.json"

def build_scenario(name,budget,active_codes,reason):
    active=set(str(x) for x in active_codes)
    intervals=[]
    total_observed=0.0
    total_residual=0.0
    for item in budget["intervals"]:
        preferred=item.get("entering_observed_boundaries") or []
        used=[]
        returned=[]
        returned_area=0.0
        used_area=0.0
        for b in preferred:
            code=str(b["station_code"])
            a=float(b["boundary_area_km2_bho6"])
            if code in active:
                used.append(b); used_area+=a
            else:
                returned.append(b); returned_area+=a
        residual=float(item["residual_rainfall_runoff_area_km2"])+returned_area
        total_observed+=used_area
        total_residual+=residual
        intervals.append({
          "interval_id":item["interval_id"],
          "upstream_station":item["upstream_station"],
          "downstream_station":item["downstream_station"],
          "gross_increment_km2":item["gross_increment_km2"],
          "active_observed_boundaries":used,
          "inactive_boundaries_returned_to_rainfall_runoff":returned,
          "observed_boundary_area_km2":round(used_area,3),
          "effective_rainfall_runoff_area_km2":round(residual,3),
        })
    start=float(budget["upstream_observed_boundary_area_km2"])
    outlet=float(budget["downstream_cumulative_area_km2"])
    closure=start+total_observed+total_residual
    return {
      "name":name,
      "reason":reason,
      "active_boundary_codes":sorted(active),
      "upstream_ljj_boundary_area_km2":round(start,3),
      "active_tributary_boundary_area_km2":round(total_observed,3),
      "effective_rainfall_runoff_area_km2":round(total_residual,3),
      "outlet_area_km2":round(outlet,3),
      "closure_error_km2":round(closure-outlet,6),
      "intervals":intervals,
    }

def main():
    b=json.loads(BUDGET.read_text(encoding="utf-8"))
    h=json.loads(HYDRO.read_text(encoding="utf-8"))
    preferred=[
      str(x["code"]) for x in h["controls"]
      if x.get("group")=="branch" and x.get("mass_balance") is True and str(x["code"])!="86472000"
    ]
    fresh=[
      str(x["code"]) for x in h["controls"]
      if x.get("group")=="branch" and x.get("mass_balance") is True
      and str(x["code"])!="86472000" and x.get("fresh_flow_boundary") is True
    ]
    scenarios=[
      build_scenario("preferred_all_boundaries",b,preferred,
                     "research scenario using all preferred independent branch boundaries when Q is available"),
      build_scenario("live_available_boundaries",b,fresh,
                     "current live scenario; unavailable branch Q is represented by rainfall-runoff, not synthetic flow"),
      build_scenario("ljj_only",b,[],
                     "fallback sensitivity scenario with only Linha Jose Julio as observed upstream boundary"),
    ]
    current=next(x for x in scenarios if x["name"]=="live_available_boundaries")
    if any(abs(x["closure_error_km2"])>0.5 for x in scenarios):
        raise RuntimeError("boundary scenario area closure failed")
    payload={
      "schema_version":"g040_whole_basin_boundary_scenarios_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,
      "preferred_tributary_boundaries":preferred,
      "currently_fresh_tributary_boundaries":fresh,
      "current_scenario":"live_available_boundaries",
      "current":current,
      "scenarios":scenarios,
      "policy":{
        "missing_boundary_q":"return its contributing area to rainfall-runoff",
        "forbidden":"zero-fill or synthetic discharge presented as observation",
        "linea_jose_julio":"primary Antas upstream boundary; Prata remains nested diagnostic",
      },
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
      "current_active_boundaries":fresh,
      "current_effective_rainfall_runoff_area_km2":current["effective_rainfall_runoff_area_km2"],
      "current_closure_error_km2":current["closure_error_km2"],
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
