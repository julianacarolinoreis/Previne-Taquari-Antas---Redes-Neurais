#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Corrige o datum vertical dos MDTs de drone (Muçum + Santa Tereza), de
elipsoidal (h, cru do GNSS/RTK do levantamento) pra ortométrico (H, o
mesmo datum do ANADEM e da régua oficial — Imbituba), usando a grade
oficial de ondulação geoidal do IBGE (ver gerar_grade_geoide.py):

    H = h - N        (N = ondulação geoidal, IBGE hgeoHNOR2020/MAPGEO2015)

Depois de corrigir, REMEDE o offset drone-vs-ANADEM nos mesmos pontos que
o achado original (mesma metodologia: recorta ANADEM na extensão do
drone, reamostra o drone pra grade do ANADEM por 2 métodos — média e
vizinho mais próximo — e compara). Isso valida ao mesmo tempo a grade do
IBGE E a convenção de sinal usada: se a correção estiver certa, o offset
mediano (hoje ~+6,7-6,9 m) deve cair pra perto de zero.

Uso: python codigo_python/02_mdt_hand_mancha/corrigir_datum_drone.py
"""
import os
import numpy as np
import rasterio
import rasterio.windows
from rasterio.warp import reproject, Resampling
from scipy.interpolate import RegularGridInterpolator

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GEOIDE = os.path.join(RAIZ, "assets", "data", "geoide", "ondulacao_geoidal_ibge_hnor2020_imbituba.tif")

CIDADES = {
    "mucum": {
        "drone": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_drone_1m.tif"),
        "anadem": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_anadem_30m.tif"),
        "out": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_drone_1m_ortho.tif"),
    },
    "santa_tereza": {
        "drone": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "mdt", "mdt_santa_tereza_drone_1m.tif"),
        "anadem": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "mdt", "mdt_santa_tereza_anadem_30m.tif"),
        "out": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "mdt", "mdt_santa_tereza_drone_1m_ortho.tif"),
    },
}


def carrega_interpolador_geoide():
    with rasterio.open(GEOIDE) as ds:
        arr = ds.read(1)
        b = ds.bounds
        ny, nx = arr.shape
        lons = b.left + (np.arange(nx) + 0.5) * (b.right - b.left) / nx
        lats = b.top - (np.arange(ny) + 0.5) * (b.top - b.bottom) / ny
    # RegularGridInterpolator exige eixos ascendentes
    lats_asc = lats[::-1]
    arr_asc = arr[::-1, :]
    return RegularGridInterpolator((lats_asc, lons), arr_asc, bounds_error=False, fill_value=None)


def corrige_mdt(path_in, path_out, interp):
    with rasterio.open(path_in) as ds:
        dem = ds.read(1)
        nd = ds.nodata
        profile = ds.profile.copy()
        b = ds.bounds
        ny, nx = dem.shape
        lons = b.left + (np.arange(nx) + 0.5) * (b.right - b.left) / nx
        lats = b.top - (np.arange(ny) + 0.5) * (b.top - b.bottom) / ny
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    pts = np.stack([lat_grid.ravel(), lon_grid.ravel()], axis=1)
    n_vals = interp(pts).reshape(ny, nx).astype("float32")

    valid = dem != nd if nd is not None else np.ones_like(dem, dtype=bool)
    corrigido = dem.copy()
    corrigido[valid] = dem[valid] - n_vals[valid]

    profile.update(tiled=False)
    if "blockxsize" in profile:
        del profile["blockxsize"]
    if "blockysize" in profile:
        del profile["blockysize"]
    with rasterio.open(path_out, "w", **profile) as ds:
        ds.write(corrigido, 1)

    print(f"  N aplicado: min/med/max = {n_vals.min():.2f} / {np.median(n_vals):.2f} / {n_vals.max():.2f} m")
    print(f"  elev antes : {dem[valid].min():.1f}-{dem[valid].max():.1f} m")
    print(f"  elev depois: {corrigido[valid].min():.1f}-{corrigido[valid].max():.1f} m")
    print(f"  escrito {path_out}")


def remede_offset(anadem_path, drone_corrigido_path, nome):
    with rasterio.open(drone_corrigido_path) as ds:
        db = ds.bounds
        crs_fino = ds.crs
        drone = ds.read(1).astype("float64")
        nd_fino = ds.nodata
    drone = np.where(drone == nd_fino, np.nan, drone) if nd_fino is not None else drone

    with rasterio.open(anadem_path) as ad:
        win = rasterio.windows.from_bounds(db.left, db.bottom, db.right, db.top, ad.transform).round_offsets().round_lengths()
        sub_anadem = ad.read(1, window=win).astype("float64")
        nd_a = ad.nodata
        transform_dst = rasterio.windows.transform(win, ad.transform)
        crs_a = ad.crs
    sub_anadem = np.where(sub_anadem == nd_a, np.nan, sub_anadem) if nd_a is not None else sub_anadem

    with rasterio.open(drone_corrigido_path) as ds:
        drone_transform = ds.transform

    out_avg = np.full(sub_anadem.shape, np.nan)
    reproject(source=drone, destination=out_avg, src_transform=drone_transform, src_crs=crs_fino,
              dst_transform=transform_dst, dst_crs=crs_a, resampling=Resampling.average)
    out_nn = np.full(sub_anadem.shape, np.nan)
    reproject(source=drone, destination=out_nn, src_transform=drone_transform, src_crs=crs_fino,
              dst_transform=transform_dst, dst_crs=crs_a, resampling=Resampling.nearest)

    mask = ~np.isnan(sub_anadem) & ~np.isnan(out_avg)
    diff_avg = out_avg[mask] - sub_anadem[mask]
    diff_nn = out_nn[mask] - sub_anadem[mask]
    print(f"{nome} | n={mask.sum()}")
    print(f"  offset (média)   : mediana={np.median(diff_avg):.3f} m | std={np.std(diff_avg):.3f} m")
    print(f"  offset (nearest) : mediana={np.median(diff_nn):.3f} m | std={np.std(diff_nn):.3f} m")
    return float(np.median(diff_avg))


def main():
    interp = carrega_interpolador_geoide()
    residuais = {}
    for cidade, cfg in CIDADES.items():
        print(f"=== {cidade}: corrigindo datum ===")
        corrige_mdt(cfg["drone"], cfg["out"], interp)
        print(f"=== {cidade}: remedindo offset vs ANADEM (pós-correção) ===")
        residuais[cidade] = remede_offset(cfg["anadem"], cfg["out"], cidade)
        print()
    print("=== RESUMO ===")
    for cidade, r in residuais.items():
        print(f"  {cidade}: offset residual (mediana, método média) = {r:+.3f} m")


if __name__ == "__main__":
    main()
