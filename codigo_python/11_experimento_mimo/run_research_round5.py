#!/usr/bin/env python3
"""Rodada 5: rótulos obs (Ttot1) + trainer protocolo PREVINE.

Correções vs rodadas 3–4:
1. y_true = Ttot1 (observação), não Tctot1 (predição)
2. ae/be com std ddof=1; au/bu = liminf/limsup(f=0.05)
3. Loss no espaço yn; dunisig piso 0,01; GD full-batch + TX adaptativo
4. Teto justo no alinhado = Direct .mat vs observação (não NASH≈1)
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

ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = ROOT / "assets/data/research_mimo_multihorizon_latest.json"


def _metrics_split(y_true, y_pred, y_pers):
    m = compute_metrics(y_true, y_pred, y_pers)
    return {
        "n": m.n,
        "nash": round(m.nash, 4),
        "pers": round(m.pers, 4),
        "e95": round(m.e95, 3),
        "mae": round(m.mae, 4),
    }


def gate_direct_2h_previne(max_cycles: int = 25000, seeds=(42, 7, 19, 11, 3)) -> dict:
    ds = load_horizon_dataset("2h")
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
        name_suffix="_gate_direct2h_previne",
        protocol="previne",
        max_cycles=max_cycles,
        patience_previne=6000,
        seeds=seeds,
    )
    teste = payload["splits"]["teste"]["2h"]
    return {
        "status": "ok",
        "mat_reference_teste": {
            "nash": round(ref.nash, 4),
            "pers": round(ref.pers, 4),
            "e95": round(ref.e95, 3),
            "mae": round(ref.mae, 4),
            "n": ref.n,
            "stored_NASH_TESTE": 0.9962,
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
        "note": (
            "Gate passa com NASH≥0,90 no teste (twin aproximado). "
            "Teto operacional do .mat (~0,996) exige Cic/nit plenos do MATLAB."
        ),
    }


def fair_aligned_ceilings(rows, ds2, ds4) -> dict:
    w2 = load_mat_weights(ds2.mat_path)
    w4 = load_mat_weights(ds4.mat_path)
    out = {}
    for split_id, label in [(1, "treino"), (2, "validacao"), (3, "teste")]:
        picked = [r for r in rows if r["split"] == split_id]
        if not picked:
            continue
        x2 = np.asarray([ds2.inputs[r["indices"][0]] for r in picked], float)
        a2 = np.asarray([ds2.atual[r["indices"][0]] for r in picked], float)
        y2 = np.asarray([ds2.target_abs[r["indices"][0]] for r in picked], float)
        p2 = predict_direct_batch(w2, x2, a2)
        x4 = np.asarray([ds4.inputs[r["indices"][1]] for r in picked], float)
        a4 = np.asarray([ds4.atual[r["indices"][1]] for r in picked], float)
        y4 = np.asarray([ds4.target_abs[r["indices"][1]] for r in picked], float)
        p4 = predict_direct_batch(w4, x4, a4)
        out[label] = {
            "2h_direct_mat_vs_obs": _metrics_split(y2, p2, a2),
            "4h_direct_mat_vs_obs": _metrics_split(y4, p4, a4),
            "n": len(picked),
        }
    return out


def run_round5() -> dict:
    print("=== gate Direct 2h PREVINE ===", flush=True)
    gate = gate_direct_2h_previne()
    print(json.dumps({"gate": gate["previne_twin_teste"], "pass": gate["gate_pass"]}, indent=2), flush=True)

    aligned = align_horizons(["2h", "4h"])
    rows, ds = aligned["rows"], aligned["datasets"]
    specs = [(0, 0), (1, 1)]
    ceilings = fair_aligned_ceilings(rows, ds[0], ds[1])
    print("ceilings alinhados teste", ceilings.get("teste"), flush=True)

    print("scratch SGD ...", flush=True)
    scratch = train_direct_scratch(rows, ds, 0, specs, hidden_sizes=[30, 40])
    scratch_teste = scratch["splits"]["teste"]

    train_rows = [r for r in rows if r["split"] == 1]
    y_tr = np.asarray(
        [[ds[0].delta[r["indices"][0]], ds[1].delta[r["indices"][1]]] for r in train_rows],
        float,
    )
    rising_w = np.where((y_tr[:, 1] - y_tr[:, 0]) > 0, 2.0, 1.0)

    mat_ref_full = {
        "2h": {"nash": 0.9962, "pers": 0.9688, "e95": 10.39, "note": "mat completo vs obs"},
        "4h": {"nash": 0.9926, "pers": 0.8782, "e95": 58.84, "note": "mat completo vs obs (26in)"},
    }
    fair = ceilings["teste"]
    mat_ref_aligned = {
        "2h": {**fair["2h_direct_mat_vs_obs"], "note": "Direct .mat vs obs no alinhado"},
        "4h": {**fair["4h_direct_mat_vs_obs"], "note": "Direct .mat vs obs no alinhado (26in)"},
    }

    variants_cfg = [
        {
            "key": "mimo_sgd_rising_legacy",
            "kwargs": {
                "name_suffix": "_r5_sgd_rising",
                "protocol": "sgd",
                "hidden_sizes": [30, 40, 52],
                "sample_weights_tr": rising_w,
                "seeds": (42, 7, 19),
            },
        },
        {
            "key": "mimo_previne",
            "kwargs": {
                "name_suffix": "_r5_previne",
                "protocol": "previne",
                "hidden_sizes": [30, 40, 52],
                "seeds": (42, 7, 19, 11, 3),
                "max_cycles": 40000,
                "patience_previne": 8000,
            },
        },
        {
            "key": "mimo_previne_rising",
            "kwargs": {
                "name_suffix": "_r5_previne_rising",
                "protocol": "previne",
                "hidden_sizes": [30, 40, 52],
                "sample_weights_tr": rising_w,
                "seeds": (42, 7, 19, 11, 3),
                "max_cycles": 40000,
                "patience_previne": 8000,
            },
        },
        {
            "key": "mimo_previne_nh52",
            "kwargs": {
                "name_suffix": "_r5_previne_nh52",
                "protocol": "previne",
                "hidden_sizes": [52],
                "seeds": (42, 7, 19, 11, 3, 99),
                "max_cycles": 50000,
                "patience_previne": 10000,
            },
        },
    ]

    results = {}
    rankings = []
    for cfg in variants_cfg:
        kwargs = dict(cfg["kwargs"])
        hidden = kwargs.pop("hidden_sizes")
        print("treino", cfg["key"], "...", flush=True)
        payload, _ = train_mimo_variants(rows, ds, 0, specs, hidden, **kwargs)
        compact = _round_metrics(payload)
        score = _score(compact, scratch_teste, mat_ref_aligned)
        score["gap_mat_full_4h"] = round(
            mat_ref_full["4h"]["nash"] - compact["splits"]["teste"]["4h"]["nash"], 4
        )
        results[cfg["key"]] = {**compact, "score": score}
        rankings.append({"key": cfg["key"], **score})
        print(" ", cfg["key"], compact["splits"]["teste"], score, flush=True)

    rankings.sort(key=lambda r: (not r["ok_2h_vs_scratch"], -r["objective_4h"], r["gap_mat_4h"]))
    best_key = rankings[0]["key"]
    best = results[best_key]
    best_4h = best["splits"]["teste"]["4h"]["nash"]
    fair_4h = mat_ref_aligned["4h"]["nash"]

    payload = {
        "status": "ok",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "question": (
            "Com rótulos corretos (obs) e trainer PREVINE, o MIMO fecha o gap ao "
            "teto justo (Direct .mat vs obs no alinhado)?"
        ),
        "label_fix": {
            "before": "Tctot1 (predição da rede) usado como y_true",
            "after": "Ttot1 / Ttot (observação) como y_true; Tctot1 só em pred_abs",
        },
        "gate_direct_2h_previne": gate,
        "fair_aligned_ceilings": ceilings,
        "mat_reference_metrics_teste_full": mat_ref_full,
        "mat_reference_aligned_teste": mat_ref_aligned,
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
            "gate_pass": gate["gate_pass"],
            "note": (
                "Rodadas 3–4 mediam contra predições e misturavam teto full 26in. "
                "Aqui o teto justo é Direct vs obs no alinhado (~0,92 no 4h). "
                "Trainer PREVINE é o twin Python; limite restante = multi-saída / 15 vs 26 inputs "
                "ou Cic/nit plenos no MATLAB."
            ),
        },
    }

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    data["schema_version"] = max(int(data.get("schema_version", 4)), 5)
    data["generated_at_utc"] = payload["generated_at_utc"]
    data["experiments"]["exp8_previne_protocol_obs_labels"] = payload
    data["method"]["round5"] = (
        "Corrige y_true=obs (Ttot1); trainer PREVINE (au/bu padded, dunisig, TX adaptativo); "
        "teto justo = Direct .mat vs obs no alinhado."
    )
    data["method"]["note_labels"] = (
        "target_abs/delta vêm de Ttot1/Ttot (observação). Tctot1 fica em pred_abs para auditoria."
    )
    data["mat_reference_aligned_teste"] = mat_ref_aligned
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    out = run_round5()
    print(
        json.dumps(
            {
                "best": out["best_variant"],
                "ranking": out["ranking"][:3],
                "verdict": out["verdict"],
                "gate": out["gate_direct_2h_previne"]["previne_twin_teste"],
                "fair_ceiling_teste": out["mat_reference_aligned_teste"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
