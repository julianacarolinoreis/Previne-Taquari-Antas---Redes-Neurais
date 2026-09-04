#!/usr/bin/env python3
"""Search a small common-parameter set across the available nested replays.

The search deliberately uses one rainfall policy (the explicit 86472000 proxy
for every incremental area) and one parameter vector for every event.  This is
diagnostic evidence for generalisation, not an operational calibration.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEC_CMD = Path(r"D:\PREVINE\tools\hec-hms-4.13\portable\HEC-HMS-4.13\HEC-HMS.cmd")
BASE = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "network_replay_all_events"
DEFAULT_OUT = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "network_common_calibration_search"
WINDOWS = {
    "E19": ("06May2023", "1000", "08May2023", "1400"),
    "E22": ("04Sep2023", "0000", "12Sep2023", "0700"),
    "E24": ("16Nov2023", "0000", "25Nov2023", "2300"),
    "E27": ("29Apr2024", "1600", "09May2024", "2000"),
    "E28": ("16Jun2024", "1000", "25Jun2024", "0200"),
}


def candidates() -> list[dict[str, float]]:
    # The first six cover the main hydrologic trade-offs seen in the targeted
    # searches; the next six vary routing while holding transformation fixed;
    # the final six test a slower, less-lossy response without overfitting one
    # event.  All values are applied identically to the three increments.
    rows = [
        (1.0, 4.0, 4.0, 90.0, 0.98, 0.005, 1.0, 1.0),
        (0.0, 3.0, 4.0, 90.0, 0.98, 0.005, 0.25, 0.25),
        (1.0, 3.0, 4.0, 90.0, 0.98, 0.005, 1.0, 1.0),
        (2.5, 2.0, 10.0, 45.0, 0.80, 0.0025, 1.0, 1.0),
        (5.5, 0.88, 22.5, 34.3, 0.70, 0.001, 1.0, 1.0),
        (5.0, 1.0, 30.0, 60.0, 0.90, 0.001, 1.0, 1.0),
        (1.0, 4.0, 4.0, 90.0, 0.98, 0.005, 0.5, 0.5),
        (1.0, 4.0, 4.0, 90.0, 0.98, 0.005, 2.0, 2.0),
        (1.0, 4.0, 4.0, 90.0, 0.98, 0.005, 3.0, 3.0),
        (2.5, 2.0, 10.0, 45.0, 0.80, 0.0025, 0.5, 0.5),
        (2.5, 2.0, 10.0, 45.0, 0.80, 0.0025, 2.0, 2.0),
        (2.5, 2.0, 10.0, 45.0, 0.80, 0.0025, 3.0, 3.0),
        (0.0, 2.0, 10.0, 60.0, 0.85, 0.0025, 1.0, 1.0),
        (1.0, 2.0, 10.0, 60.0, 0.85, 0.0025, 1.0, 1.0),
        (2.5, 1.0, 20.0, 60.0, 0.80, 0.0025, 1.0, 1.0),
        (5.0, 2.0, 20.0, 60.0, 0.90, 0.001, 2.0, 2.0),
        (0.0, 4.0, 4.0, 90.0, 0.98, 0.005, 0.5, 0.5),
        (2.5, 3.0, 10.0, 60.0, 0.85, 0.0025, 1.0, 2.0),
    ]
    keys = ("initial_loss", "constant_loss", "tc", "storage", "recession", "initial_flow_ratio", "k1", "k2")
    return [dict(zip(keys, row)) for row in rows]


def replace_fields(text: str, field: str, values: list[float]) -> str:
    iterator = iter(values)
    pattern = re.compile(r"(?m)^(\s*" + re.escape(field) + r":\s*)[-+0-9.eE]+$")

    def repl(match: re.Match[str]) -> str:
        try:
            value = next(iterator)
        except StopIteration:
            return match.group(0)
        return match.group(1) + f"{value:.3f}"

    return pattern.sub(repl, text)


def parameterize(text: str, params: dict[str, float]) -> str:
    for field, key in (
        ("Initial Loss", "initial_loss"),
        ("Constant Loss Rate", "constant_loss"),
        ("Time of Concentration", "tc"),
        ("Storage Coefficient", "storage"),
        ("Recession Factor", "recession"),
        ("Initial Flow/Area Ratio", "initial_flow_ratio"),
    ):
        text = replace_fields(text, field, [params[key]] * 3)
    return replace_fields(text, "Muskingum K", [params["k1"], params["k2"]])


def metric_script(event_id: str, project_dir: Path) -> str:
    project = project_dir.as_posix()
    output = (project_dir / "output.dss").as_posix()
    start_date, start_time, end_date, end_time = WINDOWS[event_id]
    return f'''from hms.model.JythonHms import *
from hec.heclib.dss import HecDss
from hec.heclib.util import HecTime
import math

OpenProject("taquari_antas_{event_id}", "{project}")
Compute("Calibracao")
dss = HecDss.open("{output}")
sim = {{}}
obs = {{}}
def values_by_time(series):
    return {{int(series.times[i]): float(series.values[i]) for i in range(series.numberValues)}}
for pathname in list(dss.getCatalogedPathnames()):
    if pathname.startswith("//J_MUCUM_{event_id}/") and "/FLOW/" in pathname and "/RUN:Calibracao/" in pathname:
        sim.update(values_by_time(dss.get(pathname)))
    if pathname.startswith("//J_MUCUM_{event_id}/") and "/FLOW-OBSERVED/" in pathname and "/RUN:Calibracao/" in pathname:
        obs.update(values_by_time(dss.get(pathname)))
start = HecTime("{start_date}", "{start_time}").value()
end = HecTime("{end_date}", "{end_time}").value()
pairs = [(t, obs[t], sim[t]) for t in sorted(set(sim).intersection(obs)) if start <= t <= end and obs[t] > -1.0e20 and sim[t] > -1.0e20]
if len(pairs) < 24:
    raise ValueError("less than 24 paired hours")
mean_obs = sum(p[1] for p in pairs) / len(pairs)
ss_res = sum((p[2] - p[1]) ** 2 for p in pairs)
ss_tot = sum((p[1] - mean_obs) ** 2 for p in pairs)
obs_peak = max(pairs, key=lambda p: p[1])
sim_peak = max(pairs, key=lambda p: p[2])
nse = 1.0 - ss_res / ss_tot
mae = sum(abs(p[2] - p[1]) for p in pairs) / len(pairs)
lag = (sim_peak[0] - obs_peak[0]) / 60.0
peak_error = abs(sim_peak[2] - obs_peak[1]) / obs_peak[1]
print("METRIC|%d|%.10f|%.10f|%.10f|%.10f|%.10f|%.10f|%.10f" % (len(pairs), mae, math.sqrt(ss_res / len(pairs)), nse, obs_peak[1], sim_peak[2], lag, peak_error))
dss.close()
Exit(1)
'''


def run_event(base: Path, candidate: Path, event_id: str, params: dict[str, float]) -> dict:
    source = base / event_id
    target = candidate / event_id
    target.mkdir(parents=True, exist_ok=True)
    prefix = f"taquari_antas_{event_id}"
    for filename in (f"{prefix}.hms", f"{prefix}.run", f"{prefix}.gage", f"chuva_{event_id}.met", f"evento_{event_id}.control"):
        shutil.copy2(source / filename, target / filename)
    # Event packages can legitimately use one DSS for both observed rain and
    # flow (E24) or separate DSS files. Copy only what the package contains;
    # never fabricate a missing rainfall/flow file.
    for filename in ("rain.dss", "target.dss", "event.dss"):
        if (source / filename).exists():
            shutil.copy2(source / filename, target / filename)
    basin = parameterize((source / f"bacia_{event_id}.basin").read_text(encoding="utf-8"), params)
    (target / f"bacia_{event_id}.basin").write_text(basin, encoding="utf-8")
    script = target / "common_search.script"
    script.write_text(metric_script(event_id, target), encoding="utf-8")
    result = subprocess.run([str(HEC_CMD), "-s", str(script)], cwd=HEC_CMD.parent, capture_output=True, text=True, timeout=180, check=False)
    combined = result.stdout + "\n" + result.stderr
    (target / "common_search_stdout.txt").write_text(combined, encoding="utf-8")
    metric_line = next((line for line in combined.splitlines() if "METRIC|" in line), None)
    if not metric_line:
        return {"event_id": event_id, **params, "status": "failed", "returncode": result.returncode, "tail": combined[-500:]}
    parts = metric_line.split("METRIC|", 1)[1].split("|")
    row = {"event_id": event_id, **params, "pairs": int(parts[0]), "mae_m3s": float(parts[1]), "rmse_m3s": float(parts[2]), "nse": float(parts[3]), "observed_peak_m3s": float(parts[4]), "simulated_peak_m3s": float(parts[5]), "peak_lag_hours": float(parts[6]), "peak_relative_error": float(parts[7]), "status": "ok"}
    return row


def aggregate(rows: list[dict], candidate_id: int, params: dict[str, float]) -> dict:
    good = [row for row in rows if row.get("status") == "ok"]
    if len(good) != len(WINDOWS):
        return {"candidate_id": candidate_id, **params, "status": "incomplete", "events_ok": len(good), "events_expected": len(WINDOWS)}
    mean_nse = sum(row["nse"] for row in good) / len(good)
    mean_abs_lag = sum(abs(row["peak_lag_hours"]) for row in good) / len(good)
    mean_peak_error = sum(row["peak_relative_error"] for row in good) / len(good)
    median_nse = sorted(row["nse"] for row in good)[len(good) // 2]
    return {"candidate_id": candidate_id, **params, "events_ok": len(good), "mean_nse": mean_nse, "median_nse": median_nse, "mean_abs_lag_hours": mean_abs_lag, "mean_peak_relative_error": mean_peak_error, "research_score": mean_nse - 0.02 * mean_abs_lag - 0.2 * mean_peak_error, "status": "common_parameter_diagnostic"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    pool = candidates()[: args.limit or None]
    aggregates = []
    event_rows = []
    for index, params in enumerate(pool, start=1):
        candidate_dir = out / f"candidate_{index:03d}"
        rows = [dict(run_event(BASE, candidate_dir, event_id, params), candidate_id=index) for event_id in WINDOWS]
        aggregates.append(aggregate(rows, index, params))
        event_rows.extend(rows)
        print(f"candidate {index}/{len(pool)} complete")
    good = [row for row in aggregates if row.get("status") == "common_parameter_diagnostic"]
    good.sort(key=lambda row: row["research_score"], reverse=True)
    with (out / "common_search_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in aggregates for key in row}))
        writer.writeheader(); writer.writerows(aggregates)
    with (out / "common_search_event_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in event_rows for key in row}))
        writer.writeheader(); writer.writerows(event_rows)
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "purpose": "busca diagnóstica de parâmetros comuns; não é calibração promovida", "rainfall_policy": "86472000 explicit proxy applied to all three incremental areas", "events": list(WINDOWS), "candidates": len(pool), "successful_common_candidates": len(good), "best_by_research_score": good[0] if good else None, "artifacts": ["common_search_summary.csv", "common_search_event_metrics.csv"]}
    (out / "common_search_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
