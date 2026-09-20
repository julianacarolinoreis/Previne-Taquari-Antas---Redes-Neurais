#!/usr/bin/env python3
"""Contract checks for the non-promoted Q62 candidate-series artifact."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "assets" / "data" / "mucum_q62" / "mucum_q62_replay_candidates.json"


def main() -> None:
    data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert data["status"] == "research_candidates_only_not_promoted"
    assert data["research_only"] is True
    assert data["official_alert"] is False
    assert data["selection"]["selected_model"] is None
    assert data["selection"]["selection_status"] == "blocked_by_independent_review_gate"
    assert data["candidate_count"] == 10
    assert data["test_events"] == [31, 33, 34, 35, 37]
    assert data["event_count"] == 5
    assert [(item["event_number"], item["candidate_series_count"]) for item in data["events"]] == [
        (31, 10),
        (33, 10),
        (34, 10),
        (35, 10),
        (37, 10),
    ]
    assert {item["horizon_hours"] for item in data["candidates"]} == {8, 12}
    for horizon in (8, 12):
        candidates = [item for item in data["candidates"] if item["horizon_hours"] == horizon]
        assert len(candidates) == 5
        for candidate in candidates:
            assert candidate["series_key"] == "35|Teste"
            assert candidate["events_available"] == [31, 33, 34, 35, 37]
            assert candidate["unit"] == "cm"
            assert candidate["prediction_contract"]["target_and_prediction_excluded_from_inputs"] is True
            assert candidate["checks"]["event_values"] == [31, 33, 34, 35, 37]
            assert candidate["checks"]["partition"] == "Teste"
            assert candidate["checks"]["serie_values"] == [3]
            assert candidate["checks"]["formula_mismatch_count"] == 0
            assert candidate["checks"]["nonfinite_row_count"] == 0
            assert candidate["checks"]["duplicate_timestamp_count"] == 0
            assert set(candidate["series_by_event"]) == {"31", "33", "34", "35", "37"}
            assert set(candidate["event_metrics_by_event"]) == {"31", "33", "34", "35", "37"}
            assert all(candidate["series_by_event"][event] for event in candidate["series_by_event"])
            assert all(
                candidate["event_metrics_by_event"][event]["points"] == len(candidate["series_by_event"][event])
                for event in candidate["series_by_event"]
            )
            assert candidate["event_metrics"]["points"] in {47, 48}
            assert candidate["event_metrics"]["observed_peak_target_timestamp"] == "2026-07-22 15:00"
            assert candidate["event_metrics"]["predicted_peak_target_timestamp"]
            assert candidate["series"]
            assert all(row["target_timestamp"] > row["base_timestamp"] for row in candidate["series"])
    fail = next(item for item in data["candidates"] if item["model_id"].startswith("035_"))
    assert fail["review"]["status"] == "FAIL_DESEMPENHO_NAO_PUBLICAR"
    assert fail["review"]["promotion_allowed"] is False
    print("Muçum Q62 candidate replay contract: OK")


if __name__ == "__main__":
    main()
