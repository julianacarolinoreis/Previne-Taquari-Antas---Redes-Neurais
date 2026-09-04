#!/usr/bin/env python3
"""Build a compact, source-linked status report for the nested HEC-HMS study."""

from __future__ import annotations

import json
import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas"
OUT = BASE / "network_calibration_status_latest.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def event_status(event_id: str, metric: dict) -> str:
    if event_id == "E19":
        return "pendente: atraso e forma do hidrograma ainda não explicados"
    if event_id == "E22":
        return "pendente: pico subestimado; chuva/perdas ainda não reconciliadas"
    if event_id == "E24":
        return "bom ajuste deste evento; não promovido para uso comum"
    if event_id == "E27":
        return "ajuste intermediário; 2 h de atraso e viés de pico"
    if event_id == "E28":
        return "bom ajuste deste evento; não promovido para uso comum"
    return metric.get("status", "não classificado")


def main() -> int:
    audit = read_json(BASE / "network_audit_latest.json")
    terrain = read_json(BASE / "reach_terrain_metrics_latest.json")
    replay = read_json(BASE / "network_replay_eventwise_candidate_all_events" / "network_metrics_all_events.json")
    e19_search = read_json(BASE / "parameter_search_E19" / "parameter_search_best.json")
    e22_search = read_json(BASE / "parameter_search_E22" / "parameter_search_best.json")
    e27_route = read_json(BASE / "routing_search_E27" / "routing_search_best.json")
    e27_loss = read_json(BASE / "loss_search_E27" / "loss_search_best.json")
    common_search = read_json(BASE / "network_common_calibration_search" / "common_search_report.json")
    santa_tereza_audit = read_json(ROOT / "assets" / "data" / "hec_hms_audit" / "santa_tereza_event_input_audit_latest.json")
    santa_tereza_raw_rain = read_json(ROOT / "assets" / "data" / "hec_hms_audit" / "derived" / "santa_tereza_raw_rain_dss_report.json")
    station_search = read_json(BASE / "network_station_e28_calibration_search" / "station_e28_search_report.json")
    hybrid_search = read_json(BASE / "network_hybrid_e28_calibration_search" / "hybrid_e28_search_report.json")
    hybrid_search_csv = BASE / "network_hybrid_e28_calibration_search" / "hybrid_e28_search.csv"
    with hybrid_search_csv.open(encoding="utf-8", newline="") as handle:
        hybrid_rows = list(csv.DictReader(handle))
    zero_lag_rows = [row for row in hybrid_rows if float(row["peak_lag_hours"]) == 0.0]
    best_zero_lag = max(zero_lag_rows, key=lambda row: float(row["research_score"])) if zero_lag_rows else None
    if best_zero_lag:
        best_zero_lag = {
            "candidate_id": int(best_zero_lag["candidate_id"]),
            "nse": float(best_zero_lag["nse"]),
            "peak_lag_hours": float(best_zero_lag["peak_lag_hours"]),
            "peak_relative_error": float(best_zero_lag["peak_relative_error"]),
            "research_score": float(best_zero_lag["research_score"]),
        }
    hybrid_replay = read_json(BASE / "network_replay_hybrid_e28" / "hybrid_e28_metrics.json")
    hybrid_rain = read_json(ROOT / "assets" / "data" / "hec_hms_audit" / "derived" / "mucum_hybrid_e28_rain_dss_report.json")

    events = []
    for metric in replay["events"]:
        row = dict(metric)
        row["interpretation"] = event_status(metric["event_id"], metric)
        row["rainfall_policy"] = {
            "E19": "Thiessen ANA; estação 86472000 como base do replay",
            "E22": "Thiessen ANA; estação 86472000 como base do replay",
            "E24": "série específica 86472000; Thiessen bloqueada por 5 valores ausentes/negativos",
            "E27": "série específica 86472000",
            "E28": "série específica 86472000",
        }.get(metric["event_id"], "não informado")
        events.append(row)

    report = {
        "schema_version": "hec_hms_taquari_antas_calibration_status_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "estudo de calibração e replay HEC-HMS; não é alerta, ordem de evacuação ou operação",
        "overall_status": "estrutura verificada; calibração comum ainda não concluída",
        "network": {
            "topology": audit["topology"]["connected_order"],
            "description": "Rio das Antas -> controle intermediário Santa Tereza -> Muçum",
            "source": audit["source"],
            "areas_km2": audit["topology"]["nested_catchment_area_km2_from_bho6"],
            "incremental_areas_km2": {
                "Antas_to_Santa_Tereza": audit["topology"]["nested_area_differences_km2"]["86472000_to_86472600_km2"],
                "Santa_Tereza_to_Mucum": audit["topology"]["nested_area_differences_km2"]["86472600_to_86510000_km2"],
            },
        },
        "terrain": {
            "status": terrain["gate"],
            "reaches": terrain["reaches"],
            "limitation": terrain["sources"]["terrain_note"],
        },
        "event_replay": {
            "candidate_package": "network_replay_eventwise_candidate_all_events",
            "events": events,
            "excluded": replay.get("excluded", {}),
            "warning": "parâmetros e fontes de chuva variam por evento; estes resultados servem para diagnóstico e não demonstram generalização",
        },
        "diagnostic_searches": {
            "E19": {"best_candidate": e19_search, "scope": "busca de K, tempo de concentração e armazenamento; chuva mantida"},
            "E22": {"best_candidate": e22_search, "scope": "busca de K e perda constante; chuva mantida"},
            "E27_routing": {"best_candidate": e27_route, "scope": "K dos dois trechos; zero atraso é métrica, não verdade física"},
            "E27_losses": {"best_candidate": e27_loss, "scope": "perdas; menor erro de pico pode piorar NSE"},
            "common_parameters": common_search,
        },
        "station_distributed_test": {
            "event_id": "E28",
            "rainfall_station": "86472600 · Santa Tereza",
            "policy": "86472000 no alto Antas; 86472600 nos dois incrementos a jusante de Santa Tereza",
            "candidate_count": station_search.get("candidate_count"),
            "best_candidate": station_search.get("best_by_research_score"),
            "candidate_package": f"network_station_e28_calibration_search/candidate_{int(station_search['best_by_research_score']['candidate_id']):03d}/E28" if station_search.get("best_by_research_score") else None,
            "replay_metrics": station_search.get("best_by_research_score"),
            "comparison_baseline_eventwise_proxy": next((row for row in replay["events"] if row["event_id"] == "E28"), None),
            "status": "candidata específica do E28; não promovida",
            "limitation": "não há vazão reconciliada em Santa Tereza para validar o ponto intermediário; E24/E27 têm lacuna interna na chuva bruta; a busca não prova generalização",
        },
        "hybrid_e28_test": {
            "event_id": "E28",
            "rainfall_stations": ["86472000 · Antas a montante", "86472600 · Santa Tereza", "86510000 · Muçum"],
            "policy": "86472000 no Antas a montante; 86472600 no incremento Santa Tereza; 86510000 no incremento final de Muçum",
            "candidate_count": hybrid_search.get("candidate_count"),
            "best_candidate": hybrid_search.get("best_by_research_score"),
            "replay_metrics": hybrid_replay.get("metrics"),
            "comparison_station_distributed_same_stz": station_search.get("best_by_research_score"),
            "comparison_baseline_eventwise_proxy": next((row for row in replay["events"] if row["event_id"] == "E28"), None),
            "rainfall_audit": hybrid_rain,
            "zero_lag_tradeoff": {
                "candidate_count": len(zero_lag_rows),
                "best_by_research_score": best_zero_lag,
                "interpretation": "zero atraso reduz uma métrica, mas não é escolhido se aumentar materialmente o erro do pico",
            },
            "spatial_series": "network_replay_hybrid_e28/E28/spatial_series_e28.csv",
            "spatial_report": "network_replay_hybrid_e28/E28/spatial_series_e28_report.json",
            "status": "candidata híbrida específica do E28; não promovida",
            "limitation": "a chuva local de E28 está completa, mas a vazão observada intermediária de Santa Tereza não está fechada; a busca continua específica do evento e não autoriza operação",
        },
        "rainfall_input_audit": {
            "station": santa_tereza_audit.get("station"),
            "events": santa_tereza_audit.get("events"),
            "raw_hourly_dss": santa_tereza_raw_rain,
        },
        "gates": {
            "Santa_Tereza_observed_flow": "bloqueado: série/vazão reconciliada não fechada nesta rodada",
            "rainfall_spatialization": "parcial: E28 tem teste híbrido com 86472000, 86472600 e 86510000; E24/E27 têm lacuna interna e não foram preenchidos; estação intermediária ainda não tem vazão reconciliada",
            "reach_routing": "bloqueado para parametrização física: faltam seções de calha, nível/cota e política Manning/Muskingum-Cunge",
            "MDT": "auditado para geometria de terreno; não substitui fundo da calha nem seção hidráulica",
            "E26": "bloqueado: não há pacote HEC-HMS de entrada reconciliado nesta rodada",
            "operational_promotion": "bloqueado: manter como pesquisa/replay",
        },
        "artifacts": {
            "network_audit": "network_audit_latest.json",
            "network_geojson": "bho6_taquari_antas_network.geojson",
            "terrain_audit": "reach_terrain_metrics_latest.json",
            "metrics_json": "network_replay_eventwise_candidate_all_events/network_metrics_all_events.json",
            "metrics_csv": "network_replay_eventwise_candidate_all_events/network_metrics_all_events.csv",
            "series_csv": "network_replay_eventwise_candidate_all_events/network_series_all_events.csv",
            "station_e28_search": "network_station_e28_calibration_search/station_e28_search_report.json",
            "station_e28_search_csv": "network_station_e28_calibration_search/station_e28_search.csv",
            "station_e28_best_candidate": f"network_station_e28_calibration_search/candidate_{int(station_search['best_by_research_score']['candidate_id']):03d}/E28" if station_search.get("best_by_research_score") else None,
            "station_distributed_replay": "network_replay_station_distributed_eventwise_all_events/network_metrics_all_events.json",
            "hybrid_e28_search": "network_hybrid_e28_calibration_search/hybrid_e28_search_report.json",
            "hybrid_e28_search_csv": "network_hybrid_e28_calibration_search/hybrid_e28_search.csv",
            "hybrid_e28_replay": "network_replay_hybrid_e28/hybrid_e28_metrics.json",
            "hybrid_e28_manifest": "network_replay_hybrid_e28/E28/event_network_manifest.json",
            "hybrid_e28_spatial_series": "network_replay_hybrid_e28/E28/spatial_series_e28.csv",
            "hybrid_e28_spatial_report": "network_replay_hybrid_e28/E28/spatial_series_e28_report.json",
            "hybrid_e28_rainfall_audit": "../hec_hms_audit/derived/mucum_hybrid_e28_rain_dss_report.json",
            "santa_tereza_input_audit": "../hec_hms_audit/santa_tereza_event_input_audit_latest.json",
            "santa_tereza_raw_rain_report": "../hec_hms_audit/derived/santa_tereza_raw_rain_dss_report.json",
            "dashboard": "network_dashboard/index.html",
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "events": len(events), "status": report["overall_status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
