#!/usr/bin/env python3
"""Download an ECMWF/IFS precipitation field for the full G040+buffer domain.

The download grid is derived from the buffered basin geometry, not from a fixed
rectangle chosen by a downstream station. Every cell carries its intersection
with the strict G040 mask. Buffer-only cells are retained for meteorological
edge context/maps but have zero hydrologic contributing weight.
"""
from __future__ import annotations

import csv
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pyproj import Transformer
from shapely.geometry import Point, box, shape
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "assets/data/hec_hms_g040_full_basin"
MASK = BASE / "g040_basin_mask.geojson"
BUFFER = BASE / "g040_download_buffer.geojson"
OUT = BASE / "g040_ecmwf_buffer_grid_latest.json"
OUTCSV = BASE / "g040_ecmwf_buffer_hourly.csv"

STEP = float(os.environ.get("G040_MET_GRID_STEP_DEG", "0.1"))
HORIZON_HOURS = int(os.environ.get("G040_ECMWF_HORIZON_HOURS", "120"))
BATCH_SIZE = int(os.environ.get("G040_ECMWF_BATCH_SIZE", "40"))
USER_AGENT = "PREVINE-G040-buffered-IFS-research/1.0"
METRIC_CRS = "EPSG:31982"


def load_union(path: Path):
    j = json.loads(path.read_text(encoding="utf-8"))
    geoms = [shape(f["geometry"]) for f in (j.get("features") or []) if f.get("geometry")]
    if not geoms:
        raise RuntimeError(f"no geometry in {path}")
    g = unary_union(geoms)
    return g.buffer(0) if not g.is_valid else g


def floor_step(v: float, step: float) -> float:
    return math.floor(v / step) * step


def ceil_step(v: float, step: float) -> float:
    return math.ceil(v / step) * step


def build_cells(basin, download):
    minx, miny, maxx, maxy = download.bounds
    west, south = floor_step(minx, STEP), floor_step(miny, STEP)
    east, north = ceil_step(maxx, STEP), ceil_step(maxy, STEP)

    to_metric = Transformer.from_crs("EPSG:4326", METRIC_CRS, always_xy=True).transform
    basin_m = transform(to_metric, basin)
    download_m = transform(to_metric, download)

    rows = int(round((north - south) / STEP))
    cols = int(round((east - west) / STEP))
    cells = []
    for row in range(rows):
        y0 = south + row * STEP
        y1 = y0 + STEP
        lat = (y0 + y1) / 2.0
        for col in range(cols):
            x0 = west + col * STEP
            x1 = x0 + STEP
            lon = (x0 + x1) / 2.0
            p = Point(lon, lat)
            poly = box(x0, y0, x1, y1)
            poly_m = transform(to_metric, poly)
            buffer_intersection = poly_m.intersection(download_m).area
            if buffer_intersection <= 0:
                continue
            basin_intersection = poly_m.intersection(basin_m).area
            cell_area = poly_m.area
            cells.append({
                "cell_id": f"BUF_R{row:02d}_C{col:02d}",
                "row": row,
                "col": col,
                "latitude": round(lat, 6),
                "longitude": round(lon, 6),
                "inside_basin_center": bool(basin.covers(p)),
                "inside_download_buffer_center": bool(download.covers(p)),
                "cell_area_km2": round(cell_area / 1_000_000.0, 6),
                "basin_intersection_km2": round(basin_intersection / 1_000_000.0, 6),
                "basin_area_fraction": round(basin_intersection / cell_area, 8) if cell_area else 0.0,
            })
    if not cells:
        raise RuntimeError("buffered ECMWF grid has no cells")
    return cells, {"west": west, "east": east, "south": south, "north": north, "rows": rows, "cols": cols}


