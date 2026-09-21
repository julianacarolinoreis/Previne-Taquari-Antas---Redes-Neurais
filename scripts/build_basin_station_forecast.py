"""Build the basin-wide station forecast feed used by the PREVINE map.

The public page is static, so the map reads one reviewed JSON snapshot instead
of making one weather request per browser visitor. The snapshot is rebuilt by
GitHub Actions every six hours.

This is a research-screening surface. It keeps observed rain, forecast model
output, river telemetry and experimental level forecasts in separate fields.
Missing observations are represented as null/unavailable and are never
converted to zero.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
FLOW_CATALOG = ROOT / "assets/data/estudo_bacia_taquari_antas/postos_g040.geojson"
RAIN_CATALOG = ROOT / "assets/data/estudo_bacia_taquari_antas/pluviometria_g040.geojson"
OBSERVED_CSV = ROOT / "assets/data/chuvas_horarias.csv"
LIVE_FEEDS = (
    ROOT / "previsao_ao_vivo.json",
    ROOT / "previsao_ao_vivo_mucum.json",
)
DEFAULT_OUTPUT = ROOT / "assets/data/basin_station_forecast_latest.json"

BRT = timezone(timedelta(hours=-3))
UTC = timezone.utc

# These are global/seamless model families that Open-Meteo currently exposes
# for southern Brazil. The labels are deliberately explicit in the UI.
MODEL_SPECS = (
    {
        "id": "ecmwf_ifs025",
        "label": "ECMWF IFS",
        "provider": "ECMWF",
        "resolution": "0,25°",
        "color": "#1769aa",
    },
    {
        "id": "gfs_seamless",
        "label": "GFS",
        "provider": "NOAA",
        "resolution": "global seamless",
        "color": "#d97706",
    },
    {
        "id": "icon_seamless",
        "label": "ICON",
        "provider": "DWD",
        "resolution": "global seamless",
        "color": "#7c3aed",
    },
    {
        "id": "gem_seamless",
        "label": "GEM",
        "provider": "Environment Canada",
        "resolution": "global seamless",
        "color": "#059669",
    },
    {
        "id": "meteofrance_seamless",
        "label": "Météo-France",
        "provider": "Météo-France",
        "resolution": "global seamless",
        "color": "#dc2626",
    },
)

FORECAST_VARIABLES = (
    "precipitation",
    "temperature_2m",
    "relative_humidity_2m",
    "pressure_msl",
    "wind_speed_10m",
    "wind_gusts_10m",
    "cloud_cover",
    "precipitation_probability",
    "soil_moisture_0_to_7cm",
)
REQUIRED_FORECAST_VARIABLES = (
    "precipitation",
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
)

FORECAST_DAYS = 4
FORECAST_STEP_HOURS = 3
PRECIPITATION_WINDOW_HOURS = (3, 6, 12, 24, 48, 72)
OBSERVED_HOURS = 72
OBSERVED_WINDOW_HOURS = (1, 3, 6, 12, 24, 48, 72)
BATCH_SIZE = 100
BATCH_PAUSE_SECONDS = 15.0
REFRESH_MINUTE_UTC = 17
LEVEL_OBSERVED_HOURS = 72

LEVEL_FORECAST_LABELS = {
    "2h": "RNA 2h",
    "2h_versao_b": "RNA 2h B",
    "4h": "RNA 4h",
    "4h_versao_b": "RNA 4h B",
    "8h": "RNA 8h",
    "8h_v002": "RNA 8h V002",
    "8h_versao_b": "RNA 8h B",
}

LEVEL_FORECAST_COLORS = {
    "2h": "#1769aa",
    "2h_versao_b": "#7c3aed",
    "4h": "#d97706",
    "4h_versao_b": "#dc2626",
    "8h": "#059669",
    "8h_v002": "#9333ea",
    "8h_versao_b": "#be123c",
}

# The CSV is intentionally not treated as a complete basin network. These
# are the six columns that the existing ANA/INMET/CEMADEN robot publishes.
OBSERVED_COLUMNS = {
    "86472600": "chuva_86472600",
    "86472000": "chuva_86472000",
    "02851044": "chuva_02851044",
    "2851044": "chuva_02851044",
    "02851072": "chuva_02851072",
    "2851072": "chuva_02851072",
    "A894": "chuva_inmet_A894",
    "432040401A": "chuva_cemaden_4320404010A",
    "4320404010A": "chuva_cemaden_4320404010A",
}


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_iso(value: Any, *, default_timezone: timezone = UTC) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_timezone)
    return parsed.astimezone(UTC)


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat(timespec="minutes").replace("+00:00", "Z")


def station_code(value: Any) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def json_load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON raiz inválida: {path}")
    return value


def valid_coordinates(properties: dict[str, Any], geometry: dict[str, Any]) -> tuple[float, float] | None:
    latitude = finite(properties.get("lat"))
    longitude = finite(properties.get("lon"))
    if latitude is None or longitude is None:
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if isinstance(coordinates, list) and len(coordinates) >= 2:
            longitude = finite(coordinates[0])
            latitude = finite(coordinates[1])
    if latitude is None or longitude is None:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return round(latitude, 6), round(longitude, 6)


def _append_unique(values: list[Any], value: Any) -> None:
    if value in (None, ""):
        return
    if value not in values:
        values.append(value)


def public_asset_path(path: Path) -> str:
    """Return a repository-relative path suitable for the public JSON feed."""

    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        # Test fixtures may live in a temporary directory. Keep their
        # provenance inspectable without leaking the machine's absolute path.
        return path.name


def load_station_catalog(
    flow_path: Path = FLOW_CATALOG,
    rain_path: Path = RAIN_CATALOG,
) -> list[dict[str, Any]]:
    """Merge the G040 flow and rain inventories by network/code."""

    registry: dict[str, dict[str, Any]] = {}
    inputs = (
        (flow_path, "fluviometria"),
        (rain_path, "pluviometria"),
    )
    for path, catalog_kind in inputs:
        raw = json_load(path)
        features = raw.get("features")
        if not isinstance(features, list):
            raise ValueError(f"catálogo sem features: {path}")
        for feature in features:
            properties = feature.get("properties") if isinstance(feature, dict) else {}
            properties = properties if isinstance(properties, dict) else {}
            code = station_code(properties.get("codigo"))
            coordinates = valid_coordinates(
                properties,
                feature.get("geometry") if isinstance(feature, dict) else {},
            )
            if not code or coordinates is None:
                continue
            network = station_code(properties.get("rede")) or "ANA"
            key = f"{network}:{code}"
            item = registry.get(key)
            if item is None:
                item = {
                    "id": key,
                    "code": code,
                    "name": str(properties.get("nome") or f"Estação {code}").strip(),
                    "network": network,
                    "latitude": coordinates[0],
                    "longitude": coordinates[1],
                    "types": [],
                    "upgs": [],
                    "catalog_sources": [],
                    "drainage_area_km2": None,
                    "operating": None,
                }
                registry[key] = item
            name = str(properties.get("nome") or "").strip()
            if name and item["name"] == f"Estação {code}":
                item["name"] = name
            item["latitude"], item["longitude"] = coordinates
            _append_unique(item["types"], properties.get("tipo") or catalog_kind)
            _append_unique(item["upgs"], properties.get("upg"))
            _append_unique(item["catalog_sources"], public_asset_path(path))
            area = finite(properties.get("area_drenagem_km2"))
            if area is not None and item["drainage_area_km2"] is None:
                item["drainage_area_km2"] = round(area, 3)
            if properties.get("operando") not in (None, ""):
                item["operating"] = str(properties["operando"])
            if properties.get("situacao") not in (None, ""):
                item["operating"] = str(properties["situacao"])

    stations = list(registry.values())
    stations.sort(key=lambda item: (item["network"], item["name"].casefold(), item["code"]))
    for item in stations:
        item["type_label"] = " + ".join(item["types"])
        item["upg_label"] = " · ".join(item["upgs"]) or "UPG não informada"
    return stations


def _csv_timestamp(row: dict[str, Any]) -> datetime | None:
    raw = str(row.get("COD_SEQUENCIAL") or "").strip()
    try:
        local = datetime.strptime(raw, "%Y%m%d%H%M").replace(tzinfo=BRT)
    except ValueError:
        return None
    return local.astimezone(UTC)


def load_observed_rain(
    csv_path: Path = OBSERVED_CSV,
    *,
    now: datetime | None = None,
    hours: int = OBSERVED_HOURS,
) -> dict[str, dict[str, Any]]:
    """Read only the observed series that the existing robot actually publishes."""

    now = (now or datetime.now(UTC)).astimezone(UTC)
    records: dict[str, list[tuple[datetime, float | None]]] = {
        code: [] for code in OBSERVED_COLUMNS
    }
    all_times: set[datetime] = set()
    if not csv_path.exists():
        return {
            code: {
                "state": "unavailable",
                "source": "assets/data/chuvas_horarias.csv",
                "unit": "mm",
                "rows": [],
                "available_points": 0,
                "expected_points": 0,
                "last_observed_at_utc": None,
                "windows": _observed_window_stats(
                    [], latest_observed=None, windows=OBSERVED_WINDOW_HOURS
                ),
                "message": "Arquivo de chuva observada não publicado.",
            }
            for code in OBSERVED_COLUMNS
        }

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timestamp = _csv_timestamp(row)
            if timestamp is None or timestamp > now:
                continue
            all_times.add(timestamp)
            for code, column in OBSERVED_COLUMNS.items():
                if column not in row:
                    continue
                raw_value = row.get(column)
                value = finite(raw_value) if raw_value not in (None, "") else None
                records[code].append((timestamp, value if value is None or value >= 0 else None))

    window_start = now - timedelta(hours=hours)
    window = sorted(timestamp for timestamp in all_times if timestamp >= window_start)
    if len(window) > hours + 1:
        window = window[-(hours + 1) :]

    result: dict[str, dict[str, Any]] = {}
    for code, rows in records.items():
        values = {timestamp: value for timestamp, value in rows}
        selected = [
            {"time": iso_utc(timestamp), "mm": values.get(timestamp)}
            for timestamp in window
        ]
        known = [row["mm"] for row in selected if row["mm"] is not None]
        latest_observed = max(
            (timestamp for timestamp, value in rows if value is not None),
            default=None,
        )
        result[code] = {
            "state": "available" if known else "unavailable",
            "source": "ANA/INMET/CEMADEN · chuvas_horarias.csv",
            "unit": "mm",
            "timezone": "America/Sao_Paulo",
            "rows": selected,
            "available_points": len(known),
            "expected_points": len(window),
            "last_observed_at_utc": iso_utc(latest_observed),
            "windows": _observed_window_stats(
                rows,
                latest_observed=latest_observed,
                windows=OBSERVED_WINDOW_HOURS,
            ),
            "message": (
                "Série observada publicada pelo robô de chuva."
                if known
                else "Não há série observada publicada para este código."
            ),
        }
    return result


def _observed_window_stats(
    rows: list[tuple[datetime, float | None]],
    *,
    latest_observed: datetime | None,
    windows: tuple[int, ...],
) -> dict[str, dict[str, Any]]:
    """Summarize trailing observed-rain windows without hiding gaps."""

    if latest_observed is None:
        return {
            f"{hours}h": {
                "mm": None,
                "valid_points": 0,
                "expected_points": hours + 1,
                "coverage_ratio": 0.0,
                "complete": False,
            }
            for hours in windows
        }

    by_time = {timestamp: value for timestamp, value in rows}
    result: dict[str, dict[str, Any]] = {}
    for hours in windows:
        start = latest_observed - timedelta(hours=hours)
        expected_points = hours + 1
        selected = [
            value
            for timestamp, value in by_time.items()
            if start <= timestamp <= latest_observed
        ]
        valid = [value for value in selected if value is not None]
        coverage_ratio = len(valid) / expected_points
        result[f"{hours}h"] = {
            "mm": round(sum(valid), 3) if valid else None,
            "valid_points": len(valid),
            "expected_points": expected_points,
            "coverage_ratio": round(coverage_ratio, 4),
            "complete": len(valid) == expected_points,
        }
    return result


def _level_record(raw: dict[str, Any], code: str) -> dict[str, Any] | None:
    observed_at = parse_iso(
        raw.get("telemetria_ultima_em_utc")
        or raw.get("nivel_rio_agora_em_utc")
        or raw.get("telemetria_ultima_em")
        or raw.get("nivel_rio_agora_em"),
        default_timezone=BRT,
    )
    level = finite(
        raw.get("telemetria_ultima_nivel_cm", raw.get("nivel_rio_agora_cm"))
    )
    forecast = finite(
        raw.get("nivel_previsto_cm", raw.get("nivel_modelo_cm"))
    )
    forecast_at = parse_iso(
        raw.get("hora_alvo_utc")
        or raw.get("hora_alvo")
        or raw.get("nivel_previsto_em_utc")
        or raw.get("nivel_previsto_em"),
        default_timezone=BRT,
    )
    observed_series = _level_observed_series(raw)
    forecast_series = _level_forecast_series(raw)
    if level is None and forecast is None and observed_at is None:
        return None
    return {
        "state": "available" if level is not None else "partial",
        "current_cm": level,
        "observed_at_utc": iso_utc(observed_at),
        "forecast_cm": forecast,
        "forecast_at_utc": iso_utc(forecast_at),
        "threshold_cm": finite(raw.get("bankfull_cm")),
        "unit": "cm",
        "series": observed_series,
        "forecasts": forecast_series,
        "source": f"feed ao vivo · estação {code}",
        "quality": raw.get("status_dados"),
        "message": str(raw.get("aviso") or raw.get("status_dados") or "").strip(),
    }


def _decorate_level_snapshot(
    level: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    """Add freshness and trend diagnostics without changing the source values."""

    observed_at = parse_iso(level.get("observed_at_utc"), default_timezone=UTC)
    age_minutes = None
    if observed_at is not None:
        age_minutes = round(max(0.0, (now - observed_at).total_seconds() / 60.0), 1)

    series = level.get("series") if isinstance(level.get("series"), list) else []
    parsed_series = []
    for item in series:
        if not isinstance(item, dict):
            continue
        timestamp = parse_iso(item.get("time"), default_timezone=UTC)
        value = finite(item.get("cm"))
        if timestamp is not None and value is not None:
            parsed_series.append((timestamp, value))
    trend = None
    if len(parsed_series) >= 2:
        first_time, first_value = parsed_series[-2]
        last_time, last_value = parsed_series[-1]
        elapsed_hours = (last_time - first_time).total_seconds() / 3600.0
        if elapsed_hours > 0:
            trend = round((last_value - first_value) / elapsed_hours, 3)

    level["observed_age_minutes"] = age_minutes
    level["series_valid_points"] = len(parsed_series)
    level["trend_cm_per_hour"] = trend
    level["trend_label"] = (
        "subindo" if trend is not None and trend > 0.01
        else "descendo" if trend is not None and trend < -0.01
        else "estável" if trend is not None
        else None
    )
    return level


def _level_observed_series(
    raw: dict[str, Any], *, hours: int = LEVEL_OBSERVED_HOURS
) -> list[dict[str, Any]]:
    """Normalize the published ANA/SGB level series to the last 72 hours."""

    values: list[tuple[datetime, float]] = []
    for item in raw.get("serie_observada_ana") or []:
        if not isinstance(item, dict):
            continue
        timestamp = parse_iso(
            item.get("hora") or item.get("time") or item.get("timestamp"),
            default_timezone=BRT,
        )
        value = finite(item.get("nivel_cm", item.get("cm", item.get("value"))))
        if timestamp is None or value is None:
            continue
        values.append((timestamp, value))
    if not values:
        return []
    values.sort(key=lambda pair: pair[0])
    start = values[-1][0] - timedelta(hours=hours)
    return [
        {"time": iso_utc(timestamp), "cm": value}
        for timestamp, value in values
        if timestamp >= start
    ]


def _level_forecast_series(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep the live RNA level forecasts as separate, labelled points."""

    horizons = raw.get("horizontes")
    if not isinstance(horizons, dict):
        horizons = {}
    result: list[dict[str, Any]] = []
    for horizon_id, item in horizons.items():
        if not isinstance(item, dict):
            continue
        value = finite(item.get("nivel_previsto_cm", item.get("nivel_modelo_cm")))
        target = parse_iso(
            item.get("hora_alvo_utc")
            or item.get("hora_alvo")
            or item.get("hora_modelo_utc")
            or item.get("hora_modelo"),
            default_timezone=BRT,
        )
        if value is None or target is None:
            continue
        horizon_text = str(item.get("rotulo") or item.get("horizonte") or horizon_id)
        result.append(
            {
                "id": "rna_" + str(horizon_id),
                "label": LEVEL_FORECAST_LABELS.get(
                    str(horizon_id), "RNA " + horizon_text
                ),
                "horizon_h": finite(item.get("horizonte_h")),
                "time": iso_utc(target),
                "cm": value,
                "color": LEVEL_FORECAST_COLORS.get(str(horizon_id), "#64748b"),
                "model": item.get("modelo"),
                "source": "feed ao vivo · previsão experimental de nível",
            }
        )
    result.sort(key=lambda item: (item.get("time") or "", item.get("id") or ""))
    return result


