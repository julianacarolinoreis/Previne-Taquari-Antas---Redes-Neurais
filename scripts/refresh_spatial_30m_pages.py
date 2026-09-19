#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Atualiza as cotas espaciais dos painéis de impacto/margem até HAND 30 m.

Os HTMLs antigos embutiam cotas derivadas de contornos que terminavam em 15 m.
Este script NÃO estica esses dados: ele lê os contornos HAND regenerados até
30 m e recalcula a primeira cota que alcança cada nó/célula. Assim, o slider
0–30 m usa cobertura espacial real do conjunto publicado; ausência continua
sendo None/SEM DADO, nunca "ponto alto".

Uso:
  python scripts/refresh_spatial_30m_pages.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from shapely.geometry import Point, Polygon, shape
from shapely.ops import unary_union
from shapely.prepared import prep

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_MAX_M = 30.0

CITIES = {
    "mucum": {
        "contours": ROOT / "assets/data/mucum_inundacao/contornos_mancha.json",
        "ui_hand_max_m": 30.0,
        "pages": [
            ROOT / "pesquisas/mucum-mapa-impacto.html",
            ROOT / "pesquisas/mucum-mapa-margem.html",
            ROOT / "pesquisas/mucum-painel-evacuacao.html",
            ROOT / "mucum_painel_evacuacao.html",
        ],
    },
    "santa_tereza": {
        "contours": ROOT / "assets/data/santa_tereza_inundacao/contornos_mancha.json",
        # Santa Tereza usa 15 m na régua como HAND 0. Logo, HAND 15 m
        # corresponde ao teto visível pedido de 30 m na régua.
        "ui_hand_max_m": 15.0,
        "pages": [
            ROOT / "pesquisas/santa-tereza-mapa-impacto.html",
            ROOT / "pesquisas/santa-tereza-mapa-margem.html",
            ROOT / "pesquisas/santa-tereza-painel-evacuacao.html",
            ROOT / "santa_tereza_painel_evacuacao.html",
        ],
    },
}


def load_levels(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    grouped: dict[float, list] = {}
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        try:
            level = round(float(props["nivel_m"]), 1)
        except (KeyError, TypeError, ValueError):
            continue
        if not (0.0 <= level <= SCENARIO_MAX_M):
            continue
        geom = shape(feature.get("geometry")).buffer(0)
        if geom.is_empty:
            continue
        grouped.setdefault(level, []).append(geom)
    if not grouped:
        raise RuntimeError(f"sem contornos válidos em {path}")
    levels = []
    for level in sorted(grouped):
        merged = unary_union(grouped[level]).buffer(0)
        levels.append((level, prep(merged)))
    if levels[-1][0] < SCENARIO_MAX_M - 0.05:
        raise RuntimeError(
            f"{path} termina em {levels[-1][0]:.1f} m; regenere os contornos até {SCENARIO_MAX_M:.1f} m antes de atualizar as páginas"
        )
    return levels


def first_level(point: Point, levels):
    for level, prepared in levels:
        if prepared.covers(point):
            return level
    return None


def point_from_poly(poly):
    if not poly:
        return None
    try:
        geom = Polygon([(float(lon), float(lat)) for lat, lon in poly]).buffer(0)
    except Exception:
        return None
    if geom.is_empty:
        return None
    return geom.representative_point()


def extract_payload(html: str):
    match = re.search(r"const D=(\{[\s\S]*?\});\n", html)
    if not match:
        raise RuntimeError("const D={...}; não encontrado")
    return match, json.loads(match.group(1))


def update_payload(data: dict, levels, ui_hand_max_m: float):
    meta = data.setdefault("meta", {})
    meta["nivel_max_m"] = float(ui_hand_max_m)
    meta["cobertura_espacial_m"] = SCENARIO_MAX_M
    meta["cobertura_espacial_nota"] = "contornos HAND recalculados até 30 m; None significa sem dado espacial"

    nodes = data.get("nos")
    if isinstance(nodes, list) and nodes:
        cotas = []
        for item in nodes:
            try:
                lat, lon = float(item[0]), float(item[1])
                cotas.append(first_level(Point(lon, lat), levels))
            except (TypeError, ValueError, IndexError):
                cotas.append(None)
        if "cota_no" in data:
            data["cota_no"] = cotas
        if "cota_alaga_m" in data:
            data["cota_alaga_m"] = cotas

    cells = data.get("cells")
    if isinstance(cells, list):
        for cell in cells:
            point = point_from_poly(cell.get("poly"))
            if point is None and cell.get("lat") is not None and cell.get("lon") is not None:
                try:
                    point = Point(float(cell["lon"]), float(cell["lat"]))
                except (TypeError, ValueError):
                    point = None
            cell["cota"] = first_level(point, levels) if point is not None else None
    return data


def update_page(path: Path, levels, ui_hand_max_m: float):
    html = path.read_text(encoding="utf-8")
    match, data = extract_payload(html)
    data = update_payload(data, levels, ui_hand_max_m)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    updated = html[: match.start(1)] + payload + html[match.end(1) :]
    path.write_text(updated, encoding="utf-8")
    n_nodes = len(data.get("nos") or [])
    n_cells = len(data.get("cells") or [])
    max_node = max((v for v in (data.get("cota_no") or data.get("cota_alaga_m") or []) if isinstance(v, (int, float))), default=None)
    max_cell = max((c.get("cota") for c in (data.get("cells") or []) if isinstance(c.get("cota"), (int, float))), default=None)
    print(f"{path.relative_to(ROOT)}: nós={n_nodes} células={n_cells} max_nó={max_node} max_célula={max_cell}")


def main():
    for city, cfg in CITIES.items():
        levels = load_levels(cfg["contours"])
        print(f"{city}: {len(levels)} níveis, {levels[0][0]:.1f}–{levels[-1][0]:.1f} m")
        for page in cfg["pages"]:
            if page.exists():
                update_page(page, levels, float(cfg["ui_hand_max_m"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
