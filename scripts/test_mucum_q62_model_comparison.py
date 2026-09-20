"""Contract tests for the same-row Muçum Q62 model benchmark."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "assets" / "data" / "mucum_q62" / "mucum_q62_model_comparison.json"
CSV_PATH = ROOT / "assets" / "data" / "mucum_q62" / "mucum_q62_model_comparison_metrics.csv"
TUNED_PATH = ROOT / "assets" / "data" / "mucum_q62" / "mucum_q62_tuned_baselines.json"


def main() -> None:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert data["status"] == "research_only_same_common_test_rows"
    assert data["promotion_allowed"] is False
    assert data["method"]["test_events"] == [31, 33, 34, 35, 37]
    assert data["method"]["same_common_test_rows"] is True
    assert data["method"]["no_future_features"] is True
    assert len(data["aggregate_metrics"]) == 20
    assert len(data["event_metrics"]) == 100
    assert data["audit"]["duplicate_common_keys"] == 0
    assert data["audit"]["target_and_output_columns_in_inputs"] is False
    models = {row["model"] for row in data["aggregate_metrics"]}
    expected = {"Persistência", "Ridge", "MLP", "Random Forest", "XGBoost"} | {f"RNA {value:03d}" for value in range(31, 36)} | {f"RNA {value:03d}" for value in range(36, 41)}
    assert models == expected
    for horizon in ("8", "12"):
        contract = data["fairness_by_horizon"][horizon]
        assert contract["train_partition"] == "Treino"
        assert contract["test_partition"] == "Teste"
        assert contract["common_test_points_total"] == 395
        assert all(contract["common_test_points_by_event"][str(event)] > 0 for event in (31, 33, 34, 35, 37))
    for row in data["aggregate_metrics"] + data["event_metrics"]:
        assert row["n"] > 0
        for key in ("mae_cm", "rmse_cm", "peak_abs_error_cm"):
            assert row[key] is not None and row[key] >= 0
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 100
    tuned = json.loads(TUNED_PATH.read_text(encoding="utf-8"))
    assert tuned["status"] == "research_only_test_frozen_after_validation_tuning"
    assert tuned["promotion_allowed"] is False
    assert tuned["method"]["same_common_test_rows"] is True
    assert len(tuned["aggregate_metrics"]) == 20
    assert len(tuned["event_metrics"]) == 100
    assert set(tuned["tuning"]) == {"8", "12"}
    assert all(item["train_points"] >= item["validation_points"] for item in tuned["aggregate_metrics"])
    print("Muçum Q62 same-row model comparison contract: OK")


if __name__ == "__main__":
    main()
