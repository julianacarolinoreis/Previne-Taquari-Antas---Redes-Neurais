"""Run a reproducible event-specific HEC-HMS parameter search for Mucum.

This script deliberately keeps the calibration scope explicit: one historical
event, one lumped basin, one candidate ANA precipitation series, and the
observed 86472000 hourly flow series.  It does not promote the result to an
operational forecast model.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(r"D:\PREVINE\worktrees\previne-catalogo-pesquisas-20260828")
BASE = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_event_2023"
SEARCH = BASE / "calibration_search"
HEC_CMD = Path(r"D:\PREVINE\tools\hec-hms-4.13\portable\HEC-HMS-4.13\HEC-HMS.cmd")


COARSE_GRID = {
    "initial_loss": [0.0, 5.0, 15.0],
    "constant_loss": [0.1, 0.5, 1.5],
    "tc_min": [60.0, 180.0, 360.0, 720.0],
    "storage_min": [60.0, 180.0, 360.0, 720.0],
    # Keep the first stage focused on runoff timing and volume.  Baseflow is
    # varied in the second stage after the coarse runoff region is known.
    "recession_factor": [0.80],
    "initial_flow_area_ratio": [0.005],
}

REFINE_GRID = {
    "initial_loss": [0.0, 2.5, 5.0, 10.0],
    "constant_loss": [0.05, 0.1, 0.25, 0.5, 1.0],
    "tc_min": [30.0, 45.0, 60.0, 75.0, 90.0],
    "storage_min": [0.25, 0.5, 1.0, 2.0, 5.0],
    "recession_factor": [0.70, 0.80, 0.90, 0.95],
    "initial_flow_area_ratio": [0.0025, 0.005, 0.01, 0.02],
}

FOCAL_GRID = {
    "initial_loss": [0.0, 5.0],
    "constant_loss": [0.1, 0.5],
    # The observed peak is 94 hourly steps into the event.  The coarse grid
    # showed that 60 minutes was still lagging, so explicitly test sub-hour
    # Clark response and the neighboring values.
    "tc_min": [1.0, 15.0, 60.0],
    "storage_min": [1.0, 15.0, 60.0],
    "recession_factor": [0.80],
    "initial_flow_area_ratio": [0.005],
}


def replace_parameter(text: str, label: str, value: float) -> str:
    pattern = rf"(?m)^(\s*{re.escape(label)}:\s*)[^\r\n]+$"
    updated, count = re.subn(pattern, rf"\g<1>{value:g}", text)
    if count != 1:
        raise ValueError(f"expected one '{label}' line, found {count}")
    return updated


def make_candidate(index: int, params: dict[str, float]) -> Path:
    candidate = SEARCH / f"candidate_{index:04d}"
    if candidate.exists():
        shutil.rmtree(candidate)
    candidate.mkdir(parents=True)
    names = [
        "mucum_event_2023.hms",
        "evento_2023-09.control",
        "chuva_86472000.met",
        "mucum_event_2023.gage",
        "mucum_event_2023.dss",
    ]
    for name in names:
        shutil.copy2(BASE / name, candidate / name)
    basin = (BASE / "bacia_86472000.basin").read_text(encoding="utf-8")
    basin = replace_parameter(basin, "Initial Loss", params["initial_loss"])
    basin = replace_parameter(basin, "Constant Loss Rate", params["constant_loss"])
    basin = replace_parameter(basin, "Time of Concentration", params["tc_min"])
    basin = replace_parameter(basin, "Storage Coefficient", params["storage_min"])
    basin = replace_parameter(basin, "Recession Factor", params["recession_factor"])
    basin = replace_parameter(
        basin,
        "Initial Flow/Area Ratio",
        params["initial_flow_area_ratio"],
    )
    (candidate / "bacia_86472000.basin").write_text(basin, encoding="utf-8")

    run = (BASE / "mucum_event_2023.run").read_text(encoding="utf-8")
    run = re.sub(r"(?m)^Run:.*$", "Run: Calibracao", run, count=1)
    run = re.sub(r"(?m)^\s*Log File:.*$", "     Log File: calibracao.log", run, count=1)
    run = re.sub(r"(?m)^\s*DSS File:.*$", "     DSS File: calibracao.dss", run, count=1)
    (candidate / "mucum_event_2023.run").write_text(run, encoding="utf-8")
    return candidate


def jython_script(candidate: Path) -> Path:
    p = candidate.as_posix()
    script = candidate / "compute_and_score.script"
    script.write_text(
        f'''from hms.model.JythonHms import *
from hec.heclib.dss import HecDss
import math
import csv

project = r"{p}"
output = r"{p}/calibracao.dss"
OpenProject("mucum_event_2023", project)
Compute("Calibracao")

dss = HecDss.open(output)
sim = dss.get("//Saida_86472000/FLOW/01Sep2023/1Hour/RUN:Calibracao/")
obs = dss.get("//Saida_86472000/FLOW-OBSERVED/01Sep2023/1Hour/RUN:Calibracao/")
if sim is None or obs is None:
    raise ValueError("simulated or observed result series not found")

values = []
count = min(sim.numberValues, obs.numberValues)
for i in range(count):
    observed = float(obs.values[i])
    simulated = float(sim.values[i])
    if observed > -1.0e20 and simulated > -1.0e20:
        values.append((observed, simulated))
if not values:
    raise ValueError("no valid paired values")

mean_observed = sum(x[0] for x in values) / len(values)
mae = sum(abs(x[1] - x[0]) for x in values) / len(values)
rmse = math.sqrt(sum((x[1] - x[0]) ** 2 for x in values) / len(values))
denominator = sum((x[0] - mean_observed) ** 2 for x in values)
nse = 1.0 - sum((x[1] - x[0]) ** 2 for x in values) / denominator if denominator else None
observed_peak = max(x[0] for x in values)
simulated_peak = max(x[1] for x in values)
observed_peak_index = [i for i, x in enumerate(values) if x[0] == observed_peak][0]
simulated_peak_index = [i for i, x in enumerate(values) if x[1] == simulated_peak][0]

with open(r"{p}/series.csv", "wb") as handle:
    writer = csv.writer(handle)
    writer.writerow(["index", "observed_m3s", "simulated_m3s"])
    for i, pair in enumerate(values):
        writer.writerow([i, pair[0], pair[1]])

print("RESULT|count=%d|mae=%.10f|rmse=%.10f|nse=%.10f|observed_peak=%.10f|simulated_peak=%.10f|observed_peak_index=%d|simulated_peak_index=%d" % (len(values), mae, rmse, nse, observed_peak, simulated_peak, observed_peak_index, simulated_peak_index))
dss.close()
Exit(1)
''',
        encoding="utf-8",
    )
    return script


def parse_result(output: str) -> dict[str, float] | None:
    match = re.search(r"RESULT\|([^\r\n]+)", output)
    if not match:
        return None
    result: dict[str, float] = {}
    for item in match.group(1).split("|"):
        key, value = item.split("=", 1)
        result[key] = float(value)
    return result


def run_candidate(index: int, params: dict[str, float], timeout: int) -> dict[str, object]:
    candidate = make_candidate(index, params)
    script = jython_script(candidate)
    started = time.time()
    try:
        completed = subprocess.run(
            [str(HEC_CMD), "-s", str(script)],
            # HEC-HMS.cmd resolves its bundled JRE relative to its own folder.
            # The project path itself remains absolute, so each candidate is
            # still isolated while the launcher can find Java and its DLLs.
            cwd=str(HEC_CMD.parent),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
        parsed = parse_result(combined)
        result: dict[str, object] = {
            "index": index,
            **params,
            "returncode": completed.returncode,
            "seconds": round(time.time() - started, 3),
            "status": "ok" if parsed and completed.returncode == 0 else "failed",
        }
        if parsed:
            result.update(parsed)
        else:
            result["error_tail"] = combined[-2000:]
        return result
    except Exception as exc:  # keep the search resumable
        return {
            "index": index,
            **params,
            "status": "failed",
            "returncode": -1,
            "seconds": round(time.time() - started, 3),
            "error_tail": repr(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="run only the first N candidates")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--samples", type=int, default=180, help="random deterministic sample size for refine")
    parser.add_argument("--stage", choices=["coarse", "focal", "refine"], default="coarse")
    args = parser.parse_args()
    if not HEC_CMD.exists():
        raise SystemExit(f"HEC-HMS not found: {HEC_CMD}")
    SEARCH.mkdir(parents=True, exist_ok=True)
    if args.clean:
        for old in SEARCH.glob("candidate_*"):
            if old.is_dir():
                shutil.rmtree(old)
    parameter_grid = {
        "coarse": COARSE_GRID,
        "focal": FOCAL_GRID,
        "refine": REFINE_GRID,
    }[args.stage]
    keys = list(parameter_grid)
    combinations = [dict(zip(keys, values)) for values in itertools.product(*(parameter_grid[k] for k in keys))]
    if args.stage == "refine" and len(combinations) > args.samples:
        # Deterministic sampling keeps runtime bounded while covering all six
        # parameters. The focal winner is included explicitly as an anchor.
        anchor = {
            "initial_loss": 5.0,
            "constant_loss": 0.5,
            "tc_min": 60.0,
            "storage_min": 1.0,
            "recession_factor": 0.8,
            "initial_flow_area_ratio": 0.005,
        }
        rng = random.Random(20260902)
        remaining = [item for item in combinations if item != anchor]
        combinations = [anchor] + rng.sample(remaining, max(0, args.samples - 1))
    if args.limit:
        combinations = combinations[: args.limit]
    output = SEARCH / "calibration_search_results.csv"
    rows: list[dict[str, object]] = []
    for index, params in enumerate(combinations, 1):
        row = run_candidate(index, params, args.timeout)
        rows.append(row)
        valid = [r for r in rows if r.get("status") == "ok"]
        best = max(valid, key=lambda r: float(r.get("nse", -1.0e99))) if valid else None
        if best:
            print(
                "PROGRESS index=%d/%d ok=%d best_nse=%.6f best_rmse=%.3f"
                % (index, len(combinations), len(valid), float(best["nse"]), float(best["rmse"])),
                flush=True,
            )
        else:
            print("PROGRESS index=%d/%d ok=0" % (index, len(combinations)), flush=True)
        fields = sorted({key for row in rows for key in row})
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    valid = [r for r in rows if r.get("status") == "ok"]
    if valid:
        best = max(valid, key=lambda r: float(r.get("nse", -1.0e99)))
        (SEARCH / "calibration_search_best.json").write_text(
            json.dumps(best, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("BEST", json.dumps(best, ensure_ascii=False), flush=True)
    print("DONE", len(rows), "candidates", len(valid), "successful", flush=True)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
