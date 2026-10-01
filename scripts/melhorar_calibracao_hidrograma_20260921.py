#!/usr/bin/env python3
"""Rebuild the interrupted 2026-09-21 HEC current-wave experiment.

This script does one job only: prepend observed ANA rainfall to the existing
ECMWF/IFS 5-day forcing without overwriting the production forcing.

Why this exists
---------------
The production forcing starts at "now" (past_hours=0). That is enough for a
cold forward experiment, but it cannot reproduce the hydrologic state and the
rising limb already observed before the forecast issue time. The interrupted
Work run on 2026-09-21 was explicitly using a multi-day observed pre-roll.

The reconstruction below is conservative:
* uses the existing PREVINE rain inventory for the upstream corridor only;
* downloads ANA telemetric rain for the four upstream UPGs;
* never converts missing observations to zero;
* aggregates available station rain by UPG as a research proxy;
* records hourly station coverage and refuses a run below a configurable floor;
* appends the untouched IFS future forcing already built by PREVINE;
* writes a separate research artifact, never the live production forcing.

Research only. This file does not promote parameters, publish alerts, or alter
the RNA/live robot.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
INVENTORY = OUT / "pluviometria_g040_latest.json"
FUTURE_DEFAULT = OUT / "hec_twin_ifs_forcing_5d_latest.json"
OUTPUT_DEFAULT = OUT / "hec_twin_ifs_forcing_preroll_research_20260921.json"

ANA_URLS = (
    "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos",
    "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/DadosHidrometeorologicos",
)
USER_AGENT = "PREVINE-hec-wave-recovery-research/1.0"
BRT = timezone(timedelta(hours=-3))

CORE_UPGS = (
    "Alto Taquari-Antas",
    "Médio Taquari-Antas",
    "Carreiro",
    "Prata",
)

# This is an explicit research proxy, not a closed areal rainfall mask.
SUBBASIN_UPGS = {
    "SB_PRATA_7868": ("Prata",),
    "SB_ANTAS_RESIDUAL": ("Alto Taquari-Antas", "Médio Taquari-Antas"),
    "SB_CARREIRO_7866": ("Carreiro",),
    "SB_STZ_RESIDUAL": ("Médio Taquari-Antas",),
    "SB_INC_MUCUM": ("Médio Taquari-Antas",),
}


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _parse_local_hour(raw: str) -> datetime | None:
    text = (raw or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[:19], fmt).replace(minute=0, second=0, microsecond=0)
        except ValueError:
            pass
    return None


def _http_get(url: str, *, timeout: int = 55, attempts: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"ANA request failed: {last}")


def _parse_ana_rain(xml_bytes: bytes) -> dict[datetime, float]:
    root = ET.fromstring(xml_bytes)
    roots = [root]
    if (root.text or "").strip().startswith("<"):
        try:
            roots.append(ET.fromstring(root.text))
        except ET.ParseError:
            pass

    out: dict[datetime, float] = {}
    for rt in roots:
        for row in rt.iter():
            fields = {_local(ch.tag): (ch.text or "") for ch in row}
            raw_time = fields.get("DataHora") or fields.get("Data_Hora")
            raw_rain = fields.get("Chuva") or fields.get("chuva") or fields.get("Precipitacao")
            if not raw_time or raw_rain in (None, ""):
                continue
            hour = _parse_local_hour(raw_time)
            if hour is None:
                continue
            try:
                value = float(str(raw_rain).replace(",", "."))
            except ValueError:
                continue
            if not math.isfinite(value) or value < 0:
                continue
            out[hour] = out.get(hour, 0.0) + value
    return out


def fetch_station_rain(code: str, start_local: datetime, end_local: datetime) -> dict[datetime, float]:
    query = urllib.parse.urlencode(
        {
            "codEstacao": code,
            "dataInicio": start_local.strftime("%d/%m/%Y"),
            "dataFim": end_local.strftime("%d/%m/%Y"),
        }
    )
    errors = []
    for base in ANA_URLS:
        try:
            return _parse_ana_rain(_http_get(f"{base}?{query}"))
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    raise RuntimeError(" | ".join(errors))


def load_station_inventory() -> dict[str, dict[str, Any]]:
    data = json.loads(INVENTORY.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    by_upg = data.get("by_upg") or {}
    for upg in CORE_UPGS:
        for row in by_upg.get(upg) or []:
            if str(row.get("rede") or "").upper() != "ANA":
                continue
            code = str(row.get("codigo") or "")
            if not code:
                continue
            out[code] = {
                "codigo": code,
                "nome": row.get("nome"),
                "upg": upg,
                "situacao": row.get("situacao"),
            }
    return out


def iso_utc(dt_local_naive: datetime) -> str:
    return dt_local_naive.replace(tzinfo=BRT).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(raw: str) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)


def mean_available(values: list[float]) -> float:
    if not values:
        raise ValueError("empty values")
    return float(statistics.fmean(values))


def build_preroll(
    future: dict[str, Any],
    *,
    past_hours: int,
    min_total_stations: int,
    workers: int,
) -> dict[str, Any]:
    future_times = list(future.get("times_utc") or [])
    future_precip = future.get("precip_mm_by_subbasin") or {}
    if not future_times:
        raise RuntimeError("future forcing has no times_utc")

    now_utc = parse_utc(str((future.get("window") or {}).get("now_utc") or future.get("now_utc") or future_times[0]))
    now_local = now_utc.astimezone(BRT).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    start_local = now_local - timedelta(hours=past_hours)
    past_local_hours = [start_local + timedelta(hours=i) for i in range(past_hours)]

    stations = load_station_inventory()
    if not stations:
        raise RuntimeError("no ANA rain stations found in upstream corridor inventory")

    station_series: dict[str, dict[datetime, float]] = {}
    station_errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        jobs = {
            pool.submit(fetch_station_rain, code, start_local, now_local): code
            for code in stations
        }
        for fut in as_completed(jobs):
            code = jobs[fut]
            try:
                series = fut.result()
                if series:
                    station_series[code] = series
            except Exception as exc:  # noqa: BLE001
                station_errors[code] = str(exc)

    by_upg_codes: dict[str, list[str]] = {u: [] for u in CORE_UPGS}
    for code, meta in stations.items():
        if code in station_series:
            by_upg_codes[meta["upg"]].append(code)

    coverage_rows: list[dict[str, Any]] = []
    past_by_sb: dict[str, list[float]] = {sb: [] for sb in SUBBASIN_UPGS}
    fallback_hours: dict[str, int] = {sb: 0 for sb in SUBBASIN_UPGS}

    for hour in past_local_hours:
        all_values = [
            series[hour]
            for series in station_series.values()
            if hour in series
        ]
        if len(all_values) < min_total_stations:
            raise RuntimeError(
                f"observed-rain coverage too low at {hour:%Y-%m-%d %H:%M} BRT: "
                f"{len(all_values)} stations < required {min_total_stations}; "
                "do not zero-fill the missing rain"
            )

        row = {
            "time_local": hour.isoformat(),
            "time_utc": iso_utc(hour),
            "stations_available_total": len(all_values),
            "by_upg": {},
        }
        for upg in CORE_UPGS:
            vals = [
                station_series[code][hour]
                for code in by_upg_codes[upg]
                if hour in station_series[code]
            ]
            row["by_upg"][upg] = {
                "n": len(vals),
                "mean_mm": round(mean_available(vals), 4) if vals else None,
            }

        global_mean = mean_available(all_values)
        for sb, upgs in SUBBASIN_UPGS.items():
            vals = []
            for upg in upgs:
                vals.extend(
                    station_series[code][hour]
                    for code in by_upg_codes[upg]
                    if hour in station_series[code]
                )
            if vals:
                past_by_sb[sb].append(mean_available(vals))
            else:
                # Missing is never interpreted as zero. A basin-wide observed
                # mean is a documented fallback so the state simulation remains
                # continuous; every use is counted in metadata.
                past_by_sb[sb].append(global_mean)
                fallback_hours[sb] += 1
        coverage_rows.append(row)

    for sb in SUBBASIN_UPGS:
        if sb not in future_precip:
            raise RuntimeError(f"future forcing missing subbasin {sb}")

    combined_times = [iso_utc(h) for h in past_local_hours] + future_times
    combined_by_sb = {
        sb: [round(float(v), 4) for v in past_by_sb[sb]]
        + [round(float(v), 4) for v in future_precip[sb]]
        for sb in SUBBASIN_UPGS
    }

    meta_future = future.get("subbasin_meta") or {}
    areas = {
        sb: float((meta_future.get(sb) or {}).get("area_km2") or 0.0)
        for sb in SUBBASIN_UPGS
    }
    if any(v <= 0 for v in areas.values()):
        raise RuntimeError(f"invalid/missing subbasin areas in future forcing: {areas}")
    area_sum = sum(areas.values())
    weighted_hourly = []
    for i in range(len(combined_times)):
        weighted_hourly.append(
            sum(combined_by_sb[sb][i] * areas[sb] for sb in SUBBASIN_UPGS) / area_sum
        )

    past_mm = float(sum(weighted_hourly[:past_hours]))
    future_mm = float(sum(weighted_hourly[past_hours:]))
    min_coverage = min(r["stations_available_total"] for r in coverage_rows)
    med_coverage = statistics.median(r["stations_available_total"] for r in coverage_rows)

    payload = {
        "schema_version": "hec_twin_observed_preroll_plus_ifs_v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "research_forcing_preroll_ready",
        "purpose": (
            "Forçante de pesquisa para reconstruir a onda atual: chuva ANA observada "
            "antes da emissão + IFS futuro; não altera o forcing operacional."
        ),
        "model": "ANA_observed_UPG_mean_plus_ecmwf_ifs025",
        "horizon_hours": len(future_times),
        "now_utc": future_times[0],
        "window": {
            "now_utc": future_times[0],
            "past_hours": past_hours,
            "future_hours": len(future_times),
            "definition": "observed_ANA_preroll_then_existing_IFS_future",
        },
        "times_utc": combined_times,
        "precip_mm_by_subbasin": combined_by_sb,
        "subbasin_meta": {
            sb: {
                **(meta_future.get(sb) or {}),
                "observed_preroll_method": "mean_available_ANA_stations_by_UPG",
                "observed_preroll_upgs": list(SUBBASIN_UPGS[sb]),
                "observed_preroll_fallback_hours_to_all_core_mean": fallback_hours[sb],
            }
            for sb in SUBBASIN_UPGS
        },
        "area_weighted_mean_mm": {
            "hourly": [round(v, 4) for v in weighted_hourly],
            "past_mm": round(past_mm, 3),
            "future_mm": round(future_mm, 3),
            "analog_total_mm": round(past_mm + future_mm, 3),
            "total_mm": round(past_mm + future_mm, 3),
            "max_hourly_mm": round(max(weighted_hourly) if weighted_hourly else 0.0, 3),
        },
        "observed_preroll_coverage": {
            "candidate_ana_stations": len(stations),
            "stations_with_any_data": len(station_series),
            "stations_failed_request": len(station_errors),
            "past_hours": past_hours,
            "min_stations_available_per_hour": min_coverage,
            "median_stations_available_per_hour": med_coverage,
            "required_min_stations_per_hour": min_total_stations,
            "fallback_hours_by_subbasin": fallback_hours,
            "hours": coverage_rows,
            "request_errors": station_errors,
        },
        "source_future_forcing": {
            "schema_version": future.get("schema_version"),
            "generated_at_utc": future.get("generated_at_utc"),
            "model": future.get("model"),
            "point_proxy_not_areal_mask": True,
        },
        "discipline": {
            "research_only": True,
            "not_official_alert": True,
            "does_not_overwrite_production_forcing": True,
            "missing_rain_is_never_zero": True,
            "observed_rain_is_UPG_station_mean_proxy_not_areal_mask": True,
            "future_rain_keeps_existing_IFS_point_proxy": True,
        },
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--future", type=Path, default=FUTURE_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--past-hours", type=int, default=96)
    parser.add_argument(
        "--min-total-stations",
        type=int,
        default=40,
        help="Abort if fewer observed ANA rain stations exist in any past hour.",
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    future = json.loads(args.future.read_text(encoding="utf-8"))
    payload = build_preroll(
        future,
        past_hours=max(1, args.past_hours),
        min_total_stations=max(1, args.min_total_stations),
        workers=max(1, args.workers),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cov = payload["observed_preroll_coverage"]
    rain = payload["area_weighted_mean_mm"]
    print(f"wrote {args.output}")
    print(
        "coverage="
        f"{cov['min_stations_available_per_hour']} min / "
        f"{cov['median_stations_available_per_hour']} median; "
        f"past={rain['past_mm']} mm future={rain['future_mm']} mm"
    )


if __name__ == "__main__":
    main()
