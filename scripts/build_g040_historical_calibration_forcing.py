#!/usr/bin/env python3
"""Build event-specific historical forcing packages for G040 E1 calibration.

The builder reuses the same observed-rain provenance and QC functions used by
PREVINE's current whole-basin rain pipeline. It creates a separate forcing
package per fixed benchmark event:

- hourly accumulated observed rain from all eligible in-basin gauges;
- IDW^2 spatialization to the verified BHO6 rain-support mesh;
- area-weighted precipitation for all 11 current branch/core components;
- historical ANA/SGB discharge/level controls;
- an event-specific boundary scenario that activates a tributary Source only
  when the exact branch station has sufficient observed discharge coverage.

This is an intermediate BHO6 branch-model calibration input. It does not replace
or redefine the canonical G040+buffer operational acquisition domain.
Missing rain is never converted to zero.
"""
from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

try:
    from scripts.build_g040_observed_rain_forcing import (
        basin_mask,
        catalog,
        interpolate_points,
        read_support,
        vectorized_idw_matrix,
    )
    from scripts.build_mucum_observed_multistation import (
        BRT,
        UTC,
        aggregate_hourly,
        csv_observed_rain,
        fetch_network,
        inventory_operational,
        qc_rain,
    )
except ModuleNotFoundError:
    from build_g040_observed_rain_forcing import (
        basin_mask,
        catalog,
        interpolate_points,
        read_support,
        vectorized_idw_matrix,
    )
    from build_mucum_observed_multistation import (
        BRT,
        UTC,
        aggregate_hourly,
        csv_observed_rain,
        fetch_network,
        inventory_operational,
        qc_rain,
    )

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "assets/data/hec_hms_g040_full_basin"
STUDY = ROOT / "assets/data/estudo_bacia_taquari_antas"
HYDRO_DIR = BASE / "historical_hydro_events"
OUTROOT = BASE / "historical_calibration_forcing"
MANIFEST = OUTROOT / "manifest_latest.json"

RAIN_CATALOG = STUDY / "pluviometria_g040.geojson"
FLOW_CATALOG = STUDY / "postos_g040.geojson"
BRANCH_CODES = ("86500000", "86595000", "86746000")
SOURCE_PRIMARY = "86472000"

DEFAULT_EVENTS = ("E22_SEP2023", "E24_NOV2023")
MIN_BRANCH_FLOW_COVERAGE = 0.75
MIN_RAIN_STATIONS_FOR_STRONG_HOUR = 3


def parse_local(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=None)


def iso_local(value: datetime) -> str:
    return value.isoformat(timespec="minutes")


def hourly_axis(start: datetime, end: datetime) -> list[datetime]:
    a = start.replace(minute=0, second=0, microsecond=0)
    b = end.replace(minute=0, second=0, microsecond=0)
    out = []
    t = a
    while t <= b:
        out.append(t)
        t += timedelta(hours=1)
    return out


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def historical_hydro(event_id: str) -> dict[str, Any]:
    path = HYDRO_DIR / f"{event_id}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return load_json(path)


def event_window(event: dict[str, Any]) -> tuple[datetime, datetime]:
    w = event.get("window_local") or {}
    return parse_local(str(w["start"])), parse_local(str(w["end"]))


def controls_wrapper(event: dict[str, Any]) -> dict[str, Any]:
    controls = []
    for st in event.get("stations") or []:
        controls.append({
            "code": str(st.get("code") or ""),
            "label": st.get("label"),
            "role": st.get("role"),
            "group": st.get("group"),
            "mass_balance": st.get("mass_balance"),
            "fetch_ok": bool(st.get("fetch_ok")),
            "recent_rows": list(st.get("series") or []),
        })
    return {
        "schema_version": "g040_historical_hydro_controls_wrapper_v1",
        "event_id": event.get("event_id"),
        "research_only": True,
        "source": event.get("source"),
        "controls": controls,
    }


def event_active_boundaries(event: dict[str, Any], expected_hours: int) -> list[str]:
    by_code = {str(x.get("code") or ""): x for x in event.get("stations") or []}
    active = []
    for code in BRANCH_CODES:
        st = by_code.get(code) or {}
        hours = int(st.get("flow_hour_count") or 0)
        coverage = hours / max(expected_hours, 1)
        if bool(st.get("fetch_ok")) and coverage >= MIN_BRANCH_FLOW_COVERAGE:
            active.append(code)
    return active


def rain_candidates() -> dict[str, dict[str, Any]]:
    basin = basin_mask()
    candidates: dict[str, dict[str, Any]] = {}
    for src in (catalog(RAIN_CATALOG, basin), catalog(FLOW_CATALOG, basin)):
        for code, st in src.items():
            if inventory_operational(st):
                candidates.setdefault(code, st)
    return candidates


