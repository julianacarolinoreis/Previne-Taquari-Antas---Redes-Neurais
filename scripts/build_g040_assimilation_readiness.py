#!/usr/bin/env python3
"""Build Stage-1 assimilation readiness from live G040 controls.

Observed boundary replacement and internal-state assimilation are deliberately
separated. Fresh observed Q may define a model boundary where the architecture
explicitly supports that station. Stage/flow at checkpoints is diagnostic until
an internal state-update method is implemented and validated.

Research only.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
STACK=ROOT/"assets/data/g040_hydro_stack"
LIVE=BASE/"whole_basin_live_hydro_controls_latest.json"
SCEN=BASE/"whole_basin_boundary_scenarios_latest.json"
OUT=STACK/"assimilation_readiness_latest.json"

def load(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

def main():
    live=load(LIVE); scen=load(SCEN)
    current=scen.get("current") or {}
    active={str(x) for x in current.get("active_boundary_codes") or []}
    controls=[]
    for c in live.get("controls") or []:
        code=str(c.get("code") or "")
        fresh_q=bool(c.get("fresh_flow_boundary")) and c.get("latest_flow_m3s") is not None
        fresh_state=bool(c.get("fresh_for_state"))
        is_active=code in active or (code=="86472000" and fresh_q)
        controls.append({
            "code":code,
            "label":c.get("label"),
            "group":c.get("group"),
            "role":c.get("role"),
            "last_observation_utc":c.get("last_observation_utc"),
            "age_minutes":c.get("age_minutes"),
            "latest_flow_m3s":c.get("latest_flow_m3s"),
            "latest_level_source_unit":c.get("latest_level_source_unit"),
            "fresh_for_state":fresh_state,
            "fresh_flow_boundary":fresh_q,
            "architecture_boundary_active":is_active,
            "stage1_boundary_update_allowed":bool(is_active and fresh_q),
            "internal_state_update_allowed":False,
            "checkpoint_residual_diagnostic_allowed":bool(fresh_state),
            "reason":(
                "fresh observed discharge can replace this explicit source/boundary"
                if is_active and fresh_q
                else "observation may diagnose residual/state mismatch, but no validated internal-state update is implemented"
            ),
        })
    boundary_ready=[x for x in controls if x["stage1_boundary_update_allowed"]]
    diagnostic=[x for x in controls if x["checkpoint_residual_diagnostic_allowed"]]
    payload={
        "schema_version":"g040_assimilation_readiness_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"BOUNDARY_ASSIMILATION_READY_INTERNAL_STATE_UPDATE_BLOCKED" if boundary_ready else "ASSIMILATION_INPUTS_PARTIAL",
        "current_boundary_scenario":scen.get("current_scenario"),
        "controls":controls,
        "summary":{
            "control_count":len(controls),
            "stage1_boundary_update_count":len(boundary_ready),
            "diagnostic_checkpoint_count":len(diagnostic),
            "internal_state_update_count":0,
        },
        "stage1_contract":{
            "method":"replace explicit source/boundary time-series values only with quality-controlled fresh observed discharge",
            "timestamp_alignment_required":True,
            "unit_alignment_required":True,
            "rating_curve_provenance_required_if_flow_is_derived":True,
            "missing_rule":"do not synthesize observed Q; tributary contributing area returns to rainfall-runoff where applicable",
        },
        "internal_state_contract":{
            "status":"NOT_IMPLEMENTED",
            "candidate_states":["routing storage","channel discharge/level","baseflow state","SMA soil/groundwater states"],
            "next_methods":["documented deterministic nudging/state correction","ensemble/sequential assimilation after replay validation"],
            "forbidden":"visual curve shift presented as physical state assimilation",
        },
        "promotion_allowed":False,
    }
    STACK.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":payload["status"],"summary":payload["summary"]},ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
