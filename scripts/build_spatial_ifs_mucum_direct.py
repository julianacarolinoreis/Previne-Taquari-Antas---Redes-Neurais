#!/usr/bin/env python3
"""Build Muçum spatial precipitation directly from the latest ECMWF IFS Open Data cycle.

The output schema is compatible with build_hec_hms_spatial_forecast_mucum.py.
For accumulated total precipitation (tp), increments between available forecast
steps are distributed uniformly across the covered hours. This is explicit
temporal disaggregation, not duplication of accumulated totals.
"""

from __future__ import annotations

import json
import math
import re
import time
from urllib.error import HTTPError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import eccodes

from build_spatial_ifs_mucum import ROOT, OUT, LIVE, load_basin, build_cells
from ecmwf_direct import _find_cycle, _request, _find_tp_entry

USER_AGENT = "PREVINE-spatial-ifs-direct/1.0"
MAX_STEP_H = 48


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _current_hour() -> datetime:
    live = json.loads(LIVE.read_text(encoding="utf-8"))
    raw = live.get("telemetria_ultima_em_utc") or live.get("nivel_rio_agora_em_utc")
    if not raw:
        raise RuntimeError("Muçum live observation timestamp unavailable")
    return _parse_utc(raw).replace(minute=0, second=0, microsecond=0)


def _latest_cycle(now: datetime):
    # Reuse the independently audited selector. It already confirms the newest
    # cycle with +24/+48/+72/+120 h available, including 06Z/18Z.
    cycle, prefix, _ = _find_cycle(now)
    # Probe all integer lead times; unavailable files are skipped later.
    steps = {
        h: f"{cycle:%Y%m%d%H}0000-{h}h-oper-fc.grib2"
        for h in range(3, MAX_STEP_H + 1, 3)
    }
    return cycle, prefix, steps

def _decode_points(payload: bytes, cells: list[dict]) -> dict[str, float]:
    handle = eccodes.codes_new_from_message(payload)
    try:
        values = eccodes.codes_get_array(handle, "values")
        units = str(eccodes.codes_get(handle, "units"))
        if units.lower() not in {"m", "metre", "meter"}:
            raise RuntimeError(f"unexpected tp unit: {units}")
        ni = int(eccodes.codes_get(handle, "Ni"))
        nj = int(eccodes.codes_get(handle, "Nj"))
        lat1 = float(eccodes.codes_get(handle, "latitudeOfFirstGridPointInDegrees"))
        lon1 = float(eccodes.codes_get(handle, "longitudeOfFirstGridPointInDegrees"))
        di = abs(float(eccodes.codes_get(handle, "iDirectionIncrementInDegrees")))
        dj = abs(float(eccodes.codes_get(handle, "jDirectionIncrementInDegrees")))
        j_positive = int(eccodes.codes_get(handle, "jScansPositively")) == 1
        i_negative = int(eccodes.codes_get(handle, "iScansNegatively")) == 1
        j_consecutive = int(eccodes.codes_get(handle, "jPointsAreConsecutive")) == 1

        out = {}
        for cell in cells:
            lat = float(cell["latitude"])
            lon = float(cell["longitude"])
            target_lon = lon % 360.0
            first_lon = lon1 % 360.0
            if i_negative:
                i = int(round(((first_lon - target_lon) % 360.0) / di)) % ni
            else:
                i = int(round(((target_lon - first_lon) % 360.0) / di)) % ni
            j = int(round((lat - lat1) / dj)) if j_positive else int(round((lat1 - lat) / dj))
            j = max(0, min(nj - 1, j))
            idx = i * nj + j if j_consecutive else j * ni + i
            raw = float(values[idx])
            if not math.isfinite(raw):
                raise RuntimeError(f"non-finite tp for {cell['cell_id']}")
            out[cell["cell_id"]] = raw * 1000.0
        return out
    finally:
        eccodes.codes_release(handle)


def _request_with_backoff(url: str, *, byte_range=None) -> bytes:
    """Retry ECMWF throttling without silently changing forecast cycle."""
    for attempt in range(5):
        try:
            return _request(url, byte_range=byte_range)
        except HTTPError as exc:
            if exc.code != 429 or attempt == 4:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("ECMWF request retry exhausted")


def _fetch_cumulative(prefix: str, steps: dict[int, str], cells: list[dict]) -> dict[int, dict[str, float]]:
    out = {0: {c["cell_id"]: 0.0 for c in cells}}
    # Use all available steps. For 06Z/18Z, resolution may vary with lead time.
    for h in sorted(k for k in steps if 0 < k <= MAX_STEP_H):
        filename = steps[h]
        file_url = f"{prefix}/{filename}"
        index_url = file_url.replace(".grib2", ".index")
        try:
            entry = _find_tp_entry(_request_with_backoff(index_url).decode("utf-8"), h)
        except Exception:
            # Skip files whose index does not expose tp for this exact step.
            continue
        offset = int(entry["_offset"])
        length = int(entry["_length"])
        payload = _request_with_backoff(file_url, byte_range=(offset, offset + length - 1))
        out[h] = _decode_points(payload, cells)
        # Be polite to the public endpoint and stay below burst throttles.
        time.sleep(1.0)
    max_step = max(out) if out else 0
    if 24 not in out or 48 not in out:
        raise RuntimeError(
            f"latest ECMWF cycle did not yield direct +24 h and +48 h forcing (max={max_step})"
        )
    return out


