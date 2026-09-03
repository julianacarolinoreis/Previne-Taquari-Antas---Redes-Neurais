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
    compute_metrics,
    evaluate_strategy,
    load_mat_weights,
    predict_direct_batch,
    rising_inconsistency_rate,
    save_json,
)

ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = ROOT / "assets/data/research_mimo_multihorizon_latest.json"


def _mask(rows, split_id: int):
    return [r for r in rows if r["split"] == split_id]


def _stack(rows, datasets, input_idx, output_specs, split_id: int | None = None):
    picked = rows if split_id is None else _mask(rows, split_id)
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


def _fit_search(
    x_tr,
    y_tr,
    x_va,
    y_va,
    hidden_sizes,
    *,
    trajectory_weight=0.0,
    rising_mono_weight=0.0,
    horizon_weights=None,
):
    best = None
    for nh in hidden_sizes:
        for seed in (42, 7, 19):
            model = MimoMLP(x_tr.shape[1], y_tr.shape[1], nh, seed=seed)
            fit = model.fit(
                x_tr,
                y_tr,
                x_va,
                y_va,
                max_epochs=500,
                patience=40,
                lr=0.015,
                seed=seed,
                horizon_weights=horizon_weights,
                trajectory_weight=trajectory_weight,
                rising_mono_weight=rising_mono_weight,
            )
            val_pred = model.forward_delta(x_va)
            val_mse = float(np.mean((val_pred - y_va) ** 2))
            cand = {"model": model, "nh": nh, "seed": seed, "val_mse": val_mse, "fit": fit}
            if best is None or val_mse < best["val_mse"]:
                best = cand
    assert best is not None
    return best


def train_mimo_variants(
    rows,
    datasets,
    input_idx,
    output_specs,
    hidden_sizes,
    *,
    name_suffix="",
    trajectory_weight=0.0,
    rising_mono_weight=0.0,
    horizon_weights=None,
):
    train_rows, x_tr, y_tr, _, _ = _stack(rows, datasets, input_idx, output_specs, 1)
    val_rows, x_va, y_va, _, y_va_abs = _stack(rows, datasets, input_idx, output_specs, 2)
    best = _fit_search(
        x_tr,
        y_tr,
        x_va,
        y_va,
        hidden_sizes,
        trajectory_weight=trajectory_weight,
        rising_mono_weight=rising_mono_weight,
        horizon_weights=horizon_weights,
    )

    def predict_fn(x, atual, _row):
        deltas = best["model"].forward_delta(x)[0]
        return [float(atual + d) for d in deltas]

    result = evaluate_strategy(
        name=f"mimo_nh{best['nh']}_in{datasets[input_idx].n_inputs}_out{len(output_specs)}{name_suffix}",
        rows=rows,
        datasets=datasets,
        input_dataset_idx=input_idx,
        output_specs=output_specs,
        predict_fn=predict_fn,
    )
    # rising-only consistency on validation for diagnostics
    val_pred = best["model"].forward_delta(x_va)
    pred_abs = y_va_abs.copy()
    # rebuild abs from atual of input set
    _, _, _, atual_va, y_va_abs = _stack(rows, datasets, input_idx, output_specs, 2)
    pred_abs = atual_va[:, None] + val_pred
    result["training"] = {
        "hidden": best["nh"],
        "seed": best["seed"],
        "val_mse_delta": best["val_mse"],
        **best["fit"],
        "n_train": len(train_rows),
        "n_val": len(val_rows),
        "rising_consistency_val": rising_inconsistency_rate(y_va_abs, pred_abs),
    }
    return result, best["model"]


def train_direct_scratch(rows, datasets, input_idx, output_specs, hidden_sizes):
    models = []
    for ds_idx, _ in output_specs:
        ds = datasets[ds_idx]
        picked_tr = _mask(rows, 1)
        picked_va = _mask(rows, 2)
        x_tr = np.asarray([ds.inputs[row["indices"][ds_idx]] for row in picked_tr], float)
        y_tr = np.asarray([ds.delta[row["indices"][ds_idx]] for row in picked_tr], float).reshape(-1, 1)
        x_va = np.asarray([ds.inputs[row["indices"][ds_idx]] for row in picked_va], float)
        y_va = np.asarray([ds.delta[row["indices"][ds_idx]] for row in picked_va], float).reshape(-1, 1)
        best = _fit_search(x_tr, y_tr, x_va, y_va, hidden_sizes)
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


