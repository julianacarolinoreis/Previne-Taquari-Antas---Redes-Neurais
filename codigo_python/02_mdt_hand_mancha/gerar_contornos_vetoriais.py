#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Gera o CONTORNO VETORIAL da mancha de inundação (polígono real, não raster
pintado pixel a pixel) a partir do HAND do mosaico de 2 m — um por nível de
rio, mesma faixa/passo do slider do site (0 a 15 m, passo 0,5 m).

POR QUE (decisão da pessoa, 2026-07-29): o raster/canvas pintado pixel a
pixel (L.imageOverlay) mostrava borda "em escada" ao dar zoom próximo — não
por falta de resolução no CÁLCULO (confirmado: o HAND bruto varia suave,
decímetro a decímetro, célula a célula, dentro da área do drone), mas pela
ETAPA DE DESENHO: threshold binário por pixel sem nenhuma suavização (o
supersampling que suavizava visualmente o raster antigo de 30 m foi
desligado pra corrigir o bug do canvas estourando limite do navegador — ver
commit anterior). Solução: polígono vetorial de verdade, extraído do
raster (não desenhado célula a célula), que fica reaproveitável também pra
teste ponto-dentro-do-polígono (mapa casa a casa, próxima etapa).

MÉTODO
------
1. Máscara conectada ao talvegue (mesmo critério de sempre — hand<=nível E
   conectado à rede de drenagem validada, ancorada no ANADEM; ver
   gerar_mancha_mosaico.py) — não o "hand<=nível bruto" que o raster antigo
   desenhava (esse incluía poças isoladas sem ligação com o rio; o contorno
   vetorial já nasce mais limpo por causa disso, então a área do polígono
   pode diferir um pouco da área que o raster mostrava).
2. rasterio.features.shapes() poligoniza a máscara célula a célula — sai
   com milhares de vértices e cantos de 90° (rastro do pixel), ~1 MB por
   nível sem tratamento.
3. shapely.simplify(tolerância ~2 px = 4 m, preserve_topology=True) —
   remove o zigue-zague do traçado pixel a pixel (ruído da rasterização,
   não detalhe real: nada mais fino que 1 pixel existe no dado de qualquer
   jeito). Sozinho já derruba pra ~100 KB/nível preservando a área a menos
   de 0,15%.
4. Suavização GAUSSIANA das coordenadas (scipy.ndimage.gaussian_filter1d,
   modo 'wrap' por ser um anel fechado) — trocou o Chaikin (corner-cutting)
   depois de comparar visualmente (renderizado e conferido por imagem, não
   só por número): Chaikin arredonda cada canto individualmente, mas num
   contorno com serrilhado de alta frequência (o "dente de serra" que sobra
   da rasterização) ele só REESCALA o serrilhado pra um tamanho menor —
   continua parecendo grosseiro de perto, não importa quantas iterações.
   Um filtro gaussiano de verdade (passa-baixa nas coordenadas x/y como se
   fossem sinais 1D) remove o ruído de alta frequência mantendo a forma
   grande do polígono — visivelmente mais suave no mesmo teste, e ainda por
   cima gera MENOS vértices (não duplica a cada iteração feito o Chaikin).

