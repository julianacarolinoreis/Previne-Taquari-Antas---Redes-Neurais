"""Build the Muçum long-horizon meteorological research feed.

This feed is deliberately separate from ``previsao_ao_vivo_mucum.json``.
The live robot owns the +2 h/+4 h level forecasts; this file only publishes
prospective IFS rain and modeled soil-moisture context.  It never creates a
flood probability or an official alert.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from .ecmwf_direct import fetch_ecmwf_direct
except ImportError:  # direct execution: ``python scripts/build_mucum_weather_feed.py``
    from ecmwf_direct import fetch_ecmwf_direct


STATION_CODE = "86510000"
STATION_NAME = "Muçum"
LATITUDE = -29.1672
LONGITUDE = -51.8686
FLOOD_THRESHOLD_CM = 1800
HORIZONS = (24, 48, 72, 120, 168)
BRT = timezone(timedelta(hours=-3))


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


def fetch_open_meteo() -> tuple[dict, str]:
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "models": "ecmwf_ifs025",
        "hourly": "precipitation,soil_moisture_0_to_7cm,temperature_2m",
        # Eight calendar days keep a complete rolling +168 h window even when
        # the workflow runs after 00 UTC.
        "forecast_days": 8,
        "timezone": "UTC",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "PREVINE-Mucum-research/1.0"})
    with urlopen(request, timeout=30) as response:
        return json.load(response), url


def read_live(path: Path, now: datetime) -> dict:
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


def finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def build_feed(api: dict, source_url: str, live_path: Path) -> dict:
    now = utc_now()
    ecmwf_direct = fetch_ecmwf_direct(now)
    ecmwf_by_hour = {
        int(item.get("hours")): item
        for item in ecmwf_direct.get("horizons", [])
        if item.get("hours") is not None
    }
    previous = {}
    previous_horizons = {}
    previous_risk = {}
    output_path = Path("assets/data/research_weather_mucum_latest.json")
    if output_path.exists():
        try:
            previous = json.loads(output_path.read_text(encoding="utf-8"))
            previous_horizons = {
                int(item.get("hours")): item
                for item in previous.get("horizons", [])
                if item.get("hours") is not None
            }
            previous_risk = previous.get("risk_model", {})
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            previous_horizons = {}
            previous_risk = {}
    times = [parse_forecast_hour(value) for value in api.get("hourly", {}).get("time", [])]
    rain = api.get("hourly", {}).get("precipitation", [])
    soil = api.get("hourly", {}).get("soil_moisture_0_to_7cm", [])
    temperature = api.get("hourly", {}).get("temperature_2m", [])
    pairs = [(t, finite(rain[i]) if i < len(rain) else None) for i, t in enumerate(times)]
    soil_pairs = [(t, finite(soil[i]) if i < len(soil) else None) for i, t in enumerate(times)]
    temp_pairs = [(t, finite(temperature[i]) if i < len(temperature) else None) for i, t in enumerate(times)]

    horizons = []
    for hours in HORIZONS:
        old = previous_horizons.get(hours, {})
        direct = ecmwf_by_hour.get(hours, {})
        end = now + timedelta(hours=hours)
        selected = [v for t, v in pairs if now < t <= end and v is not None]
        soil_selected = [v for t, v in soil_pairs if now < t <= end and v is not None]
        temp_selected = [v for t, v in temp_pairs if now < t <= end and v is not None]
        point_mm = round(sum(selected), 1) if selected else None
        direct_mm = direct.get("rain_point_mm")
        horizons.append(
            {
                "hours": hours,
                "rain_point_mm": point_mm,
                "rain_ecmwf_direct_mm": direct_mm,
                "rain_ecmwf_direct_minus_openmeteo_mm": round(direct_mm - point_mm, 2)
                if direct_mm is not None and point_mm is not None
                else None,
                "rain_hours_available": len(selected),
                "soil_moisture_model_mean_m3m3": round(sum(soil_selected) / len(soil_selected), 3)
                if soil_selected
                else None,
                "temperature_model_mean_c": round(sum(temp_selected) / len(temp_selected), 1)
                if temp_selected
                else None,
                "rain_gefs_proxy_mm": old.get("rain_gefs_proxy_mm"),
                "rain_ifs_proxy_mm": old.get("rain_ifs_proxy_mm"),
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
    return {
        "schema_version": 1,
        "feed_type": "meteorological_forecast",
        "status": "research_only",
        "station_code": STATION_CODE,
        "station_name": STATION_NAME,
        "coordinates": {"latitude": LATITUDE, "longitude": LONGITUDE},
        "official_flood_threshold_cm": FLOOD_THRESHOLD_CM,
        "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
        "forecast_kind": "prospective_point_forecast",
        "forecast_provider": "ECMWF IFS via Open-Meteo",
        "forecast_model": "ECMWF IFS 0.25° (ecmwf_ifs025)",
        "forecast_source_url": source_url,
        "ecmwf_direct": ecmwf_direct,
        "availability_is_exact_historical_timestamp": False,
        "current_forecast_state": "available" if horizons and horizons[0]["rain_point_mm"] is not None else "unknown_or_stale",
        "current_forecast_message": "Chuva prevista no ponto da estação. O ECMWF Open Data direto é mantido como auditoria; a estimativa experimental, quando presente, não é alerta oficial.",
        "observation": live,
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
            "chuva é previsão pontual, não média de toda a bacia",
            "o horário histórico de disponibilização do IFS não é preservado pelo endpoint prospectivo",
            "estimativa experimental, quando presente, não é probabilidade calibrada nem alerta",
            "o ECMWF Open Data direto é conferência independente; a saída via Open-Meteo permanece registrada para comparação",
            "não substitui ANA, SGB, SACE ou Defesa Civil",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("assets/data/research_weather_mucum_latest.json"))
    parser.add_argument("--live-json", type=Path, default=Path("previsao_ao_vivo_mucum.json"))
    args = parser.parse_args()
    api, url = fetch_open_meteo()
    feed = build_feed(api, url, args.live_json)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".partial")
    tmp.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(args.output)
    print(json.dumps({"output": str(args.output), "status": feed["status"], "horizons": [h["hours"] for h in feed["horizons"]]}))


if __name__ == "__main__":
    main()
