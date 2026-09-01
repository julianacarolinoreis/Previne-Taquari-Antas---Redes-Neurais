#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refina ruído visual isolado do MDT de Santa Tereza.

O produto original nunca é sobrescrito. O refinamento é deliberadamente
conservador: somente células do drone próximas ao talvegue ANADEM que
divergem da mediana 5x5 por pelo menos 1,5 m e pertencem a componentes
pequenos (até 64 células) são substituídas pela mediana local. Assim,
estruturas contínuas do relevo não são achatadas e nenhum vizinho é
interpolado fora da máscara de pesquisa.

Saídas:
  - mosaico 2 m refinado (gitignored, regenerável);
  - grade RG 10 m refinada usada pelo clique de altitude do site;
  - PNG colorido opcional para inspeção visual no mapa;
  - relatório JSON com hashes, critérios e contagem de células alteradas.

Uso:
  python refinar_mdt_santa_tereza.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.warp import reproject
from scipy import ndimage

from gerar_grade_altitude_web import gerar_grade


ROOT = Path(__file__).resolve().parents[2]
MDT_DIR = ROOT / "assets" / "data" / "santa_tereza_inundacao" / "mdt"
MOSAIC = MDT_DIR / "mdt_santa_tereza_mosaico_2m.tif"
REFINED_MOSAIC = MDT_DIR / "mdt_santa_tereza_mosaico_2m_refinado.tif"
ANADEM = MDT_DIR / "mdt_santa_tereza_anadem_30m.tif"
DRONE = MDT_DIR / "mdt_santa_tereza_drone_1m_ortho.tif"
WEB_PNG = MDT_DIR / "altitude_terreno_10m_refinado.png"
WEB_JSON = MDT_DIR / "altitude_terreno_10m_refinado.json"
VISUAL_PNG = MDT_DIR / "mdt_santa_tereza_10m_refinado_visual.png"
REPORT = ROOT / "assets" / "data" / "santa_tereza_inundacao" / "mdt_refinamento_santa_tereza.json"
ORIGINAL_WEB_JSON = MDT_DIR / "altitude_terreno_10m.json"

THRESHOLD_M = 1.5
MEDIAN_SIZE = 5
MAX_COMPONENT_CELLS = 64
CORRIDOR_DILATION_M = 40.0
MOSAIC_RES_M = 2.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_float(path: Path):
    with rasterio.open(path) as ds:
        arr = ds.read(1).astype("float32")
        nodata = ds.nodata
        if nodata is not None:
            arr[arr == nodata] = np.nan
        return arr, ds.transform, ds.crs, ds.bounds, ds.profile.copy()


def talvegue_anadem(dem: np.ndarray) -> np.ndarray:
    filled = np.where(np.isfinite(dem), dem, np.nanmax(dem))
    local_min = ndimage.minimum_filter(filled, size=9)
    cutoff = np.nanpercentile(dem, 15)
    candidates = (filled <= local_min + 1.0) & (filled <= cutoff)
    labels, _ = ndimage.label(candidates)
    row, col = np.unravel_index(int(np.nanargmin(dem)), dem.shape)
    return labels == labels[row, col]


def visual_png_from_rg(source_png: Path, target_png: Path) -> tuple[float, float]:
    """Converte a grade RG de decímetros em uma imagem transparente colorida."""
    rgba = np.asarray(Image.open(source_png).convert("RGBA"))
    valid = rgba[..., 3] > 0
    dm = rgba[..., 0].astype("uint16") * 256 + rgba[..., 1].astype("uint16")
    values = dm.astype("float32") / 10.0
    lo, hi = np.nanpercentile(values[valid], [2, 98])
    z = np.clip((values - lo) / max(hi - lo, 1e-6), 0.0, 1.0)

    # Azul (vales) -> verde -> amarelo -> laranja -> marrom claro (altos).
    stops = np.array([0.0, 0.18, 0.42, 0.66, 0.84, 1.0], dtype="float32")
    colors = np.array(
        [
            [31, 78, 161],
            [35, 139, 92],
            [151, 190, 54],
            [244, 188, 55],
            [178, 91, 47],
            [222, 218, 208],
        ],
        dtype="float32",
    )
    out = np.empty((*values.shape, 4), dtype=np.uint8)
    for band in range(3):
        out[..., band] = np.interp(z, stops, colors[:, band]).astype(np.uint8)
    out[..., 3] = np.where(valid, 185, 0).astype(np.uint8)
    target_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out, mode="RGBA").save(target_png, optimize=True)
    return float(lo), float(hi)


