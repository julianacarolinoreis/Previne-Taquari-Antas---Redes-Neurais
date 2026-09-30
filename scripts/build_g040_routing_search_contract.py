#!/usr/bin/env python3
"""Build conservative routing-search constraints for the G040 HEC model.

Observed multi-event lags constrain aggregate routing searches but are never
assigned directly as Muskingum K. Search windows deliberately include margin
for lateral inflows, storage, hourly discretization, and partial observations.

Research only.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
DIAG=BASE/"whole_basin_multi_event_propagation_diagnostics_latest.json"
TOPO=BASE/"whole_basin_bho6_topology_latest.json"
OUT=BASE/"whole_basin_routing_search_contract_latest.json"

def main():
    d=json.loads(DIAG.read_text(encoding="utf-8"))
    t=json.loads(TOPO.read_text(encoding="utf-8"))
    by={x["label"]:x for x in d["pair_summaries"]}

    def contract(label,intervals,margin_low,margin_high,min_k=0.25,confidence=None):
        x=by[label]
        rg=x.get("diagnostic_lag_range_h")
        usable=int(x.get("events_usable_medium_or_high") or 0)
        if not rg or usable==0:
            return {
              "label":label,"intervals":intervals,"evidence":"NO_Q_LAG_CONSTRAINT",
              "usable_events":usable,"aggregate_K_search_h":None,
              "note":"derive from reach hydraulics and calibrate against other observables/events",
            }
        lo=max(min_k,float(rg[0])-margin_low)
        hi=max(lo+0.25,float(rg[1])+margin_high)
        conf=confidence or ("high" if usable>=4 else "medium" if usable>=3 else "low")
        return {
          "label":label,"intervals":intervals,
          "usable_events":usable,
          "diagnostic_lag_center_h":x.get("diagnostic_lag_center_h"),
          "diagnostic_lag_range_h":rg,
          "aggregate_K_search_h":[round(lo,2),round(hi,2)],
          "confidence":conf,
          "constraint_type":"aggregate search window, not direct K assignment",
          "calibration_objective":[
            "NSE","KGE","PBIAS","RMSE","volume_error",
            "peak_error","peak_timing_error","rise_fall_skill"
          ],
        }

    constraints=[
      contract("Linha Jose Julio -> Mucum",
               ["86472000_to_86510000"],1.0,2.0,0.5,"high"),
      contract("Mucum -> Encantado",
               ["86510000_to_86720000"],0.0,2.0,0.25,"high"),
      contract("Encantado -> Estrela composite",
               ["86720000_to_86743000","86743000_to_86879000","86879000_to_86879300"],
               0.5,4.0,0.5,"medium"),
      contract("Estrela -> Porto Mariante",
               ["86879300_to_86895000"],0.0,6.0,0.5,"low"),
      {
        "label":"Porto Mariante -> Taquari",
        "intervals":["86895000_to_86950000"],
        "usable_events":0,"evidence":"NO_DOWNSTREAM_Q_IN_CURRENT_ARCHIVE",
        "aggregate_K_search_h":None,"confidence":"none",
        "note":"Taquari has stage but no discharge in the ANA responses used; use hydraulic/level timing evidence only after datum/time audit."
      },
      {
        "label":"Taquari -> Triunfo",
        "intervals":["86950000_to_86996000"],
        "usable_events":0,"evidence":"NO_PAIR_Q",
        "aggregate_K_search_h":None,"confidence":"none",
        "note":"lower Taquari routing may require HEC-RAS/backwater representation before stage validation."
      }
    ]

    payload={
      "schema_version":"g040_routing_search_contract_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,
      "constraints":constraints,
      "rules":{
        "observed_lag":"constraint for aggregate routing search only",
        "muskingum_K":"must be optimized in HEC; never copied from statistical lag",
        "muskingum_X":"search physically admissible range and validate sensitivity",
        "split_reaches":"when a tributary join splits an interval, the aggregate constraint applies to the sum/effective travel behavior, not equal K on both pieces",
        "event_use":"calibration and independent validation partitions must remain separated before promotion",
        "current_Mucum_K_1_25h":"local current-event result; not transferable basin-wide without multi-event evidence"
      },
      "topology_reference":"whole_basin_bho6_topology_latest.json",
      "diagnostic_reference":"whole_basin_multi_event_propagation_diagnostics_latest.json",
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"constraints":[{"label":x["label"],"K_search":x.get("aggregate_K_search_h"),"confidence":x.get("confidence")} for x in constraints]},ensure_ascii=False))
    return 0

if __name__=="__main__": raise SystemExit(main())
