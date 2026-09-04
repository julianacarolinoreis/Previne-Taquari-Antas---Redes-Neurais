"""Fine timing search for Muçum HEC-HMS event replays.

This search changes only HEC-HMS timing parameters. It never shifts observed
timestamps, imputes missing rainfall, or changes the scoring window. Results
are intended to decide whether a zero peak-lag replay is defensible for E19,
E26, and E28.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from itertools import product
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(r"D:\PREVINE\worktrees\previne-catalogo-pesquisas-20260828")
sys.path.insert(0, str(SCRIPT_DIR))
import calibrate_hec_hms_mucum_multi_event as base  # noqa: E402


EVENT_PARAMS = {
    19: {
        "initial_loss": 0.0,
        "constant_loss": 1.0,
        "recession_factor": 0.7,
        "initial_flow_area_ratio": 0.01,
        "tc_min": [30.0, 45.0, 60.0, 75.0, 90.0, 105.0, 120.0, 150.0, 180.0],
        "storage_min": [30.0, 60.0, 90.0, 120.0, 150.0, 180.0, 240.0],
    },
    26: {
        "initial_loss": 2.5,
        "constant_loss": 1.0,
        "recession_factor": 0.7,
        "initial_flow_area_ratio": 0.005,
        "tc_min": [10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 60.0, 75.0],
        "storage_min": [1.0, 5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 90.0],
    },
    28: {
        "initial_loss": 2.5,
        "constant_loss": 2.0,
        "recession_factor": 0.8,
        "initial_flow_area_ratio": 0.0025,
        "tc_min": [15.0, 17.5, 20.0, 22.5, 25.0, 27.5, 30.0, 32.5, 35.0, 40.0],
        "storage_min": [15.0, 30.0, 45.0, 60.0, 75.0, 90.0, 105.0, 120.0],
    },
}


def candidates(event_id: int) -> list[dict[str, float]]:
    spec = EVENT_PARAMS[event_id]
    keys = ("tc_min", "storage_min")
    result = []
    for tc_min, storage_min in product(spec["tc_min"], spec["storage_min"]):
        result.append(
            {
                "initial_loss": float(spec["initial_loss"]),
                "constant_loss": float(spec["constant_loss"]),
                "tc_min": float(tc_min),
                "storage_min": float(storage_min),
                "recession_factor": float(spec["recession_factor"]),
                "initial_flow_area_ratio": float(spec["initial_flow_area_ratio"]),
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--events", default="19,26,28")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base.OUT_ROOT = output_dir
    base.INPUT_DSS = base.MULTI_DSS
    base.BASIN_AREA_KM2 = 16000.0

    all_rows: list[dict[str, object]] = []
    for event_id in [int(item.strip()) for item in args.events.split(",") if item.strip()]:
        specs = base.event_specs({event_id}, "ana86472000")
        if not specs:
            raise SystemExit(f"no source-backed specification for E{event_id}")
        params_list = candidates(event_id)
        for index, params in enumerate(params_list, 1):
            row = base.run_candidate(index, params, specs, args.timeout, "ana86472000", 16000.0)
            row["event_id"] = event_id
            all_rows.append(row)
            if row.get("status") == "ok":
                print(
                    "PROGRESS E%d index=%d/%d lag=%sh NSE=%.5f peak_error=%.4f"
                    % (
                        event_id,
                        index,
                        len(params_list),
                        row.get("mean_abs_peak_lag_hours"),
                        row.get("mean_nse"),
                        row.get("mean_peak_relative_error"),
                    ),
                    flush=True,
                )
            else:
                print(f"PROGRESS E{event_id} index={index}/{len(params_list)} FAILED", flush=True)

        event_rows = [row for row in all_rows if row.get("event_id") == event_id and row.get("status") == "ok"]
        zero_rows = [row for row in event_rows if float(row.get("mean_abs_peak_lag_hours", 999.0)) == 0.0]
        ranked = sorted(
            zero_rows or event_rows,
            key=lambda row: (
                -float(row.get("mean_nse", -1.0e99)),
                float(row.get("mean_peak_relative_error", 1.0e99)),
            ),
        )
        summary = {
            "event_id": event_id,
            "candidates": len(params_list),
            "successful": len(event_rows),
            "zero_lag_candidates": len(zero_rows),
            "best_zero_lag_or_event": ranked[0] if ranked else None,
        }
        (output_dir / f"E{event_id}_zero_lag_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)

    fields = sorted({key for row in all_rows for key in row})
    with (output_dir / "zero_lag_search_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"DONE rows={len(all_rows)} output={output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
