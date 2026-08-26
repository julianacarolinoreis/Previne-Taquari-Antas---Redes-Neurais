"""Build compact, source-backed data for the visual research dashboard.

The public pages should not download the large event/model archives directly.
This builder keeps the reader-facing feed small while preserving the source
paths, units, horizons and the distinction between observation, forecast and
research scores.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data"


def load(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    threshold = number(card.get("threshold_cm")) or 1500.0
    event_rows = []
    for event in catalog.get("eventos", []):
        peak = number(event.get("pico_cm"))
        if peak is None or peak < threshold:
            continue
        event_rows.append(
            {
                "id": f"SANTA-{event.get('pico_data')}",
                "date": event.get("pico_data"),
                "peak_cm": event.get("pico_cm"),
                "status": "pico acima da cota de pesquisa",
                "model_count": event.get("n_modelos"),
                "nse_test": event.get("nse_teste"),
                "nse_validation": event.get("nse_validacao"),
                "difficulty": event.get("dificuldade_nse_pers"),
            }
        )
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
                "probability_percent": number(p.get("probability")) * 100.0 if p.get("probability") is not None else row.get("probability_percent"),
                "decision": row.get("decision"),
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
            "pattern_text": "A série pública já permite comparar os picos e o desempenho dos modelos; a chuva antecedente por evento ainda não está ligada a este painel.",
        },
        "events": event_rows,
        "horizons": horizons,
        "models": [
            {"name": "ECMWF IFS", "kind": "rain", "unit": "mm", "description": "chuva média e máxima na bacia"},
            {"name": "RNA do feed IFS", "kind": "risk", "unit": "%", "description": "score MLP do feed meteorológico"},
            {"name": "Probabilidade GEFS", "kind": "risk", "unit": "%", "description": "probabilidade experimental do modelo GEFS"},
            {"name": "Modelos de nível", "kind": "level", "unit": "NSE", "description": "desempenho histórico por evento"},
        ],
        "evaluation": binary.get("evaluation"),
        "sources": {
            "events": "assets/data/eventos_analise.json",
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
