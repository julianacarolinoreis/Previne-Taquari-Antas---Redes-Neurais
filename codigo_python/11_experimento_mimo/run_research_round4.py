#!/usr/bin/env python3
"""Rodada 4: corrigir warm-start / escala ae·be e testar stitch Direct+MIMO.

Hipótese da rodada 3: warm-start colapsou porque copiava ws/au/bu e o fit
trocava a escala de saída para min/max do treino.

Variantes:
- mat_input_only: congela ae/be do .mat; pesos aleatórios
- warm_hidden_only: copia Wh/bh + ae/be; cabeças novas (z-score y)
- warm_full_freeze_y: copia tudo; congela au/bu na cabeça 2h; afina só 4h
- rising + hidden warm (melhor da r3 + transferência oculta)
- stitch: 2h = Direct .mat; 4h = cabeça MIMO (treino só no Δ4h residual opcional)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from mimo_core import align_horizons, evaluate_strategy, load_mat_weights, predict_direct
from run_experiment import (
    build_summary_vs,
    build_summary_vs_mat_reference,
    train_direct_scratch,
    train_mimo_variants,
)
from run_research_round3 import _round_metrics, _score

ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = ROOT / "assets/data/research_mimo_multihorizon_latest.json"


def _stitch_eval(rows, datasets, w2, mimo_model) -> dict:
    """2h via Direct .mat; 4h via MIMO (mesmo input 15)."""

    def predict_fn(x, atual, _row):
        y2 = predict_direct(w2, np.asarray(x, float), float(atual))
        d4 = float(mimo_model.forward_delta(np.asarray(x, float))[0, 1])
        return [float(y2), float(atual + d4)]

    payload = evaluate_strategy(
        name="stitch_direct2h_mimo4h",
        rows=rows,
        datasets=datasets,
        input_dataset_idx=0,
        output_specs=[(0, 0), (1, 1)],
        predict_fn=predict_fn,
    )
    payload["training"] = {
        "note": "2h = Direct .mat auditado; 4h = MIMO forward_delta[:,1]",
        "mimo_hidden": int(mimo_model.n_hidden),
    }
    return payload


def run_round4() -> dict:
    aligned = align_horizons(["2h", "4h"])
    rows, ds = aligned["rows"], aligned["datasets"]
    specs = [(0, 0), (1, 1)]
    w2 = load_mat_weights(ds[0].mat_path)
    nh_mat = int(np.atleast_2d(w2["wh"]).shape[0])
    if np.atleast_2d(w2["wh"]).shape[1] != 15:
        nh_mat = int(np.atleast_2d(w2["wh"]).shape[1])

    scratch = train_direct_scratch(rows, ds, 0, specs, hidden_sizes=[30, 40])
    scratch_teste = scratch["splits"]["teste"]

    train_rows = [r for r in rows if r["split"] == 1]
    y_tr = np.asarray([[ds[0].delta[r["indices"][0]], ds[1].delta[r["indices"][1]]] for r in train_rows], float)
    rising_w = np.where((y_tr[:, 1] - y_tr[:, 0]) > 0, 2.0, 1.0)

    variants_cfg = [
        {
            "key": "mimo_mat_input_only",
            "kwargs": {
                "name_suffix": "_r4_mat_in",
                "scale_mode": "zscore",
                "hidden_sizes": [nh_mat, 40, 52],
                "mat_input_scale_weights": w2,
                "seeds": (42, 7, 19),
            },
        },
        {
            "key": "mimo_warm_hidden_only",
            "kwargs": {
                "name_suffix": "_r4_wh",
                "scale_mode": "zscore",
                "hidden_sizes": [nh_mat],
                "warm_start_weights": w2,
                "warm_start_mode": "hidden_only",
                "lr": 0.012,
                "seeds": (42, 7, 19, 11),
            },
        },
        {
            "key": "mimo_warm_full_freeze_y",
            "kwargs": {
                "name_suffix": "_r4_full_fy",
                "scale_mode": "zscore",
                "hidden_sizes": [nh_mat],
                "warm_start_weights": w2,
                "warm_start_mode": "full_freeze_y",
                "lr": 0.004,
                "seeds": (42, 7, 19),
            },
        },
        {
            "key": "mimo_warm_hidden_rising",
            "kwargs": {
                "name_suffix": "_r4_wh_rising",
                "scale_mode": "zscore",
                "hidden_sizes": [nh_mat, 40, 52],
                "warm_start_weights": w2,
                "warm_start_mode": "hidden_only",
                "sample_weights_tr": rising_w,
                "lr": 0.012,
                "seeds": (42, 7, 19, 11),
            },
        },
        {
            "key": "mimo_rising_r3_ref",
            "kwargs": {
                "name_suffix": "_r4_rising_ref",
                "scale_mode": "zscore",
                "hidden_sizes": [30, 40, 52, 63],
                "sample_weights_tr": rising_w,
                "seeds": (42, 7, 19, 11),
            },
        },
    ]

    mat_ref = {
        "2h": {"nash": 0.9962, "pers": 0.9688, "e95": 10.39, "note": "mat completo"},
        "4h": {"nash": 0.9926, "pers": 0.8782, "e95": 58.84, "note": "mat completo"},
    }

    results = {}
    rankings = []
    models = {}
    for cfg in variants_cfg:
        kwargs = dict(cfg["kwargs"])
        hidden = kwargs.pop("hidden_sizes")
        print("treino", cfg["key"], "...", flush=True)
        payload, model = train_mimo_variants(rows, ds, 0, specs, hidden, **kwargs)
        compact = _round_metrics(payload)
        score = _score(compact, scratch_teste, mat_ref)
        results[cfg["key"]] = {**compact, "score": score}
        models[cfg["key"]] = model
        rankings.append({"key": cfg["key"], **score})
        print(" ", cfg["key"], compact["splits"]["teste"], score, flush=True)

    # stitch usa o melhor MIMO 4h entre as variantes ok_2h
    candidate_keys = [r["key"] for r in rankings if r["ok_2h_vs_scratch"]]
    if not candidate_keys:
        candidate_keys = [rankings[0]["key"]]
    stitch_src = max(candidate_keys, key=lambda k: results[k]["splits"]["teste"]["4h"]["nash"])
    print("stitch com", stitch_src, "...", flush=True)
    stitch_payload = _stitch_eval(rows, ds, w2, models[stitch_src])
    stitch_compact = _round_metrics(stitch_payload)
    stitch_score = _score(stitch_compact, scratch_teste, mat_ref)
    results["stitch_direct2h_mimo4h"] = {
        **stitch_compact,
        "score": stitch_score,
        "mimo_source": stitch_src,
    }
    rankings.append({"key": "stitch_direct2h_mimo4h", **stitch_score})
    print(" stitch", stitch_compact["splits"]["teste"], stitch_score, flush=True)

    rankings.sort(key=lambda r: (not r["ok_2h_vs_scratch"], -r["objective_4h"], r["gap_mat_4h"]))
    best_key = rankings[0]["key"]
    best = results[best_key]

    summary_vs_scratch = build_summary_vs(
        {"splits": {"teste": {hz: scratch_teste[hz] for hz in scratch_teste}}},
        {"splits": {"teste": {hz: best["splits"]["teste"][hz] for hz in best["splits"]["teste"]}}},
    )
    summary_vs_mat = build_summary_vs_mat_reference(mat_ref, {"splits": {"teste": best["splits"]["teste"]}})

    # comparar com melhor da rodada 3 se presente
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    r3 = data["experiments"].get("exp6_close_mat_gap_2h4h") or {}
    r3_best = None
    if r3.get("best_variant"):
        r3_best = {
            "key": r3["best_variant"],
            "teste": r3["variants"][r3["best_variant"]]["splits"]["teste"],
            "gap_mat_4h": r3["ranking"][0]["gap_mat_4h"] if r3.get("ranking") else None,
        }

    payload = {
        "status": "ok",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "question": (
            "Corrigindo a escala ae/be (z-score PREVINE) e o warm-start (só oculta), "
            "fechamos o gap ao teto .mat sem piorar o 2h?"
        ),
        "hypothesis": (
            "O colapso do warm-start na r3 veio de copiar ws+au/bu e sobrescrever a escala y; "
            "transferir só Wh/bh com ae/be congelado deve ser estável."
        ),
        "baseline_scratch_teste": {
            hz: {k: round(float(v[k]), 4) if isinstance(v[k], float) else v[k] for k in ("nash", "pers", "e95", "mae", "n")}
            for hz, v in scratch_teste.items()
        },
        "mat_reference_metrics_teste": mat_ref,
        "round3_best_ref": r3_best,
        "variants": results,
        "ranking": rankings,
        "best_variant": best_key,
        "summary_best_vs_scratch": summary_vs_scratch,
        "summary_best_vs_mat": summary_vs_mat,
        "verdict": {
            "best": best_key,
            "closes_mat_gap": rankings[0]["gap_mat_4h"] < 0.10,
            "beats_scratch_4h": rankings[0]["delta_scratch_4h"] > 0.002,
            "improves_vs_round3_4h": (
                r3_best is not None
                and best["splits"]["teste"]["4h"]["nash"] > r3_best["teste"]["4h"]["nash"] + 0.002
            ),
            "note": (
                "Se gap_mat_4h continuar ≥0,10 após warm-start corrigido e stitch, "
                "o teto .mat exige treino nativo MATLAB (ou dados/protocolo idêntico ao Direct), "
                "não mais alavancas ad-hoc em Python."
            ),
        },
    }

    data["schema_version"] = max(int(data.get("schema_version", 3)), 4)
    data["generated_at_utc"] = payload["generated_at_utc"]
    data["experiments"]["exp7_mat_scale_warmstart_fix"] = payload
    data["method"]["round4"] = (
        "Warm-start hidden_only + ae/be congelado; full_freeze_y; stitch Direct2h+MIMO4h."
    )
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    out = run_round4()
    print(
        json.dumps(
            {"best": out["best_variant"], "ranking": out["ranking"][:4], "verdict": out["verdict"]},
            ensure_ascii=False,
            indent=2,
        )
    )
