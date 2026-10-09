# -*- coding: utf-8 -*-
"""Raster da cota que alaga cada pixel (m HAND), para o roteamento por nível.

Mesmo critério de contornos_mancha.json (gerar_contornos_vetoriais.py): um
pixel alaga no nível L quando HAND <= L e está ligado ao talvegue por pixels
com HAND <= L. Aqui o resultado vira um raster só (o menor L de cada pixel),
de 0 a 25 m em passos de 0,1 m — os contornos param em 15 m, abaixo do
recorde de 2024 em Santa Tereza (HAND ~21,8 m).

Saída: assets/data/rota_fuga/cota_alaga_<cidade>.tif, uint16 em decímetros,
recortado na área das vias do gerador de rotas.
  NAO_ALAGA (65535) = não alaga até 25 m.

  python codigo_python/09_rota_fuga/gerar_cota_alaga.py [mucum|santa_tereza]
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.windows import from_bounds
from scipy import ndimage

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(AQUI, "..", "02_mdt_hand_mancha"))
from gerar_mancha_mosaico import CIDADES as MOSAICO, le, talvegue_anadem, talvegue_mosaico  # noqa: E402
import gerar_rota_fuga_ruas as rf_mod  # noqa: E402

NIVEL_MAX_DM = 250
NAO_ALAGA = 65535
FOLGA_GRAUS = 0.005
PASSO_GRAUS = 0.00002  # ~2 m, abaixo da resolução dos contornos LiDAR (~10 m)


def caminho(slug):
    return os.path.join(rf_mod.RAIZ, "assets", "data", "rota_fuga", f"cota_alaga_{slug}.tif")


def gera_de_contornos(slug):
    """Menor nível dos contornos (contornos_mancha.json) que cobre cada pixel.

    Para cidade cujo zero da régua foi calibrado sobre outra superfície HAND
    (Santa Tereza: LiDAR), que não está no repositório como raster.
    """
    cfg = rf_mod.CIDADES[slug]
    t0 = time.time()
    feats = json.load(open(cfg["contornos"], encoding="utf-8"))["features"]
    feats = sorted(feats, key=lambda f: -f["properties"]["nivel_m"])
    bb, m = cfg["bbox"], rf_mod.MARGEM_VIAS_GRAUS + FOLGA_GRAUS
    w, s, e, n = bb["W"] - m, bb["S"] - m, bb["E"] + m, bb["N"] + m
    largura, altura = round((e - w) / PASSO_GRAUS), round((n - s) / PASSO_GRAUS)
    tr = from_origin(w, n, PASSO_GRAUS, PASSO_GRAUS)
    cota = rasterize(((f["geometry"], int(round(f["properties"]["nivel_m"] * 10))) for f in feats
                      if f["properties"]["nivel_m"] * 10 <= NIVEL_MAX_DM),
                     out_shape=(altura, largura), transform=tr, fill=NAO_ALAGA, dtype="uint16")
    out = caminho(slug)
    with rasterio.open(out, "w", driver="GTiff", height=altura, width=largura, count=1, dtype="uint16",
                       crs="EPSG:4326", transform=tr, compress="deflate", predictor=2, tiled=True) as ds:
        ds.write(cota, 1)
        ds.update_tags(unidade="decimetro HAND", nao_alaga=str(NAO_ALAGA), nivel_max_m=str(NIVEL_MAX_DM / 10),
                       fonte=os.path.relpath(cfg["contornos"], rf_mod.RAIZ))
    print(f"{slug}: {len(feats)} contornos -> {out} ({largura}x{altura}, "
          f"{int((cota != NAO_ALAGA).sum())} pixels alagáveis, {time.time() - t0:.0f} s)")


def gera(slug):
    if rf_mod.CIDADES[slug].get("cota_de_contornos"):
        return gera_de_contornos(slug)
    cfg, mos = rf_mod.CIDADES[slug], MOSAICO[slug]
    t0 = time.time()
    dem_a, tr_a, crs_a, _ = le(mos["anadem"])
    thal_a = talvegue_anadem(dem_a)
    dem, tr, crs, _b = le(mos["mosaico"])
    thal = talvegue_mosaico(dem, tr, crs, thal_a, tr_a, crs_a)
    _, (ri, rj) = ndimage.distance_transform_edt(~thal, return_indices=True)
    hand = dem - dem[ri, rj]
    del ri, rj
    hand[hand < 0] = 0
    hand_dm = np.round(hand * 10.0).astype(np.int32)
    del hand
    print(f"{slug}: HAND pronto ({dem.shape[1]}x{dem.shape[0]}, {time.time() - t0:.0f} s)")

    cota = np.full(dem.shape, NAO_ALAGA, dtype=np.uint16)
    for nv in range(0, NIVEL_MAX_DM + 1):
        mask = hand_dm <= nv
        lbl, _ = ndimage.label(mask)
        keep = np.unique(lbl[thal])
        keep = keep[keep > 0]
        if keep.size:
            novo = np.isin(lbl, keep) & (cota == NAO_ALAGA)
            cota[novo] = nv
        if nv % 25 == 0:
            print(f"  {nv / 10:4.1f} m: {int((cota != NAO_ALAGA).sum())} pixels ({time.time() - t0:.0f} s)")

    bb, m = cfg["bbox"], rf_mod.MARGEM_VIAS_GRAUS + FOLGA_GRAUS
    win = from_bounds(bb["W"] - m, bb["S"] - m, bb["E"] + m, bb["N"] + m, tr).round_offsets().round_lengths()
    r0, c0 = max(0, win.row_off), max(0, win.col_off)
    r1, c1 = min(cota.shape[0], win.row_off + win.height), min(cota.shape[1], win.col_off + win.width)
    recorte = cota[r0:r1, c0:c1]
    tr_rec = rasterio.windows.transform(rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0), tr)
    out = caminho(slug)
    with rasterio.open(out, "w", driver="GTiff", height=recorte.shape[0], width=recorte.shape[1], count=1,
                       dtype="uint16", crs=crs, transform=tr_rec, compress="deflate", predictor=2,
                       tiled=True) as ds:
        ds.write(recorte, 1)
        ds.update_tags(unidade="decimetro HAND", nao_alaga=str(NAO_ALAGA), nivel_max_m=str(NIVEL_MAX_DM / 10))
    print(f"-> {out} ({os.path.getsize(out) / 1e6:.1f} MB, {time.time() - t0:.0f} s)")


if __name__ == "__main__":
    alvo = sys.argv[1] if len(sys.argv) > 1 else None
    for slug in ([alvo] if alvo else rf_mod.CIDADES):
        gera(slug)
