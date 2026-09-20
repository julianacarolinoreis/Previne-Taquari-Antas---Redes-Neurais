#!/usr/bin/env python3
"""Contract checks for the Santa Tereza 2 h same-row benchmark."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "assets" / "data" / "santa_tereza_2h" / "stz_2h_model_comparison.json"
CSV_PATH = ROOT / "assets" / "data" / "santa_tereza_2h" / "stz_2h_model_comparison_metrics.csv"
PAGE = ROOT / "pesquisas" / "comparacao-modelos-stz-2h.html"


def main() -> None:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert data["research_only"] is True
    assert data["promotion_allowed"] is False
    assert data["method"]["independent_event"] == 12
    assert data["method"]["independent_partition_source"] == "Verificacao"
    assert data["method"]["same_common_test_rows"] is True
    assert data["method"]["common_points"] == 257
    assert len(data["eligible_source_models"]) == 6
    assert len(data["excluded_source_models"]) == 4
    assert len(data["aggregate_metrics"]) == 11
    assert all(row["event"] == 12 for row in data["event_metrics"])
    assert all(row["n_common_event_points"] == 257 for row in data["event_metrics"])
    assert data["audit"]["duplicate_common_keys"] == 0
    assert data["audit"]["target_and_output_columns_in_inputs"] is False
    assert data["audit"]["source_rna_not_retrained"] is True
    assert PAGE.exists()
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 11
    print("Santa Tereza 2 h same-row comparison contract: OK")


if __name__ == "__main__":
    main()
