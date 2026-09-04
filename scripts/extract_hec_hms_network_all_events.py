#!/usr/bin/env python3
"""Extract and score all executed BHO6-network HEC-HMS event replays."""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEC_CMD = Path(r"D:\PREVINE\tools\hec-hms-4.13\portable\HEC-HMS-4.13\HEC-HMS.cmd")
DEFAULT_ROOT = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "network_replay_all_events"
WINDOWS = {
    "E19": ("06May2023", "1000", "08May2023", "1400"),
    "E22": ("04Sep2023", "0000", "12Sep2023", "0700"),
    "E24": ("16Nov2023", "0000", "25Nov2023", "2300"),
    "E27": ("29Apr2024", "1600", "09May2024", "2000"),
    "E28": ("16Jun2024", "1000", "25Jun2024", "0200"),
}


def jython_text(event_id: str, project_dir: Path) -> str:
    project = project_dir.as_posix()
    output = (project_dir / "output.dss").as_posix()
    pairs = (project_dir / "network_pairs_scored.csv").as_posix()
    start_date, start_time, end_date, end_time = WINDOWS[event_id]
    return f'''from hms.model.JythonHms import *
from hec.heclib.dss import HecDss
from hec.heclib.util import HecTime
import csv

OpenProject("taquari_antas_{event_id}", "{project}")
dss = HecDss.open("{output}")
paths = list(dss.getCatalogedPathnames())
sim = {{}}
obs = {{}}
def values_by_time(series):
    return {{int(series.times[i]): float(series.values[i]) for i in range(series.numberValues)}}
for pathname in paths:
    if pathname.startswith("//J_MUCUM_{event_id}/") and "/FLOW/" in pathname and "/RUN:Calibracao/" in pathname:
        sim.update(values_by_time(dss.get(pathname)))
    if pathname.startswith("//J_MUCUM_{event_id}/") and "/FLOW-OBSERVED/" in pathname and "/RUN:Calibracao/" in pathname:
        obs.update(values_by_time(dss.get(pathname)))
start = HecTime("{start_date}", "{start_time}").value()
end = HecTime("{end_date}", "{end_time}").value()
handle = open(r"{pairs}", "wb")
writer = csv.writer(handle)
writer.writerow(["time_value", "observed_m3s", "simulated_m3s"])
count = 0
for t in sorted(set(sim).intersection(obs)):
    if start <= t <= end and obs[t] > -1.0e20 and sim[t] > -1.0e20:
        writer.writerow([t, obs[t], sim[t]])
        count += 1
handle.close()
print("NETWORK_{event_id}_PAIRED=%d" % count)
dss.close()
Exit(1)
'''


def extract_event(event_id: str, project_dir: Path) -> list[tuple[int, float, float]]:
    script = project_dir / "extract_network.script"
    script.write_text(jython_text(event_id, project_dir), encoding="utf-8")
    result = subprocess.run(
        [str(HEC_CMD), "-s", str(script)],
        cwd=HEC_CMD.parent,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    (project_dir / "extract_stdout.txt").write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
    if not (project_dir / "network_pairs_scored.csv").exists():
        raise RuntimeError(f"missing pair file for {event_id}; HEC return code {result.returncode}")
    rows = []
    with (project_dir / "network_pairs_scored.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append((int(float(row["time_value"])), float(row["observed_m3s"]), float(row["simulated_m3s"])))
    return rows


def score(event_id: str, pairs: list[tuple[int, float, float]]) -> dict:
    if len(pairs) < 24:
        return {"event_id": event_id, "pairs": len(pairs), "status": "blocked_less_than_24_pairs"}
    mean_obs = sum(row[1] for row in pairs) / len(pairs)
    ss_res = sum((row[2] - row[1]) ** 2 for row in pairs)
    ss_tot = sum((row[1] - mean_obs) ** 2 for row in pairs)
    observed_peak = max(pairs, key=lambda row: row[1])
    simulated_peak = max(pairs, key=lambda row: row[2])
    return {
        "event_id": event_id,
        "pairs": len(pairs),
        "mae_m3s": sum(abs(row[2] - row[1]) for row in pairs) / len(pairs),
        "rmse_m3s": math.sqrt(ss_res / len(pairs)),
        "nse": None if ss_tot == 0 else 1.0 - ss_res / ss_tot,
        "observed_peak_m3s": observed_peak[1],
        "simulated_peak_m3s": simulated_peak[2],
        "peak_lag_hours": (simulated_peak[0] - observed_peak[0]) / 60.0,
        "peak_relative_error": abs(simulated_peak[2] - observed_peak[1]) / observed_peak[1],
        "status": "replay_scored_not_promoted",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    metrics = []
    all_series = []
    for event_id in WINDOWS:
        pairs = extract_event(event_id, root / event_id)
        metrics.append(score(event_id, pairs))
        all_series.extend({"event_id": event_id, "time_value": t, "observed_m3s": obs, "simulated_m3s": sim} for t, obs, sim in pairs)
    with (root / "network_metrics_all_events.csv").open("w", newline="", encoding="utf-8") as handle:
        fieldnames = sorted({key for row in metrics for key in row})
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(metrics)
    with (root / "network_series_all_events.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["event_id", "time_value", "observed_m3s", "simulated_m3s"])
        writer.writeheader()
        writer.writerows(all_series)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "replay HEC-HMS de pesquisa; nao e alerta nem autorizacao operacional",
        "network": "ANA BHO6 nested incremental areas 86472000 -> 86472600 -> 86510000",
        "events": metrics,
        "excluded": {"E26": "sem entrada HEC-HMS reconciliada nesta rodada"},
        "artifacts": ["network_metrics_all_events.csv", "network_series_all_events.csv"],
    }
    (root / "network_metrics_all_events.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if all(row.get("status") == "replay_scored_not_promoted" for row in metrics) else 1


if __name__ == "__main__":
    raise SystemExit(main())