def recursive_baseline(rows, datasets, start_ds_idx=0):
    w2 = load_mat_weights(datasets[0].mat_path)
    w4 = load_mat_weights(datasets[1].mat_path)

    def predict_fn(_x, _atual, row):
        i2, i4 = row["indices"][0], row["indices"][1]
        ds2, ds4 = datasets[0], datasets[1]
        pred2 = predict_direct_batch(w2, ds2.inputs[i2 : i2 + 1], ds2.atual[i2 : i2 + 1])[0]
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
    true_abs = []
    pred_abs = []
    for row in rows:
        if row["split"] != 3:
            continue
        ds0 = datasets[output_specs[0][0]]
        x = ds0.inputs[row["indices"][output_specs[0][0]]]
        atual = ds0.atual[row["indices"][output_specs[0][0]]]
        preds = predict_fn(x, atual, row)
        trues = [
            float(datasets[ds_idx].target_abs[row["indices"][ds_idx]]) for ds_idx, _ in output_specs
        ]
        true_abs.append(trues)
        pred_abs.append(preds)
    if not true_abs:
        return {"inconsistent_4h_below_2h_rate": None, "rising_violation_rate": None, "n_test": 0}
    true_abs = np.asarray(true_abs, float)
    pred_abs = np.asarray(pred_abs, float)
    raw = float(np.mean(pred_abs[:, 1] < pred_abs[:, 0]))
    rising = rising_inconsistency_rate(true_abs, pred_abs)
    return {
        "inconsistent_4h_below_2h_rate": raw,
        "rising_violation_rate": rising["rate"],
        "n_rising": rising["n_rising"],
        "n_rising_violations": rising["n_violations"],
        "n_test": int(true_abs.shape[0]),
    }


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


