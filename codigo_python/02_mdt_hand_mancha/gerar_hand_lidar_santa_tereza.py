#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera o HAND de Santa Tereza a partir dos rasters novos de campo.

O produto publicado é deliberadamente restrito ao rio principal. Os arquivos
de entrada são insumos hidrológicos, não um HAND pronto:

  CLIP_MOSAICO_LIDAR_RS.tif       terreno
  FILL_CLIP_MOSAICO_LIDAR_RS.tif  terreno preenchido
  FLOWDIR_CLIP_MOSAICO_LIDAR_RS.tif
  FLOWACC_CLIP_MOSAICO_LIDAR_RS.tif

O rio principal é extraído por acumulação de fluxo >= 50.000.000 células finas
(aproximadamente 50 km² de área contribuinte no raster de 1 m). O terreno é
reamostrado para 5 m apenas para o payload leve do navegador; a calibração
vertical permanece separada: régua 1,60 m = HAND 0.

Uso:
  python gerar_hand_lidar_santa_tereza.py
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.features import shapes
from rasterio.transform import array_bounds
from rasterio.warp import reproject, transform_bounds
from pyproj import Transformer
from scipy import ndimage
from shapely.geometry import mapping, shape
from shapely.ops import transform as transform_geometry, unary_union
from shapely.validation import make_valid


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = Path(r"D:\PREVINE\hand\santa tereza")
PAGE = ROOT / "santa_tereza_previsao_inundacao.html"
DIAGNOSTIC = ROOT / "assets" / "data" / "santa_tereza_inundacao" / "hand_lidar_5m_diagnostic.json"
CONTOURS = ROOT / "assets" / "data" / "santa_tereza_inundacao" / "contornos_mancha.json"
FACTOR = 5
FLOWACC_THRESHOLD_FINE_CELLS = 50_000_000
MAX_HAND_M = 25.0
HAND_ZERO_CM = 160
CONTOUR_LEVELS_M = [round(x, 1) for x in np.arange(0, 15.01, 0.1)]
CONTOUR_FACTOR = 2


def read_dem(path: Path) -> tuple[np.ndarray, rasterio.Affine, object, rasterio.coords.BoundingBox, float]:
    with rasterio.open(path) as ds:
        out_h = (ds.height + FACTOR - 1) // FACTOR
        out_w = (ds.width + FACTOR - 1) // FACTOR
        dem = ds.read(1, out_shape=(out_h, out_w), resampling=Resampling.average, masked=True)
        dem = dem.filled(np.nan).astype("float32")
        transform = ds.transform * ds.transform.scale(ds.width / out_w, ds.height / out_h)
        return dem, transform, ds.crs, ds.bounds, float(ds.res[0])


def read_flowacc(path: Path, shape: tuple[int, int], transform, crs, nodata: float | None) -> np.ndarray:
    flowacc = np.zeros(shape, dtype="float32")
    with rasterio.open(path) as ds:
        reproject(
            rasterio.band(ds, 1),
            flowacc,
            src_transform=ds.transform,
            src_crs=ds.crs,
            dst_transform=transform,
            dst_crs=crs,
            resampling=Resampling.max,
            src_nodata=nodata if nodata is not None else ds.nodata,
            dst_nodata=0,
        )
    flowacc[~np.isfinite(flowacc) | (flowacc > 1e20)] = 0
    return flowacc


def inject_payload(page: Path, payload: dict) -> None:
    html = page.read_text(encoding="utf-8")
    pattern = r'<script id="hand-data" type="application/json">.*?</script>'
    replacement = '<script id="hand-data" type="application/json">' + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ) + "</script>"
    html2, count = re.subn(pattern, replacement, html, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"hand-data não encontrado em {page}")
    page.write_text(html2, encoding="utf-8")


