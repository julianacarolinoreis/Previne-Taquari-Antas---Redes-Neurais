#!/usr/bin/env python3
"""Audit approximate reach terrain from BHO6 geometry and the local SRTM MDT."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import rasterio
from shapely.geometry import shape


ROOT = Path(__file__).resolve().parents[1]
NETWORK = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas"
AUDIT = NETWORK / "network_audit_latest.json"
GEOJSON = NETWORK / "bho6_taquari_antas_network.geojson"
MDT = ROOT / "assets" / "data" / "hec_hms_spatialized_mucum" / "srtm_mosaic_wgs84.tif"
OUT = NETWORK / "reach_terrain_metrics_latest.json"


def coords_for(geometry: dict) -> list[tuple[float, float]]:
    geom = shape(geometry)
    if geom.geom_type == "LineString":
        return [(float(x), float(y)) for x, y in geom.coords]
    if geom.geom_type == "MultiLineString":
        parts = list(geom.geoms)
        coords: list[tuple[float, float]] = []
        for part in parts:
            coords.extend((float(x), float(y)) for x, y in part.coords)
        return coords
    return []


def sample(dataset: rasterio.DatasetReader, coords: list[tuple[float, float]]) -> list[float]:
    values = []
    for value in dataset.sample(coords):
        number = float(value[0])
        if number > -1.0e20:
            values.append(number)
    return values


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    geojson = json.loads(GEOJSON.read_text(encoding="utf-8"))
    by_fid = {
        int(feature["properties"]["fid"]): feature
        for feature in geojson["features"]
        if "fid" in feature.get("properties", {})
    }
    paths = audit["topology"]["paths"]
    results = {}
    with rasterio.open(MDT) as dataset:
        for path_name, path in paths.items():
            coords: list[tuple[float, float]] = []
            missing = []
            for fid in path["segments"]:
                feature = by_fid.get(int(fid))
                if not feature:
                    missing.append(int(fid))
                    continue
                segment_coords = coords_for(feature["geometry"])
                if segment_coords:
                    coords.extend(segment_coords)
            values = sample(dataset, coords)
            start_elevation = values[0] if values else None
            end_elevation = values[-1] if values else None
            drop = None if start_elevation is None or end_elevation is None else start_elevation - end_elevation
            length_km = float(path["length_km"])
            results[path_name] = {
                "segment_count": path["segment_count"],
                "length_km_bho6": length_km,
                "mdt_source": str(MDT.relative_to(ROOT)).replace("\\", "/"),
                "mdt_crs": str(dataset.crs),
                "sample_count": len(values),
                "start_terrain_elevation_m": start_elevation,
                "end_terrain_elevation_m": end_elevation,
                "terrain_drop_m": drop,
                "mean_terrain_elevation_m": None if not values else sum(values) / len(values),
                "min_terrain_elevation_m": None if not values else min(values),
                "max_terrain_elevation_m": None if not values else max(values),
                "approx_positive_slope_m_per_m": None if drop is None else max(drop, 0.0) / (length_km * 1000.0),
                "missing_bho6_geometry_fids": missing,
                "routing_use": "diagnostic only; not a channel-bed slope or travel time",
            }
    report = {
        "schema_version": "taquari_antas_reach_terrain_audit_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "auditoria de terreno para parametrizacao futura HEC-HMS; nao e calibracao nem operacao",
        "sources": {
            "network": "ANA BHO6 network_audit_latest.json and bho6_taquari_antas_network.geojson",
            "terrain": str(MDT.relative_to(ROOT)).replace("\\", "/"),
            "terrain_note": "SRTM/MDT e terreno amostrado, nao substitui secao hidraulica, cota d'agua, Manning ou nivelamento de calha",
        },
        "reaches": results,
        "gate": "terrain_screening_complete; reach routing parameters still require channel evidence",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
