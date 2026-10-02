#!/usr/bin/env python3
"""Build a source-auditable SMA parameter template for the current BHO6 branch model.

The template is derived from the same support mesh used by observed/forecast
rainfall. It creates one row per hydrologic component (8 mainstem-core
increments + 3 tributary branches). No SMA numerical parameter is guessed.

Research only.
"""
from __future__ import annotations
import csv, json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
STACK=ROOT/"assets/data/g040_hydro_stack"
SUPPORT=BASE/"whole_basin_rain_support_points.csv"
SCENARIOS=BASE/"whole_basin_boundary_scenarios_latest.json"
OUT=STACK/"sma_branch_parameter_template.csv"
AUDIT=STACK/"sma_branch_parameter_template_audit.json"

PARAMS=[
 "canopy_storage_mm","surface_storage_mm","soil_storage_mm","tension_storage_mm",
 "soil_percolation_mm_h","gw1_storage_mm","gw1_percolation_mm_h","gw1_coefficient_h",
 "gw2_storage_mm","gw2_percolation_mm_h","gw2_coefficient_h",
 "initial_canopy_pct","initial_surface_pct","initial_soil_pct","initial_gw1_pct","initial_gw2_pct",
]

def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def main():
    if not SUPPORT.exists():
        raise RuntimeError("BHO6 support mesh missing")
    scenarios=json.loads(SCENARIOS.read_text(encoding="utf-8"))
    current=scenarios.get("current") or {}
    active={str(x) for x in current.get("active_boundary_codes") or []}
    grouped={}
    with SUPPORT.open(encoding="utf-8",newline="") as fh:
        for r in csv.DictReader(fh):
            cid=str(r.get("component_id") or "").strip()
            if not cid:
                raise RuntimeError("support point without component_id")
            g=grouped.setdefault(cid,{
                "area_km2":0.0,"support_points":0,"boundary_codes":set(),
            })
            g["area_km2"]+=float(r["local_area_km2"])
            g["support_points"]+=1
            b=str(r.get("tributary_boundary_code") or "").strip()
            if b: g["boundary_codes"].add(b)

    if len(grouped)!=11:
        raise RuntimeError(f"expected 11 BHO6 rainfall-runoff components; found {len(grouped)}")
    branch_count=sum(cid.startswith("BRANCH_") for cid in grouped)
    core_count=sum(cid.startswith("CORE_INC_") for cid in grouped)
    if branch_count!=3 or core_count!=8:
        raise RuntimeError(f"unexpected component split: branches={branch_count}, core={core_count}")

    STACK.mkdir(parents=True,exist_ok=True)
    fields=[
        "component_id","component_type","tributary_boundary_code",
        "gross_area_km2","support_points","used_as_rainfall_runoff_current_scenario",
        "soil_source","land_cover_source","pet_source","warmup_start","parameter_source",
        *PARAMS,"calibration_status","notes",
    ]
    with OUT.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader()
        for cid,g in sorted(grouped.items()):
            branch=cid.replace("BRANCH_","",1) if cid.startswith("BRANCH_") else ""
            row={k:"" for k in fields}
            row.update({
                "component_id":cid,
                "component_type":"tributary_branch" if branch else "mainstem_core_increment",
                "tributary_boundary_code":branch,
                "gross_area_km2":f"{g['area_km2']:.6f}",
                "support_points":g["support_points"],
                "used_as_rainfall_runoff_current_scenario":"NO" if branch and branch in active else "YES",
                "calibration_status":"PENDING_SOURCE_BACKED_INITIALIZATION",
                "notes":"SMA numerical fields intentionally blank; do not derive directly from SCS CN.",
            })
            w.writerow(row)

    total=sum(g["area_km2"] for g in grouped.values())
    payload={
        "schema_version":"g040_sma_branch_template_audit_v1",
        "generated_at_utc":now(),
        "research_only":True,
        "component_count":len(grouped),
        "core_component_count":core_count,
        "branch_component_count":branch_count,
        "gross_component_area_km2":round(total,6),
        "current_boundary_scenario":scenarios.get("current_scenario"),
        "active_observed_tributary_boundaries":sorted(active),
        "numeric_sma_parameters_filled":0,
        "parameter_policy":"blank until source-backed initialization; no SCS-CN to SMA conversion",
        "source_candidates":{
            "soil":["IBGE 2023 pedology 1:250000","local permeability measurements","Embrapa 2011 coarse independent reference"],
            "land_cover":["MapBiomas source data; alternate discretization workbook is not a direct crosswalk"],
            "pet":["PENDING_VERIFIED_TIME_SERIES_SOURCE"],
        },
        "next_step":"select PET, spatially intersect source-backed soil/land-cover evidence with component geometry/support, define broad priors, then warm up continuous states",
        "promotion_allowed":False,
    }
    AUDIT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(payload,ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
