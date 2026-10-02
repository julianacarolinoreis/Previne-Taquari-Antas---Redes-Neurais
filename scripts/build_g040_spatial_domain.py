#!/usr/bin/env python3
"""Build the PREVINE G040 spatial domain contract.

Hydrologic computation is clipped to the union of the current G040/Q040
polygons. Meteorological acquisition uses the same basin union plus a
configurable metric buffer (default 50 km) so gauges and gridded NWP cells near
the boundary can support interpolation without adding runoff area outside G040.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "assets/data/estudo_bacia_taquari_antas"
OUTDIR = ROOT / "assets/data/hec_hms_g040_full_basin"
SOURCE = STUDY / "sub_bacias_q040_enquadramento.geojson"
OUT_MASK = OUTDIR / "g040_basin_mask.geojson"
OUT_BUFFER = OUTDIR / "g040_download_buffer.geojson"
OUT_META = OUTDIR / "g040_domain_contract_latest.json"

BUFFER_KM = float(os.environ.get("G040_ACQUISITION_BUFFER_KM", "50"))
SRC_CRS = "EPSG:4326"
METRIC_CRS = "EPSG:31982"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def feature_collection(geom, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": properties,
            "geometry": mapping(geom),
        }],
    }


def main() -> int:
    raw = load_json(SOURCE)
    geoms = [
        shape(f["geometry"])
        for f in (raw.get("features") or [])
        if f.get("geometry")
    ]
    if not geoms:
        raise RuntimeError("G040/Q040 source contains no geometry")

    basin = unary_union(geoms)
    if basin.is_empty:
        raise RuntimeError("G040 union is empty")
    if not basin.is_valid:
        basin = basin.buffer(0)
    if basin.is_empty or not basin.is_valid:
        raise RuntimeError("G040 union could not be repaired")

    to_metric = Transformer.from_crs(SRC_CRS, METRIC_CRS, always_xy=True).transform
    to_wgs84 = Transformer.from_crs(METRIC_CRS, SRC_CRS, always_xy=True).transform
    basin_m = transform(to_metric, basin)
    buffer_m = basin_m.buffer(BUFFER_KM * 1000.0)
    download = transform(to_wgs84, buffer_m)

    minx, miny, maxx, maxy = basin.bounds
    dminx, dminy, dmaxx, dmaxy = download.bounds

    mask_payload = feature_collection(
        basin,
        {
            "domain": "G040 hydrologic computation mask",
            "rule": "strict basin union; no outside-buffer or buffer-only area contributes runoff",
            "source": str(SOURCE.relative_to(ROOT)),
        },
    )
    buffer_payload = feature_collection(
        download,
        {
            "domain": "G040 meteorological acquisition domain",
            "buffer_km": BUFFER_KM,
            "rule": "may support interpolation/NWP edge context; never adds hydrologic contributing area",
            "source": str(SOURCE.relative_to(ROOT)),
        },
    )

    OUTDIR.mkdir(parents=True, exist_ok=True)
    OUT_MASK.write_text(json.dumps(mask_payload, ensure_ascii=False), encoding="utf-8")
    OUT_BUFFER.write_text(json.dumps(buffer_payload, ensure_ascii=False), encoding="utf-8")

    meta = {
        "schema_version": "g040_spatial_domain_contract_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "research_only": True,
        "source": str(SOURCE.relative_to(ROOT)),
        "source_feature_count": len(geoms),
        "hydrologic_mask": {
            "path": str(OUT_MASK.relative_to(ROOT)),
            "crs": SRC_CRS,
            "bounds_wgs84": [minx, miny, maxx, maxy],
            "area_km2_geometry": round(basin_m.area / 1_000_000.0, 3),
            "rule": "all hydrologic area integration must be clipped to this geometry",
        },
        "meteorological_acquisition": {
            "path": str(OUT_BUFFER.relative_to(ROOT)),
            "buffer_km": BUFFER_KM,
            "metric_crs_used_for_buffer": METRIC_CRS,
            "bounds_wgs84": [dminx, dminy, dmaxx, dmaxy],
            "rule": "download/search gauges and NWP over basin+buffer; clip hydrologic computation back to basin",
        },
        "station_policy": {
            "inside_basin": "eligible for hydrologic observation/assimilation/calibration by variable/QC",
            "inside_buffer_outside_basin": "eligible only for meteorological spatialization/context; never hydrologic contributing area",
            "outside_buffer": "excluded from default meteorological acquisition",
        },
        "grid_policy": {
            "legacy_600_cell_rectangle": "retained for compatibility only",
            "new_rule": "every gridded field must carry inside_basin and inside_download_buffer masks; basin statistics use inside_basin cells/area weights only",
        },
    }
    OUT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "G040_FULL_BASIN_DOMAIN_READY",
        "buffer_km": BUFFER_KM,
        "source_features": len(geoms),
        "geometry_area_km2": meta["hydrologic_mask"]["area_km2_geometry"],
        "basin_bounds": meta["hydrologic_mask"]["bounds_wgs84"],
        "download_bounds": meta["meteorological_acquisition"]["bounds_wgs84"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