def parse_hour(raw: str) -> datetime:
    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fetch_batch(points, start_utc):
    params = {
        "latitude": ",".join(f"{p['latitude']:.4f}" for p in points),
        "longitude": ",".join(f"{p['longitude']:.4f}" for p in points),
        "models": "ecmwf_ifs025",
        "hourly": "precipitation",
        "forecast_days": 7,
        "timezone": "UTC",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode(params)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    last = None
    for attempt in range(1, 5):
        try:
            with urlopen(req, timeout=90) as resp:
                payload = json.load(resp)
            break
        except Exception as exc:
            last = exc
            if attempt == 4:
                raise RuntimeError(f"ECMWF buffer batch failed: {exc}") from exc
            time.sleep(attempt * 4)
    else:
        raise RuntimeError(f"ECMWF buffer empty payload: {last}")

    if isinstance(payload, dict):
        payload = [payload]
    if len(payload) != len(points):
        raise RuntimeError(f"ECMWF buffer response mismatch {len(payload)} != {len(points)}")

    out = []
    for point, item in zip(points, payload):
        h = item.get("hourly") or {}
        times, rain = list(h.get("time") or []), list(h.get("precipitation") or [])
        rows = []
        for t, v in zip(times, rain):
            dt = parse_hour(t)
            if dt < start_utc:
                continue
            if v is None:
                rows.append((dt, None))
            else:
                x = float(v)
                rows.append((dt, x if math.isfinite(x) and x >= 0 else None))
        rows = rows[:HORIZON_HOURS]
        if len(rows) < HORIZON_HOURS or any(v is None for _, v in rows):
            raise RuntimeError(f"{point['cell_id']}: incomplete ECMWF precipitation")
        out.append({
            **point,
            "response_latitude": item.get("latitude"),
            "response_longitude": item.get("longitude"),
            "times_utc": [t.isoformat().replace("+00:00", "Z") for t, _ in rows],
            "precip_mm": [round(float(v), 4) for _, v in rows],
        })
    return out


def fetch_all(cells, start):
    out = []
    for i in range(0, len(cells), BATCH_SIZE):
        out.extend(fetch_batch(cells[i:i+BATCH_SIZE], start))
        if i + BATCH_SIZE < len(cells):
            time.sleep(0.25)
    return out


def accum(values, n):
    vals = values[:n]
    return round(sum(vals), 3) if len(vals) == n else None


def main() -> int:
    if not MASK.exists() or not BUFFER.exists():
        raise RuntimeError("run build_g040_spatial_domain.py first")
    basin = load_union(MASK)
    download = load_union(BUFFER)
    cells, bounds = build_cells(basin, download)
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    fetched = fetch_all(cells, start)
    times = fetched[0]["times_utc"]
    if any(x["times_utc"] != times for x in fetched):
        raise RuntimeError("ECMWF buffer cell time axes differ")

    with OUTCSV.open("w", encoding="utf-8", newline="") as fh:
        fields = ["time_utc", *[x["cell_id"] for x in fetched]]
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for h, t in enumerate(times):
            row = {"time_utc": t}
            for cell in fetched:
                row[cell["cell_id"]] = cell["precip_mm"][h]
            w.writerow(row)

    cell_meta = []
    total_basin_area = sum(float(c["basin_intersection_km2"]) for c in fetched)
    for c in fetched:
        vals = c["precip_mm"]
        cell_meta.append({
            k: c[k] for k in (
                "cell_id", "row", "col", "latitude", "longitude",
                "inside_basin_center", "inside_download_buffer_center",
                "cell_area_km2", "basin_intersection_km2", "basin_area_fraction",
                "response_latitude", "response_longitude"
            )
        } | {
            "forecast_accumulations_mm": {
                "6h": accum(vals, 6),
                "12h": accum(vals, 12),
                "24h": accum(vals, 24),
                "48h": accum(vals, 48),
                "72h": accum(vals, 72),
                "120h": accum(vals, 120),
            }
        })

    basin_weighted = {}
    for n in (6, 12, 24, 48, 72, 120):
        if n > HORIZON_HOURS:
            continue
        numerator = 0.0
        denominator = 0.0
        for c in fetched:
            a = float(c["basin_intersection_km2"])
            if a <= 0:
                continue
            numerator += sum(c["precip_mm"][:n]) * a
            denominator += a
        basin_weighted[f"{n}h_mm"] = round(numerator / denominator, 3) if denominator else None

    payload = {
        "schema_version": "g040_ecmwf_buffer_grid_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "research_only": True,
        "status": "ECMWF_G040_BUFFER_FIELD_READY_CYCLE_ID_UNVERIFIED",
        "domain": {
            "hydrologic_mask": str(MASK.relative_to(ROOT)),
            "download_buffer": str(BUFFER.relative_to(ROOT)),
            "step_deg": STEP,
            "bounds": bounds,
            "cell_count": len(fetched),
            "cells_with_g040_area": sum(float(c["basin_intersection_km2"]) > 0 for c in fetched),
            "represented_g040_area_km2_cell_intersections": round(total_basin_area, 3),
            "hydrologic_rule": "only basin_intersection_km2 contributes to G040 aggregate/forcing; buffer-only cells are meteorological context",
        },
        "source": {
            "provider": "Open-Meteo ECMWF endpoint",
            "model_query": "ecmwf_ifs025",
            "variable": "hourly precipitation",
            "exact_ecmwf_cycle_id": None,
            "cycle_provenance_gate": False,
            "note": "retrieval time is not relabeled as ECMWF cycle",
        },
        "window": {"start_utc": times[0], "end_utc": times[-1], "hours": len(times)},
        "basin_area_weighted_forecast_accumulations": basin_weighted,
        "cells": cell_meta,
        "hourly_csv": str(OUTCSV.relative_to(ROOT)),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "cells": len(fetched),
        "cells_with_g040_area": payload["domain"]["cells_with_g040_area"],
        "buffer_bounds": bounds,
        "basin_24h_mm": basin_weighted.get("24h_mm"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
