#!/usr/bin/env python3
"""Build a source-backed Taquari--Antas network audit for HEC-HMS.

This is deliberately an audit/preparation builder.  It uses the official ANA
BHO6 hosted service to recover the directed drainage network upstream of the
Muçum response station and to test the nesting of the three relevant gauges:
Rio das Antas (86472000) -> Santa Tereza (86472600) -> Muçum (86510000).

It does not invent cross sections, rating curves, rainfall at 86472600 or
reach-routing parameters.  The generated JSON therefore distinguishes:
network topology confirmed, HEC structure designed, and calibration ready.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from pyproj import Transformer
from shapely.geometry import Point, shape, mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas"
BHO6_QUERY = (
    "https://portal1.snirh.gov.br/server/rest/services/Hosted/"
    "main_geoft_bho6_trecho_drenagem/FeatureServer/0/query"
)
OUT_FIELDS = (
    "fid,cotrecho,noorigem,nodestino,cocursodag,cobacia,nuareamont,"
    "nuareacont,nucomptrec,nucompcda,nunivotcda,nustrahler,noriocomp,"
    "noespecif,dedominial,dsversao"
)
STATIONS = {
    "86472000": {
        "name": "Linha José Júlio",
        "role": "Rio das Antas",
        "lon": -51.6997,
        "lat": -29.0978,
    },
    "86472600": {
        "name": "Santa Tereza",
        "role": "controle intermediário no Rio Taquari",
        "lon": -51.7322,
        "lat": -29.1781,
    },
    "86510000": {
        "name": "Muçum",
        "role": "posto de resposta no Rio Taquari",
        "lon": -51.8686,
        "lat": -29.1672,
    },
}
STATION_ORDER = ["86472000", "86472600", "86510000"]
PROJECTED = Transformer.from_crs("EPSG:4326", "EPSG:31982", always_xy=True)


def get_json(session: requests.Session, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(BHO6_QUERY, params=params, timeout=90)
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(json.dumps(payload["error"], ensure_ascii=False))
    return payload


def fetch_attributes(session: requests.Session, where: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        payload = get_json(
            session,
            {
                "where": where,
                "outFields": OUT_FIELDS,
                "returnGeometry": "false",
                "resultOffset": offset,
                "resultRecordCount": 2000,
                "orderByFields": "fid",
                "f": "json",
            },
        )
        page = [feature["attributes"] for feature in payload.get("features", [])]
        rows.extend(page)
        if len(page) < 2000:
            return rows
        offset += len(page)


def fetch_mainstem_geometry(session: requests.Session) -> list[dict[str, Any]]:
    payload = get_json(
        session,
        {
            "where": "cocursodag='786'",
            "outFields": OUT_FIELDS,
            "returnGeometry": "true",
            "outSR": "4326",
            "resultRecordCount": 1000,
            "f": "geojson",
        },
    )
    return payload.get("features", [])


def fetch_geometry_for_ids(
    session: requests.Session, fids: list[int]
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for start in range(0, len(fids), 100):
        batch = fids[start : start + 100]
        where = "fid IN (" + ",".join(str(fid) for fid in batch) + ")"
        payload = get_json(
            session,
            {
                "where": where,
                "outFields": OUT_FIELDS,
                "returnGeometry": "true",
                "outSR": "4326",
                "resultRecordCount": 200,
                "f": "geojson",
            },
        )
        features.extend(payload.get("features", []))
    return features


def projected_distance_m(geometry: Any, point: Point) -> float:
    def project(x: float, y: float) -> tuple[float, float]:
        return PROJECTED.transform(x, y)

    projected_geometry = type(geometry)(
        [project(x, y) for x, y in geometry.coords]
    ) if geometry.geom_type == "LineString" else None
    if projected_geometry is None:
        # The BHO6 mainstem is normally LineString.  This fallback keeps the
        # audit explicit if the service returns a multipart geometry.
        from shapely.ops import transform

        projected_geometry = transform(project, geometry)
    px, py = PROJECTED.transform(point.x, point.y)
    return projected_geometry.distance(Point(px, py))


def nearest_mainstem_segment(
    station: dict[str, Any], geometries: list[dict[str, Any]]
) -> tuple[dict[str, Any], float]:
    point = Point(station["lon"], station["lat"])
    candidates: list[tuple[float, dict[str, Any]]] = []
    for feature in geometries:
        geometry = shape(feature["geometry"])
        candidates.append(
            (projected_distance_m(geometry, point), feature["properties"])
        )
    return min(candidates, key=lambda pair: pair[0])[1], min(candidates)[0]


def downstream_path(
    by_origin: dict[int, list[dict[str, Any]]],
    start: dict[str, Any],
    target_fid: int,
) -> list[dict[str, Any]]:
    path = [start]
    seen = {int(start["fid"]) }
    current = start
    while int(current["fid"]) != target_fid:
        choices = by_origin.get(int(current["nodestino"]), [])
        if not choices:
            raise RuntimeError(
                f"rota downstream interrompida em nó {current['nodestino']}"
            )
        main_choices = [item for item in choices if str(item["cocursodag"]) == "786"]
        choices = main_choices or choices
        choices.sort(key=lambda item: (float(item.get("nuareamont") or 0), int(item["fid"])))
        next_item = choices[-1]
        fid = int(next_item["fid"])
        if fid in seen:
            raise RuntimeError(f"ciclo topológico detectado no trecho {fid}")
        path.append(next_item)
        seen.add(fid)
        current = next_item
    return path


def upstream_network(
    by_destination: dict[int, list[dict[str, Any]]], start: dict[str, Any]
) -> list[dict[str, Any]]:
    selected: dict[int, dict[str, Any]] = {int(start["fid"]): start}
    pending = [int(start["noorigem"])]
    visited_nodes: set[int] = set()
    while pending:
        node = pending.pop()
        if node in visited_nodes:
            continue
        visited_nodes.add(node)
        for item in by_destination.get(node, []):
            fid = int(item["fid"])
            if fid not in selected:
                selected[fid] = item
                pending.append(int(item["noorigem"]))
    return list(selected.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--major-area-km2", type=float, default=50.0)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with requests.Session() as session:
        session.headers.update({"User-Agent": "PREVINE-research-audit/1.0"})
        all_segments = fetch_attributes(session, "cocursodag LIKE '786%'")
        mainstem_features = fetch_mainstem_geometry(session)

        mainstem_by_fid = {
            int(feature["properties"]["fid"]): feature["properties"]
            for feature in mainstem_features
        }
        anchors: dict[str, dict[str, Any]] = {}
        for code in STATION_ORDER:
            segment, distance = nearest_mainstem_segment(STATIONS[code], mainstem_features)
            anchors[code] = {
                **STATIONS[code],
                "segment": segment,
                "station_to_bho6_mainstem_m": round(distance, 2),
            }

        by_origin: dict[int, list[dict[str, Any]]] = {}
        by_destination: dict[int, list[dict[str, Any]]] = {}
        for item in all_segments:
            by_origin.setdefault(int(item["noorigem"]), []).append(item)
            by_destination.setdefault(int(item["nodestino"]), []).append(item)

        muçum_anchor = anchors["86510000"]["segment"]
        upstream = upstream_network(by_destination, muçum_anchor)
        upstream_ids = {int(item["fid"]) for item in upstream}
        mainstem_upstream = [item for item in upstream if str(item["cocursodag"]) == "786"]
        major = [
            item
            for item in upstream
            if float(item.get("nuareamont") or 0) >= args.major_area_km2
        ]

        paths: dict[str, Any] = {}
        for left, right in zip(STATION_ORDER, STATION_ORDER[1:]):
            start = anchors[left]["segment"]
            target = int(anchors[right]["segment"]["fid"])
            path = downstream_path(by_origin, start, target)
            paths[f"{left}_to_{right}"] = {
                "segment_count": len(path),
                "length_km": round(sum(float(i.get("nucomptrec") or 0) for i in path), 3),
                "start_segment": int(path[0]["fid"]),
                "end_segment": int(path[-1]["fid"]),
                "watercourses": sorted({i.get("noriocomp") or i.get("noespecif") for i in path}),
                "segments": [int(i["fid"]) for i in path],
            }

        major_ids = sorted({int(item["fid"]) for item in major})
        major_features = fetch_geometry_for_ids(session, major_ids)

    # Preserve the official geometries that form the connected mainstem path.
    path_ids = sorted(
        {
            fid
            for path in paths.values()
            for fid in path["segments"]
        }
    )
    mainstem_selected = [
        feature for feature in mainstem_features
        if int(feature["properties"]["fid"]) in set(path_ids)
    ]
    network_features = []
    for feature in mainstem_selected + major_features:
        properties = dict(feature["properties"])
        properties["network_role"] = (
            "mainstem_station_path"
            if int(properties["fid"]) in set(path_ids)
            else "major_upstream_segment"
        )
        network_features.append(
            {
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": properties,
            }
        )
    for code in STATION_ORDER:
        station = STATIONS[code]
        network_features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [station["lon"], station["lat"]]},
                "properties": {
                    "station_code": code,
                    "name": station["name"],
                    "role": station["role"],
                    "network_role": "observed_station_anchor",
                },
            }
        )

    geojson = {
        "type": "FeatureCollection",
        "name": "BHO6_Taquari_Antas_network_research",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": network_features,
    }
    (output_dir / "bho6_taquari_antas_network.geojson").write_text(
        json.dumps(geojson, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    station_area = {
        code: round(float(anchors[code]["segment"].get("nuareamont") or 0), 3)
        for code in STATION_ORDER
    }
    nested_differences = {
        "86472000_to_86472600_km2": round(station_area["86472600"] - station_area["86472000"], 3),
        "86472600_to_86510000_km2": round(station_area["86510000"] - station_area["86472600"], 3),
        "86472000_to_86510000_km2": round(station_area["86510000"] - station_area["86472000"], 3),
    }
    audit = {
        "schema_version": "hec_hms_taquari_antas_network_audit_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "estrutura de rede para pesquisa HEC-HMS; não é alerta nem autorização operacional",
        "source": {
            "provider": "ANA / SNIRH",
            "dataset": "BHO6 main.geoft_bho_trecho_drenagem",
            "endpoint": BHO6_QUERY,
            "version_field": "dsversao",
            "query": "cocursodag LIKE '786%'",
            "network_semantics": "noorigem -> nodestino, trechos conectados com sentido de fluxo",
        },
        "stations": anchors,
        "topology": {
            "all_bho6_segments_in_code_786_family": len(all_segments),
            "upstream_segments_reachable_from_86510000": len(upstream),
            "mainstem_segments_in_upstream_network": len(mainstem_upstream),
            "major_segments_at_or_above_area_threshold": len(major),
            "major_area_threshold_km2": args.major_area_km2,
            "connected_order": STATION_ORDER,
            "paths": paths,
            "nested_catchment_area_km2_from_bho6": station_area,
            "nested_area_differences_km2": nested_differences,
        },
        "model_design": {
            "scope": "bacia aninhada Rio das Antas -> Rio Taquari até Muçum",
            "elements": [
                {"id": "SB_ANTAS_86472000", "type": "subbasin", "area_km2": station_area["86472000"], "status": "network_anchor"},
                {"id": "R_ANTAS_SANTA_TEREZA", "type": "reach", "source_path": "86472000_to_86472600", "status": "geometry_source_ready_routing_parameters_pending"},
                {"id": "J_SANTA_TEREZA_86472600", "type": "junction", "station": "86472600", "status": "control_point_no_reconciled_flow_target"},
                {"id": "R_SANTA_TEREZA_MUCUM", "type": "reach", "source_path": "86472600_to_86510000", "status": "geometry_source_ready_routing_parameters_pending"},
                {"id": "J_MUCUM_86510000", "type": "junction", "station": "86510000", "status": "calibration_target_candidate"},
            ],
            "routing_method": "Muskingum or Muskingum-Cunge only after reach length/slope/section evidence is reconciled",
            "rainfall_policy": "use only audited station variables; 86472600 has no audited event rainfall in the current package",
        },
        "calibration_gate": {
            "network_topology": "CONFIRMED_FROM_BHO6",
            "mucum_observed_flow": "CANDIDATE_AVAILABLE_BUT_UNIT_AND_SERIES_RECONCILIATION_REQUIRED",
            "santa_tereza_observed_flow": "BLOCKED_CURRENT_AUDIT_HAS_NO_RECONCILED_SERIES",
            "reach_routing_parameters": "BLOCKED_UNTIL_CHANNEL_LENGTH_SLOPE_AND_CROSS_SECTION_POLICY_IS_CLOSED",
            "rainfall_spatialization": "PARTIAL_AUDITED_GAUGES_ONLY",
            "calibration_status": "NOT_CLAIMED_AS_COMPLETED",
        },
        "artifacts": {
            "network_geojson": "bho6_taquari_antas_network.geojson",
            "this_report": "network_audit_latest.json",
        },
    }
    (output_dir / "network_audit_latest.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "output_dir": str(output_dir),
        "stations": {code: {"fid": anchors[code]["segment"]["fid"], "area_km2": station_area[code], "distance_m": anchors[code]["station_to_bho6_mainstem_m"]} for code in STATION_ORDER},
        "paths": {key: {"segments": value["segment_count"], "length_km": value["length_km"]} for key, value in paths.items()},
        "upstream_segments": len(upstream),
        "major_segments": len(major),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
