#!/usr/bin/env python3
"""Recalcula os limiares espaciais do painel de evacuação de Santa Tereza.

O painel conserva sua finalidade de pesquisa/exercício, sua rede de ruas e
sua Grade IBGE. Este script troca somente os limiares espaciais embutidos por
limiares obtidos nos contornos atuais: HAND hidráulico LiDAR e calibração de
campo ``régua 1,60 m = HAND 0`` para o rio principal.

Não transforma o resultado em rota liberada, alerta ou observação de água.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon, shape


ROOT = Path(__file__).resolve().parents[1]
CONTOURS = ROOT / "assets/data/santa_tereza_inundacao/contornos_mancha.json"
REPORT = ROOT / "assets/data/santa_tereza_inundacao/painel_evacuacao_hand_campo_diagnostic.json"
PAGES = [
    ROOT / "santa_tereza_painel_evacuacao.html",
    ROOT / "pesquisas/santa-tereza-painel-evacuacao.html",
    ROOT / "pesquisas/santa-tereza-mapa-impacto.html",
    ROOT / "pesquisas/santa-tereza-mapa-margem.html",
]
ROUTE_PAGES = [
    ROOT / "pesquisas/santa-tereza-rota-fuga-ruas.html",
    ROOT / "santa_tereza_rota_fuga_ruas_cenario.html",
    ROOT / "pesquisas/santa-tereza-rota-fuga-ruas-cenario.html",
]
HAND_ZERO_M = 1.60


def read_embedded_payload(page: Path) -> tuple[list[str], int, dict]:
    lines = page.read_text(encoding="utf-8").splitlines()
    idx = next((i for i, line in enumerate(lines) if line.startswith("const D=")), None)
    if idx is None:
        raise RuntimeError(f"payload D não encontrado em {page}")
    line = lines[idx]
    if not line.endswith(";"):
        raise RuntimeError(f"payload D sem terminador em {page}")
    return lines, idx, json.loads(line[len("const D=") : -1])


def first_level_for_point(point: Point, geometries: list, levels: list[float]) -> float | None:
    lo, hi, answer = 0, len(geometries) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if geometries[mid].covers(point):
            answer = levels[mid]
            hi = mid - 1
        else:
            lo = mid + 1
    return answer


def first_level_for_cell(cell: Polygon, geometries: list, levels: list[float]) -> tuple[float | None, float | None]:
    """Return first HAND level and wet fraction, requiring positive overlap."""
    lo, hi, answer = 0, len(geometries) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if geometries[mid].intersection(cell).area > 0:
            answer = mid
            hi = mid - 1
        else:
            lo = mid + 1
    if answer is None:
        return None, None
    fraction = geometries[answer].intersection(cell).area / cell.area if cell.area else None
    return levels[answer], fraction


def update_page(page: Path, geometries: list, levels: list[float]) -> dict:
    lines, payload_line, data = read_embedded_payload(page)
    nodes = data.get("nos", [])
    node_levels = [first_level_for_point(Point(lon, lat), geometries, levels) for lat, lon in nodes]
    cell_levels: list[float | None] = []
    cell_fractions: list[float | None] = []
    for cell in data.get("cells", []):
        polygon = Polygon([(lon, lat) for lat, lon in cell["poly"]])
        level, fraction = first_level_for_cell(polygon, geometries, levels)
        cell["cota"] = level
        cell["frac_area_primeiro_nivel"] = fraction
        cell["cota_metodo"] = "intersecao_geometrica_contorno_lidar_hand_campo"
        cell_levels.append(level)
        cell_fractions.append(fraction)

    if "cota_no" in data:
        data["cota_no"] = node_levels
    if "cota_alaga_m" in data:
        data["cota_alaga_m"] = node_levels
    if "mancha" in data:
        data["mancha"] = []  # The visual layer is always fetched from the current contour file.
    meta = data.setdefault("meta", {})
    meta.update(
        {
            "nivel_max_m": levels[-1],
            "hand_zero_regua_m": HAND_ZERO_M,
            "formula_regua_para_hand": "HAND = max(0, regua_m - 1.60)",
            "fonte_terreno": "HAND hidráulico LiDAR atual; contornos_mancha.json",
            "fonte_roteamento": "somente rio principal; FILL usado apenas para roteamento",
            "gerado_em": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "cobertura_espacial_m": levels[-1],
            "cobertura_espacial_nota": "limiares recalculados nos contornos LiDAR atuais; ausência de limiar não significa segurança, água observada ou rota liberada",
            "status": "pesquisa_exercicio_nao_operacional",
        }
    )
    lines[payload_line] = "const D=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
    page.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "page": page.relative_to(ROOT).as_posix(),
        "nodes_total": len(nodes),
        "nodes_with_threshold": sum(level is not None for level in node_levels),
        "cells_total": len(data.get("cells", [])),
        "cells_with_threshold": sum(level is not None for level in cell_levels),
        "population_with_threshold": sum(cell["pop"] for cell in data.get("cells", []) if cell["cota"] is not None),
    }


def route_stage_m(meta: dict) -> tuple[float, str]:
    nivel = meta.get("nivel", {})
    if nivel.get("fonte") in {"live", "snapshot_historico"}:
        candidates = [nivel.get("nivel_atual_cm"), nivel.get("nivel_pico_cm")]
        valid = [float(value) / 100 for value in candidates if isinstance(value, (int, float))]
        if not valid:
            raise RuntimeError("snapshot de rota sem nível de régua")
        return max(valid), "snapshot_historico"
    if isinstance(nivel.get("nivel_regua_cm"), (int, float)):
        return float(nivel["nivel_regua_cm"]) / 100, "cenario_historico"
    raise RuntimeError("cenário de rota sem nível de régua")


def contour_rings(geometry) -> list[list[list[float]]]:
    if geometry.geom_type == "Polygon":
        return [[[lat, lon] for lon, lat in geometry.exterior.coords]]
    if geometry.geom_type == "MultiPolygon":
        return [[[lat, lon] for lon, lat in polygon.exterior.coords] for polygon in geometry.geoms]
    raise RuntimeError(f"geometria de contorno inesperada: {geometry.geom_type}")


def haversine_m(a: list[float], b: list[float]) -> float:
    from math import asin, cos, radians, sin, sqrt

    lat1, lon1, lat2, lon2 = map(radians, [a[0], a[1], b[0], b[1]])
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 6_371_000 * 2 * asin(sqrt(h))


def update_route_page(page: Path, geometries: list, levels: list[float]) -> dict:
    lines, payload_line, data = read_embedded_payload(page)
    meta = data.setdefault("meta", {})
    stage_m, temporal_scope = route_stage_m(meta)
    hand_m = max(0.0, stage_m - HAND_ZERO_M)
    level_idx = min(range(len(levels)), key=lambda index: abs(levels[index] - hand_m))
    selected_level = levels[level_idx]
    inundation = geometries[level_idx]

    edges = data["edges"]
    edge_water: dict[tuple[int, int], bool] = {}
    for edge in edges:
        a, b = int(edge[0]), int(edge[1])
        segment = LineString([(data["nos"][a][1], data["nos"][a][0]), (data["nos"][b][1], data["nos"][b][0])])
        wet = inundation.intersects(segment)
        edge[2] = 1 if wet else 0
        edge_water[(min(a, b), max(a, b))] = wet

    route_water_m: list[float] = []
    for origin in range(len(data["nos"])):
        cursor, total_m, guard, visited = origin, 0.0, 0, set()
        while 0 <= cursor < len(data["nos"]) and cursor not in visited and guard < 6000:
            visited.add(cursor)
            next_node = data["prox"][cursor]
            if next_node is None or next_node < 0 or next_node == cursor:
                break
            if edge_water.get((min(cursor, next_node), max(cursor, next_node)), False):
                total_m += haversine_m(data["nos"][cursor], data["nos"][next_node])
            cursor, guard = next_node, guard + 1
        route_water_m.append(round(total_m, 1))

    data["agua_m"] = route_water_m
    data["mancha"] = contour_rings(inundation)
    nivel = meta.setdefault("nivel", {})
    if temporal_scope == "snapshot_historico":
        nivel["fonte"] = "snapshot_historico"
        nivel["rotulo"] = f"snapshot histórico da régua ({stage_m:.2f} m), recalculado no HAND LiDAR"
    else:
        nivel["rotulo"] = f"cenário histórico: régua {stage_m:.2f} m → HAND {selected_level:.1f} m"
    nivel["bankfull_m"] = HAND_ZERO_M
    nivel["transbordando"] = stage_m > HAND_ZERO_M
    meta.update(
        {
            "nivel_projeto_m": selected_level,
            "nivel_regua_cenario_m": stage_m,
            "hand_zero_regua_m": HAND_ZERO_M,
            "formula_regua_para_hand": "HAND = max(0, regua_m - 1.60)",
            "fonte_mancha": "contornos_mancha.json (HAND hidráulico LiDAR, calibração de campo)",
            "gerado_em": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "temporal_scope": temporal_scope,
            "status": "pesquisa_exercicio_nao_operacional",
        }
    )
    lines[payload_line] = "const D=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
    page.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "page": page.relative_to(ROOT).as_posix(),
        "temporal_scope": temporal_scope,
        "gauge_m": stage_m,
        "hand_m": selected_level,
        "edges_total": len(edges),
        "edges_intersecting_contour": sum(bool(edge[2]) for edge in edges),
        "routes_with_intersecting_edge": sum(value > 0 for value in route_water_m),
    }


def main() -> None:
    contours = json.loads(CONTOURS.read_text(encoding="utf-8"))
    ordered = sorted(
        (
            (float(feature["properties"]["nivel_m"]), shape(feature["geometry"]))
            for feature in contours["features"]
            if feature.get("geometry")
        ),
        key=lambda item: item[0],
    )
    levels = [level for level, _ in ordered]
    geometries = [geometry for _, geometry in ordered]
    if not levels or levels[0] < 0 or any(b < a for a, b in zip(levels, levels[1:])):
        raise RuntimeError("contornos HAND ausentes ou não monotônicos")

    pages = [update_page(page, geometries, levels) for page in PAGES]
    routes = [update_route_page(page, geometries, levels) for page in ROUTE_PAGES]
    report = {
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": CONTOURS.relative_to(ROOT).as_posix(),
        "field_calibration": {"gauge_m": HAND_ZERO_M, "hand_m": 0.0, "scope": "rio principal"},
        "hand_levels": {"minimum_m": levels[0], "maximum_m": levels[-1], "count": len(levels)},
        "pages": pages,
        "routes": routes,
        "limit": "Pesquisa/exercício: os limiares espaciais não validam observação de água, rota segura, alerta ou ordem de evacuação.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
