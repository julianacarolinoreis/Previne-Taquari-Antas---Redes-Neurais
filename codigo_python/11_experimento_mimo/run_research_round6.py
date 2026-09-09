#!/usr/bin/env python3
"""Rodada 6 — 100% Python: MIMO PREVINE com 26 inputs (features do 4h) + nit ampliado.

Hipótese: o gap justo ~0,05 no 4h vinha de treinar com só 15 inputs do 2h,
enquanto o Direct 4h operacional usa 26. Com o mesmo feature set + mais
reinícios (nit) e ciclos, o MIMO deve aproximar o teto alinhado (~0,920).

MATLAB permanece opcional (matlab/OPTIONAL.md); este script é o caminho canônico.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from mimo_core import (
    align_horizons,
    compute_metrics,
    load_horizon_dataset,
    load_mat_weights,
    predict_direct_batch,
)
from run_experiment import train_direct_scratch, train_mimo_variants
from run_research_round3 import _round_metrics, _score
from run_research_round5 import fair_aligned_ceilings, gate_direct_2h_previne

ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = ROOT / "assets/data/research_mimo_multihorizon_latest.json"


def run_round6() -> dict:
    print("=== gate Direct 2h PREVINE (nit ampliado) ===", flush=True)
    gate = gate_direct_2h_previne(
        max_cycles=50000,
        seeds=tuple(range(1, 11)),  # nit=10
    )
    print(json.dumps({"gate": gate["previne_twin_teste"], "pass": gate["gate_pass"]}, indent=2), flush=True)

    aligned = align_horizons(["2h", "4h"])
    rows, ds = aligned["rows"], aligned["datasets"]
    # output: 2h + 4h deltas; input features from 4h (26)
    specs = [(0, 0), (1, 1)]
    ceilings = fair_aligned_ceilings(rows, ds[0], ds[1])
    fair = ceilings["teste"]
    mat_ref_aligned = {
        "2h": {**fair["2h_direct_mat_vs_obs"], "note": "Direct .mat vs obs no alinhado"},
        "4h": {**fair["4h_direct_mat_vs_obs"], "note": "Direct .mat vs obs no alinhado (26in)"},
    }
    print("ceilings alinhados teste", fair, flush=True)

    print("scratch SGD 26in ...", flush=True)
    scratch = train_direct_scratch(rows, ds, 1, specs, hidden_sizes=[40, 52])
    scratch_teste = scratch["splits"]["teste"]

    train_rows = [r for r in rows if r["split"] == 1]
    y_tr = np.asarray(
        [[ds[0].delta[r["indices"][0]], ds[1].delta[r["indices"][1]]] for r in train_rows],
        float,
    )
    rising_w = np.where((y_tr[:, 1] - y_tr[:, 0]) > 0, 2.0, 1.0)

    # referência r5 (15in) se presente
    data0 = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    r5 = data0["experiments"].get("exp8_previne_protocol_obs_labels") or {}
    r5_best = None
    if r5.get("best_variant"):
        r5_best = {
            "key": r5["best_variant"],
            "teste": r5["variants"][r5["best_variant"]]["splits"]["teste"],
            "gap_fair_aligned_4h": r5["verdict"].get("gap_fair_aligned_4h"),
        }

    nit = tuple(range(1, 11))  # 10 reinícios
    variants_cfg = [
        {
            "key": "mimo15_previne_rising_r5ref",
            "input_idx": 0,
            "kwargs": {
                "name_suffix": "_r6_15in_ref",
                "protocol": "previne",
                "hidden_sizes": [40, 52],
                "sample_weights_tr": rising_w,
                "seeds": (42, 7, 19, 11, 3),
                "max_cycles": 40000,
                "patience_previne": 8000,
            },
        },
        {
            "key": "mimo26_previne",
            "input_idx": 1,
            "kwargs": {
                "name_suffix": "_r6_26in",
                "protocol": "previne",
                "hidden_sizes": [40, 52, 63],
                "seeds": nit,
                "max_cycles": 80000,
                "patience_previne": 12000,
            },
        },
        {
            "key": "mimo26_previne_rising",
            "input_idx": 1,
            "kwargs": {
                "name_suffix": "_r6_26in_rising",
                "protocol": "previne",
                "hidden_sizes": [40, 52, 63],
                "sample_weights_tr": rising_w,
                "seeds": nit,
                "max_cycles": 80000,
                "patience_previne": 12000,
            },
        },
        {
            "key": "mimo26_previne_nh52_nit10",
            "input_idx": 1,
            "kwargs": {
                "name_suffix": "_r6_26in_nh52",
                "protocol": "previne",
                "hidden_sizes": [52],
                "sample_weights_tr": rising_w,
                "seeds": nit,
                "max_cycles": 100000,
                "patience_previne": 15000,
            },
        },
    ]

    results = {}
    rankings = []
    for cfg in variants_cfg:
        kwargs = dict(cfg["kwargs"])
        hidden = kwargs.pop("hidden_sizes")
        print("treino", cfg["key"], "input_idx", cfg["input_idx"], "...", flush=True)
        payload, _ = train_mimo_variants(rows, ds, cfg["input_idx"], specs, hidden, **kwargs)
        compact = _round_metrics(payload)
        score = _score(compact, scratch_teste, mat_ref_aligned)
        score["n_inputs"] = int(ds[cfg["input_idx"]].n_inputs)
        results[cfg["key"]] = {**compact, "score": score, "input_idx": cfg["input_idx"]}
        rankings.append({"key": cfg["key"], **score})
        print(" ", cfg["key"], compact["splits"]["teste"], score, flush=True)

    rankings.sort(key=lambda r: (not r["ok_2h_vs_scratch"], -r["objective_4h"], r["gap_mat_4h"]))
    best_key = rankings[0]["key"]
    best = results[best_key]
    best_4h = best["splits"]["teste"]["4h"]["nash"]
    fair_4h = mat_ref_aligned["4h"]["nash"]
    improves_r5 = (
        r5_best is not None
        and best_4h > r5_best["teste"]["4h"]["nash"] + 0.002
    )

    payload = {
        "status": "ok",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "question": (
            "Com 26 inputs do Direct 4h + nit=10 + Cic ampliado, o MIMO PREVINE "
            "fecha o gap justo alinhado no 4h (<0,05) sem piorar o 2h?"
        ),
        "python_first": True,
        "matlab_optional": True,
        "gate_direct_2h_previne": gate,
        "fair_aligned_ceilings": ceilings,
        "mat_reference_aligned_teste": mat_ref_aligned,
        "round5_best_ref": r5_best,
        "baseline_scratch_teste": {
            hz: {
                k: round(float(v[k]), 4) if isinstance(v[k], float) else v[k]
                for k in ("nash", "pers", "e95", "mae", "n")
            }
            for hz, v in scratch_teste.items()
        },
        "variants": results,
        "ranking": rankings,
        "best_variant": best_key,
        "verdict": {
            "best": best_key,
            "closes_fair_aligned_gap": (fair_4h - best_4h) < 0.05,
            "gap_fair_aligned_4h": round(fair_4h - best_4h, 4),
            "beats_scratch_4h": rankings[0]["delta_scratch_4h"] > 0.002,
            "improves_vs_round5_4h": improves_r5,
            "gate_pass": gate["gate_pass"],
            "note": (
                "Caminho canônico = Python. MATLAB em matlab/OPTIONAL.md. "
                "Se 26in + nit não fechar gap<0,05, o limite é multi-saída vs dois Direct "
                "independentes — não falta de runtime MATLAB."
            ),
        },
    }

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    data["schema_version"] = max(int(data.get("schema_version", 5)), 6)
    data["generated_at_utc"] = payload["generated_at_utc"]
    data["experiments"]["exp9_python_26in_nit"] = payload
    data["method"]["round6"] = (
        "100% Python: MIMO PREVINE com 26 inputs do 4h, nit=10, Cic até 1e5; "
        "MATLAB arquivado como opcional."
    )
    data["method"]["python_first"] = True
    data["mat_reference_aligned_teste"] = mat_ref_aligned
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    out = run_round6()
    print(
        json.dumps(
            {
                "best": out["best_variant"],
                "ranking": out["ranking"][:4],
                "verdict": out["verdict"],
                "fair_ceiling_teste": out["mat_reference_aligned_teste"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