def fetch_event_rain(
    candidates: dict[str, dict[str, Any]],
    start: datetime,
    end: datetime,
    *,
    max_workers: int,
) -> tuple[list[dict[str, Any]], dict[str, dict[datetime, float]], list[dict[str, Any]]]:
    fetched: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(fetch_network, st, start, end): code
            for code, st in candidates.items()
        }
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                fetched[code] = fut.result()
            except Exception as exc:
                fetched[code] = {
                    "ok": False,
                    "rows": [],
                    "source": candidates[code].get("network"),
                    "error": str(exc),
                }

    archived = csv_observed_rain(start, end)
    series_by_code: dict[str, dict[datetime, float]] = {}
    stations = []
    failures = []

    for code, st in candidates.items():
        series = dict(archived.get(code) or {})
        hourly = aggregate_hourly((fetched.get(code) or {}).get("rows") or [])
        for t, value in hourly.items():
            rain = qc_rain(value.get("rain_mm"))
            if rain is not None:
                series[t.replace(minute=0, second=0, microsecond=0)] = float(rain)

        if series:
            series_by_code[code] = series
            stations.append({
                **st,
                "source": (fetched.get(code) or {}).get("source"),
                "valid_hours": len(series),
                "archive_contributed": bool(archived.get(code)),
            })

        if not (fetched.get(code) or {}).get("ok") and not archived.get(code):
            failures.append({
                "code": code,
                "network": st.get("network"),
                "error": (fetched.get(code) or {}).get("error"),
            })

    return stations, series_by_code, failures