def leave_one_event_out(rows, datasets, input_idx, output_specs, hidden_sizes):
    events = sorted({r["event"] for r in rows if r.get("event") is not None})
    if len(events) < 3:
        return {"status": "skipped", "reason": "menos de 3 eventos alinhados", "events": events}

    per_event = []
    all_true = {datasets[i].name: [] for i, _ in output_specs}
    all_pred_mimo = {datasets[i].name: [] for i, _ in output_specs}
    all_pred_dir = {datasets[i].name: [] for i, _ in output_specs}
    all_pers = {datasets[i].name: [] for i, _ in output_specs}

    for held in events:
        train_rows = [r for r in rows if r["event"] != held]
        test_rows = [r for r in rows if r["event"] == held]
        if len(train_rows) < 50 or len(test_rows) < 5:
            continue
        # Use 80/20 of remaining for train/val by original split when possible
        tr = [r for r in train_rows if r["split"] == 1] or train_rows[: int(0.8 * len(train_rows))]
        va = [r for r in train_rows if r["split"] == 2] or train_rows[int(0.8 * len(train_rows)) :]
        if len(va) < 5:
            va = train_rows[-max(5, len(train_rows) // 5) :]
            tr = [r for r in train_rows if r not in va]
        if len(tr) < 20:
            continue

        _, x_tr, y_tr, _, _ = _stack(tr, datasets, input_idx, output_specs, None)
        _, x_va, y_va, _, _ = _stack(va, datasets, input_idx, output_specs, None)
        mimo = _fit_search(
            x_tr,
            y_tr,
            x_va,
            y_va,
            hidden_sizes,
            trajectory_weight=0.0,
            rising_mono_weight=0.0,
            horizon_weights=None,
        )
        # Direct scratch for each horizon on same fold
        dir_models = []
        for out_i, (ds_idx, _) in enumerate(output_specs):
            y_tr_i = y_tr[:, out_i : out_i + 1]
            y_va_i = y_va[:, out_i : out_i + 1]
            # use horizon-specific inputs
            x_tr_i = np.asarray([datasets[ds_idx].inputs[r["indices"][ds_idx]] for r in tr], float)
            x_va_i = np.asarray([datasets[ds_idx].inputs[r["indices"][ds_idx]] for r in va], float)
            dir_models.append(_fit_search(x_tr_i, y_tr_i, x_va_i, y_va_i, hidden_sizes))

        fold_metrics = {"event": held, "n_test": len(test_rows), "horizons": {}}
        for out_i, (ds_idx, _) in enumerate(output_specs):
            ds = datasets[ds_idx]
            y_true = []
            y_mimo = []
            y_dir = []
            y_pers = []
            for row in test_rows:
                idx = row["indices"][ds_idx]
                atual = float(ds.atual[idx])
                true = float(ds.target_abs[idx])
                x_in = datasets[input_idx].inputs[row["indices"][input_idx]]
                atual_in = float(datasets[input_idx].atual[row["indices"][input_idx]])
                pred_m = float(atual_in + mimo["model"].forward_delta(x_in)[0, out_i])
                x_d = ds.inputs[idx]
                pred_d = float(atual + dir_models[out_i]["model"].forward_delta(x_d)[0, 0])
                y_true.append(true)
                y_mimo.append(pred_m)
                y_dir.append(pred_d)
                y_pers.append(atual)
            yt = np.asarray(y_true)
            ym = np.asarray(y_mimo)
            yd = np.asarray(y_dir)
            yp = np.asarray(y_pers)
            mm = compute_metrics(yt, ym, yp)
            md = compute_metrics(yt, yd, yp)
            fold_metrics["horizons"][ds.name] = {
                "mimo": mm.__dict__,
                "direct_scratch": md.__dict__,
                "delta_nash": mm.nash - md.nash,
                "delta_e95_cm": mm.e95 - md.e95,
            }
            all_true[ds.name].extend(y_true)
            all_pred_mimo[ds.name].extend(y_mimo)
            all_pred_dir[ds.name].extend(y_dir)
            all_pers[ds.name].extend(y_pers)
        per_event.append(fold_metrics)

    pooled = {}
    for name in all_true:
        if not all_true[name]:
            continue
        yt = np.asarray(all_true[name])
        ym = np.asarray(all_pred_mimo[name])
        yd = np.asarray(all_pred_dir[name])
        yp = np.asarray(all_pers[name])
        mm = compute_metrics(yt, ym, yp)
        md = compute_metrics(yt, yd, yp)
        pooled[name] = {
            "mimo": mm.__dict__,
            "direct_scratch": md.__dict__,
            "delta_nash": round(mm.nash - md.nash, 6),
            "delta_pers": round(mm.pers - md.pers, 6),
            "delta_e95_cm": round(mm.e95 - md.e95, 3),
            "n": int(yt.size),
        }

    # Wins by event
    wins = {name: {"mimo": 0, "direct": 0, "tie": 0} for name in all_true}
    for fold in per_event:
        for hz, payload in fold["horizons"].items():
            dn = payload["delta_nash"]
            if dn > 0.002:
                wins[hz]["mimo"] += 1
            elif dn < -0.002:
                wins[hz]["direct"] += 1
            else:
                wins[hz]["tie"] += 1

    return {
        "status": "ok",
        "n_events_evaluated": len(per_event),
        "events_evaluated": [f["event"] for f in per_event],
        "pooled": pooled,
        "wins_by_event": wins,
        "per_event": per_event,
    }


def run_all(output: Path) -> dict:
    aligned_24 = align_horizons(["2h", "4h"])
    rows24 = aligned_24["rows"]
    ds24 = aligned_24["datasets"]
    specs24 = [(0, 0), (1, 1)]

    direct24 = direct_baseline(rows24, ds24, specs24)
    scratch24 = train_direct_scratch(rows24, ds24, 0, specs24, hidden_sizes=[20, 30, 40, 52])
    mimo15_24, model15 = train_mimo_variants(rows24, ds24, 0, specs24, hidden_sizes=[20, 30, 40, 52])
    mimo15_mono, model15_mono = train_mimo_variants(
        rows24,
        ds24,
        0,
        specs24,
        hidden_sizes=[20, 30, 40, 52],
        name_suffix="_traj",
        trajectory_weight=0.15,
        rising_mono_weight=0.0,
        horizon_weights=np.asarray([1.0, 1.0]),
    )

    def mimo_repair_predict(x, atual, _row):
        deltas = model15.forward_delta(x)[0]
        d2, d4 = float(deltas[0]), float(deltas[1])
        # Correção pós-hoc: se ambos apontam subida e a trajetória inverte, eleva o 4h.
        if d2 > 0 and d4 > 0 and (atual + d4) < (atual + d2):
            d4 = d2
        return [float(atual + d2), float(atual + d4)]

    mimo_repair = evaluate_strategy(
        name="mimo_nh_posthoc_rising_repair",
        rows=rows24,
        datasets=ds24,
        input_dataset_idx=0,
        output_specs=specs24,
        predict_fn=mimo_repair_predict,
    )
    recursive24 = recursive_baseline(rows24, ds24)
    summary24 = build_summary_vs(direct24, mimo15_24, recursive24)
    summary24_scratch = build_summary_vs(scratch24, mimo15_24)
    summary24_mono = build_summary_vs(scratch24, mimo15_mono)
    summary24_repair = build_summary_vs(scratch24, mimo_repair)

    mimo26_24, _ = train_mimo_variants(rows24, ds24, 1, specs24, hidden_sizes=[30, 40, 52, 63])
    summary26 = build_summary_vs(scratch24, mimo26_24)

    aligned_248 = align_horizons(["2h", "4h", "8h"])
    rows248 = aligned_248["rows"]
    ds248 = aligned_248["datasets"]
    specs248 = [(0, 0), (1, 1), (2, 2)]
    direct248 = direct_baseline(rows248, ds248, specs248)
    scratch248 = train_direct_scratch(rows248, ds248, 2, specs248, hidden_sizes=[40, 52, 63, 80])
    mimo31_248, _ = train_mimo_variants(rows248, ds248, 2, specs248, hidden_sizes=[40, 52, 63, 80])
    summary248 = build_summary_vs(scratch248, mimo31_248)

    aligned_48 = align_horizons(["4h", "8h"])
    rows48 = aligned_48["rows"]
    ds48 = aligned_48["datasets"]
    specs48 = [(0, 0), (1, 1)]
    direct48 = direct_baseline(rows48, ds48, specs48)
    scratch48 = train_direct_scratch(rows48, ds48, 1, specs48, hidden_sizes=[40, 52, 63])
    mimo31_48, _ = train_mimo_variants(rows48, ds48, 1, specs48, hidden_sizes=[40, 52, 63])
    summary48 = build_summary_vs(scratch48, mimo31_48)

    loo = leave_one_event_out(rows24, ds24, 0, specs24, hidden_sizes=[30, 40])

    def mimo15_predict(x, atual, row):
        deltas = model15.forward_delta(x)[0]
        return [float(atual + d) for d in deltas]

    def mimo_mono_predict(x, atual, row):
        deltas = model15_mono.forward_delta(x)[0]
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
        "mimo_15in_traj_2h4h": trajectory_consistency(rows24, ds24, mimo_mono_predict, specs24),
        "mimo_15in_repair_2h4h": trajectory_consistency(rows24, ds24, mimo_repair_predict, specs24),
        "direct_2h4h": trajectory_consistency(rows24, ds24, direct24_predict, specs24),
    }

    payload = {
        "schema_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "title": "Experimento RNA multi-horizonte (MIMO) — Santa Tereza",
        "method": {
            "strategy_baseline": "Direct por horizonte (.mat auditados, mesmas amostras alinhadas)",
            "strategy_mimo": "MLP multi-saída logsig, early stopping na validação (X=2), targets = delta ALT",
            "strategy_mimo_traj": "MIMO + loss leve de formato (pred4-pred2 ≈ true4-true2)",
            "strategy_mimo_repair": "MIMO base + correção pós-hoc quando d2>0, d4>0 e nível 4h < 2h",
            "note_mono_loss": "Penalidade ReLU em subidas com 4h<2h foi testada e piorou NASH/PERS; não usada na variante final",
            "alignment_key": "nível ST + três primeiros inputs (arredondamento 0,1 cm)",
            "loo": "leave-one-event-out nos eventos do workbook auditável alinhado 2h+4h",
            "splits": {"1": "treino", "2": "validacao", "3": "teste"},
        },
        "datasets": {
            "2h_4h_aligned": {
                "n_rows": len(rows24),
                "split_counts": {str(k): len(_mask(rows24, k)) for k in (1, 2, 3)},
                "n_events": len({r["event"] for r in rows24 if r.get("event") is not None}),
            },
            "2h_4h_8h_aligned": {"n_rows": len(rows248), "split_counts": {str(k): len(_mask(rows248, k)) for k in (1, 2, 3)}},
            "4h_8h_aligned": {"n_rows": len(rows48), "split_counts": {str(k): len(_mask(rows48, k)) for k in (1, 2, 3)}},
        },
        "experiments": {
            "exp1_2h4h_15in": {
                "direct_mat": direct24,
                "direct_scratch": scratch24,
                "mimo": mimo15_24,
                "mimo_traj": mimo15_mono,
                "mimo_rising_repair": mimo_repair,
                "recursive_2h_4h": recursive24,
                "summary_mat_vs_mimo": summary24,
                "summary_scratch_vs_mimo": summary24_scratch,
                "summary_scratch_vs_mimo_traj": summary24_mono,
                "summary_scratch_vs_mimo_repair": summary24_repair,
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
            "exp5_leave_one_event_out_2h4h": loo,
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
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(args.output),
                "experiments": list(payload["experiments"].keys()),
                "loo_status": payload["experiments"]["exp5_leave_one_event_out_2h4h"].get("status"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
