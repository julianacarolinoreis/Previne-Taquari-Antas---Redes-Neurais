#!/usr/bin/env python3
"""Regenera as cotas de margem/impacto a partir dos contornos HAND atuais.

Os arquivos antigos usavam cota HAND relativa 0..15 m e a interface a chamava
de "nível da cheia". Esta rotina mantém HAND como cálculo interno e publica a
cota equivalente da régua, com cenários da cota oficial de inundação até 30 m.

Não inventa área alagada além do contorno disponível: pontos nunca cobertos
permanecem nulos.
"""
from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Point, Polygon, shape
from shapely.prepared import prep

ROOT = Path(__file__).resolve().parents[1]

CITIES = {
    "santa_tereza": {
        "zero_gauge_m": 4.0,
        "scenario_min_m": 15.0,
        "scenario_max_m": 30.0,
        "contours": ROOT / "assets/data/santa_tereza_inundacao/contornos_mancha.json",
        "pages": [
            ROOT / "pesquisas/santa-tereza-mapa-margem.html",
            ROOT / "pesquisas/santa-tereza-mapa-impacto.html",
            ROOT / "pesquisas/santa-tereza-painel-evacuacao.html",
            ROOT / "santa_tereza_painel_evacuacao.html",
        ],
    },
    "mucum": {
        "zero_gauge_m": 5.0,
        "scenario_min_m": 18.0,
        "scenario_max_m": 30.0,
        "contours": ROOT / "assets/data/mucum_inundacao/contornos_mancha.json",
        "pages": [
            ROOT / "pesquisas/mucum-mapa-margem.html",
            ROOT / "pesquisas/mucum-mapa-impacto.html",
            ROOT / "pesquisas/mucum-painel-evacuacao.html",
            ROOT / "mucum_painel_evacuacao.html",
        ],
    },
}


def load_contours(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for feature in raw.get("features", []):
        level = feature.get("properties", {}).get("nivel_m")
        geom = feature.get("geometry")
        if level is None or not geom:
            continue
        geometry = shape(geom).buffer(0)
        if geometry.is_empty:
            continue
        rows.append((float(level), prep(geometry)))
    rows.sort(key=lambda item: item[0])
    if not rows:
        raise RuntimeError(f"sem contornos válidos: {path}")
    return rows


def first_hand_level(point: Point, contours):
    for level, geometry in contours:
        if geometry.covers(point):
            return level
    return None


def extract_data(html: str):
    marker = "const D="
    start = html.find(marker)
    if start < 0:
        raise RuntimeError("const D= não encontrado")
    start += len(marker)
    decoder = json.JSONDecoder()
    data, used = decoder.raw_decode(html[start:])
    return data, start, start + used


def cell_point(cell):
    poly = cell.get("poly")
    if not poly:
        return None
    try:
        geom = Polygon([(float(lon), float(lat)) for lat, lon in poly]).buffer(0)
    except Exception:
        return None
    if geom.is_empty:
        return None
    return geom.representative_point()


def gauge_level(hand_level, zero):
    return None if hand_level is None else round(zero + float(hand_level), 1)


def patch_ui(html: str) -> str:
    html = html.replace(
        "Arraste o nível da cheia e veja a janela de fuga fechar.",
        "Arraste o nível da régua do rio e veja a janela de fuga fechar.",
    )
    html = html.replace("Nível da cheia:", "Nível da régua (cenário):")
    html = html.replace("cota que alaga:", "régua estimada que alcança:")
    html = html.replace(
        "const sld=document.getElementById('sld'), sldTaxa=document.getElementById('sldTaxa'), NVMAX=D.meta.nivel_max_m;",
        "const sld=document.getElementById('sld'), sldTaxa=document.getElementById('sldTaxa'), NVMIN=D.meta.nivel_min_m, NVMAX=D.meta.nivel_max_m;",
    )
    html = html.replace(
        "const sld=document.getElementById('sld'),sldTaxa=document.getElementById('sldTaxa'),NVMAX=D.meta.nivel_max_m;",
        "const sld=document.getElementById('sld'),sldTaxa=document.getElementById('sldTaxa'),NVMIN=D.meta.nivel_min_m,NVMAX=D.meta.nivel_max_m;",
    )
    html = html.replace(
        "let taxaCmH=D.meta.taxa_cm_h; const vel=D.meta.vel_idoso_ms, NVMAX=D.meta.nivel_max_m;",
        "let taxaCmH=D.meta.taxa_cm_h; const vel=D.meta.vel_idoso_ms, NVMIN=D.meta.nivel_min_m, NVMAX=D.meta.nivel_max_m;",
    )
    html = html.replace(
        "render(sld.value/100*NVMAX);",
        "render(NVMIN+(sld.value/100)*(NVMAX-NVMIN));",
    )
    html = html.replace(
        "function nivelAtual(){return sld.value/100*NVMAX;}",
        "function nivelAtual(){return NVMIN+(sld.value/100)*(NVMAX-NVMIN);}",
    )
    return html


def rebuild_page(path: Path, cfg, contours):
    html = path.read_text(encoding="utf-8")
    data, start, end = extract_data(html)
    zero = float(cfg["zero_gauge_m"])
    hand_max = max(level for level, _ in contours)

    if isinstance(data.get("nos"), list):
        cotas = []
        for node in data["nos"]:
            try:
                lat, lon = float(node[0]), float(node[1])
                hand = first_hand_level(Point(lon, lat), contours)
            except Exception:
                hand = None
            cotas.append(gauge_level(hand, zero))
        if "cota_alaga_m" in data:
            data["cota_alaga_hand_m_legacy"] = data.get("cota_alaga_m")
            data["cota_alaga_m"] = cotas
        if "cota_no" in data:
            data["cota_no_hand_m_legacy"] = data.get("cota_no")
            data["cota_no"] = cotas

    if isinstance(data.get("cells"), list):
        for cell in data["cells"]:
            point = cell_point(cell)
            hand = first_hand_level(point, contours) if point is not None else None
            if "cota" in cell:
                cell["cota_hand_m"] = hand
                cell["cota"] = gauge_level(hand, zero)

    meta = data.setdefault("meta", {})
    meta["zero_regua_m"] = zero
    meta["nivel_min_m"] = float(cfg["scenario_min_m"])
    meta["nivel_max_m"] = float(cfg["scenario_max_m"])
    meta["hand_max_disponivel_m"] = hand_max
    meta["cota_referencia"] = "regua_m"
    meta["nota_cota"] = (
        "Cotas exibidas são da régua do cenário; HAND permanece como variável "
        "relativa interna. A faixa pública vai da cota oficial de inundação até 30 m."
    )

    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html = html[:start] + encoded + html[end:]
    html = patch_ui(html)
    path.write_text(html, encoding="utf-8")
    print(
        f"atualizado {path.relative_to(ROOT)} · HAND até {hand_max:.1f} m "
        f"· régua até {cfg['scenario_max_m']:.1f} m"
    )


def main():
    for cfg in CITIES.values():
        contours = load_contours(cfg["contours"])
        for path in cfg["pages"]:
            rebuild_page(path, cfg, contours)


if __name__ == "__main__":
    main()
