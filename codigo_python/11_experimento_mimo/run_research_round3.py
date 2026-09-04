#!/usr/bin/env python3
"""Rodada 3 da pesquisa MIMO: fechar o gap ao teto dos .mat Direct.

Variantes:
- minmax (escala estilo PREVINE .mat)
- warm-start da camada oculta do Direct 2h
- pesos de horizonte [1,2]
- oversample de subidas (sample weight)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from mimo_core import align_horizons, load_mat_weights
from run_experiment import (
    build_summary_vs,
    build_summary_vs_mat_reference,
    train_direct_scratch,
    train_mimo_variants,
)

ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = ROOT / "assets/data/research_mimo_multihorizon_latest.json"


def _round_metrics(payload: dict) -> dict:
    """Compacta splits para o relatório."""
    out = {"strategy": payload.get("strategy") or payload.get("name"), "splits": {}, "training": payload.get("training")}
    for split, horizons in payload.get("splits", {}).items():
        out["splits"][split] = {
            hz: {
                "n": v["n"],
                "nash": round(float(v["nash"]), 4),
                "pers": round(float(v["pers"]), 4),
                "e95": round(float(v["e95"]), 3),
                "mae": round(float(v["mae"]), 4),
            }
            for hz, v in horizons.items()
        }
    return out


def _score(variant: dict, scratch_teste: dict, mat_ref: dict) -> dict:
    t = variant["splits"]["teste"]
    s2, s4 = scratch_teste["2h"]["nash"], scratch_teste["4h"]["nash"]
    m2, m4 = t["2h"]["nash"], t["4h"]["nash"]
    # Não sacrificar 2h além de 0,01 NASH vs scratch; maximizar 4h e proximidade ao teto.
    ok_2h = m2 >= s2 - 0.01
    gap_mat_4h = mat_ref["4h"]["nash"] - m4
    gap_mat_2h = mat_ref["2h"]["nash"] - m2
    return {
        "ok_2h_vs_scratch": ok_2h,
        "delta_scratch_2h": round(m2 - s2, 4),
        "delta_scratch_4h": round(m4 - s4, 4),
        "gap_mat_2h": round(gap_mat_2h, 4),
        "gap_mat_4h": round(gap_mat_4h, 4),
        "objective_4h": round(m4, 4),
    }


def run_round3() -> dict:
    aligned = align_horizons(["2h", "4h"])
    rows, ds = aligned["rows"], aligned["datasets"]
    specs = [(0, 0), (1, 1)]
    w2 = load_mat_weights(ds[0].mat_path)

    # baseline scratch (rápido, nh fixos principais)
    scratch = train_direct_scratch(rows, ds, 0, specs, hidden_sizes=[30, 40])
    scratch_teste = scratch["splits"]["teste"]

    # rising weights on train
    train_rows = [r for r in rows if r["split"] == 1]
    y_tr = np.asarray([[ds[0].delta[r["indices"][0]], ds[1].delta[r["indices"][1]]] for r in train_rows], float)
    rising_w = np.where((y_tr[:, 1] - y_tr[:, 0]) > 0, 2.0, 1.0)

    variants_cfg = [
        {"key": "mimo_zscore_base", "kwargs": {"name_suffix": "_r3_zscore", "scale_mode": "zscore", "hidden_sizes": [30, 40, 52]}},
        {
            "key": "mimo_warmstart_2h",
            "kwargs": {
                "name_suffix": "_r3_warm2h",
                "scale_mode": "minmax",
                "hidden_sizes": [30],
                "warm_start_weights": w2,
                "seeds": (42, 7, 19),
                "lr": 0.008,
            },
        },
        {
            "key": "mimo_weight_4h",
            "kwargs": {
                "name_suffix": "_r3_w4h",
                "scale_mode": "zscore",
                "hidden_sizes": [30, 40, 52],
                "horizon_weights": np.asarray([1.0, 2.0]),
            },
        },
        {
            "key": "mimo_rising_weight",
            "kwargs": {
                "name_suffix": "_r3_rising",
                "scale_mode": "zscore",
                "hidden_sizes": [30, 40, 52, 63],
                "sample_weights_tr": rising_w,
                "seeds": (42, 7, 19, 11),
            },
        },
        {
            "key": "mimo_rising_w4h",
            "kwargs": {
                "name_suffix": "_r3_rising_w4h",
                "scale_mode": "zscore",
                "hidden_sizes": [40, 52, 63],
                "sample_weights_tr": rising_w,
                "horizon_weights": np.asarray([1.0, 1.5]),
                "seeds": (42, 7, 19, 11),
            },
        },
        {
            "key": "mimo_warm_rising",
            "kwargs": {
                "name_suffix": "_r3_warm_rising",
                "scale_mode": "minmax",
                "hidden_sizes": [30],
                "warm_start_weights": w2,
                "sample_weights_tr": rising_w,
                "lr": 0.008,
                "seeds": (42, 7, 19),
            },
        },
    ]

    mat_ref = {
        "2h": {"nash": 0.9962, "pers": 0.9688, "e95": 10.39, "note": "mat completo"},
        "4h": {"nash": 0.9926, "pers": 0.8782, "e95": 58.84, "note": "mat completo"},
    }

    results = {}
    rankings = []
    for cfg in variants_cfg:
        kwargs = dict(cfg["kwargs"])
        hidden = kwargs.pop("hidden_sizes")
        print("treino", cfg["key"], "...", flush=True)
        payload, _ = train_mimo_variants(rows, ds, 0, specs, hidden, **kwargs)
        compact = _round_metrics(payload)
        score = _score(compact, scratch_teste, mat_ref)
        results[cfg["key"]] = {**compact, "score": score}
        rankings.append({"key": cfg["key"], **score})
        print(
            " ",
            cfg["key"],
            "teste",
            compact["splits"]["teste"],
            "score",
            score,
            flush=True,
        )

    # ranking: ok_2h first, then best 4h, then menor gap_mat_4h
    rankings.sort(key=lambda r: (not r["ok_2h_vs_scratch"], -r["objective_4h"], r["gap_mat_4h"]))
    best_key = rankings[0]["key"]
    best = results[best_key]

    summary_vs_scratch = build_summary_vs(
        {"splits": {"teste": {hz: scratch_teste[hz] for hz in scratch_teste}}},
        {"splits": {"teste": {hz: best["splits"]["teste"][hz] for hz in best["splits"]["teste"]}}},
    )
    # build_summary_vs expects full metric dicts with nash/pers/e95 - scratch_teste already has them
    summary_vs_mat = build_summary_vs_mat_reference(mat_ref, {"splits": {"teste": best["splits"]["teste"]}})

    payload = {
        "status": "ok",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "question": "Qual variante MIMO reduz o gap ao teto .mat sem piorar o 2h vs Direct scratch?",
        "baseline_scratch_teste": {
            hz: {k: round(float(v[k]), 4) if isinstance(v[k], float) else v[k] for k in ("nash", "pers", "e95", "mae", "n")}
            for hz, v in scratch_teste.items()
        },
        "mat_reference_metrics_teste": mat_ref,
        "variants": results,
        "ranking": rankings,
        "best_variant": best_key,
        "summary_best_vs_scratch": summary_vs_scratch,
        "summary_best_vs_mat": summary_vs_mat,
        "verdict": {
            "best": best_key,
            "closes_mat_gap": rankings[0]["gap_mat_4h"] < 0.10,
            "beats_scratch_4h": rankings[0]["delta_scratch_4h"] > 0.002,
            "note": (
                "Ganho vs scratch no 4h já existia; rodada 3 busca aproximar o teto .mat. "
                "Se nenhuma variante reduzir gap_mat_4h < 0,10 mantendo 2h, o handoff MATLAB "
                "com inicialização nativa permanece o próximo passo."
            ),
        },
    }

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    data["schema_version"] = max(int(data.get("schema_version", 2)), 3)
    data["generated_at_utc"] = payload["generated_at_utc"]
    data["experiments"]["exp6_close_mat_gap_2h4h"] = payload
    data["method"]["round3"] = (
        "Busca minmax/warm-start/pesos de horizonte/subidas para fechar gap ao teto mat_reference."
    )
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    out = run_round3()
    print(json.dumps({"best": out["best_variant"], "ranking": out["ranking"][:3], "verdict": out["verdict"]}, ensure_ascii=False, indent=2))
