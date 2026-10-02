#!/usr/bin/env python3
"""Build area budget for the G040 whole-basin observed-branch HEC architecture.

Uses BHO6 cumulative drainage areas at verified mainstem/control segments.
For each mainstem interval:
  residual_area = downstream_area - upstream_area - entering_observed_boundary_areas

Residual area is the rainfall-runoff area still to be represented explicitly.
Observed branch boundaries are not double-counted. Prata remains diagnostic
because it is already nested inside Linha Jose Julio.

Research only.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
TOPO=BASE/"whole_basin_bho6_topology_latest.json"
OUT=BASE/"whole_basin_incremental_area_budget_latest.json"
OUTCSV=BASE/"whole_basin_incremental_area_budget.csv"

def main():
    j=json.loads(TOPO.read_text(encoding="utf-8"))
    if not j.get("topology_pass"):
        raise RuntimeError("BHO6 topology has not passed")

    trib=j.get("tributary_connections") or {}
    intervals=[]
    total_residual=0.0
    total_entering=0.0

    # deterministic order follows JSON mainstem chain
    chain=j["mainstem_chain"]
    paths=j["mainstem_paths"]

    for up,down in zip(chain,chain[1:]):
        key=f"{up}_to_{down}"
        p=paths[key]
        start=float(p["start_area_km2"])
        end=float(p["end_area_km2"])
        delta=end-start
        segment_ids=set(int(x) for x in p.get("segments") or [])
        entering=[]
        entering_area=0.0
        for code,t in trib.items():
            if not t.get("mass_balance"):
                continue
            join=t.get("join_mainstem_fid")
            if join is None or int(join) not in segment_ids:
                continue
            snap=t.get("snap") or {}
            a=float((snap.get("segment") or {}).get("nuareamont") or 0.0)
            entering.append({
                "station_code":code,
                "branch":t.get("branch"),
                "join_mainstem_fid":int(join),
                "boundary_area_km2_bho6":round(a,3),
            })
            entering_area+=a
        residual=delta-entering_area
        # Tiny negatives can occur only from floating precision. A real
        # negative value is a mass-balance/topology error and must block.
        if residual < -0.5:
            raise RuntimeError(
                f"negative residual area {key}: delta={delta:.3f}, entering={entering_area:.3f}"
            )
        residual=max(0.0,residual)
        total_residual+=residual
        total_entering+=entering_area
        intervals.append({
            "interval_id":f"INC_{up}_{down}",
            "upstream_station":up,
            "downstream_station":down,
            "mainstem_length_km":float(p["length_km"]),
            "upstream_cumulative_area_km2":round(start,3),
            "downstream_cumulative_area_km2":round(end,3),
            "gross_increment_km2":round(delta,3),
            "entering_observed_boundaries":entering,
            "entering_observed_area_km2":round(entering_area,3),
            "residual_rainfall_runoff_area_km2":round(residual,3),
            "hec_role":"incremental_subbasin",
        })

    first_area=float(paths[f"{chain[0]}_to_{chain[1]}"]["start_area_km2"])
    last_area=float(paths[f"{chain[-2]}_to_{chain[-1]}"]["end_area_km2"])
    closure=first_area+total_entering+total_residual
    error=closure-last_area

    payload={
        "schema_version":"g040_whole_basin_incremental_area_budget_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"AREA_BUDGET_CLOSED" if abs(error)<=0.5 else "AREA_BUDGET_REVIEW",
        "source":"ANA/SNIRH BHO6 cumulative drainage areas from verified topology",
        "mainstem_start_station":chain[0],
        "mainstem_end_station":chain[-1],
        "upstream_observed_boundary_area_km2":round(first_area,3),
        "entering_observed_branch_area_km2":round(total_entering,3),
        "residual_rainfall_runoff_area_km2":round(total_residual,3),
        "downstream_cumulative_area_km2":round(last_area,3),
        "closure_area_km2":round(closure,3),
        "closure_error_km2":round(error,6),
        "closure_error_pct":round(100*error/last_area,6) if last_area else None,
        "intervals":intervals,
        "interpretation":{
            "observed_boundary_area":"already represented by observed discharge and therefore removed from residual rainfall-runoff area",
            "residual_area":"area that still requires explicit rainfall-runoff generation between observed boundaries/checkpoints",
            "prata":"diagnostic upstream state only while Linha Jose Julio is the Antas boundary",
        },
        "next_step":"build HEC-HMS branch skeleton with one residual subbasin per interval and observed Source elements for independent branch boundaries",
    }
    if abs(error)>0.5:
        raise RuntimeError(f"area budget did not close: {error:.3f} km2")
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    fields=[
      "interval_id","upstream_station","downstream_station","mainstem_length_km",
      "upstream_cumulative_area_km2","downstream_cumulative_area_km2",
      "gross_increment_km2","entering_observed_area_km2",
      "residual_rainfall_runoff_area_km2","entering_boundary_codes"
    ]
    with OUTCSV.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader()
        for x in intervals:
            w.writerow({
              **{k:x[k] for k in fields if k!="entering_boundary_codes"},
              "entering_boundary_codes":";".join(y["station_code"] for y in x["entering_observed_boundaries"])
            })

    print(json.dumps({
      "status":payload["status"],
      "interval_count":len(intervals),
      "upstream_boundary_area_km2":payload["upstream_observed_boundary_area_km2"],
      "observed_branch_area_km2":payload["entering_observed_branch_area_km2"],
      "residual_area_km2":payload["residual_rainfall_runoff_area_km2"],
      "outlet_area_km2":payload["downstream_cumulative_area_km2"],
      "closure_error_km2":payload["closure_error_km2"],
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
