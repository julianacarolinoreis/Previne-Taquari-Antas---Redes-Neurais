#!/usr/bin/env python3
"""Build a single auditable Stage-2 readiness package for PREVINE G040.

Outputs:
- master_readiness_latest.json
- tributary_inventory_latest.json
- benchmark_matrix_latest.json

The builder never invents hydrologic parameters. Missing data remain explicit
and block promotion. Research only.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
STACK=ROOT/"assets/data/g040_hydro_stack"

PATHS={
    "rain":BASE/"whole_basin_rain_forcing_latest.json",
    "obs":BASE/"whole_basin_observed_rain_latest.json",
    "ifs":BASE/"whole_basin_ifs_forecast_latest.json",
    "support":BASE/"whole_basin_rain_support_latest.json",
    "skeleton":BASE/"whole_basin_hec_branch_skeleton_latest.json",
    "events":BASE/"whole_basin_historical_hydro_events_latest.json",
    "propagation":BASE/"whole_basin_multi_event_propagation_diagnostics_latest.json",
    "boundary":BASE/"whole_basin_boundary_scenarios_latest.json",
    "live":BASE/"whole_basin_live_hydro_controls_latest.json",
    "e1":BASE/"g040_e1_hindcast/SMOKE_E1/result.json",
    "e1_calibration":BASE/"g040_e1_multievent_calibration_latest.json",
    "legacy_met_audit":BASE/"original_145_meteorologic_assignment_audit_latest.json",
    "sma":STACK/"sma_parameter_template.csv",
    "sma_branch":STACK/"sma_branch_parameter_template.csv",
    "mgb":STACK/"mgb_prep_manifest.json",
    "mgb_readiness":STACK/"mgb_input_readiness_latest.json",
    "ras":STACK/"hec_ras_coupling_manifest.json",
    "ras_pilot_readiness":STACK/"hec_ras_pilot_readiness_latest.json",
    "assim":STACK/"assimilation_ensemble_contract.json",
    "assim_readiness":STACK/"assimilation_readiness_latest.json",
    "ensemble_readiness":STACK/"ensemble_member_inventory_latest.json",
    "sources":STACK/"project_source_inventory_latest.json",
    "legacy_readiness":STACK/"readiness_latest.json",
}

OUT_MASTER=STACK/"master_readiness_latest.json"
OUT_TRIB=STACK/"tributary_inventory_latest.json"
OUT_BENCH=STACK/"benchmark_matrix_latest.json"

REQUIRED_BENCHMARK_EVENTS=[
    "E19_MAY2023","E22_SEP2023","E24_NOV2023",
    "E27_MAY2024","E28_JUN2024","E2026_JUL",
]
PROPOSED_ROLES={
    "E19_MAY2023":"development",
    "E22_SEP2023":"calibration",
    "E24_NOV2023":"calibration",
    "E27_MAY2024":"independent_validation",
    "E28_JUN2024":"independent_validation",
    "E2026_JUL":"pseudo_operational_holdout",
}

def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def jload(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def count_sma_file(path: Path):
    if not path.exists():
        return 0,0
    with path.open(encoding="utf-8",newline="") as fh:
        rows=list(csv.DictReader(fh))
    numeric=[
        "canopy_storage_mm","surface_storage_mm","soil_storage_mm",
        "tension_storage_mm","soil_percolation_mm_h",
        "gw1_storage_mm","gw1_percolation_mm_h","gw1_coefficient_h",
        "gw2_storage_mm","gw2_percolation_mm_h","gw2_coefficient_h",
        "initial_canopy_pct","initial_surface_pct","initial_soil_pct",
        "initial_gw1_pct","initial_gw2_pct",
    ]
    sourced=sum(
        all(str(r.get(k) or "").strip() for k in numeric)
        and bool(str(r.get("parameter_source") or "").strip())
        for r in rows
    )
    return len(rows),sourced

def count_sma_rows():
    return count_sma_file(PATHS["sma"])

def count_sma_branch_rows():
    return count_sma_file(PATHS["sma_branch"])

def gate(passed: bool, detail: Any, blocker: str|None=None):
    out={"pass":bool(passed),"detail":detail}
    if blocker:
        out["blocker"]=blocker
    return out

def historical_event(path: Path):
    return jload(path,{}) or {}

def build_tributaries(boundary, live, events_manifest):
    preferred=boundary.get("preferred_tributary_boundaries") or []
    current=boundary.get("current") or {}
    live_by_code={str(x.get("code")):x for x in (live.get("controls") or [])}
    branch_meta={}
    for interval in current.get("intervals") or []:
        all_rows=(interval.get("active_observed_boundaries") or [])+(interval.get("inactive_boundaries_returned_to_rainfall_runoff") or [])
        for row in all_rows:
            code=str(row.get("station_code"))
            branch_meta[code]={
                "branch":row.get("branch"),
                "join_mainstem_fid":row.get("join_mainstem_fid"),
                "boundary_area_km2_bho6":row.get("boundary_area_km2_bho6"),
                "interval_id":interval.get("interval_id"),
            }

    role_tokens={
        "86500000":["carreiro"],
        "86595000":["guapore","guaporé"],
        "86746000":["forqueta"],
    }
    out=[]
    for code in preferred:
        code=str(code)
        live_row=live_by_code.get(code) or {}
        history=[]
        for ev in events_manifest.get("events") or []:
            event_id=ev.get("event_id")
            p=ROOT/str(ev.get("path"))
            raw=historical_event(p)
            candidates=[]
            for st in raw.get("stations") or []:
                sc=str(st.get("code") or "")
                role=str(st.get("role") or "").lower()
                exact=sc==code
                fallback=any(tok in role for tok in role_tokens.get(code,[]))
                if exact or fallback:
                    candidates.append({
                        "code":sc,
                        "label":st.get("label"),
                        "role":st.get("role"),
                        "exact_boundary_station":exact,
                        "flow_hour_count":int(st.get("flow_hour_count") or 0),
                        "level_hour_count":int(st.get("level_hour_count") or 0),
                        "fetch_ok":bool(st.get("fetch_ok")),
                    })
            best_flow=max((x["flow_hour_count"] for x in candidates),default=0)
            best_level=max((x["level_hour_count"] for x in candidates),default=0)
            history.append({
                "event_id":event_id,
                "candidate_records":candidates,
                "best_flow_hours":best_flow,
                "best_level_hours":best_level,
                "has_exact_boundary_flow":any(x["exact_boundary_station"] and x["flow_hour_count"]>0 for x in candidates),
                "fallback_evidence_only":any((not x["exact_boundary_station"]) and (x["flow_hour_count"]>0 or x["level_hour_count"]>0) for x in candidates),
            })
        out.append({
            "station_code":code,
            **(branch_meta.get(code) or {}),
            "currently_active":code in (current.get("active_boundary_codes") or []),
            "live_fetch_ok":bool(live_row.get("fetch_ok")),
            "fresh_flow_boundary":bool(live_row.get("fresh_flow_boundary")),
            "last_observation_utc":live_row.get("last_observation_utc"),
            "latest_flow_m3s":live_row.get("latest_flow_m3s"),
            "missing_live_policy":"return contributing area to rainfall-runoff; never zero-fill",
            "historical_event_evidence":history,
        })

    payload={
        "schema_version":"g040_tributary_inventory_v1",
        "generated_at_utc":now(),
        "research_only":True,
        "current_scenario":current.get("name"),
        "current_active_boundary_codes":current.get("active_boundary_codes") or [],
        "tributaries":out,
        "policy":{
            "preferred_boundary":"use observed Q only when exact station series is valid/fresh enough for the intended use",
            "fallback_station":"diagnostic evidence only until a defensible transfer/rating relationship is validated",
            "missing":"return contributing area to rainfall-runoff; never zero-fill",
            "forbidden":"zero-fill or synthetic flow presented as observation",
        },
    }
    OUT_TRIB.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return payload

def build_benchmark(events_manifest, propagation):
    prop_by_id={}
    candidates=propagation.get("event_results") or []
    if isinstance(candidates,dict):
        candidates=[{"event_id":k,**(v if isinstance(v,dict) else {})} for k,v in candidates.items()]
    if not candidates:
        raw_events=propagation.get("events") or []
        if raw_events and isinstance(raw_events[0],dict):
            candidates=raw_events
    for row in candidates:
        if isinstance(row,dict) and row.get("event_id"):
            prop_by_id[row["event_id"]]=row
    matrix=[]
    present={x.get("event_id"):x for x in events_manifest.get("events") or []}
    for event_id in REQUIRED_BENCHMARK_EVENTS:
        meta=present.get(event_id) or {}
        pr=prop_by_id.get(event_id) or {}
        pairs=pr.get("pairs") or []
        qualities={}
        for pair in pairs:
            q=str(pair.get("fit_quality") or "none")
            qualities[q]=qualities.get(q,0)+1
        matrix.append({
            "event_id":event_id,
            "proposed_role":PROPOSED_ROLES[event_id],
            "present":bool(meta),
            "station_count":meta.get("station_count"),
            "stations_with_flow":meta.get("stations_with_flow"),
            "stations_with_level":meta.get("stations_with_level"),
            "flow_hours_total":meta.get("flow_hours_total"),
            "propagation_pair_count":len(pairs),
            "propagation_fit_quality_counts":qualities,
            "reliable_peak_lag_pairs":sum(bool(x.get("observed_peak_lag_reliable")) for x in pairs),
            "use_gate":"QC_REQUIRED_BEFORE_CALIBRATION_OR_SCORING",
        })
    payload={
        "schema_version":"g040_benchmark_matrix_v1",
        "generated_at_utc":now(),
        "research_only":True,
        "events":matrix,
        "required_metrics":[
            "NSE","KGE","PBIAS","RMSE","MAE","volume_error",
            "peak_error","peak_timing_error","rise_skill","recession_skill",
        ],
        "checkpoint_policy":"score multiple mainstem checkpoints; do not optimize a single outlet only",
        "split_policy":{
            "proposal_only":True,
            "development":["E19_MAY2023"],
            "calibration":["E22_SEP2023","E24_NOV2023"],
            "independent_validation":["E27_MAY2024","E28_JUN2024"],
            "pseudo_operational_holdout":["E2026_JUL"],
            "no_event_may_move_from_validation_to_calibration_after_results_are_seen":True,
        },
        "promotion_gate":"no model promotion from a single event or only NSE",
    }
    OUT_BENCH.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return payload

def build_master():
    rain=jload(PATHS["rain"],{}) or {}
    obs=jload(PATHS["obs"],{}) or {}
    fc=jload(PATHS["ifs"],{}) or {}
    support=jload(PATHS["support"],{}) or {}
    skeleton=jload(PATHS["skeleton"],{}) or {}
    events=jload(PATHS["events"],{}) or {}
    propagation=jload(PATHS["propagation"],{}) or {}
    boundary=jload(PATHS["boundary"],{}) or {}
    live=jload(PATHS["live"],{}) or {}
    e1=jload(PATHS["e1"],{}) or {}
    e1_calibration=jload(PATHS["e1_calibration"],{}) or {}
    mgb=jload(PATHS["mgb"],{}) or {}
    mgb_ready=jload(PATHS["mgb_readiness"],{}) or {}
    ras=jload(PATHS["ras"],{}) or {}
    ras_pilot=jload(PATHS["ras_pilot_readiness"],{}) or {}
    assim=jload(PATHS["assim"],{}) or {}
    assim_ready=jload(PATHS["assim_readiness"],{}) or {}
    ensemble_ready=jload(PATHS["ensemble_readiness"],{}) or {}
    sources=jload(PATHS["sources"],{}) or {}
    legacy=jload(PATHS["legacy_readiness"],{}) or {}
    met_audit=jload(PATHS["legacy_met_audit"],{}) or {}

    trib=build_tributaries(boundary,live,events)
    bench=build_benchmark(events,propagation)

    sma_rows,sma_sourced=count_sma_rows()
    sma_branch_rows,sma_branch_sourced=count_sma_branch_rows()
    sk_audits=skeleton.get("audits") or {}
    sk_counts=skeleton.get("counts") or {}
    current=boundary.get("current") or {}

    obs_grid=obs.get("grid") or {}
    fc_grid=fc.get("grid") or {}
    rain_gates=rain.get("gates") or {}

    source_updates=sources.get("readiness_updates") or {}
    legacy_native=((legacy.get("gates") or {}).get("native_hec_145_geometry_topology") or {}).get("pass",False)

    gates={
        "bho6_branch_topology":gate(
            bool(sk_audits.get("topology_passed") and sk_audits.get("area_budget_closed") and sk_audits.get("all_reach_lengths_close")),
            {"counts":sk_counts,"audits":sk_audits},
            "repair BHO6 branch skeleton/audits" if not sk_audits.get("topology_passed") else None,
        ),
        "dynamic_boundary_mass_balance":gate(
            (current.get("closure_error_km2") is not None and abs(float(current.get("closure_error_km2"))) < 1e-6),
            {
                "scenario":current.get("name"),
                "active_boundary_codes":current.get("active_boundary_codes") or [],
                "effective_rainfall_runoff_area_km2":current.get("effective_rainfall_runoff_area_km2"),
                "closure_error_km2":current.get("closure_error_km2"),
            },
            "boundary area budget does not close",
        ),
        "rain_support":gate(
            str(support.get("status","")).startswith("RAIN_SUPPORT_READY"),
            {
                "status":support.get("status"),
                "support_point_count":support.get("support_point_count") or support.get("point_count") or len(support.get("support_points") or []),
                "total_support_area_km2":support.get("total_support_area_km2") or support.get("effective_rainfall_runoff_area_km2") or ((support.get("boundary_scenario") or {}).get("effective_rainfall_runoff_area_km2")),
            },
            "build BHO6 rain support mesh",
        ),
        "observed_full_grid":gate(
            str(obs.get("status","")).startswith("OBSERVED_RAIN_READY")
            and int(obs_grid.get("cells") or 0)==600,
            {
                "status":obs.get("status"),
                "grid_cells":obs_grid.get("cells"),
                "valid_rain_station_count":((obs.get("network") or {}).get("valid_rain_station_count")),
            },
            "publish observed 600-cell field with all-valid-station IDW2",
        ),
        "ifs_full_grid":gate(
            str(fc.get("status","")).startswith("IFS_FULLGRID_FORCING_READY")
            and int(fc_grid.get("cells") or 0)==600
            and bool((fc.get("gates") or {}).get("full_600_cell_grid")),
            {
                "status":fc.get("status"),
                "grid_cells":fc_grid.get("cells"),
                "exact_cycle_id_available":(fc.get("gates") or {}).get("exact_cycle_id_available"),
            },
            "complete 600-cell ECMWF field and attach exact cycle provenance for operational promotion",
        ),
        "merged_rain":gate(
            str(rain.get("status","")).startswith("MERGED_RAIN_FORCING_READY")
            and bool(rain_gates.get("observed_forecast_grid_contract_identical")),
            {
                "status":rain.get("status"),
                "grid_cells":((rain.get("grid_contract") or {}).get("cells")),
                "operational_promotion_allowed":rain_gates.get("operational_promotion_allowed"),
            },
            "merge observed and forecast full-grid fields",
        ),
        "historical_benchmark":gate(
            all(x.get("present") for x in bench["events"]),
            {
                "event_count":sum(x.get("present",False) for x in bench["events"]),
                "required_event_count":len(REQUIRED_BENCHMARK_EVENTS),
            },
            "recover missing benchmark events",
        ),
        "hec_branch_compute":gate(
            bool(e1.get("compute_ok")),
            {
                "candidate_id":e1.get("candidate_id"),
                "compute_ok":e1.get("compute_ok"),
                "returncode":e1.get("returncode"),
                "scores":e1.get("scores"),
            },
            "fix HEC-HMS branch-project compute before calibration",
        ),
        "hec_multievent_calibration":gate(
            str(e1_calibration.get("status","")).startswith("MULTIEVENT_CALIBRATION_SEARCH_COMPLETE")
            and bool((e1_calibration.get("best_calibration_candidate") or {}).get("eligible_for_calibration_ranking")),
            {
                "status":e1_calibration.get("status"),
                "fixed_split":e1_calibration.get("fixed_split") or {},
                "best_calibration_candidate":e1_calibration.get("best_calibration_candidate"),
                "candidate_count":len(e1_calibration.get("ranked_candidates") or []),
            },
            "run fixed E22_SEP2023 + E24_NOV2023 multi-event calibration and retain only candidates supported by both events",
        ),
        "native_hec145":gate(
            bool(legacy_native),
            {
                "target_subbasins":145,
                "target_reaches":72,
                "native_project_recovered":bool(legacy_native),
                "legacy_meteorologic_assignment_missing_bacias":((met_audit.get("integrity") or {}).get("missing_bacia_ids")),
            },
            "recover or independently reconstruct/verify native 145-subbasin + 72-reach topology",
        ),
        "sma_branch_parameters":gate(
            sma_branch_rows==11 and sma_branch_sourced==11,
            {"rows":sma_branch_rows,"fully_sourced_parameter_rows":sma_branch_sourced,"target":"current BHO6 branch model"},
            "select PET and source-backed soil/storage/percolation priors for the 11 current components; do not infer from CN",
        ),
        "sma_145_transfer":gate(
            sma_rows==145 and sma_sourced==145,
            {"rows":sma_rows,"fully_sourced_parameter_rows":sma_sourced,"target":"legacy 145-unit transfer"},
            "transfer only after native/reconstructed 145 geometry-topology is independently verified",
        ),
        "mgb_inputs":gate(
            not (mgb_ready.get("blockers") or []),
            {
                "manifest_status":mgb.get("status"),
                "readiness_status":mgb_ready.get("status"),
                "blockers":mgb_ready.get("blockers") or [],
                "soil_source_candidate_found":source_updates.get("soil_source_candidate_found"),
                "land_cover_source_candidate_found":source_updates.get("land_cover_source_candidate_found"),
            },
            "close MGB meteorological forcing, select/condition DEM, then generate mini-basins/HRUs",
        ),
        "hec_ras_inputs":gate(
            bool(ras_pilot) and all(
                all(bool(v) for k,v in (p.get("gates") or {}).items()
                    if k in {
                        "horizontal_crs_identified","terrain_source_materialized",
                        "current_raw_lidar_materialized_for_ras","vertical_datum_reconciled",
                        "channel_bathymetry_audited","bridges_structures_audited",
                        "upstream_hydrograph_validated","downstream_boundary_validated"
                    })
                for p in (ras_pilot.get("pilots") or [])
            ),
            {
                "manifest_status":ras.get("status"),
                "pilot_status":ras_pilot.get("status"),
                "bathymetry_candidate_found":source_updates.get("hydraulic_bathymetry_candidate_found"),
                "pilots":[{"name":p.get("name"),"gates":p.get("gates")} for p in ras_pilot.get("pilots") or []],
            },
            "reconcile terrain/bathymetry vertical datums, structures and boundaries for Santa Tereza/Mucum pilots",
        ),
        "assimilation_generalized":gate(
            int((assim_ready.get("summary") or {}).get("internal_state_update_count") or 0)>0,
            {
                "contract_status":(assim.get("assimilation") or {}).get("status"),
                "readiness_status":assim_ready.get("status"),
                "summary":assim_ready.get("summary") or {},
                "stage1_contract":assim_ready.get("stage1_contract") or {},
                "internal_state_contract":assim_ready.get("internal_state_contract") or {},
            },
            "boundary replacement is allowed where fresh Q exists; internal state update is still unimplemented and must be replay-validated",
        ),
        "ensemble_validated":gate(
            bool((ensemble_ready.get("weighting_gate") or {}).get("stage_ensemble_ready"))
            or bool((ensemble_ready.get("weighting_gate") or {}).get("discharge_ensemble_ready")),
            {
                "contract_status":(assim.get("ensemble") or {}).get("status"),
                "members":ensemble_ready.get("members") or [],
                "compatibility":ensemble_ready.get("compatibility") or {},
                "weighting_gate":ensemble_ready.get("weighting_gate") or {},
            },
            "need at least two independently benchmarked members for the same variable/location/horizon before skill weighting",
        ),
    }

    foundation_keys=[
        "bho6_branch_topology","dynamic_boundary_mass_balance","rain_support",
        "observed_full_grid","ifs_full_grid","merged_rain","historical_benchmark",
    ]
    foundation=all(gates[k]["pass"] for k in foundation_keys)
    calibratable=foundation and gates["hec_branch_compute"]["pass"]
    operational=False

    blockers=[k for k,v in gates.items() if not v["pass"]]
    payload={
        "schema_version":"g040_stage2_master_readiness_v1",
        "generated_at_utc":now(),
        "research_only":True,
        "status":{
            "foundation_ready":foundation,
            "branch_model_calibratable":calibratable,
            "operational_ready":operational,
            "overall":"BRANCH_MODEL_CALIBRATABLE_RESEARCH_ONLY" if calibratable else ("FOUNDATION_READY_COMPUTE_BLOCKED" if foundation else "FOUNDATION_INCOMPLETE"),
        },
        "gates":gates,
        "blockers":blockers,
        "workstreams":{
            "A_rain_and_state":["observed_full_grid","ifs_full_grid","merged_rain","sma_branch_parameters","sma_145_transfer"],
            "B_hec_network":["bho6_branch_topology","hec_branch_compute","hec_multievent_calibration","native_hec145"],
            "C_tributaries":["dynamic_boundary_mass_balance","assimilation_generalized"],
            "D_mgb":["mgb_inputs"],
            "E_hec_ras":["hec_ras_inputs"],
            "F_ensemble":["historical_benchmark","ensemble_validated"],
        },
        "next_actions_in_order":[
            "close current full-grid observed+IFS run and publish merged 600-cell artifacts",
            "complete and refine fixed E22_SEP2023 + E24_NOV2023 multi-event calibration search",
            "freeze the selected calibration candidate and run E27_MAY2024 + E28_JUN2024 independent validation without retuning",
            "run E2026_JUL pseudo-operational holdout only after validation parameters are frozen",
            "recover/verify native 145-subbasin + 72-reach topology in parallel with BHO6 branch model",
            "select and materialize PET + soil/land-cover inputs for continuous SMA",
            "prepare MGB mini-basins/HRUs and meteorological forcing without reusing HEC discretization blindly",
            "audit DNIT bathymetry/vertical datum and terrain for Santa Tereza and Muçum HEC-RAS pilots",
            "generalize state assimilation to available mainstem/tributary controls",
            "hindcast HEC-SMA + MGB + RNA and estimate skill-based ensemble weights",
            "only then enable impact products and any operational promotion discussion",
        ],
        "promotion_allowed":False,
    }
    OUT_MASTER.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return payload

def main():
    STACK.mkdir(parents=True,exist_ok=True)
    payload=build_master()
    print(json.dumps({
        "overall":payload["status"]["overall"],
        "foundation_ready":payload["status"]["foundation_ready"],
        "branch_model_calibratable":payload["status"]["branch_model_calibratable"],
        "blocker_count":len(payload["blockers"]),
        "blockers":payload["blockers"],
        "outputs":[str(OUT_MASTER.relative_to(ROOT)),str(OUT_TRIB.relative_to(ROOT)),str(OUT_BENCH.relative_to(ROOT))],
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
