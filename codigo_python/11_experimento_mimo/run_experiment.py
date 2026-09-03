#!/usr/bin/env python3
"""Executa experimentos RNA multi-horizonte (MIMO) e grava relatório JSON."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from mimo_core import (
    MimoMLP,
    align_horizons,
    evaluate_strategy,
    load_horizon_dataset,
    load_mat_weights,
    predict_direct_batch,
    save_json,
)

ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = ROOT / "assets/data/research_mimo_multihorizon_latest.json"


def _mask(rows, split_id: int):
    return [r for r in rows if r["split"] == split_id]


def _stack(rows, datasets, input_idx, output_specs, split_id: int):
    picked = _mask(rows, split_id)
    x = np.asarray([datasets[input_idx].inputs[row["indices"][input_idx]] for row in picked], float)
    y = np.asarray(
        [[datasets[ds_idx].delta[row["indices"][ds_idx]] for ds_idx, _ in output_specs] for row in picked],
        float,
    )
    atual = np.asarray([datasets[input_idx].atual[row["indices"][input_idx]] for row in picked], float)
    y_abs = np.asarray(
        [[datasets[ds_idx].target_abs[row["indices"][ds_idx]] for ds_idx, _ in output_specs] for row in picked],
        float,
    )
    return picked, x, y, atual, y_abs


def train_mimo_variants(rows, datasets, input_idx, output_specs, hidden_sizes):
    train_rows, x_tr, y_tr, _, _ = _stack(rows, datasets, input_idx, output_specs, 1)
    val_rows, x_va, y_va, _, _ = _stack(rows, datasets, input_idx, output_specs, 2)
    best = None
    for nh in hidden_sizes:
        for seed in (42, 7, 19):
            model = MimoMLP(x_tr.shape[1], y_tr.shape[1], nh, seed=seed)
            fit = model.fit(x_tr, y_tr, x_va, y_va, max_epochs=500, patience=40, lr=0.015, seed=seed)
            val_pred = model.forward_delta(x_va)
            val_mse = float(np.mean((val_pred - y_va) ** 2))
            cand = {"model": model, "nh": nh, "seed": seed, "val_mse": val_mse, "fit": fit}
            if best is None or val_mse < best["val_mse"]:
                best = cand
    assert best is not None

    def predict_fn(x, atual, _row):
        deltas = best["model"].forward_delta(x)[0]
        return [float(atual + d) for d in deltas]

    result = evaluate_strategy(
        name=f"mimo_nh{best['nh']}_in{datasets[input_idx].n_inputs}_out{len(output_specs)}",
        rows=rows,
        datasets=datasets,
        input_dataset_idx=input_idx,
        output_specs=output_specs,
        predict_fn=predict_fn,
    )
    result["training"] = {
        "hidden": best["nh"],
        "seed": best["seed"],
        "val_mse_delta": best["val_mse"],
        **best["fit"],
        "n_train": len(train_rows),
        "n_val": len(val_rows),
    }
    return result, best["model"]


def direct_baseline(rows, datasets, output_specs):
    weights = {ds.name: load_mat_weights(ds.mat_path) for ds in datasets}

    def predict_fn(x, atual, row):
        out = []
        for ds_idx, _ in output_specs:
            ds = datasets[ds_idx]
            idx = row["indices"][ds_idx]
            w = weights[ds.name]
            pred = predict_direct_batch(w, ds.inputs[idx : idx + 1], ds.atual[idx : idx + 1])[0]
            out.append(float(pred))
        return out

    return evaluate_strategy(
        name="direct_por_horizonte",
        rows=rows,
        datasets=datasets,
        input_dataset_idx=0,
        output_specs=output_specs,
        predict_fn=predict_fn,
    )


def dirmo_baseline(rows, datasets, input_idx, output_specs):
    """DirMO com bloco=1: um modelo direct por horizonte, mesma amostra alinhada."""
    weights = {datasets[i].name: load_mat_weights(datasets[i].mat_path) for i, _ in output_specs}

    def predict_fn(_x, _atual, row):
        out = []
        for ds_idx, _ in output_specs:
            ds = datasets[ds_idx]
            idx = row["indices"][ds_idx]
            w = weights[ds.name]
            pred = predict_direct_batch(w, ds.inputs[idx : idx + 1], ds.atual[idx : idx + 1])[0]
            out.append(float(pred))
        return out

    return evaluate_strategy(
        name="dirmo_bloco1_equivalente_direct",
        rows=rows,
        datasets=datasets,
        input_dataset_idx=input_idx,
        output_specs=output_specs,
        predict_fn=predict_fn,
    )


def recursive_baseline(rows, datasets, start_ds_idx=0):
    """Recursivo 2h→4h encadeando previsões (baseline negativo)."""
    w2 = load_mat_weights(datasets[0].mat_path)
    w4 = load_mat_weights(datasets[1].mat_path)

    def predict_fn(_x, _atual, row):
        i2, i4 = row["indices"][0], row["indices"][1]
        ds2, ds4 = datasets[0], datasets[1]
        pred2 = predict_direct_batch(w2, ds2.inputs[i2 : i2 + 1], ds2.atual[i2 : i2 + 1])[0]
        # aproximação operacional: reutiliza inputs 4h mas substitui nível atual pelo previsto 2h
        x4 = ds4.inputs[i4].copy()
        x4[0] = pred2
        pred4_rec = predict_direct_batch(w4, x4[None, :], np.asarray([pred2]))[0]
        return [float(pred2), float(pred4_rec)]

    return evaluate_strategy(
        name="recursivo_2h_para_4h",
        rows=rows,
        datasets=datasets[:2],
        input_dataset_idx=start_ds_idx,
        output_specs=[(0, 0), (1, 1)],
        predict_fn=predict_fn,
    )


def trajectory_consistency(rows, datasets, predict_fn, output_specs):
    vals = []
    for row in rows:
        if row["split"] != 3:
            continue
        ds0 = datasets[output_specs[0][0]]
        x = ds0.inputs[row["indices"][output_specs[0][0]]]
        atual = ds0.atual[row["indices"][output_specs[0][0]]]
        preds = predict_fn(x, atual, row)
        if len(preds) >= 2 and preds[1] < preds[0]:
            vals.append(1)
        else:
            vals.append(0)
    return {"inconsistent_4h_below_2h_rate": float(np.mean(vals)) if vals else None, "n_test": len(vals)}


def train_direct_scratch(rows, datasets, input_idx, output_specs, hidden_sizes):
    models = []
    metrics = {}
    for ds_idx, _ in output_specs:
        ds = datasets[ds_idx]
        picked_tr = _mask(rows, 1)
        picked_va = _mask(rows, 2)
        x_tr = np.asarray([ds.inputs[row["indices"][ds_idx]] for row in picked_tr], float)
        y_tr = np.asarray([ds.delta[row["indices"][ds_idx]] for row in picked_tr], float).reshape(-1, 1)
        x_va = np.asarray([ds.inputs[row["indices"][ds_idx]] for row in picked_va], float)
        y_va = np.asarray([ds.delta[row["indices"][ds_idx]] for row in picked_va], float).reshape(-1, 1)
        best = None
        for nh in hidden_sizes:
            for seed in (42, 7, 19):
                model = MimoMLP(x_tr.shape[1], 1, nh, seed=seed)
                fit = model.fit(x_tr, y_tr, x_va, y_va, max_epochs=500, patience=40, lr=0.015, seed=seed)
                val_mse = float(np.mean((model.forward_delta(x_va) - y_va) ** 2))
                cand = {"model": model, "nh": nh, "seed": seed, "val_mse": val_mse, "fit": fit, "ds_idx": ds_idx}
                if best is None or val_mse < best["val_mse"]:
                    best = cand
        models.append(best)

    def predict_fn(_x, _atual, row):
        out = []
        for spec, trained in zip(output_specs, models):
            ds_idx, _ = spec
            ds = datasets[ds_idx]
            idx = row["indices"][ds_idx]
            x = ds.inputs[idx]
            atual = ds.atual[idx]
            delta = trained["model"].forward_delta(x)[0, 0]
            out.append(float(atual + delta))
        return out

    result = evaluate_strategy(
        name="direct_scratch_mesmo_treino",
        rows=rows,
        datasets=datasets,
        input_dataset_idx=input_idx,
        output_specs=output_specs,
        predict_fn=predict_fn,
    )
    result["training"] = [
        {"horizon": datasets[s[0]].name, "hidden": m["nh"], "seed": m["seed"], "val_mse_delta": m["val_mse"]}
        for s, m in zip(output_specs, models)
    ]
    return result


def build_summary_vs(direct, mimo, recursive=None):
    summary = {"ganhos": [], "perdas": [], "empates": []}
    for hz in direct["splits"].get("teste", {}):
        d = direct["splits"]["teste"][hz]
        m = mimo["splits"]["teste"].get(hz)
        if not m:
            continue
        delta_nash = m["nash"] - d["nash"]
        delta_pers = m["pers"] - d["pers"]
        delta_e95 = m["e95"] - d["e95"]
        item = {
            "horizonte": hz,
            "delta_nash": round(delta_nash, 6),
            "delta_pers": round(delta_pers, 6),
            "delta_e95_cm": round(delta_e95, 3),
            "direct": {k: round(d[k], 4) if isinstance(d[k], float) else d[k] for k in ("nash", "pers", "e95", "mae", "n")},
            "mimo": {k: round(m[k], 4) if isinstance(m[k], float) else m[k] for k in ("nash", "pers", "e95", "mae", "n")},
        }
        if delta_nash > 0.002 and delta_e95 <= 0:
            summary["ganhos"].append(item)
        elif delta_nash < -0.002 or delta_e95 > 1.0:
            summary["perdas"].append(item)
        else:
            summary["empates"].append(item)
    if recursive and recursive["splits"].get("teste"):
        for hz in recursive["splits"]["teste"]:
            summary.setdefault("recursivo_vs_direct", {})[hz] = {
                "delta_nash": round(
                    recursive["splits"]["teste"][hz]["nash"] - direct["splits"]["teste"][hz]["nash"], 6
                ),
                "delta_e95_cm": round(
                    recursive["splits"]["teste"][hz]["e95"] - direct["splits"]["teste"][hz]["e95"], 3
                ),
            }
    return summary


def run_all(output: Path) -> dict:
    # --- Experimento 1: 2h + 4h com 15 inputs (subconjunto comum) ---
    aligned_24 = align_horizons(["2h", "4h"])
    rows24 = aligned_24["rows"]
    ds24 = aligned_24["datasets"]
    specs24 = [(0, 0), (1, 1)]
    direct24 = direct_baseline(rows24, ds24, specs24)
    scratch24 = train_direct_scratch(rows24, ds24, 0, specs24, hidden_sizes=[20, 30, 40, 52])
    mimo15_24, model15 = train_mimo_variants(rows24, ds24, 0, specs24, hidden_sizes=[20, 30, 40, 52])
    recursive24 = recursive_baseline(rows24, ds24)
    summary24 = build_summary_vs(direct24, mimo15_24, recursive24)
    summary24_scratch = build_summary_vs(scratch24, mimo15_24)

    # --- Experimento 2: 2h + 4h com 26 inputs ---
    mimo26_24, _ = train_mimo_variants(rows24, ds24, 1, specs24, hidden_sizes=[30, 40, 52, 63])
    summary26 = build_summary_vs(scratch24, mimo26_24)

    # --- Experimento 3: 2h + 4h + 8h com 31 inputs ---
    aligned_248 = align_horizons(["2h", "4h", "8h"])
    rows248 = aligned_248["rows"]
    ds248 = aligned_248["datasets"]
    specs248 = [(0, 0), (1, 1), (2, 2)]
    direct248 = direct_baseline(rows248, ds248, specs248)
    scratch248 = train_direct_scratch(rows248, ds248, 2, specs248, hidden_sizes=[40, 52, 63, 80])
    mimo31_248, _ = train_mimo_variants(rows248, ds248, 2, specs248, hidden_sizes=[40, 52, 63, 80])
    summary248 = build_summary_vs(scratch248, mimo31_248)

    # --- Experimento 4: 4h + 8h (26 inputs indisponível para 8h; usa 31) ---
    aligned_48 = align_horizons(["4h", "8h"])
    rows48 = aligned_48["rows"]
    ds48 = aligned_48["datasets"]
    specs48 = [(0, 0), (1, 1)]
    direct48 = direct_baseline(rows48, ds48, specs48)
    scratch48 = train_direct_scratch(rows48, ds48, 1, specs48, hidden_sizes=[40, 52, 63])
    mimo31_48, _ = train_mimo_variants(rows48, ds48, 1, specs48, hidden_sizes=[40, 52, 63])
    summary48 = build_summary_vs(scratch48, mimo31_48)

    def mimo15_predict(x, atual, row):
        deltas = model15.forward_delta(x)[0]
        return [float(atual + d) for d in deltas]

    weights24 = {ds.name: load_mat_weights(ds.mat_path) for ds in ds24}

    def direct24_predict(_x, _atual, row):
        out = []
        for ds_idx, _ in specs24:
            ds = ds24[ds_idx]
            idx = row["indices"][ds_idx]
            w = weights24[ds.name]
            pred = predict_direct_batch(w, ds.inputs[idx : idx + 1], ds.atual[idx : idx + 1])[0]
            out.append(float(pred))
        return out

    consistency = {
        "mimo_15in_2h4h": trajectory_consistency(rows24, ds24, mimo15_predict, specs24),
        "direct_2h4h": trajectory_consistency(rows24, ds24, direct24_predict, specs24),
    }

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "title": "Experimento RNA multi-horizonte (MIMO) — Santa Tereza",
        "method": {
            "strategy_baseline": "Direct por horizonte (.mat auditados, mesmas amostras alinhadas)",
            "strategy_mimo": "MLP multi-saída logsig, early stopping na validação (X=2), targets = delta ALT",
            "alignment_key": "nível ST + três primeiros inputs (arredondamento 0,1 cm)",
            "splits": {"1": "treino", "2": "validacao", "3": "teste"},
        },
        "datasets": {
            "2h_4h_aligned": {"n_rows": len(rows24), "split_counts": {str(k): len(_mask(rows24, k)) for k in (1, 2, 3)}},
            "2h_4h_8h_aligned": {"n_rows": len(rows248), "split_counts": {str(k): len(_mask(rows248, k)) for k in (1, 2, 3)}},
            "4h_8h_aligned": {"n_rows": len(rows48), "split_counts": {str(k): len(_mask(rows48, k)) for k in (1, 2, 3)}},
        },
        "experiments": {
            "exp1_2h4h_15in": {
                "direct_mat": direct24,
                "direct_scratch": scratch24,
                "mimo": mimo15_24,
                "recursive_2h_4h": recursive24,
                "summary_mat_vs_mimo": summary24,
                "summary_scratch_vs_mimo": summary24_scratch,
            },
            "exp2_2h4h_26in": {
                "direct_mat": direct24,
                "direct_scratch": scratch24,
                "mimo": mimo26_24,
                "summary_scratch_vs_mimo": summary26,
            },
            "exp3_2h4h8h_31in": {
                "direct_mat": direct248,
                "direct_scratch": scratch248,
                "mimo": mimo31_248,
                "summary_scratch_vs_mimo": summary248,
            },
            "exp4_4h8h_31in": {
                "direct_mat": direct48,
                "direct_scratch": scratch48,
                "mimo": mimo31_48,
                "summary_scratch_vs_mimo": summary48,
            },
        },
        "mat_reference_metrics_teste": {
            "2h": {"nash": 0.9962, "pers": 0.9688, "e95": 10.39, "note": "mat completo, não recorte alinhado"},
            "4h": {"nash": 0.9926, "pers": 0.8782, "e95": 58.84, "note": "mat completo"},
            "8h_v001": {"note": "ver .mat; recorte alinhado menor"},
        },
        "trajectory_consistency": consistency,
    }
    save_json(output, payload)
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT_JSON)
    args = parser.parse_args()
    payload = run_all(args.output)
    print(json.dumps({"ok": True, "output": str(args.output), "experiments": list(payload["experiments"].keys())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
