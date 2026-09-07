"""Build the unified historical replay and spatial research dashboard.

The page deliberately keeps hydrologic replay and spatial scenarios side by
side without silently converting a river level into a flood map.  All values
come from the audited packages already committed to the repository.  The map
uses the published 10 m terrain PNG as a visual background and overlays the
actual contour, 200 m statistical grid and response inventory points.
"""

from __future__ import annotations

import csv
import json
import math
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MUCUM = ROOT / "assets" / "data" / "mucum_eventwise_replay_calibrated"
SANTA = ROOT / "assets" / "data" / "santa_tereza_eventwise_replay_rna_2h"
SPATIAL = ROOT / "assets" / "data" / "research_event_replay_latest.json"
BASE = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas"


def num(value: object | None) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def compact_geometry(geometry: dict[str, object]) -> dict[str, object]:
    """Keep only geometry coordinates/type; source properties are carried separately."""
    return {"type": geometry["type"], "coordinates": geometry["coordinates"]}


def selected_contours(path: Path, levels: set[float]) -> list[dict[str, object]]:
    source = json.loads(path.read_text(encoding="utf-8"))
    result = []
    for feature in source["features"]:
        level = float(feature["properties"]["nivel_m"])
        if level.is_integer() and level in levels:
            result.append(
                {
                    "level": level,
                    "area_ha": num(feature["properties"].get("area_ha")),
                    "geometry": compact_geometry(feature["geometry"]),
                }
            )
    return result


def compact_grid(path: Path) -> list[dict[str, object]]:
    source = json.loads(path.read_text(encoding="utf-8"))
    result = []
    for feature in source["features"]:
        props = feature.get("properties", {})
        result.append(
            {
                "id": props.get("id_grade"),
                "pop": num(props.get("pop")),
                "dom": num(props.get("dom")),
                "pop_completude": props.get("pop_completude"),
                "geometry": compact_geometry(feature["geometry"]),
            }
        )
    return result


def geometry_intersects_bounds(geometry: dict[str, object], bounds: dict[str, float]) -> bool:
    """Return whether a geometry bbox intersects the terrain image extent."""
    pairs: list[tuple[float, float]] = []
    stack = [geometry["coordinates"]]
    while stack:
        item = stack.pop()
        if (
            isinstance(item, list)
            and len(item) >= 2
            and isinstance(item[0], (int, float))
            and isinstance(item[1], (int, float))
        ):
            pairs.append((float(item[0]), float(item[1])))
        elif isinstance(item, list):
            stack.extend(item)
    if not pairs:
        return False
    west, east = min(x for x, _ in pairs), max(x for x, _ in pairs)
    south, north = min(y for _, y in pairs), max(y for _, y in pairs)
    return not (
        east < bounds["west"]
        or west > bounds["east"]
        or north < bounds["south"]
        or south > bounds["north"]
    )


def service_points(city: str) -> list[dict[str, object]]:
    services = (
        ("abrigos.geojson", "Abrigo"),
        ("bombeiros.geojson", "Bombeiros"),
        ("ubs.geojson", "Saúde"),
        ("hospitais.geojson", "Hospital"),
        ("escolas.geojson", "Escola"),
    )
    result = []
    for filename, kind in services:
        source = ROOT / "assets" / "data" / "servicos" / filename
        data = json.loads(source.read_text(encoding="utf-8"))
        for feature in data["features"]:
            props = feature.get("properties", {})
            if props.get("municipio") != city:
                continue
            coordinates = feature["geometry"]["coordinates"]
            result.append(
                {
                    "kind": kind,
                    "name": props.get("nome") or props.get("name") or kind,
                    "lon": num(coordinates[0]),
                    "lat": num(coordinates[1]),
                    "source": f"assets/data/servicos/{filename}",
                }
            )
    return result


def mucum_events() -> list[dict[str, object]]:
    manifest = json.loads((MUCUM / "eventwise_manifest.json").read_text(encoding="utf-8"))
    result = []
    for item in manifest["events"]:
        event_id = item["id"]
        if event_id == "E22":
            metrics_path = MUCUM / "diagnostics" / "E22_partial" / "focused_metrics_20260903.csv"
            series_path = MUCUM / "diagnostics" / "E22_partial" / "focused_series_20260903.csv"
            metrics_source = "assets/data/mucum_eventwise_replay_calibrated/diagnostics/E22_partial/focused_metrics_20260903.csv"
            series_source = "assets/data/mucum_eventwise_replay_calibrated/diagnostics/E22_partial/focused_series_20260903.csv"
        elif item["status"] == "not_promoted":
            metrics_path = MUCUM / item["package_path"] / "multi_event_metrics.csv"
            series_path = MUCUM / item["package_path"] / "multi_event_series.csv"
            metrics_source = f"assets/data/mucum_eventwise_replay_calibrated/{item['package_path']}/multi_event_metrics.csv"
            series_source = f"assets/data/mucum_eventwise_replay_calibrated/{item['package_path']}/multi_event_series.csv"
        else:
            metrics_path = MUCUM / item["package_path"] / "metrics.csv"
            series_path = MUCUM / item["package_path"] / "series.csv"
            metrics_source = f"assets/data/mucum_eventwise_replay_calibrated/{item['package_path']}/metrics.csv"
            series_source = f"assets/data/mucum_eventwise_replay_calibrated/{item['package_path']}/series.csv"

        metrics = read_csv(metrics_path)[0]
        series = []
        for row in read_csv(series_path):
            if "time_value" in row:
                # HEC-HMS time values are Excel-style minutes from 1899-12-31.
                from datetime import datetime, timedelta

                timestamp = datetime(1899, 12, 31) + timedelta(minutes=float(row["time_value"]))
                timestamp_value = timestamp.strftime("%Y-%m-%dT%H:%M:00")
                observed = num(row.get("observed_m3s"))
                simulated = num(row.get("simulated_m3s"))
            else:
                timestamp_value = row["timestamp_local"].replace(" ", "T")
                observed = num(row.get("observed_m3s"))
                simulated = num(row.get("simulated_m3s"))
            series.append([timestamp_value, observed, simulated])

        status = "ajuste por evento" if item["status"] in {"calibrated_replay", "calibrated_replay_timing_priority"} else "diagnóstico"
        result.append(
            {
                "key": f"mucum-{event_id}",
                "municipality": "Muçum",
                "city_key": "mucum",
                "id": event_id,
                "period": item["period"],
                "model": "HEC-HMS 4.13",
                "variable": "vazão",
                "unit": "m³/s",
                "status": status,
                "status_detail": item["status"],
                "reason": item.get("reason", "Replay histórico auditado."),
                "selection_note": item.get("selection_note", ""),
                "metrics": {
                    "pairs": num(metrics.get("pairs")),
                    "mae": num(metrics.get("mae_m3s")),
                    "rmse": num(metrics.get("rmse_m3s")),
                    "nse": num(metrics.get("nse")),
                    "observed_peak": num(metrics.get("observed_peak_m3s")),
                    "model_peak": num(metrics.get("simulated_peak_m3s")),
                    "peak_error": num(metrics.get("peak_relative_error")),
                    "lag": num(metrics.get("peak_lag_hours")),
                },
                "series": series,
                "metrics_source": metrics_source,
                "series_source": series_source,
            }
        )
    return result


