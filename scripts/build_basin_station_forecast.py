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

FORECAST_DAYS = 4
FORECAST_STEP_HOURS = 3
OBSERVED_HOURS = 72
BATCH_SIZE = 50
BATCH_PAUSE_SECONDS = 10.0
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
        result[code] = {
            "state": "available" if known else "unavailable",
            "source": "ANA/INMET/CEMADEN · chuvas_horarias.csv",
            "unit": "mm",
            "timezone": "America/Sao_Paulo",
            "rows": selected,
            "available_points": len(known),
            "message": (
                "Série observada publicada pelo robô de chuva."
                if known
                else "Não há série observada publicada para este código."
            ),
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


def fetch_json(url: str, *, attempts: int = 2, timeout: int = 20) -> Any:
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
                    # Keep a scheduled GitHub run bounded when the public
                    # endpoint rate-limits the runner. A later six-hour run
                    # can replace the degraded snapshot after the limit lifts.
                    delay = max(delay, 10.0 * (attempt + 1))
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


def extract_forecast_payload(
    payload: dict[str, Any],
    *,
    step_hours: int = FORECAST_STEP_HOURS,
) -> dict[str, Any]:
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not isinstance(hourly, dict):
        return {
            "state": "unavailable",
            "times": [],
            "models": {},
            "message": "Resposta sem bloco hourly.",
        }
    raw_times = hourly.get("time") or []
    indices = _sample_indices(list(raw_times), step_hours)
    times = []
    for index in indices:
        parsed = parse_iso(raw_times[index], default_timezone=UTC)
        if parsed is not None:
            times.append(iso_utc(parsed))

    models: dict[str, dict[str, list[float | None]]] = {}
    for spec in MODEL_SPECS:
        model_id = spec["id"]
        model_payload: dict[str, list[float | None]] = {}
        for variable in FORECAST_VARIABLES:
            values = hourly.get(f"{variable}_{model_id}") or []
            model_payload[variable] = [
                finite(values[index]) if index < len(values) else None
                for index in indices
            ]
        if any(any(value is not None for value in values) for values in model_payload.values()):
            models[model_id] = model_payload
    if not times or not models:
        return {
            "state": "unavailable",
            "times": [],
            "models": {},
            "message": "Nenhum modelo retornou série utilizável.",
        }
    return {
        "state": "available",
        "times": times,
        "models": models,
        "message": "Previsão horária amostrada para leitura comparativa.",
    }


def _unavailable_forecast(message: str) -> dict[str, Any]:
    return {
        "state": "unavailable",
        "times": [],
        "models": {},
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
                "message": "Não há coluna observada publicada para esta estação.",
            },
        )
        item["level"] = levels.get(item["code"], _unavailable_level(item["code"]))
        item["forecast"] = _unavailable_forecast("Aguardando a rodada meteorológica.")

    for start in range(0, len(stations), batch_size):
        batch = stations[start : start + batch_size]
        try:
            response = fetcher(build_open_meteo_url(batch))
            payloads = response if isinstance(response, list) else [response]
            if len(payloads) != len(batch):
                raise ValueError(
                    f"Open-Meteo retornou {len(payloads)} locais para {len(batch)} pedidos"
                )
            for item, payload in zip(batch, payloads):
                item["forecast"] = extract_forecast_payload(payload)
        except Exception as exc:
            message = f"Rodada não disponível para este lote: {exc}"
            for item in batch:
                item["forecast"] = _unavailable_forecast(message)
        if start + batch_size < len(stations):
            # Avoid bursting the public endpoint when the catalog is large.
            time.sleep(BATCH_PAUSE_SECONDS)

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
            "forecast_station_count": available_forecasts,
            "observed_rain_station_count": available_observations,
            "level_station_count": available_levels,
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
        "metrics": [
            {"id": "precipitation", "label": "Chuva", "unit": "mm", "source_state": "forecast", "sampling": "horário do modelo, exibido a cada 3 h"},
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
