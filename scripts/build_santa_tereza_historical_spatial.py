#!/usr/bin/env python3
"""Build event-specific historical flood spatializations for Santa Tereza.

Research-only reconstruction. Uses the current LiDAR/D8 HAND product and the
field calibration gauge 1.60 m = HAND 0. It does not claim an observed flood
boundary, route safety, evacuation need, or official alert.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, shape
from shapely.validation import make_valid

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "assets" / "data"
OUT = DATA / "estudo_caso_territorio" / "santa_tereza_event_spatial.json"
CONTOURS = DATA / "santa_tereza_inundacao" / "contornos_mancha.json"
DIAGNOSTIC = DATA / "santa_tereza_inundacao" / "hand_lidar_5m_diagnostic.json"
FIELD = DATA / "santa_tereza_inundacao" / "painel_evacuacao_hand_campo_diagnostic.json"
GRID = DATA / "estudo_caso_territorio" / "grade_200m_santa_tereza.geojson"
ROADS = DATA / "estudo_caso_territorio" / "ruas_santa_tereza.json"

HAND_ZERO_GAUGE_M = 1.60

EVENTS = [
    {
        "case_id": "st-e4-set2023",
        "event_label": "Set/2023",
        "gauge_peak_m": 24.04,
        "gauge_basis": "SGB leveled flood mark; report SGIH ID 261924",
        "gauge_source_url": "https://rigeo.sgb.gov.br/server/api/core/bitstreams/fc1b8a76-deae-4913-96de-3b25cd3f9845/content",
        "secondary_replay_peak_m": 23.65,
        "secondary_replay_source": "assets/data/santa_tereza_eventwise_replay_rna_2h/events_metrics.csv",
        "evidence_status": "official_leveled_mark",
    },
    {
        "case_id": "st-e6-nov2023",
        "event_label": "Nov/2023",
        "gauge_peak_m": 21.61,
        "gauge_basis": "local 15-min telemetry audit; corroborated by post-event reporting",
        "gauge_source": "assets/data/hec_hms_audit/raw/ana/events/telemetry_86472600_E24.xml",
        "evidence_status": "audited_local_telemetry",
    },
    {
        "case_id": "st-e9-mai2024",
        "event_label": "Mai/2024",
        "gauge_peak_m": 22.42,
        "gauge_basis": "SGB leveled flood mark",
        "gauge_source_url": "https://rigeo.sgb.gov.br/bitstream/doc/24939.6/4/2024-09-24_nota_tecnica_levantamento_cheia_2024_v4.pdf",
        "secondary_raw_peak_m": 22.33,
        "secondary_raw_source": "assets/data/hec_hms_audit/raw/ana/events/telemetry_86472600_E27.xml",
        "evidence_status": "official_leveled_mark",
    },
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def nearest_tenth(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def clean_geom(geom):
    if geom.is_valid:
        return geom
    return make_valid(geom)


def haversine_m(a: list[float], b: list[float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    s = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(s))


def scenario(grid: dict[str, Any], roads: dict[str, Any], feature: dict[str, Any]) -> dict[str, Any]:
    flood = clean_geom(shape(feature["geometry"]))
    cells = []
    upper = 0
    weighted = 0.0
    for cell_feature in grid.get("features", []):
        props = cell_feature.get("properties", {})
        cell_id = str(props.get("id_grade", ""))
        if not cell_id.upper().startswith("200M"):
            continue
        cell = clean_geom(shape(cell_feature["geometry"]))
        inter = cell.intersection(flood)
        if inter.is_empty or inter.area <= 0:
            continue
        overlap = inter.area / cell.area * 100 if cell.area else 0.0
        pop = int(float(props.get("pop") or 0))
        dom = int(float(props.get("dom") or 0))
        upper += pop
        weighted += pop * overlap / 100.0
        cells.append({
            "id_grade": cell_id,
            "pop": pop,
            "dom": dom,
            "overlap_pct_proxy": round(overlap, 3),
        })

    nodes = roads.get("nos", [])
    edges = roads.get("edges", [])
    wet_ids = []
    wet_length_m = 0.0
    total_length_m = 0.0
    for idx, edge in enumerate(edges):
        if len(edge) < 2:
            continue
        a_idx, b_idx = int(edge[0]), int(edge[1])
        if a_idx >= len(nodes) or b_idx >= len(nodes):
            continue
        a, b = nodes[a_idx], nodes[b_idx]  # [lat, lon]
        length_m = haversine_m(a, b)
        total_length_m += length_m
        line = LineString([(a[1], a[0]), (b[1], b[0])])
        inter = line.intersection(flood)
        if inter.is_empty or inter.length <= 0:
            continue
        wet_ids.append(idx)
        ratio = min(1.0, inter.length / line.length) if line.length else 0.0
        wet_length_m += length_m * ratio

    return {
        "contour_area_ha": feature.get("properties", {}).get("area_ha"),
        "cells_200m_touched": len(cells),
        "population_upper_bound_whole_touched_cells": upper,
        "population_area_weighted_proxy": round(weighted, 1),
        "intersected_cells_200m": sorted(cells, key=lambda x: x["id_grade"]),
        "road_centerline_edges_total": len(edges),
        "road_centerline_edges_touched": len(wet_ids),
        "road_centerline_touched_length_m_estimate": round(wet_length_m, 1),
        "road_centerline_total_length_m_estimate": round(total_length_m, 1),
        "wet_edge_ids": wet_ids,
        "road_semantics": "OSM centerline intersection with reconstructed flood contour; not a route-closure or traversability assessment",
    }


def main() -> None:
    contours = read_json(CONTOURS)
    diagnostic = read_json(DIAGNOSTIC)
    field = read_json(FIELD)
    grid = read_json(GRID)
    roads = read_json(ROADS)

    by_level = {}
    for feat in contours.get("features", []):
        value = feat.get("properties", {}).get("nivel_m")
        if value is not None:
            by_level[round(float(value), 1)] = feat

    event_rows = []
    selected_features = []
    for spec in EVENTS:
        exact_hand = max(0.0, float(spec["gauge_peak_m"]) - HAND_ZERO_GAUGE_M)
        contour_level = nearest_tenth(exact_hand)
        feat = by_level.get(round(contour_level, 1))
        if feat is None:
            raise RuntimeError(f"missing HAND contour {contour_level:.1f} m")
        metrics = scenario(grid, roads, feat)
        row = dict(spec)
        row.update({
            "hand_exact_m": round(exact_hand, 3),
            "contour_level_m": contour_level,
            "contour_rounding_m": round(contour_level - exact_hand, 3),
            "scenario": metrics,
        })

        if spec["case_id"] == "st-e9-mai2024" and spec.get("secondary_raw_peak_m") is not None:
            sens_exact = max(0.0, float(spec["secondary_raw_peak_m"]) - HAND_ZERO_GAUGE_M)
            sens_level = nearest_tenth(sens_exact)
            sens_feat = by_level.get(round(sens_level, 1))
            row["sensitivity"] = {
                "basis": "raw telemetry instead of SGB leveled mark",
                "gauge_peak_m": spec["secondary_raw_peak_m"],
                "hand_exact_m": round(sens_exact, 3),
                "contour_level_m": sens_level,
                "scenario": scenario(grid, roads, sens_feat) if sens_feat else None,
            }

        event_rows.append(row)
        out_feat = json.loads(json.dumps(feat))
        out_feat.setdefault("properties", {}).update({
            "case_id": spec["case_id"],
            "event_label": spec["event_label"],
            "gauge_peak_m": spec["gauge_peak_m"],
            "hand_exact_m": round(exact_hand, 3),
            "contour_level_m": contour_level,
            "reconstruction": "historical_research_spatialization",
        })
        selected_features.append(out_feat)

    # Pairwise increments make the spatial difference auditable.
    by_case = {row["case_id"]: row for row in event_rows}
    comparisons = []
    for a_id, b_id in [
        ("st-e4-set2023", "st-e6-nov2023"),
        ("st-e4-set2023", "st-e9-mai2024"),
        ("st-e9-mai2024", "st-e6-nov2023"),
    ]:
        a = by_case[a_id]
        b = by_case[b_id]
        comparisons.append({
            "a": a_id,
            "b": b_id,
            "delta_contour_area_ha_a_minus_b": round(
                float(a["scenario"]["contour_area_ha"] or 0) - float(b["scenario"]["contour_area_ha"] or 0), 1
            ),
            "delta_cells_a_minus_b": a["scenario"]["cells_200m_touched"] - b["scenario"]["cells_200m_touched"],
            "delta_population_upper_a_minus_b": (
                a["scenario"]["population_upper_bound_whole_touched_cells"]
                - b["scenario"]["population_upper_bound_whole_touched_cells"]
            ),
            "delta_population_proxy_a_minus_b": round(
                a["scenario"]["population_area_weighted_proxy"]
                - b["scenario"]["population_area_weighted_proxy"], 1
            ),
            "delta_road_edges_touched_a_minus_b": (
                a["scenario"]["road_centerline_edges_touched"]
                - b["scenario"]["road_centerline_edges_touched"]
            ),
        })

    artifact = {
        "schema_version": 1,
        "artifact_id": "santa-tereza-historical-event-spatial",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "research_historical_spatialization_not_observed_boundary",
        "official_alert": False,
        "calibration": {
            "gauge_zero_hand_m": HAND_ZERO_GAUGE_M,
            "formula": "HAND = max(0, gauge_m - 1.60)",
            "scope": field.get("field_calibration", {}).get("scope", "rio principal"),
            "terrain": "raw LiDAR; FILL only for routing; D8 connectivity and maximum raw-LiDAR barrier along path",
            "diagnostic_status": diagnostic.get("status"),
            "d8_scheme": diagnostic.get("d8_scheme"),
            "d8_scheme_score": diagnostic.get("d8_scheme_scores", {}).get(diagnostic.get("d8_scheme"), {}).get("score"),
            "drained_fraction": diagnostic.get("drained_fraction"),
            "contour_step_m": 0.1,
            "contour_range_m": [0.0, diagnostic.get("contour_max_m", 25.0)],
            "uncertainty": "gauge-to-HAND field calibration and 0.1 m contour discretization; this is not a 2-D hydrodynamic reconstruction nor an observed event polygon",
        },
        "events": event_rows,
        "comparisons": comparisons,
        "event_contours": {"type": "FeatureCollection", "features": selected_features},
        "sources": [
            {"path": str(CONTOURS.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(CONTOURS)},
            {"path": str(DIAGNOSTIC.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(DIAGNOSTIC)},
            {"path": str(FIELD.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(FIELD)},
            {"path": str(GRID.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(GRID)},
            {"path": str(ROADS.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(ROADS)},
        ],
        "limits": [
            "population in whole touched cells is an upper-bound screening count",
            "area-weighted population is a geometric proxy, not an individual count",
            "road intersections are centerline geometry intersections, not closures or safe-route decisions",
            "event extents are reconstructed from peak stage and current LiDAR/HAND calibration, not surveyed event boundaries",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    for row in event_rows:
        s = row["scenario"]
        print(
            row["event_label"],
            f"gauge={row['gauge_peak_m']:.2f}m",
            f"HAND={row['hand_exact_m']:.2f}m",
            f"contour={row['contour_level_m']:.1f}m",
            f"area={s['contour_area_ha']}ha",
            f"cells={s['cells_200m_touched']}",
            f"pop_proxy={s['population_area_weighted_proxy']}",
            f"road_edges={s['road_centerline_edges_touched']}",
        )


if __name__ == "__main__":
    main()
