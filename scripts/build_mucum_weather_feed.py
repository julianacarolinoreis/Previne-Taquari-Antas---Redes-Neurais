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


STATION_CODE = "86510000"
STATION_NAME = "Muçum"
LATITUDE = -29.1672
LONGITUDE = -51.8686
FLOOD_THRESHOLD_CM = 1800
HORIZONS = (24, 48, 72, 120, 168)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_hour(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_open_meteo() -> tuple[dict, str]:
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "models": "ecmwf_ifs025",
        "hourly": "precipitation,soil_moisture_0_to_7cm,temperature_2m",
        "forecast_days": 7,
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
        observed = raw.get("telemetria_ultima_em") or raw.get("nivel_rio_agora_em")
        age = None
        if observed:
            age = max(0.0, (now - parse_hour(observed)).total_seconds() / 60.0)
        level = raw.get("telemetria_ultima_nivel_cm", raw.get("nivel_rio_agora_cm"))
        fresh = age is not None and age <= 90
        return {
            "state": "fresh" if fresh else "unknown_or_stale",
            "level_cm": level,
            "observed_at_utc": observed,
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
    times = [parse_hour(value) for value in api.get("hourly", {}).get("time", [])]
    rain = api.get("hourly", {}).get("precipitation", [])
    soil = api.get("hourly", {}).get("soil_moisture_0_to_7cm", [])
    temperature = api.get("hourly", {}).get("temperature_2m", [])
    pairs = [(t, finite(rain[i]) if i < len(rain) else None) for i, t in enumerate(times)]
    soil_pairs = [(t, finite(soil[i]) if i < len(soil) else None) for i, t in enumerate(times)]
    temp_pairs = [(t, finite(temperature[i]) if i < len(temperature) else None) for i, t in enumerate(times)]

    horizons = []
    for hours in HORIZONS:
        end = now + timedelta(hours=hours)
        selected = [v for t, v in pairs if now < t <= end and v is not None]
        soil_selected = [v for t, v in soil_pairs if now < t <= end and v is not None]
        temp_selected = [v for t, v in temp_pairs if now < t <= end and v is not None]
        horizons.append(
            {
                "hours": hours,
                "rain_point_mm": round(sum(selected), 1) if selected else None,
                "rain_hours_available": len(selected),
                "soil_moisture_model_mean_m3m3": round(sum(soil_selected) / len(soil_selected), 3)
                if soil_selected
                else None,
                "temperature_model_mean_c": round(sum(temp_selected) / len(temp_selected), 1)
                if temp_selected
                else None,
                "flood_probability": None,
                "flood_answer": "indisponível — modelo Muçum 24–168 h ainda não calibrado",
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
        "forecast_provider": "Open-Meteo",
        "forecast_model": "ECMWF IFS 0.25° (ecmwf_ifs025)",
        "forecast_source_url": source_url,
        "availability_is_exact_historical_timestamp": False,
        "current_forecast_state": "available" if horizons and horizons[0]["rain_point_mm"] is not None else "unknown_or_stale",
        "current_forecast_message": "Chuva prevista no ponto da estação. Isso ainda não é uma probabilidade de inundação.",
        "observation": live,
        "soil_moisture": {
            "status": "modeled_proxy",
            "observation_available": False,
            "message": "Umidade do solo é uma variável modelada; não representa medição local de saturação.",
        },
        "risk_model": {
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
            "não há probabilidade de transbordamento neste feed",
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
