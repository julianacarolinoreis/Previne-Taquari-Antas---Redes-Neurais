#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Diagnóstico P0: o mínimo do MDT de drone de Santa Tereza (~6 m) entra no
talvegue final do mosaico?

Sem o mosaico 2 m no checkout (gitignored), estima a faixa do talvegue
ANADEM reprojetada sobre o drone ortométrico e reporta:
  - mínimo global do drone
  - mínimo do drone dentro da faixa do talvegue ANADEM
  - se células < 40 m (abaixo da faixa típica ANADEM 49–72 m) contaminam o thal

Uso: python codigo_python/02_mdt_hand_mancha/diagnosticar_talvegue_drone.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from scipy import ndimage

RAIZ = Path(__file__).resolve().parents[2]
OUT = RAIZ / "assets" / "data" / "santa_tereza_inundacao" / "diagnostico_talvegue_drone.json"
ANADEM = RAIZ / "assets" / "data" / "santa_tereza_inundacao" / "mdt" / "mdt_santa_tereza_anadem_30m.tif"
DRONE = RAIZ / "assets" / "data" / "santa_tereza_inundacao" / "mdt" / "mdt_santa_tereza_drone_1m_ortho.tif"
MOSAICO = RAIZ / "assets" / "data" / "santa_tereza_inundacao" / "mdt" / "mdt_santa_tereza_mosaico_2m.tif"


def _read(path):
    with rasterio.open(path) as ds:
        arr = ds.read(1).astype("float64")
        nd = ds.nodata
        if nd is not None:
            arr = np.where(arr == nd, np.nan, arr)
        return arr, ds.transform, ds.crs


def talvegue_anadem(dem_a):
    sr, sc = np.unravel_index(int(np.nanargmin(dem_a)), dem_a.shape)
    filled = np.where(np.isnan(dem_a), np.nanmax(dem_a), dem_a)
    mn = ndimage.minimum_filter(filled, size=9)
    corte = np.nanpercentile(dem_a, 15)
    thal = (filled <= mn + 1.0) & (filled <= corte)
    lbl, _ = ndimage.label(thal)
    return lbl == lbl[sr, sc]


def main():
    dem_a, tr_a, crs_a = _read(ANADEM)
    dem_d, tr_d, crs_d = _read(DRONE)
    thal_a = talvegue_anadem(dem_a)

    band = np.zeros(dem_d.shape, dtype=np.uint8)
    reproject(
        source=thal_a.astype(np.uint8),
        destination=band,
        src_transform=tr_a,
        src_crs=crs_a,
        dst_transform=tr_d,
        dst_crs=crs_d,
        resampling=Resampling.nearest,
    )
    in_thal = band.astype(bool) & ~np.isnan(dem_d)
    drone_valid = dem_d[~np.isnan(dem_d)]
    drone_in_thal = dem_d[in_thal]

    limiar_baixo = 40.0  # abaixo da faixa ANADEM documentada (49–72 m)
    n_baixo_thal = int(np.sum(drone_in_thal < limiar_baixo)) if drone_in_thal.size else 0
    min_global = float(np.nanmin(dem_d))
    min_thal = float(np.min(drone_in_thal)) if drone_in_thal.size else None
    p50_thal = float(np.percentile(drone_in_thal, 50)) if drone_in_thal.size else None

    # Se o mosaico existir, checa o talvegue final (mesmo critério do gerador: p50 na faixa)
    mosaico_info = None
    if MOSAICO.exists():
        dem_m, tr_m, crs_m = _read(MOSAICO)
        band_m = np.zeros(dem_m.shape, dtype=np.uint8)
        reproject(
            source=thal_a.astype(np.uint8),
            destination=band_m,
            src_transform=tr_a,
            src_crs=crs_a,
            dst_transform=tr_m,
            dst_crs=crs_m,
            resampling=Resampling.nearest,
        )
        mask = band_m.astype(bool) & ~np.isnan(dem_m)
        vals = dem_m[mask]
        if vals.size:
            corte = np.percentile(vals, 50)
            thal_m = mask & (dem_m <= corte)
            # maior componente
            lbl, _ = ndimage.label(thal_m)
            # semente = mínimo dentro da faixa
            flat = np.where(mask, dem_m, np.inf)
            sr, sc = np.unravel_index(int(np.argmin(flat)), dem_m.shape)
            if lbl[sr, sc] > 0:
                thal_final = lbl == lbl[sr, sc]
            else:
                # fallback: maior componente
                sizes = np.bincount(lbl.ravel())
                sizes[0] = 0
                thal_final = lbl == int(np.argmax(sizes))
            vals_final = dem_m[thal_final]
            mosaico_info = {
                "min_talvegue_final_m": float(np.min(vals_final)),
                "p50_faixa_anadem_m": float(corte),
                "n_celulas_talvegue": int(thal_final.sum()),
                "n_celulas_abaixo_40m": int(np.sum(vals_final < limiar_baixo)),
                "contamina_talvegue": bool(np.min(vals_final) < limiar_baixo),
            }

    contamina_drone = bool(min_thal is not None and min_thal < limiar_baixo and n_baixo_thal > 0)
    report = {
        "cidade": "santa_tereza",
        "drone_ortho": str(DRONE.relative_to(RAIZ)),
        "anadem": str(ANADEM.relative_to(RAIZ)),
        "mosaico_presente": MOSAICO.exists(),
        "drone_min_global_m": min_global,
        "drone_min_na_faixa_talvegue_anadem_m": min_thal,
        "drone_p50_na_faixa_talvegue_anadem_m": p50_thal,
        "drone_n_celulas_na_faixa": int(in_thal.sum()),
        "drone_n_celulas_faixa_abaixo_40m": n_baixo_thal,
        "limiar_baixo_m": limiar_baixo,
        "contamina_faixa_talvegue_no_drone": contamina_drone,
        "mosaico": mosaico_info,
        "mitigacao_atual": (
            "gerar_mancha_mosaico.py ancora o talvegue na topologia ANADEM e "
            "refina com percentil 50 local — células ~6 m só entram se estiverem "
            "dentro da faixa ANADEM e abaixo do p50 dessa faixa."
        ),
        "recomendacao": (
            "Se mosaico.contamina_talvegue=true: mascarar células drone < 40 m "
            "antes do mosaico/HAND. Se false: pendência documentada, sem impacto "
            "direto no HAND publicado."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
