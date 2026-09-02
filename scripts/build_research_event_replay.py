#!/usr/bin/env python3
"""Build the source-backed replay contract for the integrated research room.

This builder deliberately stops short of operational conclusions. It joins only
the relationships that are reproducible from the repository: event/model
series, flood-contour geometry/200 m cells, and response-plan inventories.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from shapely.geometry import shape


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "data" / "research_event_replay_latest.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_ref(path: Path, role: str, status: str = "available") -> dict[str, Any]:
    return {"path": rel(path), "role": role, "status": status, "sha256": sha256(path)}


def number(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def integer(value: Any) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None else None


def parse_q62(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    return [row for row in rows if str(row.get("usar", "")) == "1"]


def iso_without_offset(value: str) -> datetime:
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    raise ValueError(f"timestamp not understood: {value}")


def series_summary(model: dict[str, Any], event_number: int, peak: str, horizon: int, window_hours: int) -> dict[str, Any]:
    series_key = f"{event_number}|Teste"
    raw_series = model.get("series", {}).get(series_key, [])
    points = [row for row in raw_series if isinstance(row, list) and len(row) >= 3 and number(row[1]) is not None and number(row[2]) is not None]
    observed = [number(row[1]) for row in points]
    predicted = [number(row[2]) for row in points]
    observed = [value for value in observed if value is not None]
    predicted = [value for value in predicted if value is not None]
    observed_peak = max(observed) if observed else None
    predicted_peak = max(predicted) if predicted else None
    peak_index = observed.index(observed_peak) if observed_peak is not None else -1
    peak_row = points[peak_index] if peak_index >= 0 else None
    target_stamp = iso_without_offset(peak).strftime("%Y-%m-%d %H:%M")
    origin = iso_without_offset(peak) - timedelta(hours=horizon)
    target_row = next((row for row in points if str(row[0]) == target_stamp), None)
    mae = sum(abs(number(row[2]) - number(row[1])) for row in points) / len(points) if points else None
    return {
        "series_key": series_key,
        "set": "Teste",
        "points_published": len(points),
        "points_expected_in_recorte": window_hours,
        "missing_hours_in_recorte": max(window_hours - len(points), 0),
        "first_timestamp": points[0][0] if points else None,
        "last_timestamp": points[-1][0] if points else None,
        "observed_peak_cm_in_series": round(observed_peak, 3) if observed_peak is not None else None,
        "predicted_peak_cm_in_series": round(predicted_peak, 3) if predicted_peak is not None else None,
        "prediction_at_observed_peak_cm": round(number(peak_row[2]), 3) if peak_row else None,
        "observed_peak_timestamp": peak_row[0] if peak_row else None,
        "forecast_target_timestamp": target_stamp,
        "inferred_origin_timestamp": origin.strftime("%Y-%m-%d %H:%M"),
        "target_timestamp_present_in_series": target_row is not None,
        "prediction_at_target_cm": round(number(target_row[2]), 3) if target_row else None,
        "mean_absolute_error_cm_in_published_points": round(mae, 3) if mae is not None else None,
        "timestamp_reconciliation_status": "target_aligned_series_only; release_timestamp_pending",
    }


def mucum_replays(q62_path: Path, audit_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    q62 = parse_q62(q62_path)
    audit = read_json(audit_path)
    models = audit.get("models", [])
    event = next(row for row in q62 if str(row.get("evento")) == "35")
    event_number = integer(event["evento"])
    peak = event["pico_data"]
    window_hours = integer(event["horas_recorte"]) or 0
    horizons: list[dict[str, Any]] = []
    for horizon in (8, 12):
        candidates = [
            model for model in models
            if str(model.get("horizon", "")).lower() == f"{horizon}h"
            and f"{event_number}|Teste" in model.get("series", {})
        ]
        candidates.sort(key=lambda model: number(model.get("metrics", {}).get("score_equilibrio")) or -1, reverse=True)
        selected = candidates[0] if candidates else None
        horizons.append({
            "horizon_hours": horizon,
            "selection_basis": "highest published score_equilibrio among candidates with event 35|Teste",
            "candidate_count": len(candidates),
            "selected_model": selected.get("name") if selected else None,
            "selected_model_metadata": {
                "family": selected.get("family"),
                "combo_id": selected.get("combo_id"),
                "rotation": selected.get("rotation"),
                "score_equilibrio": selected.get("metrics", {}).get("score_equilibrio"),
                "mae_teste_cm": selected.get("metrics", {}).get("MAE_teste_cm"),
                "source_workbook": selected.get("workbookUrl"),
            } if selected else None,
            "series": series_summary(selected, event_number, peak, horizon, window_hours) if selected else None,
        })
    replay = {
        "municipality": "Muçum",
        "code_ibge": "4312609",
        "station_code": "86472600",
        "event_id": "mucum-q62-35",
        "event_number": event_number,
        "peak_timestamp_local_without_offset": peak,
        "peak_observed_cm": number(event.get("pico_cm_obs")),
        "catalog_peak_cm": number(event.get("pico_cm_catalogo")),
        "recorte": {
            "start": event.get("inicio_recorte"),
            "end": event.get("fim_recorte"),
            "hours": window_hours,
            "hours_before_peak": integer(event.get("horas_antes")),
            "hours_after_peak": integer(event.get("horas_depois")),
        },
        "event_status": "usable_research_test_record",
        "independent_test_status": "test label available in audited series; exact release timestamp not reconciled",
        "horizons": horizons,
    }
    return [replay], {"q62_used_events": len(q62), "audited_models": len(models)}


def contour_scenario(grid_path: Path, contour_path: Path, level_m: float) -> dict[str, Any]:
    grid = read_json(grid_path)
    contours = read_json(contour_path)
    contour = next(
        feature for feature in contours.get("features", [])
        if abs(number(feature.get("properties", {}).get("nivel_m")) - level_m) < 1e-9
    )
    flood = shape(contour["geometry"])
    cells: list[dict[str, Any]] = []
    invalid_cells = 0
    for feature in grid.get("features", []):
        props = feature.get("properties", {})
        cell_id = str(props.get("id_grade", ""))
        if not cell_id.upper().startswith("200M"):
            continue
        cell = shape(feature["geometry"])
        if not cell.is_valid:
            invalid_cells += 1
        intersection = cell.intersection(flood)
        if intersection.is_empty or intersection.area <= 0:
            continue
        overlap_pct = (intersection.area / cell.area * 100.0) if cell.area else 0.0
        cells.append({
            "id_grade": cell_id,
            "pop": integer(props.get("pop")) or 0,
            "overlap_pct_proxy": round(overlap_pct, 3),
        })
    upper_population = sum(cell["pop"] for cell in cells)
    weighted_population = 0.0
    for cell in cells:
        # Recompute with the same geometry join to preserve the auditable ratio.
        feature = next(f for f in grid["features"] if f.get("properties", {}).get("id_grade") == cell["id_grade"])
        geometry = shape(feature["geometry"])
        weighted_population += (integer(feature.get("properties", {}).get("pop")) or 0) * cell["overlap_pct_proxy"] / 100.0
    return {
        "level_m": level_m,
        "contour_area_ha": contour.get("properties", {}).get("area_ha"),
        "contour_feature_count_at_level": 1,
        "cells_200m_touched": len(cells),
        "population_upper_bound_whole_touched_cells": upper_population,
        "population_area_weighted_proxy": round(weighted_population, 1),
        "intersected_cells_200m": sorted(cells, key=lambda cell: cell["id_grade"]),
        "join_status": "reproduced_geometry_intersection",
        "invalid_200m_cells_seen": invalid_cells,
    }


def spatial_inventory() -> dict[str, Any]:
    muc_grid = ROOT / "assets" / "data" / "vulnerabilidade" / "grade" / "4312609.geojson"
    stz_grid = ROOT / "assets" / "data" / "vulnerabilidade" / "grade" / "4317251.geojson"
    muc_contour = ROOT / "assets" / "data" / "mucum_inundacao" / "contornos_mancha.json"
    stz_contour = ROOT / "assets" / "data" / "santa_tereza_inundacao" / "contornos_mancha.json"
    return {
        "mucum": {
            "grid_source": rel(muc_grid),
            "contour_source": rel(muc_contour),
            "stage_conversion_status": "pending_vertical_datum_and_gauge_to_HAND_reconciliation",
            "published_level_range_m": [0.0, 25.0],
            "scenarios": [contour_scenario(muc_grid, muc_contour, level) for level in (18.0, 20.0, 25.0)],
            "note": "HAND/contorno é cenário de triagem espacial; não é uma cota de régua automaticamente convertida nem define uma rota.",
        },
        "santa_tereza": {
            "grid_source": rel(stz_grid),
            "contour_source": rel(stz_contour),
            "stage_conversion_status": "pending_vertical_datum_and_gauge_to_HAND_reconciliation",
            "published_level_range_m": [0.0, 15.0],
            "higher_than_published_status": "not_published_in_current_contour_file",
            "scenarios": [contour_scenario(stz_grid, stz_contour, 15.0)],
            "note": "O arquivo atual chega a 15 m; não há cenário espacial publicado acima disso nesta fonte.",
        },
    }


def response_inventory() -> dict[str, Any]:
    muc_path = ROOT / "assets" / "data" / "mucum_contingencia_202607.json"
    stz_path = ROOT / "assets" / "data" / "estudo_caso_resposta_v002.json"
    muc = read_json(muc_path)
    stz = read_json(stz_path)
    capacity = muc.get("resumo_capacidade", {})
    return {
        "mucum": {
            "source": rel(muc_path),
            "shelters_count": len(muc.get("abrigos", [])),
            "routes_in_plan_count": len(muc.get("rotas_plano", [])),
            "bridges_in_plan_count": len(muc.get("pontes", [])),
            "planned_capacity_values_people": [
                capacity.get("capacidade_quadro_2_pessoas"),
                capacity.get("capacidade_quadro_13_pessoas"),
                capacity.get("capacidade_anexo_5_pessoas"),
            ],
            "capacity_reconciliation_status": capacity.get("status_reconciliacao"),
            "current_occupancy_status": "unknown",
            "route_traversability_status": "unknown",
            "bridge_engineering_status": "inspection_required; operational_state_unknown",
            "operational_gate": "blocked",
        },
        "santa_tereza": {
            "source": rel(stz_path),
            "shelters_count": 1 if stz.get("shelter") else 0,
            "routes_in_plan_count": 0,
            "bridges_in_plan_count": 0,
            "planned_capacity_values_people": [stz.get("shelter", {}).get("capacity")],
            "capacity_reconciliation_status": "unknown",
            "current_occupancy_status": "unknown",
            "route_traversability_status": stz.get("spatial", {}).get("route_status"),
            "bridge_engineering_status": "not_integrated",
            "operational_gate": stz.get("operational_gate", {}).get("status", "blocked"),
        },
    }


def build() -> dict[str, Any]:
    q62_path = ROOT / "assets" / "data" / "mucum_q62" / "mucum_q62_recorte_eventos.csv"
    audit_path = ROOT / "assets" / "data" / "mucum_auditaveis_series.json"
    muc_events_path = ROOT / "assets" / "data" / "mucum_eventos_analise.json"
    stz_events_path = ROOT / "assets" / "data" / "eventos_analise.json"
    stz_protocol_path = ROOT / "assets" / "data" / "santa_tereza_inundacao" / "protocolo_leave_one_event_out_estrangulamento.json"
    basin_path = ROOT / "assets" / "data" / "research_basin_screening_latest.json"
    muc_replays, audit_counts = mucum_replays(q62_path, audit_path)
    muc_events = read_json(muc_events_path)
    stz_events = read_json(stz_events_path)
    stz_protocol = read_json(stz_protocol_path)
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "artifact_id": "research-event-replay-latest",
        "generated_at_utc": generated,
        "research_only": True,
        "official_alert": False,
        "operational_gate": {
            "status": "blocked",
            "reason": "Replay, spatial triage and response inventory are source-backed research artifacts; gauge/HAND conversion, field route checks and current shelter capacity are not closed.",
            "disallowed": ["official_alert", "evacuation_order", "route_navigation", "public_dispatch", "resource_allocation"],
        },
        "purpose": "Reproduzir retrospectivamente o que os dados disponíveis teriam mostrado antes de um evento e registrar quais ligações ainda precisam ser validadas.",
        "method": {
            "interpolation": False,
            "nearest_neighbor": False,
            "spatial_join": "interseção geométrica com área positiva; filtro explícito id_grade=200M",
            "population_semantics": "soma de células inteiras é limite superior de triagem; proxy ponderado por área não é contagem individual nem população evacuável",
            "gauge_hand_conversion": "pending_vertical_datum_and_gauge_to_HAND_reconciliation",
            "route_rule": "nenhuma rota é derivada do cruzamento espacial deste artefato",
            "model_rule": "séries publicadas permanecem separadas de uma emissão operacional; timestamp de liberação T− ainda não foi reconciliado",
        },
        "forecast_sources": [
            {"id": "rna", "status": "available_for_historical_replay", "horizons_hours": [8, 12], "municipality_scope": ["Muçum"]},
            {"id": "rna_santa_tereza", "status": "available_as_catalog_and_experimental_short_horizon; 8h/12h replay pending", "horizons_hours": [2], "municipality_scope": ["Santa Tereza"]},
            {
                "id": "hec_hms",
                "status": "not_integrated_yet",
                "horizons_hours": [72],
                "municipality_scope": ["Muçum", "Santa Tereza"],
                "required_inputs": ["precipitação de bacia", "modelo de perdas", "parâmetros calibrados", "vazão/nível observado", "regras de propagação"],
                "published_peak": None,
            },
        ],
        "replay_cases": muc_replays,
        "municipality_catalogs": {
            "mucum": {"event_count_catalog": len(muc_events.get("eventos", [])), "q62_used_event_count": audit_counts["q62_used_events"], "audited_model_count": audit_counts["audited_models"]},
            "santa_tereza": {
                "event_count_catalog": len(stz_events.get("eventos", [])),
                "available_rotation_manifest": rel(ROOT / "assets" / "data" / "stz_2h_rotacao" / "MANIFESTO_ROTACAO_2H_ALT_STZ.csv"),
                "independent_holdout_protocol": stz_protocol,
                "eight_or_twelve_hour_replay_status": "pending_rna_event_id_and_auditable_series_reconciliation",
            },
        },
        "spatial_scenarios": spatial_inventory(),
        "response_inventory": response_inventory(),
        "sources": [
            source_ref(q62_path, "Muçum Q62 event recortes"),
            source_ref(audit_path, "Muçum auditável model series"),
            source_ref(muc_events_path, "Muçum event catalog"),
            source_ref(stz_events_path, "Santa Tereza event catalog"),
            source_ref(basin_path, "basin research feed", "available_snapshot"),
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    artifact = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {rel(args.output) if args.output.is_relative_to(ROOT) else args.output}")
    print(f"replay_cases={len(artifact['replay_cases'])}")
    print("spatial_scenarios=Muçum:18,20,25m; Santa Tereza:15m")


if __name__ == "__main__":
    main()
