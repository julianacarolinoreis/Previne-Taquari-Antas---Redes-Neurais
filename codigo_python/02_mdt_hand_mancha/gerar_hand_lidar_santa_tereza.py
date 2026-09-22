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
(aproximadamente 50 km² de área contribuinte no raster de 1 m). O HAND é
calculado seguindo a direção D8 do escoamento até esse rio principal — nunca
pela distância euclidiana ao canal. O código autodetecta a convenção D8
(ESRI/Whitebox/ordinal) comparando a direção proposta com a acumulação e o
terreno e interrompe a geração se a convenção não puder ser identificada com
segurança. O terreno é reamostrado para 5 m apenas para o payload leve do
navegador; a calibração vertical permanece separada: régua 1,60 m = HAND 0.

A superfície física da inundação usa o LiDAR bruto CLIP_MOSAICO_LIDAR_RS.tif.
O raster FILL_CLIP_MOSAICO_LIDAR_RS.tif é usado somente para orientar o
roteamento hidrológico (FLOWDIR/FLOWACC), nunca como cota final do terreno.

Além do HAND vertical, a mancha usa um limiar hidráulico de conectividade:
para cada célula é considerada a maior cota do LiDAR bruto encontrada no
caminho D8 até o rio principal. Assim a água não "salta" aterros, ruas ou
divisores apenas porque existe uma área baixa atrás deles.

O mesmo processo gera a grade de altitude absoluta a ~10 m diretamente do
CLIP_MOSAICO_LIDAR_RS.tif bruto.

Uso:
  python gerar_hand_lidar_santa_tereza.py
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import subprocess
import sys
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
CONTOUR_LEVELS_M = [round(x, 1) for x in np.arange(0, MAX_HAND_M + 0.01, 0.1)]
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
    """Agrega a acumulação 1 m preservando o maior valor de cada célula ~5 m."""
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
    flowacc[~np.isfinite(flowacc) | (flowacc > 1e20) | (flowacc < 0)] = 0
    return flowacc


def read_flowdir(path: Path, shape: tuple[int, int], transform, crs) -> np.ndarray:
    """Agrega o D8 1 m por moda; nunca interpola códigos de direção."""
    flowdir = np.zeros(shape, dtype="int16")
    with rasterio.open(path) as ds:
        tmp = np.zeros(shape, dtype="float32")
        reproject(
            rasterio.band(ds, 1),
            tmp,
            src_transform=ds.transform,
            src_crs=ds.crs,
            dst_transform=transform,
            dst_crs=crs,
            resampling=Resampling.mode,
            src_nodata=ds.nodata,
            dst_nodata=0,
        )
    tmp[~np.isfinite(tmp) | (tmp < 0) | (tmp > 255)] = 0
    flowdir[:] = np.rint(tmp).astype("int16")
    return flowdir


D8_SCHEMES = {
    # ArcGIS/ESRI D8: E, SE, S, SW, W, NW, N, NE.
    "esri": {
        1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1),
        16: (0, -1), 32: (-1, -1), 64: (-1, 0), 128: (-1, 1),
    },
    # Whitebox native pointer: NE, E, SE, S, SW, W, NW, N.
    "whitebox": {
        1: (-1, 1), 2: (0, 1), 4: (1, 1), 8: (1, 0),
        16: (1, -1), 32: (0, -1), 64: (-1, -1), 128: (-1, 0),
    },
    # Algumas exportações usam 1..8 em sentido horário a partir do leste.
    "ordinal": {
        1: (0, 1), 2: (1, 1), 3: (1, 0), 4: (1, -1),
        5: (0, -1), 6: (-1, -1), 7: (-1, 0), 8: (-1, 1),
    },
}


def offset_slices(shape: tuple[int, int], dr: int, dc: int):
    rows, cols = shape
    src_r = slice(max(0, -dr), min(rows, rows - dr))
    dst_r = slice(max(0, dr), min(rows, rows + dr))
    src_c = slice(max(0, -dc), min(cols, cols - dc))
    dst_c = slice(max(0, dc), min(cols, cols + dc))
    return (src_r, src_c), (dst_r, dst_c)


