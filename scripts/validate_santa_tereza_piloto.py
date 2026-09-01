"""Audita os insumos do piloto visual de Santa Tereza sem promover o protótipo.

O relatório confirma presença e coerência estrutural dos arquivos. Não certifica
abrigo, ponte, rota, capacidade, atualidade hidrológica ou segurança de campo.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def embedded_map_data(path: Path):
    text = path.read_text(encoding="utf-8")
    marker = "const D="
    start = text.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data


def main() -> int:
    html = ROOT / "pesquisas" / "santa-tereza-rota-fuga-ruas.html"
    route_source = ROOT / "assets" / "data" / "rota_fuga_santa_tereza.json"
    flood_source = ROOT / "assets" / "data" / "santa_tereza_inundacao" / "mancha_preliminar_santa_tereza.geojson"
    shelter_source = ROOT / "assets" / "data" / "servicos" / "abrigos.geojson"

    data = embedded_map_data(html)
    route = read_json(route_source)
    flood = read_json(flood_source)
    shelters = read_json(shelter_source)
    shelter_features = shelters.get("features", [])
    route_meta = route.get("meta", {})
    issues = []

    if not data.get("nos") or not data.get("edges"):
        issues.append("rede embutida sem nós ou arestas")
    if not route.get("quadras"):
        issues.append("fonte da grade sem quadras")
    if not flood.get("features"):
        issues.append("mancha preliminar sem feições")
    if not shelter_features:
        issues.append("nenhum ponto de referência cadastrado")
    if any("capacidade" in (feature.get("properties") or {}) for feature in shelter_features):
        issues.append("capacidade encontrada: revisar antes de exibir como capacidade atual")

    raw_hydrology_label = data.get("meta", {}).get("nivel", {}).get("rotulo")
    report = {
        "schema_version": 1,
        "municipio": "Santa Tereza",
        "status": "PASS_WITH_KNOWN_LIMITS" if not issues else "DEGRADED",
        "research_only": True,
        "official_alert": False,
        "operational_gate": "blocked",
        "generated_from": {
            "map_html": str(html.relative_to(ROOT)),
            "route_source": str(route_source.relative_to(ROOT)),
            "flood_source": str(flood_source.relative_to(ROOT)),
            "reference_source": str(shelter_source.relative_to(ROOT)),
        },
        "counts": {
            "route_nodes": len(data.get("nos", [])),
            "route_edges": len(data.get("edges", [])),
            "grid_cells": len(route.get("quadras", [])),
            "flood_features": len(flood.get("features", [])),
            "shelters": len(shelter_features),
        },
        "source_snapshot": {
            "map_generated_at": data.get("meta", {}).get("gerado_em"),
            "route_source_generated_at": route_meta.get("gerado_em"),
            "raw_hydrology_label": raw_hydrology_label,
            "hydrology_label_in_page": "captura histórica / RNA experimental",
            "hydrology_label_normalized": raw_hydrology_label == "previsão ao vivo (RNA 2h/4h)",
            "hydrology_timestamp": data.get("meta", {}).get("nivel", {}).get("telemetria_em"),
            "reference_status": "capacity_and_current_opening_unknown",
            "flood_status": "preliminary_visual_proxy",
        },
        "known_limits": [
            "a captura hidrológica embutida é histórica/atrasada e não é entrada operacional",
            "a mancha preliminar é uma camada visual de pesquisa, não uma cota oficial",
            "imagem aérea e OSM não certificam estrutura, passagem, bloqueio ou segurança de ponte",
            "o ponto de encontro não tem capacidade, vagas, abertura ou responsável atual publicados",
            "população, acessibilidade, transporte, animais e necessidades específicas não estão inferidos",
        ],
        "issues": issues,
        "summary": "Estrutura suficiente para estudar o fluxo localizar → dimensionar grupo → conferir em campo; gate operacional permanece bloqueado.",
    }
    output = ROOT / "assets" / "data" / "santa_tereza_piloto_qa_latest.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SANTA_TEREZA_PILOTO_QA={report['status']} issues={len(issues)}")
    print(json.dumps(report["counts"], ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS_WITH_KNOWN_LIMITS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
