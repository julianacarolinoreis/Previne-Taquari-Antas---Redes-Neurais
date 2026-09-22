#!/usr/bin/env python3
"""Build spatial ECMWF/IFS precipitation forcing over the full Muçum catchment.

Unlike the legacy HEC-twin forcing, this script does NOT replace the catchment
with a handful of point proxies and does NOT collapse the spatial field into a
single rainfall series. It preserves every 0.25° IFS grid cell intersecting the
catchment upstream of ANA station 86510000.

Outputs are research diagnostics. They are not an official flood alert and are
not, by themselves, an executable replacement for the original 145-subbasin
HEC-HMS project.
"""

from __future__ import annotations

import csv
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.collections import PatchCollection
from pyproj import Transformer
from shapely.geometry import box, shape, mapping
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
WATERSHED = ROOT / "assets/data/hec_hms_spatialized_mucum/watershed_86510000_srtm.geojson"
OUT = ROOT / "assets/data/estudo_bacia_taquari_antas/spatial_ifs_mucum"
HORIZON_HOURS = 120
GRID_DEG = 0.25
HALF = GRID_DEG / 2.0
USER_AGENT = "PREVINE-spatial-ifs-mucum-research/1.0"
PROJECT = Transformer.from_crs("EPSG:4326", "EPSG:31982", always_xy=True).transform


def utc_now_hour() -> datetime:
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def load_basin():
    data = json.loads(WATERSHED.read_text(encoding="utf-8"))
    geoms = [shape(f["geometry"]) for f in data.get("features", []) if f.get("geometry")]
    if not geoms:
        raise RuntimeError("watershed GeoJSON has no geometry")
    geom = unary_union(geoms)
    if geom.is_empty:
        raise RuntimeError("watershed geometry is empty")
    return geom


def grid_centers(lo: float, hi: float) -> list[float]:
    start = math.floor((lo - HALF) / GRID_DEG) * GRID_DEG
    end = math.ceil((hi + HALF) / GRID_DEG) * GRID_DEG
    vals = []
    x = start
    while x <= end + 1e-10:
        vals.append(round(x, 6))
        x += GRID_DEG
    return vals


def build_cells(basin):
    basin_proj = transform(PROJECT, basin)
    minx, miny, maxx, maxy = basin.bounds
    lons = grid_centers(minx, maxx)
    lats = grid_centers(miny, maxy)
    cells = []
    for lat in lats:
        for lon in lons:
            cell = box(lon - HALF, lat - HALF, lon + HALF, lat + HALF)
            inter = basin.intersection(cell)
            if inter.is_empty:
                continue
            inter_proj = transform(PROJECT, inter)
            overlap_km2 = inter_proj.area / 1_000_000.0
            if overlap_km2 < 0.001:
                continue
            cell_proj = transform(PROJECT, cell)
            cell_km2 = cell_proj.area / 1_000_000.0
            cells.append({
                "cell_id": f"IFS_{lat:+07.2f}_{lon:+07.2f}",
                "latitude": lat,
                "longitude": lon,
                "cell_bounds": [lon-HALF, lat-HALF, lon+HALF, lat+HALF],
                "overlap_km2": overlap_km2,
                "overlap_fraction": overlap_km2 / cell_km2 if cell_km2 else 0.0,
                "geometry": mapping(cell),
            })
    if not cells:
        raise RuntimeError("no IFS cells intersect watershed")
    overlap_sum = sum(c["overlap_km2"] for c in cells)
    basin_area = basin_proj.area / 1_000_000.0
    return cells, basin_area, overlap_sum


