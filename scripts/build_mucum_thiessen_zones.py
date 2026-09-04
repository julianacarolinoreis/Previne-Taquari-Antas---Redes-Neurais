#!/usr/bin/env python3
"""Build the lightweight GeoJSON used by the Muçum spatialized HEC-HMS view."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import MultiPoint, Point, mapping
from shapely.ops import voronoi_diagram


ROOT = Path(__file__).resolve().parents[1]
WATERSHED = ROOT / "assets" / "data" / "hec_hms_spatialized_mucum" / "watershed_86510000_srtm.geojson"
OUTPUT = ROOT / "assets" / "data" / "hec_hms_spatialized_mucum" / "thiessen_zones_86510000.geojson"
VISUAL_SIMPLIFY_M = 75.0
STATIONS = {
    "86472000": {
        "longitude": -51.6997,
        "latitude": -29.0978,
        "name": "Linha José Júlio",
        "role": "chuva por zona",
    },
    "02851072": {
        "longitude": -51.6331,
        "latitude": -28.3811,
        "name": "Ibiraiaras",
        "role": "chuva por zona",
    },
}


def main() -> None:
    watershed = gpd.read_file(WATERSHED).to_crs("EPSG:31982").geometry.iloc[0]
    watershed_visual = watershed.simplify(VISUAL_SIMPLIFY_M, preserve_topology=True)
    watershed_wgs84 = gpd.GeoSeries([watershed_visual], crs="EPSG:31982").to_crs("EPSG:4326").iloc[0]
    points = {
        code: gpd.GeoSeries([Point(item["longitude"], item["latitude"])], crs="EPSG:4326")
        .to_crs("EPSG:31982")
        .iloc[0]
        for code, item in STATIONS.items()
    }
    cells = voronoi_diagram(MultiPoint(list(points.values())), envelope=watershed.envelope, edges=False)
    areas = {}
    features = [
        {
            "type": "Feature",
            "properties": {"feature_type": "watershed", "station": "86510000", "area_km2": watershed.area / 1_000_000.0},
            "geometry": mapping(watershed_wgs84),
        }
    ]
    for code, point in points.items():
        cell = min(cells.geoms, key=lambda candidate: candidate.distance(point))
        clipped = watershed.intersection(cell)
        area_km2 = clipped.area / 1_000_000.0
        areas[code] = area_km2
        item = STATIONS[code]
        clipped_visual = clipped.simplify(VISUAL_SIMPLIFY_M, preserve_topology=True)
        clipped_wgs84 = gpd.GeoSeries([clipped_visual], crs="EPSG:31982").to_crs("EPSG:4326").iloc[0]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "feature_type": "thiessen_zone",
                    "station": code,
                    "name": item["name"],
                    "role": item["role"],
                    "area_km2": area_km2,
                    "weight": area_km2 / (watershed.area / 1_000_000.0),
                },
                "geometry": mapping(clipped_wgs84),
            }
        )
        features.append(
            {
                "type": "Feature",
                "properties": {"feature_type": "rain_gage", "station": code, "name": item["name"], "role": item["role"]},
                "geometry": mapping(gpd.GeoSeries([point], crs="EPSG:31982").to_crs("EPSG:4326").iloc[0]),
            }
        )
    payload = {
        "type": "FeatureCollection",
        "name": "mucum_thiessen_zones_86510000",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "properties": {
            "method": "Thiessen clipped by SRTM D8 watershed",
            "outlet": "86510000",
            "watershed_area_km2": watershed.area / 1_000_000.0,
            "visual_simplification_m": VISUAL_SIMPLIFY_M,
            "areas_km2": areas,
        },
        "features": features,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "areas_km2": areas, "total_km2": watershed.area / 1_000_000.0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
