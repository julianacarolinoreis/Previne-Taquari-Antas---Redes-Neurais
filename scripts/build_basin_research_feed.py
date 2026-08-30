#!/usr/bin/env python3
"""Build the reader-facing research context for the Taquari--Antas basin.

This is a deliberately conservative *join* of artifacts that already exist in
the repository.  It does not manufacture a catchment mask, soil observation,
travel time, or calibrated flood probability.  Those fields are represented as
explicit states so that the dashboard can be useful while still being honest
about what is and is not supported by the data.

The feed is small, deterministic apart from its generation timestamp, and has
no network dependency.  The weather and level robots remain the owners of
their own feeds; this script only creates a normalized research view after a
robot or QA run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "data" / "research_basin_screening_latest.json"
HORIZONS = (24, 48, 72, 120, 168)
BRT = timezone(timedelta(hours=-3))

STATIONS: dict[str, dict[str, Any]] = {
    "santa_tereza": {
        "name": "Santa Tereza",
        "code": "86472600",
        "threshold_cm": 1500,
        "coordinates": {"latitude": -29.1781, "longitude": -51.7322},
        "weather": "assets/data/research_weather_santa_tereza_latest.json",
        "pattern": "assets/data/research_visual_patterns_santa_tereza_latest.json",
        "probability": "assets/data/research_probability_santa_tereza_latest.json",
        "binary": "assets/data/research_binary_decision_santa_tereza_latest.json",
        "live": "previsao_ao_vivo.json",
    },
    "mucum": {
        "name": "Muçum",
        "code": "86510000",
        "threshold_cm": 1800,
        "coordinates": {"latitude": -29.1672, "longitude": -51.8686},
        "weather": "assets/data/research_weather_mucum_latest.json",
        "pattern": "assets/data/research_visual_patterns_mucum_latest.json",
        "probability": "assets/data/research_probability_mucum_latest.json",
        "binary": "assets/data/research_binary_decision_mucum_latest.json",
        "live": "previsao_ao_vivo_mucum.json",
    },
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace(" ", "T")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    if len(raw) == 10 and raw[4] == "-":
        raw += "T00:00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    # Robot fields without a suffix are historical BRT fields.  Treating them
    # explicitly prevents a three-hour freshness error in the public view.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BRT)
    return parsed.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if value else None


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def integer(value: Any) -> int | None:
    result = number(value)
    return None if result is None else int(result)


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return default


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        output: list[dict[str, Any]] = []
        for key, item in value.items():
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.setdefault("hours", integer(key))
            output.append(row)
        return output
    return []


def row_at(value: Any, hours: int) -> dict[str, Any]:
    for row in rows(value):
        if integer(row.get("hours", row.get("horizon_hours"))) == hours:
            return row
    return {}


def age_hours(value: Any, now: datetime) -> float | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds() / 3600.0)


def age_state(age: float | None, *, stale_after: float) -> str:
    if age is None:
        return "unknown"
    return "stale" if age > stale_after else "fresh"


def latest_time(*values: Any) -> str | None:
    parsed = [parse_time(value) for value in values]
    parsed = [value for value in parsed if value is not None]
    return iso(max(parsed)) if parsed else None


def live_current(live: dict[str, Any], weather: dict[str, Any], now: datetime) -> dict[str, Any]:
    observation = weather.get("observation") if isinstance(weather.get("observation"), dict) else {}
    live_at = live.get("telemetria_ultima_em_utc") or live.get("nivel_rio_agora_em_utc") or live.get("telemetria_ultima_em") or live.get("nivel_rio_agora_em")
    weather_at = observation.get("observed_at_utc") or observation.get("timestamp_utc")
    selected_at = latest_time(live_at, weather_at)
    live_time = parse_time(live_at)
    weather_time = parse_time(weather_at)
    if live_time and (not weather_time or live_time >= weather_time):
        level = live.get("telemetria_ultima_nivel_cm", live.get("nivel_rio_agora_cm", live.get("nivel_atual_cm")))
        station_code = live.get("estacao") or live.get("codigo_estacao")
        source = f"ANA/SGB · estação {station_code}" if station_code else live.get("local") or "robô ao vivo"
        state = "fresh" if age_hours(live_at, now) is not None and age_hours(live_at, now) <= 3 else "stale"
    else:
        level = observation.get("level_cm")
        source = observation.get("source") or "ANA/SGB"
        state = observation.get("state") or age_state(age_hours(weather_at, now), stale_after=3)
    selected_age = age_hours(selected_at, now)
    return {
        "level_cm": number(level),
        "observed_at_utc": selected_at,
        "age_hours": round(selected_age, 2) if selected_age is not None else None,
        "state": state,
        "source": str(source),
        "change_24h_cm": number(observation.get("change_24h_cm")),
        "rain_observed_24h_mm": number(observation.get("rain_observed_24h_mm")),
        "rain_observed_72h_mm": number(observation.get("rain_observed_72h_mm")),
    }


def short_forecasts(live: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    live_horizons = live.get("horizontes") if isinstance(live.get("horizontes"), dict) else {}
    for label in ("2h", "4h"):
        item = live_horizons.get(label)
        if not isinstance(item, dict):
            continue
        output.append(
            {
                "hours": integer(item.get("horizonte_h")) or integer(label.rstrip("h")),
                "model": item.get("modelo"),
                "version": item.get("versao"),
                "issued_at_utc": latest_time(item.get("hora_modelo_utc"), item.get("hora_modelo")),
                "target_at_utc": latest_time(item.get("hora_alvo_utc"), item.get("hora_alvo")),
                "level_now_cm": number(item.get("nivel_rio_agora_cm", item.get("nivel_atual_cm"))),
                "level_forecast_cm": number(item.get("nivel_previsto_cm", item.get("nivel_previsto"))),
                "inputs_total": integer(item.get("inputs_total")),
                "inputs_missing": integer(item.get("inputs_faltantes_n")),
                "input_contract": item.get("input_contract_version"),
                "audit": {
                    "n_total": integer((item.get("auditoria") or {}).get("n_total")) if isinstance(item.get("auditoria"), dict) else None,
                    "n_conferidas": integer((item.get("auditoria") or {}).get("n_conferidas")) if isinstance(item.get("auditoria"), dict) else None,
                    "mae_24h_cm": number((item.get("auditoria") or {}).get("mae_24h_cm")) if isinstance(item.get("auditoria"), dict) else None,
                    "mae_ultimas_6_cm": number((item.get("auditoria") or {}).get("mae_ultimas_6_cm")) if isinstance(item.get("auditoria"), dict) else None,
                },
            }
        )
    return output


def event_summary(pattern: dict[str, Any], binary: dict[str, Any], *, location: str) -> dict[str, Any]:
    events = pattern.get("events") if isinstance(pattern.get("events"), list) else []
    summary = pattern.get("summary") if isinstance(pattern.get("summary"), dict) else {}
    statuses = [str(event.get("status", "")) for event in events if isinstance(event, dict)]
    confirmed = sum(1 for status in statuses if "confirm" in status.lower() or "acima da cota" in status.lower())
    candidates = len(events)
    model_card_count = integer(summary.get("model_card_event_count"))
    evaluation = pattern.get("evaluation") if isinstance(pattern.get("evaluation"), dict) else {}
    return {
        "candidate_events": candidates,
        "model_card_events": model_card_count,
        "confirmed_or_above_threshold_records": confirmed,
        "negative_control_events": None,
        "threshold_cm": integer(pattern.get("threshold_cm")),
        "label_definition": "pico observado acima da cota de pesquisa; Muçum ainda contém candidatos pendentes de revisão ANA/SACE",
        "training_mode": "shadow_only",
        "evaluation": {
            "model_verdict": evaluation.get("model_verdict") or (binary.get("evaluation") or {}).get("model_verdict"),
            "metric": evaluation.get("metric"),
            "by_horizon": evaluation.get("by_horizon") or (binary.get("evaluation") or {}).get("by_horizon") or [],
            "false_positive_metrics": evaluation.get("false_positive_metrics") or (binary.get("evaluation") or {}).get("false_positive_metrics"),
        },
        "note": "N pequeno e ausência de negativos independentes impedem calibração operacional; o resultado serve para comparação retrospectiva.",
    }


def geometry_summary() -> dict[str, Any]:
    path = ROOT / "assets" / "data" / "vulnerabilidade" / "bacia.geojson"
    value = load(path, {})
    features = value.get("features") if isinstance(value, dict) and isinstance(value.get("features"), list) else []
    coordinates: list[tuple[float, float]] = []

    def collect(item: Any) -> None:
        if isinstance(item, (list, tuple)):
            if len(item) >= 2 and all(number(x) is not None for x in item[:2]):
                coordinates.append((float(item[0]), float(item[1])))
            else:
                for child in item:
                    collect(child)

    for feature in features:
        if isinstance(feature, dict):
            collect((feature.get("geometry") or {}).get("coordinates"))
    bbox = None
    if coordinates:
        bbox = {
            "west": min(x[0] for x in coordinates),
            "south": min(x[1] for x in coordinates),
            "east": max(x[0] for x in coordinates),
            "north": max(x[1] for x in coordinates),
        }
    mdt_root = ROOT / "assets" / "data"
    mdt_files = [
        mdt_root / "santa_tereza_inundacao" / "mdt" / "altitude_terreno_10m.json",
        mdt_root / "santa_tereza_inundacao" / "mdt" / "altitude_terreno_10m.png",
        mdt_root / "santa_tereza_inundacao" / "mdt" / "mdt_santa_tereza_anadem_30m.tif",
        mdt_root / "santa_tereza_inundacao" / "mdt" / "mdt_santa_tereza_drone_1m.tif",
        mdt_root / "santa_tereza_inundacao" / "mdt" / "mdt_santa_tereza_drone_1m_ortho.tif",
        mdt_root / "mucum_inundacao" / "mdt" / "altitude_terreno_10m.json",
    ]
    assets = [{"path": rel(item), "sha256": sha256(item)} for item in mdt_files if item.exists()]
    return {
        "boundary": {
            "source": rel(path),
            "sha256": sha256(path),
            "geometry_type": (features[0].get("geometry") or {}).get("type") if features else None,
            "feature_count": len(features),
            "bbox": bbox,
            "status": "boundary_reference_only",
        },
        "mdt": {
            "assets": assets,
            "status": "terrain_reference_available",
            "flow_accumulation_available": False,
            "complete_regional_dem_published": False,
            "note": "Os MDTs publicados são referências locais; ainda não há rede hidrográfica, outlet e acumulação de fluxo validados para a bacia inteira.",
        },
        "hydrologic_delineation": {
            "status": "not_validated",
            "headwater_polygons": None,
            "outlet": None,
            "flow_accumulation": None,
            "reason": "A geometria disponível é o limite de referência da bacia, não uma delimitação derivada de fluxo com ponto de saída validado.",
        },
    }


def upstream_gauge_context() -> dict[str, Any]:
    """Expose the upstream gauges already used by the level models.

    These are observed level anchors, not rainfall zones.  Keeping them in the
    same artifact makes the distinction visible and gives the future
    hydrologic-mask work a reproducible inventory to start from.
    """
    model_path = ROOT / "assets" / "data" / "mucum_modelo_inputs.json"
    model = load(model_path, {})
    inputs = model.get("estacoes_input") if isinstance(model.get("estacoes_input"), dict) else {}
    santa_live = load(ROOT / "previsao_ao_vivo.json", {})
    live_rows = santa_live.get("estacoes_status") if isinstance(santa_live.get("estacoes_status"), list) else []
    live_by_code = {str(item.get("estacao")): item for item in live_rows if isinstance(item, dict) and item.get("estacao")}
    stations: list[dict[str, Any]] = []
    for code, item in inputs.items():
        if not isinstance(item, dict):
            continue
        role = str(item.get("papel", ""))
        lag = None
        marker = "lag ~"
        if marker in role:
            try:
                lag = float(role.split(marker, 1)[1].split("h", 1)[0].strip())
            except (TypeError, ValueError):
                lag = None
        live = live_by_code.get(str(code), {})
        stations.append(
            {
                "station_code": str(code),
                "name": item.get("nome"),
                "river": item.get("rio"),
                "role": role,
                "lag_hours_declared": lag,
                "coordinates": {"latitude": item.get("lat"), "longitude": item.get("lon")} if item.get("lat") is not None and item.get("lon") is not None else None,
                "telemetry": bool(item.get("telemetrica")),
                "current_level_cm": number(live.get("ultima_leitura_bruta_nivel_cm", live.get("ultima_hora_modelo_nivel_cm"))),
                "last_observation": live.get("ultima_leitura_bruta") or live.get("ultima_hora_modelo"),
                "quality": live.get("qc_status"),
            }
        )
    return {
        "status": "inventory_from_level_model_contract" if stations else "not_available",
        "stations": stations,
        "source": rel(model_path),
        "note": "Inventário de estações de nível/âncoras; não é uma máscara de cabeceiras nem uma chuva média da bacia.",
    }


def risk_for(pattern: dict[str, Any], probability: dict[str, Any], binary: dict[str, Any], hours: int, now: datetime) -> dict[str, Any]:
    p_row = row_at(pattern.get("horizons"), hours)
    p_horizons = probability.get("horizons")
    p_row_prob = p_horizons.get(str(hours), {}) if isinstance(p_horizons, dict) else row_at(p_horizons, hours)
    b_row = next((item for item in rows(binary.get("decisions")) if integer(item.get("hours")) == hours), {})
    value = number(p_row.get("probability_percent"))
    if value is None:
        raw = number(p_row_prob.get("probability"))
        if raw is not None:
            value = raw * 100.0
        else:
            value = number(p_row_prob.get("flood_probability_percent"))
    generated = probability.get("generated_at_utc") or pattern.get("generated_at_utc")
    age = age_hours(generated, now)
    calibration = probability.get("calibration_status")
    if calibration is None and "calibrated_for_current_source" in probability:
        calibration = "calibrated_for_declared_source" if probability.get("calibrated_for_current_source") else "not_calibrated_for_current_source"
    return {
        "probability_percent": value,
        "decision": b_row.get("decision") or p_row.get("decision"),
        "source": probability.get("forecast_source") or pattern.get("sources", {}).get("probability"),
        "generated_at_utc": generated,
        "age_hours": round(age, 2) if age is not None else None,
        "state": "stale" if age is None or age > 36 else "current_window",
        "calibration_status": calibration or "unknown",
        "usable_as_current_probability": bool(value is not None and age is not None and age <= 36 and probability.get("official_alert") is False),
        "research_only": True,
        "official_alert": False,
        "binary_threshold_percent": 50.0,
        "binary_source_decision": b_row.get("decision"),
    }


def station_context(key: str, now: datetime, santa_weather: dict[str, Any] | None = None) -> dict[str, Any]:
    config = STATIONS[key]
    weather_path = ROOT / config["weather"]
    pattern_path = ROOT / config["pattern"]
    probability_path = ROOT / config["probability"]
    binary_path = ROOT / config["binary"]
    live_path = ROOT / config["live"]
    weather = load(weather_path, {})
    pattern = load(pattern_path, {})
    probability = load(probability_path, {})
    binary = load(binary_path, {})
    live = load(live_path, {})
    current = live_current(live, weather, now)
    weather_generated = weather.get("generated_at_utc")
    forecast_age = age_hours(weather_generated, now)
    forecast_rows = {integer(row.get("hours", row.get("horizon_hours"))): row for row in rows(weather.get("horizons")) if integer(row.get("hours", row.get("horizon_hours"))) is not None}
    pattern_rows = {integer(row.get("hours", row.get("horizon_hours"))): row for row in rows(pattern.get("horizons")) if integer(row.get("hours", row.get("horizon_hours"))) is not None}

    horizon_rows: list[dict[str, Any]] = []
    for hours in HORIZONS:
        w = forecast_rows.get(hours, {})
        p = pattern_rows.get(hours, {})
        if key == "santa_tereza":
            point = number(w.get("rain_point_mm", p.get("point_mm")))
            mean = number(w.get("basin_mean_mm", p.get("ifs_mean_mm")))
            maximum = number(w.get("basin_max_mm", p.get("ifs_max_mm")))
            headwater = {
                "mean_mm": mean,
                "max_mm": maximum,
                "status": "proxy_spatial_recut" if mean is not None else "not_available",
                "source": "ECMWF IFS representative cells",
                "independent_for_station": True,
            }
            rain = {
                "point_mm": point,
                "basin_mean_mm": mean,
                "basin_max_mm": maximum,
                "headwater": headwater,
                "method": (weather.get("basin_aggregation") or {}).get("method"),
            }
        else:
            point = number(w.get("rain_ecmwf_direct_mm", w.get("rain_point_mm", p.get("ifs_direct_mm"))))
            direct_openmeteo = number(w.get("rain_point_mm", p.get("ifs_direct_mm")))
            proxy = number(w.get("rain_ifs_proxy_mm", p.get("ifs_proxy_mm")))
            gefs = number(w.get("rain_gefs_proxy_mm", p.get("gefs_proxy_mm")))
            reference = row_at((santa_weather or {}).get("horizons"), hours)
            ref_mean = number(reference.get("basin_mean_mm"))
            ref_max = number(reference.get("basin_max_mm"))
            headwater = {
                "mean_mm": ref_mean,
                "max_mm": ref_max,
                "status": "shared_santa_reference" if ref_mean is not None else "not_available",
                "source": "Santa Tereza IFS spatial recut; not an independent Muçum catchment",
                "independent_for_station": False,
            }
            rain = {
                "point_mm": point,
                "ifs_direct_mm": number(w.get("rain_ecmwf_direct_mm", p.get("ifs_direct_mm"))),
                "ifs_openmeteo_mm": direct_openmeteo,
                "ifs_proxy_mm": proxy,
                "gefs_proxy_mm": gefs,
                "headwater": headwater,
                "method": "ponto Muçum + referência espacial Santa Tereza; sem máscara independente",
            }
        coverage = integer(w.get("rain_hours_available"))
        risk = risk_for(pattern, probability, binary, hours, now)
        horizon_rows.append(
            {
                "hours": hours,
                "rain": rain,
                "soil": {
                    "model_m3m3": number(w.get("soil_moisture_model_mean_m3m3", p.get("soil_moisture_m3m3"))),
                    "status": (weather.get("soil_moisture") or {}).get("status", "not_available"),
                    "local_observation": False,
                },
                "risk": risk,
                "coverage_hours": coverage,
                "coverage_expected_hours": hours,
                "forecast_complete": coverage is None or coverage >= hours,
            }
        )
    quality_flags: list[str] = []
    if forecast_age is None or forecast_age > 36:
        quality_flags.append("forecast_stale_or_unknown")
    if current["state"] != "fresh":
        quality_flags.append("observation_stale_or_unknown")
    if any(not row["forecast_complete"] for row in horizon_rows):
        quality_flags.append("partial_horizon")
    if key == "mucum":
        quality_flags.extend(["point_forecast", "shared_headwater_reference", "no_local_soil_sensor"])
    else:
        quality_flags.extend(["representative_cells_not_hydrologic_mask", "no_local_soil_sensor"])
    return {
        "station_code": config["code"],
        "station_name": config["name"],
        "coordinates": config["coordinates"],
        "threshold_cm": config["threshold_cm"],
        "current": current,
        "short_forecasts": short_forecasts(live),
        "forecast": {
            "generated_at_utc": weather_generated,
            "age_hours": round(forecast_age, 2) if forecast_age is not None else None,
            "state": "stale" if forecast_age is None or forecast_age > 36 else "current_window",
            "provider": weather.get("forecast_provider") or weather.get("forecast_source"),
            "model": weather.get("forecast_model"),
            "run_time_utc": (weather.get("forecast") or {}).get("run_time_utc") if isinstance(weather.get("forecast"), dict) else None,
            "source_url": weather.get("forecast_source_url"),
        },
        "horizons": horizon_rows,
        "events": event_summary(pattern, binary, location=key),
        "quality": {
            "status": "DEGRADED" if quality_flags else "OK",
            "flags": quality_flags,
            "source_hashes": {name: sha256(ROOT / config[name]) for name in ("weather", "pattern", "probability", "binary", "live")},
        },
        "sources": {
            "weather": rel(weather_path),
            "pattern": rel(pattern_path),
            "probability": rel(probability_path),
            "binary": rel(binary_path),
            "live": rel(live_path),
        },
    }


def build_feed(now: datetime | None = None) -> dict[str, Any]:
    now = now or utc_now()
    santa_weather = load(ROOT / STATIONS["santa_tereza"]["weather"], {})
    station_data = {key: station_context(key, now, santa_weather=santa_weather) for key in STATIONS}
    return {
        "schema_version": 1,
        "feed_type": "basin_overflow_research_context",
        "generated_at_utc": iso(now),
        "research_only": True,
        "official_alert": False,
        "status": "research_screening_with_explicit_data_gates",
        "basin": {
            "name": "Taquari–Antas",
            "station_scope": ["Santa Tereza", "Muçum"],
            **geometry_summary(),
            "upstream_gauges": upstream_gauge_context(),
        },
        "stations": station_data,
        "signals": {
            "observed_level": "ANA/SGB or robot live level, with timestamp and age",
            "forecast_rain": "ECMWF IFS point or representative-cell recut, always labelled",
            "headwater_rain": "Santa Tereza spatial recut; Muçum currently uses a shared reference, not an independent catchment",
            "soil_moisture": "modelled proxy only; no local saturation sensor in the published feed",
            "propagation": "short forecasts are shown; basin travel-time field remains unvalidated per event",
            "probability": "experimental score/probability by source and age; never an official alert",
        },
        "automation": {
            "status": "configured_by_workflow",
            "workflow": ".github/workflows/research-basin.yml",
            "triggers": ["manual", "hourly schedule", "completion of weather/level workflows"],
            "steps": ["join current artifacts", "write compact feed", "run schema/QA", "publish only changed artifacts"],
        },
        "gates": [
            {"id": "hydrologic_mask", "status": "pending", "reason": "outlet, flow accumulation and headwater polygons need a validated regional DEM/network"},
            {"id": "mucum_independent_headwater", "status": "pending", "reason": "current spatial rain is a shared Santa Tereza reference, not an independent Muçum catchment"},
            {"id": "soil_observation", "status": "pending", "reason": "no local in-situ saturation series is published for either station"},
            {"id": "radar_qpe", "status": "pending", "reason": "CEMADEN radar/QPE feed requires a successful public download or credentials"},
            {"id": "travel_time", "status": "research_partial", "reason": "known model anchors are displayed, but event-level propagation still needs validation"},
            {"id": "probability_calibration", "status": "research_only", "reason": "few positive events, missing independent negatives, source mismatch and stale probability runs"},
        ],
        "limitations": [
            "A chuva acumulada não equivale sozinha a transbordamento: localização, nível inicial, solo e propagação importam.",
            "A classificação VAI/NÃO VAI é uma regra de pesquisa sobre a saída publicada; não é certeza nem alerta.",
            "Sem rótulo temporal causal e negativos independentes, não se publica probabilidade operacional calibrada.",
            "Os artefatos públicos podem ter idades diferentes; a idade e a fonte aparecem por estação e horizonte.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--now-utc", help="timestamp ISO para testes/reprodutibilidade")
    args = parser.parse_args()
    now = parse_time(args.now_utc) if args.now_utc else utc_now()
    if now is None:
        raise SystemExit("--now-utc inválido")
    payload = build_feed(now)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    partial.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial.replace(output)
    print(json.dumps({"output": rel(output), "generated_at_utc": payload["generated_at_utc"], "stations": sorted(payload["stations"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
