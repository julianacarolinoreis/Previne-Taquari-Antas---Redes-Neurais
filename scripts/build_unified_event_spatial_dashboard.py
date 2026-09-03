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
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MUCUM = ROOT / "assets" / "data" / "mucum_eventwise_replay_calibrated"
SANTA = ROOT / "assets" / "data" / "santa_tereza_eventwise_replay_rna_2h"
SPATIAL = ROOT / "assets" / "data" / "research_event_replay_latest.json"


def num(value: object | None) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
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
            if observed is not None and simulated is not None:
                series.append([timestamp_value, observed, simulated])

        status = "fechado" if item["status"] in {"calibrated_replay", "calibrated_replay_timing_priority"} else "diagnóstico"
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
        if observed is not None and predicted is not None:
            by_event.setdefault(key, []).append(
                [row["timestamp_local"].replace(" ", "T"), observed, predicted]
            )
    result = []
    for row in rows:
        event_id = str(row["evento"])
        role = row["papel_avaliacao"]
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
                    "peak_error": (num(row.get("erro_pico_relativo_pct")) or 0) / 100,
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
    return {
        "mucum": {
            "label": "Muçum",
            "background": "../assets/data/mucum_inundacao/mdt/altitude_terreno_10m.png",
            "background_label": "MDT visual 10 m · mosaico de terreno",
            "bounds": json.loads((ROOT / "assets/data/mucum_inundacao/mdt/altitude_terreno_10m.json").read_text(encoding="utf-8"))["bounds"],
            "crs": "EPSG:4326",
            "level_min": 0,
            "level_max": 25,
            "contours": selected_contours(ROOT / "assets/data/mucum_inundacao/contornos_mancha.json", set(range(0, 26))),
            "grid": compact_grid(ROOT / "assets/data/vulnerabilidade/grade/4312609.geojson"),
            "points": service_points("Muçum"),
            "stage_status": mucum["stage_conversion_status"],
            "published": {str(int(s["level_m"])): s for s in mucum["scenarios"]},
            "grid_source": mucum["grid_source"],
            "contour_source": mucum["contour_source"],
        },
        "santa_tereza": {
            "label": "Santa Tereza",
            "background": "../assets/data/santa_tereza_inundacao/mdt/altitude_terreno_10m_refinado.png",
            "background_label": "MDT visual refinado 10 m · corredor do talvegue",
            "bounds": json.loads((ROOT / "assets/data/santa_tereza_inundacao/mdt/altitude_terreno_10m_refinado.json").read_text(encoding="utf-8"))["bounds"],
            "crs": "EPSG:4326",
            "level_min": 0,
            "level_max": 15,
            "contours": selected_contours(ROOT / "assets/data/santa_tereza_inundacao/contornos_mancha.json", set(range(0, 16))),
            "grid": compact_grid(ROOT / "assets/data/vulnerabilidade/grade/4317251.geojson"),
            "points": service_points("Santa Tereza"),
            "stage_status": santa["stage_conversion_status"],
            "higher_than_published_status": santa["higher_than_published_status"],
            "published": {str(int(s["level_m"])): s for s in santa["scenarios"]},
            "grid_source": santa["grid_source"],
            "contour_source": santa["contour_source"],
        },
    }


