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
from math import isfinite
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon
from santa_tereza_hand_field_contract import gauge_to_hand, select_hand_level, validate_field_contours


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
BANKFULL_M = 15.0  # limiar de transbordamento publicado; não é o zero espacial HAND


def read_embedded_payload(page: Path) -> tuple[list[str], int, dict]:
    lines = page.read_text(encoding="utf-8").splitlines()
    idx = next((i for i, line in enumerate(lines) if line.startswith("const D=")), None)
    if idx is None:
        raise RuntimeError(f"payload D não encontrado em {page}")
    line = lines[idx]
    if not line.endswith(";"):
        raise RuntimeError(f"payload D sem terminador em {page}")
    return lines, idx, json.loads(line[len("const D=") : -1])


def validate_payload(data: dict, page: Path, *, route: bool = False) -> None:
    """Check structures consumed by the calculation before preparing a write."""
    def reject(message: str) -> None:
        raise RuntimeError(f"payload incompatível em {page.name}: {message}")

    def number(value) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)

    def coordinates(value) -> bool:
        return (isinstance(value, list) and len(value) == 2
                and all(number(item) for item in value)
                and -90 <= value[0] <= 90 and -180 <= value[1] <= 180)

    if not isinstance(data, dict) or not isinstance(data.get("meta", {}), dict):
        reject("objeto/meta ausente ou inválido")
    nodes = data.get("nos", [])
    if not isinstance(nodes, list) or any(not coordinates(node) for node in nodes):
        reject("nos deve conter coordenadas [lat, lon] finitas")
    for key in ("cota_no", "cota_alaga_m"):
        if key in data and (not isinstance(data[key], list) or len(data[key]) != len(nodes)):
            reject(f"{key} não corresponde aos nós")
    cells = data.get("cells", [])
    if not isinstance(cells, list):
        reject("cells deve ser uma lista")
    for cell in cells:
        if not isinstance(cell, dict):
            reject("célula não é um objeto")
        ring = cell.get("poly")
        if not isinstance(ring, list) or len(ring) < 3 or any(not coordinates(point) for point in ring):
            reject("poly da célula ausente ou inválido")
        polygon = Polygon([(lon, lat) for lat, lon in ring])
        if not polygon.is_valid or polygon.is_empty or polygon.area <= 0:
            reject("poly da célula não é um polígono válido de área positiva")
        if not number(cell.get("pop")) or cell["pop"] < 0:
            reject("pop da célula ausente ou inválida")
    if not route:
        return
    if "nos" not in data or not isinstance(data.get("meta", {}).get("nivel"), dict):
        reject("rota sem nos/meta.nivel")
    edges, prox = data.get("edges"), data.get("prox")
    if not isinstance(edges, list):
        reject("edges ausente ou inválido")
    for edge in edges:
        if (not isinstance(edge, list) or len(edge) < 3
                or any(not isinstance(index, int) or isinstance(index, bool)
                       or not 0 <= index < len(nodes) for index in edge[:2])):
            reject("edges contém referência de nó inválida")
    if not isinstance(prox, list) or len(prox) != len(nodes):
        reject("prox não corresponde aos nós")
    if any(value is not None and (not isinstance(value, int) or isinstance(value, bool)
                                 or not -1 <= value < len(nodes)) for value in prox):
        reject("prox contém referência de nó inválida")


def render_payload(lines: list[str], payload_line: int, data: dict) -> str:
    # Serialization is part of preparation too: a late NaN or unsupported
    # value must not leave six freshly stamped pages and an old OK report.
    lines[payload_line] = "const D=" + json.dumps(
        data, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ) + ";"
    return "\n".join(lines) + "\n"


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


def prepare_page(page: Path, geometries: list, levels: list[float], provenance: dict | None = None) -> tuple[str, dict]:
    lines, payload_line, data = read_embedded_payload(page)
    validate_payload(data, page)
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
        cell["cobertura_status"] = "limiar_identificado" if level is not None else "sem limiar identificado no intervalo"
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
            "hand_source": provenance,
        }
    )
    summary = {
        "page": page.relative_to(ROOT).as_posix(),
        "nodes_total": len(nodes),
        "nodes_with_threshold": sum(level is not None for level in node_levels),
        "cells_total": len(data.get("cells", [])),
        "cells_with_threshold": sum(level is not None for level in cell_levels),
        "population_with_threshold": sum(cell["pop"] for cell in data.get("cells", []) if cell["cota"] is not None),
    }
    return render_payload(lines, payload_line, data), summary


def update_page(page: Path, geometries: list, levels: list[float], provenance: dict | None = None) -> dict:
    html, summary = prepare_page(page, geometries, levels, provenance)
    page.write_text(html, encoding="utf-8")
    return summary