def detect_d8_scheme(flowdir: np.ndarray, flowacc: np.ndarray, dem: np.ndarray) -> tuple[str, dict[int, tuple[int, int]], dict]:
    """Escolhe a convenção D8 que melhor aponta para maior acumulação/menor cota."""
    scores: dict[str, dict[str, float | int]] = {}
    for name, mapping in D8_SCHEMES.items():
        good = 0
        total = 0
        for code, (dr, dc) in mapping.items():
            src, dst = offset_slices(flowdir.shape, dr, dc)
            mask = (
                (flowdir[src] == code)
                & np.isfinite(dem[src])
                & np.isfinite(dem[dst])
                & (flowacc[src] > 0)
                & (flowacc[dst] > 0)
            )
            n = int(mask.sum())
            if not n:
                continue
            plausible = (flowacc[dst] >= flowacc[src]) & (dem[dst] <= dem[src] + 2.0)
            good += int((mask & plausible).sum())
            total += n
        scores[name] = {"good": good, "total": total, "score": (good / total if total else 0.0)}

    best_name = max(scores, key=lambda k: float(scores[k]["score"]))
    best = scores[best_name]
    if int(best["total"]) < 1000 or float(best["score"]) < 0.55:
        raise RuntimeError(
            "Não foi possível identificar com segurança a convenção do FLOWDIR. "
            f"Scores: {scores}. Não publique o HAND até conferir o raster de direção."
        )
    return best_name, D8_SCHEMES[best_name], scores


