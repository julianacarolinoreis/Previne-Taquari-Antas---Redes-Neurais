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
SANTA_WEATHER = ROOT / "assets" / "data" / "research_weather_santa_tereza_latest.json"
PROBABILITY = ROOT / "assets" / "data" / "research_probability_mucum_latest.json"
BINARIES = {
    "mucum": ROOT / "assets" / "data" / "research_binary_decision_mucum_latest.json",
    "santa_tereza": ROOT / "assets" / "data" / "research_binary_decision_santa_tereza_latest.json",
}
VISUALS = {
    "mucum": ROOT / "assets" / "data" / "research_visual_patterns_mucum_latest.json",
    "santa_tereza": ROOT / "assets" / "data" / "research_visual_patterns_santa_tereza_latest.json",
}
PAGES = (ROOT / "pesquisa_status.html", ROOT / "pesquisa_status_mucum.html")
BASIN_PAGE = ROOT / "dashboard_bacia.html"
BASIN_RESEARCH = ROOT / "assets" / "data" / "research_basin_screening_latest.json"
SOURCE_REGISTRY = ROOT / "assets" / "data" / "research_source_registry.json"
BASIN_ASSETS = (
    ROOT / "assets" / "css" / "bacia_dashboard.css",
    ROOT / "assets" / "js" / "bacia_dashboard.js",
)
REQUIRED_HORIZONS = (24, 48, 72, 120, 168)
SANTA_WEATHER_HORIZONS = (24, 48, 72, 96, 120, 168)


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
    santa_weather = load_json(SANTA_WEATHER, errors) or {}
    probability = load_json(PROBABILITY, errors) or {}
    weather_rows = horizon_rows(weather.get("horizons"))
    santa_weather_rows = horizon_rows(santa_weather.get("horizons"))
    probability_rows = horizon_rows(probability.get("horizons"))
    weather_hours = [h for h, _ in weather_rows]
    santa_weather_hours = [h for h, _ in santa_weather_rows]
    probability_hours = [h for h, _ in probability_rows]
    if weather_hours != list(REQUIRED_HORIZONS):
        errors.append({"severity": "FAIL", "code": "weather_horizons", "detail": weather_hours})
    if santa_weather_hours != list(SANTA_WEATHER_HORIZONS):
        errors.append({"severity": "FAIL", "code": "santa_weather_horizons", "detail": santa_weather_hours})
    if probability_hours != list(REQUIRED_HORIZONS):
        errors.append({"severity": "FAIL", "code": "probability_horizons", "detail": probability_hours})
    for label, feed in (("weather", weather), ("weather_santa_tereza", santa_weather), ("probability", probability)):
        if feed and parse_time(feed.get("generated_at_utc")) is None:
            errors.append({"severity": "FAIL", "code": "timestamp_without_timezone", "feed": label})
    for location, rows_to_check in (("mucum", weather_rows), ("santa_tereza", santa_weather_rows)):
        for hours, item in rows_to_check:
            for key in ("rain_point_mm", "rain_ecmwf_direct_mm", "basin_mean_mm", "basin_max_mm"):
                if key in item and item[key] is not None and not isinstance(item[key], (int, float)):
                    errors.append({"severity": "FAIL", "code": "non_numeric_weather_value", "location": location, "horizon": hours, "field": key})
    coverage = {str(hours): item.get("rain_hours_available", hours) for hours, item in weather_rows}
    santa_coverage = {str(hours): item.get("rain_hours_available", hours) for hours, item in santa_weather_rows}
    if weather_rows and any(item.get("rain_hours_available", hours) != hours for hours, item in weather_rows):
        errors.append({"severity": "DEGRADED", "code": "partial_forecast_window", "coverage": coverage})
    if santa_weather_rows and any(item.get("rain_hours_available", hours) != hours for hours, item in santa_weather_rows):
        errors.append({"severity": "DEGRADED", "code": "santa_partial_forecast_window", "coverage": santa_coverage})
    aggregation = santa_weather.get("basin_aggregation") if isinstance(santa_weather.get("basin_aggregation"), dict) else {}
    if aggregation.get("status") != "upstream_monitoring_grid_proxy":
        errors.append({"severity": "FAIL", "code": "santa_spatial_proxy_status", "detail": aggregation.get("status")})
    if aggregation.get("hydrologic_mask") is not False or aggregation.get("area_weighted") is not False:
        errors.append({"severity": "FAIL", "code": "santa_hydrologic_overclaim"})
    if aggregation.get("deduplication_applied") is not True:
        errors.append({"severity": "FAIL", "code": "santa_grid_deduplication_missing"})
    now = datetime.now(timezone.utc)
    for location, feed in (("mucum", weather), ("santa_tereza", santa_weather)):
        generated = parse_time(feed.get("generated_at_utc"))
        if generated is None or (now - generated.astimezone(timezone.utc)).total_seconds() > 36 * 3600:
            errors.append({"severity": "DEGRADED", "code": "weather_feed_stale", "location": location, "generated_at_utc": feed.get("generated_at_utc")})
    if probability.get("calibration_status") in ("experimental_uncalibrated", "uncalibrated"):
        errors.append({"severity": "DEGRADED", "code": "score_uncalibrated", "detail": "exibido como score, nunca como chance real"})
    if probability.get("direct_mucum_point") is False:
        errors.append({"severity": "DEGRADED", "code": "probability_proxy_source", "detail": probability.get("forecast_source")})
    return {
        "weather": {"generated_at_utc": weather.get("generated_at_utc"), "sha256": sha256(WEATHER) if WEATHER.exists() else None, "horizons": weather_hours, "coverage": coverage},
        "weather_santa_tereza": {"generated_at_utc": santa_weather.get("generated_at_utc"), "sha256": sha256(SANTA_WEATHER) if SANTA_WEATHER.exists() else None, "horizons": santa_weather_hours, "coverage": santa_coverage, "spatial_proxy_status": aggregation.get("status"), "hydrologic_mask": aggregation.get("hydrologic_mask")},
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


def check_visual_patterns(errors: list[dict]) -> dict:
    """Check the compact, reader-facing feed used by the visual dashboard."""
    result: dict[str, dict] = {}
    for location, path in VISUALS.items():
        feed = load_json(path, errors) or {}
        rows = horizon_rows(feed.get("horizons"))
        hours = [h for h, _ in rows]
        if hours != list(REQUIRED_HORIZONS):
            errors.append({"severity": "FAIL", "code": "visual_horizons", "location": location, "detail": hours})
        events = feed.get("events")
        if not isinstance(events, list) or not events:
            errors.append({"severity": "FAIL", "code": "visual_events_missing", "location": location})
        if not isinstance(feed.get("models"), list) or not feed.get("models"):
            errors.append({"severity": "FAIL", "code": "visual_models_missing", "location": location})
        if not isinstance(feed.get("sources"), dict) or not feed.get("sources"):
            errors.append({"severity": "FAIL", "code": "visual_sources_missing", "location": location})
        if parse_time(feed.get("generated_at_utc")) is None:
            errors.append({"severity": "FAIL", "code": "visual_timestamp_invalid", "location": location})
        for hours_value, item in rows:
            for key, value in item.items():
                if value is not None and (key.endswith("_mm") or key.endswith("_percent") or key.endswith("_m3m3")) and not isinstance(value, (int, float)):
                    errors.append({"severity": "FAIL", "code": "visual_non_numeric_value", "location": location, "horizon": hours_value, "field": key})
        summary = feed.get("summary") or {}
        if not isinstance(summary.get("pattern_text"), str) or not summary.get("pattern_text").strip():
            errors.append({"severity": "FAIL", "code": "visual_pattern_text_missing", "location": location})
        result[location] = {
            "generated_at_utc": feed.get("generated_at_utc"),
            "sha256": sha256(path) if path.exists() else None,
            "horizons": hours,
            "events": len(events) if isinstance(events, list) else 0,
            "models": len(feed.get("models")) if isinstance(feed.get("models"), list) else 0,
            "sources": sorted(feed.get("sources", {}).keys()) if isinstance(feed.get("sources"), dict) else [],
        }
    return result


def check_pages(errors: list[dict]) -> dict:
    result = {}
    required_tokens = ("data-pv-dashboard", "pv-feed-chips", "pv-chart-scale", "pv-detail-table", 'role="tab"', "aria-selected", "resultado-binario", "research_binary_decision_", "data-pattern-dashboard", "research_visual_patterns_")
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
    visual_js = ROOT / "assets" / "js" / "research_patterns_dashboard.js"
    visual_text = visual_js.read_text(encoding="utf-8") if visual_js.exists() else ""
    for token, code in (("data-pattern-dashboard", "visual_dashboard_mount"), ("research_visual_patterns_", "visual_feed_contract"), ("pattern-models", "visual_model_comparison")):
        if token not in visual_text and code == "visual_dashboard_mount":
            errors.append({"severity": "FAIL", "code": code})
    if not visual_js.exists():
        errors.append({"severity": "FAIL", "code": "visual_dashboard_script_missing"})
    result["research_patterns_dashboard.js"] = {"sha256": sha256(visual_js) if visual_js.exists() else None}
    return result


def check_basin_page(errors: list[dict]) -> dict:
    """Check the single, reader-facing view that joins both stations.

    This is deliberately a static contract check.  The browser still loads
    the feeds at runtime, while this check prevents publishing a page whose
    controls or data labels silently disappeared.
    """
    result: dict[str, object] = {"file": BASIN_PAGE.name}
    if not BASIN_PAGE.exists():
        errors.append({"severity": "FAIL", "code": "missing_basin_page", "file": BASIN_PAGE.name})
        return result
    text = BASIN_PAGE.read_text(encoding="utf-8")
    parser = IdParser()
    parser.feed(text)
    duplicates = sorted({ident for ident in parser.ids if parser.ids.count(ident) > 1})
    if duplicates:
        errors.append({"severity": "FAIL", "code": "basin_duplicate_ids", "file": BASIN_PAGE.name, "detail": duplicates})
    required = (
        "data-bacia-dashboard",
        "assets/css/bacia_dashboard.css",
        "assets/js/bacia_dashboard.js",
        'data-station="basin"',
        'data-station="santa"',
        'data-station="mucum"',
        'data-horizon="24"',
        'data-horizon="72"',
        'data-horizon="168"',
        "probabilidade",
        "não é a mesma coisa que probabilidade de inundação",
        "research-context-grid",
        "research-context-gates",
        "research-source-registry",
        "research_source_registry.json",
        "research_basin_screening_latest.json",
        'id="refresh-feeds"',
    )
    missing = [token for token in required if token not in text]
    if missing:
        errors.append({"severity": "FAIL", "code": "basin_dashboard_contract_missing", "file": BASIN_PAGE.name, "detail": missing})
    result.update({"sha256": sha256(BASIN_PAGE), "ids": len(parser.ids), "duplicate_ids": duplicates, "required_tokens": len(required) - len(missing)})
    for asset in BASIN_ASSETS:
        if not asset.exists():
            errors.append({"severity": "FAIL", "code": "missing_basin_asset", "file": asset.relative_to(ROOT).as_posix()})
    js = ROOT / "assets" / "js" / "bacia_dashboard.js"
    js_text = js.read_text(encoding="utf-8") if js.exists() else ""
    for token, code in (("loadFeeds", "basin_feed_loader"), ("stationSnapshot", "basin_station_normalization"), ("renderProvenance", "basin_provenance"), ("renderResearchSources", "basin_source_registry"), ("source_registry", "basin_source_registry_feed"), ("safeHttpUrl", "basin_source_url_guard"), ("Não há probabilidade conjunta publicada", "basin_no_joint_probability"), ("riskUsable", "stale_risk_hidden"), ("refresh-feeds", "manual_refresh")):
        if token not in js_text:
            errors.append({"severity": "FAIL", "code": code})
    result["bacia_dashboard.js"] = {"sha256": sha256(js) if js.exists() else None}
    return result


def check_source_registry(errors: list[dict], feed: dict) -> dict:
    """Check that curated links are explicit without treating them as data."""
    registry = load_json(SOURCE_REGISTRY, errors) or {}
    embedded = feed.get("source_registry") if isinstance(feed, dict) else None
    if not isinstance(registry, dict):
        return {"sources": 0}
    if registry.get("scope") != "research_only":
        errors.append({"severity": "FAIL", "code": "source_registry_scope"})
    sources = registry.get("sources") if isinstance(registry.get("sources"), list) else []
    if len(sources) < 3:
        errors.append({"severity": "FAIL", "code": "source_registry_too_small", "detail": len(sources)})
    known_gates = {"hydrologic_mask", "radar_qpe", "travel_time", "soil_observation", "mucum_independent_headwater", "probability_calibration"}
    ids: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            errors.append({"severity": "FAIL", "code": "source_registry_item_not_object"})
            continue
        source_id = str(source.get("id") or "")
        ids.append(source_id)
        if not source_id or source_id in ids[:-1]:
            errors.append({"severity": "FAIL", "code": "source_registry_duplicate_id", "detail": source_id})
        if source.get("status") not in {"identified", "conditional", "integrated"}:
            errors.append({"severity": "FAIL", "code": "source_registry_status", "detail": source_id})
        if source.get("gate") not in known_gates:
            errors.append({"severity": "FAIL", "code": "source_registry_gate", "detail": source_id})
        if not isinstance(source.get("role"), str) or not source.get("role", "").strip():
            errors.append({"severity": "FAIL", "code": "source_registry_role", "detail": source_id})
        if not isinstance(source.get("next_step"), str) or not source.get("next_step", "").strip():
            errors.append({"severity": "FAIL", "code": "source_registry_next_step", "detail": source_id})
        if not isinstance(source.get("url"), str) or not re.match(r"^https://", source.get("url", ""), re.I):
            errors.append({"severity": "FAIL", "code": "source_registry_url", "detail": source_id})
    if not isinstance(embedded, dict) or not isinstance(embedded.get("sources"), list):
        errors.append({"severity": "FAIL", "code": "source_registry_not_embedded"})
    else:
        embedded_ids = [str(item.get("id") or "") for item in embedded["sources"] if isinstance(item, dict)]
        if embedded_ids != ids:
            errors.append({"severity": "FAIL", "code": "source_registry_embed_mismatch", "detail": {"file": ids, "feed": embedded_ids}})
        artifact = embedded.get("artifact") if isinstance(embedded.get("artifact"), dict) else {}
        if artifact.get("sha256") != sha256(SOURCE_REGISTRY):
            errors.append({"severity": "FAIL", "code": "source_registry_hash_mismatch"})
    return {"sha256": sha256(SOURCE_REGISTRY) if SOURCE_REGISTRY.exists() else None, "sources": ids, "last_reviewed_utc": registry.get("last_reviewed_utc")}


def check_basin_research(errors: list[dict]) -> dict:
    """Validate the compact join used by the basin research section."""
    feed = load_json(BASIN_RESEARCH, errors) or {}
    result: dict[str, object] = {"file": BASIN_RESEARCH.name}
    if not feed:
        return result
    source_summary = check_source_registry(errors, feed)
    if feed.get("research_only") is not True or feed.get("official_alert") is not False:
        errors.append({"severity": "FAIL", "code": "basin_research_scope"})
    if feed.get("feed_type") != "basin_overflow_research_context":
        errors.append({"severity": "FAIL", "code": "basin_research_feed_type"})
    basin = feed.get("basin") if isinstance(feed.get("basin"), dict) else {}
    boundary = basin.get("boundary") if isinstance(basin.get("boundary"), dict) else {}
    hydro = basin.get("hydrologic_delineation") if isinstance(basin.get("hydrologic_delineation"), dict) else {}
    if boundary.get("status") != "boundary_reference_only":
        errors.append({"severity": "FAIL", "code": "basin_boundary_status"})
    if hydro.get("status") != "not_validated":
        errors.append({"severity": "FAIL", "code": "basin_hydrology_overclaim"})
    stations = feed.get("stations") if isinstance(feed.get("stations"), dict) else {}
    required_locations = ("santa_tereza", "mucum")
    for location in required_locations:
        item = stations.get(location) if isinstance(stations, dict) else None
        if not isinstance(item, dict):
            errors.append({"severity": "FAIL", "code": "basin_research_station_missing", "location": location})
            continue
        rows = horizon_rows(item.get("horizons"))
        if [hours for hours, _ in rows] != list(REQUIRED_HORIZONS):
            errors.append({"severity": "FAIL", "code": "basin_research_horizons", "location": location, "detail": [hours for hours, _ in rows]})
        if not isinstance(item.get("quality"), dict):
            errors.append({"severity": "FAIL", "code": "basin_research_quality_missing", "location": location})
    mucum_rows = horizon_rows((stations.get("mucum") or {}).get("horizons")) if isinstance(stations.get("mucum"), dict) else []
    if mucum_rows:
        for hours, row in mucum_rows:
            headwater = ((row.get("rain") or {}).get("headwater") or {}) if isinstance(row, dict) else {}
            if headwater.get("independent_for_station") is not False:
                errors.append({"severity": "FAIL", "code": "mucum_headwater_independence_overclaim", "horizon": hours})
    gates = feed.get("gates")
    if not isinstance(gates, list) or not gates:
        errors.append({"severity": "FAIL", "code": "basin_research_gates_missing"})
    result.update({
        "sha256": sha256(BASIN_RESEARCH) if BASIN_RESEARCH.exists() else None,
        "generated_at_utc": feed.get("generated_at_utc"),
        "stations": sorted(stations) if isinstance(stations, dict) else [],
        "gate_count": len(gates) if isinstance(gates, list) else 0,
        "boundary_status": boundary.get("status"),
        "hydrologic_status": hydro.get("status"),
        "source_registry": source_summary,
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(REPORT))
    args = parser.parse_args()
    errors: list[dict] = []
    feeds = check_feeds(errors)
    binaries = check_binary_decisions(errors)
    visuals = check_visual_patterns(errors)
    pages = check_pages(errors)
    basin = check_basin_page(errors)
    basin_research = check_basin_research(errors)
    status = "FAIL" if any(e["severity"] == "FAIL" for e in errors) else "DEGRADED" if errors else "PASS"
    reference = max((x.get("generated_at_utc") or "" for x in feeds.values()), default=None)
    report = {"schema_version": 1, "status": status, "research_only": True, "checked_reference_utc": reference, "feeds": feeds, "binary_decisions": binaries, "visual_patterns": visuals, "pages": pages, "basin_dashboard": basin, "basin_research": basin_research, "issues": errors, "publication_decision": status}
    target = Path(args.report)
    if not target.is_absolute():
        target = ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"RESEARCH_DASHBOARD_QA={status} issues={len(errors)} report={target}")
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