HTML = r'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PREVINE · replay histórico e território</title>
<style>
:root{--ink:#12313b;--muted:#607681;--line:#d6e6e8;--paper:#fff;--bg:#eff8f7;--blue:#0879c9;--orange:#ed7a2a;--teal:#087d77;--pink:#df3f88;--gold:#b57216;--shadow:0 18px 44px rgba(15,57,70,.11)}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 90% 0,#fff0dc 0,transparent 30%),linear-gradient(145deg,#edf8f7,#f8fbff 62%,#fffaf2);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Arial,sans-serif}main{max-width:1440px;margin:auto;padding:22px 18px 48px}.shell{background:var(--paper);border:1px solid var(--line);border-radius:26px;box-shadow:var(--shadow);padding:24px}.eyebrow{color:var(--teal);font-size:11px;font-weight:950;letter-spacing:.13em;text-transform:uppercase}h1{font-size:clamp(28px,4vw,48px);line-height:1.01;letter-spacing:-.045em;margin:7px 0 11px}h2{font-size:19px;margin:0 0 12px}h3{font-size:15px;margin:0 0 6px}.muted{color:var(--muted)}.notice{margin:16px 0;padding:13px 15px;border-left:5px solid var(--gold);background:#fff7e7;color:#70480d;border-radius:11px}.summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:18px 0}.summary-card{border:1px solid var(--line);border-radius:15px;padding:13px 14px;background:linear-gradient(145deg,#fff,#f5fbfb)}.summary-card .label{text-transform:uppercase;font-size:10px;font-weight:950;color:var(--muted);letter-spacing:.05em}.summary-card .value{font-size:28px;font-weight:950;color:var(--blue);margin-top:3px}.summary-card .detail{font-size:12px;color:var(--muted)}.toolbar{display:flex;gap:12px;align-items:end;flex-wrap:wrap;padding:15px;border:1px solid var(--line);border-radius:16px;background:#f7fcfc}.field{display:flex;flex-direction:column;gap:6px;min-width:220px}.field label,.check-label{font-size:12px;font-weight:900}.field select,.field input[type=range]{width:100%}.field select{border:1px solid #a8cbd0;border-radius:10px;background:#fff;padding:10px 11px;color:var(--ink);font-weight:850;font-size:15px}.checks{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding-bottom:9px}.check-label{display:flex;gap:7px;align-items:center;color:var(--ink);white-space:nowrap}input[type=checkbox]{accent-color:var(--blue);width:17px;height:17px}.button{border:1px solid #a8cbd0;border-radius:10px;padding:10px 13px;background:#fff;color:var(--blue);font-weight:900;cursor:pointer}.button:hover,.button:focus-visible{background:#edf7ff;outline:3px solid #bfe2f5}.level-box{min-width:220px}.level-readout{display:flex;justify-content:space-between;gap:10px;align-items:center;font-weight:900}.level-readout output{color:var(--pink);font-size:19px}.level-box input{accent-color:var(--pink)}.layout{display:grid;grid-template-columns:minmax(360px,.9fr) minmax(560px,1.45fr);gap:16px;margin-top:16px}.panel{border:1px solid var(--line);border-radius:19px;background:#fff;padding:16px}.event-head{display:flex;justify-content:space-between;gap:12px;align-items:start;flex-wrap:wrap}.event-head strong{font-size:22px}.pill{display:inline-flex;align-items:center;border-radius:999px;padding:5px 10px;background:#e8f5f3;color:var(--teal);font-size:12px;font-weight:950}.pill.warn{background:#fff1e8;color:#a74e19}.pill.test{background:#eaf1ff;color:#245b9b}.kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:14px 0}.kpi{border:1px solid var(--line);border-radius:13px;padding:11px 10px;min-width:0;background:#fbfefe}.kpi .label{text-transform:uppercase;font-size:10px;color:var(--muted);font-weight:950}.kpi .value{font-size:clamp(19px,2.2vw,27px);font-weight:950;margin-top:3px;white-space:nowrap}.kpi .unit{font-size:11px;color:var(--muted)}.chart-panel{margin-top:13px;border:1px solid var(--line);border-radius:17px;padding:13px 10px 9px;background:#fff}.chart-head{display:flex;justify-content:space-between;gap:10px;align-items:start;flex-wrap:wrap}.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;font-weight:850;color:var(--muted)}.legend span{display:inline-flex;align-items:center;gap:6px}.dot{width:21px;height:4px;border-radius:5px;display:inline-block}.dot.blue{background:var(--blue)}.dot.orange{background:var(--orange)}.chart-wrap{position:relative;height:350px;margin-top:4px}.chart-wrap canvas{display:block;width:100%;height:100%;touch-action:none;cursor:crosshair}.tip{position:absolute;display:none;z-index:2;pointer-events:none;min-width:190px;background:#12343e;color:#fff;border-radius:10px;padding:9px 11px;box-shadow:0 10px 22px #12343e35;font-size:12px}.tip strong{display:block;color:#fff4b0;margin-bottom:3px}.chart-foot{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;color:var(--muted);font-size:11px}.reading{margin-top:13px;border:1px solid #d6ece5;border-left:4px solid var(--teal);border-radius:11px;background:#f1faf7;padding:11px 12px;color:#35625f;font-size:13px}.source-links{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;font-size:12px}.source-links a,.table-link{color:var(--blue);font-weight:900}.map-panel{padding:12px}.map-top{display:flex;justify-content:space-between;gap:12px;align-items:start;flex-wrap:wrap;padding:4px 3px 11px}.map-top strong{font-size:20px}.map-top .small{max-width:680px}.map-viewport{position:relative;overflow:hidden;min-height:590px;border:1px solid #b8d0d1;border-radius:15px;background:#b5d1ce;touch-action:none;isolation:isolate}.map-content{position:absolute;inset:0;transform-origin:center;will-change:transform}.map-bg{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;filter:saturate(.8) contrast(1.04);opacity:.92}.map-bg::after{content:""}.map-svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}.map-svg .grid-cell{fill:#d9f2ff44;stroke:#e9ffffcc;stroke-width:1;vector-effect:non-scaling-stroke;cursor:pointer}.map-svg .grid-cell:hover,.map-svg .grid-cell.selected{fill:#ffed9c99;stroke:#f5a623;stroke-width:3}.map-svg .flood{fill:#e7478790;stroke:#ffef88;stroke-width:2.2;vector-effect:non-scaling-stroke}.map-svg .service{stroke:#fff;stroke-width:2;vector-effect:non-scaling-stroke}.map-svg .service.shelter{fill:#0b9c8b}.map-svg .service.fire{fill:#ec6b37}.map-svg .service.health{fill:#2874d6}.map-svg .service.school{fill:#7356bb}.map-svg .service-label{font-size:12px;font-weight:900;paint-order:stroke;stroke:#fff;stroke-width:4px;stroke-linejoin:round;fill:#173945}.map-badge{position:absolute;top:12px;left:12px;max-width:min(420px,calc(100% - 24px));padding:10px 12px;border-radius:12px;background:#12343ee8;color:#fff;font-size:12px;box-shadow:0 8px 18px #12343e44;z-index:3}.map-badge strong{display:block;color:#fff4ae;margin-bottom:3px;font-size:14px}.map-controls{position:absolute;right:12px;top:12px;display:flex;gap:5px;z-index:4}.map-controls .button{padding:8px 11px;background:#fffffff0}.north{position:absolute;right:18px;bottom:18px;color:#163d47;font-weight:950;background:#ffffffc8;border-radius:8px;padding:5px 8px;z-index:3}.map-legend{display:flex;gap:12px;flex-wrap:wrap;margin:10px 3px 0;color:var(--muted);font-size:12px;font-weight:800}.map-legend span{display:inline-flex;gap:6px;align-items:center}.legend-swatch{display:inline-block;width:18px;height:10px;border-radius:3px;border:1px solid #fff}.swatch-flood{background:#e7478790;border-color:#ffef88}.swatch-grid{background:#d9f2ff88;border-color:#e9ffff}.swatch-shelter{background:#0b9c8b}.swatch-fire{background:#ec6b37}.swatch-health{background:#2874d6}.swatch-school{background:#7356bb}.cell-info{margin-top:11px;border:1px solid var(--line);border-radius:13px;padding:12px;background:#fbfefe;min-height:87px}.cell-info strong{color:var(--blue)}.cell-info p{margin:3px 0 0;color:var(--muted);font-size:12px}.spatial-note{margin-top:11px;color:var(--muted);font-size:12px}.all-events{margin-top:16px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:15px}.events-table{border-collapse:collapse;width:100%;min-width:760px;font-size:13px}.events-table th,.events-table td{padding:10px 11px;border-bottom:1px solid #e7eff0;text-align:left;vertical-align:middle}.events-table th{font-size:10px;text-transform:uppercase;color:var(--muted);letter-spacing:.05em;background:#f7fcfc;position:sticky;top:0}.events-table tr:last-child td{border-bottom:0}.events-table tr.selected{background:#fff8e9}.events-table tr{cursor:pointer}.events-table tr:hover{background:#f2f9ff}.event-button{border:0;background:none;padding:0;color:var(--blue);font-weight:950;cursor:pointer;font:inherit}.tiny-pill{display:inline-flex;border-radius:999px;padding:3px 7px;font-size:11px;font-weight:900;background:#e8f5f3;color:#087d77;white-space:nowrap}.tiny-pill.warn{background:#fff1e8;color:#a74e19}.tiny-pill.test{background:#eaf1ff;color:#245b9b}.foot-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}.foot-grid .panel p{margin:4px 0;color:var(--muted);font-size:13px}.foot-grid a{color:var(--blue);font-weight:900}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}@media(max-width:1100px){.layout{grid-template-columns:1fr}.map-viewport{min-height:520px}.summary{grid-template-columns:repeat(4,1fr)}}@media(max-width:700px){main{padding:10px 8px 28px}.shell{padding:15px;border-radius:19px}.summary{grid-template-columns:repeat(2,1fr)}.summary-card .value{font-size:24px}.toolbar{align-items:stretch}.field,.level-box{min-width:100%}.kpis{grid-template-columns:repeat(2,1fr)}.chart-wrap{height:290px}.map-viewport{min-height:410px}.map-svg .service-label{font-size:15px}.foot-grid{grid-template-columns:1fr}.map-top strong{font-size:18px}.map-badge{font-size:11px}.map-controls{top:auto;bottom:12px;right:12px}}
</style></head>
<body><main><section class="shell">
<div class="eyebrow">PREVINE · replay histórico · território</div>
<h1>Todos os eventos, no mesmo lugar</h1>
<p class="muted">Compare os replays disponíveis de <strong>Muçum</strong> e <strong>Santa Tereza</strong> e veja, ao lado, a camada territorial correspondente. O gráfico responde “o que o modelo reproduziu?”; o mapa responde “qual cenário espacial está sendo examinado?”.</p>
<div class="notice"><strong>Pesquisa, não operação.</strong> As séries são replays históricos. A camada espacial é um cenário de triagem sobre MDT e manchas publicadas; a conversão cota–mancha, rotas, capacidade de abrigo e despacho continuam fora deste painel.</div>
<div class="summary" aria-label="Escopo dos dados"><div class="summary-card"><div class="label">Eventos reunidos</div><div class="value" id="totalEvents">—</div><div class="detail">Muçum + Santa Tereza</div></div><div class="summary-card"><div class="label">Muçum</div><div class="value" id="mucumEvents">—</div><div class="detail">HEC-HMS · vazão</div></div><div class="summary-card"><div class="label">Santa Tereza</div><div class="value" id="santaEvents">—</div><div class="detail">RNA 2h · nível</div></div><div class="summary-card"><div class="label">Testes independentes</div><div class="value" id="independentEvents">—</div><div class="detail">mantidos separados do treino</div></div></div>
<div class="toolbar"><div class="field"><label for="citySelect">Município / coleção</label><select id="citySelect"><option value="all">Todos os eventos</option><option value="mucum">Muçum</option><option value="santa_tereza">Santa Tereza</option></select></div><div class="field"><label for="eventSelect">Evento para abrir no gráfico</label><select id="eventSelect"></select></div><div class="checks"><label class="check-label"><input id="showObserved" type="checkbox" checked> observado</label><label class="check-label"><input id="showModel" type="checkbox" checked> modelo</label><button class="button" id="resetZoom" type="button">Redefinir zoom</button></div><div class="level-box"><div class="level-readout"><label for="levelRange">Cota do contorno espacial</label><output id="levelValue">—</output></div><input id="levelRange" type="range" min="0" max="25" step="1" value="18"></div></div>
<div class="layout"><section class="panel"><div class="event-head"><div><strong id="eventTitle">—</strong><div class="muted" id="eventSubtitle">—</div></div><span id="eventStatus" class="pill">—</span></div><div class="kpis" aria-label="Métricas do evento"><div class="kpi"><div class="label">Pico observado</div><div class="value" id="obsPeak">—</div><div class="unit" id="unitObs">—</div></div><div class="kpi"><div class="label">Pico modelo</div><div class="value" id="modelPeak">—</div><div class="unit" id="unitModel">—</div></div><div class="kpi"><div class="label">Erro do pico</div><div class="value" id="peakError">—</div><div class="unit">diferença relativa</div></div><div class="kpi"><div class="label">Atraso do pico</div><div class="value" id="peakLag">—</div><div class="unit">modelo − observado</div></div><div class="kpi"><div class="label">Ajuste</div><div class="value" id="fitMetric">—</div><div class="unit" id="fitLabel">NSE ou MAE</div></div><div class="kpi"><div class="label">Amostras</div><div class="value" id="pairs">—</div><div class="unit">pontos pareados</div></div></div><section class="chart-panel" aria-labelledby="chartTitle"><div class="chart-head"><div><h2 id="chartTitle">—</h2><div class="muted" id="peakDates"></div></div><div class="legend"><span><i class="dot blue"></i>observado</span><span><i class="dot orange"></i><span id="modelLegend">modelo</span></span></div></div><div class="chart-wrap"><canvas id="chart" aria-label="Gráfico interativo do replay"></canvas><div class="tip" id="tip"></div></div><div class="chart-foot"><span id="rangeText"></span><span>Arraste para ampliar · duplo clique para voltar</span></div><div class="sr-only" id="srSummary" aria-live="polite"></div></section><div class="reading" id="reading">—</div><div class="source-links"><a id="metricsLink" href="#">métricas</a><a id="seriesLink" href="#">série</a><a id="manifestLink" href="#">manifesto do pacote</a></div></section>
<section class="panel map-panel"><div class="map-top"><div><strong id="mapTitle">—</strong><div class="small muted" id="mapSubtitle">—</div></div><span class="pill" id="mapStatus">—</span></div><div class="map-viewport" id="mapViewport"><div class="map-content" id="mapContent"><img class="map-bg" id="mapBg" alt="Fundo visual do MDT do município"><svg class="map-svg" id="mapSvg" viewBox="0 0 1000 1000" role="img" aria-label="Mapa espacial interativo"></svg></div><div class="map-badge" id="mapBadge">—</div><div class="map-controls"><button class="button" id="mapZoomIn" type="button" aria-label="Aumentar mapa">+</button><button class="button" id="mapZoomOut" type="button" aria-label="Reduzir mapa">−</button><button class="button" id="mapReset" type="button">Enquadrar</button></div><div class="north">N ↑</div></div><div class="map-legend"><span><i class="legend-swatch swatch-flood"></i>contorno selecionado</span><span><i class="legend-swatch swatch-grid"></i>grade 200 m</span><span><i class="legend-swatch swatch-shelter"></i>abrigo cadastrado</span><span><i class="legend-swatch swatch-fire"></i>bombeiros</span><span><i class="legend-swatch swatch-health"></i>saúde</span><span><i class="legend-swatch swatch-school"></i>escola</span></div><div class="cell-info" id="cellInfo"><strong>Explore a grade</strong><p>Clique em uma célula de 200 m para abrir a população agregada e a completude do dado. A grade não representa endereços individuais.</p></div><div class="spatial-note" id="spatialNote">—</div></section></div>
<section class="panel all-events"><div class="event-head"><div><h2>Catálogo completo de replays</h2><div class="muted">Clique em qualquer linha para trocar o evento aberto. Diagnóstico não vira calibração por aparecer na mesma tabela.</div></div><span class="pill" id="tableScope">27 eventos</span></div><div class="table-wrap"><table class="events-table"><thead><tr><th>Evento</th><th>Município</th><th>Modelo</th><th>Período</th><th>Pico obs.</th><th>Pico modelo</th><th>Erro</th><th>Status</th></tr></thead><tbody id="eventRows"></tbody></table></div></section>
<div class="foot-grid"><section class="panel"><h2>O que melhorou nesta sala</h2><p>Um seletor reúne 6 eventos HEC-HMS de Muçum e 21 eventos RNA de Santa Tereza.</p><p>O mapa usa um fundo de MDT visual, contorno do nível escolhido, grade 200 m clicável e pontos de apoio locais.</p><p>O nível espacial é escolhido explicitamente; ele não é convertido automaticamente a partir do pico do gráfico.</p></section><section class="panel"><h2>Fontes e limites</h2><p><a href="../assets/data/research_event_replay_latest.json">Manifesto espacial auditável</a> · <a href="../pesquisas/sala-integrada-eventos.html">sala integrada anterior</a></p><p><a href="../assets/data/mucum_eventwise_replay_calibrated/index.html">visualizador HEC-HMS de Muçum</a> · <a href="../assets/data/santa_tereza_eventwise_replay_rna_2h/santa_tereza_event_replay.html">visualizador RNA de Santa Tereza</a></p><p>O MDT e as manchas são visualizações de pesquisa. O próprio manifesto registra pendência de datum/CRS vertical e, em Santa Tereza, não há cenário publicado acima de 15 m nesta fonte.</p></section></div>
</section></main>
<script>
const DATA=__DATA__;
const $=id=>document.getElementById(id),canvas=$("chart"),ctx=canvas.getContext("2d"),tip=$("tip");
const fmt0=new Intl.NumberFormat("pt-BR",{maximumFractionDigits:0}),fmt1=new Intl.NumberFormat("pt-BR",{minimumFractionDigits:1,maximumFractionDigits:1}),fmt2=new Intl.NumberFormat("pt-BR",{minimumFractionDigits:2,maximumFractionDigits:2});
const dateFmt=new Intl.DateTimeFormat("pt-BR",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
const state={key:"mucum-E24",start:0,end:0,hover:null,dragStart:null,dragCurrent:null,city:"all",selectedCell:null,map:{scale:1,tx:0,ty:0,drag:false,lastX:0,lastY:0}};
function eventByKey(k){return DATA.events.find(e=>e.key===k)||DATA.events[0]}
function current(){return eventByKey(state.key)}
function city(){return DATA.spatial[current().city_key]}
function finite(v){return Number.isFinite(Number(v))?Number(v):null}
function dt(v){return new Date(String(v).replace(" ","T"))}
function levelKey(v){return String(Number(v))}
function niceStatus(e){return e.status}
function statusClass(e){return e.status.includes("independente")?"pill test":e.status==="fechado"?"pill":"pill warn"}
function populateEvents(){const select=$("eventSelect"),old=state.key;select.innerHTML="";const groups={};for(const e of DATA.events){if(state.city!=="all"&&e.city_key!==state.city)continue;(groups[e.municipality]??= []).push(e)}for(const [label,events] of Object.entries(groups)){const group=document.createElement("optgroup");group.label=label;for(const e of events){const o=document.createElement("option");o.value=e.key;o.textContent=`${e.id} · ${e.period.split(" ")[0]} · ${e.model}`;group.append(o)}select.append(group)}if([...select.options].some(o=>o.value===old)){select.value=old}else{state.key=select.options[0]?.value||DATA.events[0].key;select.value=state.key}state.start=0;state.end=Math.max(0,current().series.length-1)}
function renderSummary(){const mucum=DATA.events.filter(e=>e.city_key==="mucum"),santa=DATA.events.filter(e=>e.city_key==="santa_tereza");$("totalEvents").textContent=fmt0.format(DATA.events.length);$("mucumEvents").textContent=fmt0.format(mucum.length);$("santaEvents").textContent=fmt0.format(santa.length);$("independentEvents").textContent=fmt0.format(DATA.events.filter(e=>e.status.includes("independente")).length)}
function renderEvent(){const e=current(),m=e.metrics;$('eventTitle').textContent=`${e.municipality} · ${e.id}`;$('eventSubtitle').textContent=`${e.period} · ${e.variable} · ${e.series.length} pontos`;const st=$("eventStatus");st.textContent=niceStatus(e);st.className=statusClass(e);$('obsPeak').textContent=e.unit==="cm"?fmt1.format(m.observed_peak):fmt1.format(m.observed_peak);$('modelPeak').textContent=fmt1.format(m.model_peak);$('unitObs').textContent=e.unit;$('unitModel').textContent=e.unit;$('peakError').textContent=m.peak_error==null?"—":fmt2.format(m.peak_error*100)+"%";$('peakLag').textContent=m.lag==null?"—":(m.lag>0?"+":"")+fmt1.format(m.lag)+" h";$('pairs').textContent=fmt0.format(m.pairs||e.series.length);if(m.nse!=null){$('fitMetric').textContent=fmt2.format(m.nse);$('fitLabel').textContent="NSE"}else{$('fitMetric').textContent=m.mae==null?"—":fmt1.format(m.mae);$('fitLabel').textContent="MAE · "+e.unit}$('chartTitle').textContent=`${e.id} · observado × ${e.model}`;$('modelLegend').textContent=e.model;$('peakDates').textContent=`Picos: observado ${peakDate(e,1)} · modelo ${peakDate(e,2)}`;$('reading').textContent=e.city_key==="mucum"?(e.status==="fechado"?"Replay fechado no pacote de pesquisa. Compare forma, pico e horário; o conjunto ainda usa uma bacia agregada e não uma delineação hidrológica completa derivada do MDT.":"Diagnóstico preservado para mostrar o que ainda precisa melhorar: há lacuna ou subestimação no evento e ele não foi promovido."):e.status.includes("independente")?"Teste independente da rotação RNA: a comparação está separada do treino e serve para avaliar generalização do replay de nível.":"Replay de nível da RNA: útil para estudar forma, pico e atraso, mas não é calibração HEC-HMS de vazão.";$('metricsLink').href=hrefFor(e.metrics_source);$('seriesLink').href=hrefFor(e.series_source);$('manifestLink').href=e.city_key==="mucum"?"../assets/data/mucum_eventwise_replay_calibrated/eventwise_manifest.json":"../assets/data/santa_tereza_eventwise_replay_rna_2h/eventwise_manifest.json";state.start=0;state.end=Math.max(0,e.series.length-1);renderMap();renderEventsTable();draw()}
function hrefFor(path){return "../"+path}
function peakDate(e,col){if(!e.series.length)return "—";let idx=0;for(let i=1;i<e.series.length;i++)if(e.series[i][col]>e.series[idx][col])idx=i;return dateFmt.format(dt(e.series[idx][0]))}
function sourceLink(path){return hrefFor(path)}
function projectPoint(lon,lat,c){const b=c.bounds;return {x:(lon-b.west)/(b.east-b.west)*1000,y:(b.north-lat)/(b.north-b.south)*1000}}
function geometryPath(g,c){const rings=g.type==="Polygon"?g.coordinates:g.coordinates.flat();return rings.map(r=>r.map((p,i)=>{const q=projectPoint(p[0],p[1],c);return `${i?"L":"M"}${q.x.toFixed(2)},${q.y.toFixed(2)}`}).join(" ")+" Z").join(" ")}
function svgEl(tag,attrs={}){const el=document.createElementNS("http://www.w3.org/2000/svg",tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,String(v));return el}
function renderMap(){const c=city();$("mapTitle").textContent=`${c.label} · cenário espacial`;$("mapSubtitle").textContent=`${c.background_label} · ${c.crs} · fonte do contorno: ${c.contour_source.split("/").pop()}`;$("mapBg").src=c.background;$("mapBg").alt=`${c.label}: ${c.background_label}`;const range=$("levelRange");range.min=c.level_min;range.max=c.level_max;range.value=Math.min(Number(range.value),c.level_max);if(current().city_key!==state.city&&state.city!=="all"){range.value=c.city_key}$("levelValue").textContent=fmt1.format(Number(range.value))+" m";const selected=Number(range.value),contour=c.contours.find(x=>x.level===selected)||c.contours[c.contours.length-1];const svg=$("mapSvg");svg.innerHTML="";const gridGroup=svgEl("g",{"aria-label":"grade estatística de 200 metros"});for(const cell of c.grid){const path=svgEl("path",{d:geometryPath(cell.geometry,c),class:"grid-cell",tabindex:0,"aria-label":`Célula ${cell.id||"sem ID"}`});path.dataset.cell=cell.id||"";path.addEventListener("click",()=>selectCell(cell));path.addEventListener("keydown",ev=>{if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();selectCell(cell)}});gridGroup.append(path)}svg.append(gridGroup);if(contour){const flood=svgEl("path",{d:geometryPath(contour.geometry,c),class:"flood",role:"img","aria-label":`Contorno de cota ${contour.level} metros`});svg.append(flood)}const pointsGroup=svgEl("g",{"aria-label":"pontos de apoio"});for(const p of c.points){if(p.lon==null||p.lat==null)continue;const q=projectPoint(p.lon,p.lat,c),kind=p.kind.toLowerCase();let cls=kind.includes("abrigo")?"shelter":kind.includes("bombeiro")?"fire":kind.includes("saúde")||kind.includes("hospital")?"health":"school";const circle=svgEl("circle",{cx:q.x,cy:q.y,r:7,class:`service ${cls}`,tabindex:0,"aria-label":`${p.kind}: ${p.name}`});circle.addEventListener("click",()=>showPoint(p));pointsGroup.append(circle);if(window.innerWidth>760){const label=svgEl("text",{x:q.x+10,y:q.y+4,class:"service-label"});label.textContent=p.name.length>28?p.name.slice(0,27)+"…":p.name;pointsGroup.append(label)}}svg.append(pointsGroup);const pub=c.published[levelKey(selected)];const badge=$("mapBadge");if(pub){badge.innerHTML=`<strong>cenário publicado · ${fmt1.format(selected)} m</strong>${fmt1.format(pub.contour_area_ha)} ha · ${fmt0.format(pub.cells_200m_touched)} células 200 m · população tocada: até ${fmt0.format(pub.population_upper_bound_whole_touched_cells)} (limite superior)`}else{badge.innerHTML=`<strong>contorno de referência · ${fmt1.format(selected)} m</strong>Esta cota tem geometria disponível, mas não possui métricas agregadas publicadas no manifesto.`}const mapStatus=$("mapStatus");mapStatus.textContent=c.higher_than_published_status?`faixa publicada: 0–${c.level_max} m`:`faixa publicada: 0–${c.level_max} m`;mapStatus.className="pill warn";$("spatialNote").textContent=c.label==="Santa Tereza"&&c.higher_than_published_status?`A fonte atual não publica cenário acima de ${c.level_max} m. O MDT refinado está marcado como visualização, pendente de validação independente; não extrapole a mancha.`:`Datum/CRS vertical e reconciliação régua → HAND ainda estão pendentes. A camada ajuda a comparar cenários, não define rota nem área evacuável.`;state.selectedCell=null;$("cellInfo").innerHTML="<strong>Explore a grade</strong><p>Clique em uma célula de 200 m para abrir a população agregada e a completude do dado. A grade não representa endereços individuais.</p>";applyMapTransform();}
function selectCell(cell){state.selectedCell=cell;document.querySelectorAll(".grid-cell").forEach(el=>el.classList.toggle("selected",el.dataset.cell===(cell.id||"")));const pop=cell.pop==null?"sem valor":fmt0.format(cell.pop);const dom=cell.dom==null?"sem valor":fmt0.format(cell.dom);$("cellInfo").innerHTML=`<strong>${cell.id||"Célula sem ID"}</strong><p>População agregada: <b>${pop}</b> · domicílios: <b>${dom}</b> · completude pop.: <b>${cell.pop_completude||"não informada"}</b>. Isso é dado agregado de grade, não cadastro de pessoas.</p>`}
function showPoint(p){$("cellInfo").innerHTML=`<strong>${p.kind}: ${p.name}</strong><p>Ponto cadastrado na camada <b>${p.source.split("/").pop()}</b>. A presença no mapa não confirma abertura, capacidade, acessibilidade, rota ou disponibilidade durante um evento.</p>`}
function renderEventsTable(){const rows=$("eventRows");rows.innerHTML="";const list=state.city==="all"?DATA.events:DATA.events.filter(e=>e.city_key===state.city);$("tableScope").textContent=`${list.length} evento${list.length===1?"":"s"}`;for(const e of list){const tr=document.createElement("tr");if(e.key===state.key)tr.className="selected";tr.addEventListener("click",()=>{state.key=e.key;$("eventSelect").value=e.key;renderEvent()});const m=e.metrics;tr.innerHTML=`<td><button class="event-button" type="button">${e.municipality} · ${e.id}</button></td><td>${e.municipality}</td><td>${e.model}</td><td>${e.period.split(" → ")[0]}</td><td>${m.observed_peak==null?"—":fmt1.format(m.observed_peak)} ${e.unit}</td><td>${m.model_peak==null?"—":fmt1.format(m.model_peak)} ${e.unit}</td><td>${m.peak_error==null?"—":fmt2.format(m.peak_error*100)+"%"}</td><td><span class="tiny-pill ${e.status.includes("independente")?"test":e.status==="fechado"?"":"warn"}">${e.status}</span></td>`;rows.append(tr)}}
function bounds(){const e=current(),s=e.series.slice(state.start,state.end+1);let ys=[];if($("showObserved").checked)ys=ys.concat(s.map(x=>x[1]));if($("showModel").checked)ys=ys.concat(s.map(x=>x[2]));if(!ys.length)ys=[0,1];const lo=Math.min(0,...ys),hi=Math.max(...ys);return {lo,hi:hi+(hi-lo)*.08||1}}
function resize(){const r=canvas.getBoundingClientRect(),d=window.devicePixelRatio||1,w=Math.max(1,Math.round(r.width*d)),h=Math.max(1,Math.round(r.height*d));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h}ctx.setTransform(d,0,0,d,0,0);draw()}
function draw(){const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;ctx.clearRect(0,0,w,h);const pad={l:57,r:12,t:18,b:38},pw=w-pad.l-pad.r,ph=h-pad.t-pad.b,e=current(),s=e.series.slice(state.start,state.end+1),b=bounds(),x=i=>pad.l+(i/Math.max(1,s.length-1))*pw,y=v=>pad.t+(b.hi-v)/(b.hi-b.lo)*ph;ctx.font="11px system-ui";ctx.lineWidth=1;for(let g=0;g<=4;g++){const yy=pad.t+ph*g/4;ctx.strokeStyle="#dcebed";ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(w-pad.r,yy);ctx.stroke();ctx.fillStyle="#607681";ctx.fillText(fmt0.format(b.hi-(b.hi-b.lo)*g/4),7,yy+4)}const ticks=Math.min(6,Math.max(2,Math.floor(pw/120)));for(let k=0;k<=ticks;k++){const i=Math.round((s.length-1)*k/ticks),xx=x(i);ctx.strokeStyle="#e8f0f1";ctx.beginPath();ctx.moveTo(xx,pad.t);ctx.lineTo(xx,pad.t+ph);ctx.stroke();ctx.fillStyle="#607681";ctx.fillText(dateFmt.format(dt(s[i][0])),Math.max(pad.l,xx-32),h-13)}function line(color,col){if(!s.length)return;ctx.beginPath();s.forEach((p,i)=>{const xx=x(i),yy=y(p[col]);if(i===0)ctx.moveTo(xx,yy);else ctx.lineTo(xx,yy)});ctx.strokeStyle=color;ctx.lineWidth=2.5;ctx.lineJoin="round";ctx.lineCap="round";ctx.stroke()}if($("showObserved").checked)line("#0879c9",1);if($("showModel").checked)line("#ed7a2a",2);if(state.dragStart!==null&&state.dragCurrent!==null){const a=Math.min(state.dragStart,state.dragCurrent),z=Math.max(state.dragStart,state.dragCurrent);ctx.fillStyle="#0879c922";ctx.fillRect(a,pad.t,z-a,ph);ctx.strokeStyle="#0879c9";ctx.strokeRect(a,pad.t,z-a,ph)}if(state.hover!==null&&s[state.hover]){const p=s[state.hover],xx=x(state.hover),y1=y(p[1]),y2=y(p[2]);ctx.strokeStyle="#153d4880";ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(xx,pad.t);ctx.lineTo(xx,pad.t+ph);ctx.stroke();ctx.setLineDash([]);if($("showObserved").checked){ctx.fillStyle="#0879c9";ctx.beginPath();ctx.arc(xx,y1,4,0,Math.PI*2);ctx.fill()}if($("showModel").checked){ctx.fillStyle="#ed7a2a";ctx.beginPath();ctx.arc(xx,y2,4,0,Math.PI*2);ctx.fill()}showTip(p,xx,y1,y2,w,h)}else tip.style.display="none";$("rangeText").textContent=s.length?`${dateFmt.format(dt(s[0][0]))} → ${dateFmt.format(dt(s[s.length-1][0]))} · ${s.length} pontos exibidos`:"sem série"}
function showTip(p,xx,y1,y2,w,h){const e=current(),left=Math.min(Math.max(8,xx+12),w-205),top=Math.min(Math.max(8,Math.min(y1,y2)-66),h-100);tip.style.left=left+"px";tip.style.top=top+"px";tip.innerHTML=`<strong>${dateFmt.format(dt(p[0]))}</strong><div style="color:#9ed8ff">observado: ${fmt1.format(p[1])} ${e.unit}</div><div style="color:#ffc297">${e.model}: ${fmt1.format(p[2])} ${e.unit}</div><div>diferença: ${fmt1.format(p[2]-p[1])} ${e.unit}</div>`;tip.style.display="block"}
function indexAt(clientX){const r=canvas.getBoundingClientRect(),w=canvas.clientWidth,pl=57,pr=12,px=Math.max(pl,Math.min(w-pr,clientX-r.left)),n=state.end-state.start+1;return Math.round((px-pl)/(w-pl-pr)*Math.max(0,n-1))}
canvas.addEventListener("pointermove",ev=>{const i=indexAt(ev.clientX);if(state.dragStart!==null){state.dragCurrent=ev.clientX-canvas.getBoundingClientRect().left;draw()}else{state.hover=i;draw()}});canvas.addEventListener("pointerleave",()=>{if(state.dragStart===null){state.hover=null;draw()}});canvas.addEventListener("pointerdown",ev=>{state.dragStart=ev.clientX-canvas.getBoundingClientRect().left;state.dragCurrent=state.dragStart;canvas.setPointerCapture(ev.pointerId)});canvas.addEventListener("pointerup",ev=>{if(state.dragStart===null)return;const r=canvas.getBoundingClientRect(),a=Math.min(state.dragStart,state.dragCurrent),z=Math.max(state.dragStart,state.dragCurrent),w=canvas.clientWidth,pl=57,pr=12;if(Math.abs(z-a)>18){const n=current().series.length,oldN=state.end-state.start+1,ia=Math.round((a-pl)/(w-pl-pr)*Math.max(0,oldN-1)),ib=Math.round((z-pl)/(w-pl-pr)*Math.max(0,oldN-1));state.start=Math.max(0,state.start+Math.min(ia,ib));state.end=Math.min(n-1,state.start+Math.max(ia,ib))}state.dragStart=null;state.dragCurrent=null;draw();try{canvas.releasePointerCapture(ev.pointerId)}catch{}});canvas.addEventListener("dblclick",()=>$("resetZoom").click());
function applyMapTransform(){$("mapContent").style.transform=`translate(${state.map.tx}px,${state.map.ty}px) scale(${state.map.scale})`}
$("mapZoomIn").addEventListener("click",()=>{state.map.scale=Math.min(4,state.map.scale*1.25);applyMapTransform()});$("mapZoomOut").addEventListener("click",()=>{state.map.scale=Math.max(1,state.map.scale/1.25);if(state.map.scale===1){state.map.tx=0;state.map.ty=0}applyMapTransform()});$("mapReset").addEventListener("click",()=>{state.map={scale:1,tx:0,ty:0,drag:false,lastX:0,lastY:0};applyMapTransform()});const viewport=$("mapViewport");viewport.addEventListener("pointerdown",ev=>{if(ev.target.closest("button")||ev.target.closest("path")||ev.target.closest("circle"))return;state.map.drag=true;state.map.lastX=ev.clientX;state.map.lastY=ev.clientY;viewport.setPointerCapture(ev.pointerId)});viewport.addEventListener("pointermove",ev=>{if(!state.map.drag)return;state.map.tx+=ev.clientX-state.map.lastX;state.map.ty+=ev.clientY-state.map.lastY;state.map.lastX=ev.clientX;state.map.lastY=ev.clientY;applyMapTransform()});viewport.addEventListener("pointerup",()=>{state.map.drag=false});viewport.addEventListener("pointercancel",()=>{state.map.drag=false});
$("citySelect").addEventListener("change",()=>{state.city=$("citySelect").value;populateEvents();renderEvent()});$("eventSelect").addEventListener("change",()=>{state.key=$("eventSelect").value;renderEvent()});$("showObserved").addEventListener("change",draw);$("showModel").addEventListener("change",draw);$("resetZoom").addEventListener("click",()=>{state.start=0;state.end=current().series.length-1;draw()});$("levelRange").addEventListener("input",()=>{$("levelValue").textContent=fmt1.format(Number($("levelRange").value))+" m";renderMap()});window.addEventListener("resize",resize);
renderSummary();populateEvents();$("eventSelect").value=state.key;renderEvent();resize();
</script></body></html>'''


def main() -> None:
    payload = {
        "events": mucum_events() + santa_events(),
        "spatial": spatial_data(),
    }
    output = ROOT / "pesquisas" / "replay-hidrologico-espacial.html"
    output.write_text(HTML.replace("__DATA__", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))), encoding="utf-8")
    print(f"wrote {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