def _parse_hour(raw: str) -> datetime:
    raw = str(raw)
    if raw.endswith("Z"):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fetch_batch(points: list[dict], start_utc: datetime) -> list[dict]:
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
    payload = None
    last_exc = None
    for attempt in range(1, 5):
        try:
            with urlopen(req, timeout=90) as resp:
                payload = json.load(resp)
            break
        except Exception as exc:
            last_exc = exc
            if attempt == 4:
                raise RuntimeError(f"Open-Meteo IFS batch failed: {exc}") from exc
            time.sleep(attempt * 5)
    if payload is None:
        raise RuntimeError(f"empty IFS payload: {last_exc}")
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or len(payload) != len(points):
        raise RuntimeError(f"IFS batch response count mismatch: got {type(payload)} len={len(payload) if isinstance(payload,list) else 'n/a'}, expected {len(points)}")

    out = []
    for point, item in zip(points, payload):
        hourly = item.get("hourly") or {}
        times = list(hourly.get("time") or [])
        rain = list(hourly.get("precipitation") or [])
        if len(times) != len(rain):
            raise RuntimeError(f"time/rain mismatch for {point['cell_id']}")
        rows = [(_parse_hour(t), float(v or 0.0)) for t, v in zip(times, rain)]
        rows = [(t, v) for t, v in rows if t >= start_utc]
        if len(rows) < HORIZON_HOURS:
            raise RuntimeError(f"not enough forecast hours for {point['cell_id']}: {len(rows)}")
        rows = rows[:HORIZON_HOURS]
        out.append({
            **point,
            "times_utc": [t.isoformat().replace("+00:00", "Z") for t, _ in rows],
            "precip_mm": [round(v, 4) for _, v in rows],
        })
    return out


def fetch_all(cells, start_utc):
    fetched = []
    batch_size = 40
    for i in range(0, len(cells), batch_size):
        fetched.extend(fetch_batch(cells[i:i+batch_size], start_utc))
    return fetched


