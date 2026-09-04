#!/usr/bin/env python3
"""Search a two-station nested HEC-HMS network on complete events.

This is a diagnostic experiment. It keeps the BHO6 nested network and gives
the upstream Antas area the 86472000 rainfall and the two downstream
increments the 86510000 rainfall. Only E19 and E28 are included because they
have complete hourly rainfall and target flow in the audited score windows.
"""

from __future__ import annotations

import csv
import json
import random
import re
import shutil
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

from build_hec_hms_network_station_distributed import blocks, build_event, run_event, set_gage
from extract_hec_hms_network_all_events import extract_event, score


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "network_two_station_search"
RAIN_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_two_station_rain_complete_v2.dss"
EVENTS = ("E19", "E28")


def candidates(count: int) -> list[dict[str, float]]:
    keys = ("initial_loss", "constant_loss", "tc", "storage", "recession", "initial_flow_ratio", "k")
    grid = {
        "initial_loss": [0.0, 1.0, 2.5, 5.0, 10.0],
        "constant_loss": [0.5, 1.0, 2.0, 3.0, 4.0],
        "tc": [0.5, 1.0, 4.0, 10.0, 20.0, 30.0, 45.0, 60.0],
        "storage": [10.0, 20.0, 30.0, 45.0, 60.0, 90.0],
        "recession": [0.7, 0.8, 0.9, 0.95, 0.98],
        "initial_flow_ratio": [0.001, 0.003, 0.005, 0.01],
        "k": [0.25, 0.5, 1.0, 2.0, 3.0],
    }
    anchors = [
        (2.5, 2.0, 25.0, 45.0, 0.8, 0.003, 1.0),
        (1.0, 4.0, 4.0, 90.0, 0.98, 0.005, 1.0),
        (10.0, 1.0, 60.0, 60.0, 0.9, 0.001, 1.0),
        (5.0, 0.5, 20.0, 30.0, 0.7, 0.0025, 0.5),
        (0.0, 3.0, 10.0, 20.0, 0.8, 0.005, 2.0),
    ]
    pool = [dict(zip(keys, values)) for values in product(*(grid[key] for key in keys))]
    rng = random.Random(20260904)
    rng.shuffle(pool)
    ordered: list[dict[str, float]] = []
    for values in anchors + [tuple(item[key] for key in keys) for item in pool]:
        candidate = dict(zip(keys, values))
        if candidate not in ordered:
            ordered.append(candidate)
        if len(ordered) >= count:
            break
    return ordered


def add_target_rain_gage(text: str, event_id: str) -> str:
    source = next(block for block in blocks(text, "Gage: ") if f"Gage: Chuva_86472000_{event_id}" in block)
    target = source.replace(f"Chuva_86472000_{event_id}", f"Chuva_86510000_{event_id}")
    target = target.replace("86472000", "86510000")
    target = re.sub(r"(?m)^\s*Description: .*?$", "     Description: Chuva ANA 86510000 para os incrementos finais", target)
    flow = next(block for block in blocks(text, "Gage: ") if f"Gage: Q_{event_id}" in block)
    return text.replace(flow, target.strip() + "\n\n" + flow, 1)


def configure_event(candidate_dir: Path, event_id: str, params: dict[str, float]) -> Path:
    build_event(event_id, candidate_dir, set(), "common", params_override=params)
    event_dir = candidate_dir / event_id
    met_path = event_dir / f"chuva_{event_id}.met"
    met = met_path.read_text(encoding="utf-8")
    for subbasin in (f"SB_INC_STZ_{event_id}", f"SB_INC_MUCUM_{event_id}"):
        met = set_gage(met, subbasin, f"Chuva_86510000_{event_id}")
    met_path.write_text(met, encoding="utf-8")
    gage_path = event_dir / f"taquari_antas_{event_id}.gage"
    gage_path.write_text(add_target_rain_gage(gage_path.read_text(encoding="utf-8"), event_id), encoding="utf-8")
    shutil.copy2(RAIN_DSS, event_dir / "rain.dss")
    manifest_path = event_dir / "event_network_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "rainfall_policy": "86472000 no alto Antas; 86510000 nos incrementos a jusante de Santa Tereza",
        "two_station_diagnostic": True,
        "rainfall_source": str(RAIN_DSS.relative_to(ROOT)),
        "gage_mapping": {
            f"SB_ANTAS_{event_id}": f"Chuva_86472000_{event_id}",
            f"SB_INC_STZ_{event_id}": f"Chuva_86510000_{event_id}",
            f"SB_INC_MUCUM_{event_id}": f"Chuva_86510000_{event_id}",
        },
        "status": "replay_scored_not_promoted",
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return event_dir


def run_candidate(index: int, params: dict[str, float]) -> dict[str, object]:
    candidate_dir = OUT / "search" / f"candidate_{index:03d}"
    if candidate_dir.exists():
        shutil.rmtree(candidate_dir)
    candidate_dir.mkdir(parents=True, exist_ok=True)
    metrics = []
    for event_id in EVENTS:
        event_dir = configure_event(candidate_dir, event_id, params)
        run = run_event(event_id, event_dir)
        if not run["ok_marker"]:
            return {"candidate_id": index, **params, "status": "failed", "returncode": run["returncode"], "failed_event": event_id}
        metrics.append(score(event_id, extract_event(event_id, event_dir)))
    mean_nse = sum(float(item["nse"]) for item in metrics) / len(metrics)
    mean_lag = sum(abs(float(item["peak_lag_hours"])) for item in metrics) / len(metrics)
    mean_peak_error = sum(float(item["peak_relative_error"]) for item in metrics) / len(metrics)
    row: dict[str, object] = {
        "candidate_id": index,
        **params,
        "status": "replay_scored_not_promoted",
        "events": len(metrics),
        "mean_nse": mean_nse,
        "mean_abs_peak_lag_hours": mean_lag,
        "mean_peak_relative_error": mean_peak_error,
        "research_score": mean_nse - 0.01 * mean_lag - 0.2 * mean_peak_error,
        "event_metrics": metrics,
    }
    return row


def main() -> int:
    import argparse

    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    OUT = args.output.resolve()
    if not RAIN_DSS.exists():
        raise SystemExit(f"missing rainfall DSS: {RAIN_DSS}")
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    pool = candidates(args.count)
    for index, params in enumerate(pool, 1):
        row = run_candidate(index, params)
        rows.append(row)
        print("PROGRESS %d/%d status=%s score=%s" % (index, len(pool), row.get("status"), row.get("research_score", "NA")), flush=True)
    good = [row for row in rows if row.get("status") == "replay_scored_not_promoted"]
    good.sort(key=lambda row: float(row["research_score"]), reverse=True)
    flat = []
    for row in good:
        item = {key: value for key, value in row.items() if key != "event_metrics"}
        flat.append(item)
    fields = sorted({key for row in flat for key in row})
    with (OUT / "two_station_search.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(flat)
    report = {
        "schema_version": "hec_hms_two_station_network_search_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "busca diagnóstica na rede HEC-HMS com dois postos; não é calibração promovida nem operação",
        "events": list(EVENTS),
        "rainfall_policy": "86472000 no alto Antas; 86510000 nos incrementos a jusante de Santa Tereza",
        "candidate_count": len(rows),
        "successful_candidates": len(good),
        "best_by_research_score": good[0] if good else None,
        "artifacts": ["two_station_search.csv"],
        "limitation": "a chuva de 86510000 continua sendo uma hipótese espacial; faltam séries completas de chuva no posto intermediário para uma calibração multi-evento de três zonas",
    }
    (OUT / "two_station_search_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
