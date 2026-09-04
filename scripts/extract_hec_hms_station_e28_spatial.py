#!/usr/bin/env python3
"""Extract the simulated flow at Santa Tereza and Muçum for E28."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEC_CMD = Path(r"D:\PREVINE\tools\hec-hms-4.13\portable\HEC-HMS-4.13\HEC-HMS.cmd")
DEFAULT_PROJECT = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "network_station_e28_calibration_search" / "candidate_033" / "E28"


def extraction_script(project: Path, output_csv: Path) -> str:
    return f'''from hec.heclib.dss import HecDss
from hms.model.JythonHms import Exit

dss = HecDss.open("{(project / "output.dss").as_posix()}")
def values(path):
    s = dss.get(path)
    return {{int(s.times[i]): float(s.values[i]) for i in range(s.numberValues) if float(s.values[i]) > -1.0e20}}

stz = values("//J_STZ_E28/FLOW/01Jun2024/1Hour/RUN:Calibracao/")
mucum = values("//J_MUCUM_E28/FLOW/01Jun2024/1Hour/RUN:Calibracao/")
observed = values("//J_MUCUM_E28/FLOW-OBSERVED/01Jun2024/1Hour/RUN:Calibracao/")
handle = open(r"{output_csv.as_posix()}", "wb")
handle.write(b"time_value,santa_tereza_sim_m3s,mucum_sim_m3s,mucum_observed_m3s\\n")
for t in sorted(set(stz).union(mucum).union(observed)):
    row = "%d,%s,%s,%s\\n" % (t, stz.get(t, ""), mucum.get(t, ""), observed.get(t, ""))
    handle.write(row.encode("utf-8"))
handle.close()
print("SPATIAL_E28_ROWS=%d" % len(set(stz).union(mucum).union(observed)))
dss.close()
Exit(1)
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    args = parser.parse_args()
    project = args.project.resolve()
    output_csv = project / "spatial_series_e28.csv"
    script = project / "extract_spatial_e28.script"
    script.write_text(extraction_script(project, output_csv), encoding="utf-8")
    result = subprocess.run([str(HEC_CMD), "-s", str(script)], cwd=HEC_CMD.parent, capture_output=True, text=True, timeout=180, check=False)
    (project / "extract_spatial_e28_stdout.txt").write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
    if not output_csv.exists():
        raise RuntimeError("HEC-HMS did not create the spatial series")
    raw_rows = list(csv.DictReader(output_csv.open(encoding="utf-8")))
    # HEC-DSS stores regular hourly timestamps as minutes since 1899-12-31.
    # Keep the original integer for traceability and add a human-readable local
    # label so the dashboard does not expose an opaque DSS time value.
    dss_epoch = datetime(1899, 12, 31)
    rows = []
    for row in raw_rows:
        row["time_local"] = (dss_epoch + timedelta(minutes=int(row["time_value"]))).strftime("%Y-%m-%d %H:%M")
        rows.append(row)
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["time_value", "time_local", "santa_tereza_sim_m3s", "mucum_sim_m3s", "mucum_observed_m3s"])
        writer.writeheader()
        writer.writerows(rows)
    def finite(key: str) -> list[float]:
        return [float(row[key]) for row in rows if row.get(key)]
    stz_values = finite("santa_tereza_sim_m3s")
    mucum_values = finite("mucum_sim_m3s")
    obs_values = finite("mucum_observed_m3s")
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "série espacial simulada do candidato E28; não é alerta nem validação observacional em Santa Tereza",
        "event_id": "E28",
        "candidate_id": 33,
        "nodes": {
            "santa_tereza": {"pathname": "//J_STZ_E28/FLOW/.../RUN:Calibracao/", "simulated_points": len(stz_values), "simulated_peak_m3s": max(stz_values) if stz_values else None},
            "mucum": {"pathname": "//J_MUCUM_E28/FLOW/.../RUN:Calibracao/", "simulated_points": len(mucum_values), "simulated_peak_m3s": max(mucum_values) if mucum_values else None, "observed_points": len(obs_values), "observed_peak_m3s": max(obs_values) if obs_values else None},
        },
        "artifacts": ["spatial_series_e28.csv"],
    }
    (project / "spatial_series_e28_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if result.returncode == 0 and stz_values and mucum_values and obs_values else 1


if __name__ == "__main__":
    raise SystemExit(main())