def _unavailable_level(code: str) -> dict[str, Any]:
    return {
        "state": "unavailable",
        "current_cm": None,
        "observed_at_utc": None,
        "forecast_cm": None,
        "forecast_at_utc": None,
        "threshold_cm": None,
        "unit": "cm",
        "series": [],
        "forecasts": [],
        "source": f"feed ao vivo · estação {code}",
        "quality": None,
        "message": "Telemetria de nível não publicada para esta estação.",
    }


def load_level_snapshots(paths: tuple[Path, ...] = LIVE_FEEDS) -> dict[str, dict[str, Any]]:
    """Extract the current level evidence already published by the live feeds."""

    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.exists():
            continue
        try:
            raw = json_load(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        top_code = station_code(raw.get("estacao"))
        if top_code:
            record = _level_record(raw, top_code)
            if record:
                result[top_code] = record
        for item in raw.get("estacoes_status") or []:
            if not isinstance(item, dict):
                continue
            code = station_code(item.get("estacao"))
            if not code:
                continue
            observed_at = parse_iso(
                item.get("ultima_leitura_bruta")
                or item.get("ultima_hora_modelo"),
                default_timezone=BRT,
            )
            level = finite(
                item.get("ultima_leitura_bruta_nivel_cm")
                or item.get("ultima_hora_modelo_nivel_cm")
            )
            if level is None:
                continue
            result.setdefault(
                code,
                {
                    "state": "available",
                    "current_cm": level,
                    "observed_at_utc": iso_utc(observed_at),
                    "forecast_cm": None,
                    "forecast_at_utc": None,
                    "threshold_cm": None,
                    "unit": "cm",
                    "series": [],
                    "forecasts": [],
                    "source": f"telemetria ANA/SGB · estação {code}",
                    "quality": item.get("qc_status"),
                    "message": item.get("fonte") or "Leitura de nível publicada.",
                },
            )
    return result


def build_open_meteo_url(stations: list[dict[str, Any]]) -> str:
    params = {
        "latitude": ",".join(str(item["latitude"]) for item in stations),
        "longitude": ",".join(str(item["longitude"]) for item in stations),
        "models": ",".join(spec["id"] for spec in MODEL_SPECS),
        "hourly": ",".join(FORECAST_VARIABLES),
        "forecast_days": str(FORECAST_DAYS),
        "timezone": "UTC",
    }
    return "https://api.open-meteo.com/v1/forecast?" + urlencode(params)


def _coordinate_key(station: dict[str, Any]) -> tuple[float, float]:
    return (round(float(station["latitude"]), 6), round(float(station["longitude"]), 6))


def _unique_forecast_locations(stations: list[dict[str, Any]]) -> list[dict[str, float]]:
    locations: dict[tuple[float, float], dict[str, float]] = {}
    for station in stations:
        key = _coordinate_key(station)
        locations.setdefault(
            key,
            {"latitude": key[0], "longitude": key[1]},
        )
    return list(locations.values())


def fetch_json(url: str, *, attempts: int = 4, timeout: int = 20) -> Any:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": "PREVINE-basin-stations/1.0"})
            with urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except Exception as exc:  # pragma: no cover - network dependent
            last_error = exc
            if attempt + 1 < attempts:
                delay = float(2 ** attempt)
                retry_after = getattr(getattr(exc, "headers", None), "get", lambda *_: None)(
                    "Retry-After"
                )
                try:
                    if retry_after:
                        delay = max(delay, float(retry_after))
                except (TypeError, ValueError):
                    pass
                if "429" in str(exc):
                    # Open-Meteo can rate-limit a GitHub runner between large
                    # multi-location requests. Give the provider time to
                    # release the window before abandoning the whole batch.
                    delay = max(delay, 30.0 * (attempt + 1))
                delay = min(delay, 45.0)
                time.sleep(delay)
    raise RuntimeError(f"Open-Meteo indisponível: {last_error}")


def _sample_indices(times: list[Any], step_hours: int) -> list[int]:
    if not times:
        return []
    indices = list(range(0, len(times), step_hours))
    if indices[-1] != len(times) - 1:
        indices.append(len(times) - 1)
    return indices


def _forward_window_sums(
    values: list[Any], indices: list[int], window_hours: int
) -> list[float | None]:
    """Sum complete hourly precipitation windows after each sampled time.

    Open-Meteo's precipitation value at timestamp ``t`` is the preceding
    hour. Starting at ``t + 1`` keeps a forward window from accidentally
    including an hour that has already ended at the sampled timestamp.
    Missing or incomplete windows remain unavailable instead of becoming zero.
    """

    result: list[float | None] = []
    for index in indices:
        window = values[index + 1 : index + 1 + window_hours]
        if len(window) != window_hours:
            result.append(None)
            continue
        numeric = [finite(value) for value in window]
        result.append(sum(value for value in numeric if value is not None) if all(value is not None for value in numeric) else None)
    return result


def extract_forecast_payload(
    payload: dict[str, Any],
    *,
    step_hours: int = FORECAST_STEP_HOURS,
    fetched_at_utc: str | None = None,
) -> dict[str, Any]:
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not isinstance(hourly, dict):
        return {
            "state": "unavailable",
            "times": [],
            "models": {},
            "fetched_at_utc": fetched_at_utc,
            "message": "Resposta sem bloco hourly.",
        }
    raw_times = hourly.get("time") or []
    indices = _sample_indices(list(raw_times), step_hours)
    times = []
    for index in indices:
        parsed = parse_iso(raw_times[index], default_timezone=UTC)
        if parsed is not None:
            times.append(iso_utc(parsed))

    models: dict[str, dict[str, Any]] = {}
    for spec in MODEL_SPECS:
        model_id = spec["id"]
        model_payload: dict[str, Any] = {}
        for variable in FORECAST_VARIABLES:
            values = hourly.get(f"{variable}_{model_id}") or []
            model_payload[variable] = [
                finite(values[index]) if index < len(values) else None
                for index in indices
            ]
        precipitation_values = hourly.get(f"precipitation_{model_id}") or []
        model_payload["precipitation_windows"] = {
            f"{hours}h": _forward_window_sums(precipitation_values, indices, hours)
            for hours in PRECIPITATION_WINDOW_HOURS
        }
        if any(
            any(value is not None for value in model_payload[variable])
            for variable in FORECAST_VARIABLES
        ):
            models[model_id] = model_payload
    if not times or not models:
        return {
            "state": "unavailable",
            "times": [],
            "models": {},
            "fetched_at_utc": fetched_at_utc,
            "message": "Nenhum modelo retornou série utilizável.",
        }
    return {
        "state": "available",
        "times": times,
        "models": models,
        "fetched_at_utc": fetched_at_utc,
        "source_metadata": {
            key: payload[key]
            for key in ("timezone", "timezone_abbreviation", "utc_offset_seconds", "generationtime_ms")
            if key in payload
        },
        "model_run_at_utc": None,
        "message": "Previsão horária amostrada para leitura comparativa.",
    }


def _unavailable_forecast(message: str) -> dict[str, Any]:
    return {
        "state": "unavailable",
        "times": [],
        "models": {},
        "fetched_at_utc": None,
        "source_metadata": {},
        "model_run_at_utc": None,
        "message": message,
    }


def _next_cycle(now: datetime) -> datetime:
    candidate = now.astimezone(UTC).replace(
        minute=REFRESH_MINUTE_UTC, second=0, microsecond=0
    )
    while candidate <= now or candidate.hour % 6:
        candidate += timedelta(hours=1)
        candidate = candidate.replace(minute=REFRESH_MINUTE_UTC)
    return candidate


def _metric_coverage(stations: list[dict[str, Any]]) -> dict[str, Any]:
    """Count real values by metric, model and station for the public contract."""

    coverage: dict[str, Any] = {}
    for variable in FORECAST_VARIABLES:
        by_model: dict[str, Any] = {}
        for spec in MODEL_SPECS:
            model_id = spec["id"]
            station_count = 0
            valid_points = 0
            total_points = 0
            for station in stations:
                forecast = station.get("forecast") or {}
                model = (forecast.get("models") or {}).get(model_id) or {}
                values = model.get(variable)
                if not isinstance(values, list):
                    continue
                total_points += len(values)
                valid = sum(finite(value) is not None for value in values)
                valid_points += valid
                if valid:
                    station_count += 1
            by_model[model_id] = {
                "station_count": station_count,
                "valid_points": valid_points,
                "total_points": total_points,
                "coverage_ratio": round(valid_points / total_points, 4)
                if total_points
                else 0.0,
            }
        coverage[variable] = {"models": by_model}
    return coverage


def _coordinate_coverage(stations: list[dict[str, Any]]) -> dict[str, int]:
    groups: dict[tuple[float, float], int] = {}
    for station in stations:
        key = _coordinate_key(station)
        groups[key] = groups.get(key, 0) + 1
    duplicated = [count for count in groups.values() if count > 1]
    return {
        "unique_location_count": len(groups),
        "duplicate_location_group_count": len(duplicated),
        "stations_in_duplicate_locations": sum(duplicated),
    }


def build_feed(
    *,
    now: datetime | None = None,
    flow_catalog: Path = FLOW_CATALOG,
    rain_catalog: Path = RAIN_CATALOG,
    observed_csv: Path = OBSERVED_CSV,
    live_feeds: tuple[Path, ...] = LIVE_FEEDS,
    fetcher=fetch_json,
    batch_size: int = BATCH_SIZE,
) -> dict[str, Any]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    stations = load_station_catalog(flow_catalog, rain_catalog)
    observed = load_observed_rain(observed_csv, now=now)
    levels = load_level_snapshots(live_feeds)

    for item in stations:
        item["observed_rain"] = observed.get(
            item["code"],
            {
                "state": "unavailable",
                "source": "ANA/INMET/CEMADEN · chuvas_horarias.csv",
                "unit": "mm",
                "rows": [],
                "available_points": 0,
                "expected_points": 0,
                "last_observed_at_utc": None,
                "windows": _observed_window_stats(
                    [], latest_observed=None, windows=OBSERVED_WINDOW_HOURS
                ),
                "message": "Não há coluna observada publicada para esta estação.",
            },
        )
        item["level"] = _decorate_level_snapshot(
            levels.get(item["code"], _unavailable_level(item["code"])),
            now=now,
        )
        item["forecast"] = _unavailable_forecast("Aguardando a rodada meteorológica.")

    forecast_locations = _unique_forecast_locations(stations)
    forecasts_by_coordinate: dict[tuple[float, float], dict[str, Any]] = {}
    for start in range(0, len(forecast_locations), batch_size):
        batch = forecast_locations[start : start + batch_size]
        try:
            response = fetcher(build_open_meteo_url(batch))
            payloads = response if isinstance(response, list) else [response]
            if len(payloads) != len(batch):
                raise ValueError(
                    f"Open-Meteo retornou {len(payloads)} locais para {len(batch)} pedidos"
                )
            for location, payload in zip(batch, payloads):
                forecasts_by_coordinate[_coordinate_key(location)] = extract_forecast_payload(
                    payload,
                    fetched_at_utc=iso_utc(now),
                )
        except Exception as exc:
            message = f"Rodada não disponível para este lote: {exc}"
            for location in batch:
                forecasts_by_coordinate[_coordinate_key(location)] = _unavailable_forecast(message)
        if start + batch_size < len(forecast_locations):
            # Avoid bursting the public endpoint when the catalog is large.
            time.sleep(BATCH_PAUSE_SECONDS)

    for item in stations:
        item["forecast"] = forecasts_by_coordinate.get(
            _coordinate_key(item),
            _unavailable_forecast("A coordenada não retornou previsão nesta rodada."),
        )

    available_forecasts = sum(item["forecast"]["state"] == "available" for item in stations)
    available_observations = sum(item["observed_rain"]["state"] == "available" for item in stations)
    available_levels = sum(
        item["level"]["state"] in {"available", "partial"} for item in stations
    )
    complete_forecast = available_forecasts == len(stations)
    return {
        "schema_version": 1,
        "feed_type": "basin_station_multi_model_forecast",
        "status": "RESEARCH_SCREENING" if complete_forecast else "RESEARCH_SCREENING_DEGRADED",
        "research_only": True,
        "official_alert": False,
        "generated_at_utc": iso_utc(now),
        "next_cycle_utc": iso_utc(_next_cycle(now)),
        "refresh_contract": {
            "scheduled_every_hours": 6,
            "schedule_note": "GitHub Actions programado para 00:17, 06:17, 12:17 e 18:17 UTC.",
        },
        "scope": {
            "basin": "Taquari–Antas · G040",
            "station_count": len(stations),
            "forecast_location_count": len(forecast_locations),
            "forecast_station_count": available_forecasts,
            "observed_rain_station_count": available_observations,
            "level_station_count": available_levels,
            **_coordinate_coverage(stations),
            "catalogs": [
                "assets/data/estudo_bacia_taquari_antas/postos_g040.geojson",
                "assets/data/estudo_bacia_taquari_antas/pluviometria_g040.geojson",
            ],
        },
        "coverage": {
            "forecast_complete": complete_forecast,
            "forecast_missing_station_count": len(stations) - available_forecasts,
            "message": (
                "Cobertura completa da rodada meteorológica."
                if complete_forecast
                else "Cobertura parcial: estações sem resposta permanecem como indisponíveis."
            ),
        },
        "models": list(MODEL_SPECS),
        "metric_coverage": _metric_coverage(stations),
        "metrics": [
            {"id": "precipitation", "label": "Chuva", "unit": "mm", "source_state": "forecast", "sampling": "ponto horário do modelo exibido a cada 3 h; acumulados de 3 h, 6 h e 24 h somente com série horária completa"},
            {"id": "level_cm", "label": "Nível", "unit": "cm", "source_state": "observed_and_experimental_forecast", "sampling": "observação publicada em até 72 h; previsão RNA por horizonte"},
            {"id": "temperature_2m", "label": "Temperatura", "unit": "°C", "source_state": "forecast"},
            {"id": "relative_humidity_2m", "label": "Umidade relativa", "unit": "%", "source_state": "forecast"},
            {"id": "pressure_msl", "label": "Pressão ao nível do mar", "unit": "hPa", "source_state": "forecast"},
            {"id": "wind_speed_10m", "label": "Vento", "unit": "km/h", "source_state": "forecast"},
            {"id": "wind_gusts_10m", "label": "Rajada", "unit": "km/h", "source_state": "forecast"},
            {"id": "cloud_cover", "label": "Nuvens", "unit": "%", "source_state": "forecast"},
            {"id": "precipitation_probability", "label": "Probabilidade de chuva", "unit": "%", "source_state": "forecast"},
            {"id": "soil_moisture_0_to_7cm", "label": "Umidade do solo", "unit": "m³/m³", "source_state": "forecast"},
        ],
        "provenance": {
            "forecast_provider": "Open-Meteo · saída individual de cinco famílias de modelos",
            "forecast_source": "https://api.open-meteo.com/v1/forecast",
            "observed_rain_source": "assets/data/chuvas_horarias.csv",
            "level_sources": [
                "previsao_ao_vivo.json",
                "previsao_ao_vivo_mucum.json",
            ],
            "message": (
                "Previsão meteorológica e telemetria de pesquisa. "
                "Não é alerta oficial, ordem de evacuação ou confirmação de inundação."
            ),
        },
        "stations": stations,
    }


def validate_complete_feed(feed: dict[str, Any]) -> None:
    """Reject partial forecast runs so they cannot replace a complete snapshot."""

    scope = feed.get("scope") or {}
    station_count = int(scope.get("station_count") or 0)
    forecast_count = int(scope.get("forecast_station_count") or 0)
    if station_count and forecast_count != station_count:
        raise RuntimeError(
            f"Rodada incompleta: {forecast_count}/{station_count} estações com previsão; "
            "o snapshot anterior deve ser preservado."
        )

    expected_models = {spec["id"] for spec in MODEL_SPECS}
    for station in feed.get("stations") or []:
        station_id = station.get("id") or station.get("code") or "estação"
        forecast = station.get("forecast") or {}
        if forecast.get("state") != "available":
            raise RuntimeError(f"Previsão indisponível para {station_id}.")
        times = forecast.get("times") or []
        models = forecast.get("models") or {}
        missing_models = expected_models.difference(models)
        if missing_models:
            raise RuntimeError(
                f"Modelos ausentes para {station_id}: {', '.join(sorted(missing_models))}."
            )
        for model_id in expected_models:
            model = models[model_id]
            for variable in REQUIRED_FORECAST_VARIABLES:
                values = model.get(variable)
                if not isinstance(values, list) or len(values) != len(times):
                    raise RuntimeError(
                        f"Série inválida {station_id}/{model_id}/{variable}: "
                        f"{len(values) if isinstance(values, list) else 'sem série'} "
                        f"pontos para {len(times)} horários."
                    )
                if not any(finite(value) is not None for value in values):
                    raise RuntimeError(
                        f"Série vazia {station_id}/{model_id}/{variable}."
                    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    feed = build_feed()
    validate_complete_feed(feed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(feed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "feed written:",
        args.output,
        "stations=",
        feed["scope"]["station_count"],
        "forecast=",
        feed["scope"]["forecast_station_count"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
