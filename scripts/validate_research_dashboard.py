#!/usr/bin/env python3
"""Contract check for the public research dashboards.

The check is intentionally deterministic and network-free.  It verifies that
the dashboard can distinguish observation, direct forecast, spatial proxies
and the experimental score.  A partial/old source is reported as DEGRADED;
it is never converted into a reassuring ``no flood`` statement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "assets" / "data" / "research_dashboard_validation_latest.json"
WEATHER = ROOT / "assets" / "data" / "research_weather_mucum_latest.json"
PROBABILITY = ROOT / "assets" / "data" / "research_probability_mucum_latest.json"
BINARIES = {
    "mucum": ROOT / "assets" / "data" / "research_binary_decision_mucum_latest.json",
    "santa_tereza": ROOT / "assets" / "data" / "research_binary_decision_santa_tereza_latest.json",
}
PAGES = (ROOT / "pesquisa_status.html", ROOT / "pesquisa_status_mucum.html")
REQUIRED_HORIZONS = (24, 48, 72, 120, 168)


class IdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.attrs: dict[str, dict[str, str]] = {}

    def handle_starttag(self, tag: str, attrs):
        values = {str(k): str(v or "") for k, v in attrs}
        ident = values.get("id")
        if ident:
            self.ids.append(ident)
            self.attrs[ident] = values


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace(" ", "T")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path, errors: list[dict]) -> dict | None:
    if not path.exists():
        errors.append({"severity": "FAIL", "code": "missing_file", "file": path.name})
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - message is part of report
        errors.append({"severity": "FAIL", "code": "invalid_json", "file": path.name, "detail": str(exc)})
        return None
    if not isinstance(value, dict):
        errors.append({"severity": "FAIL", "code": "root_not_object", "file": path.name})
        return None
    return value


def horizon_rows(value: object) -> list[tuple[int, dict]]:
    if isinstance(value, list):
        entries = [(item.get("hours", item.get("horizon_hours")), item) for item in value if isinstance(item, dict)]
    elif isinstance(value, dict):
        entries = [(key, item) for key, item in value.items() if isinstance(item, dict)]
    else:
        return []
    rows = []
    for key, item in entries:
        try:
            rows.append((int(item.get("hours", item.get("horizon_hours", key))), item))
        except (TypeError, ValueError):
            continue
    return sorted(rows, key=lambda pair: pair[0])


def check_feeds(errors: list[dict]) -> dict:
    weather = load_json(WEATHER, errors) or {}
    probability = load_json(PROBABILITY, errors) or {}
    weather_rows = horizon_rows(weather.get("horizons"))
    probability_rows = horizon_rows(probability.get("horizons"))
    weather_hours = [h for h, _ in weather_rows]
    probability_hours = [h for h, _ in probability_rows]
    if weather_hours != list(REQUIRED_HORIZONS):
        errors.append({"severity": "FAIL", "code": "weather_horizons", "detail": weather_hours})
    if probability_hours != list(REQUIRED_HORIZONS):
        errors.append({"severity": "FAIL", "code": "probability_horizons", "detail": probability_hours})
    for label, feed in (("weather", weather), ("probability", probability)):
        if feed and parse_time(feed.get("generated_at_utc")) is None:
            errors.append({"severity": "FAIL", "code": "timestamp_without_timezone", "feed": label})
    for hours, item in weather_rows:
        for key in ("rain_point_mm", "rain_ecmwf_direct_mm"):
            if key in item and item[key] is not None and not isinstance(item[key], (int, float)):
                errors.append({"severity": "FAIL", "code": "non_numeric_weather_value", "horizon": hours, "field": key})
    coverage = {str(hours): item.get("rain_hours_available", hours) for hours, item in weather_rows}
    if weather_rows and any(item.get("rain_hours_available", hours) != hours for hours, item in weather_rows):
        errors.append({"severity": "DEGRADED", "code": "partial_forecast_window", "coverage": coverage})
    if probability.get("calibration_status") in ("experimental_uncalibrated", "uncalibrated"):
        errors.append({"severity": "DEGRADED", "code": "score_uncalibrated", "detail": "exibido como score, nunca como chance real"})
    if probability.get("direct_mucum_point") is False:
        errors.append({"severity": "DEGRADED", "code": "probability_proxy_source", "detail": probability.get("forecast_source")})
    return {
        "weather": {"generated_at_utc": weather.get("generated_at_utc"), "sha256": sha256(WEATHER) if WEATHER.exists() else None, "horizons": weather_hours, "coverage": coverage},
        "probability": {"generated_at_utc": probability.get("generated_at_utc"), "sha256": sha256(PROBABILITY) if PROBABILITY.exists() else None, "horizons": probability_hours, "source": probability.get("forecast_source"), "calibration_status": probability.get("calibration_status")},
    }


def check_binary_decisions(errors: list[dict]) -> dict:
    result: dict[str, dict] = {}
    for name, path in BINARIES.items():
        feed = load_json(path, errors) or {}
        rule = feed.get("decision_rule") or {}
        decisions = feed.get("decisions")
        evaluation = feed.get("evaluation") or {}
        hours = [int(item.get("hours")) for item in decisions if isinstance(item, dict) and item.get("hours") is not None] if isinstance(decisions, list) else []
        if hours != list(REQUIRED_HORIZONS):
            errors.append({"severity": "FAIL", "code": "binary_horizons", "location": name, "detail": hours})
        if rule.get("probability_threshold_percent") != 50.0:
            errors.append({"severity": "FAIL", "code": "binary_threshold", "location": name, "detail": rule})
        if feed.get("research_only") is not True or feed.get("official_alert") is not False:
            errors.append({"severity": "FAIL", "code": "binary_scope", "location": name})
        if not isinstance(evaluation.get("model_verdict"), str):
            errors.append({"severity": "FAIL", "code": "binary_evaluation_missing", "location": name})
        for item in decisions if isinstance(decisions, list) else []:
            if item.get("decision") not in ("VAI", "NAO_VAI", None):
                errors.append({"severity": "FAIL", "code": "binary_decision_value", "location": name, "detail": item})
        result[name] = {
            "generated_at_utc": feed.get("generated_at_utc"),
            "sha256": sha256(path) if path.exists() else None,
            "horizons": hours,
            "threshold_percent": rule.get("probability_threshold_percent"),
            "model_verdict": evaluation.get("model_verdict"),
            "source_state": (feed.get("source") or {}).get("source_state"),
        }
    return result


def check_pages(errors: list[dict]) -> dict:
    result = {}
    required_tokens = ("data-pv-dashboard", "pv-feed-chips", "pv-chart-scale", "pv-detail-table", 'role="tab"', "aria-selected", "resultado-binario", "research_binary_decision_")
    for page in PAGES:
        if not page.exists():
            errors.append({"severity": "FAIL", "code": "missing_page", "file": page.name})
            continue
        text = page.read_text(encoding="utf-8")
        parser = IdParser()
        parser.feed(text)
        duplicates = sorted({ident for ident in parser.ids if parser.ids.count(ident) > 1})
        if duplicates:
            errors.append({"severity": "FAIL", "code": "duplicate_ids", "file": page.name, "detail": duplicates})
        missing = [token for token in required_tokens if token not in text]
        if missing:
            errors.append({"severity": "FAIL", "code": "dashboard_contract_missing", "file": page.name, "detail": missing})
        result[page.name] = {"sha256": sha256(page), "ids": len(parser.ids), "duplicate_ids": duplicates}
    js = ROOT / "assets" / "js" / "pv_dashboard.js"
    js_text = js.read_text(encoding="utf-8") if js.exists() else ""
    for token, code in (("Array.isArray(hs)", "probability_array_normalization"), ("render();}});", "mode_updates_all_surfaces")):
        if token not in js_text:
            errors.append({"severity": "FAIL", "code": code})
    if "||(w?.horizons||[]).find(x=>x.hours===168)" in js_text:
        errors.append({"severity": "FAIL", "code": "probability_fallback_to_weather"})
    result["pv_dashboard.js"] = {"sha256": sha256(js) if js.exists() else None}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(REPORT))
    args = parser.parse_args()
    errors: list[dict] = []
    feeds = check_feeds(errors)
    binaries = check_binary_decisions(errors)
    pages = check_pages(errors)
    status = "FAIL" if any(e["severity"] == "FAIL" for e in errors) else "DEGRADED" if errors else "PASS"
    reference = max((x.get("generated_at_utc") or "" for x in feeds.values()), default=None)
    report = {"schema_version": 1, "status": status, "research_only": True, "checked_reference_utc": reference, "feeds": feeds, "binary_decisions": binaries, "pages": pages, "issues": errors, "publication_decision": status}
    target = Path(args.report)
    if not target.is_absolute():
        target = ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"RESEARCH_DASHBOARD_QA={status} issues={len(errors)} report={target}")
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