def component_forcing(
    stations: list[dict[str, Any]],
    series_by_code: dict[str, dict[datetime, float]],
    times: list[datetime],
    active_boundaries: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    support = read_support()
    component_ids = sorted({str(p["component_id"]) for p in support if p.get("component_id")})
    indices = {
        cid: np.array(
            [i for i, p in enumerate(support) if str(p.get("component_id")) == cid],
            dtype=int,
        )
        for cid in component_ids
    }
    point_area = np.array([float(p["local_area_km2"]) for p in support], dtype=float)

    station_codes = [str(s["code"]) for s in stations]
    if stations:
        d2 = vectorized_idw_matrix(support, stations)
    else:
        d2 = np.empty((len(support), 0), dtype=float)

    by_component = {cid: [] for cid in component_ids}
    valid_counts = []

    for hour in times:
        vals = np.array(
            [series_by_code.get(code, {}).get(hour, np.nan) for code in station_codes],
            dtype=float,
        )
        valid_count = int(np.isfinite(vals).sum())
        valid_counts.append(valid_count)

        if valid_count:
            point_rain = interpolate_points(d2, vals)
        else:
            point_rain = np.full(len(support), np.nan, dtype=float)

        for cid in component_ids:
            idx = indices[cid]
            pv = point_rain[idx]
            aa = point_area[idx]
            good = np.isfinite(pv) & np.isfinite(aa) & (aa > 0)
            mm = None
            if good.any():
                mm = float(np.sum(pv[good] * aa[good]) / np.sum(aa[good]))
            by_component[cid].append({
                "time_local": iso_local(hour),
                "mm": None if mm is None else round(mm, 4),
                "valid_station_count": valid_count,
            })

    components = []
    active = set(active_boundaries)
    for cid in component_ids:
        branch_code = cid.replace("BRANCH_", "", 1) if cid.startswith("BRANCH_") else None
        area = float(point_area[indices[cid]].sum())
        rows = by_component[cid]
        available = sum(r.get("mm") is not None for r in rows)
        components.append({
            "component_id": cid,
            "component_type": "tributary_branch" if branch_code else "mainstem_core_increment",
            "tributary_boundary_code": branch_code,
            "used_as_rainfall_runoff_in_current_scenario": not branch_code or branch_code not in active,
            "support_area_km2": round(area, 6),
            "expected_hours": len(times),
            "available_hours": available,
            "coverage_ratio": round(available / len(times), 5) if times else 0.0,
            "series": rows,
        })

    valid_sorted = sorted(valid_counts)
    diagnostics = {
        "hour_count": len(times),
        "hours_with_any_station": sum(x > 0 for x in valid_counts),
        "hours_with_at_least_3_stations": sum(x >= MIN_RAIN_STATIONS_FOR_STRONG_HOUR for x in valid_counts),
        "minimum_valid_station_count": min(valid_counts) if valid_counts else 0,
        "median_valid_station_count": valid_sorted[len(valid_sorted)//2] if valid_sorted else 0,
        "maximum_valid_station_count": max(valid_counts) if valid_counts else 0,
        "complete_component_count": sum(
            int(c["available_hours"]) == int(c["expected_hours"]) for c in components
        ),
        "component_count": len(components),
    }
    return components, diagnostics


def build_event(event_id: str, *, max_workers: int) -> dict[str, Any]:
    event = historical_hydro(event_id)
    start, end = event_window(event)
    times = hourly_axis(start, end)
    expected_hours = len(times)

    active = event_active_boundaries(event, expected_hours)
    scenario_name = f"historical_{event_id}"

    candidates = rain_candidates()
    stations, series_by_code, failures = fetch_event_rain(
        candidates, start, end, max_workers=max_workers
    )
    components, rain_diag = component_forcing(
        stations, series_by_code, times, active
    )

    outdir = OUTROOT / event_id
    outdir.mkdir(parents=True, exist_ok=True)

    rain_payload = {
        "schema_version": "g040_historical_calibration_rain_v1",
        "event_id": event_id,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "research_only": True,
        "status": (
            "OBSERVED_RAIN_READY"
            if rain_diag["complete_component_count"] == rain_diag["component_count"]
            else "OBSERVED_RAIN_PARTIAL"
        ),
        "window": {
            "start_local": iso_local(start),
            "end_local": iso_local(end),
            "timezone": "America/Sao_Paulo",
            "hours": expected_hours,
        },
        "boundary_scenario": {
            "name": scenario_name,
            "active_boundary_codes": active,
        },
        "method": {
            "station_scope": "all eligible operational stations from current in-basin ANA/INMET/CEMADEN catalogs",
            "temporal_semantics": "hourly accumulated observed rain",
            "spatial_interpolation": "IDW^2 to BHO6 support points, then component area-weighted average",
            "missing_policy": "missing remains missing; never zero-filled",
            "buffer_note": "historical calibration currently uses the audited in-basin station catalog; observed-gauge expansion to G040+buffer is a separate acquisition upgrade",
        },
        "network": {
            "candidate_station_count": len(candidates),
            "valid_rain_station_count": len(stations),
            "fetch_failure_without_archive_count": len(failures),
            "failures": failures,
        },
        "rain_diagnostics": rain_diag,
        "components": components,
    }

    hydro_payload = controls_wrapper(event)
    scenario_payload = {
        "schema_version": "g040_historical_boundary_scenario_v1",
        "event_id": event_id,
        "research_only": True,
        "current_scenario": scenario_name,
        "current": {
            "name": scenario_name,
            "active_boundary_codes": active,
        },
        "policy": {
            "branch_activation_min_flow_coverage": MIN_BRANCH_FLOW_COVERAGE,
            "exact_station_required": True,
            "missing_branch_flow": "return branch area to rainfall-runoff; never synthesize Q",
        },
    }

    (outdir / "rain.json").write_text(
        json.dumps(rain_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (outdir / "hydro.json").write_text(
        json.dumps(hydro_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (outdir / "scenario.json").write_text(
        json.dumps(scenario_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    source_by = {
        str(s.get("code")): s
        for s in event.get("stations") or []
    }
    return {
        "event_id": event_id,
        "window_hours": expected_hours,
        "rain_status": rain_payload["status"],
        "rain_station_count": len(stations),
        "rain_diagnostics": rain_diag,
        "active_boundary_codes": active,
        "primary_source_flow_hours": int((source_by.get(SOURCE_PRIMARY) or {}).get("flow_hour_count") or 0),
        "muçum_flow_hours": int((source_by.get("86510000") or {}).get("flow_hour_count") or 0),
        "encantado_flow_hours": int((source_by.get("86720000") or {}).get("flow_hour_count") or 0),
        "estrela_flow_hours": int((source_by.get("86879300") or {}).get("flow_hour_count") or 0),
        "porto_mariante_flow_hours": int((source_by.get("86895000") or {}).get("flow_hour_count") or 0),
        "paths": {
            "rain": str((outdir / "rain.json").relative_to(ROOT)),
            "hydro": str((outdir / "hydro.json").relative_to(ROOT)),
            "scenario": str((outdir / "scenario.json").relative_to(ROOT)),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--events",
        default=",".join(DEFAULT_EVENTS),
        help="comma-separated fixed event IDs",
    )
    ap.add_argument("--max-workers", type=int, default=12)
    args = ap.parse_args()

    event_ids = [x.strip() for x in args.events.split(",") if x.strip()]
    OUTROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for event_id in event_ids:
        print(f"building historical calibration forcing: {event_id}", flush=True)
        rows.append(build_event(event_id, max_workers=max(2, min(24, args.max_workers))))

    existing = {}
    if MANIFEST.exists():
        try:
            existing = load_json(MANIFEST)
        except Exception:
            existing = {}
    by_id = {
        str(x.get("event_id")): x
        for x in (existing.get("events") or [])
        if isinstance(x, dict) and x.get("event_id")
    }
    for row in rows:
        by_id[row["event_id"]] = row

    payload = {
        "schema_version": "g040_historical_calibration_forcing_manifest_v1",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "research_only": True,
        "events": [by_id[k] for k in sorted(by_id)],
        "fixed_split": {
            "development": ["E19_MAY2023"],
            "calibration": ["E22_SEP2023", "E24_NOV2023"],
            "independent_validation": ["E27_MAY2024", "E28_JUN2024"],
            "pseudo_operational_holdout": ["E2026_JUL"],
        },
        "no_leakage": True,
    }
    MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "HISTORICAL_CALIBRATION_FORCING_BUILT",
        "events": rows,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
