#!/usr/bin/env python3
"""Diagnostic parameter search for E28 with audited Santa Tereza rain.

This compares parameter vectors while keeping the rainfall distribution fixed:
86472000 for the Antas headwater and 86472600 for both downstream increments.
It is a research replay, not a promoted calibration.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_hec_hms_network_station_distributed import build_event, run_event  # noqa: E402
from extract_hec_hms_network_all_events import extract_event, score  # noqa: E402


DEFAULT_OUT = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "network_station_e28_calibration_search"


def candidates() -> list[dict[str, float]]:
    rows = [
        (2.5, 2.0, 25.0, 45.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 20.0, 45.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 30.0, 45.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 15.0, 45.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 40.0, 45.0, 0.80, 0.003, 1.0),
        (0.0, 2.0, 25.0, 45.0, 0.80, 0.003, 1.0),
        (5.0, 2.0, 25.0, 45.0, 0.80, 0.003, 1.0),
        (2.5, 1.0, 25.0, 45.0, 0.80, 0.003, 1.0),
        (2.5, 3.0, 25.0, 45.0, 0.80, 0.003, 1.0),
        (2.5, 4.0, 25.0, 45.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 25.0, 30.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 25.0, 60.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 25.0, 90.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 25.0, 45.0, 0.70, 0.003, 1.0),
        (2.5, 2.0, 25.0, 45.0, 0.90, 0.003, 1.0),
        (2.5, 2.0, 25.0, 45.0, 0.98, 0.003, 1.0),
        (2.5, 2.0, 25.0, 45.0, 0.80, 0.001, 1.0),
        (2.5, 2.0, 25.0, 45.0, 0.80, 0.005, 1.0),
        (2.5, 2.0, 25.0, 45.0, 0.80, 0.003, 0.5),
        (2.5, 2.0, 25.0, 45.0, 0.80, 0.003, 2.0),
        (1.0, 3.0, 20.0, 60.0, 0.85, 0.0025, 1.0),
        (5.0, 1.0, 20.0, 60.0, 0.90, 0.001, 1.0),
        (2.5, 2.0, 23.0, 30.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 24.0, 30.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 26.0, 30.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 27.0, 30.0, 0.80, 0.003, 1.0),
        (2.0, 2.0, 25.0, 30.0, 0.80, 0.003, 1.0),
        (3.0, 2.0, 25.0, 30.0, 0.80, 0.003, 1.0),
        (2.5, 1.5, 25.0, 30.0, 0.80, 0.003, 1.0),
        (2.5, 2.5, 25.0, 30.0, 0.80, 0.003, 1.0),
        (2.5, 3.0, 25.0, 30.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 25.0, 20.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 25.0, 25.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 25.0, 35.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 25.0, 40.0, 0.80, 0.003, 1.0),
        (2.5, 2.0, 25.0, 30.0, 0.80, 0.0025, 1.0),
        (2.5, 2.0, 25.0, 30.0, 0.80, 0.0035, 1.0),
        (2.5, 2.0, 25.0, 30.0, 0.80, 0.003, 0.75),
        (2.5, 2.0, 25.0, 30.0, 0.80, 0.003, 1.25),
    ]
    keys = ("initial_loss", "constant_loss", "tc", "storage", "recession", "initial_flow_ratio", "k")
    return [dict(zip(keys, row)) for row in rows]


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    pool = candidates()[: args.limit or None]
    rows: list[dict] = []
    for index, params in enumerate(pool, start=1):
        candidate_dir = out / f"candidate_{index:03d}"
        build_event("E28", candidate_dir, {"E28"}, "eventwise", params_override=params)
        run = run_event("E28", candidate_dir / "E28")
        if run["ok_marker"]:
            metric = score("E28", extract_event("E28", candidate_dir / "E28"))
            row = {"candidate_id": index, **params, **metric}
            row["research_score"] = metric["nse"] - 0.02 * abs(metric["peak_lag_hours"]) - 0.2 * metric["peak_relative_error"]
        else:
            row = {"candidate_id": index, **params, "status": "failed", "returncode": run["returncode"]}
        rows.append(row)
        print(f"candidate {index}/{len(pool)} complete")
    good = [row for row in rows if row.get("status") == "replay_scored_not_promoted"]
    good.sort(key=lambda row: row["research_score"], reverse=True)
    fields = sorted({key for row in rows for key in row})
    with (out / "station_e28_search.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(good)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "busca diagnóstica de parâmetros no E28 com chuva bruta de Santa Tereza; não é calibração promovida",
        "rainfall_policy": "86472000 no alto Antas; 86472600 nos dois incrementos a jusante de Santa Tereza",
        "candidate_count": len(pool),
        "successful_candidates": len(good),
        "best_by_research_score": good[0] if good else None,
        "artifacts": ["station_e28_search.csv"],
    }
    (out / "station_e28_search_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
