#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes de contrato do relatório de proveniência das chuvas."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "assets" / "data" / "hec_hms_audit" / "rainfall_station_audit_latest.json"


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    csv_report = report["local_csv"]
    assert csv_report["rows"] > 0
    assert csv_report["duplicate_timestamp_rows"] == 0
    assert csv_report["cadence_breaks"] == 0

    stations = {station["inventory_code"]: station for station in report["ana"]}
    assert stations["86472600"]["official_identity"]["municipality"] == "SANTA TEREZA"
    assert stations["86472600"]["official_identity"]["station_type"] == "fluviométrica"
    assert stations["86472600"]["event_comparison"]["overlap_numeric_hours"] == 0

    for code in ("86472000", "02851072"):
        comparison = stations[code]["event_comparison"]
        assert comparison["overlap_numeric_hours"] == 240
        assert comparison["exact_match"] is True
        assert comparison["mean_absolute_error_mm"] == 0

    assert stations["86472000"]["telemetry"]["flow_records"] >= 900
    assert stations["86472000"]["telemetry"]["level_records"] >= 900
    assert "CANDIDATO DISPONÍVEL" in report["calibration_gate"]["observed_response_target"]

    assert stations["02851072"]["official_identity"]["municipality"] == "IBIRAIARAS"
    assert report["inmet"]["official_identity"]["name"] == "SERAFINA CORRÊA"
    assert report["cemaden"]["official_identity"]["municipality"] == "SERAFINA CORRÊA"
    assert report["calibration_gate"]["calibration_execution"] == "NÃO EXECUTADA"
    candidate = ROOT / report["event_candidate_package"]["path"]
    assert candidate.exists()
    assert report["event_candidate_package"]["rows"] == 240
    assert report["event_candidate_package"]["status"].startswith("candidato")
    assert len(report["raw_file_inventory"]) >= 23
    assert all(item["sha256"] for item in report["raw_file_inventory"])
    print("PASS: contrato de proveniência e bloqueios semânticos do relatório")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