def santa_events() -> list[dict[str, object]]:
    rows = read_csv(SANTA / "events_metrics.csv")
    series_rows = read_csv(SANTA / "series_hourly.csv")
    by_event: dict[str, list[list[object]]] = {}
    for row in series_rows:
        key = str(row["evento"])
        observed = num(row.get("nivel_observado_cm"))
        predicted = num(row.get("nivel_rna_cm"))
        by_event.setdefault(key, []).append(
            [row["timestamp_local"].replace(" ", "T"), observed, predicted]
        )
    result = []
    for row in rows:
        event_id = str(row["evento"])
        role = row["papel_avaliacao"]
        peak_error_pct = num(row.get("erro_pico_relativo_pct"))
        status = "teste independente" if role == "teste_independente" else role.replace("_", " ")
        result.append(
            {
                "key": f"santa-{event_id}",
                "municipality": "Santa Tereza",
                "city_key": "santa_tereza",
                "id": f"E{event_id}",
                "period": f"{row['inicio']} → {row['fim']} BRT",
                "model": "RNA 2h",
                "variable": "nível",
                "unit": "cm",
                "status": status,
                "status_detail": role,
                "reason": "Replay de nível; não é calibração HEC-HMS de vazão.",
                "metrics": {
                    "pairs": num(row.get("n")),
                    "mae": num(row.get("mae_cm")),
                    "rmse": None,
                    "nse": None,
                    "observed_peak": num(row.get("pico_observado_cm")),
                    "model_peak": num(row.get("pico_rna_cm")),
                    "peak_error": peak_error_pct / 100 if peak_error_pct is not None else None,
                    "lag": num(row.get("atraso_pico_horas")),
                },
                "series": by_event.get(event_id, []),
                "metrics_source": "assets/data/santa_tereza_eventwise_replay_rna_2h/events_metrics.csv",
                "series_source": "assets/data/santa_tereza_eventwise_replay_rna_2h/series_hourly.csv",
            }
        )
    return result


def spatial_data() -> dict[str, object]:
    manifest = json.loads(SPATIAL.read_text(encoding="utf-8"))
    mucum = manifest["spatial_scenarios"]["mucum"]
    santa = manifest["spatial_scenarios"]["santa_tereza"]
    mucum_bounds = json.loads(
        (ROOT / "assets/data/mucum_inundacao/mdt/altitude_terreno_10m.json").read_text(encoding="utf-8")
    )["bounds"]
    santa_bounds = json.loads(
        (ROOT / "assets/data/santa_tereza_inundacao/mdt/altitude_terreno_10m_refinado.json").read_text(encoding="utf-8")
    )["bounds"]
    mucum_grid_all = compact_grid(ROOT / "assets/data/vulnerabilidade/grade/4312609.geojson")
    santa_grid_all = compact_grid(ROOT / "assets/data/vulnerabilidade/grade/4317251.geojson")
    mucum_points_all = service_points("Muçum")
    santa_points_all = service_points("Santa Tereza")
    mucum_grid = [item for item in mucum_grid_all if geometry_intersects_bounds(item["geometry"], mucum_bounds)]
    santa_grid = [item for item in santa_grid_all if geometry_intersects_bounds(item["geometry"], santa_bounds)]
    mucum_points = [
        item
        for item in mucum_points_all
        if mucum_bounds["west"] <= item["lon"] <= mucum_bounds["east"]
        and mucum_bounds["south"] <= item["lat"] <= mucum_bounds["north"]
    ]
    santa_points = [
        item
        for item in santa_points_all
        if santa_bounds["west"] <= item["lon"] <= santa_bounds["east"]
        and santa_bounds["south"] <= item["lat"] <= santa_bounds["north"]
    ]
    return {
        "mucum": {
            "label": "Muçum",
            "background": "../assets/data/mucum_inundacao/mdt/altitude_terreno_10m.png",
            "background_label": "MDT visual 10 m · mosaico de terreno",
            "bounds": mucum_bounds,
            "crs": "EPSG:4326",
            "level_min": 0,
            "level_max": 25,
            "contours": selected_contours(ROOT / "assets/data/mucum_inundacao/contornos_mancha.json", set(range(0, 26))),
            "grid": mucum_grid,
            "grid_total": len(mucum_grid_all),
            "points": mucum_points,
            "points_total": len(mucum_points_all),
            "stage_status": mucum["stage_conversion_status"],
            "published": {str(int(s["level_m"])): s for s in mucum["scenarios"]},
            "grid_source": mucum["grid_source"],
            "contour_source": mucum["contour_source"],
        },
        "santa_tereza": {
            "label": "Santa Tereza",
            "background": "../assets/data/santa_tereza_inundacao/mdt/altitude_terreno_10m_refinado.png",
            "background_label": "MDT visual refinado 10 m · corredor do talvegue",
            "bounds": santa_bounds,
            "crs": "EPSG:4326",
            "level_min": 0,
            "level_max": 15,
            "contours": selected_contours(ROOT / "assets/data/santa_tereza_inundacao/contornos_mancha.json", set(range(0, 16))),
            "grid": santa_grid,
            "grid_total": len(santa_grid_all),
            "points": santa_points,
            "points_total": len(santa_points_all),
            "stage_status": santa["stage_conversion_status"],
            "higher_than_published_status": santa["higher_than_published_status"],
            "published": {str(int(s["level_m"])): s for s in santa["scenarios"]},
            "grid_source": santa["grid_source"],
            "contour_source": santa["contour_source"],
        },
    }


