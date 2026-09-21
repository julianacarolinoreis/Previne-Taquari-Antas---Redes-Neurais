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
MDT_CANDIDATES = [
    ROOT / "assets" / "data" / "santa_tereza_inundacao" / "mdt" / "mdt_santa_tereza_anadem_30m.tif",
    ROOT / "assets" / "data" / "mucum_inundacao" / "mdt" / "mdt_mucum_anadem_30m.tif",
]
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


def sample_coordinate(datasets: list[tuple[Path, rasterio.DatasetReader]], coord: tuple[float, float]) -> tuple[float | None, str | None]:
    """Return the first finite sample from a tile that covers the coordinate."""
    for path, dataset in datasets:
        try:
            row, col = dataset.index(coord[0], coord[1])
            if row < 0 or col < 0 or row >= dataset.height or col >= dataset.width:
                continue
            value = float(next(dataset.sample([coord]))[0])
        except Exception:
            continue
        if value > -1.0e20 and value == value:
            return value, str(path.relative_to(ROOT)).replace("\\", "/")
    return None, None


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
    available = [path for path in MDT_CANDIDATES if path.exists()]
    if not available:
        report = {
            "schema_version": "taquari_antas_reach_terrain_audit_v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": "auditoria de terreno para parametrizacao futura HEC-HMS; nao e calibracao nem operacao",
            "sources": {"network": "ANA BHO6 network_audit_latest.json and bho6_taquari_antas_network.geojson", "terrain": [], "terrain_note": "nenhum MDT ANADEM disponível no checkout"},
            "reaches": {},
            "gate": "terrain_screening_blocked_missing_mdt",
        }
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(OUT), "gate": report["gate"]}, ensure_ascii=False))
        return 0
    datasets = [(path, rasterio.open(path)) for path in available]
    try:
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
            sampled: list[tuple[float, str]] = []
            for coord in coords:
                value, source = sample_coordinate(datasets, coord)
                if value is not None and source is not None:
                    sampled.append((value, source))
            values = [value for value, _ in sampled]
            start_elevation = values[0] if values else None
            end_elevation = values[-1] if values else None
            drop = None if start_elevation is None or end_elevation is None else start_elevation - end_elevation
            length_km = float(path["length_km"])
            results[path_name] = {
                "segment_count": path["segment_count"],
                "length_km_bho6": length_km,
                "mdt_sources": sorted({source for _, source in sampled}),
                "mdt_crs": sorted({str(dataset.crs) for _, dataset in datasets}),
                "sample_count": len(values),
                "sample_count_by_source": {source: sum(1 for _, sampled_source in sampled if sampled_source == source) for source in sorted({source for _, source in sampled})},
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
    finally:
        for _, dataset in datasets:
            dataset.close()
    report = {
        "schema_version": "taquari_antas_reach_terrain_audit_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "auditoria de terreno para parametrizacao futura HEC-HMS; nao e calibracao nem operacao",
        "sources": {
            "network": "ANA BHO6 network_audit_latest.json and bho6_taquari_antas_network.geojson",
            "terrain": [str(path.relative_to(ROOT)).replace("\\", "/") for path in available],
            "terrain_note": "ANADEM/MDT 30 m amostrado por tiles; nao substitui secao hidraulica, cota d'agua, Manning ou nivelamento de calha",
        },
        "reaches": results,
        "gate": "terrain_screening_complete_from_anadem_tiles; reach routing parameters still require channel evidence",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
