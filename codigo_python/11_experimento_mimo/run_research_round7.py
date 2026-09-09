#!/usr/bin/env python3
"""Rodada 7 — MIMO vs Direct×2 PREVINE + residual + gate 4h full-test.

Pergunta científica após fechar o gap justo na r6:
1) No alinhado, MIMO 26in ainda ganha de *dois* Direct PREVINE independentes?
2) Residual (2h Direct + (4h−2h)) melhora o 4h?
3) Gate: twin PREVINE single-output no 4h *completo* aproxima NASH_TESTE≈0,9926?

100% Python. MATLAB opcional.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from mimo_core import (
    align_horizons,
    compute_metrics,
    evaluate_strategy,
    load_horizon_dataset,
    load_mat_weights,
    predict_direct_batch,
)
from run_experiment import train_direct_previne, train_mimo_variants, _fit_search, _mask
from run_research_round3 import _round_metrics
from run_research_round5 import fair_aligned_ceilings

ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = ROOT / "assets/data/research_mimo_multihorizon_latest.json"


def _compact_split(payload: dict) -> dict:
    return _round_metrics(payload)


def gate_direct_4h_full_previne(max_cycles: int = 60000, seeds=tuple(range(1, 11))) -> dict:
    ds = load_horizon_dataset("4h")
    w_ref = load_mat_weights(ds.mat_path)
    te = ds.split == 3
    pred_mat = predict_direct_batch(w_ref, ds.inputs[te], ds.atual[te])
    ref = compute_metrics(ds.target_abs[te], pred_mat, ds.atual[te])

    rows = [{"indices": (i,), "split": int(ds.split[i]), "event": None} for i in range(ds.n_samples)]
    nh = int(np.atleast_2d(w_ref["wh"]).shape[0])
    payload, _ = train_mimo_variants(
        rows,
        [ds],
        0,
        [(0, 0)],
        [nh],
        name_suffix="_gate_direct4h_full",
        protocol="previne",
        max_cycles=max_cycles,
        patience_previne=10000,
        seeds=seeds,
    )
    teste = payload["splits"]["teste"]["4h"]
    return {
        "status": "ok",
        "mat_reference_teste": {
            "nash": round(ref.nash, 4),
            "pers": round(ref.pers, 4),
            "e95": round(ref.e95, 3),
            "mae": round(ref.mae, 4),
            "n": ref.n,
            "stored_NASH_TESTE": 0.9926,
        },
        "previne_twin_teste": {
            "nash": round(float(teste["nash"]), 4),
            "pers": round(float(teste["pers"]), 4),
            "e95": round(float(teste["e95"]), 3),
            "mae": round(float(teste["mae"]), 4),
            "n": int(teste["n"]),
        },
        "training": payload.get("training"),
        "gate_pass": float(teste["nash"]) >= 0.90,
        "gap_to_mat": round(0.9926 - float(teste["nash"]), 4),
    }


def train_residual_previne(rows, ds2, ds4, model_2h, *, seeds, max_cycles, patience) -> dict:
    """2h = Direct PREVINE; 4h = d2_hat + residual(d4−d2) em 26in."""
    train_rows = _mask(rows, 1)
    val_rows = _mask(rows, 2)

    def pack(rs, residual=True):
        x = np.asarray([ds4.inputs[r["indices"][1]] for r in rs], float)
        d2 = np.asarray([ds2.delta[r["indices"][0]] for r in rs], float)
        d4 = np.asarray([ds4.delta[r["indices"][1]] for r in rs], float)
        y = (d4 - d2).reshape(-1, 1) if residual else d4.reshape(-1, 1)
        return x, y

    x_tr, y_tr = pack(train_rows)
    x_va, y_va = pack(val_rows)
    best = _fit_search(
        x_tr,
        y_tr,
        x_va,
        y_va,
        [40, 52, 63],
        protocol="previne",
        max_cycles=max_cycles,
        patience_previne=patience,
        seeds=seeds,
    )
    resid_model = best["model"]

    def predict_fn(_x, _atual, row):
        i2, i4 = row["indices"]
        a2 = float(ds2.atual[i2])
        x2 = ds2.inputs[i2]
        d2 = float(model_2h.forward_delta(x2)[0, 0])
        x4 = ds4.inputs[i4]
        r = float(resid_model.forward_delta(x4)[0, 0])
        # níveis absolutos: usar atual de cada horizonte (alinhados ≈ iguais)
        a4 = float(ds4.atual[i4])
        return [a2 + d2, a4 + d2 + r]

    payload = evaluate_strategy(
        name="residual_previne_2h_plus_d4minusd2",
        rows=rows,
        datasets=[ds2, ds4],
        input_dataset_idx=1,
        output_specs=[(0, 0), (1, 1)],
        predict_fn=predict_fn,
    )
    payload["training"] = {
        "residual_hidden": best["nh"],
        "residual_seed": best["seed"],
        "residual_val_mse": best["val_mse"],
        "protocol": "previne",
        **best["fit"],
    }
    return payload


def run_round7() -> dict:
    print("=== gate Direct 4h FULL PREVINE ===", flush=True)
    gate4 = gate_direct_4h_full_previne()
    print(json.dumps({"gate4": gate4["previne_twin_teste"], "gap_mat": gate4["gap_to_mat"]}, indent=2), flush=True)

    aligned = align_horizons(["2h", "4h"])
    rows, ds = aligned["rows"], aligned["datasets"]
    ds2, ds4 = ds[0], ds[1]
    specs = [(0, 0), (1, 1)]
    ceilings = fair_aligned_ceilings(rows, ds2, ds4)
    fair = ceilings["teste"]
    mat_ref_aligned = {
        "2h": {**fair["2h_direct_mat_vs_obs"], "note": "Direct .mat vs obs alinhado"},
        "4h": {**fair["4h_direct_mat_vs_obs"], "note": "Direct .mat vs obs alinhado (26in)"},
    }

    nit = tuple(range(1, 11))

    print("Direct×2 PREVINE ...", flush=True)
    pair, pair_models = train_direct_previne(
        rows,
        ds,
        1,
        specs,
        hidden_sizes_by_out=[[30, 40], [52]],
        seeds=nit,
        max_cycles=80000,
        patience_previne=12000,
        name="direct_previne_pair_15_26",
    )
    pair_c = _compact_split(pair)

    print("MIMO 26in nh52 (r6 champ) ...", flush=True)
    train_rows = [r for r in rows if r["split"] == 1]
    y_tr = np.asarray([[ds2.delta[r["indices"][0]], ds4.delta[r["indices"][1]]] for r in train_rows], float)
    rising_w = np.where((y_tr[:, 1] - y_tr[:, 0]) > 0, 2.0, 1.0)
    mimo, mimo_model = train_mimo_variants(
        rows,
        ds,
        1,
        specs,
        [52],
        name_suffix="_r7_mimo26_nh52",
        protocol="previne",
        sample_weights_tr=rising_w,
        seeds=nit,
        max_cycles=100000,
        patience_previne=15000,
    )
    mimo_c = _compact_split(mimo)

    print("Residual PREVINE ...", flush=True)
    resid = train_residual_previne(
        rows,
        ds2,
        ds4,
        pair_models[0],
        seeds=nit,
        max_cycles=80000,
        patience=12000,
    )
    resid_c = _compact_split(resid)

    # mat Direct .mat pair as oracle baseline on aligned
    print("Direct .mat pair (oracle) ...", flush=True)
    from run_experiment import direct_baseline

    mat_pair = direct_baseline(rows, ds, specs)
    mat_c = _compact_split(mat_pair)

    variants = {
        "direct_mat_oracle": {**mat_c, "role": "teto_operacional_alinhado"},
        "direct_previne_pair": {**pair_c, "role": "dois_direct_python", "training": pair.get("training")},
        "mimo26_previne_nh52": {**mimo_c, "role": "mimo", "training": mimo.get("training")},
        "residual_previne": {**resid_c, "role": "residual", "training": resid.get("training")},
    }

    def gap4(v):
        return round(mat_ref_aligned["4h"]["nash"] - v["splits"]["teste"]["4h"]["nash"], 4)

    ranking = []
    for key, v in variants.items():
        t = v["splits"]["teste"]
        ranking.append(
            {
                "key": key,
                "nash_2h": t["2h"]["nash"],
                "nash_4h": t["4h"]["nash"],
                "gap_fair_4h": gap4(v),
                "e95_4h": t["4h"]["e95"],
                "role": v.get("role"),
            }
        )
    # melhor pesquisa (exclui oracle .mat): maximiza 4h com 2h >= 0.94
    research = [r for r in ranking if r["key"] != "direct_mat_oracle"]
    research.sort(key=lambda r: (-r["nash_4h"], -r["nash_2h"]))
    best_key = research[0]["key"]

    mimo_vs_pair = {
        "delta_nash_2h": round(
            variants["mimo26_previne_nh52"]["splits"]["teste"]["2h"]["nash"]
            - variants["direct_previne_pair"]["splits"]["teste"]["2h"]["nash"],
            4,
        ),
        "delta_nash_4h": round(
            variants["mimo26_previne_nh52"]["splits"]["teste"]["4h"]["nash"]
            - variants["direct_previne_pair"]["splits"]["teste"]["4h"]["nash"],
            4,
        ),
    }

    payload = {
        "status": "ok",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "question": (
            "No alinhado, MIMO PREVINE 26in supera dois Direct PREVINE independentes? "
            "Residual ajuda? Twin 4h full-test aproxima o .mat?"
        ),
        "python_first": True,
        "gate_direct_4h_full_previne": gate4,
        "fair_aligned_ceilings": ceilings,
        "mat_reference_aligned_teste": mat_ref_aligned,
        "variants": variants,
        "ranking": ranking,
        "ranking_research": research,
        "best_research_variant": best_key,
        "mimo_vs_direct_pair": mimo_vs_pair,
        "verdict": {
            "best_research": best_key,
            "mimo_beats_direct_pair_4h": mimo_vs_pair["delta_nash_4h"] > 0.002,
            "mimo_beats_direct_pair_2h": mimo_vs_pair["delta_nash_2h"] > 0.002,
            "best_gap_fair_4h": research[0]["gap_fair_4h"],
            "closes_fair_aligned_gap": research[0]["gap_fair_4h"] < 0.05,
            "gate4_pass": gate4["gate_pass"],
            "gate4_gap_to_mat": gate4["gap_to_mat"],
            "note": (
                "Se Direct×2 PREVINE ≥ MIMO no 4h, o valor do MIMO é coerência/custo, "
                "não acurácia pura. Se o gate 4h full ainda ficar longe de 0,9926, "
                "falta fidelidade do twin (Cic/nit/init), não arquitetura MIMO."
            ),
        },
    }

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    data["schema_version"] = max(int(data.get("schema_version", 6)), 7)
    data["generated_at_utc"] = payload["generated_at_utc"]
    data["experiments"]["exp10_mimo_vs_direct_pair"] = payload
    data["method"]["round7"] = (
        "Compara MIMO 26in PREVINE vs Direct×2 PREVINE vs residual; gate twin 4h full-test."
    )
    data["mat_reference_aligned_teste"] = mat_ref_aligned
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    out = run_round7()
    print(
        json.dumps(
            {
                "best_research": out["best_research_variant"],
                "ranking_research": out["ranking_research"],
                "mimo_vs_pair": out["mimo_vs_direct_pair"],
                "verdict": out["verdict"],
                "gate4": out["gate_direct_4h_full_previne"]["previne_twin_teste"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
