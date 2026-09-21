#!/usr/bin/env python3
"""Contract checks for the source-backed basin network and terrain audit."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas"


def main() -> None:
    network = json.loads((BASE / "network_audit_latest.json").read_text(encoding="utf-8"))
    terrain = json.loads((BASE / "reach_terrain_metrics_latest.json").read_text(encoding="utf-8"))
    status = json.loads((BASE / "network_calibration_status_latest.json").read_text(encoding="utf-8"))
    reconciliation = json.loads((BASE / "station_reconciliation_latest.json").read_text(encoding="utf-8"))
    assert network["topology"]["connected_order"] == ["86472000", "86472600", "86510000"]
    assert set(network["topology"]["paths"]) == {"86472000_to_86472600", "86472600_to_86510000"}
    assert terrain["gate"].startswith("terrain_screening_complete")
    assert len(terrain["sources"]["terrain"]) == 2
    assert all(item["sample_count"] > 0 for item in terrain["reaches"].values())
    assert status["overall_status"] == "estrutura verificada; calibração comum ainda não concluída"
    assert status["network"]["representation"] == "três áreas incrementais e dois trechos de propagação entre postos, não três zonas da bacia"
    assert status["gates"]["operational_promotion"] == "bloqueado: manter como pesquisa/replay"
    assert status["diagnostic_searches"]["E19"]["best_candidate"]["status"] == "unavailable_missing_artifact"
    assert status["diagnostic_searches"]["E27_routing"]["best_candidate"]["status"] == "unavailable_missing_artifact"
    assert reconciliation["summary"]["three_incremental_areas_complete_events"] == ["E28"]
    assert reconciliation["calibration_gate"]["current_status"] == "blocked_common_calibration_single_complete_event"
    assert reconciliation["events"][0]["policy"] == "missing_data_not_filled_or_interpolated"
    print("Network reconciliation and terrain audit contract: OK")


if __name__ == "__main__":
    main()