def _hourly_from_cumulative(cycle: datetime, current_hour: datetime, cells: list[dict], cumulative):
    step_hours = sorted(cumulative)
    by_cell = {c["cell_id"]: {} for c in cells}
    for a, b in zip(step_hours[:-1], step_hours[1:]):
        if b <= a:
            continue
        span = b - a
        for c in cells:
            cid = c["cell_id"]
            delta = float(cumulative[b][cid]) - float(cumulative[a][cid])
            # Numerical GRIB packing can occasionally create tiny negative deltas.
            delta = max(0.0, delta)
            hourly = delta / span
            for ending_h in range(a + 1, b + 1):
                interval_start = cycle + timedelta(hours=ending_h - 1)
                by_cell[cid][interval_start] = hourly

    end_hour = cycle + timedelta(hours=max(step_hours))
    times = []
    t = current_hour
    while t < end_hour:
        times.append(t)
        t += timedelta(hours=1)
    if not times:
        raise RuntimeError("ECMWF cycle has no future hours after current observation")

    fetched = []
    for c in cells:
        cid = c["cell_id"]
        vals = [round(float(by_cell[cid].get(t, 0.0)), 4) for t in times]
        fetched.append({
            **c,
            "times_utc": [t.isoformat().replace("+00:00", "Z") for t in times],
            "precip_mm": vals,
            "total_forecast_mm": round(sum(vals), 3),
        })
    return times, fetched


def _write(cycle, basin_area, overlap_sum, cells):
    OUT.mkdir(parents=True, exist_ok=True)
    times = [_parse_utc(x) for x in cells[0]["times_utc"]]
    total_volume = sum(sum(c["precip_mm"]) * c["overlap_km2"] * 0.001 for c in cells)
    equivalent = total_volume / basin_area * 1000.0 if basin_area else None
    summary = {
        "schema_version": "spatial_ifs_mucum_v2_ecmwf_direct_48h",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "spatial_rain_field_ready",
        "purpose": "Campo espacial direto da rodada ECMWF IFS Open Data mais recente sobre a bacia contribuinte até Muçum.",
        "source": {
            "model": "ECMWF IFS Open Data 0.25° DIRECT",
            "cycle_time_utc": cycle.isoformat().replace("+00:00", "Z"),
            "variable": "tp",
            "temporal_processing": "diferenca de acumulados entre passos de 3 h; desagregacao uniforme dentro de cada bloco de 3 h",
        },
        "window": {
            "start_utc": times[0].isoformat().replace("+00:00", "Z"),
            "end_utc": times[-1].isoformat().replace("+00:00", "Z"),
            "hours": len(times),
            "times_utc": [t.isoformat().replace("+00:00", "Z") for t in times],
        },
        "grid": {
            "resolution_deg": 0.25,
            "intersecting_cells": len(cells),
            "basin_area_projected_km2": round(basin_area, 3),
            "sum_cell_overlap_km2": round(overlap_sum, 3),
            "coverage_ratio": round(overlap_sum / basin_area, 6) if basin_area else None,
            "spatial_field_preserved": True,
            "collapsed_to_single_basin_series_for_model": False,
        },
        "rainfall_120h": {
            "equivalent_basin_depth_mm_for_audit_only": round(equivalent, 3) if equivalent is not None else None,
            "total_rain_volume_hm3_over_basin": round(total_volume, 3),
            "note": "Profundidade equivalente apenas para auditoria; o HEC usa o campo espacial por celula.",
        },
        "cells": [{
            "cell_id": c["cell_id"],
            "latitude": c["latitude"],
            "longitude": c["longitude"],
            "overlap_km2": round(c["overlap_km2"], 4),
            "overlap_fraction": round(c["overlap_fraction"], 6),
            "precip_mm": c["precip_mm"],
            "total_forecast_mm": c["total_forecast_mm"],
            # Backward-compatible alias; when a 06Z/18Z cycle ends before
            # +120 h this value is the total over the actual window above.
            "total_120h_mm": c["total_forecast_mm"],
        } for c in cells],
    }
    (OUT / "spatial_ifs_mucum_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": summary["status"],
        "source": summary["source"],
        "hours": len(times),
        "intersecting_cells": len(cells),
        "equivalent_basin_depth_mm": summary["rainfall_120h"]["equivalent_basin_depth_mm_for_audit_only"],
    }, ensure_ascii=False))


def main():
    now = datetime.now(timezone.utc)
    current_hour = _current_hour()
    basin = load_basin()
    cells, basin_area, overlap_sum = build_cells(basin)
    cycle, prefix, steps = _latest_cycle(now)
    cumulative = _fetch_cumulative(prefix, steps, cells)
    _, fetched = _hourly_from_cumulative(cycle, current_hour, cells, cumulative)
    _write(cycle, basin_area, overlap_sum, fetched)


if __name__ == "__main__":
    main()