def write_contours(hand: np.ndarray, transform, crs, output: Path) -> dict:
    """Escreve contornos cumulativos do buffer do rio principal em WGS84."""
    to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    # O HAND consultado no popup permanece em 5 m. Para o vetor desenhado no
    # mapa, 10 m é suficiente e reduz bastante o payload público.
    hand_vector = hand[::CONTOUR_FACTOR, ::CONTOUR_FACTOR]
    vector_transform = transform * transform.scale(CONTOUR_FACTOR, CONTOUR_FACTOR)
    features = []
    for level in CONTOUR_LEVELS_M:
        mask = np.isfinite(hand_vector) & (hand_vector <= level)
        if not mask.any():
            continue
        polygons = [shape(geom) for geom, value in shapes(mask.astype(np.uint8), mask=mask, transform=vector_transform) if value]
        if not polygons:
            continue
        geom_utm = unary_union(polygons).buffer(0)
        if geom_utm.is_empty:
            continue
        # O vetor é uma camada de visualização; a tolerância de 30 m remove o
        # serrilhado de pixel sem prometer uma precisão cartográfica inexistente.
        geom_utm = geom_utm.simplify(30.0, preserve_topology=True)
        if not geom_utm.is_valid:
            geom_utm = make_valid(geom_utm)
        geom_wgs84 = transform_geometry(to_wgs84, geom_utm)
        features.append({
            "type": "Feature",
            "properties": {
                "nivel_m": level,
                "area_ha": round(float(geom_utm.area / 10000.0), 1),
                "interpretacao": "proxy cumulativo relativo ao HAND 0 do rio principal",
            },
            "geometry": mapping(geom_wgs84),
        })
        print(f"  contorno {level:4.1f} m -> {features[-1]['properties']['area_ha']:8.1f} ha")

    payload = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "cidade": "santa_tereza",
            "fonte": "HAND 5 m derivado dos rasters novos de campo",
            "rio": "somente rio principal",
            "flowacc_threshold_fine_cells": FLOWACC_THRESHOLD_FINE_CELLS,
            "hand_zero_cm": HAND_ZERO_CM,
            "resolucao_vetor_aprox_m": 10.0,
            "passo_vetor_m": 0.1,
            "calibracao": "régua 1,60 m = HAND 0",
            "interpretacao": "proxy de pesquisa; não é alerta oficial nem cota absoluta validada",
        },
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {"contornos_features": len(features), "contornos_path": str(output)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--page", type=Path, default=PAGE)
    parser.add_argument("--diagnostic", type=Path, default=DIAGNOSTIC)
    args = parser.parse_args()

    dem_path = args.source_dir / "FILL_CLIP_MOSAICO_LIDAR_RS.tif"
    acc_path = args.source_dir / "FLOWACC_CLIP_MOSAICO_LIDAR_RS.tif"
    if not dem_path.exists() or not acc_path.exists():
        raise FileNotFoundError(f"insumos ausentes: {dem_path} / {acc_path}")

    dem, transform, crs, source_bounds, source_resolution = read_dem(dem_path)
    with rasterio.open(acc_path) as ds:
        flowacc = read_flowacc(acc_path, dem.shape, transform, crs, ds.nodata)

    main_river = flowacc >= FLOWACC_THRESHOLD_FINE_CELLS
    labels, n_components = ndimage.label(main_river)
    if n_components == 0:
        raise RuntimeError("nenhum trecho do rio principal atingiu o limiar de acumulação")
    # O limiar observado produz uma única rede em Santa Tereza; se a fonte
    # mudar e fragmentar a rede, conserva-se o maior componente conectado.
    if n_components > 1:
        sizes = np.bincount(labels.ravel())
        sizes[0] = 0
        main_river = labels == int(sizes.argmax())
        n_components_kept = 1
    else:
        n_components_kept = n_components

    _, (river_rows, river_cols) = ndimage.distance_transform_edt(~main_river, return_indices=True)
    hand = dem - dem[river_rows, river_cols]
    hand[~np.isfinite(hand)] = np.nan
    hand[hand < 0] = 0

    # 250 é reservado como NoData no contrato do navegador.
    encoded = np.full(hand.shape, 250, dtype=np.uint8)
    valid = np.isfinite(hand)
    encoded[valid] = np.clip(np.rint(hand[valid] * 10), 0, int(MAX_HAND_M * 10)).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(encoded, mode="L").save(buf, format="PNG", optimize=True)

    west, south, east, north = transform_bounds(crs, "EPSG:4326", *array_bounds(*dem.shape, transform))
    payload = {
        "cols": int(encoded.shape[1]),
        "rows": int(encoded.shape[0]),
        "S": round(float(south), 6),
        "W": round(float(west), 6),
        "N": round(float(north), 6),
        "E": round(float(east), 6),
        "station": {"lat": -29.1781, "lon": -51.7322, "code": "86472600"},
        "ponte": {"lat": -29.0908727, "lon": -51.713269, "label": "Ponte Santa Barbara"},
        "hand_zero_cm": HAND_ZERO_CM,
        "fonte": (
            "HAND 5 m derivado dos rasters novos de campo em D:/PREVINE/hand/santa tereza; "
            "rio principal somente, FLOWACC >= 50000000 células finas; "
            "régua 1,60 m = HAND 0; produto de pesquisa, não é alerta oficial."
        ),
        "hand_png_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
    }
    inject_payload(args.page, payload)
    contour_summary = write_contours(hand, transform, crs, CONTOURS)

    diag = {
        "produto": "hand_lidar_santa_tereza",
        "status": "gerado_localmente_nao_promovido",
        "fonte_dir": str(args.source_dir),
        "terreno": str(dem_path),
        "acumulacao": str(acc_path),
        "resolucao_fonte_m": source_resolution,
        "fator_payload": FACTOR,
        "resolucao_payload_aprox_m": FACTOR * source_resolution,
        "shape_payload": [int(encoded.shape[0]), int(encoded.shape[1])],
        "flowacc_threshold_fine_cells": FLOWACC_THRESHOLD_FINE_CELLS,
        "componentes_detectados": int(n_components),
        "componentes_mantidos": int(n_components_kept),
        "celulas_rio_principal": int(main_river.sum()),
        "hand_zero_cm": HAND_ZERO_CM,
        "hand_max_payload_m": MAX_HAND_M,
        "crs": str(crs),
        "bounds_lonlat": {"south": float(south), "west": float(west), "north": float(north), "east": float(east)},
        "observacao": "O valor da régua é publicado bruto; a espacialização usa RNA menos 1,60 m.",
        **contour_summary,
    }
    args.diagnostic.parent.mkdir(parents=True, exist_ok=True)
    args.diagnostic.write_text(json.dumps(diag, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(diag, ensure_ascii=False, indent=2))
    print(f"payload atualizado: {args.page}")


if __name__ == "__main__":
    main()