Uso: python codigo_python/02_mdt_hand_mancha/gerar_contornos_vetoriais.py [mucum|santa_tereza]
"""
import os
import sys
import json
import numpy as np
from scipy import ndimage
from scipy.ndimage import gaussian_filter1d
from rasterio.features import shapes
from shapely.geometry import shape, mapping, Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely.validation import make_valid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gerar_mancha_mosaico import CIDADES, le, talvegue_anadem, talvegue_mosaico  # noqa: E402

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
NIVEIS_M = [round(x, 1) for x in np.arange(0, 15.5, 0.5)]
TOL_PX = 2.0
SIGMA = 2.0
PRECISAO_DECIMAIS = 6

OUT = {
    "mucum": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "contornos_mancha.json"),
    "santa_tereza": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "contornos_mancha.json"),
}


def smooth_ring(coords, sigma):
    coords = list(coords)
    if coords[0] == coords[-1]:
        coords = coords[:-1]
    if len(coords) < 5:
        coords.append(coords[0])
        return coords
    arr = np.array(coords)
    xs = gaussian_filter1d(arr[:, 0], sigma=sigma, mode="wrap")
    ys = gaussian_filter1d(arr[:, 1], sigma=sigma, mode="wrap")
    out = list(zip(xs.tolist(), ys.tolist()))
    out.append(out[0])
    return out


def suaviza(poly, tol, sigma):
    simp = poly.simplify(tol, preserve_topology=True)
    if simp.is_empty:
        return None

    def proc(p):
        ext = smooth_ring(list(p.exterior.coords), sigma)
        ints = [smooth_ring(list(r.coords), sigma) for r in p.interiors if len(r.coords) > 4]
        pol = Polygon(ext, ints)
        return pol if pol.is_valid else make_valid(pol)

    if simp.geom_type == "Polygon":
        out = proc(simp)
    else:
        outs = [proc(g) for g in simp.geoms if not g.is_empty]
        out = unary_union(outs)
    return out


def arredonda_geom(geom_mapping, casas):
    def rr(coords):
        return [tuple(round(c, casas) for c in pt) for pt in coords]

    def rr_poly(coords):
        return [rr(anel) for anel in coords]

    t = geom_mapping["type"]
    if t == "Polygon":
        return {"type": t, "coordinates": rr_poly(geom_mapping["coordinates"])}
    if t == "MultiPolygon":
        return {"type": t, "coordinates": [rr_poly(p) for p in geom_mapping["coordinates"]]}
    return geom_mapping


def gera(cidade):
    cfg = CIDADES[cidade]
    print(f"=== {cidade} ===")
    dem_a, transform_a, crs_a, _ = le(cfg["anadem"])
    thal_a = talvegue_anadem(dem_a)

    dem, transform_f, crs_f, b = le(cfg["mosaico"])
    thal = talvegue_mosaico(dem, transform_f, crs_f, thal_a, transform_a, crs_a)
    px_deg = abs(transform_f.a)
    tol = px_deg * TOL_PX

    _, (ri, rj) = ndimage.distance_transform_edt(~thal, return_indices=True)
    hand = dem - dem[ri, rj]
    hand[hand < 0] = 0
    print(f"HAND pronto | talvegue {int(thal.sum())} cel")

    features = []
    for nivel in NIVEIS_M:
        lvl_m = nivel
        mask = hand <= lvl_m
        lbl, _ = ndimage.label(mask)
        keep = set(np.unique(lbl[thal])) - {0}
        if not keep:
            continue
        mask_conn = np.isin(lbl, list(keep))
        polys = [shape(geom) for geom, _val in shapes(mask_conn.astype(np.uint8), mask=mask_conn, transform=transform_f)]
        if not polys:
            continue
        u = unary_union(polys)
        out = suaviza(u, tol, SIGMA)
        if out is None or out.is_empty:
            continue
        geom = arredonda_geom(mapping(out), PRECISAO_DECIMAIS)
        area_ha = out.area * 111320 * 111320 * abs(np.cos(np.radians((b.bottom + b.top) / 2))) / 1e4
        features.append({
            "type": "Feature",
            "properties": {"nivel_m": lvl_m, "area_ha": round(area_ha, 1)},
            "geometry": geom,
        })
        print(f"  nivel {lvl_m:4.1f} m -> {area_ha:8.1f} ha")

    fc = {"type": "FeatureCollection", "features": features,
          "metadata": {"fonte": "HAND do mosaico 2m (drone corrigido + ANADEM), contorno vetorial "
                                 f"(rasterio.features.shapes + simplify ~{TOL_PX}px + suavização gaussiana sigma={SIGMA})"}}
    out_path = OUT[cidade]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))
    tam_kb = os.path.getsize(out_path) / 1024
    print(f"escrito {os.path.relpath(out_path, RAIZ)} ({tam_kb:.0f} KB, {len(features)} níveis)")
    print()


if __name__ == "__main__":
    alvo = sys.argv[1] if len(sys.argv) > 1 else None
    for cidade in ([alvo] if alvo else CIDADES.keys()):
        gera(cidade)
