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
import rasterio
import rasterio.features
from rasterio.transform import from_bounds
from scipy import ndimage
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

Image.MAX_IMAGE_PIXELS = None
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

CIDADES = {
    "santa_tereza": {
        "pagina": "santa_tereza_previsao_inundacao.html",
        "saida": "assets/data/santa_tereza_inundacao/contornos_mancha.json",
        "mdt_drone": "assets/data/santa_tereza_inundacao/mdt/mdt_santa_tereza_drone_1m.tif",
    },
    "mucum": {
        "pagina": "mucum_previsao_inundacao.html",
        "saida": "assets/data/mucum_inundacao/contornos_mancha.json",
        "mdt_drone": "assets/data/mucum_inundacao/mdt/mdt_mucum_drone_1m.tif",
    },
}

NIVEIS = [round(x * 0.5, 1) for x in range(0, 51)]   # 0,0 .. 25,0 m (pico 2020 Muçum ~17 m)
SIMPLIFY_PX = 1.0        # tolerância Douglas-Peucker, em pixels (desvio máximo)
AREA_MIN_HA = 0.05       # descarta lascas menores que isso
SO_CONECTADO = True            # desenha apenas o que tem ligação hidráulica com a drenagem
PREENCH_MAX_DRENAGEM = 0.40    # drenagem é alongada; cratera é compacta (medido: rios 8-33%, crateras 45-64%)
AREA_MIN_DRENAGEM_HA = 0.10    # ignora ruído de poucos pixels


def ler_hand(pagina):
    """Lê o payload HAND embutido na página — exatamente o que o popup usa."""
    html = open(os.path.join(RAIZ, pagina), encoding="utf-8").read()
    m = re.search(r'<script id="hand-data" type="application/json">(.*?)</script>', html, re.DOTALL)
    d = json.loads(m.group(1))
    A = np.array(Image.open(io.BytesIO(base64.b64decode(d["hand_png_b64"]))).convert("L"))
    return d, A


def leito_drenagem(A, px_ha, d, janela_drone):
    """Máscara da drenagem real (HAND == 0), descartando crateras do drone.

    O MDT de drone tem crateras de interpolação (buracos da nuvem de pontos,
    tipicamente sobre água/sombra) que descem dezenas de metros abaixo do
    terreno real e recebem HAND 0, virando "poças" desconectadas do rio.

    Dois cuidados aprendidos medindo os dados:

    1. Não basta tomar o MAIOR componente: em Muçum isso descartaria o rio
       Guaporé (30,2 ha, componente separado do Taquari no raster) — e é o
       Guaporé que faz a cidade encher. O critério é a FORMA: drenagem é
       alongada, cratera é compacta (medido: rios 8-33% de preenchimento do
       retângulo envolvente, crateras 45-64%).

    2. O filtro só se aplica DENTRO da área voada. Fora dela o mosaico usa
       ANADEM 30 m, onde não há cratera de fotogrametria e onde trechos largos
       do rio aparecem compactos — descartá-los cortaria planície legítima
       (em Muçum, 83 ha ao sul, fora do voo).
    """
    lbl, n = ndimage.label(A == 0)
    if n == 0:
        return None
    rows, cols = A.shape
    saida = np.zeros_like(lbl, dtype=bool)
    descartadas = 0.0
    for k, fatia in enumerate(ndimage.find_objects(lbl), start=1):
        if fatia is None:
            continue
        mk = (lbl[fatia] == k)
        area_ha = int(mk.sum()) * px_ha
        preench = mk.sum() / mk.size
        # centro do componente em lat/lon
        cy = (fatia[0].start + fatia[0].stop) / 2
        cx = (fatia[1].start + fatia[1].stop) / 2
        lat = d["N"] + (d["S"] - d["N"]) * cy / rows
        lon = d["W"] + (d["E"] - d["W"]) * cx / cols
        no_drone = (janela_drone is not None and
                    janela_drone[0] <= lon <= janela_drone[2] and
                    janela_drone[1] <= lat <= janela_drone[3])
        suspeita = no_drone and area_ha >= AREA_MIN_DRENAGEM_HA and preench > PREENCH_MAX_DRENAGEM
        if suspeita:
            descartadas += area_ha
            continue
        saida[fatia] |= mk
    if descartadas:
        print(f"   crateras descartadas (dentro do voo): {descartadas:.1f} ha")
    return saida if saida.any() else None


def gerar(cidade, cfg):
    d, A = ler_hand(cfg["pagina"])
    rows, cols = A.shape
    px_ha_pre = (abs(d["E"] - d["W"]) * 111320 * np.cos(np.radians((d["S"] + d["N"]) / 2)) / cols) * \
                (abs(d["N"] - d["S"]) * 111320 / rows) / 1e4
    janela = None
    caminho_drone = os.path.join(RAIZ, cfg.get("mdt_drone", ""))
    if cfg.get("mdt_drone") and os.path.exists(caminho_drone):
        with rasterio.open(caminho_drone) as dz:
            b = dz.bounds
            janela = (b.left, b.bottom, b.right, b.top)
        print(f"   voo de drone: {janela[0]:.4f},{janela[1]:.4f} a {janela[2]:.4f},{janela[3]:.4f}")
    rio = leito_drenagem(A, px_ha_pre, d, janela) if SO_CONECTADO else None
    if rio is not None:
        print(f"   drenagem aceita: {int(rio.sum())*px_ha_pre:.1f} ha")
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
        area_bruta = int(mask.sum()) * px_ha
        if rio is not None:
            # mantém só o que encosta na drenagem real (elimina poças de cratera)
            lb, _ = ndimage.label(mask)
            ids = set(np.unique(lb[rio])) - {0}
            mask = np.isin(lb, list(ids))
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
        fant = area_bruta - area_raster
        print(f"   nível {nivel:4.1f} m | conectado {area_raster:8.1f} ha | "
              f"contorno {area_total:8.1f} ha | dif {dif:+.1f}% | "
              f"fantasma removida {fant:6.1f} ha")

    out = {
        "type": "FeatureCollection",
        "features": feats,
        "metadata": {
            "fonte": ("Vetorizado do MESMO raster HAND embutido na página "
                      "(rasterio.features.shapes, connectivity=8), simplificação "
                      f"Douglas-Peucker de {SIMPLIFY_PX} px SEM suavização gaussiana — "
                      "garante que a mancha desenhada e o valor consultado no clique "
                      "concordem. Desenha apenas o que tem ligação hidráulica com o leito "
                      "do rio, descartando as poças criadas por crateras de interpolação do "
                      "MDT de drone. Ver codigo_python/02_mdt_hand_mancha/gerar_contornos_do_hand.py"),
            "niveis_m": NIVEIS,
            "simplify_px": SIMPLIFY_PX,
            "area_minima_ha": AREA_MIN_HA,
            "somente_conectado_ao_rio": SO_CONECTADO,
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
