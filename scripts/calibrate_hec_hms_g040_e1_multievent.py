#!/usr/bin/env python3
"""Multi-event E1 calibration search for the G040 branch model.

The fixed calibration set is E22_SEP2023 + E24_NOV2023. Validation and holdout
events are deliberately excluded from parameter selection. Every candidate is
run through the same HEC-HMS runner and scored across all available checkpoints.

The output is a research calibration candidate, never an operational promotion.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "assets/data/hec_hms_g040_full_basin"
RUNNER = ROOT / "scripts/run_hec_hms_g040_e1_hindcast.py"
FORCING = BASE / "historical_calibration_forcing"
RUNROOT = BASE / "g040_e1_multievent_runs"
OUT = BASE / "g040_e1_multievent_calibration_latest.json"
OUTCSV = BASE / "g040_e1_multievent_calibration_candidates.csv"

CAL_EVENTS = ("E22_SEP2023", "E24_NOV2023")
VALIDATION_EVENTS = ("E27_MAY2024", "E28_JUN2024")
HOLDOUT_EVENTS = ("E2026_JUL",)

BOUNDS = {
    "cn": (28.505926, 73.418, "linear"),
    "lag_min": (15.847934, 465.546, "log"),
    "k_g1": (1.0, 6.0, "linear"),
    "k_g2": (0.5, 3.0, "linear"),
    "k_g3": (0.5, 10.0, "linear"),
    "k_g4": (0.5, 12.0, "linear"),
    "x": (0.10, 0.30, "linear"),
}
PRIMES = {"cn": 2, "lag_min": 3, "k_g1": 5, "k_g2": 7, "k_g3": 11, "k_g4": 13, "x": 17}


def vdc(n: int, base: int) -> float:
    value = 0.0
    denom = 1.0
    while n:
        n, rem = divmod(n, base)
        denom *= base
        value += rem / denom
    return value


def scale(u: float, bound: tuple[float, float, str]) -> float:
    lo, hi, mode = bound
    if mode == "log":
        return math.exp(math.log(lo) + u * (math.log(hi) - math.log(lo)))
    return lo + u * (hi - lo)


def design(n: int) -> list[dict[str, Any]]:
    rows = [
        {
            "candidate_id": "ANCHOR_EVENT2_MEDIAN",
            "cn": 43.22047,
            "lag_min": 55.11625,
            "k_g1": 3.5,
            "k_g2": 1.5,
            "k_g3": 5.0,
            "k_g4": 6.0,
            "x": 0.2,
        },
        {
            "candidate_id": "ANCHOR_LEGACY_MEDIAN",
            "cn": 68.22,
            "lag_min": 187.55,
            "k_g1": 3.5,
            "k_g2": 1.5,
            "k_g3": 5.0,
            "k_g4": 6.0,
            "x": 0.2,
        },
    ]
    for i in range(1, n + 1):
        row = {"candidate_id": f"QMC_{i:02d}"}
        for key, bound in BOUNDS.items():
            row[key] = scale(vdc(i, PRIMES[key]), bound)
        rows.append(row)
    return rows


def event_paths(event_id: str) -> tuple[Path, Path, Path]:
    d = FORCING / event_id
    return d / "rain.json", d / "hydro.json", d / "scenario.json"


def run_event(hec: str, row: dict[str, Any], event_id: str) -> dict[str, Any]:
    rain, hydro, scenario = event_paths(event_id)
    for path in (rain, hydro, scenario):
        if not path.exists():
            return {
                "event_id": event_id,
                "compute_ok": False,
                "error": f"missing calibration forcing: {path}",
            }

    run_id = f"{row['candidate_id']}__{event_id}"
    cmd = [
        sys.executable,
        "-B",
        str(RUNNER),
        hec,
        "--candidate-id",
        run_id,
        "--event-id",
        event_id,
        "--rain-file",
        str(rain),
        "--hydro-file",
        str(hydro),
        "--scenario-file",
        str(scenario),
        "--output-root",
        str(RUNROOT),
        "--cn",
        str(row["cn"]),
        "--lag-min",
        str(row["lag_min"]),
        "--k-g1",
        str(row["k_g1"]),
        "--k-g2",
        str(row["k_g2"]),
        "--k-g3",
        str(row["k_g3"]),
        "--k-g4",
        str(row["k_g4"]),
        "--x",
        str(row["x"]),
    ]
    p = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=420,
        check=False,
    )
    result_path = RUNROOT / run_id / "result.json"
    if not result_path.exists():
        return {
            "event_id": event_id,
            "compute_ok": False,
            "runner_returncode": p.returncode,
            "error": "result.json missing",
            "stdout_tail": p.stdout[-2500:],
            "stderr_tail": p.stderr[-2500:],
        }
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["runner_returncode"] = p.returncode
    return result


def metric_penalty(metric: dict[str, Any]) -> float | None:
    if not isinstance(metric, dict) or int(metric.get("pairs") or 0) < 4:
        return None
    terms = []
    nse = metric.get("nse")
    kge = metric.get("kge")
    nrmse = metric.get("normalized_rmse")
    if nse is not None:
        terms.append(max(0.0, 1 - float(nse)))
    if kge is not None:
        terms.append(max(0.0, 1 - float(kge)))
    if nrmse is not None:
        terms.append(abs(float(nrmse)))
    if metric.get("pbias_pct") is not None:
        terms.append(abs(float(metric["pbias_pct"])) / 100)
    if metric.get("peak_error_pct") is not None:
        terms.append(abs(float(metric["peak_error_pct"])) / 100)
    if metric.get("peak_timing_error_h") is not None:
        terms.append(abs(float(metric["peak_timing_error_h"])) / 12)
    if metric.get("rise_fall_sign_skill") is not None:
        terms.append(max(0.0, 1 - float(metric["rise_fall_sign_skill"])))
    return sum(terms) / len(terms) if terms else None


def checkpoint_gate(metric: dict[str, Any]) -> bool:
    if not isinstance(metric, dict) or int(metric.get("pairs") or 0) < 12:
        return False
    return (
        metric.get("nse") is not None
        and float(metric["nse"]) >= 0.50
        and metric.get("pbias_pct") is not None
        and abs(float(metric["pbias_pct"])) <= 20
        and metric.get("peak_error_pct") is not None
        and abs(float(metric["peak_error_pct"])) <= 20
        and metric.get("peak_timing_error_h") is not None
        and abs(float(metric["peak_timing_error_h"])) <= 3
        and metric.get("rise_fall_sign_skill") is not None
        and float(metric["rise_fall_sign_skill"]) >= 0.65
    )


def summarize_candidate(row: dict[str, Any], event_results: list[dict[str, Any]]) -> dict[str, Any]:
    event_summaries = []
    all_penalties = []
    total_gates = 0
    total_valid = 0
    contributing_events = 0

    for event in event_results:
        scores = event.get("scores") or {}
        valid = {
            code: metric
            for code, metric in scores.items()
            if isinstance(metric, dict) and int(metric.get("pairs") or 0) >= 12
        }
        penalties = [metric_penalty(metric) for metric in valid.values()]
        penalties = [x for x in penalties if x is not None]
        gates = sum(checkpoint_gate(metric) for metric in valid.values())
        if len(valid) >= 2:
            contributing_events += 1
        total_valid += len(valid)
        total_gates += gates
        all_penalties.extend(penalties)

        event_summaries.append({
            "event_id": event.get("event_id"),
            "compute_ok": bool(event.get("compute_ok")),
            "window": event.get("window"),
            "valid_checkpoint_count": len(valid),
            "checkpoint_gate_pass_count": gates,
            "mean_multi_metric_penalty": (
                sum(penalties) / len(penalties) if penalties else None
            ),
            "scores": scores,
            "error": event.get("error"),
        })

    eligible = (
        contributing_events == len(CAL_EVENTS)
        and all(bool(event.get("compute_ok")) for event in event_results)
        and total_valid >= 4
    )
    return {
        "candidate_id": row["candidate_id"],
        "parameters": {
            key: row[key]
            for key in ("cn", "lag_min", "k_g1", "k_g2", "k_g3", "k_g4", "x")
        },
        "eligible_for_calibration_ranking": eligible,
        "contributing_event_count": contributing_events,
        "valid_checkpoint_event_count": total_valid,
        "checkpoint_gate_pass_count": total_gates,
        "mean_multi_metric_penalty": (
            sum(all_penalties) / len(all_penalties) if all_penalties else None
        ),
        "events": event_summaries,
    }


def rank_key(row: dict[str, Any]) -> tuple:
    return (
        0 if row.get("eligible_for_calibration_ranking") else 1,
        -int(row.get("checkpoint_gate_pass_count") or 0),
        float("inf")
        if row.get("mean_multi_metric_penalty") is None
        else float(row["mean_multi_metric_penalty"]),
    )


def write_csv(rows: list[dict[str, Any]]) -> None:
    fields = [
        "rank",
        "candidate_id",
        "eligible",
        "contributing_event_count",
        "valid_checkpoint_event_count",
        "checkpoint_gate_pass_count",
        "mean_multi_metric_penalty",
        "cn",
        "lag_min",
        "k_g1",
        "k_g2",
        "k_g3",
        "k_g4",
        "x",
    ]
    with OUTCSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for rank, row in enumerate(rows, 1):
            p = row.get("parameters") or {}
            writer.writerow({
                "rank": rank,
                "candidate_id": row.get("candidate_id"),
                "eligible": row.get("eligible_for_calibration_ranking"),
                "contributing_event_count": row.get("contributing_event_count"),
                "valid_checkpoint_event_count": row.get("valid_checkpoint_event_count"),
                "checkpoint_gate_pass_count": row.get("checkpoint_gate_pass_count"),
                "mean_multi_metric_penalty": row.get("mean_multi_metric_penalty"),
                **{key: p.get(key) for key in ("cn", "lag_min", "k_g1", "k_g2", "k_g3", "k_g4", "x")},
            })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("hec_hms_sh")
    ap.add_argument("--qmc", type=int, default=6)
    args = ap.parse_args()

    candidates = design(max(4, min(24, args.qmc)))
    RUNROOT.mkdir(parents=True, exist_ok=True)
    results = []

    for i, row in enumerate(candidates, 1):
        print(f"[{i}/{len(candidates)}] candidate {row['candidate_id']}", flush=True)
        event_results = []
        for event_id in CAL_EVENTS:
            print(f"  -> {event_id}", flush=True)
            try:
                result = run_event(args.hec_hms_sh, row, event_id)
            except Exception as exc:
                result = {
                    "event_id": event_id,
                    "compute_ok": False,
                    "error": str(exc),
                }
            event_results.append(result)
        results.append(summarize_candidate(row, event_results))

    ranked = sorted(results, key=rank_key)
    best = next(
        (row for row in ranked if row.get("eligible_for_calibration_ranking")),
        ranked[0] if ranked else None,
    )
    write_csv(ranked)

    payload = {
        "schema_version": "g040_e1_multievent_calibration_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "research_only": True,
        "status": "MULTIEVENT_CALIBRATION_SEARCH_COMPLETE_NO_PROMOTION",
        "fixed_split": {
            "calibration": list(CAL_EVENTS),
            "independent_validation": list(VALIDATION_EVENTS),
            "pseudo_operational_holdout": list(HOLDOUT_EVENTS),
            "no_leakage": True,
        },
        "method": {
            "candidate_count": len(candidates),
            "design": "2 report-derived anchors + deterministic Van der Corput/QMC",
            "bounds": BOUNDS,
            "ranking": "require both calibration events to contribute >=2 checkpoints; maximize checkpoint gates; then minimize mean multi-metric penalty",
            "checkpoint_gate": "pairs>=12, NSE>=0.50, |PBIAS|<=20%, |peak error|<=20%, |peak timing|<=3h, rise/fall sign skill>=0.65",
            "selection_variables": [
                "CN",
                "SCS lag",
                "four aggregate Muskingum K groups",
                "Muskingum X",
            ],
        },
        "best_calibration_candidate": best,
        "ranked_candidates": ranked,
        "parameter_freeze_rule": (
            "The best candidate may be frozen for validation, but validation/holdout "
            "results must not be used to retune these parameters."
        ),
        "promotion_allowed": False,
        "next_step": (
            "Build E27_MAY2024 and E28_JUN2024 forcing packages, run the frozen "
            "best calibration candidate, and report validation skill without retuning."
        ),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "best": None if best is None else {
            "candidate_id": best.get("candidate_id"),
            "eligible": best.get("eligible_for_calibration_ranking"),
            "gate_passes": best.get("checkpoint_gate_pass_count"),
            "penalty": best.get("mean_multi_metric_penalty"),
        },
    }, ensure_ascii=False))

    return 0 if any(row.get("eligible_for_calibration_ranking") for row in ranked) else 2


if __name__ == "__main__":
    raise SystemExit(main())
