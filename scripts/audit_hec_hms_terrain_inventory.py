#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inventaria MDTs locais antes da montagem da bacia HEC-HMS."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "assets" / "data" / "hec_hms_audit" / "terrain_inventory_latest.json"
RAIN_REPORT = ROOT / "assets" / "data" / "hec_hms_audit" / "rainfall_station_audit_latest.json"
RASTER_PATHS = sorted((ROOT / "assets" / "data").glob("*/mdt/*.tif"))


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def point_inside(bounds: rasterio.coords.BoundingBox, lon: float, lat: float) -> bool:
    return bounds.left <= lon <= bounds.right and bounds.bottom <= lat <= bounds.top


def station_points() -> dict[str, dict[str, float]]:
    if not RAIN_REPORT.exists():
        return {}
    report = json.loads(RAIN_REPORT.read_text(encoding="utf-8"))
    points: dict[str, dict[str, float]] = {}
    for station in report.get("ana", []):
        identity = station.get("official_identity", {})
        if identity.get("longitude") is not None and identity.get("latitude") is not None:
            points[station["inventory_code"]] = {
                "longitude": float(identity["longitude"]),
                "latitude": float(identity["latitude"]),
            }
    return points


def inspect_raster(path: Path, points: dict[str, dict[str, float]]) -> dict:
    with rasterio.open(path) as source:
        band = source.read(1, masked=True)
        values = band.compressed()
        covered = {
            code: point_inside(source.bounds, point["longitude"], point["latitude"])
            for code, point in points.items()
        }
        return {
            "path": str(path.relative_to(ROOT)),
            "sha256": file_hash(path),
            "width": source.width,
            "height": source.height,
            "bands": source.count,
            "dtype": source.dtypes[0],
            "crs": str(source.crs),
            "transform": [float(value) for value in source.transform],
            "resolution": [float(value) for value in source.res],
            "bounds": [float(value) for value in source.bounds],
            "nodata": source.nodata,
            "masked_cells": int(np.ma.count_masked(band)),
            "cells": int(source.width * source.height),
            "min_value": float(values.min()) if values.size else None,
            "max_value": float(values.max()) if values.size else None,
            "point_coverage": covered,
            "semantic_note": (
                "arquivo local com banda numérica; confirmar se representa MDT, DSM ou outra superfície antes de usar"
                if "ortho" in path.name.lower()
                else "arquivo tratado como MDT pela nomenclatura local; confirmar metadado vertical e datum"
            ),
        }


def main() -> int:
    points = station_points()
    report = {
        "schema_version": "hec_hms_terrain_inventory_v1",
        "purpose": "inventário técnico para preparação de bacias HEC-HMS; não é mancha validada nem autorização operacional",
        "station_points_source": str(RAIN_REPORT.relative_to(ROOT)),
        "station_points": points,
        "rasters": [inspect_raster(path, points) for path in RASTER_PATHS],
        "findings": [
            "Os MDTs ANADEM de 30 m cobrem as coordenadas das estações ANA de Santa Tereza presentes no relatório de chuva.",
            "Os rasters de drone têm resolução aproximada de 1 m, mas cobrem apenas AOIs locais e não substituem automaticamente o MDT regional.",
            "Arquivos com sufixo _ortho foram mantidos como superfície numérica, porém sua semântica (MDT/DSM/ortofoto) precisa ser confirmada antes da modelagem.",
            "Todos os rasters estão em EPSG:4326; a montagem hidrológica deve reprojetar para CRS métrico antes de calcular área, comprimento e declividade.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(REPORT.relative_to(ROOT)), "rasters": len(RASTER_PATHS), "stations": len(points)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
