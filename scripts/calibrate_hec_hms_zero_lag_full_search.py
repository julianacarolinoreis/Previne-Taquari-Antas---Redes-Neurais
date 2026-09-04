"""Full parameter search constrained toward zero peak lag.

The search is deterministic and uses only the existing ANA rainfall and flow
series. It does not shift timestamps or fill missing values. A candidate is
considered timing-compatible only when HEC-HMS itself places the simulated
peak in the observed peak hour.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from itertools import product
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(r"D:\PREVINE\worktrees\previne-catalogo-pesquisas-20260828")
sys.path.insert(0, str(SCRIPT_DIR))
import calibrate_hec_hms_mucum_multi_event as base  # noqa: E402


CONFIG = {
    19: {
        "tc": [30.0, 45.0, 60.0, 75.0, 90.0, 105.0, 120.0, 150.0, 180.0],
        "storage": [60.0, 90.0, 120.0, 150.0, 180.0, 240.0],
        "loss": [0.0, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0, 20.0],
        "constant": [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
        "recession": [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98],
        "flow_area": [0.001, 0.0025, 0.005, 0.01, 0.02],
        "seed": {"initial_loss": 0.0, "constant_loss": 1.0, "tc_min": 60.0, "storage_min": 150.0, "recession_factor": 0.7, "initial_flow_area_ratio": 0.01},
    },
    26: {
        "tc": [10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 60.0, 75.0],
        "storage": [1.0, 5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 90.0],
        "loss": [0.0, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0, 20.0],
        "constant": [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0],
        "recession": [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98],
        "flow_area": [0.001, 0.0025, 0.005, 0.01, 0.02, 0.05],
        "seed": {"initial_loss": 2.5, "constant_loss": 1.0, "tc_min": 35.0, "storage_min": 10.0, "recession_factor": 0.7, "initial_flow_area_ratio": 0.005},
    },
    28: {
        "tc": [15.0, 17.5, 20.0, 22.5, 25.0, 27.5, 30.0, 32.5, 35.0, 40.0],
        "storage": [15.0, 30.0, 45.0, 60.0, 75.0, 90.0, 105.0, 120.0],
        "loss": [0.0, 0.5, 1.0, 2.0, 2.5, 3.0, 5.0, 10.0],
        "constant": [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0],
        "recession": [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98],
        "flow_area": [0.001, 0.0025, 0.005, 0.01, 0.02],
        "seed": {"initial_loss": 2.5, "constant_loss": 2.0, "tc_min": 25.0, "storage_min": 75.0, "recession_factor": 0.8, "initial_flow_area_ratio": 0.0025},
    },
}


def candidates(event_id: int, count: int) -> list[dict[str, float]]:
    cfg = CONFIG[event_id]
    rng = random.Random(20260903 + event_id)
    values = [
        {
            "initial_loss": float(il),
            "constant_loss": float(cl),
            "tc_min": float(tc),
            "storage_min": float(storage),
            "recession_factor": float(rec),
            "initial_flow_area_ratio": float(fa),
        }
        for il, cl, tc, storage, rec, fa in product(
            cfg["loss"], cfg["constant"], cfg["tc"], cfg["storage"], cfg["recession"], cfg["flow_area"]
        )
    ]
    rng.shuffle(values)
    seed = cfg["seed"]
    anchors = [seed]
    # Keep a deterministic neighborhood around the known timing solution.
    for tc in cfg["tc"]:
        for storage in cfg["storage"]:
            anchors.append({**seed, "tc_min": tc, "storage_min": storage})
    seen = set()
    ordered = []
    for item in anchors + values:
        key = tuple(item[key] for key in ("initial_loss", "constant_loss", "tc_min", "storage_min", "recession_factor", "initial_flow_area_ratio"))
        if key not in seen:
            ordered.append(item)
            seen.add(key)
        if len(ordered) >= count:
            break
    return ordered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=int, required=True, choices=sorted(CONFIG))
    parser.add_argument("--count", type=int, default=180)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base.OUT_ROOT = output_dir
    base.INPUT_DSS = base.MULTI_DSS
    base.BASIN_AREA_KM2 = 16000.0
    specs = base.event_specs({args.event}, "ana86472000")
    if not specs:
        raise SystemExit(f"no source-backed specification for E{args.event}")

    rows = []
    params_list = candidates(args.event, args.count)
    for index, params in enumerate(params_list, 1):
        row = base.run_candidate(index, params, specs, args.timeout, "ana86472000", 16000.0)
        rows.append(row)
        if row.get("status") == "ok":
            print(
                "PROGRESS E%d %d/%d lag=%s NSE=%.5f peak_error=%.4f"
                % (args.event, index, len(params_list), row.get("mean_abs_peak_lag_hours"), row.get("mean_nse"), row.get("mean_peak_relative_error")),
                flush=True,
            )
        else:
            print(f"PROGRESS E{args.event} {index}/{len(params_list)} FAILED", flush=True)

    valid = [row for row in rows if row.get("status") == "ok"]
    zero = [row for row in valid if float(row.get("mean_abs_peak_lag_hours", 999.0)) == 0.0]
    by_nse = sorted(zero, key=lambda row: (-float(row.get("mean_nse", -1.0e99)), float(row.get("mean_peak_relative_error", 1.0e99))))
    by_peak = sorted(zero, key=lambda row: (float(row.get("mean_peak_relative_error", 1.0e99)), -float(row.get("mean_nse", -1.0e99))))
    summary = {
        "event_id": args.event,
        "candidates": len(params_list),
        "successful": len(valid),
        "zero_lag_candidates": len(zero),
        "best_zero_lag_by_nse": by_nse[0] if by_nse else None,
        "best_zero_lag_by_peak_error": by_peak[0] if by_peak else None,
        "best_overall": max(valid, key=lambda row: float(row.get("fitness", -1.0e99))) if valid else None,
    }
    fields = sorted({key for row in rows for key in row})
    with (output_dir / "zero_lag_full_search_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / f"E{args.event}_zero_lag_full_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