def main() -> None:
    for path in (MOSAIC, ANADEM, DRONE):
        if not path.exists():
            raise FileNotFoundError(
                f"{path} não existe. Gere primeiro o mosaico 2 m com gerar_mosaico_mdt.py santa_tereza."
            )

    anadem, tr_a, crs_a, _, _ = read_float(ANADEM)

    # O processamento fica restrito ao footprint do drone com uma margem de
    # 40 m; o restante do mosaico é copiado byte a byte para o produto novo.
    with rasterio.open(MOSAIC) as src:
        with rasterio.open(DRONE) as drone_ds:
            db = drone_ds.bounds
            margin_deg = CORRIDOR_DILATION_M / 111320.0
            bounds = rasterio.coords.BoundingBox(
                db.left - margin_deg,
                db.bottom - margin_deg,
                db.right + margin_deg,
                db.top + margin_deg,
            )
        window = rasterio.windows.from_bounds(*bounds, transform=src.transform)
        window = window.round_offsets().round_lengths()
        crop = src.read(1, window=window).astype("float32")
        crop_transform = src.window_transform(window)
        mosaic_profile = src.profile.copy()

    # Âncoras independentes: talvegue do ANADEM e footprint válido do drone.
    talweg = talvegue_anadem(anadem)
    talweg_crop = np.zeros(crop.shape, dtype=np.uint8)
    reproject(
        talweg.astype(np.uint8),
        talweg_crop,
        src_transform=tr_a,
        src_crs=crs_a,
        dst_transform=crop_transform,
        dst_crs=mosaic_profile["crs"],
        resampling=Resampling.nearest,
    )
    with rasterio.open(DRONE) as drone_ds:
        drone_valid = np.zeros(crop.shape, dtype=np.uint8)
        reproject(
            (drone_ds.read_masks(1) > 0).astype(np.uint8),
            drone_valid,
            src_transform=drone_ds.transform,
            src_crs=drone_ds.crs,
            dst_transform=crop_transform,
            dst_crs=mosaic_profile["crs"],
            resampling=Resampling.nearest,
        )

    corridor = ndimage.binary_dilation(
        talweg_crop.astype(bool),
        iterations=max(1, round(CORRIDOR_DILATION_M / MOSAIC_RES_M)),
    ) & drone_valid.astype(bool)
    valid = np.isfinite(crop)
    local_median = ndimage.median_filter(crop, size=MEDIAN_SIZE, mode="nearest")
    deviation = np.abs(crop - local_median)
    candidates = corridor & valid & np.isfinite(local_median) & (deviation >= THRESHOLD_M)
    labels, n_labels = ndimage.label(candidates, structure=np.ones((3, 3), dtype=np.uint8))
    sizes = np.bincount(labels.ravel(), minlength=n_labels + 1)
    repair = candidates & (sizes[labels] <= MAX_COMPONENT_CELLS)

    refined_crop = crop.copy()
    refined_crop[repair] = local_median[repair]
    changed_values = refined_crop[repair] - crop[repair]

    # O produto refinado é novo; a entrada permanece intacta.
    shutil.copy2(MOSAIC, REFINED_MOSAIC)
    with rasterio.open(REFINED_MOSAIC, "r+") as dst:
        dst.write(refined_crop.astype("float32"), 1, window=window)
        dst.update_tags(
            product_type="research_visual_refinement",
            method="5x5 median; isolated deviations only inside ANADEM talweg corridor",
            threshold_m=str(THRESHOLD_M),
            max_component_cells=str(MAX_COMPONENT_CELLS),
            source_mosaic=MOSAIC.name,
            hydrologic_use="visualization_only_pending_independent_validation",
        )

    gerar_grade(REFINED_MOSAIC, WEB_PNG, WEB_JSON, passo=5)
    metadata = json.loads(WEB_JSON.read_text(encoding="utf-8"))
    original_meta = json.loads(ORIGINAL_WEB_JSON.read_text(encoding="utf-8"))
    metadata.update(
        {
            "product_type": "research_visual_refinement",
            "original_web_grade": ORIGINAL_WEB_JSON.name,
            "source_mosaic": MOSAIC.name,
            "source_mosaic_sha256": sha256(MOSAIC),
            "refined_mosaic": REFINED_MOSAIC.name,
            "refined_mosaic_sha256": sha256(REFINED_MOSAIC),
            "method": "mediana local 5x5 somente no corredor do talvegue ANADEM; desvios isolados >= 1,5 m",
            "threshold_m": THRESHOLD_M,
            "max_component_cells": MAX_COMPONENT_CELLS,
            "corridor_dilation_m": CORRIDOR_DILATION_M,
            "changed_cells_2m": int(repair.sum()),
            "candidate_cells_2m": int(candidates.sum()),
            "changed_abs_mean_m": float(np.mean(np.abs(changed_values))) if changed_values.size else 0.0,
            "changed_abs_max_m": float(np.max(np.abs(changed_values))) if changed_values.size else 0.0,
            "validation_status": "pending_independent_water_mask_and_footprint_validation",
            "hydrologic_use": "visualization_only",
            "original_web_grade_sha256": sha256(MDT_DIR / original_meta["png"]),
        }
    )
    WEB_JSON.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lo, hi = visual_png_from_rg(WEB_PNG, VISUAL_PNG)

    report = {
        "cidade": "santa_tereza",
        "produto": "mdt_visual_refinado",
        "status": "research_visual_refinement_ready",
        "source_mosaic": MOSAIC.name,
        "refined_mosaic": REFINED_MOSAIC.name,
        "original_web_grade": ORIGINAL_WEB_JSON.name,
        "refined_web_grade": WEB_JSON.name,
        "visual_png": VISUAL_PNG.name,
        "criterios": {
            "janela_mediana": f"{MEDIAN_SIZE}x{MEDIAN_SIZE}",
            "limiar_desvio_m": THRESHOLD_M,
            "componente_maximo_celulas": MAX_COMPONENT_CELLS,
            "corredor_talvegue_m": CORRIDOR_DILATION_M,
            "sem_interpolacao_fora_da_mascara": True,
        },
        "candidatas_2m": int(candidates.sum()),
        "celulas_corrigidas_2m": int(repair.sum()),
        "alteracao_media_abs_m": float(np.mean(np.abs(changed_values))) if changed_values.size else 0.0,
        "alteracao_max_abs_m": float(np.max(np.abs(changed_values))) if changed_values.size else 0.0,
        "visual_scale_percentile_m": [lo, hi],
        "source_mosaic_sha256": sha256(MOSAIC),
        "refined_mosaic_sha256": sha256(REFINED_MOSAIC),
        "validation_status": "pending_independent_water_mask_and_footprint_validation",
        "hydrologic_use": "visualization_only",
        "note": "O MDT original e a mancha HAND publicada não são sobrescritos por este refinamento visual.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
