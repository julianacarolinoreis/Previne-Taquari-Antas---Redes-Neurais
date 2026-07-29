#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Monta o MDT "mosaico fino": drone (0,5 m, já corrigido de datum — ver
corrigir_datum_drone.py) no centro urbano + ANADEM (30 m) reamostrado nas
bordas, cobrindo a MESMA extensão que o ANADEM cobre hoje (não encolhe a
área processada). Resolução de saída: 2 m — ~15x mais fino que os 30 m
atuais, mas ainda viável em memória/tempo (0,5 m em toda a extensão do
ANADEM geraria rasters de centenas de milhões de pixels).

Método:
  1. Grade de destino em 2 m, cobrindo os bounds do ANADEM inteiro.
  2. ANADEM reamostrado pra essa grade (bilinear — só preenchimento
     geométrico, não cria detalhe novo).
  3. Drone corrigido reamostrado pra essa grade (média — é downsampling
     de verdade, de 0,5 m pra 2 m).
  4. Mistura com pluma suave de ~40 m na borda da cobertura do drone
     (distance transform dentro da máscara válida do drone), pra não virar
     degrau na costura. Longe da borda: 100% drone dentro, 100% ANADEM
     fora.

Uso: python codigo_python/02_mdt_hand_mancha/gerar_mosaico_mdt.py [mucum|santa_tereza]
"""
import os
import sys
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds
from scipy import ndimage
from math import cos, radians

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RES_M = 2.0
BLEND_M = 40.0

CIDADES = {
    "mucum": {
        "anadem": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_anadem_30m.tif"),
        "drone_ortho": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_drone_1m_ortho.tif"),
        "out": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_mosaico_2m.tif"),
    },
    "santa_tereza": {
        "anadem": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "mdt", "mdt_santa_tereza_anadem_30m.tif"),
        "drone_ortho": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "mdt", "mdt_santa_tereza_drone_1m_ortho.tif"),
        "out": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "mdt", "mdt_santa_tereza_mosaico_2m.tif"),
    },
}


def monta(cidade):
    cfg = CIDADES[cidade]
    print(f"=== {cidade} ===")
    with rasterio.open(cfg["anadem"]) as ad:
        b = ad.bounds
        crs = ad.crs
        nd_a = ad.nodata
        anadem = ad.read(1)
        transform_a = ad.transform

    lat0 = (b.bottom + b.top) / 2
    deg_por_m_lon = 1 / (111320 * cos(radians(lat0)))
    deg_por_m_lat = 1 / 111320
    px_x = RES_M * deg_por_m_lon
    px_y = RES_M * deg_por_m_lat
    ncols = int(round((b.right - b.left) / px_x))
    nrows = int(round((b.top - b.bottom) / px_y))
    transform_dst = from_bounds(b.left, b.bottom, b.right, b.top, ncols, nrows)
    print(f"grade destino: {ncols}x{nrows} px @ {RES_M} m ({ncols*nrows/1e6:.1f} M px)")

    anadem_fino = np.full((nrows, ncols), np.nan, dtype="float32")
    reproject(source=anadem, destination=anadem_fino, src_transform=transform_a, src_crs=crs,
              src_nodata=nd_a, dst_transform=transform_dst, dst_crs=crs, dst_nodata=np.nan,
              resampling=Resampling.bilinear)

    with rasterio.open(cfg["drone_ortho"]) as dd:
        drone = dd.read(1)
        transform_d = dd.transform
        crs_d = dd.crs
        nd_d = dd.nodata
    drone_fino = np.full((nrows, ncols), np.nan, dtype="float32")
    reproject(source=drone, destination=drone_fino, src_transform=transform_d, src_crs=crs_d,
              src_nodata=nd_d, dst_transform=transform_dst, dst_crs=crs, dst_nodata=np.nan,
              resampling=Resampling.average)

    mask_drone = ~np.isnan(drone_fino)
    cobertura_pct = 100 * mask_drone.sum() / mask_drone.size
    print(f"cobertura do drone na grade do mosaico: {cobertura_pct:.1f}%")

    blend_px = max(1, int(round(BLEND_M / RES_M)))
    dist_dentro = ndimage.distance_transform_edt(mask_drone)
    peso = np.clip(dist_dentro / blend_px, 0, 1).astype("float32")
    peso[~mask_drone] = 0.0

    mosaico = np.where(mask_drone, drone_fino * peso + anadem_fino * (1 - peso), anadem_fino)
    buracos = np.isnan(mosaico)
    if buracos.any():
        print(f"AVISO: {int(buracos.sum())} px sem dado (nem ANADEM nem drone) — preenchendo com vizinho mais próximo")
        idx = ndimage.distance_transform_edt(buracos, return_distances=False, return_indices=True)
        mosaico = mosaico[tuple(idx)]

    print(f"elev mosaico: {np.nanmin(mosaico):.1f}-{np.nanmax(mosaico):.1f} m")

    profile = dict(driver="GTiff", dtype="float32", count=1, height=nrows, width=ncols,
                   crs=crs, transform=transform_dst, nodata=-9999.0, compress="LZW", tiled=False)
    with rasterio.open(cfg["out"], "w", **profile) as ds:
        ds.write(mosaico.astype("float32"), 1)
    tam_mb = os.path.getsize(cfg["out"]) / 1e6
    print(f"escrito {cfg['out']} ({tam_mb:.1f} MB)")
    print()


if __name__ == "__main__":
    alvo = sys.argv[1] if len(sys.argv) > 1 else None
    for cidade in ([alvo] if alvo else CIDADES.keys()):
        monta(cidade)