def compute_hand_flowpath(
    terrain_dem: np.ndarray,
    routing_dem: np.ndarray,
    flowdir: np.ndarray,
    flowacc: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Calcula HAND e limiar hidráulico numa rede guiada por D8 + FLOWACC.

    terrain_dem é o LiDAR bruto e fornece todas as cotas usadas para altitude,
    HAND e barreiras da inundação. routing_dem é o DEM preenchido (FILL) e
    serve apenas para escolher caminhos coerentes com FLOWDIR/FLOWACC.

    O hand clássico mede a diferença vertical entre cada célula e a célula do
    rio principal onde seu caminho termina. hydraulic_hand é mais conservador:
    mede a maior cota do LiDAR bruto encontrada ao longo de todo o caminho D8
    até o rio. Assim uma depressão baixa atrás de rua/aterro alto só entra na
    mancha quando o nível supera essa barreira física.
    """
    if terrain_dem.shape != routing_dem.shape:
        raise RuntimeError("LiDAR bruto e FILL não têm a mesma grade")

    main_river = flowacc >= FLOWACC_THRESHOLD_FINE_CELLS
    labels, n_components = ndimage.label(
        main_river, structure=np.ones((3, 3), dtype=np.uint8)
    )
    if n_components == 0:
        raise RuntimeError("nenhum trecho do rio principal atingiu o limiar de acumulação")
    if n_components > 1:
        sizes = np.bincount(labels.ravel())
        sizes[0] = 0
        main_river = labels == int(sizes.argmax())
        n_components_kept = 1
    else:
        n_components_kept = n_components

    scheme_name, mapping, scheme_scores = detect_d8_scheme(
        flowdir, flowacc, routing_dem
    )

    n = terrain_dem.size
    if n >= np.iinfo(np.int32).max:
        raise RuntimeError("grade grande demais para índices int32")

    dirs = [(0, 1), (1, 1), (1, 0), (1, -1),
            (0, -1), (-1, -1), (-1, 0), (-1, 1)]
    dir_to_idx = {offset: i for i, offset in enumerate(dirs)}
    code_to_idx = {code: dir_to_idx[offset] for code, offset in mapping.items()}

    pref_idx = np.full(flowdir.shape, -99, dtype=np.int8)
    for code, idx in code_to_idx.items():
        pref_idx[flowdir == code] = idx

    flat_index = np.arange(n, dtype=np.int32).reshape(terrain_dem.shape)
    receiver = flat_index.copy()
    valid = np.isfinite(terrain_dem) & np.isfinite(routing_dem)

    best_score = np.full(terrain_dem.shape, -np.inf, dtype="float32")
    assigned_primary = np.zeros(terrain_dem.shape, dtype=bool)

    for pass_all_directions in (False, True):
        for cand_idx, (dr, dc) in enumerate(dirs):
            src, dst = offset_slices(terrain_dem.shape, dr, dc)
            pref = pref_idx[src].astype(np.int16)
            circular = np.abs(((pref - cand_idx + 4) % 8) - 4)
            dst_acc = flowacc[dst]
            src_acc = flowacc[src]
            dst_route = routing_dem[dst]
            src_route = routing_dem[src]

            base = valid[src] & valid[dst] & (dst_acc > src_acc)
            if not pass_all_directions:
                base &= (pref >= 0) & (circular <= 2)
            else:
                base &= ~assigned_primary[src]

            score = (
                np.log1p(dst_acc).astype("float32")
                - 0.20 * circular.astype("float32")
                + 0.02 * np.clip(src_route - dst_route, -10.0, 10.0).astype("float32")
            )
            better = base & (score > best_score[src])
            if not better.any():
                continue
            rec_view = receiver[src]
            score_view = best_score[src]
            target_idx = flat_index[dst]
            rec_view[better] = target_idx[better]
            score_view[better] = score[better]
            if not pass_all_directions:
                assigned_view = assigned_primary[src]
                assigned_view[better] = True

    assigned_receivers = receiver != flat_index
    receiver[main_river] = flat_index[main_river]
    receiver_flat = receiver.ravel().copy()

    parent = receiver_flat.copy()
    iterations = 0
    for iterations in range(1, 33):
        jumped = parent[parent]
        if np.array_equal(jumped, parent):
            parent = jumped
            break
        parent = jumped

    unresolved = parent[parent] != parent
    river_flat = main_river.ravel()
    terrain_flat = terrain_dem.ravel()
    valid_flat = valid.ravel()
    drains_to_main = valid_flat & (~unresolved) & river_flat[parent]

    hand_flat = np.full(n, np.nan, dtype="float32")
    positions = np.flatnonzero(drains_to_main)
    values = terrain_flat[positions] - terrain_flat[parent[positions]]
    acceptable = values >= -0.5
    accepted_positions = positions[acceptable]
    hand_flat[accepted_positions] = np.maximum(values[acceptable], 0.0)
    hand = hand_flat.reshape(terrain_dem.shape)

    barrier_elev = terrain_flat.astype("float32", copy=True)
    barrier_elev[~valid_flat] = np.nan
    jump = receiver_flat.copy()
    barrier_iterations = 0
    for barrier_iterations in range(1, 33):
        downstream_barrier = barrier_elev[jump]
        barrier_elev = np.fmax(barrier_elev, downstream_barrier)
        jumped = jump[jump]
        if np.array_equal(jumped, jump):
            jump = jumped
            break
        jump = jumped

    hydraulic_flat = np.full(n, np.nan, dtype="float32")
    barrier_values = (
        barrier_elev[accepted_positions]
        - terrain_flat[parent[accepted_positions]]
    )
    hydraulic_flat[accepted_positions] = np.maximum(barrier_values, 0.0)
    hydraulic_hand = hydraulic_flat.reshape(terrain_dem.shape)

    delta = hydraulic_flat - hand_flat
    delta_valid = delta[np.isfinite(delta)]
    drained_fraction = float(
        np.isfinite(hydraulic_hand).sum() / max(1, valid.sum())
    )
    diagnostics = {
        "d8_scheme": scheme_name,
        "d8_scheme_scores": scheme_scores,
        "flowdir_source_resolution_m": 1.0,
        "flowdir_coarse_method": "mode D8 preference + FLOWACC-increasing 8-neighbour routing with fallback",
        "pointer_jumping_iterations": iterations,
        "barrier_pointer_jumping_iterations": barrier_iterations,
        "receiver_cells_assigned": int(assigned_receivers.sum()),
        "receiver_fraction_assigned": float(
            assigned_receivers.sum() / max(1, valid.sum())
        ),
        "unresolved_cells": int(unresolved.sum()),
        "valid_terrain_cells": int(valid.sum()),
        "cells_draining_to_main_river": int(np.isfinite(hydraulic_hand).sum()),
        "drained_fraction": drained_fraction,
        "componentes_detectados": int(n_components),
        "componentes_mantidos": int(n_components_kept),
        "celulas_rio_principal": int(main_river.sum()),
        "hand_method": "raw LiDAR elevation relative to D8-connected main-river cell",
        "hydraulic_hand_method": "maximum raw-LiDAR barrier along D8 path to main river",
        "hydraulic_barrier_cells_gt_0_10m": int(np.sum(delta_valid > 0.10)),
        "hydraulic_barrier_added_p95_m": (
            float(np.percentile(delta_valid, 95)) if delta_valid.size else 0.0
        ),
        "hydraulic_barrier_added_max_m": (
            float(np.max(delta_valid)) if delta_valid.size else 0.0
        ),
    }
    print(
        "DIAGNOSTICO ROTEAMENTO: "
        f"D8={scheme_name}; rio={int(main_river.sum())} células; "
        f"receptores={assigned_receivers.sum()}/{valid.sum()} "
        f"({assigned_receivers.sum()/max(1,valid.sum()):.1%}); "
        f"drena_ao_rio={np.isfinite(hydraulic_hand).sum()}/{valid.sum()} "
        f"({drained_fraction:.1%}); "
        f"barreiras>10cm={diagnostics['hydraulic_barrier_cells_gt_0_10m']}"
    )
    if drained_fraction < 0.05:
        raise RuntimeError(
            f"Só {drained_fraction:.1%} do terreno drenou ao rio principal; "
            "a agregação D8/FLOWACC ainda não é confiável. Geração abortada."
        )
    return hand, hydraulic_hand, main_river, diagnostics


def write_same_source_elevation(dem: np.ndarray, transform, crs) -> dict:
    """Gera altitude absoluta ~10 m da mesma fonte do HAND, com bounds próprios."""
    out_dir = ROOT / "assets" / "data" / "santa_tereza_inundacao" / "mdt"
    out_dir.mkdir(parents=True, exist_ok=True)
    step = 2  # dem já está a ~5 m
    elev = dem[::step, ::step]
    elev_transform = transform * transform.scale(step, step)
    valid = np.isfinite(elev)

    rgba = np.zeros((*elev.shape, 4), dtype=np.uint8)
    dm = np.zeros(elev.shape, dtype=np.uint16)
    dm[valid] = np.clip(np.rint(elev[valid] * 10.0), 0, 65535).astype(np.uint16)
    rgba[..., 0] = (dm >> 8).astype(np.uint8)
    rgba[..., 1] = (dm & 255).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 255, 0).astype(np.uint8)

    png = out_dir / "altitude_terreno_lidar_10m.png"
    Image.fromarray(rgba, mode="RGBA").save(png, optimize=True)

    visual = np.zeros((*elev.shape, 4), dtype=np.uint8)
    if valid.any():
        lo, hi = np.nanpercentile(elev[valid], [2, 98])
        norm = np.clip((elev - lo) / max(float(hi - lo), 1e-6), 0, 1)
        shade = np.nan_to_num(norm * 255.0, nan=0.0).astype(np.uint8)
        visual[..., 0] = shade
        visual[..., 1] = shade
        visual[..., 2] = shade
        visual[..., 3] = np.where(valid, 180, 0).astype(np.uint8)
    visual_png = out_dir / "mdt_santa_tereza_lidar_10m_visual.png"
    Image.fromarray(visual, mode="RGBA").save(visual_png, optimize=True)

    west, south, east, north = transform_bounds(
        crs, "EPSG:4326", *array_bounds(*elev.shape, elev_transform)
    )
    meta = {
        "cols": int(elev.shape[1]),
        "rows": int(elev.shape[0]),
        "W": float(west), "S": float(south), "E": float(east), "N": float(north),
        "bounds": {"west": float(west), "south": float(south), "east": float(east), "north": float(north)},
        "unidade": "m",
        "escala": 0.1,
        "codificacao": "uint16_decimetros_em_rg",
        "resolucao_aproximada_m": float(FACTOR * step),
        "crs": "EPSG:4326",
        "fonte": "CLIP_MOSAICO_LIDAR_RS.tif",
        "fonte_roteamento": "FILL_CLIP_MOSAICO_LIDAR_RS.tif",
        "same_source_as_hand": True,
        "terrain_surface": "raw_lidar_unfilled",
        "png": png.name,
        "visual_png": visual_png.name,
        "status": "same_source_mdt_ready",
    }
    meta_path = out_dir / "altitude_terreno_lidar_10m.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"elevation_meta": str(meta_path), "elevation_png": str(png), "elevation_visual_png": str(visual_png), "elevation_bounds": meta["bounds"]}


def activate_same_source_mdt(page: Path) -> None:
    """Aponta a página para o MDT absoluto gerado da mesma fonte do HAND."""
    html = page.read_text(encoding="utf-8")
    pattern = r"const ELEVATION_URL=.*?; // same-source MDT only"
    replacement = (
        "const ELEVATION_URL='assets/data/santa_tereza_inundacao/mdt/"
        "altitude_terreno_lidar_10m.json'; // same-source MDT only"
    )
    html2, count = re.subn(pattern, replacement, html, count=1)
    if count != 1:
        raise RuntimeError("marcador ELEVATION_URL same-source não encontrado na página")
    page.write_text(html2, encoding="utf-8")


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


def write_contours(hand: np.ndarray, main_river: np.ndarray, transform, crs, output: Path) -> dict:
    """Vetoriza o HAND hidráulico calculado sobre o LiDAR bruto.

    O array já incorpora a maior barreira física encontrada no caminho D8 até
    o rio principal. A checagem 8-vizinhos é apenas uma segunda trava para
    remover fragmentos desconectados da semente do rio. O terreno não é
    preenchido nem alterado nesta etapa.
    """
    to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    # O HAND consultado no popup permanece em 5 m. Para o vetor desenhado no
    # mapa, 10 m é suficiente e reduz bastante o payload público.
    hand_vector = hand[::CONTOUR_FACTOR, ::CONTOUR_FACTOR]
    vector_transform = transform * transform.scale(CONTOUR_FACTOR, CONTOUR_FACTOR)

    # O canal é estreito na grade HAND; dilata-se apenas a semente de
    # conectividade antes da subamostragem para não "perder" o rio entre
    # pixels. Isto NÃO altera o polígono final nem a elevação.
    river_seed_full = ndimage.binary_dilation(
        main_river,
        structure=np.ones((3, 3), dtype=bool),
        iterations=max(1, CONTOUR_FACTOR),
    )
    river_seed = river_seed_full[::CONTOUR_FACTOR, ::CONTOUR_FACTOR]
    conn8 = np.ones((3, 3), dtype=np.uint8)

    features = []
    connectivity_stats = []
    for level in CONTOUR_LEVELS_M:
        candidate = np.isfinite(hand_vector) & (hand_vector <= level)
        if not candidate.any():
            continue

        labels, count = ndimage.label(candidate, structure=conn8)
        touching = np.unique(labels[river_seed & candidate])
        touching = touching[touching != 0]
        if touching.size == 0:
            continue
        mask = np.isin(labels, touching)
        removed = int(candidate.sum() - mask.sum())
        connectivity_stats.append({
            "nivel_m": level,
            "candidate_cells": int(candidate.sum()),
            "connected_cells": int(mask.sum()),
            "removed_disconnected_cells": removed,
        })

        polygons = [shape(geom) for geom, value in shapes(mask.astype(np.uint8), mask=mask, transform=vector_transform) if value]
        if not polygons:
            continue
        geom_utm = unary_union(polygons).buffer(0)
        if geom_utm.is_empty:
            continue
        # Mantém detalhe compatível com a grade vetorial ~10 m. A antiga
        # simplificação de 30 m deslocava bordas demais perto de ruas/casas.
        geom_utm = geom_utm.simplify(5.0, preserve_topology=True)
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
            "filtro_conectividade": (
                "barreira máxima no LiDAR bruto ao longo do caminho D8 + "
                "checagem 8-vizinhos conectada ao rio principal"
            ),
            "superficie_inundacao": "CLIP_MOSAICO_LIDAR_RS.tif (LiDAR bruto)",
            "superficie_roteamento": "FILL_CLIP_MOSAICO_LIDAR_RS.tif",
            "mdt_preservado": True,
        },
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {
        "contornos_features": len(features),
        "contornos_path": str(output),
        "water_connectivity_filter": "D8 path max-barrier on raw LiDAR + 8-neighbour main-river check",
        "water_connectivity_stats": connectivity_stats,
        "terrain_modified_by_water_filter": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--page", type=Path, default=PAGE)
    parser.add_argument("--diagnostic", type=Path, default=DIAGNOSTIC)
    args = parser.parse_args()

    terrain_path = args.source_dir / "CLIP_MOSAICO_LIDAR_RS.tif"
    routing_path = args.source_dir / "FILL_CLIP_MOSAICO_LIDAR_RS.tif"
    acc_path = args.source_dir / "FLOWACC_CLIP_MOSAICO_LIDAR_RS.tif"
    dir_path = args.source_dir / "FLOWDIR_CLIP_MOSAICO_LIDAR_RS.tif"
    missing = [
        path for path in (terrain_path, routing_path, acc_path, dir_path)
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError("insumos ausentes: " + " / ".join(str(path) for path in missing))

    terrain_dem, transform, crs, source_bounds, source_resolution = read_dem(
        terrain_path
    )
    routing_dem, routing_transform, routing_crs, _, routing_resolution = read_dem(
        routing_path
    )
    if terrain_dem.shape != routing_dem.shape:
        raise RuntimeError("CLIP e FILL têm dimensões diferentes; não publique a mancha")
    if crs != routing_crs or not transform.almost_equals(routing_transform):
        raise RuntimeError("CLIP e FILL não estão na mesma grade/CRS; não publique a mancha")
    if abs(source_resolution - routing_resolution) > 1e-6:
        raise RuntimeError("CLIP e FILL têm resoluções diferentes; não publique a mancha")

    with rasterio.open(acc_path) as ds:
        flowacc = read_flowacc(
            acc_path, terrain_dem.shape, transform, crs, ds.nodata
        )
    flowdir = read_flowdir(dir_path, terrain_dem.shape, transform, crs)

    hand, hydraulic_hand, main_river, hand_diag = compute_hand_flowpath(
        terrain_dem, routing_dem, flowdir, flowacc
    )
    elevation_summary = write_same_source_elevation(terrain_dem, transform, crs)

    # O navegador usa o mesmo limiar hidráulico dos contornos.
    encoded = np.full(hydraulic_hand.shape, 255, dtype=np.uint8)
    valid = np.isfinite(hydraulic_hand)
    encoded[valid] = np.clip(
        np.rint(hydraulic_hand[valid] * 10),
        0,
        int(MAX_HAND_M * 10),
    ).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(encoded, mode="L").save(buf, format="PNG", optimize=True)

    west, south, east, north = transform_bounds(
        crs, "EPSG:4326", *array_bounds(*terrain_dem.shape, transform)
    )
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
            "HAND hidráulico 5 m: cotas e barreiras do CLIP_MOSAICO_LIDAR_RS.tif bruto; "
            "FILL/FLOWDIR/FLOWACC usados somente para roteamento até o rio principal; "
            "régua 1,60 m = HAND 0; produto de pesquisa, não é alerta oficial."
        ),
        "hand_png_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
    }
    inject_payload(args.page, payload)
    activate_same_source_mdt(args.page)
    contour_summary = write_contours(
        hydraulic_hand, main_river, transform, crs, CONTOURS
    )

    # A página ao vivo consome contornos_extravasamento.json, não o contorno
    # HAND cumulativo bruto. Regenera somente Santa Tereza para não tocar Muçum.
    overflow_script = ROOT / "codigo_python" / "02_mdt_hand_mancha" / "gerar_contornos_extravasamento.py"
    subprocess.run(
        [sys.executable, str(overflow_script), "--cidade", "santa_tereza"],
        cwd=ROOT,
        check=True,
    )

    diag = {
        "produto": "hand_lidar_santa_tereza",
        "status": "gerado_localmente_requer_validacao_cartografica",
        "fonte_dir": str(args.source_dir),
        "terreno": str(terrain_path),
        "terreno_bruto_lidar": str(terrain_path),
        "terreno_roteamento_fill": str(routing_path),
        "fill_usado_como_superficie_inundacao": False,
        "acumulacao": str(acc_path),
        "direcao_fluxo": str(dir_path),
        "resolucao_fonte_m": source_resolution,
        "fator_payload": FACTOR,
        "resolucao_payload_aprox_m": FACTOR * source_resolution,
        "shape_payload": [int(encoded.shape[0]), int(encoded.shape[1])],
        "flowacc_threshold_fine_cells": FLOWACC_THRESHOLD_FINE_CELLS,
        **hand_diag,
        "hand_zero_cm": HAND_ZERO_CM,
        "hand_max_payload_m": MAX_HAND_M,
        "contour_max_m": MAX_HAND_M,
        "spatialization_rule": "nivel_regua_m - 1.60 m",
        "crs": str(crs),
        "bounds_lonlat": {"south": float(south), "west": float(west), "north": float(north), "east": float(east)},
        "observacao": (
            "O valor da régua é publicado bruto; a espacialização usa RNA menos 1,60 m. "
            "As cotas e barreiras da mancha vêm do LiDAR bruto CLIP_MOSAICO_LIDAR_RS.tif; "
            "o FILL é usado somente no roteamento D8. O limiar hidráulico considera a "
            "maior barreira do terreno ao longo do caminho até o rio principal."
        ),
        **elevation_summary,
        **contour_summary,
        "contornos_extravasamento_path": str(
            ROOT / "assets" / "data" / "santa_tereza_inundacao" / "contornos_extravasamento.json"
        ),
    }
    args.diagnostic.parent.mkdir(parents=True, exist_ok=True)
    args.diagnostic.write_text(json.dumps(diag, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(diag, ensure_ascii=False, indent=2))
    print(f"payload atualizado: {args.page}")


if __name__ == "__main__":
    main()
