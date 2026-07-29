#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Recorta a grade oficial de ondulação geoidal do IBGE (produto hgeoHNOR2020,
derivado do modelo MAPGEO2015, referenciado ao datum vertical de Imbituba —
o datum vertical padrão do Brasil, válido pra RS) pra um GeoTIFF pequeno
cobrindo Muçum + Santa Tereza, com margem.

FONTE (baixada manualmente, com autorização explícita — ver commit):
  https://geoftp.ibge.gov.br/modelos_digitais_de_superficie/modelo_de_ondulacao_geoidal/grades_hgeoHNOR2020/hgeoHNOR2020__grades-IMBITUBA.zip
  Arquivo usado: hgeoHNOR2020__IMBITUBA__fator-conversao.txt
  Formato: texto, 3 colunas (longitude E 0-360°, latitude, N em metros),
  grade regular 5' (540 x 492 pontos), cobrindo 75°W-30°W / 6°N-35°S.
  "Fator de conversão" = ondulação geoidal N. Convenção padrão de geodésia:
    h (elipsoidal) = H (ortométrica) + N   =>   H = h - N

Não versiona a grade nacional inteira (9,5 MB de texto) — só o recorte
regional em GeoTIFF (float32, pequeno). Rodar de novo exige o .txt bruto
baixado à parte (não incluído no repo); ver ARQUIVO_BRUTO abaixo.

Uso: python codigo_python/02_mdt_hand_mancha/gerar_grade_geoide.py <caminho_para_fator-conversao.txt>
"""
import os
import sys
import numpy as np
import rasterio
from rasterio.transform import from_origin

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(RAIZ, "assets", "data", "geoide", "ondulacao_geoidal_ibge_hnor2020_imbituba.tif")

# bbox de interesse (Mucum + Santa Tereza, com margem), em longitude -180..180
BBOX_W, BBOX_S, BBOX_E, BBOX_N = -52.2, -29.5, -51.4, -28.8


def main():
    if len(sys.argv) < 2:
        raise SystemExit("uso: gerar_grade_geoide.py <caminho_para_fator-conversao.txt>")
    txt_path = sys.argv[1]

    data = np.loadtxt(txt_path)
    lon360, lat, n = data[:, 0], data[:, 1], data[:, 2]
    lon = np.where(lon360 > 180, lon360 - 360, lon360)

    # eixos únicos, SEMPRE ordenados ascendentemente por np.unique — não presume
    # nenhuma ordem específica no arquivo bruto (varredura por scatter-fill, não reshape)
    lons_sorted, lon_idx = np.unique(lon, return_inverse=True)
    lats_sorted, lat_idx = np.unique(lat, return_inverse=True)
    assert len(lons_sorted) * len(lats_sorted) == len(data), "grade não é regular/completa"

    grid = np.full((len(lats_sorted), len(lons_sorted)), np.nan)
    grid[lat_idx, lon_idx] = n
    assert not np.isnan(grid).any(), "grade tem buracos após o scatter-fill"

    mask_lon = (lons_sorted >= BBOX_W) & (lons_sorted <= BBOX_E)
    mask_lat = (lats_sorted >= BBOX_S) & (lats_sorted <= BBOX_N)
    sub = grid[np.ix_(mask_lat, mask_lon)]
    sub_lons = lons_sorted[mask_lon]
    sub_lats = lats_sorted[mask_lat]
    print(f"recorte: {sub.shape[0]}x{sub.shape[1]} pontos | lon {sub_lons.min():.4f}..{sub_lons.max():.4f} | lat {sub_lats.min():.4f}..{sub_lats.max():.4f}")
    print(f"N min/med/max: {sub.min():.2f} / {np.median(sub):.2f} / {sub.max():.2f} m")

    # GeoTIFF top-down (linha 0 = norte)
    sub_topdown = sub[::-1, :]
    step_lon = float(np.median(np.diff(sub_lons)))
    step_lat = float(np.median(np.diff(sub_lats)))
    transform = from_origin(sub_lons.min() - step_lon / 2, sub_lats.max() + step_lat / 2, step_lon, step_lat)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    profile = dict(
        driver="GTiff", dtype="float32", count=1,
        height=sub_topdown.shape[0], width=sub_topdown.shape[1],
        crs="EPSG:4326", transform=transform, nodata=-9999.0,
        compress="LZW", tiled=False,
    )
    with rasterio.open(OUT, "w", **profile) as ds:
        ds.write(sub_topdown.astype("float32"), 1)
    print(f"escrito {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
