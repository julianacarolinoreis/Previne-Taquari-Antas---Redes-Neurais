"""Run a reproducible, event-focused HEC-HMS parameter search.

This wrapper keeps the calibration engine unchanged and replaces its broad
grid with a small, explicit neighborhood around the best published replay for
the selected event. It is intended for timing/peak diagnostics, not for
post-hoc shifting of the hydrograph or for operational promotion.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "scripts" / "calibrate_hec_hms_mucum_multi_event.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("mucum_hms_engine", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load calibration engine: {ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def focused_grid(event_id: int) -> dict[str, list[float]]:
    if event_id == 24:
        # Published E24 replay: IL=5, CL=0.5, Tc=20 min, storage=30 min,
        # recession=0.7, initial-flow/area=0.0025.
        return {
            "initial_loss": [2.5, 5.0, 7.5],
            "constant_loss": [0.25, 0.5, 0.75],
            "tc_min": [15.0, 20.0, 25.0, 30.0],
            "storage_min": [15.0, 30.0],
            "recession_factor": [0.7, 0.8],
            "initial_flow_area_ratio": [0.001, 0.0025],
        }
    if event_id == 22:
        # Published E22 replay: IL=20, CL=1, Tc=30 min, storage=30 min,
        # recession=0.9, initial-flow/area=0.02. The response series has a
        # documented outage, so this search cannot repair missing evidence.
        return {
            "initial_loss": [15.0, 20.0, 25.0],
            "constant_loss": [0.5, 0.75, 1.0],
            "tc_min": [20.0, 30.0, 45.0, 60.0],
            "storage_min": [30.0, 60.0],
            "recession_factor": [0.85, 0.9],
            "initial_flow_area_ratio": [0.01, 0.02],
        }
    raise SystemExit("supported focused events: 22 or 24")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=int, choices=[22, 24], required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    engine = load_engine()
    engine.GRID = focused_grid(args.event)
    count = 1
    for values in engine.GRID.values():
        count *= len(values)
    sys.argv = [
        str(ENGINE_PATH),
        "--events",
        str(args.event),
        "--samples",
        str(count),
        "--timeout",
        str(args.timeout),
        "--output-dir",
        str(args.output_dir.resolve()),
    ]
    print(f"FOCUSED_SEARCH event=E{args.event} combinations={count}", flush=True)
    return engine.main()


if __name__ == "__main__":
    raise SystemExit(main())