def route_stage_m(meta: dict) -> tuple[float, str]:
    nivel = meta.get("nivel", {})
    if nivel.get("fonte") in {"live", "snapshot_historico"}:
        candidates = [nivel.get("nivel_atual_cm"), nivel.get("nivel_pico_cm")]
        valid = [float(value) / 100 for value in candidates
                 if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)]
        if not valid:
            raise RuntimeError("snapshot de rota sem nível de régua")
        return max(valid), "snapshot_historico"
    if (isinstance(nivel.get("nivel_regua_cm"), (int, float))
            and not isinstance(nivel["nivel_regua_cm"], bool) and isfinite(nivel["nivel_regua_cm"])):
        return float(nivel["nivel_regua_cm"]) / 100, "cenario_historico"
    raise RuntimeError("cenário de rota sem nível de régua")


def contour_rings(geometry) -> list[list[list[list[float]]]]:
    """Coordenadas Leaflet por polígono, com exterior e todas as ilhas internas."""
    if geometry.geom_type == "Polygon":
        return [[[[lat, lon] for lon, lat in ring.coords]
                 for ring in [geometry.exterior, *geometry.interiors]]]
    if geometry.geom_type == "MultiPolygon":
        return [contour_rings(polygon)[0] for polygon in geometry.geoms]
    raise RuntimeError(f"geometria de contorno inesperada: {geometry.geom_type}")


def haversine_m(a: list[float], b: list[float]) -> float:
    from math import asin, cos, radians, sin, sqrt

    lat1, lon1, lat2, lon2 = map(radians, [a[0], a[1], b[0], b[1]])
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 6_371_000 * 2 * asin(sqrt(h))


def prepare_route_page(page: Path, geometries: list, levels: list[float], provenance: dict | None = None) -> tuple[str, dict]:
    lines, payload_line, data = read_embedded_payload(page)
    validate_payload(data, page, route=True)
    meta = data.setdefault("meta", {})
    stage_m, temporal_scope = route_stage_m(meta)
    hand_m = gauge_to_hand(stage_m)
    selected_level = select_hand_level(levels, hand_m)
    if selected_level is None:
        raise RuntimeError("sem cobertura HAND no intervalo; rota não recalculada")
    inundation = geometries[levels.index(selected_level)]

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
    nivel["hand_zero_regua_m"] = HAND_ZERO_M
    nivel["bankfull_m"] = BANKFULL_M
    nivel["transbordando"] = stage_m > BANKFULL_M
    meta.update(
        {
            "nivel_projeto_m": selected_level,
            "nivel_regua_cenario_m": stage_m,
            "hand_zero_regua_m": HAND_ZERO_M,
            "hand_solicitado_m": round(hand_m, 6),
            "hand_aplicado_m": selected_level,
            "selecao_contorno": "nível superior disponível para triagem; sem limitação silenciosa ao teto",
            "hand_source": provenance,
            "formula_regua_para_hand": "HAND = max(0, regua_m - 1.60)",
            "fonte_mancha": "contornos_mancha.json (HAND hidráulico LiDAR, calibração de campo)",
            "gerado_em": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "temporal_scope": temporal_scope,
            "status": "pesquisa_exercicio_nao_operacional",
        }
    )
    summary = {
        "page": page.relative_to(ROOT).as_posix(),
        "temporal_scope": temporal_scope,
        "gauge_m": stage_m,
        "hand_m": selected_level,
        "edges_total": len(edges),
        "edges_intersecting_contour": sum(bool(edge[2]) for edge in edges),
        "routes_with_intersecting_edge": sum(value > 0 for value in route_water_m),
    }
    return render_payload(lines, payload_line, data), summary


def update_route_page(page: Path, geometries: list, levels: list[float], provenance: dict | None = None) -> dict:
    html, summary = prepare_route_page(page, geometries, levels, provenance)
    page.write_text(html, encoding="utf-8")
    return summary


def main() -> None:
    contours = json.loads(CONTOURS.read_text(encoding="utf-8"))
    levels, geometries, provenance = validate_field_contours(contours)
    # Validate, calculate summaries and serialize ALL seven pages in memory
    # before the first write. Preparation failures preserve the previous pack.
    prepared_pages = [(page, *prepare_page(page, geometries, levels, provenance)) for page in PAGES]
    prepared_routes = [(page, *prepare_route_page(page, geometries, levels, provenance)) for page in ROUTE_PAGES]
    report = {
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": CONTOURS.relative_to(ROOT).as_posix(),
        "source_provenance": provenance,
        "field_calibration": {"gauge_m": HAND_ZERO_M, "hand_m": 0.0, "scope": "rio principal"},
        "hand_levels": {"minimum_m": levels[0], "maximum_m": levels[-1], "count": len(levels)},
        "pages": [summary for _, _, summary in prepared_pages],
        "routes": [summary for _, _, summary in prepared_routes],
        "limit": "Pesquisa/exercício: os limiares espaciais não validam observação de água, rota segura, alerta ou ordem de evacuação.",
    }
    report_text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    for page, html, _ in [*prepared_pages, *prepared_routes]:
        page.write_text(html, encoding="utf-8")
    REPORT.write_text(report_text, encoding="utf-8")
    print(report_text, end="")


if __name__ == "__main__":
    main()