def calibration_snapshot() -> dict[str, object]:
    status = json.loads((BASE / "network_calibration_status_latest.json").read_text(encoding="utf-8"))
    gate = status.get("calibration_input_gate", {})
    eligible = gate.get("eligible_sets", {})
    two_station = status.get("two_station_network_test", {})
    best = two_station.get("best_by_research_score") or {}
    target_rain = eligible.get("target_rain_sensitivity", {})
    return {
        "generated_at_utc": status.get("generated_at_utc"),
        "overall_status": status.get("overall_status"),
        "incremental_area_events": eligible.get("three_incremental_areas_complete_events", []),
        "model_scope": status.get("network", {}).get("scope"),
        "model_representation": status.get("network", {}).get("representation"),
        "network_extent": status.get("network", {}).get("source_network_extent", {}),
        "target_rain_events": eligible.get("target_rain_sensitivity_complete_events", []),
        "target_rain_status": target_rain.get("status"),
        "target_rain_reason": (
            "A chuva do posto ANA 86510000 é tratada como hipótese representativa; "
            "não é uma superfície espacial de precipitação validada para toda a bacia."
        ),
        "two_station_events": two_station.get("events", []),
        "two_station_best": {
            "mean_nse": best.get("mean_nse"),
            "mean_abs_peak_lag_hours": best.get("mean_abs_peak_lag_hours"),
            "mean_peak_relative_error": best.get("mean_peak_relative_error"),
            "research_score": best.get("research_score"),
        },
        "links": {
            "status": "../assets/data/hec_hms_integrated_taquari_antas/network_calibration_status_latest.json",
            "input_gate": "../assets/data/hec_hms_audit/calibration_input_gate_latest.json",
            "two_station": "../assets/data/hec_hms_integrated_taquari_antas/network_two_station_search/two_station_search_report.json",
        },
    }


