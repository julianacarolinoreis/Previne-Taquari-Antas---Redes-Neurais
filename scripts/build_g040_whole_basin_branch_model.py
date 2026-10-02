#!/usr/bin/env python3
"""Build an auditable whole-basin observed-branch architecture for G040.

Purpose
-------
Create the intermediate, executable-design layer between the validated Muçum
dual-boundary experiment and the final 145-subbasin HEC-HMS reconstruction.

This architecture NEVER promotes the 32 IEDE management polygons to HEC
computational subbasins. It selects fresh/operational hydrometric controls on
major non-overlapping branches and downstream mainstem checkpoints, while the
145 report-listed subbasins + 72 reaches remain the final computational target.

Research only; not an official warning system.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "assets/data/hec_hms_g040_full_basin"
STATIONS = BASE / "full_basin_station_matrix.csv"
REPORT145 = BASE / "original_145_report_inventory_latest.json"
OUT = BASE / "whole_basin_branch_model_latest.json"
OUTCSV = BASE / "whole_basin_branch_controls.csv"

# Controls chosen to maximize branch independence and preserve downstream checks.
# They are verified against the repository station inventory at build time.
BRANCH_CONTROLS = [
    {"role":"upper_antas","code":"86472000","label":"Linha José Júlio","branch":"Antas/Taquari principal","kind":"boundary","mass_balance":True},
    {"role":"prata","code":"86447000","label":"UHE Monte Claro Balsa do Prata","branch":"Prata","kind":"upstream_state_diagnostic","mass_balance":False},
    {"role":"carreiro","code":"86500000","label":"Passo Carreiro","branch":"Carreiro","kind":"tributary_boundary","mass_balance":True},
    {"role":"guapore","code":"86595000","label":"Barra do Zeferino","branch":"Guaporé","kind":"tributary_boundary","mass_balance":True},
    {"role":"forqueta","code":"86746000","label":"Rio Forqueta (Travesseiro)","branch":"Forqueta","kind":"tributary_boundary","mass_balance":True},
]

MAINSTEM_CHECKPOINTS = [
    {"code":"86510000","label":"Muçum","order":1},
    {"code":"86720000","label":"Encantado","order":2},
    {"code":"86743000","label":"Arroio do Meio","order":3},
    {"code":"86879000","label":"Lajeado","order":4},
    {"code":"86879300","label":"Estrela","order":5},
    {"code":"86895000","label":"Porto Mariante","order":6},
    {"code":"86950000","label":"Taquari","order":7},
    {"code":"86996000","label":"Rio Taquari (Triunfo)","order":8},
]

def load_station_matrix():
    rows=[]
    with STATIONS.open(encoding="utf-8",newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("kind")!="flow":
                continue
            rows.append(r)
    return rows

def by_code(rows):
    return {str(r["code"]):r for r in rows}

def require_station(idx, code):
    if code not in idx:
        raise RuntimeError(f"required G040 flow station missing from matrix: {code}")
    r=idx[code]
    return {
        "code":code,
        "name":r.get("name"),
        "network":r.get("network"),
        "operating":r.get("operating"),
        "drainage_area_km2":None if not r.get("drainage_area_km2") else float(r["drainage_area_km2"]),
        "management_subbasin":r.get("subbasin"),
        "management_unit":r.get("ug"),
        "lon":float(r["lon"]),
        "lat":float(r["lat"]),
    }

def main():
    rows=load_station_matrix()
    idx=by_code(rows)
    report=json.loads(REPORT145.read_text(encoding="utf-8"))
    if len(report.get("subbasins") or []) != 145:
        raise RuntimeError("145-subbasin report inventory is not complete")
    if int((report.get("scope") or {}).get("hec_reaches") or 0) != 72:
        raise RuntimeError("72-reach report inventory is not complete")

    branches=[]
    for spec in BRANCH_CONTROLS:
        st=require_station(idx,spec["code"])
        branches.append({**spec,"station":st})

    mainstem=[]
    for spec in MAINSTEM_CHECKPOINTS:
        st=require_station(idx,spec["code"])
        mainstem.append({**spec,"station":st})

    payload={
        "schema_version":"g040_whole_basin_observed_branch_architecture_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"WHOLE_BASIN_BRANCH_ARCHITECTURE_READY_FOR_BHO6_TOPOLOGY_AND_LIVE_FORCING",
        "scope":{
            "basin":"Taquari-Antas G040",
            "official_area_km2":26430,
            "final_hec_target_subbasins":145,
            "final_hec_target_reaches":72,
            "intermediate_model":"major observed branches + incremental rainfall-runoff + routed Taquari mainstem",
            "outlet_target":"Taquari-Jacuí / lower G040",
        },
        "scientific_position":{
            "why_this_layer":"generalize the validated Muçum dual-boundary concept to the whole basin before native 145 geometry is recovered/reconstructed",
            "not_a_replacement_for_145":True,
            "management_32_are_not_computational_subbasins":True,
            "nested_gauges_rule":"nested gauges are state/QC constraints; only non-overlapping branch controls enter mass balance",
            "prata_note":"Prata is upstream of Linha José Júlio and is therefore diagnostic only whenever Linha José Júlio is used as the Antas boundary; never add both as independent flows",
        },
        "major_branch_controls":branches,
        "mainstem_checkpoints":mainstem,
        "proposed_hec_logic":[
            "Observed flow boundaries on major non-overlapping branches when fresh and quality-controlled",
            "Hourly accumulated observed rainfall spatialized over residual/intermediate contributing areas; missing never becomes zero",
            "ECMWF/IFS spatial field after t0 with cycle and lead time preserved",
            "Route flows through BHO6-verified reach order; calibrate reach storage/travel time branch-wise",
            "At each downstream checkpoint compare native HEC discharge/stage proxy, trend, 6h/12h hydrograph and peak timing",
            "Never promote a run by visual stage shifting or conditioned display-only curves",
        ],
        "calibration_sequence":[
            {"phase":1,"name":"branch state closure","targets":["86472000","86447000","86500000","86595000","86746000"]},
            {"phase":2,"name":"upper-middle mainstem","targets":["86510000","86720000"]},
            {"phase":3,"name":"middle-lower mainstem","targets":["86743000","86879000","86879300"]},
            {"phase":4,"name":"lower Taquari","targets":["86895000","86950000","86996000"],"note":"stage/inundation may require HEC-RAS because Jacuí/Guaíba backwater is outside pure HEC-HMS routing"},
            {"phase":5,"name":"145-subbasin transfer","target":"replace residual coarse areas with verified native/reconstructed 145 computational polygons and 72 reaches"},
        ],
        "forcing_contract":{
            "observed_rain":"hourly accumulated precipitation from all valid gauges, spatialized; no summing station mm as one physical basin depth",
            "forecast_rain":"ECMWF/IFS spatial field",
            "flow_state":"fresh observed discharge/level where available",
            "wetness":"explicit warm-up/state handling; future SMA option remains separate from legacy SCS-CN event model",
        },
        "validation_gate":{
            "state_native_required":True,
            "metrics":["NSE","KGE","PBIAS","RMSE","MAE","volume_error","peak_error","peak_timing_error","rise_fall_skill"],
            "multi_event_required":True,
            "independent_validation_required":True,
            "pseudo_operational_replay_required":True,
        },
        "next_build_gates":{
            "bho6_station_snap_and_branch_order":"PENDING",
            "incremental_catchment_geometry":"PENDING",
            "live_multistation_observed_package_full_g040":"PENDING",
            "full_g040_ecmwf_spatial_forcing":"PARTIAL_EXISTS_600_CELL_CONTRACT",
            "hec_hms_project_generation":"PENDING_AFTER_TOPOLOGY",
            "145_native_or_reconstructed_geometry":"PENDING",
        },
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    fields=["group","role","order","code","label","station_name","operating","drainage_area_km2","management_subbasin","management_unit","lon","lat"]
    with OUTCSV.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader()
        for b in branches:
            s=b["station"]
            w.writerow({"group":"branch","role":b["role"],"order":"","code":b["code"],"label":b["label"],
                        "station_name":s["name"],"operating":s["operating"],"drainage_area_km2":s["drainage_area_km2"],
                        "management_subbasin":s["management_subbasin"],"management_unit":s["management_unit"],
                        "lon":s["lon"],"lat":s["lat"]})
        for m in mainstem:
            s=m["station"]
            w.writerow({"group":"mainstem","role":"checkpoint","order":m["order"],"code":m["code"],"label":m["label"],
                        "station_name":s["name"],"operating":s["operating"],"drainage_area_km2":s["drainage_area_km2"],
                        "management_subbasin":s["management_subbasin"],"management_unit":s["management_unit"],
                        "lon":s["lon"],"lat":s["lat"]})

    print(json.dumps({
        "status":payload["status"],
        "branch_controls":len(branches),
        "mainstem_checkpoints":len(mainstem),
        "final_hec_target_subbasins":145,
        "final_hec_target_reaches":72,
        "out":str(OUT.relative_to(ROOT)),
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
