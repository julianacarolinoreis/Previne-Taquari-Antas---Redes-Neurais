#!/usr/bin/env python3
"""Build an isolated Muçum spatial precipitation field from one exact ECMWF IFS Open Data cycle.

This is an audit/forecast forcing builder. It hard-locks the requested IFS cycle,
reads cumulative total precipitation (tp) directly from ECMWF GRIB2 byte ranges,
converts 3-hour accumulations to hourly blocks for the existing hourly HEC-HMS
pilot, and preserves the same 0.25 degree cells intersecting the Muçum basin.

It never falls back to Open-Meteo and fails if the requested cycle is unavailable.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from build_spatial_ifs_mucum import load_basin, build_cells
from ecmwf_direct import _request, _find_tp_entry, _decode_point, ROOT as ECMWF_ROOT

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "previsao_ao_vivo_mucum.json"
OUT = ROOT / "assets/data/estudo_bacia_taquari_antas/spatial_ifs_mucum"
CYCLE_RAW = os.environ.get("IFS_CYCLE_UTC", "2026-09-29T06:00:00Z")
MAX_STEP_H = int(os.environ.get("IFS_MAX_STEP_H", "120"))


def parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)


def requested_cycle() -> datetime:
    dt = parse_utc(CYCLE_RAW)
    if dt.minute or dt.second or dt.microsecond or dt.hour not in (0, 6, 12, 18):
        raise RuntimeError(f"invalid IFS cycle: {CYCLE_RAW}")
    return dt


def forecast_start_hour() -> datetime:
    live = json.loads(LIVE.read_text(encoding="utf-8"))
    raw = live.get("telemetria_ultima_em_utc") or live.get("nivel_rio_agora_em_utc")
    if not raw:
        raise RuntimeError("latest Muçum observation timestamp unavailable")
    return parse_utc(raw).replace(minute=0, second=0, microsecond=0)


def file_url(cycle: datetime, step: int) -> str:
    prefix = f"{ECMWF_ROOT}/{cycle:%Y%m%d}/{cycle:%Hz}/ifs/0p25/oper"
    return f"{prefix}/{cycle:%Y%m%d%H}0000-{step}h-oper-fc.grib2"


def polite_request(url: str, *, byte_range=None) -> bytes:
    last = None
    for attempt in range(1, 8):
        try:
            # ECMWF Open Data rate-limits bursts. Keep this audit deliberately slow.
            time.sleep(1.25 if byte_range is None else 1.75)
            return _request(url, byte_range=byte_range)
        except HTTPError as exc:
            last = exc
            if exc.code != 429 or attempt == 7:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                pause = max(float(retry_after), attempt * 6.0) if retry_after else attempt * 6.0
            except Exception:
                pause = attempt * 6.0
            print(f"ECMWF 429 em {url}; nova tentativa {attempt}/7 após {pause:.1f}s", flush=True)
            time.sleep(pause)
    raise RuntimeError(f"ECMWF request failed: {last}")


def read_cumulative(cycle: datetime, step: int, cells: list[dict]) -> dict[str, float]:
    url = file_url(cycle, step)
    idx_url = url.replace(".grib2", ".index")
    idx = polite_request(idx_url).decode("utf-8")
    entry = _find_tp_entry(idx, step)
    offset, length = int(entry["_offset"]), int(entry["_length"])
    payload = polite_request(url, byte_range=(offset, offset + length - 1))
    values = {}
    for cell in cells:
        p = _decode_point(payload, latitude=float(cell["latitude"]), longitude=float(cell["longitude"]))
        mm = p.get("rain_mm")
        if mm is None:
            raise RuntimeError(f"non-finite tp at {cell['cell_id']} step {step}")
        values[cell["cell_id"]] = float(mm)
    return values


def main() -> None:
    cycle = requested_cycle()
    start = forecast_start_hour()
    if start < cycle:
        start = cycle
    if start >= cycle + timedelta(hours=MAX_STEP_H):
        raise RuntimeError("live observation lies outside requested IFS horizon")

    basin = load_basin()
    cells, basin_area, overlap_sum = build_cells(basin)
    by_id = {c["cell_id"]: c for c in cells}

    steps = list(range(3, MAX_STEP_H + 1, 3))
    prev = {cid: 0.0 for cid in by_id}
    hourly = {cid: {} for cid in by_id}

    for step in steps:
        cumulative = read_cumulative(cycle, step, cells)
        bucket_end = cycle + timedelta(hours=step)
        bucket_start = bucket_end - timedelta(hours=3)
        for cid, total in cumulative.items():
            inc = total - prev[cid]
            if inc < -0.05:
                raise RuntimeError(f"negative tp increment {inc:.3f} mm for {cid} at +{step}h")
            inc = max(0.0, inc)
            per_hour = inc / 3.0
            for k in range(3):
                hour = bucket_start + timedelta(hours=k)
                if hour >= start:
                    hourly[cid][hour] = per_hour
            prev[cid] = total

    times = []
    t = start
    end = cycle + timedelta(hours=MAX_STEP_H)
    while t < end:
        times.append(t)
        t += timedelta(hours=1)
    if not times:
        raise RuntimeError("empty direct IFS forecast window")

    cell_rows = []
    basin_hourly = []
    total_area = sum(float(c["overlap_km2"]) for c in cells)
    for hour in times:
        basin_hourly.append(
            sum(hourly[cid].get(hour, 0.0) * float(by_id[cid]["overlap_km2"]) for cid in by_id) / total_area
        )

    for cell in cells:
        cid = cell["cell_id"]
        vals = [round(float(hourly[cid].get(t, 0.0)), 4) for t in times]
        total = sum(vals)
        cell_rows.append({
            "cell_id": cid,
            "latitude": cell["latitude"],
            "longitude": cell["longitude"],
            "overlap_km2": round(float(cell["overlap_km2"]), 4),
            "overlap_fraction": round(float(cell["overlap_fraction"]), 6),
            "total_120h_mm": round(total, 3),
            "rain_volume_hm3": round(total * float(cell["overlap_km2"]) * 0.001, 6),
            "precip_mm": vals,
        })

    totals = [c["total_120h_mm"] for c in cell_rows]
    basin_total = sum(basin_hourly)
    rain24 = sum(basin_hourly[:24])
    summary = {
        "schema_version": "spatial_ifs_mucum_v1_direct_ecmwf_cycle_locked",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "spatial_rain_field_ready",
        "purpose": "Campo espacial ECMWF IFS direto, ciclo explicitamente travado, para rerodagem HEC-HMS de Muçum.",
        "source": {
            "provider": "ECMWF Open Data",
            "model": "IFS",
            "resolution_deg": 0.25,
            "variable": "tp",
            "cycle_time_utc": cycle.isoformat().replace("+00:00", "Z"),
            "cycle_locked": True,
            "source_root": ECMWF_ROOT,
            "temporal_native_resolution_h": 3,
            "hourly_disaggregation": "cada incremento acumulado de 3 h foi dividido uniformemente nas 3 horas do bloco para compatibilidade com o HEC-HMS horário",
            "fallback_used": False,
        },
        "window": {
            "start_utc": times[0].isoformat().replace("+00:00", "Z"),
            "end_utc": times[-1].isoformat().replace("+00:00", "Z"),
            "hours": len(times),
            "times_utc": [x.isoformat().replace("+00:00", "Z") for x in times],
        },
        "grid": {
            "intersecting_cells": len(cell_rows),
            "basin_area_projected_km2": round(basin_area, 3),
            "sum_cell_overlap_km2": round(overlap_sum, 3),
            "coverage_ratio": round(overlap_sum / basin_area, 6),
            "spatial_field_preserved": True,
            "collapsed_to_single_basin_series_for_model": False,
        },
        "rainfall_24h": {
            "equivalent_basin_depth_mm": round(rain24, 3),
            "hours_available": min(24, len(times)),
        },
        "rainfall_120h": {
            "cell_total_min_mm": round(min(totals), 3),
            "cell_total_median_mm": round(sorted(totals)[len(totals)//2], 3),
            "cell_total_max_mm": round(max(totals), 3),
            "equivalent_basin_depth_mm_for_audit_only": round(basin_total, 3),
        },
        "basin_hourly_mm": [round(x, 4) for x in basin_hourly],
        "cells": cell_rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "spatial_ifs_mucum_direct_06z_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # The HEC builder reads this canonical path. In the isolated workflow it is
    # replaced only in the runner workspace, then the canonical Open-Meteo file
    # is restored before publication.
    (OUT / "spatial_ifs_mucum_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "cycle_time_utc": summary["source"]["cycle_time_utc"],
        "start_utc": summary["window"]["start_utc"],
        "hours": summary["window"]["hours"],
        "cells": summary["grid"]["intersecting_cells"],
        "basin_rain_next_24h_mm": summary["rainfall_24h"]["equivalent_basin_depth_mm"],
        "basin_rain_to_120h_end_mm": summary["rainfall_120h"]["equivalent_basin_depth_mm_for_audit_only"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
