"""Build compact, source-backed data for the visual research dashboard.

The public pages should not download the large event/model archives directly.
This builder keeps the reader-facing feed small while preserving the source
paths, units, horizons and the distinction between observation, forecast and
research scores.
"""

from __future__ import annotations

import csv
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data"


def load(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def load_csv(path: str) -> list[dict[str, str]]:
    with (ROOT / path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def age_hours(timestamp: Any, reference: datetime | None = None) -> float | None:
    if not timestamp:
        return None
    try:
        raw = str(timestamp).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        ref = reference or datetime.now(timezone.utc)
        return max(0.0, (ref - parsed.astimezone(timezone.utc)).total_seconds() / 3600.0)
    except (TypeError, ValueError):
        return None


def number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def median(values: list[float | None]) -> float | None:
    clean = [float(x) for x in values if x is not None]
    return statistics.median(clean) if clean else None


def write(name: str, payload: dict[str, Any]) -> None:
    path = OUT / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_mucum() -> dict[str, Any]:
    evidence = load("assets/data/research_mucum_evidence_latest.json")
    probability = load("assets/data/research_probability_mucum_latest.json")
    weather = load("assets/data/research_weather_mucum_latest.json")
    binary = load("assets/data/research_binary_decision_mucum_latest.json")
    events = evidence.get("candidate_catalog", {}).get("events", [])
    rain_by_id = {row.get("event_id"): row for row in evidence.get("antecedent_conditions", [])}
    binary_by_h = {str(row.get("hours")): row for row in binary.get("decisions", [])}
    weather_by_h = {str(row.get("hours")): row for row in weather.get("horizons", [])}
    event_rows = []
    for event in events:
        rain = rain_by_id.get(event.get("id"), {})
        event_rows.append(
            {
                "id": event.get("id"),
                "date": event.get("peak"),
                "peak_cm": event.get("peak_cm"),
                "status": event.get("status"),
                "rain_24h_mm": rain.get("rain_24h_mm"),
                "rain_72h_mm": rain.get("rain_72h_mm"),
                "rain_168h_mm": rain.get("rain_168h_mm"),
                "rain_336h_mm": rain.get("rain_336h_mm"),
                "api_72h_mm": rain.get("api_72h_mm"),
                "soil_status": rain.get("soil_status"),
                "rain_source_kind": "research_antecedent",
                "context_source": "assets/data/research_mucum_evidence_latest.json",
            }
        )
    horizons = []
    for row in probability.get("horizons", []):
        key = str(row.get("hours"))
        current = weather_by_h.get(key, {})
        decision = binary_by_h.get(key, {})
        horizons.append(
            {
                "hours": row.get("hours"),
                "ifs_direct_mm": current.get("rain_ecmwf_direct_mm"),
                "ifs_proxy_mm": current.get("rain_ifs_proxy_mm"),
                "gefs_proxy_mm": current.get("rain_gefs_proxy_mm"),
                "soil_moisture_m3m3": current.get("soil_moisture_model_mean_m3m3"),
                "probability_percent": row.get("flood_probability_percent"),
                "decision": decision.get("decision"),
                "coverage_hours": current.get("rain_hours_available"),
            }
        )
    rain24 = [number(row.get("rain_24h_mm")) for row in event_rows]
    rain72 = [number(row.get("rain_72h_mm")) for row in event_rows]
    api72 = [number(row.get("api_72h_mm")) for row in event_rows]
    peaks = [number(row.get("peak_cm")) for row in event_rows]
    summary = {
        "event_count": len(event_rows),
        "peak_max_cm": max((x for x in peaks if x is not None), default=None),
        "peak_min_cm": min((x for x in peaks if x is not None), default=None),
        "rain_24h_median_mm": median(rain24),
        "rain_72h_median_mm": median(rain72),
        "api_72h_median_mm": median(api72),
        "pattern_text": "Os quatro eventos têm chuva antecedente mensurável; o volume e a memória da bacia variam bastante entre episódios.",
    }
    return {
        "schema_version": 1,
        "generated_at_utc": now(),
        "location": "mucum",
        "station_name": "Muçum",
        "threshold_cm": evidence.get("thresholds_cm", {}).get("flood"),
        "summary": summary,
        "events": event_rows,
        "horizons": horizons,
        "models": [
            {"name": "ECMWF IFS direto", "kind": "rain", "unit": "mm", "description": "chuva acumulada direta no ponto/rodada IFS"},
            {"name": "ECMWF IFS proxy", "kind": "rain", "unit": "mm", "description": "proxy espacial de chuva IFS usado na conferência"},
            {"name": "NOAA GEFS proxy", "kind": "rain", "unit": "mm", "description": "proxy da célula GEFS; alimenta o ajuste de pesquisa"},
            {"name": "Modelo logístico de pesquisa", "kind": "risk", "unit": "%", "description": "score binarizado pela regra de 50%; não calibrado operacionalmente"},
            {"name": "Solo modelado", "kind": "soil", "unit": "m³/m³", "description": "umidade modelada; não é sensor local"},
        ],
        "evaluation": binary.get("evaluation"),
        "sources": {
            "events": "assets/data/research_mucum_evidence_latest.json",
            "probability": "assets/data/research_probability_mucum_latest.json",
            "weather": "assets/data/research_weather_mucum_latest.json",
            "binary": "assets/data/research_binary_decision_mucum_latest.json",
        },
    }


def build_santa() -> dict[str, Any]:
    catalog = load("assets/data/eventos_analise.json")
    card = load("assets/data/research_card_santa_tereza_20260811.json")
    probability = load("assets/data/research_probability_santa_tereza_latest.json")
    weather = load("assets/data/research_weather_santa_tereza_latest.json")
    binary = load("assets/data/research_binary_decision_santa_tereza_latest.json")
    coupled_cases = load("assets/data/estudo_caso_territorio/casos_acoplados.json")
    coupled_by_id = {row.get("id"): row for row in coupled_cases.get("cases", []) if row.get("id")}
    # These catalog dates identify the same historical episodes represented in
    # the coupled case-study package.  Keep this mapping explicit so a later
    # event cannot be joined merely because its date is "close".
    coupled_case_by_catalog_date = {
        "2023-09-04": "st-e4-set2023",
        "2023-11-18": "st-e6-nov2023",
        "2024-04-29": "st-e9-mai2024",
    }
    antecedent_by_date: dict[str, dict[str, Any]] = {}
    for catalog_date, case_id in coupled_case_by_catalog_date.items():
        case = coupled_by_id.get(case_id, {})
        raw = case.get("raw_event_telemetry") or {}
        dynamics = case.get("dynamics") or {}
        peak = ((case.get("rna") or {}).get("peak") or {})
        local_rain = raw.get("status") != "local_rain_unavailable"
        observed_peak = number(peak.get("observed_cm"))
        rna_peak = number(peak.get("rna_cm"))
        antecedent_by_date[catalog_date] = {
            "rain_24h_mm": raw.get("rain_24h_before_raw_peak_mm") if local_rain else None,
            "rain_48h_mm": raw.get("rain_48h_before_raw_peak_mm") if local_rain else None,
            "rain_72h_mm": raw.get("rain_72h_before_raw_peak_mm") if local_rain else None,
            "event_rain_sum_mm": raw.get("event_rain_sum_mm") if local_rain else None,
            "rain_coverage_pct": (
                raw.get("rain_72h_coverage_pct")
                if local_rain
                else raw.get("proxy_rain_24h_coverage_pct")
            ),
            "rain_source_kind": "local_station" if local_rain else "downstream_proxy",
            "rain_station": raw.get("station") if local_rain else raw.get("proxy_station"),
            "proxy_rain_24h_mm": raw.get("proxy_rain_24h_before_replay_peak_mm") if not local_rain else None,
            "total_rise_cm": dynamics.get("total_rise_cm"),
            "max_hourly_rise_cm_h": dynamics.get("max_hourly_rise_cm_h"),
            "rna_peak_error_cm": (
                abs(rna_peak - observed_peak)
                if rna_peak is not None and observed_peak is not None
                else None
            ),
            "context_note": (
                raw.get("note")
                if local_rain
                else raw.get("proxy_note") or raw.get("note")
            ),
            "context_source": raw.get("source") or coupled_cases.get("generated_for"),
        }
    replay_metrics = load_csv("assets/data/santa_tereza_eventwise_replay_rna_2h/events_metrics.csv")
    replay_series = load_csv("assets/data/santa_tereza_eventwise_replay_rna_2h/series_hourly.csv")
    max_rise_by_event: dict[str, float] = {}
    previous_by_event: dict[str, tuple[datetime, float]] = {}
    for sample in replay_series:
        event_no = str(sample.get("evento") or "")
        observed = number(sample.get("nivel_observado_cm"))
        timestamp = sample.get("timestamp_local")
        if not event_no or observed is None or not timestamp:
            continue
        try:
            current_time = datetime.fromisoformat(timestamp)
        except ValueError:
            continue
        previous = previous_by_event.get(event_no)
        if previous and (current_time - previous[0]).total_seconds() == 3600:
            max_rise_by_event[event_no] = max(max_rise_by_event.get(event_no, 0.0), observed - previous[1])
        previous_by_event[event_no] = (current_time, observed)

    replay_by_peak_date: dict[str, dict[str, Any]] = {}
    for metric in replay_metrics:
        peak_at = str(metric.get("hora_pico_observado") or "")
        if len(peak_at) < 10:
            continue
        event_no = str(metric.get("evento") or "")
        replay_by_peak_date[peak_at[:10]] = {
            "replay_event": event_no or None,
            "replay_role": metric.get("conjunto"),
            "replay_peak_at": peak_at,
            "total_rise_cm": number(metric.get("subida_observada_cm")),
            "max_hourly_rise_cm_h": max_rise_by_event.get(event_no),
            "rna_peak_error_cm": number(metric.get("erro_pico_abs_cm")),
            "rna_mae_cm": number(metric.get("mae_cm")),
            "rna_max_error_cm": number(metric.get("erro_maximo_abs_cm")),
            "context_source": "assets/data/santa_tereza_eventwise_replay_rna_2h/events_metrics.csv",
        }

    reference_time = datetime.now(timezone.utc)
    probability_age = age_hours(probability.get("generated_at_utc"), reference_time)
    probability_fresh = probability_age is not None and probability_age <= 36.0
    weather_age = age_hours(weather.get("generated_at_utc"), reference_time)
    weather_fresh = weather_age is not None and weather_age <= 30.0
    threshold = number(card.get("threshold_cm")) or 1500.0
    event_rows = []
    for event in catalog.get("eventos", []):
        peak = number(event.get("pico_cm"))
        if peak is None or peak < threshold:
            continue
        row = {
            "id": f"SANTA-{event.get('pico_data')}",
            "date": event.get("pico_data"),
            "peak_cm": event.get("pico_cm"),
            "status": "pico acima da cota de pesquisa",
            "model_count": event.get("n_modelos"),
            "nse_test": event.get("nse_teste"),
            "nse_validation": event.get("nse_validacao"),
            "difficulty": event.get("dificuldade_nse_pers"),
        }
        event_date = str(event.get("pico_data"))
        row.update(antecedent_by_date.get(event_date, {}))
        replay_context = replay_by_peak_date.get(event_date, {})
        for key, value in replay_context.items():
            if row.get(key) is None:
                row[key] = value
        event_rows.append(row)
    probability_by_h = probability.get("horizons", {})
    weather_by_h = {str(row.get("hours")): row for row in weather.get("horizons", [])}
    binary_by_h = {str(row.get("hours")): row for row in binary.get("decisions", [])}
    rna_scores = (weather.get("rna") or {}).get("scores", {})
    horizons = []
    for row in binary.get("decisions", []):
        key = str(row.get("hours"))
        p = probability_by_h.get(key, {})
        w = weather_by_h.get(key, {})
        horizons.append(
            {
                "hours": row.get("hours"),
                "ifs_mean_mm": w.get("basin_mean_mm"),
                "ifs_max_mm": w.get("basin_max_mm"),
                "point_mm": w.get("rain_point_mm"),
                "rna_score_percent": None if rna_scores.get(key) is None else number(rna_scores.get(key)) * 100.0,
                "probability_percent": (
                    number(p.get("probability")) * 100.0
                    if probability_fresh and p.get("probability") is not None
                    else (row.get("probability_percent") if probability_fresh else None)
                ),
                "decision": row.get("decision") if probability_fresh else None,
                "screening_threshold_mm": w.get("screening_threshold_mm"),
            }
        )
    peaks = [number(row.get("peak_cm")) for row in event_rows]
    return {
        "schema_version": 1,
        "generated_at_utc": now(),
        "location": "santa_tereza",
        "station_name": "Santa Tereza",
        "threshold_cm": threshold,
        "summary": {
            "event_count": len(event_rows),
            "model_card_event_count": card.get("event_count"),
            "peak_max_cm": max((x for x in peaks if x is not None), default=None),
            "peak_min_cm": min((x for x in peaks if x is not None), default=None),
            "pattern_text": "Nov/2023 e mai/2024 já têm chuva local antecedente auditada; set/2023 usa somente um proxy jusante explicitamente marcado. Eventos sem chuva auditada mostram outras evidências disponíveis, sem preencher lacunas com valores inventados.",
        },
        "events": event_rows,
        "horizons": horizons,
        "models": [
            {"name": "ECMWF IFS", "kind": "rain", "unit": "mm", "description": "chuva média e máxima na bacia"},
            {"name": "RNA do feed IFS", "kind": "risk", "unit": "%", "description": "score MLP do feed meteorológico"},
            {"name": "Score GEFS experimental", "kind": "risk", "unit": "%", "description": "score experimental; ocultado quando a fonte tem mais de 36 h"},
            {"name": "Modelos de nível", "kind": "level", "unit": "NSE", "description": "desempenho histórico por evento"},
        ],
        "evaluation": binary.get("evaluation"),
        "source_quality": {
            "probability": {
                "state": "fresh" if probability_fresh else ("stale" if probability_age is not None else "unknown"),
                "generated_at_utc": probability.get("generated_at_utc"),
                "age_hours": probability_age,
                "max_age_hours": 36.0,
            },
            "weather": {
                "state": "fresh" if weather_fresh else ("stale" if weather_age is not None else "unknown"),
                "generated_at_utc": weather.get("generated_at_utc"),
                "age_hours": weather_age,
                "max_age_hours": 30.0,
            },
        },
        "sources": {
            "events": "assets/data/eventos_analise.json",
            "historical_context": "assets/data/estudo_caso_territorio/casos_acoplados.json",
            "model_card": "assets/data/research_card_santa_tereza_20260811.json",
            "probability": "assets/data/research_probability_santa_tereza_latest.json",
            "weather": "assets/data/research_weather_santa_tereza_latest.json",
            "binary": "assets/data/research_binary_decision_santa_tereza_latest.json",
        },
    }


def main() -> int:
    write("research_visual_patterns_mucum_latest.json", build_mucum())
    write("research_visual_patterns_santa_tereza_latest.json", build_santa())
    print("VISUAL_PATTERNS=OK locations=mucum,santa_tereza")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
