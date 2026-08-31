"""Build the prospective Santa Tereza meteorological research feed.

The spatial aggregate in this file is deliberately called an *upstream
monitoring-grid proxy*.  The catalog contains audited gauges/targets, not a
validated hydrologic catchment mask, so the result must never be presented as
an area-weighted basin mean.  The builder refreshes observations, point rain,
the spatial proxy and modelled soil moisture; it does not create or promote a
flood probability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from .ecmwf_direct import fetch_ecmwf_direct
except ImportError:  # direct execution
    from ecmwf_direct import fetch_ecmwf_direct


ROOT = Path(__file__).resolve().parents[1]
STATION_CODE = "86472600"
STATION_NAME = "Santa Tereza"
LATITUDE = -29.1781
LONGITUDE = -51.7322
FLOOD_THRESHOLD_CM = 1500
HORIZONS = (24, 48, 72, 96, 120, 168)
SCREENING_THRESHOLDS = {24: 40.0, 72: 80.0, 168: 120.0}
BRT = timezone(timedelta(hours=-3))


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_hour(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=BRT).astimezone(timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_forecast_hour(value: str) -> datetime:
    """Parse an Open-Meteo hour requested with ``timezone=UTC``.

    Open-Meteo returns local-looking strings without a suffix even when the
    requested timezone is UTC.  Robot timestamps without suffix are BRT, so
    the two contracts must remain separate.
    """
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def load_catalog(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    points = raw.get("points")
    if not isinstance(points, list) or not points:
        raise ValueError("catálogo de pontos vazio ou inválido")
    targets = [item for item in points if item.get("role") == "target_santa_tereza"]
    if len(targets) != 1:
        raise ValueError("catálogo deve conter exatamente um alvo Santa Tereza")
    return raw


def catalog_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_open_meteo(points: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    params = {
        "latitude": ",".join(str(item["latitude"]) for item in points),
        "longitude": ",".join(str(item["longitude"]) for item in points),
        "models": "ecmwf_ifs025",
        "hourly": "precipitation,soil_moisture_0_to_7cm,temperature_2m",
        # Eight calendar days are requested so a complete rolling +168 h
        # window remains possible late in the UTC day.
        "forecast_days": 8,
        "timezone": "UTC",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "PREVINE-Santa-Tereza-research/2.0"})
    with urlopen(request, timeout=45) as response:
        payload = json.load(response)
    payloads = payload if isinstance(payload, list) else [payload]
    if len(payloads) != len(points):
        raise RuntimeError(f"Open-Meteo retornou {len(payloads)} locais para {len(points)} pedidos")
    return payloads, url


def read_live(path: Path, now: datetime) -> dict[str, Any]:
    if not path.exists():
        return {"state": "unknown_or_stale", "message": "Robô de nível não disponível."}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        observed = (
            raw.get("telemetria_ultima_em_utc")
            or raw.get("nivel_rio_agora_em_utc")
            or raw.get("telemetria_ultima_em")
            or raw.get("nivel_rio_agora_em")
        )
        observed_at = parse_hour(observed) if observed else None
        age = max(0.0, (now - observed_at).total_seconds() / 60.0) if observed_at else None
        level = raw.get("telemetria_ultima_nivel_cm", raw.get("nivel_rio_agora_cm"))
        fresh = age is not None and age <= 90
        return {
            "state": "fresh" if fresh else "unknown_or_stale",
            "level_cm": finite(level),
            "observed_at_utc": iso_utc(observed_at) if observed_at else None,
            "timestamp_utc": iso_utc(observed_at) if observed_at else None,
            "age_minutes": round(age, 1) if age is not None else None,
            "source": "robô ao vivo Santa Tereza / estação ANA-SGB 86472600",
            "quality": raw.get("status_dados"),
            "message": "Leitura recente do robô ao vivo." if fresh else "Leitura atrasada; não usar como normalidade.",
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {"state": "unknown_or_stale", "message": f"Leitura não pôde ser validada: {exc}"}


def hourly_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    hourly = payload.get("hourly") if isinstance(payload.get("hourly"), dict) else {}
    times = hourly.get("time") or []
    rain = hourly.get("precipitation") or []
    soil = hourly.get("soil_moisture_0_to_7cm") or []
    temperature = hourly.get("temperature_2m") or []
    return [
        {
            "time": parse_forecast_hour(value),
            "rain": finite(rain[index]) if index < len(rain) else None,
            "soil": finite(soil[index]) if index < len(soil) else None,
            "temperature": finite(temperature[index]) if index < len(temperature) else None,
        }
        for index, value in enumerate(times)
    ]


def values_until(rows: list[dict[str, Any]], field: str, now: datetime, hours: int) -> list[float]:
    end = now + timedelta(hours=hours)
    return [row[field] for row in rows if now < row["time"] <= end and row.get(field) is not None]


def build_feed(
    api_payloads: list[dict[str, Any]],
    source_url: str,
    live_path: Path,
    catalog_path: Path,
    *,
    now: datetime | None = None,
    direct: dict[str, Any] | None = None,
    previous_path: Path | None = None,
) -> dict[str, Any]:
    now = (now or utc_now()).astimezone(timezone.utc)
    catalog = load_catalog(catalog_path)
    points = catalog["points"]
    if len(api_payloads) != len(points):
        raise ValueError("quantidade de respostas meteorológicas não coincide com o catálogo")

    direct = direct if direct is not None else fetch_ecmwf_direct(
        now,
        latitude=LATITUDE,
        longitude=LONGITUDE,
        target_name=STATION_NAME,
    )
    direct_by_hour = {
        int(item["hours"]): item
        for item in direct.get("horizons", [])
        if item.get("hours") is not None
    }

    previous_path = previous_path or ROOT / "assets/data/research_weather_santa_tereza_latest.json"
    previous: dict[str, Any] = {}
    if previous_path.exists():
        try:
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            previous = {}
    previous_horizons = {
        int(item.get("hours", item.get("horizon_hours"))): item
        for item in previous.get("horizons", [])
        if item.get("hours", item.get("horizon_hours")) is not None
    }

    records: list[dict[str, Any]] = []
    for point, payload in zip(points, api_payloads):
        returned_lat = finite(payload.get("latitude"))
        returned_lon = finite(payload.get("longitude"))
        records.append(
            {
                "point": point,
                "payload": payload,
                "rows": hourly_rows(payload),
                "grid_key": (round(returned_lat, 4), round(returned_lon, 4))
                if returned_lat is not None and returned_lon is not None
                else (round(float(point["latitude"]), 4), round(float(point["longitude"]), 4)),
            }
        )

    target = next(item for item in records if item["point"].get("role") == "target_santa_tereza")
    upstream = [item for item in records if item["point"].get("role") == "upstream_monitoring_point"]
    unique_upstream: dict[tuple[float, float], dict[str, Any]] = {}
    for item in upstream:
        unique_upstream.setdefault(item["grid_key"], item)
    if not unique_upstream:
        raise ValueError("nenhuma célula de monitoramento a montante disponível")

    horizons: list[dict[str, Any]] = []
    forecast_horizons: list[dict[str, Any]] = []
    for hours in HORIZONS:
        old = previous_horizons.get(hours, {})
        target_rain = values_until(target["rows"], "rain", now, hours)
        target_soil = values_until(target["rows"], "soil", now, hours)
        target_temp = values_until(target["rows"], "temperature", now, hours)
        cell_totals: list[float] = []
        cell_coverages: list[int] = []
        for item in unique_upstream.values():
            values = values_until(item["rows"], "rain", now, hours)
            if values:
                cell_totals.append(sum(values))
                cell_coverages.append(len(values))
        point_mm = round(sum(target_rain), 2) if target_rain else None
        mean_mm = round(sum(cell_totals) / len(cell_totals), 2) if cell_totals else None
        max_mm = round(max(cell_totals), 2) if cell_totals else None
        direct_mm = direct_by_hour.get(hours, {}).get("rain_point_mm")
        coverage = len(target_rain)
        complete = coverage >= hours and len(cell_coverages) == len(unique_upstream) and all(
            item >= hours for item in cell_coverages
        )
        item = {
            "hours": hours,
            "horizon_hours": hours,
            "rain_point_mm": point_mm,
            "rain_ecmwf_direct_mm": direct_mm,
            "rain_ecmwf_direct_minus_openmeteo_mm": round(direct_mm - point_mm, 2)
            if direct_mm is not None and point_mm is not None
            else None,
            "rain_ifs_proxy_mm": mean_mm,
            "basin_mean_mm": mean_mm,
            "basin_max_mm": max_mm,
            "spatial_metric_label": "proxy médio dos pontos monitorados a montante",
            "screening_threshold_mm": SCREENING_THRESHOLDS.get(hours),
            "rain_hours_available": coverage,
            "spatial_cells_available": len(cell_totals),
            "forecast_complete": complete,
            "soil_moisture_model_mean_m3m3": round(sum(target_soil) / len(target_soil), 3)
            if target_soil
            else None,
            "temperature_model_mean_c": round(sum(target_temp) / len(target_temp), 1)
            if target_temp
            else None,
            # A atualização meteorológica preserva resultados de outra cadeia,
            # mas não os recalcula nem os promove como previsão atual.
            "flood_probability": old.get("flood_probability"),
            "flood_probability_percent": old.get("flood_probability_percent"),
        }
        horizons.append(item)
        forecast_horizons.append(
            {
                "horizon_hours": hours,
                "target_santa_tereza_mm": point_mm,
                "upstream_monitoring_proxy_mean_mm": mean_mm,
                "upstream_monitoring_proxy_max_mm": max_mm,
                # Compatibility fields; their interpretation is explicitly
                # constrained by ``basin_aggregation``.
                "basin_mean_mm": mean_mm,
                "basin_max_mm": max_mm,
                "screening_threshold_mm": SCREENING_THRESHOLDS.get(hours),
            }
        )

    cycle = direct.get("cycle_time_utc") if direct.get("status") == "available" else None
    observation = read_live(live_path, now)
    previous_risk = previous.get("risk_model") if isinstance(previous.get("risk_model"), dict) else {}
    return {
        "schema_version": 3,
        "feed_type": "meteorological_forecast",
        "status": "RESEARCH_SCREENING",
        "research_only": True,
        "official_alert": False,
        "station_code": STATION_CODE,
        "station_name": STATION_NAME,
        "coordinates": {"latitude": LATITUDE, "longitude": LONGITUDE},
        "official_flood_threshold_cm": FLOOD_THRESHOLD_CM,
        "generated_at_utc": iso_utc(now),
        "forecast_kind": "prospective_point_and_upstream_monitoring_grid_proxy",
        "forecast_provider": "ECMWF IFS via Open-Meteo; ECMWF Open Data direto para auditoria",
        "forecast_model": "ECMWF IFS 0.25° (ecmwf_ifs025)",
        "forecast_source_url": source_url,
        "availability_is_exact_historical_timestamp": False,
        "current_forecast_state": "available" if horizons and horizons[0]["rain_point_mm"] is not None else "unknown_or_stale",
        "current_forecast_message": "Chuva no ponto e proxy dos pontos monitorados a montante. Não é média hidrológica oficial da bacia.",
        "observation": observation,
        "forecast": {
            "source": "ECMWF IFS",
            "run_time_utc": cycle,
            "available_at_utc": iso_utc(now),
            "requested_points": len(points),
            "unique_upstream_grid_cells": len(unique_upstream),
            "horizons": forecast_horizons,
        },
        "ecmwf_direct": direct,
        "basin_aggregation": {
            "status": "upstream_monitoring_grid_proxy",
            "method": "média simples e máximo de células IFS únicas associadas a pontos monitorados a montante",
            "metric_label": "proxy dos pontos monitorados a montante",
            "hydrologic_mask": False,
            "area_weighted": False,
            "requested_locations": len(points),
            "upstream_monitoring_points": len(upstream),
            "unique_upstream_grid_cells": len(unique_upstream),
            "target_station_excluded": True,
            "target_station_code": STATION_CODE,
            "deduplication_applied": True,
            "point_catalog_sha256": catalog_sha256(catalog_path),
            "note": "Rede de monitoramento auditada; não substitui polígonos de cabeceira nem média ponderada por área.",
        },
        "soil_moisture": {
            "status": "modeled_proxy",
            "observation_available": False,
            "message": "Umidade superficial modelada no ponto; não é sensor local nem percentual de saturação.",
        },
        "risk_model": previous_risk or {
            "status": "not_computed_by_weather_robot",
            "probabilities_available": False,
            "official_alert": False,
            "promotion_allowed": False,
            "message": "Este robô atualiza meteorologia e observação; não fabrica probabilidade de transbordamento.",
        },
        "horizons": horizons,
        "limitations": [
            "o agregado espacial é proxy de pontos monitorados, não média hidrológica de toda a bacia",
            "as células são deduplicadas, mas não há ponderação por área nem máscara de cabeceiras validada",
            "umidade do solo é modelada, não medição local de saturação",
            "probabilidades preservadas pertencem a outra cadeia e devem exibir fonte e idade próprias",
            "não substitui ANA, SGB, SACE ou Defesa Civil",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "assets/data/research_weather_santa_tereza_latest.json")
    parser.add_argument("--live-json", type=Path, default=ROOT / "previsao_ao_vivo.json")
    parser.add_argument("--point-catalog", type=Path, default=ROOT / "assets/data/basin_forecast_points.json")
    args = parser.parse_args()
    catalog = load_catalog(args.point_catalog)
    payloads, source_url = fetch_open_meteo(catalog["points"])
    feed = build_feed(payloads, source_url, args.live_json, args.point_catalog, previous_path=args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    partial = args.output.with_suffix(args.output.suffix + ".partial")
    partial.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial.replace(args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "generated_at_utc": feed["generated_at_utc"],
                "unique_upstream_grid_cells": feed["basin_aggregation"]["unique_upstream_grid_cells"],
                "horizons": [item["hours"] for item in feed["horizons"]],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
