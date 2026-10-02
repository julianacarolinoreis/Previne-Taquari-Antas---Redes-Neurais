#!/usr/bin/env python3
"""Build auditable scaffolds for the G040 hydrologic-hydrodynamic stack.

The 32 IEDE polygons are used only as management/audit units. They are NOT
silently promoted to HEC-HMS computational sub-basins.

The HEC-HMS target inventory is the 145 sub-basins + 72 reaches documented in
the July 2026 report inventory. The native HEC geometry/topology must still be
recovered or independently reconstructed and verified before an executable
145-unit network is generated.

This script does not run HEC-HMS, MGB or HEC-RAS and invents no parameters.
Research only; not an official warning system.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANAGEMENT = ROOT / "assets/data/hec_hms_g040_full_basin/full_basin_architecture_latest.json"
DEFAULT_REPORT145 = ROOT / "assets/data/hec_hms_g040_full_basin/original_145_report_inventory_latest.json"
DEFAULT_CONFIG = ROOT / "config/g040_hydro_stack_v1.json"
DEFAULT_OUT = ROOT / "assets/data/g040_hydro_stack"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_management_layer(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    units = payload.get("subbasins") or []
    if len(units) != 32:
        raise RuntimeError(f"expected 32 G040 management polygons; found {len(units)}")
    ugs = sorted({str(u.get("ug")) for u in units})
    if len(ugs) != 7:
        raise RuntimeError(f"expected 7 G040 management units; found {len(ugs)}: {ugs}")
    unsafe = [u.get("id") for u in units if u.get("not_hec_computational_unit") is not True]
    if unsafe:
        raise RuntimeError(
            "management-layer safety flag missing: 32 polygons must remain non-computational HEC units"
        )
    return units, payload.get("topology_audit") or {}


def validate_report145(payload: dict[str, Any]) -> list[dict[str, Any]]:
    scope = payload.get("scope") or {}
    units = payload.get("subbasins") or []
    if int(scope.get("hec_subbasins") or 0) != 145 or len(units) != 145:
        raise RuntimeError(
            f"expected 145 report-listed HEC sub-basins; scope={scope.get('hec_subbasins')}, rows={len(units)}"
        )
    if int(scope.get("hec_reaches") or 0) != 72:
        raise RuntimeError(f"expected 72 report-listed HEC reaches; found {scope.get('hec_reaches')}")
    return units


def write_sma_template(out: Path, report_units: list[dict[str, Any]]) -> None:
    fields = [
        "hec_report_subbasin_id", "area_km2",
        "legacy_cn_initial", "legacy_main_channel_length_m", "legacy_main_channel_slope_m_m",
        "legacy_tc_kirpich_min", "legacy_lag_scs_min",
        "legacy_event2_cn_calibrated", "legacy_event2_initial_abstraction_mm",
        "legacy_event2_tc_kirpich_min", "legacy_event2_lag_min",
        "native_geometry_verified", "native_topology_verified",
        "canopy_storage_mm", "surface_storage_mm", "soil_storage_mm",
        "tension_storage_mm", "soil_percolation_mm_h",
        "gw1_storage_mm", "gw1_percolation_mm_h", "gw1_coefficient_h",
        "gw2_storage_mm", "gw2_percolation_mm_h", "gw2_coefficient_h",
        "initial_canopy_pct", "initial_surface_pct", "initial_soil_pct",
        "initial_gw1_pct", "initial_gw2_pct",
        "potential_et_source", "parameter_source", "calibration_status", "notes",
    ]
    sma_fields = [
        "canopy_storage_mm", "surface_storage_mm", "soil_storage_mm",
        "tension_storage_mm", "soil_percolation_mm_h",
        "gw1_storage_mm", "gw1_percolation_mm_h", "gw1_coefficient_h",
        "gw2_storage_mm", "gw2_percolation_mm_h", "gw2_coefficient_h",
        "initial_canopy_pct", "initial_surface_pct", "initial_soil_pct",
        "initial_gw1_pct", "initial_gw2_pct",
    ]
    with (out / "sma_parameter_template.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for unit in report_units:
            e2 = unit.get("event2_calibration") or {}
            row = {k: "" for k in fields}
            row.update({
                "hec_report_subbasin_id": unit.get("id"),
                "area_km2": unit.get("area_km2"),
                "legacy_cn_initial": unit.get("cn_initial"),
                "legacy_main_channel_length_m": unit.get("main_channel_length_m"),
                "legacy_main_channel_slope_m_m": unit.get("main_channel_slope_m_m"),
                "legacy_tc_kirpich_min": unit.get("tc_kirpich_min"),
                "legacy_lag_scs_min": unit.get("lag_scs_min"),
                "legacy_event2_cn_calibrated": e2.get("cn_calibrated"),
                "legacy_event2_initial_abstraction_mm": e2.get("initial_abstraction_mm"),
                "legacy_event2_tc_kirpich_min": e2.get("tc_kirpich_min"),
                "legacy_event2_lag_min": e2.get("lag_min"),
                "native_geometry_verified": "NO",
                "native_topology_verified": "NO",
                "calibration_status": "BLOCKED_NATIVE_GEOMETRY_TOPOLOGY_AND_SOURCED_SMA_PARAMS",
                "notes": "Legacy SCS-CN/UH values are reference only; SMA fields intentionally blank.",
            })
            for field in sma_fields:
                row[field] = ""
            w.writerow(row)


def write_mgb_manifest(
    out: Path,
    management_units: list[dict[str, Any]],
    report_units: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> None:
    payload = {
        "schema_version": "g040_mgb_prep_manifest_v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "research_only": True,
        "status": "INPUT_PREPARATION_PENDING",
        "role": cfg["mgb"]["role"],
        "discretization_policy": cfg["mgb"]["discretization_policy"],
        "reference_layers": {
            "management_polygons": len(management_units),
            "report_hec_subbasins": len(report_units),
            "note": "Neither reference layer is automatically the final MGB discretization.",
        },
        "required_inputs": [
            {"name": name, "status": "PENDING_SOURCE_OR_PREPROCESSING"}
            for name in cfg["mgb"]["required_inputs"]
        ],
        "gates": [
            "DEM hydrologically conditioned and projection/resolution documented",
            "mini-basins and drainage topology audited",
            "HRU/soil/land-cover provenance documented",
            "meteorological forcing units/time zones audited",
            "observed discharge calibration and independent validation periods separated",
        ],
    }
    (out / "mgb_prep_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_ras_manifest(out: Path, cfg: dict[str, Any]) -> None:
    domains = []
    for d in cfg["hec_ras"]["pilot_domains"]:
        domains.append({
            **d,
            "upstream_hydrograph_source": None,
            "downstream_boundary_source": None,
            "terrain_source": None,
            "cross_sections_or_mesh": None,
            "structures": [],
            "manning_source": None,
            "baseline_equation": "Diffusion Wave",
            "comparison_equations": ["SWE-ELM", "SWE-EM"],
            "selected_equation": None,
            "selection_evidence": None,
        })
    payload = {
        "schema_version": "g040_hec_ras_coupling_manifest_v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "research_only": True,
        "status": "HYDRAULIC_INPUTS_PENDING",
        "strategy": cfg["hec_ras"]["strategy"],
        "equation_test": cfg["hec_ras"]["equation_test"],
        "swe_priority_conditions": cfg["hec_ras"]["swe_priority_conditions"],
        "downstream_note": cfg["hec_ras"]["downstream_note"],
        "domains": domains,
        "validation_requirements": [
            "observed water levels and/or flood marks",
            "arrival timing when available",
            "inundation extent reference",
            "terrain and channel representation audit",
            "Manning sensitivity",
            "mesh/cross-section sensitivity",
            "boundary-condition sensitivity",
        ],
    }
    (out / "hec_ras_coupling_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_assimilation_ensemble(out: Path, cfg: dict[str, Any]) -> None:
    payload = {
        "schema_version": "g040_assimilation_ensemble_contract_v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "research_only": True,
        "assimilation": cfg["assimilation"],
        "ensemble": cfg["ensemble"],
        "state_update_contract": {
            "required": [
                "observation_timestamp", "station_or_sensor_id", "variable", "value",
                "unit", "quality_flag", "model_state_timestamp", "update_method",
            ],
            "rule": "new observations update model state/boundary only through a documented method",
            "forbidden": "visual-only curve shift presented as physical state correction",
        },
        "skill_contract": {
            "metrics": cfg["validation"]["hydrology_metrics"],
            "required_partitions": ["calibration_or_training", "independent_validation"],
            "pseudo_operational_replay_required_before_weighting": True,
            "automatic_simple_mean": False,
        },
    }
    (out / "assimilation_ensemble_contract.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def readiness(
    management_units: list[dict[str, Any]],
    topology: dict[str, Any],
    report_units: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    rain_covered = sum(1 for u in management_units if int(u.get("rain_station_count") or 0) > 0)
    flow_covered = sum(1 for u in management_units if int(u.get("flow_station_count") or 0) > 0)
    gates = {
        "management_layer_32": {
            "pass": len(management_units) == 32,
            "detail": "32/32 IEDE polygons loaded as management/audit units only",
        },
        "management_coarse_connectivity": {
            "pass": True,
            "detail": {
                "topology_pass_diagnostic": bool(topology.get("topology_pass")),
                "edge_count": topology.get("edge_count"),
                "cycle_count": len(topology.get("cycles") or []),
                "note": "diagnostic only; never a gate for HEC computational topology",
            },
        },
        "report_inventory_145": {
            "pass": len(report_units) == 145,
            "detail": "145 report-listed HEC sub-basins + 72 reaches are the target inventory",
        },
        "native_hec_145_geometry_topology": {
            "pass": False,
            "detail": "native .hms/.basin geometry/topology not yet recovered/verified",
        },
        "rain_station_presence_management_layer": {
            "pass": rain_covered > 0,
            "detail": f"{rain_covered}/{len(management_units)} management polygons contain >=1 inventoried rain station",
            "note": "presence is not hourly completeness and is not final HEC spatialization",
        },
        "flow_station_presence_management_layer": {
            "pass": flow_covered > 0,
            "detail": f"{flow_covered}/{len(management_units)} management polygons contain >=1 inventoried flow station",
        },
        "sma_parameters_sourced": {"pass": False, "detail": "145-row SMA template intentionally blank"},
        "potential_et_selected": {
            "pass": bool(cfg["forcing_contract"]["potential_et"].get("source")),
            "detail": str(cfg["forcing_contract"]["potential_et"]),
        },
        "mgb_inputs_ready": {"pass": False, "detail": "preprocessing manifest created; inputs pending"},
        "hec_ras_geometry_ready": {"pass": False, "detail": "domain manifests created; geometry/boundaries pending"},
        "assimilation_generalized": {"pass": False, "detail": cfg["assimilation"]["status"]},
        "ensemble_validated": {"pass": False, "detail": cfg["ensemble"]["status"]},
    }
    return {
        "schema_version": "g040_hydro_stack_readiness_v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "research_only": True,
        "overall_status": "SCAFFOLD_READY_NATIVE_145_AND_MODEL_INPUTS_PENDING",
        "gates": gates,
        "promotion_allowed": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--management", type=Path, default=DEFAULT_MANAGEMENT)
    ap.add_argument("--report145", type=Path, default=DEFAULT_REPORT145)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    management = load_json(args.management)
    report145 = load_json(args.report145)
    cfg = load_json(args.config)
    management_units, topology = validate_management_layer(management)
    report_units = validate_report145(report145)

    args.out.mkdir(parents=True, exist_ok=True)
    write_sma_template(args.out, report_units)
    write_mgb_manifest(args.out, management_units, report_units, cfg)
    write_ras_manifest(args.out, cfg)
    write_assimilation_ensemble(args.out, cfg)

    ready = readiness(management_units, topology, report_units, cfg)
    (args.out / "readiness_latest.json").write_text(
        json.dumps(ready, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps({
        "status": ready["overall_status"],
        "out": str(args.out),
        "management_polygons": len(management_units),
        "management_ugs": len({u["ug"] for u in management_units}),
        "hec_report_subbasins": len(report_units),
        "hec_report_reaches": 72,
        "promotion_allowed": ready["promotion_allowed"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
