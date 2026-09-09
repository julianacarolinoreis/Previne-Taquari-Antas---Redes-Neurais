#!/usr/bin/env python3
"""Rodada 8 — LOO PREVINE 26in + export de pesos Python (pesquisa).

1) Leave-one-event-out: MIMO 26in PREVINE vs Direct PREVINE por horizonte
2) Empacota pesos do campeão em assets/data/research_mimo_python_weights/
   (research_only — sem promoção ao vivo)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from export_python_mimo_weights import export_champion_weights
from mimo_core import align_horizons
from run_experiment import leave_one_event_out
from run_research_round5 import fair_aligned_ceilings

ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = ROOT / "assets/data/research_mimo_multihorizon_latest.json"


def run_round8() -> dict:
    aligned = align_horizons(["2h", "4h"])
    rows, ds = aligned["rows"], aligned["datasets"]
    specs = [(0, 0), (1, 1)]
    ceilings = fair_aligned_ceilings(rows, ds[0], ds[1])

    def rising_weights(y_tr: np.ndarray) -> np.ndarray:
        return np.where((y_tr[:, 1] - y_tr[:, 0]) > 0, 2.0, 1.0)

    print("=== LOO PREVINE 26in ===", flush=True)
    loo = leave_one_event_out(
        rows,
        ds,
        1,  # 26 inputs
        specs,
        [52],
        protocol="previne",
        direct_protocol="previne",
        direct_hidden_by_out=[[30], [52]],
        max_cycles=25000,
        patience_previne=5000,
        seeds=(42, 7, 19),
        mimo_sample_weights_fn=rising_weights,
    )
    print(
        json.dumps(
            {
                "n_events": loo.get("n_events_evaluated"),
                "pooled_4h": (loo.get("pooled") or {}).get("4h"),
                "wins_4h": (loo.get("wins_by_event") or {}).get("4h"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )

    print("=== export pesos campeão ===", flush=True)
    weights_manifest = export_champion_weights()
    print(json.dumps({"teste": weights_manifest["teste_metrics"], "file": weights_manifest["files"]}, indent=2), flush=True)

    pooled = loo.get("pooled") or {}
    wins = loo.get("wins_by_event") or {}
    d4 = (pooled.get("4h") or {}).get("delta_nash")
    d2 = (pooled.get("2h") or {}).get("delta_nash")
    payload = {
        "status": "ok" if loo.get("status") == "ok" else loo.get("status", "error"),
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "question": (
            "No leave-one-event-out com protocolo PREVINE e 26 inputs, o MIMO "
            "ainda supera Direct PREVINE no 4h? Pesos Python exportados para pesquisa?"
        ),
        "python_first": True,
        "loo": loo,
        "fair_aligned_ceilings": ceilings,
        "weights_export": weights_manifest,
        "verdict": {
            "loo_ok": loo.get("status") == "ok",
            "mimo_beats_direct_loo_4h": d4 is not None and d4 > 0.002,
            "mimo_beats_direct_loo_2h": d2 is not None and d2 > 0.002,
            "pooled_delta_nash_2h": d2,
            "pooled_delta_nash_4h": d4,
            "wins_4h": wins.get("4h"),
            "wins_2h": wins.get("2h"),
            "weights_exported": True,
            "note": (
                "LOO mede generalização por evento. Export de pesos é research_only — "
                "não promover ao robô ao vivo; Direct .mat continua operacional."
            ),
        },
    }

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    data["schema_version"] = max(int(data.get("schema_version", 7)), 8)
    data["generated_at_utc"] = payload["generated_at_utc"]
    data["experiments"]["exp11_loo_previne_26in_weights"] = payload
    data["method"]["round8"] = (
        "LOO PREVINE 26in (MIMO vs Direct) + export npz de pesos Python (pesquisa)."
    )
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    out = run_round8()
    print(
        json.dumps(
            {
                "verdict": out["verdict"],
                "pooled": {k: v for k, v in (out["loo"].get("pooled") or {}).items()},
                "weights_teste": out["weights_export"]["teste_metrics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