HTML = r'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,">
<title>PREVINE · replay histórico e território</title>
<style>
:root{--ink:#12313b;--muted:#607681;--line:#d6e6e8;--paper:#fff;--bg:#eff8f7;--blue:#0879c9;--orange:#ed7a2a;--teal:#087d77;--pink:#df3f88;--gold:#b57216;--shadow:0 18px 44px rgba(15,57,70,.11)}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 90% 0,#fff0dc 0,transparent 30%),linear-gradient(145deg,#edf8f7,#f8fbff 62%,#fffaf2);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Arial,sans-serif}main{max-width:1440px;margin:auto;padding:22px 18px 48px}.shell{background:var(--paper);border:1px solid var(--line);border-radius:26px;box-shadow:var(--shadow);padding:24px}.eyebrow{color:var(--teal);font-size:11px;font-weight:950;letter-spacing:.13em;text-transform:uppercase}h1{font-size:clamp(28px,4vw,48px);line-height:1.01;letter-spacing:-.045em;margin:7px 0 11px}h2{font-size:19px;margin:0 0 12px}h3{font-size:15px;margin:0 0 6px}.muted{color:var(--muted)}.notice{margin:16px 0;padding:13px 15px;border-left:5px solid var(--gold);background:#fff7e7;color:#70480d;border-radius:11px}.summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:18px 0}.summary-card{border:1px solid var(--line);border-radius:15px;padding:13px 14px;background:linear-gradient(145deg,#fff,#f5fbfb)}.summary-card .label{text-transform:uppercase;font-size:10px;font-weight:950;color:var(--muted);letter-spacing:.05em}.summary-card .value{font-size:28px;font-weight:950;color:var(--blue);margin-top:3px}.summary-card .detail{font-size:12px;color:var(--muted)}.toolbar{display:flex;gap:12px;align-items:end;flex-wrap:wrap;padding:15px;border:1px solid var(--line);border-radius:16px;background:#f7fcfc}.field{display:flex;flex-direction:column;gap:6px;min-width:220px}.field label,.check-label{font-size:12px;font-weight:900}.field select,.field input[type=range]{width:100%}.field select{border:1px solid #a8cbd0;border-radius:10px;background:#fff;padding:10px 11px;color:var(--ink);font-weight:850;font-size:15px}.checks{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding-bottom:9px}.check-label{display:flex;gap:7px;align-items:center;color:var(--ink);white-space:nowrap}input[type=checkbox]{accent-color:var(--blue);width:17px;height:17px}.button{border:1px solid #a8cbd0;border-radius:10px;padding:10px 13px;background:#fff;color:var(--blue);font-weight:900;cursor:pointer}.button:hover,.button:focus-visible{background:#edf7ff;outline:3px solid #bfe2f5}.level-box{min-width:220px}.level-readout{display:flex;justify-content:space-between;gap:10px;align-items:center;font-weight:900}.level-readout output{color:var(--pink);font-size:19px}.level-box input{accent-color:var(--pink)}.layout{display:grid;grid-template-columns:minmax(360px,.9fr) minmax(560px,1.45fr);gap:16px;margin-top:16px}.panel{border:1px solid var(--line);border-radius:19px;background:#fff;padding:16px}.event-head{display:flex;justify-content:space-between;gap:12px;align-items:start;flex-wrap:wrap}.event-head strong{font-size:22px}.pill{display:inline-flex;align-items:center;border-radius:999px;padding:5px 10px;background:#e8f5f3;color:var(--teal);font-size:12px;font-weight:950}.pill.warn{background:#fff1e8;color:#a74e19}.pill.test{background:#eaf1ff;color:#245b9b}.kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:14px 0}.kpi{border:1px solid var(--line);border-radius:13px;padding:11px 10px;min-width:0;background:#fbfefe}.kpi .label{text-transform:uppercase;font-size:10px;color:var(--muted);font-weight:950}.kpi .value{font-size:clamp(19px,2.2vw,27px);font-weight:950;margin-top:3px;white-space:nowrap}.kpi .unit{font-size:11px;color:var(--muted)}.chart-panel{margin-top:13px;border:1px solid var(--line);border-radius:17px;padding:13px 10px 9px;background:#fff}.chart-head{display:flex;justify-content:space-between;gap:10px;align-items:start;flex-wrap:wrap}.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;font-weight:850;color:var(--muted)}.legend span{display:inline-flex;align-items:center;gap:6px}.dot{width:21px;height:4px;border-radius:5px;display:inline-block}.dot.blue{background:var(--blue)}.dot.orange{background:var(--orange)}.chart-wrap{position:relative;height:350px;margin-top:4px}.chart-wrap canvas{display:block;width:100%;height:100%;touch-action:none;cursor:crosshair}.tip{position:absolute;display:none;z-index:2;pointer-events:none;min-width:190px;background:#12343e;color:#fff;border-radius:10px;padding:9px 11px;box-shadow:0 10px 22px #12343e35;font-size:12px}.tip strong{display:block;color:#fff4b0;margin-bottom:3px}.chart-foot{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;color:var(--muted);font-size:11px}.reading{margin-top:13px;border:1px solid #d6ece5;border-left:4px solid var(--teal);border-radius:11px;background:#f1faf7;padding:11px 12px;color:#35625f;font-size:13px}.source-links{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;font-size:12px}.source-links a,.table-link{color:var(--blue);font-weight:900}.map-panel{padding:12px}.map-top{display:flex;justify-content:space-between;gap:12px;align-items:start;flex-wrap:wrap;padding:4px 3px 11px}.map-top strong{font-size:20px}.map-top .small{max-width:680px}.map-viewport{position:relative;overflow:hidden;min-height:590px;border:1px solid #b8d0d1;border-radius:15px;background:#b5d1ce;touch-action:none;isolation:isolate}.map-content{position:absolute;inset:0;transform-origin:center;will-change:transform}.map-bg{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;filter:saturate(.8) contrast(1.04);opacity:.92}.map-bg::after{content:""}.map-svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}.map-svg .grid-cell{fill:#d9f2ff44;stroke:#e9ffffcc;stroke-width:1;vector-effect:non-scaling-stroke;cursor:pointer}.map-svg .grid-cell:hover,.map-svg .grid-cell.selected{fill:#ffed9c99;stroke:#f5a623;stroke-width:3}.map-svg .flood{fill:#e7478790;stroke:#ffef88;stroke-width:2.2;vector-effect:non-scaling-stroke}.map-svg .service{stroke:#fff;stroke-width:2;vector-effect:non-scaling-stroke}.map-svg .service.shelter{fill:#0b9c8b}.map-svg .service.fire{fill:#ec6b37}.map-svg .service.health{fill:#2874d6}.map-svg .service.school{fill:#7356bb}.map-svg .service-label{font-size:12px;font-weight:900;paint-order:stroke;stroke:#fff;stroke-width:4px;stroke-linejoin:round;fill:#173945}.map-badge{position:absolute;top:12px;left:12px;max-width:min(420px,calc(100% - 24px));padding:10px 12px;border-radius:12px;background:#12343ee8;color:#fff;font-size:12px;box-shadow:0 8px 18px #12343e44;z-index:3}.map-badge strong{display:block;color:#fff4ae;margin-bottom:3px;font-size:14px}.map-controls{position:absolute;right:12px;top:12px;display:flex;gap:5px;z-index:4}.map-controls .button{padding:8px 11px;background:#fffffff0}.north{position:absolute;right:18px;bottom:18px;color:#163d47;font-weight:950;background:#ffffffc8;border-radius:8px;padding:5px 8px;z-index:3}.map-legend{display:flex;gap:12px;flex-wrap:wrap;margin:10px 3px 0;color:var(--muted);font-size:12px;font-weight:800}.map-legend span{display:inline-flex;gap:6px;align-items:center}.legend-swatch{display:inline-block;width:18px;height:10px;border-radius:3px;border:1px solid #fff}.swatch-flood{background:#e7478790;border-color:#ffef88}.swatch-grid{background:#d9f2ff88;border-color:#e9ffff}.swatch-shelter{background:#0b9c8b}.swatch-fire{background:#ec6b37}.swatch-health{background:#2874d6}.swatch-school{background:#7356bb}.cell-info{margin-top:11px;border:1px solid var(--line);border-radius:13px;padding:12px;background:#fbfefe;min-height:87px}.cell-info strong{color:var(--blue)}.cell-info p{margin:3px 0 0;color:var(--muted);font-size:12px}.spatial-note{margin-top:11px;color:var(--muted);font-size:12px}.all-events{margin-top:16px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:15px}.events-table{border-collapse:collapse;width:100%;min-width:760px;font-size:13px}.events-table th,.events-table td{padding:10px 11px;border-bottom:1px solid #e7eff0;text-align:left;vertical-align:middle}.events-table th{font-size:10px;text-transform:uppercase;color:var(--muted);letter-spacing:.05em;background:#f7fcfc;position:sticky;top:0}.events-table tr:last-child td{border-bottom:0}.events-table tr.selected{background:#fff8e9}.events-table tr{cursor:pointer}.events-table tr:hover{background:#f2f9ff}.event-button{border:0;background:none;padding:0;color:var(--blue);font-weight:950;cursor:pointer;font:inherit}.tiny-pill{display:inline-flex;border-radius:999px;padding:3px 7px;font-size:11px;font-weight:900;background:#e8f5f3;color:#087d77;white-space:nowrap}.tiny-pill.warn{background:#fff1e8;color:#a74e19}.tiny-pill.test{background:#eaf1ff;color:#245b9b}.foot-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}.foot-grid .panel p{margin:4px 0;color:var(--muted);font-size:13px}.foot-grid a{color:var(--blue);font-weight:900}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}@media(max-width:1100px){.layout{grid-template-columns:1fr}.map-viewport{min-height:520px}.summary{grid-template-columns:repeat(4,1fr)}}@media(max-width:700px){main{padding:10px 8px 28px}.shell{padding:15px;border-radius:19px}.summary{grid-template-columns:repeat(2,1fr)}.summary-card .value{font-size:24px}.toolbar{align-items:stretch}.field,.level-box{min-width:100%}.kpis{grid-template-columns:repeat(2,1fr)}.chart-wrap{height:290px}.map-viewport{min-height:410px}.map-svg .service-label{font-size:15px}.foot-grid{grid-template-columns:1fr}.map-top strong{font-size:18px}.map-badge{font-size:11px}.map-controls{top:auto;bottom:12px;right:12px}}
</style><style>
.map-tools{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:0 3px 10px;padding:9px 10px;border:1px solid var(--line);border-radius:12px;background:#f7fcfc;color:var(--muted);font-size:12px}.map-tools-title{font-weight:950;color:var(--ink);margin-right:2px}.map-tools label{display:inline-flex;align-items:center;gap:5px;white-space:nowrap;font-weight:850}.map-tools input{accent-color:var(--blue);width:15px;height:15px}.map-svg .grid-cell{fill:#d9f2ff20;stroke:#efffff99;stroke-width:.8}.map-svg .flood{fill:#e7478758;stroke:#fff1a1;stroke-width:3}.map-svg .service{stroke-width:2.4}.map-svg .service.selected{stroke:#fff7b0;stroke-width:4}.map-svg .service-index{font-size:10px;font-weight:950;text-anchor:middle;dominant-baseline:central;fill:#fff;pointer-events:none}.map-svg .service-label{display:none;font-size:13px;font-weight:950}.map-svg.show-labels .service-label{display:block}.map-point-list{display:flex;gap:7px;flex-wrap:wrap;margin:10px 3px 0}.map-point-list:empty{display:none}.map-point-button{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;padding:6px 9px;background:#fff;color:var(--ink);font:inherit;font-size:12px;font-weight:850;cursor:pointer}.map-point-button:hover,.map-point-button:focus-visible{border-color:#78b9c5;background:#f0fbff;outline:3px solid #bfe2f5}.point-number{display:inline-grid;place-items:center;width:21px;height:21px;border-radius:50%;background:var(--blue);color:#fff;font-size:11px;font-weight:950}@media(max-width:700px){.map-tools{align-items:flex-start}.map-tools-title{width:100%}.map-point-button{font-size:11px}.map-svg .service-label{font-size:13px}}
</style><style>__EXTRA_CSS__</style></head>
<body><a class="skip-link" href="#workspace">Pular para explorar os eventos</a><main><section class="shell">
<div class="eyebrow">PREVINE · replay histórico · território</div>
<h1>Todos os eventos, no mesmo lugar</h1>
<p class="muted">Compare os replays disponíveis de <strong>Muçum</strong> e <strong>Santa Tereza</strong> e veja, ao lado, a camada territorial correspondente. O gráfico responde “o que o modelo reproduziu?”; o mapa responde “qual cenário espacial está sendo examinado?”.</p>
<div class="notice"><strong>Pesquisa, não operação.</strong> As séries são replays históricos. A camada espacial é um cenário de triagem sobre MDT e manchas publicadas; a conversão cota–mancha, rotas, capacidade de abrigo e despacho continuam fora deste painel.</div>
<section class="panel" aria-labelledby="calibrationGateTitle" style="margin:16px 0 0;background:linear-gradient(135deg,#f3fbff,#fffaf0);border-color:#cfe3e7"><div class="event-head"><div><h2 id="calibrationGateTitle">Validação entre eventos · HEC-HMS</h2><div class="muted" id="calibrationStatus">Verificando a cobertura dos dados…</div></div><span class="pill warn">pesquisa · não promovida</span></div><div class="summary" style="margin:11px 0 0"><div class="summary-card"><div class="label">Rede completa · 3 zonas</div><div class="value" id="threeZoneCount">—</div><div class="detail" id="threeZoneDetail">chuva nos três postos + vazão-alvo</div></div><div class="summary-card"><div class="label">Sensibilidade · posto-alvo</div><div class="value" id="targetRainCount">—</div><div class="detail" id="targetRainDetail">eventos com chuva e vazão completas</div></div><div class="summary-card"><div class="label">Teste de dois postos</div><div class="value" id="twoStationScore">—</div><div class="detail" id="twoStationDetail">resultado médio da busca diagnóstica</div></div></div><div class="source-links"><a id="calibrationStatusLink" href="../assets/data/hec_hms_integrated_taquari_antas/network_calibration_status_latest.json">status auditado</a><a id="calibrationGateLink" href="../assets/data/hec_hms_audit/calibration_input_gate_latest.json">gate de entradas</a><a id="twoStationLink" href="../assets/data/hec_hms_integrated_taquari_antas/network_two_station_search/two_station_search_report.json">teste espacial de dois postos</a></div></section>
<div class="summary" aria-label="Escopo dos dados"><div class="summary-card"><div class="label">Eventos reunidos</div><div class="value" id="totalEvents">—</div><div class="detail">Muçum + Santa Tereza</div></div><div class="summary-card"><div class="label">Muçum</div><div class="value" id="mucumEvents">—</div><div class="detail">HEC-HMS · vazão</div></div><div class="summary-card"><div class="label">Santa Tereza</div><div class="value" id="santaEvents">—</div><div class="detail">RNA 2h · nível</div></div><div class="summary-card"><div class="label">Testes independentes</div><div class="value" id="independentEvents">—</div><div class="detail">mantidos separados do treino</div></div></div>
<nav class="quick-nav" aria-label="Nesta página"><a href="#workspace">Explorar eventos</a><a href="#mapTitle">Território</a><a href="#calibrationGateTitle">Validação HEC-HMS</a><a href="#catalogTitle">Catálogo</a></nav><div class="toolbar" id="workspace" tabindex="-1"><div class="field"><label for="citySelect">Município / coleção</label><select id="citySelect"><option value="all">Todos os eventos</option><option value="mucum">Muçum</option><option value="santa_tereza">Santa Tereza</option></select></div><div class="field"><label for="eventSelect">Evento para abrir no gráfico</label><select id="eventSelect"></select></div><div class="checks"><label class="check-label"><input id="showObserved" type="checkbox" checked> observado</label><label class="check-label"><input id="showModel" type="checkbox" checked> modelo</label><button class="button" id="resetZoom" type="button">Redefinir zoom</button></div><div class="level-box"><div class="level-readout"><label for="levelRange">Cenário espacial manual · separado do gráfico</label><output id="levelValue">—</output></div><input id="levelRange" type="range" min="0" max="25" step="1" value="18"></div></div>
<div class="layout"><section class="panel"><div class="event-head"><div><strong id="eventTitle" tabindex="-1">—</strong><div class="muted" id="eventSubtitle">—</div></div><span id="eventStatus" class="pill">—</span></div><div class="kpis" aria-label="Métricas do evento"><div class="kpi"><div class="label">Pico observado</div><div class="value" id="obsPeak">—</div><div class="unit" id="unitObs">—</div></div><div class="kpi"><div class="label">Pico modelo</div><div class="value" id="modelPeak">—</div><div class="unit" id="unitModel">—</div></div><div class="kpi"><div class="label">Erro do pico</div><div class="value" id="peakError">—</div><div class="unit">diferença relativa</div></div><div class="kpi"><div class="label">Atraso do pico</div><div class="value" id="peakLag">—</div><div class="unit">modelo − observado</div></div><div class="kpi"><div class="label">Ajuste</div><div class="value" id="fitMetric">—</div><div class="unit" id="fitLabel">NSE ou MAE</div></div><div class="kpi"><div class="label">Amostras</div><div class="value" id="pairs">—</div><div class="unit">pontos pareados</div></div></div><section class="chart-panel" aria-labelledby="chartTitle"><div class="chart-head"><div><h2 id="chartTitle">—</h2><div class="muted" id="peakDates"></div></div><div class="legend"><span><i class="dot blue"></i>observado</span><span><i class="dot orange"></i><span id="modelLegend">modelo</span></span></div></div><div class="chart-wrap"><canvas id="chart" tabindex="0" role="img" aria-label="Série temporal. Setas percorrem os horários; Escape restaura o intervalo." aria-describedby="srSummary"></canvas><div class="tip" id="tip"></div></div><div class="chart-foot"><span id="rangeText"></span><span>Mouse: arraste para ampliar · teclado: setas para ler os horários</span></div><p class="chart-quality" id="chartQuality"></p><div class="chart-range"><label for="chartStart">Início do intervalo<input id="chartStart" type="range" min="0" max="0" value="0"></label><label for="chartEnd">Fim do intervalo<input id="chartEnd" type="range" min="0" max="0" value="0"></label></div><output class="point-readout" id="pointReadout">Selecione um horário com as setas no gráfico.</output><div class="sr-only" id="srSummary" aria-live="polite"></div><details class="series-details"><summary>Ver os valores do intervalo em tabela</summary><div class="table-wrap"><table class="series-table"><caption id="seriesCaption"></caption><thead><tr><th scope="col">Horário BRT</th><th scope="col">Observado</th><th scope="col">Modelo</th></tr></thead><tbody id="seriesRows"></tbody></table></div></details></section><div class="reading" id="reading">—</div><div class="source-links"><a id="metricsLink" href="#">métricas</a><a id="seriesLink" href="#">série</a><a id="manifestLink" href="#">manifesto do pacote</a></div></section>
<section class="panel map-panel"><div class="map-top"><div><strong id="mapTitle" tabindex="-1">—</strong><div class="small muted" id="mapSubtitle">—</div></div><span class="pill" id="mapStatus">—</span></div><div class="map-viewport" id="mapViewport"><div class="map-content" id="mapContent"><img class="map-bg" id="mapBg" alt="Fundo visual do MDT do município"><svg class="map-svg" id="mapSvg" viewBox="0 0 1000 1000" role="group" aria-label="Cenário territorial exploratório"></svg></div><div class="map-badge" id="mapBadge">—</div><div class="map-controls"><button class="button" id="mapZoomIn" type="button" aria-label="Aumentar mapa">+</button><button class="button" id="mapZoomOut" type="button" aria-label="Reduzir mapa">−</button><button class="button" id="mapReset" type="button">Enquadrar</button></div><div class="north">N ↑</div></div><div class="map-legend"><span><i class="legend-swatch swatch-flood"></i>contorno selecionado</span><span><i class="legend-swatch swatch-grid"></i>grade 200 m</span><span><i class="legend-swatch swatch-shelter"></i>abrigo cadastrado</span><span><i class="legend-swatch swatch-fire"></i>bombeiros</span><span><i class="legend-swatch swatch-health"></i>saúde</span><span><i class="legend-swatch swatch-school"></i>escola</span></div><div class="map-selection"><label for="cellSelect">Consultar uma célula da grade</label><select id="cellSelect"><option value="">Selecione uma célula</option></select></div><div class="cell-info" id="cellInfo" role="status"><strong>Explore a grade</strong><p>Clique em uma célula de 200 m para abrir a população agregada e a completude do dado. A grade não representa endereços individuais.</p></div><div class="spatial-note" id="spatialNote">—</div></section></div>
<section class="panel all-events"><div class="event-head"><div><h2 id="catalogTitle">Catálogo completo de replays</h2><div class="muted">Clique em qualquer linha para trocar o evento aberto. Diagnóstico não vira calibração por aparecer na mesma tabela.</div></div><span class="pill" id="tableScope">27 eventos</span></div><div class="table-wrap"><table class="events-table"><thead><tr><th>Evento</th><th>Município</th><th>Modelo</th><th>Período</th><th>Pico obs.</th><th>Pico modelo</th><th>Erro</th><th>Status</th></tr></thead><tbody id="eventRows"></tbody></table></div></section>
<div class="foot-grid"><section class="panel"><h2>O que melhorou nesta sala</h2><p>Um seletor reúne 6 eventos HEC-HMS de Muçum e 21 eventos RNA de Santa Tereza.</p><p>O mapa usa um fundo de MDT visual, contorno do nível escolhido, grade 200 m clicável e pontos de apoio locais.</p><p>O nível espacial é escolhido explicitamente; ele não é convertido automaticamente a partir do pico do gráfico.</p></section><section class="panel"><h2>Fontes e limites</h2><p><a href="../assets/data/research_event_replay_latest.json">Manifesto espacial auditável</a> · <a href="../pesquisas/sala-integrada-eventos.html">sala integrada anterior</a></p><p><a href="../assets/data/mucum_eventwise_replay_calibrated/index.html">visualizador HEC-HMS de Muçum</a> · <a href="../assets/data/santa_tereza_eventwise_replay_rna_2h/santa_tereza_event_replay.html">visualizador RNA de Santa Tereza</a></p><p>O MDT e as manchas são visualizações de pesquisa. O próprio manifesto registra pendência de datum/CRS vertical e, em Santa Tereza, não há cenário publicado acima de 15 m nesta fonte.</p></section></div>
</section></main>
<script>const DATA=__DATA__;</script>
<script>__RUNTIME__</script></body></html>'''


# Keep the reader-facing language precise: the experiment contains three
# incremental model areas along a connected BHO6 corridor, not three zones of
# the whole Taquari-Antas basin.
HTML = HTML.replace("Rede completa · 3 zonas", "Cobertura completa · 3 áreas incrementais")
HTML = HTML.replace('id="threeZoneCount"', 'id="incrementalAreaCount"')
HTML = HTML.replace('id="threeZoneDetail"', 'id="incrementalAreaDetail"')
HTML = HTML.replace("chuva nos três postos + vazão-alvo", "chuva nos controles + vazão no exutório")
HTML = HTML.replace("Sensibilidade · posto-alvo", "Diagnóstico pontual · 86510000")
HTML = HTML.replace('id="calibrationStatus">Verificando a cobertura dos dados…</div>', 'id="calibrationStatus">Verificando a cobertura dos dados…</div><div class="muted" id="calibrationScope" style="margin-top:5px">__NETWORK_SCOPE__</div>')
HTML = HTML.replace("const zone=c.three_zone_events||[]", "const area=c.incremental_area_events||[]")
HTML = HTML.replace("A rede de três zonas", "A cobertura das três áreas incrementais")
HTML = HTML.replace("A cobertura das três áreas incrementais só tem cobertura completa em", "A cobertura das três áreas incrementais está completa em")
HTML = HTML.replace("zone.length", "area.length")
HTML = HTML.replace("zone.join", "area.join")
HTML = HTML.replace("$('threeZoneCount')", "$('incrementalAreaCount')")
HTML = HTML.replace("$('threeZoneDetail')", "$('incrementalAreaDetail')")
HTML = HTML.replace('$("threeZoneCount")', '$("incrementalAreaCount")')
HTML = HTML.replace('$("threeZoneDetail")', '$("incrementalAreaDetail")')

# Keep the calibration evidence one tap away without making it displace the
# event selector and the actual replay on the first screen.
HTML = HTML.replace(
    '<section class="panel" aria-labelledby="calibrationGateTitle" style="margin:16px 0 0;background:linear-gradient(135deg,#f3fbff,#fffaf0);border-color:#cfe3e7">',
    '<details class="panel calibration-panel"><summary><span>Validação HEC-HMS: generalização ainda não demonstrada</span><small>abrir evidências</small></summary><div class="calibration-body">',
    1,
)
HTML = HTML.replace(
    '</div></section>\n<div class="summary" aria-label="Escopo dos dados">',
    '</div></div></details>\n<div class="summary" aria-label="Escopo dos dados">',
    1,
)

# Semantic and keyboard affordances for the two dense tables and the map.
HTML = HTML.replace(
    '<strong id="eventTitle" tabindex="-1">—</strong>',
    '<h2 id="eventTitle" tabindex="-1">—</h2>',
)
HTML = HTML.replace(
    '<section class="panel map-panel"><div class="map-top"><div><strong id="mapTitle" tabindex="-1">—</strong>',
    '<section class="panel map-panel" aria-labelledby="mapTitle"><div class="map-top"><div><h2 id="mapTitle" tabindex="-1">—</h2>',
)
HTML = HTML.replace(
    '<div class="table-wrap"><table class="series-table">',
    '<p class="table-instruction">Tabela rolável: use as setas quando o quadro estiver em foco.</p><div class="table-wrap" tabindex="0" role="region" aria-label="Valores horários; use as setas para rolar"><table class="series-table">',
)
HTML = HTML.replace(
    '<div class="table-wrap"><table class="events-table">',
    '<p class="table-instruction">Em telas estreitas, arraste a tabela ou coloque o quadro em foco e use as setas.</p><div class="table-wrap" tabindex="0" role="region" aria-label="Catálogo completo de replays; use as setas para rolar"><table class="events-table">',
)
HTML = HTML.replace(
    '<thead><tr><th>Evento</th><th>Município</th><th>Modelo</th><th>Período</th><th>Pico obs.</th><th>Pico modelo</th><th>Erro</th><th>Status</th></tr></thead>',
    '<thead><tr><th scope="col">Evento</th><th scope="col">Município</th><th scope="col">Modelo</th><th scope="col">Período</th><th scope="col">Pico obs.</th><th scope="col">Pico modelo</th><th scope="col">Erro</th><th scope="col">Status</th></tr></thead>',
)
HTML = HTML.replace(
    '<span><i class="legend-swatch swatch-flood"></i>contorno selecionado</span>',
    '<span data-legend="contour"><i class="legend-swatch swatch-flood"></i>contorno selecionado</span>',
)
HTML = HTML.replace(
    '<span><i class="legend-swatch swatch-grid"></i>grade 200 m</span>',
    '<span data-legend="grid"><i class="legend-swatch swatch-grid"></i>grade 200 m</span>',
)
for legend_class in ("shelter", "fire", "health", "school"):
    HTML = HTML.replace(
        f'<span><i class="legend-swatch swatch-{legend_class}"></i>',
        f'<span data-legend="services"><i class="legend-swatch swatch-{legend_class}"></i>',
    )


# Add the model-selection rationale without making the main event card harder
# to scan.  It is populated from the manifest and stays hidden when an event
# has no explicit calibration trade-off.
HTML = HTML.replace(
    '<div class="reading" id="reading">—</div>',
    '<div class="reading" id="reading">—</div><div id="selectionNote" style="display:none;margin-top:9px;border:1px solid #f0dfbd;border-left:4px solid #b57216;border-radius:11px;background:#fff8e9;padding:10px 12px;color:#70480d;font-size:12px"></div>',
)

# Expose freshness, add an event-comparison view, and let the reader replay the
# historical hourly series. These controls use only values embedded in DATA.
HTML = HTML.replace(
    '<div class="notice"><strong>Pesquisa, não operação.</strong> As séries são replays históricos. A camada espacial é um cenário de triagem sobre MDT e manchas publicadas; a conversão cota–mancha, rotas, capacidade de abrigo e despacho continuam fora deste painel.</div>',
    '<div class="notice"><strong>Pesquisa, não operação.</strong> As séries são replays históricos. A camada espacial é um cenário de triagem sobre MDT e manchas publicadas; a conversão cota–mancha, rotas, capacidade de abrigo e despacho continuam fora deste painel.</div><div class="snapshot-strip" aria-label="Atualização e natureza dos dados"><span id="snapshotFreshness">Data do snapshot indisponível</span><span id="snapshotSources">Fontes embarcadas e reproduzíveis · não é telemetria ao vivo</span></div>',
)
HTML = HTML.replace(
    '<a href="#catalogTitle">Catálogo</a>',
    '<a href="#comparisonTitle">Comparar eventos</a><a href="#catalogTitle">Catálogo</a>',
)
HTML = HTML.replace(
    '<p class="chart-quality" id="chartQuality"></p>',
    '<div class="playback-panel" aria-label="Reprodução do replay histórico"><button class="button playback-button" id="playReplay" type="button" aria-pressed="false">▶ Reproduzir replay</button><label for="playSpeed">Velocidade<select id="playSpeed"><option value="900">lenta</option><option value="450" selected>normal</option><option value="160">rápida</option></select></label><progress id="playProgress" max="1" value="0"></progress><output id="playStatus" aria-live="polite">—</output></div><p class="playback-note">A animação apenas percorre o replay histórico hora a hora; não é previsão em tempo real.</p><p class="chart-quality" id="chartQuality"></p>',
)
comparison = '''<section class="panel comparison-panel" aria-labelledby="comparisonTitle"><div class="event-head"><div><h2 id="comparisonTitle">Onde o replay mais divergiu</h2><div class="muted" id="comparisonSubtitle">Ordenando os eventos com dados disponíveis.</div></div><span class="pill" id="comparisonScope">—</span></div><div class="comparison-toolbar"><label for="comparisonMetric">Ordenar por<select id="comparisonMetric"><option value="peak_error">erro relativo do pico</option><option value="lag">diferença temporal do pico</option></select></label></div><div class="compare-rows" id="comparisonRows"></div><div class="comparison-foot"><button class="button" id="comparisonToggle" type="button" aria-expanded="false">Mostrar todos</button><p id="comparisonNote"></p></div></section>'''
HTML = HTML.replace(
    '<section class="panel all-events">',
    comparison + '<section class="panel all-events">',
    1,
)
HTML = HTML.replace(
    '<p class="table-instruction">Em telas estreitas, arraste a tabela ou coloque o quadro em foco e use as setas.</p><div class="table-wrap" tabindex="0" role="region" aria-label="Catálogo completo de replays; use as setas para rolar">',
    '<details class="catalog-details" id="catalogDetails"><summary><span id="catalogSummary">Abrir tabela com 27 eventos</span><small>valores exatos e status</small></summary><p class="table-instruction">Em telas estreitas, arraste a tabela ou coloque o quadro em foco e use as setas.</p><div class="table-wrap" tabindex="0" role="region" aria-label="Catálogo completo de replays; use as setas para rolar">',
    1,
)
HTML = HTML.replace(
    '</div></section>\n<div class="foot-grid">',
    '</div></details></section>\n<div class="foot-grid">',
    1,
)

def main() -> None:
    spatial_manifest = json.loads(SPATIAL.read_text(encoding="utf-8"))
    calibration = calibration_snapshot()
    payload = {
        "events": mucum_events() + santa_events(),
        "spatial": spatial_data(),
        "calibration": calibration,
        "meta": {
            "spatial_generated_at_utc": spatial_manifest.get("generated_at_utc"),
            "calibration_generated_at_utc": calibration.get("generated_at_utc"),
        },
    }
    extent = payload["calibration"].get("network_extent", {})
    upstream = f"{int(extent.get('upstream_segments_reachable_from_86510000', 0)):,}".replace(",", ".")
    mainstem = f"{int(extent.get('mainstem_segments_in_upstream_network', 0)):,}".replace(",", ".")
    scope_text = (
        f"Escopo: {payload['calibration'].get('model_scope') or 'corredor BHO6 conectado'}. "
        f"A fonte BHO6 tem {upstream} trechos a montante do controle de Muçum, "
        f"incluindo {mainstem} no eixo principal; este experimento usa "
        f"{int(extent.get('explicit_model_reach_segment_references', 0))} referências em "
        f"{int(extent.get('explicit_model_reaches', 0))} trechos de propagação."
    )
    output = ROOT / "pesquisas" / "replay-hidrologico-espacial.html"
    runtime = (ROOT / "assets/js/replay-hidrologico-espacial.js").read_text(encoding="utf-8")
    extra_css = (ROOT / "assets/css/replay-hidrologico-espacial.css").read_text(encoding="utf-8")
    # Escaping '<' prevents source labels from terminating the embedded JSON script.
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    page = HTML.replace("__NETWORK_SCOPE__", escape(scope_text)).replace("__DATA__", serialized)
    output.write_text(page.replace("__RUNTIME__", runtime).replace("__EXTRA_CSS__", extra_css), encoding="utf-8")
    print(f"wrote {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
