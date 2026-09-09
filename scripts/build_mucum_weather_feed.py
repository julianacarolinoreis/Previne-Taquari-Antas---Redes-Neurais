"""Build the Muçum long-horizon meteorological research feed.

This feed is deliberately separate from ``previsao_ao_vivo_mucum.json``.
The live robot owns the +2 h/+4 h level forecasts; this file only publishes
prospective IFS rain, an independent upstream monitoring-grid proxy and
modeled soil-moisture context.  It never creates a flood probability or an
official alert.

The spatial aggregate uses the same Open-Meteo multi-point pattern as Santa
Tereza, but ownership is Muçum's: upstream cells include monitoring points and
Santa Tereza, and exclude the Muçum target itself.  The published SRTM
watershed polygon is cited only as catchment provenance — it is not an
area-weighted hydrologic mask.
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
except ImportError:  # direct execution: ``python scripts/build_mucum_weather_feed.py``
    from ecmwf_direct import fetch_ecmwf_direct


ROOT = Path(__file__).resolve().parents[1]
STATION_CODE = "86510000"
STATION_NAME = "Muçum"
LATITUDE = -29.1672
LONGITUDE = -51.8686
FLOOD_THRESHOLD_CM = 1800
HORIZONS = (24, 48, 72, 120, 168)
BRT = timezone(timedelta(hours=-3))
WATERSHED_GEOJSON = ROOT / "assets/data/hec_hms_spatialized_mucum/watershed_86510000_srtm.geojson"
WATERSHED_REPORT = ROOT / "assets/data/hec_hms_spatialized_mucum/watershed_preparation_report.json"
UPSTREAM_ROLES = frozenset({"upstream_monitoring_point", "target_santa_tereza"})


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_hour(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        # Os robôs antigos publicam alguns horários sem fuso em BRT. Sem
        # esta marcação, a leitura seria tratada como UTC e pareceria três
        # horas mais antiga no feed meteorológico.
        return parsed.replace(tzinfo=BRT).astimezone(timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_forecast_hour(value: str) -> datetime:
    """Interpret Open-Meteo hourly values in the requested UTC timezone."""
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


def catalog_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_catalog(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    points = raw.get("points")
    if not isinstance(points, list) or not points:
        raise ValueError("catálogo de pontos vazio ou inválido")
    targets = [item for item in points if item.get("role") == "target_mucum"]
    if len(targets) != 1:
        raise ValueError("catálogo deve conter exatamente um alvo Muçum")
    return raw


def watershed_provenance() -> dict[str, Any]:
    """Cite the published SRTM Muçum watershed without claiming area weights."""
    report: dict[str, Any] = {}
    if WATERSHED_REPORT.exists():
        try:
            loaded = json.loads(WATERSHED_REPORT.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                report = loaded
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            report = {}
    outlet = report.get("outlet") if isinstance(report.get("outlet"), dict) else {}
    return {
        "path": "assets/data/hec_hms_spatialized_mucum/watershed_86510000_srtm.geojson",
        "report_path": "assets/data/hec_hms_spatialized_mucum/watershed_preparation_report.json",
        "exists": WATERSHED_GEOJSON.exists(),
        "sha256": catalog_sha256(WATERSHED_GEOJSON) if WATERSHED_GEOJSON.exists() else None,
        "report_sha256": catalog_sha256(WATERSHED_REPORT) if WATERSHED_REPORT.exists() else None,
        "srtm_area_km2": finite(report.get("srtm_area_km2")),
        "srtm_to_ana_area_ratio": finite(report.get("srtm_to_ana_area_ratio")),
        "ana_declared_area_km2": finite(outlet.get("ana_declared_area_km2")),
        "outlet_station": outlet.get("station") or STATION_CODE,
        "hydrologic_mask_validated": False,
        "area_weighted_rainfall": False,
        "note": (
            "Polígono SRTM usado só como proveniência da bacia de Muçum. "
            "A chuva agregada continua sendo média simples de células IFS "
            "associadas a pontos monitorados, sem ponderação por área."
        ),
    }


def fetch_open_meteo(points: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    params = {
        "latitude": ",".join(str(item["latitude"]) for item in points),
        "longitude": ",".join(str(item["longitude"]) for item in points),
        "models": "ecmwf_ifs025",
        "hourly": "precipitation,soil_moisture_0_to_7cm,temperature_2m",
        # Eight calendar days keep a complete rolling +168 h window even when
        # the workflow runs after 00 UTC.
        "forecast_days": 8,
        "timezone": "UTC",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "PREVINE-Mucum-research/2.0"})
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
        # Preferir o campo explícito em UTC quando o robô o publica. O campo
        # sem fuso é mantido como fallback e é interpretado como BRT por
        # ``parse_hour``.
        observed = (
            raw.get("telemetria_ultima_em_utc")
            or raw.get("nivel_rio_agora_em_utc")
            or raw.get("telemetria_ultima_em")
            or raw.get("nivel_rio_agora_em")
        )
        age = None
        observed_at_utc = None
        if observed:
            observed_at_utc = parse_hour(observed)
            age = max(0.0, (now - observed_at_utc).total_seconds() / 60.0)
        level = raw.get("telemetria_ultima_nivel_cm", raw.get("nivel_rio_agora_cm"))
        fresh = age is not None and age <= 90
        return {
            "state": "fresh" if fresh else "unknown_or_stale",
            "level_cm": level,
            "observed_at_utc": iso_utc(observed_at_utc) if observed_at_utc else None,
            "age_minutes": round(age, 1) if age is not None else None,
            "source": "robô ao vivo Muçum / estação ANA 86510000",
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

    ecmwf_direct = direct if direct is not None else fetch_ecmwf_direct(
        now,
        latitude=LATITUDE,
        longitude=LONGITUDE,
        target_name=STATION_NAME,
    )
    ecmwf_by_hour = {
        int(item.get("hours")): item
        for item in ecmwf_direct.get("horizons", [])
        if item.get("hours") is not None
    }

    previous_path = previous_path or ROOT / "assets/data/research_weather_mucum_latest.json"
    previous: dict[str, Any] = {}
    if previous_path.exists():
        try:
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            previous = {}
    previous_horizons = {
        int(item.get("hours")): item
        for item in previous.get("horizons", [])
        if item.get("hours") is not None
    }
    previous_risk = previous.get("risk_model") if isinstance(previous.get("risk_model"), dict) else {}

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

    target = next(item for item in records if item["point"].get("role") == "target_mucum")
    upstream = [item for item in records if item["point"].get("role") in UPSTREAM_ROLES]
    unique_upstream: dict[tuple[float, float], dict[str, Any]] = {}
    for item in upstream:
        unique_upstream.setdefault(item["grid_key"], item)
    if not unique_upstream:
        raise ValueError("nenhuma célula de monitoramento a montante disponível para Muçum")

    horizons: list[dict[str, Any]] = []
    for hours in HORIZONS:
        old = previous_horizons.get(hours, {})
        direct_row = ecmwf_by_hour.get(hours, {})
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
        point_mm = round(sum(target_rain), 1) if target_rain else None
        mean_mm = round(sum(cell_totals) / len(cell_totals), 2) if cell_totals else None
        max_mm = round(max(cell_totals), 2) if cell_totals else None
        direct_mm = direct_row.get("rain_point_mm")
        coverage = len(target_rain)
        complete = coverage >= hours and len(cell_coverages) == len(unique_upstream) and all(
            item >= hours for item in cell_coverages
        )
        horizons.append(
            {
                "hours": hours,
                "rain_point_mm": point_mm,
                "rain_ecmwf_direct_mm": direct_mm,
                "rain_ecmwf_direct_minus_openmeteo_mm": round(direct_mm - point_mm, 2)
                if direct_mm is not None and point_mm is not None
                else None,
                "rain_ifs_proxy_mm": mean_mm,
                "basin_mean_mm": mean_mm,
                "basin_max_mm": max_mm,
                "spatial_metric_label": "proxy médio dos pontos monitorados a montante (bacia Muçum)",
                "rain_hours_available": coverage,
                "spatial_cells_available": len(cell_totals),
                "forecast_complete": complete,
                "soil_moisture_model_mean_m3m3": round(sum(target_soil) / len(target_soil), 3)
                if target_soil
                else None,
                "temperature_model_mean_c": round(sum(target_temp) / len(target_temp), 1)
                if target_temp
                else None,
                "rain_gefs_proxy_mm": old.get("rain_gefs_proxy_mm"),
                # Preserve the separately generated research score across
                # the hourly meteorological refresh.  This robot must not
                # erase it merely because Open-Meteo ran.
                "flood_probability": old.get("flood_probability"),
                "flood_probability_percent": old.get("flood_probability_percent"),
                "flood_answer": old.get(
                    "flood_answer",
                    "indisponível — modelo Muçum 24–168 h ainda não calibrado",
                ),
            }
        )

    live = read_live(live_path, now)
    catchment = watershed_provenance()
    return {
        "schema_version": 2,
        "feed_type": "meteorological_forecast",
        "status": "research_only",
        "research_only": True,
        "official_alert": False,
        "station_code": STATION_CODE,
        "station_name": STATION_NAME,
        "coordinates": {"latitude": LATITUDE, "longitude": LONGITUDE},
        "official_flood_threshold_cm": FLOOD_THRESHOLD_CM,
        "generated_at_utc": iso_utc(now),
        "forecast_kind": "prospective_point_and_independent_upstream_monitoring_grid_proxy",
        "forecast_provider": "ECMWF IFS via Open-Meteo",
        "forecast_model": "ECMWF IFS 0.25° (ecmwf_ifs025)",
        "forecast_source_url": source_url,
        "ecmwf_direct": ecmwf_direct,
        "availability_is_exact_historical_timestamp": False,
        "current_forecast_state": "available" if horizons and horizons[0]["rain_point_mm"] is not None else "unknown_or_stale",
        "current_forecast_message": (
            "Chuva no ponto de Muçum e proxy independente dos pontos monitorados a montante "
            "(inclui Santa Tereza). O polígono SRTM da bacia é proveniência; a média não é "
            "ponderada por área. O ECMWF Open Data direto permanece como auditoria."
        ),
        "observation": live,
        "forecast": {
            "source": "ECMWF IFS",
            "requested_points": len(points),
            "unique_upstream_grid_cells": len(unique_upstream),
            "independent_for_station": True,
        },
        "basin_aggregation": {
            "status": "mucum_independent_upstream_monitoring_grid_proxy",
            "method": (
                "média simples e máximo de células IFS únicas associadas a pontos "
                "monitorados a montante e a Santa Tereza; alvo Muçum excluído"
            ),
            "metric_label": "proxy independente dos pontos monitorados a montante (Muçum)",
            "hydrologic_mask": False,
            "area_weighted": False,
            "independent_for_station": True,
            "requested_locations": len(points),
            "upstream_monitoring_points": len(upstream),
            "unique_upstream_grid_cells": len(unique_upstream),
            "target_station_excluded": True,
            "target_station_code": STATION_CODE,
            "includes_santa_tereza_as_upstream": True,
            "deduplication_applied": True,
            "point_catalog_sha256": catalog_sha256(catalog_path),
            "catchment_mask": catchment,
            "note": (
                "Proxy próprio de Muçum com proveniência no polígono SRTM. "
                "Não substitui máscara hidrológica validada nem média ponderada por área."
            ),
        },
        "soil_moisture": {
            "status": "modeled_proxy",
            "observation_available": False,
            "message": "Umidade do solo é uma variável modelada; não representa medição local de saturação.",
        },
        "risk_model": previous_risk if previous_risk.get("experimental_probability") else {
            "status": "not_available_for_mucum_long_horizon",
            "probabilities_available": False,
            "official_alert": False,
            "promotion_allowed": False,
            "message": "O robô de nível +2 h/+4 h permanece separado. Ainda não há modelo causal Muçum de 24–168 h validado.",
        },
        "horizons": horizons,
        "limitations": [
            "chuva pontual e proxy de pontos monitorados; não é média oficial de toda a bacia de Muçum",
            "o polígono SRTM é proveniência da bacia; a agregação ainda não é ponderada por área",
            "o horário histórico de disponibilização do IFS não é preservado pelo endpoint prospectivo",
            "estimativa experimental, quando presente, não é probabilidade calibrada nem alerta",
            "o ECMWF Open Data direto é conferência independente; a saída via Open-Meteo permanece registrada para comparação",
            "não substitui ANA, SGB, SACE ou Defesa Civil",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "assets/data/research_weather_mucum_latest.json")
    parser.add_argument("--live-json", type=Path, default=ROOT / "previsao_ao_vivo_mucum.json")
    parser.add_argument("--point-catalog", type=Path, default=ROOT / "assets/data/basin_forecast_points.json")
    args = parser.parse_args()
    catalog = load_catalog(args.point_catalog)
    payloads, url = fetch_open_meteo(catalog["points"])
    feed = build_feed(payloads, url, args.live_json, args.point_catalog, previous_path=args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".partial")
    tmp.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": feed["status"],
                "unique_upstream_grid_cells": feed["basin_aggregation"]["unique_upstream_grid_cells"],
                "independent_for_station": feed["basin_aggregation"]["independent_for_station"],
                "horizons": [h["hours"] for h in feed["horizons"]],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