def percentile(values, p):
    vals = sorted(values)
    if not vals:
        return None
    k = (len(vals)-1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return vals[int(k)]
    return vals[f] * (c-k) + vals[c] * (k-f)


def write_outputs(basin, cells, basin_area, overlap_sum, start_utc):
    OUT.mkdir(parents=True, exist_ok=True)
    times = cells[0]["times_utc"]
    for c in cells:
        if c["times_utc"] != times:
            raise RuntimeError("forecast time grids differ between IFS cells")

    totals = []
    for c in cells:
        total = sum(c["precip_mm"])
        c["total_120h_mm"] = round(total, 3)
        c["rain_volume_hm3"] = round(total * c["overlap_km2"] * 0.001, 6)
        totals.append(total)

    hourly_volume_hm3 = []
    for h in range(HORIZON_HOURS):
        volume = sum(c["precip_mm"][h] * c["overlap_km2"] * 0.001 for c in cells)
        hourly_volume_hm3.append(round(volume, 6))

    total_volume = sum(c["rain_volume_hm3"] for c in cells)
    effective_depth_equivalent = total_volume / basin_area * 1000.0 if basin_area else None

    summary = {
        "schema_version": "spatial_ifs_mucum_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "spatial_rain_field_ready",
        "purpose": "Campo espacial completo de precipitação ECMWF IFS 0.25° sobre a bacia contribuinte até Muçum/86510000.",
        "warning": "Pesquisa. Não é alerta oficial. Ainda não é a execução do projeto HEC-HMS original de 145 sub-bacias porque os arquivos/polígonos desse projeto não estão no repositório.",
        "source": {
            "model": "ECMWF IFS 0.25° via Open-Meteo",
            "variable": "hourly precipitation",
            "watershed": str(WATERSHED.relative_to(ROOT)),
            "watershed_source_note": "SRTM/WhiteboxTools watershed already stored in repository",
        },
        "window": {
            "start_utc": times[0],
            "end_utc": times[-1],
            "hours": HORIZON_HOURS,
        },
        "grid": {
            "resolution_deg": GRID_DEG,
            "intersecting_cells": len(cells),
            "basin_area_projected_km2": round(basin_area, 3),
            "sum_cell_overlap_km2": round(overlap_sum, 3),
            "coverage_ratio": round(overlap_sum / basin_area, 6) if basin_area else None,
            "spatial_field_preserved": True,
            "collapsed_to_single_basin_series_for_model": False,
        },
        "rainfall_120h": {
            "cell_total_min_mm": round(min(totals), 3),
            "cell_total_p25_mm": round(percentile(totals, 0.25), 3),
            "cell_total_median_mm": round(percentile(totals, 0.50), 3),
            "cell_total_p75_mm": round(percentile(totals, 0.75), 3),
            "cell_total_max_mm": round(max(totals), 3),
            "total_rain_volume_hm3_over_basin": round(total_volume, 3),
            "equivalent_basin_depth_mm_for_audit_only": round(effective_depth_equivalent, 3) if effective_depth_equivalent is not None else None,
            "note": "A profundidade equivalente é apenas auditoria volumétrica. O campo célula-a-célula permanece nos artefatos e não deve ser substituído por essa média na modelagem.",
        },
        "hourly_total_rain_volume_hm3": hourly_volume_hm3,
        "cells": [
            {
                "cell_id": c["cell_id"],
                "latitude": c["latitude"],
                "longitude": c["longitude"],
                "overlap_km2": round(c["overlap_km2"], 4),
                "overlap_fraction": round(c["overlap_fraction"], 6),
                "total_120h_mm": c["total_120h_mm"],
                "rain_volume_hm3": c["rain_volume_hm3"],
                "precip_mm": c["precip_mm"],
            }
            for c in cells
        ],
    }
    (OUT / "spatial_ifs_mucum_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with (OUT / "spatial_ifs_mucum_cells_120h.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cell_id","latitude","longitude","overlap_km2","overlap_fraction","total_120h_mm","rain_volume_hm3"])
        for c in cells:
            w.writerow([c["cell_id"],c["latitude"],c["longitude"],round(c["overlap_km2"],4),round(c["overlap_fraction"],6),c["total_120h_mm"],c["rain_volume_hm3"]])

    with (OUT / "spatial_ifs_mucum_hourly.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_utc","cell_id","latitude","longitude","overlap_km2","precip_mm"])
        for c in cells:
            for t, mm in zip(times, c["precip_mm"]):
                w.writerow([t,c["cell_id"],c["latitude"],c["longitude"],round(c["overlap_km2"],4),mm])

    features = []
    for c in cells:
        features.append({
            "type": "Feature",
            "geometry": c["geometry"],
            "properties": {
                "cell_id": c["cell_id"],
                "latitude": c["latitude"],
                "longitude": c["longitude"],
                "overlap_km2": round(c["overlap_km2"],4),
                "overlap_fraction": round(c["overlap_fraction"],6),
                "total_120h_mm": c["total_120h_mm"],
                "rain_volume_hm3": c["rain_volume_hm3"],
            },
        })
    (OUT / "spatial_ifs_mucum_cells_120h.geojson").write_text(
        json.dumps({"type":"FeatureCollection","features":features}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Diagnostic spatial map. Cell color = forecast total, boundary = catchment.
    fig, ax = plt.subplots(figsize=(9, 8))
    patches, values = [], []
    for c in cells:
        xmin, ymin, xmax, ymax = c["cell_bounds"]
        patches.append(MplPolygon([(xmin,ymin),(xmax,ymin),(xmax,ymax),(xmin,ymax)], closed=True))
        values.append(c["total_120h_mm"])
    pc = PatchCollection(patches, cmap="viridis", edgecolor="white", linewidth=0.7)
    pc.set_array(values)
    ax.add_collection(pc)
    boundary = basin.boundary
    geoms = list(boundary.geoms) if hasattr(boundary, "geoms") else [boundary]
    for g in geoms:
        try:
            xs, ys = g.xy
            ax.plot(xs, ys, color="black", linewidth=1.2)
        except Exception:
            pass
    ax.autoscale()
    ax.set_aspect("equal", adjustable="box")
    ax.set_title("Muçum (86510000) — precipitação IFS espacial, 120 h")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    cb = fig.colorbar(pc, ax=ax, shrink=0.8)
    cb.set_label("Precipitação acumulada por célula (mm)")
    fig.tight_layout()
    fig.savefig(OUT / "spatial_ifs_mucum_120h.png", dpi=180)
    plt.close(fig)

    print(json.dumps({
        "status": summary["status"],
        "intersecting_cells": len(cells),
        "basin_area_km2": round(basin_area,3),
        "coverage_ratio": summary["grid"]["coverage_ratio"],
        "rain_min_mm": summary["rainfall_120h"]["cell_total_min_mm"],
        "rain_median_mm": summary["rainfall_120h"]["cell_total_median_mm"],
        "rain_max_mm": summary["rainfall_120h"]["cell_total_max_mm"],
        "total_rain_volume_hm3": summary["rainfall_120h"]["total_rain_volume_hm3_over_basin"],
        "audit_equivalent_depth_mm": summary["rainfall_120h"]["equivalent_basin_depth_mm_for_audit_only"],
    }, ensure_ascii=False))


def main():
    basin = load_basin()
    cells, basin_area, overlap_sum = build_cells(basin)
    start = utc_now_hour()
    fetched = fetch_all(cells, start)
    write_outputs(basin, fetched, basin_area, overlap_sum, start)


if __name__ == "__main__":
    main()
