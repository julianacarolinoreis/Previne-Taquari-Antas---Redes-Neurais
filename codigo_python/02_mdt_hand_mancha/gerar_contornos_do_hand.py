#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera contornos_mancha.json A PARTIR DO MESMO RASTER HAND que o popup consulta.

Motivação (bug encontrado em 30/07/2026): a mancha desenhada no mapa vinha de
contornos vetorizados COM suavização gaussiana (sigma=2,0), enquanto o popup
consulta o raster HAND pixel a pixel. As duas geometrias discordavam: em
34–57% dos pontos de borda o HAND real diferia mais de 1 m do nível anunciado
pelo contorno — e num barranco isso vira "o mapa diz que tem água, o popup diz
que não". Em Muçum os contornos ainda vinham 10–20% menores em área.

Correção: vetorizar o PRÓPRIO HAND embutido na página (a mesma fonte do popup),
sem suavização. Mantém-se apenas a simplificação de Douglas-Peucker, cujo desvio
máximo é limitado pela tolerância (padrão 1 px), então a borda nunca se afasta
mais que isso do raster. Assim popup e mancha concordam por construção.

Uso:
    python gerar_contornos_do_hand.py            # as duas cidades
    python gerar_contornos_do_hand.py mucum      # só uma
"""
import os, sys, json, re, base64, io
import numpy as np
from PIL import Image
import rasterio.features
from rasterio.transform import from_bounds
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

Image.MAX_IMAGE_PIXELS = None
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

CIDADES = {
    "santa_tereza": {
        "pagina": "santa_tereza_previsao_inundacao.html",
        "saida": "assets/data/santa_tereza_inundacao/contornos_mancha.json",
    },
    "mucum": {
        "pagina": "mucum_previsao_inundacao.html",
        "saida": "assets/data/mucum_inundacao/contornos_mancha.json",
    },
}

NIVEIS = [round(x * 0.5, 1) for x in range(0, 31)]   # 0,0 .. 15,0 m
SIMPLIFY_PX = 1.0        # tolerância Douglas-Peucker, em pixels (desvio máximo)
AREA_MIN_HA = 0.05       # descarta lascas menores que isso


def ler_hand(pagina):
    """Lê o payload HAND embutido na página — exatamente o que o popup usa."""
    html = open(os.path.join(RAIZ, pagina), encoding="utf-8").read()
    m = re.search(r'<script id="hand-data" type="application/json">(.*?)</script>', html, re.DOTALL)
    d = json.loads(m.group(1))
    A = np.array(Image.open(io.BytesIO(base64.b64decode(d["hand_png_b64"]))).convert("L"))
    return d, A


def gerar(cidade, cfg):
    d, A = ler_hand(cfg["pagina"])
    rows, cols = A.shape
    tr = from_bounds(d["W"], d["S"], d["E"], d["N"], cols, rows)
    grau_px_lon = abs(d["E"] - d["W"]) / cols
    grau_px_lat = abs(d["N"] - d["S"]) / rows
    grau_por_px = grau_px_lon
    tol = SIMPLIFY_PX * grau_px_lon
    lat0 = (d["S"] + d["N"]) / 2
    m_por_grau_lon = 111320 * np.cos(np.radians(lat0))
    px_ha = (abs(d["E"] - d["W"]) * m_por_grau_lon / cols) * \
            (abs(d["N"] - d["S"]) * 111320 / rows) / 1e4

    print(f"\n== {cidade} == HAND {cols}x{rows} | simplify {SIMPLIFY_PX} px "
          f"(~{tol*m_por_grau_lon:.1f} m de desvio máximo)")

    feats = []
    for nivel in NIVEIS:
        dm = int(round(nivel * 10))
        if dm > int(A.max()):
            continue
        mask = (A <= dm)
        if not mask.any():
            continue
        geoms = [shape(g) for g, v in rasterio.features.shapes(
            mask.astype(np.uint8), mask=mask, transform=tr, connectivity=8)]
        if not geoms:
            continue
        uni = unary_union(geoms)
        uni = uni.simplify(tol, preserve_topology=True)   # sem suavização gaussiana
        partes = list(uni.geoms) if uni.geom_type == "MultiPolygon" else [uni]
        area_total = 0.0
        for p in partes:
            if p.is_empty:
                continue
            a_ha = p.area / (grau_px_lon * grau_px_lat) * px_ha
            if a_ha < AREA_MIN_HA:
                continue
            area_total += a_ha
            feats.append({
                "type": "Feature",
                "properties": {"nivel_m": nivel, "area_ha": round(a_ha, 2)},
                "geometry": mapping(p),
            })
        area_raster = int(mask.sum()) * px_ha
        dif = 100 * (area_total / area_raster - 1) if area_raster else 0
        print(f"   nível {nivel:4.1f} m | raster {area_raster:8.1f} ha | "
              f"contorno {area_total:8.1f} ha | dif {dif:+.1f}%")

    out = {
        "type": "FeatureCollection",
        "features": feats,
        "metadata": {
            "fonte": ("Vetorizado do MESMO raster HAND embutido na página "
                      "(rasterio.features.shapes, connectivity=8), simplificação "
                      f"Douglas-Peucker de {SIMPLIFY_PX} px SEM suavização gaussiana — "
                      "garante que a mancha desenhada e o valor consultado no clique "
                      "concordem. Ver codigo_python/02_mdt_hand_mancha/gerar_contornos_do_hand.py"),
            "niveis_m": NIVEIS,
            "simplify_px": SIMPLIFY_PX,
            "area_minima_ha": AREA_MIN_HA,
        },
    }
    destino = os.path.join(RAIZ, cfg["saida"])
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"   -> {cfg['saida']}: {len(feats)} feições, "
          f"{os.path.getsize(destino)/1e6:.1f} MB")


def main():
    alvos = sys.argv[1:] or list(CIDADES)
    for cidade in alvos:
        if cidade not in CIDADES:
            print("cidade desconhecida:", cidade); continue
        gerar(cidade, CIDADES[cidade])


if __name__ == "__main__":
    main()
