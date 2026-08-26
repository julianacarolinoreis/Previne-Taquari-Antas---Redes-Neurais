"""Build an explicit research-only VAO_NAO decision from current probability feeds.

This does not invent missing labels or promote the model to an official alert.  It
turns the existing probability output into a deterministic binary research answer
and carries the held-out-event detection summary alongside it so the dashboard can
show both the current answer and whether the model has worked retrospectively.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUTS = {
    "mucum": ROOT / "assets" / "data" / "research_probability_mucum_latest.json",
    "santa_tereza": ROOT / "assets" / "data" / "research_probability_santa_tereza_latest.json",
}
DEFAULT_OUTPUTS = {
    "mucum": ROOT / "assets" / "data" / "research_binary_decision_mucum_latest.json",
    "santa_tereza": ROOT / "assets" / "data" / "research_binary_decision_santa_tereza_latest.json",
}
AUX_VALIDATION = {
    "santa_tereza": ROOT / "assets" / "data" / "research_card_santa_tereza_20260811.json",
}

# The binary research rule is deliberately explicit: p is a fraction in [0, 1].
# A current horizon is labelled VAI only at p >= 0.50.  This is a research
# decision threshold, not an operational alert threshold.
DECISION_THRESHOLD = 0.50


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def age_hours(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600.0)


def as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def current_decisions(feed: dict[str, Any]) -> list[dict[str, Any]]:
    horizons = feed.get("horizons") or []
    if isinstance(horizons, dict):
        items = []
        for key, value in horizons.items():
            item = dict(value or {})
            item.setdefault("hours", int(key))
            items.append(item)
    else:
        items = [dict(x) for x in horizons if isinstance(x, dict)]
    decisions: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda x: int(x.get("hours", 0))):
        probability = as_float(item.get("flood_probability"))
        if probability is None:
            probability_percent = as_float(item.get("probability"))
            # The Santa Tereza export stores ``probability`` as a fraction,
            # while older exports may expose ``probability_percent``.  Do not
            # divide a fraction by 100 a second time.
            if probability_percent is not None:
                probability = probability_percent
            else:
                probability_percent = as_float(item.get("probability_percent"))
                probability = probability_percent / 100.0 if probability_percent is not None else None
        probability_percent = None if probability is None else probability * 100.0
        decision = None if probability is None else ("VAI" if probability >= DECISION_THRESHOLD else "NAO_VAI")
        decisions.append(
            {
                "hours": int(item.get("hours", 0)),
                "probability": probability,
                "probability_percent": probability_percent,
                "decision": decision,
                "decision_label": (
                    "INDICA transbordamento" if decision == "VAI" else
                    "NAO_INDICA transbordamento" if decision == "NAO_VAI" else
                    "UNKNOWN"
                ),
                "input_interpretation": item.get("score_interpretation") or item.get("interpretation"),
            }
        )
    return decisions


def evaluation(feed: dict[str, Any], location: str) -> dict[str, Any]:
    summary = ((feed.get("validation") or {}).get("event_detection_summary") or {})
    by_horizon: list[dict[str, Any]] = []
    sensitivities: list[float] = []
    false_positive_metrics = "indisponíveis: a base publicada não traz negativos independentes por evento"
    for key, item in sorted(summary.items(), key=lambda x: int(str(x[0]).rstrip("h"))):
        held_out = int(item.get("held_out_events", 0) or 0)
        detected = int(item.get("detected_at_score_0_5", 0) or 0)
        sensitivity = detected / held_out if held_out else None
        if sensitivity is not None:
            sensitivities.append(sensitivity)
        by_horizon.append(
            {
                "hours": int(str(key).rstrip("h")),
                "held_out_events": held_out,
                "detected_at_score_0_5": detected,
                "sensitivity": sensitivity,
                "sensitivity_percent": None if sensitivity is None else sensitivity * 100.0,
                "result": (
                    "SEM_EVIDENCIA" if sensitivity is None else
                    "FRACA" if sensitivity < 0.50 else
                    "PARCIAL" if sensitivity < 0.80 else
                    "FORTE"
                ),
            }
        )
    validation_source = "feed.validation.event_detection_summary"
    if not by_horizon and location in AUX_VALIDATION and AUX_VALIDATION[location].exists():
        # Santa's current probability export predates the binary artifact, but
        # its audited model card carries a separate LOEO recall table.  Keep
        # that threshold (25%) explicit instead of pretending it is the 50%
        # current-decision threshold.
        aux = read_json(AUX_VALIDATION[location])
        aux_rows = aux.get("horizons") or []
        event_count = int(aux.get("event_count", 0) or 0)
        for item in aux_rows:
            recall = as_float(item.get("recall_at_25_pct"))
            false_rate = as_float(item.get("false_control_rate_at_25_pct"))
            sensitivity = None if recall is None else recall / 100.0
            if sensitivity is not None:
                sensitivities.append(sensitivity)
            by_horizon.append(
                {
                    "hours": int(item.get("hours", 0)),
                    "held_out_events": event_count,
                    "detected_at_score_0_5": None,
                    "sensitivity": sensitivity,
                    "sensitivity_percent": recall,
                    "result": (
                        "SEM_EVIDENCIA" if sensitivity is None else
                        "FRACA" if sensitivity < 0.50 else
                        "PARCIAL" if sensitivity < 0.80 else
                        "FORTE"
                    ),
                    "evaluation_threshold": "score >= 25%",
                    "false_control_rate_percent": false_rate,
                }
            )
        validation_source = str(AUX_VALIDATION[location].relative_to(ROOT)).replace("\\", "/")
        rates = [x.get("false_control_rate_percent") for x in by_horizon if x.get("false_control_rate_percent") is not None]
        if rates:
            false_positive_metrics = "taxa de falso controle no model card (limiar de 25%): " + ", ".join(f"{x:.1f}%" for x in rates)
    max_sensitivity = max(sensitivities, default=None)
    if not by_horizon:
        verdict = "SEM_AVALIACAO"
    elif max_sensitivity is not None and max_sensitivity < 0.50:
        verdict = "NAO_FUNCIONA_DE_FORMA_CONFIAVEL"
    else:
        verdict = "SINAL_PARCIAL_REQUER_VALIDACAO"
    return {
        "metric": "sensibilidade de detecção de eventos positivos",
        "threshold_used": "score >= 0.5" if validation_source.startswith("feed.") else "score >= 25% (modelo card LOEO)",
        "by_horizon": by_horizon,
        "false_positive_metrics": false_positive_metrics,
        "model_verdict": verdict,
        "validation_source": validation_source,
    }


def build(name: str, source: Path, output: Path) -> dict[str, Any]:
    feed = read_json(source)
    source_age = age_hours(feed.get("generated_at_utc"))
    calibration_status = feed.get("calibration_status")
    if calibration_status is None and "calibrated_for_current_source" in feed:
        calibration_status = f"calibrated_for_current_source={str(bool(feed.get('calibrated_for_current_source'))).lower()}"
    try:
        source_name = str(source.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        source_name = str(source)
    payload = {
        "schema_version": 1,
        "generated_at_utc": iso_now(),
        "location": name,
        "research_only": True,
        "official_alert": False,
        "decision_rule": {
            "name": "binary_research_threshold",
            "probability_threshold_fraction": DECISION_THRESHOLD,
            "probability_threshold_percent": DECISION_THRESHOLD * 100.0,
            "vai_when": "probabilidade experimental >= 50%",
            "otherwise": "NAO_VAI",
        },
        "source": {
            "probability_file": source_name,
            "source_generated_at_utc": feed.get("generated_at_utc"),
            "source_age_hours_at_generation": source_age,
            "source_state": "STALE" if source_age is None or source_age > 36 else "CURRENT_WINDOW",
            "calibration_status": calibration_status,
            "forecast_source": feed.get("forecast_source"),
        },
        "decisions": current_decisions(feed),
        "evaluation": evaluation(feed, name),
        "interpretation": (
            "Este bloco responde a pergunta binária dentro da pesquisa. "
            "Ele não transforma o score em certeza e não substitui alerta oficial."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--location", choices=sorted(DEFAULT_INPUTS), action="append")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "assets" / "data")
    args = parser.parse_args()
    locations = args.location or list(DEFAULT_INPUTS)
    for location in locations:
        source = DEFAULT_INPUTS[location]
        output = args.output_dir / DEFAULT_OUTPUTS[location].name
        payload = build(location, source, output)
        print(
            f"BINARY_RESEARCH={location} "
            f"verdict={payload['evaluation']['model_verdict']} "
            f"horizons={len(payload['decisions'])} output={output}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
