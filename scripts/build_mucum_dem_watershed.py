#!/usr/bin/env python3
"""Build an auditable regional DEM and a first watershed delineation for Muçum.

This is a terrain preparation artifact, not a validated operational basin model.
It downloads public SRTM tiles, reprojects them to SIRGAS 2000 / UTM 22S, fills
depressions with WhiteboxTools, snaps the ANA 86510000 outlet to the drainage
network, and writes a GeoJSON watershed plus an evidence report. The reported
area is compared with the ANA inventory area (16,000 km²); no area is forced.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.merge import merge
from rasterio.transform import from_origin
from rasterio.warp import calculate_default_transform, reproject, Resampling
from shapely.geometry import Point, shape
from shapely.ops import transform as shapely_transform
from pyproj import Transformer
from whitebox.whitebox_tools import WhiteboxTools


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "hec_hms_spatialized_mucum"
DEM_SOURCE = OUT / "dem_source"
DEM_SOURCE.mkdir(parents=True, exist_ok=True)

OUTLET_LON = -51.8686
OUTLET_LAT = -29.1672
ANA_AREA_KM2 = 16000.0
TARGET_CRS = "EPSG:31982"  # SIRGAS 2000 / UTM 22S
TILES = ["S30W052", "S29W052", "S28W052", "S30W051", "S29W051", "S28W051"]
S3_TEMPLATE = "https://s3.amazonaws.com/elevation-tiles-prod/skadi/{lat_band}/{tile}.hgt.gz"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tile_url(tile: str) -> str:
    return S3_TEMPLATE.format(lat_band=tile[:3], tile=tile)


def download_tiles() -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for tile in TILES:
        compressed = DEM_SOURCE / f"{tile}.hgt.gz"
        hgt = DEM_SOURCE / f"{tile}.hgt"
        if not compressed.exists():
            request = urllib.request.Request(tile_url(tile), headers={"User-Agent": "PREVINE-dem-preparation/1.0"})
            with urllib.request.urlopen(request, timeout=180) as response:
                compressed.write_bytes(response.read())
        if not hgt.exists():
            with gzip.open(compressed, "rb") as source, hgt.open("wb") as target:
                shutil.copyfileobj(source, target)
        results.append({
            "tile": tile,
            "url": tile_url(tile),
            "compressed_path": str(compressed.relative_to(ROOT)),
            "hgt_path": str(hgt.relative_to(ROOT)),
            "compressed_bytes": compressed.stat().st_size,
            "hgt_bytes": hgt.stat().st_size,
            "sha256_compressed": sha256(compressed),
            "sha256_hgt": sha256(hgt),
        })
    return results


def make_mosaic() -> Path:
    mosaic = OUT / "srtm_mosaic_wgs84.tif"
    sources = [rasterio.open(DEM_SOURCE / f"{tile}.hgt") for tile in TILES]
    try:
        data, transform = merge(sources, nodata=-32768)
        profile = sources[0].profile.copy()
        profile.update(
            driver="GTiff",
            height=data.shape[1],
            width=data.shape[2],
            transform=transform,
            crs="EPSG:4326",
            count=1,
            dtype="int16",
            nodata=-32768,
            compress="deflate",
            predictor=2,
        )
        with rasterio.open(mosaic, "w", **profile) as target:
            target.write(data[0].astype("int16"), 1)
    finally:
        for source in sources:
            source.close()
    return mosaic


def reproject_dem(source_path: Path) -> Path:
    target_path = OUT / "srtm_mosaic_utm22s_30m.tif"
    with rasterio.open(source_path) as source:
        transform, width, height = calculate_default_transform(
            source.crs, TARGET_CRS, source.width, source.height, *source.bounds, resolution=30
        )
        profile = source.profile.copy()
        profile.update(
            crs=TARGET_CRS,
            transform=transform,
            width=width,
            height=height,
            dtype="float32",
            nodata=-32768.0,
            compress="deflate",
            # WhiteboxTools 2.4 cannot read GeoTIFF floating-point
            # predictors; leave the float raster without PREDICTOR=3.
        )
        with rasterio.open(target_path, "w", **profile) as target:
            reproject(
                source=rasterio.band(source, 1),
                destination=rasterio.band(target, 1),
                src_transform=source.transform,
                src_crs=source.crs,
                src_nodata=source.nodata,
                dst_transform=transform,
                dst_crs=TARGET_CRS,
                dst_nodata=-32768.0,
                resampling=Resampling.bilinear,
            )
    return target_path


def write_point(path: Path) -> None:
    points = gpd.GeoDataFrame(
        [{"station": "86510000", "area_ana_km2": ANA_AREA_KM2}],
        geometry=[Point(OUTLET_LON, OUTLET_LAT)],
        crs="EPSG:4326",
    ).to_crs(TARGET_CRS)
    points.to_file(path, driver="ESRI Shapefile")


def run_whitebox(dem_path: Path) -> dict[str, str]:
    work = OUT / "whitebox"
    work.mkdir(exist_ok=True)
    filled = work / "dem_filled.tif"
    pointer = work / "d8_pointer.tif"
    accumulation = work / "d8_accumulation.tif"
    outlet = work / "outlet.shp"
    raw_point = work / "outlet_raw.shp"
    watershed = work / "watershed.tif"
    wbt = WhiteboxTools()
    wbt.set_working_dir(str(work))
    wbt.verbose = False
    write_point(raw_point)
    wbt.fill_depressions_wang_and_liu(str(dem_path), str(filled))
    wbt.d8_pointer(str(filled), str(pointer))
    wbt.d8_flow_accumulation(str(filled), str(accumulation), out_type="cells")
    wbt.snap_pour_points(str(raw_point), str(accumulation), str(outlet), snap_dist=3000.0)
    wbt.watershed(str(pointer), str(outlet), str(watershed))
    return {"filled": str(filled), "pointer": str(pointer), "accumulation": str(accumulation), "outlet": str(outlet), "watershed": str(watershed)}


def watershed_geojson(watershed_path: Path) -> tuple[Path, float, dict[str, float]]:
    geojson_path = OUT / "watershed_86510000_srtm.geojson"
    with rasterio.open(watershed_path) as source:
        array = source.read(1)
        mask = array > 0
        geometries = [shape(geom) for geom, value in shapes(array, mask=mask, transform=source.transform) if value > 0]
        if not geometries:
            raise RuntimeError("Whitebox watershed is empty; check pour-point CRS and DEM coverage")
        watershed = geometries[0]
        for geom in geometries[1:]:
            watershed = watershed.union(geom)
        area_km2 = float(watershed.area / 1_000_000)
        gpd.GeoDataFrame(
            [{
                "station": "86510000",
                "area_ana_km2": ANA_AREA_KM2,
                "area_srtm_km2": round(area_km2, 3),
                "area_ratio_srtm_to_ana": round(area_km2 / ANA_AREA_KM2, 6),
                "source": "SRTM via AWS elevation-tiles-prod; WhiteboxTools watershed",
            }],
            geometry=[watershed],
            crs=source.crs,
        ).to_crs("EPSG:4326").to_file(geojson_path, driver="GeoJSON")
        bounds = {"west": float(watershed.bounds[0]), "south": float(watershed.bounds[1]), "east": float(watershed.bounds[2]), "north": float(watershed.bounds[3])}
    return geojson_path, area_km2, bounds


def main() -> int:
    tile_records = download_tiles()
    mosaic = make_mosaic()
    dem = reproject_dem(mosaic)
    artifacts = run_whitebox(dem)
    watershed, area_km2, bounds = watershed_geojson(Path(artifacts["watershed"]))
    report = {
        "schema_version": "mucum_srtm_watershed_preparation_v1",
        "purpose": "preparação de bacia para teste HEC-HMS semidistribuído; não é validação operacional",
        "outlet": {"station": "86510000", "longitude": OUTLET_LON, "latitude": OUTLET_LAT, "ana_declared_area_km2": ANA_AREA_KM2},
        "target_crs": TARGET_CRS,
        "dem_source": "SRTM 1 arc-second tiles from AWS elevation-tiles-prod",
        "tiles": tile_records,
        "artifacts": {key: str(Path(value).relative_to(ROOT)) for key, value in artifacts.items()},
        "watershed_geojson": str(watershed.relative_to(ROOT)),
        "srtm_area_km2": round(area_km2, 3),
        "srtm_to_ana_area_ratio": round(area_km2 / ANA_AREA_KM2, 6),
        "watershed_bounds_utm": bounds,
        "methods": [
            "mosaico dos tiles SRTM sem ajuste de área",
            "reprojeção para EPSG:31982 com resolução de 30 m",
            "preenchimento de depressões Wang-Liu e direção/accumulação D8 no WhiteboxTools",
            "ponto 86510000 deslocado somente por maior acumulação em raio de 3 km",
        ],
        "quality_gate": "compare a área delineada com os 16.000 km² da ANA antes de usar no HMS; se divergente, investigar ponto, datum, DEM e rede, sem aumentar a bacia artificialmente",
    }
    (OUT / "watershed_preparation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"watershed": str(watershed), "srtm_area_km2": round(area_km2, 3), "ana_area_km2": ANA_AREA_KM2, "ratio": round(area_km2 / ANA_AREA_KM2, 6)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
