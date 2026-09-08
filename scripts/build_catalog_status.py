#!/usr/bin/env python3
"""Build the compact status manifest shown by the research catalogue.

The catalogue contains several valid, but different, grains of information:
qualified RNA models, historical training rounds, HTML research pages,
event replays and spatial/HEC-HMS gates. This script keeps those counts in a
single source-linked artifact so the UI cannot present them as one number.

This is a research inventory. It never promotes an RNA, spatial scenario or
HEC-HMS result to an operational product.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "data" / "research_catalog_status_latest.json"
INDEX = ROOT / "index.html"
CATALOGUE = ROOT / "pesquisas.html"
ROUNDS = ROOT / "assets" / "data" / "rodadas_realizadas.json"
EVENT_REPLAY = ROOT / "assets" / "data" / "research_event_replay_latest.json"
QUALITY = ROOT / "assets" / "data" / "research_dashboard_validation_latest.json"
BASIN_SCREENING = ROOT / "assets" / "data" / "research_basin_screening_latest.json"
HEC_STATUS = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "network_calibration_status_latest.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def embedded_json(text: str, script_id: str) -> dict[str, Any]:
    pattern = re.compile(
        rf'<script\s+id="{re.escape(script_id)}"\s+type="application/json">(.*?)</script>',
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        raise ValueError(f"JSON embutido não encontrado: {script_id}")
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ValueError(f"JSON embutido inválido: {script_id}")
    return value


def model_summary() -> dict[str, Any]:
    index_text = INDEX.read_text(encoding="utf-8")
    santa = embedded_json(index_text, "data")
    mucum = embedded_json(index_text, "data-mucum")
    city_data = {"santa_tereza": santa, "mucum": mucum}
    by_city: dict[str, Any] = {}
    total_types: Counter[str] = Counter()
    total_horizons: Counter[str] = Counter()
    for city, value in city_data.items():
        models = value.get("models") if isinstance(value.get("models"), list) else []
        types = Counter(str(item.get("tipo")) for item in models if item.get("tipo"))
        horizons = Counter(str(item.get("horizonte")) for item in models if item.get("horizonte"))
        total_types.update(types)
        total_horizons.update(horizons)
        filter_info = value.get("positivePersFilter") if isinstance(value.get("positivePersFilter"), dict) else {}
        by_city[city] = {
            "qualified_models": len(models),
            "original_models": filter_info.get("originalModelCount", len(models)),
            "types": dict(sorted(types.items())),
            "horizons": dict(sorted(horizons.items())),
            "qualification_rule": filter_info.get("rule"),
            "source": f"{rel(INDEX)}#{'data-mucum' if city == 'mucum' else 'data'}",
        }
    return {
        "qualified_total": sum(item["qualified_models"] for item in by_city.values()),
        "types": dict(sorted(total_types.items())),
        "horizons": dict(sorted(total_horizons.items())),
        "by_city": by_city,
        "definition": "Modelos presentes nos recortes atuais do feed com persistência positiva nos recortes declarados pela ficha de cada cidade.",
    }


def round_summary() -> dict[str, Any]:
    value = read_json(ROUNDS)
    cities = value.get("cidades") if isinstance(value.get("cidades"), dict) else {}
    by_city: dict[str, Any] = {}
    all_days: set[str] = set()
    total_folders = 0
    for city in ("santa_tereza", "mucum"):
        item = cities.get(city) if isinstance(cities.get(city), dict) else {}
        days = [str(day) for day in item.get("dias", []) if day]
        folders = item.get("pastas") if isinstance(item.get("pastas"), list) else []
        all_days.update(days)
        total_folders += len(folders)
        by_city[city] = {
            "round_folders": len(folders),
            "distinct_days": len(set(days)),
            "source_generated_at": value.get("gerado_em"),
        }
    return {
        "round_folders": total_folders,
        "distinct_days": len(all_days),
        "by_city": by_city,
        "source_generated_at": value.get("gerado_em"),
        "definition": str(value.get("fonte", "")),
    }


def catalogue_summary() -> dict[str, Any]:
    text = CATALOGUE.read_text(encoding="utf-8")
    start = text.find("const entries = [")
    end = text.find("\n    ];", start)
    if start < 0 or end < 0:
        raise ValueError("array de entradas do catálogo não encontrado")
    entry_count = len(re.findall(r"\{\s*title\s*:", text[start:end]))
    html_count = sum(1 for path in ROOT.rglob("*.html") if path.is_file())
    return {
        "catalogue_entries": entry_count,
        "html_pages_in_worktree": html_count,
        "source": rel(CATALOGUE),
        "definition": "Entradas são páginas distintas indexadas pelo catálogo; a contagem não é a quantidade de modelos nem de rodadas.",
    }


def event_summary() -> dict[str, Any]:
    value = read_json(EVENT_REPLAY)
    municipality_catalogs = value.get("municipality_catalogs") if isinstance(value.get("municipality_catalogs"), dict) else {}
    replay_cases = value.get("replay_cases") if isinstance(value.get("replay_cases"), list) else []
    st = municipality_catalogs.get("santa_tereza") if isinstance(municipality_catalogs.get("santa_tereza"), dict) else {}
    muc = municipality_catalogs.get("mucum") if isinstance(municipality_catalogs.get("mucum"), dict) else {}
    return {
        "published_replay_cases": len(replay_cases),
        "catalog_events": {
            "mucum": muc.get("event_count_catalog"),
            "mucum_q62_used": muc.get("q62_used_event_count"),
            "santa_tereza": st.get("event_count_catalog"),
        },
        "santa_tereza_8h_12h_status": st.get("eight_or_twelve_hour_replay_status"),
        "operational_gate": value.get("operational_gate"),
        "research_only": value.get("research_only") is True,
        "source": rel(EVENT_REPLAY),
    }


def spatial_summary() -> dict[str, Any]:
    value = read_json(EVENT_REPLAY)
    scenarios = value.get("spatial_scenarios") if isinstance(value.get("spatial_scenarios"), dict) else {}
    output: dict[str, Any] = {}
    for city in ("mucum", "santa_tereza"):
        item = scenarios.get(city) if isinstance(scenarios.get(city), dict) else {}
        rows = item.get("scenarios") if isinstance(item.get("scenarios"), list) else []
        output[city] = {
            "published_level_range_m": item.get("published_level_range_m"),
            "scenario_levels_m": [row.get("level_m") for row in rows if isinstance(row, dict)],
            "stage_conversion_status": item.get("stage_conversion_status"),
            "higher_than_published_status": item.get("higher_than_published_status"),
            "source": item.get("contour_source"),
        }
    return {
        "by_city": output,
        "definition": "Cenários espaciais publicados no arquivo de contornos; não são conversão automática de cota de régua nem mancha operacional.",
    }


def quality_summary() -> dict[str, Any]:
    value = read_json(QUALITY)
    issues = value.get("issues") if isinstance(value.get("issues"), list) else []
    issue_rows = []
    for item in issues:
        if not isinstance(item, dict):
            continue
        issue_rows.append(
            {
                "code": item.get("code"),
                "severity": item.get("severity"),
                "location": item.get("location"),
                "detail": item.get("detail"),
            }
        )
    basin = read_json(BASIN_SCREENING)
    gates = basin.get("gates") if isinstance(basin.get("gates"), list) else []
    gate_rows = [
        {"id": item.get("id"), "status": item.get("status"), "reason": item.get("reason")}
        for item in gates
        if isinstance(item, dict)
    ]
    return {
        "status": value.get("status"),
        "checked_reference_utc": value.get("checked_reference_utc"),
        "issues": issue_rows,
        "basin_screening_status": basin.get("status"),
        "basin_screening_generated_at_utc": basin.get("generated_at_utc"),
        "basin_gates": gate_rows,
        "source": rel(QUALITY),
        "basin_source": rel(BASIN_SCREENING),
    }


def hec_summary() -> dict[str, Any]:
    value = read_json(HEC_STATUS)
    event_replay = value.get("event_replay") if isinstance(value.get("event_replay"), dict) else {}
    events = event_replay.get("events") if isinstance(event_replay.get("events"), list) else []
    input_gate = value.get("calibration_input_gate") if isinstance(value.get("calibration_input_gate"), dict) else {}
    eligible = input_gate.get("eligible_sets") if isinstance(input_gate.get("eligible_sets"), dict) else {}
    complete = eligible.get("three_incremental_areas_complete_events")
    if not isinstance(complete, list):
        complete = []
    gates = value.get("gates") if isinstance(value.get("gates"), dict) else {}
    return {
        "overall_status": value.get("overall_status"),
        "scope": (value.get("network") or {}).get("scope"),
        "representation": (value.get("network") or {}).get("representation"),
        "scored_event_count": len(events),
        "complete_three_incremental_area_events": complete,
        "operational_promotion_gate": gates.get("operational_promotion"),
        "source": rel(HEC_STATUS),
        "definition": "Replay HEC-HMS diagnóstico no corredor BHO6; não é a discretização integral da bacia Taquari–Antas.",
    }


def response_summary() -> dict[str, Any]:
    value = read_json(EVENT_REPLAY)
    inventory = value.get("response_inventory") if isinstance(value.get("response_inventory"), dict) else {}
    output: dict[str, Any] = {}
    for city in ("mucum", "santa_tereza"):
        item = inventory.get(city) if isinstance(inventory.get(city), dict) else {}
        output[city] = {
            "shelters_count": item.get("shelters_count"),
            "routes_in_plan_count": item.get("routes_in_plan_count"),
            "bridges_in_plan_count": item.get("bridges_in_plan_count"),
            "capacity_reconciliation_status": item.get("capacity_reconciliation_status"),
            "current_occupancy_status": item.get("current_occupancy_status"),
            "route_traversability_status": item.get("route_traversability_status"),
            "operational_gate": item.get("operational_gate"),
        }
    return {
        "by_city": output,
        "definition": "Inventário documental para exercício; capacidade atual, ocupação, travessia e liberação de rota permanecem separadas.",
    }


def main() -> int:
    report = {
        "schema_version": "previne_research_catalog_status_v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "research_only": True,
        "official_alert": False,
        "purpose": "Inventário consolidado do acervo de pesquisa do PREVINE; não é alerta, ordem de evacuação, rota liberada ou despacho.",
        "models": model_summary(),
        "rounds": round_summary(),
        "catalogue": catalogue_summary(),
        "events": event_summary(),
        "spatial": spatial_summary(),
        "data_quality": quality_summary(),
        "hec_hms": hec_summary(),
        "response": response_summary(),
        "sources": [
            rel(INDEX),
            rel(CATALOGUE),
            rel(ROUNDS),
            rel(EVENT_REPLAY),
            rel(QUALITY),
            rel(BASIN_SCREENING),
            rel(HEC_STATUS),
        ],
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {rel(OUTPUT)}")
    print(f"models={report['models']['qualified_total']} rounds={report['rounds']['round_folders']} pages={report['catalogue']['catalogue_entries']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
