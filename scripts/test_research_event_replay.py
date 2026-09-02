#!/usr/bin/env python3
"""Contract checks for the source-backed research-event replay artifact."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "assets" / "data" / "research_event_replay_latest.json"


def main() -> None:
    data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["research_only"] is True
    assert data["official_alert"] is False
    assert data["operational_gate"]["status"] == "blocked"
    assert {source["id"] for source in data["forecast_sources"]} == {"rna", "rna_santa_tereza", "hec_hms"}
    hec = next(source for source in data["forecast_sources"] if source["id"] == "hec_hms")
    assert hec["status"] == "not_integrated_yet"
    assert hec["published_peak"] is None

    case = next(item for item in data["replay_cases"] if item["event_id"] == "mucum-q62-35")
    assert case["event_status"] == "usable_research_test_record"
    assert case["peak_observed_cm"] == 1986.0
    assert {item["horizon_hours"] for item in case["horizons"]} == {8, 12}
    for item in case["horizons"]:
        assert item["selected_model"]
        assert item["series"]["set"] == "Teste"
        assert item["series"]["points_published"] == 47
        assert item["series"]["missing_hours_in_recorte"] == 10
        assert item["series"]["forecast_target_timestamp"] == "2026-07-22 15:00"
        assert item["series"]["timestamp_reconciliation_status"].endswith("release_timestamp_pending")

    muc = data["spatial_scenarios"]["mucum"]
    assert muc["published_level_range_m"] == [0.0, 25.0]
    assert [item["cells_200m_touched"] for item in muc["scenarios"]] == [67, 70, 79]
    assert [item["population_upper_bound_whole_touched_cells"] for item in muc["scenarios"]] == [3153, 3351, 3581]
    stz = data["spatial_scenarios"]["santa_tereza"]
    assert stz["published_level_range_m"] == [0.0, 15.0]
    assert stz["higher_than_published_status"] == "not_published_in_current_contour_file"
    assert stz["scenarios"][0]["cells_200m_touched"] == 43
    assert data["response_inventory"]["mucum"]["capacity_reconciliation_status"]
    assert data["response_inventory"]["mucum"]["operational_gate"] == "blocked"
    print("research event replay contract: OK")


if __name__ == "__main__":
    main()
