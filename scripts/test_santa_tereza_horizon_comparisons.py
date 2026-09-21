#!/usr/bin/env python3
"""Contract checks for the Santa Tereza 4 h / 8 h comparison package."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "assets" / "data" / "santa_tereza_horizons" / "stz_horizon_model_comparisons.json"
CSV_PATH = ROOT / "assets" / "data" / "santa_tereza_horizons" / "stz_horizon_model_comparisons_metrics.csv"
PAGE = ROOT / "pesquisas" / "comparacao-modelos-stz-horizontes.html"


def main() -> None:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert data["research_only"] is True
    assert data["promotion_allowed"] is False
    assert data["station"]["code"] == "86472600"
    assert data["horizons"]["4"]["event"] == 13
    assert data["horizons"]["4"]["partition"] == "Teste"
    assert data["horizons"]["4"]["common_points"] == 249
    assert len(data["horizons"]["4"]["source_models"]) == 11
    assert data["horizons"]["8"]["event"] == 3
    assert data["horizons"]["8"]["partition"] == "Teste"
    assert data["horizons"]["8"]["common_points"] == 231
    assert len(data["horizons"]["8"]["source_models"]) == 10
    assert all(c["same_common_test_rows"] for c in data["horizons"].values())
    assert all(c["audit"]["source_rna_not_retrained"] for c in data["horizons"].values())
    assert all(c["audit"]["train_and_test_temporally_separated"] for c in data["horizons"].values())
    assert data["uncertainty"]["status"] == "not_calibrated_for_live_use"
    assert PAGE.exists()
    html = PAGE.read_text(encoding="utf-8")
    for token in ["data-h=\"2\"", "data-h=\"4\"", "data-h=\"8\"", "peak_lag_hours", "não é operação"]:
        assert token in html, token
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 31
    assert {int(row["horizon_hours"]) for row in rows} == {4, 8}
    print("Santa Tereza 4 h / 8 h comparison contract: OK")


if __name__ == "__main__":
    main()
