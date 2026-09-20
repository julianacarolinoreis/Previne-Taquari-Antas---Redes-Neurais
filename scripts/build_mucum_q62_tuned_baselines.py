#!/usr/bin/env python3
"""Tune simple baselines on validation events, then test on frozen Q62 rows."""

from __future__ import annotations

import json
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from build_mucum_q62_model_comparison import (
    AUDIT,
    CANONICAL,
    EVENTS,
    OUTPUT_JSON as INITIAL_JSON,
    common_keys,
    metric_rows,
    read_workbook,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_JSON = ROOT / "assets" / "data" / "mucum_q62" / "mucum_q62_tuned_baselines.json"


def mean_event_mae(estimator, rows_by_event: dict[int, list[dict]], features: int) -> float:
    scores = []
    for rows in rows_by_event.values():
        x = np.asarray([row["features"] for row in rows], dtype=float).reshape(-1, features)
        y = np.asarray([row["observed"] for row in rows], dtype=float)
        pred = estimator.predict(x)
        scores.append(float(np.mean(np.abs(pred - y))))
    return float(np.mean(scores))


def estimator_grid(name: str):
    if name == "Ridge":
        return [(f"alpha={alpha}", make_pipeline(StandardScaler(), Ridge(alpha=alpha))) for alpha in (0.1, 1.0, 10.0, 100.0)]
    if name == "MLP":
        return [
            (f"layers={layers};alpha={alpha}", make_pipeline(StandardScaler(), MLPRegressor(hidden_layer_sizes=layers, activation="relu", solver="lbfgs", alpha=alpha, max_iter=800, random_state=42)))
            for layers in ((16,), (32, 16)) for alpha in (0.001, 0.01)
        ]
    if name == "Random Forest":
        return [
            (f"depth={depth};leaf={leaf}", RandomForestRegressor(n_estimators=220, max_depth=depth, min_samples_leaf=leaf, random_state=42, n_jobs=2))
            for depth in (6, 12, None) for leaf in (1, 2)
        ]
    if name == "XGBoost":
        return [
            (
                f"trees={trees};depth={depth};lr={learning_rate}",
                XGBRegressor(n_estimators=trees, max_depth=depth, learning_rate=learning_rate, min_child_weight=2, subsample=0.9, colsample_bytree=0.9, objective="reg:squarederror", eval_metric="rmse", random_state=42, n_jobs=2, tree_method="hist"),
            )
            for trees in (120, 240) for depth in (2, 3) for learning_rate in (0.03, 0.06)
        ]
    raise KeyError(name)


def build() -> dict:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    initial = json.loads(INITIAL_JSON.read_text(encoding="utf-8"))
    by_horizon = defaultdict(list)
    source = {}
    for model in audit["models"]:
        item = read_workbook(model)
        source[item["model_id"]] = item
        by_horizon[item["horizon"]].append(item)
    aggregate = []
    event_metrics = []
    tuning = {}
    for horizon in sorted(by_horizon):
        workbooks = sorted(by_horizon[horizon], key=lambda item: item["model_id"])
        keys_by_event = common_keys(workbooks, "Teste")
        canonical = next(item for item in workbooks if item["model_id"].startswith(CANONICAL[horizon]))
        by_key = {row["key"]: row for row in canonical["rows"]}
        test_keys = [key for event in EVENTS for key in keys_by_event.get(event, [])]
        train = [row for row in canonical["rows"] if row["partition"] == "Treino"]
        valid_by_event = defaultdict(list)
        for row in canonical["rows"]:
            if row["partition"] == "Validacao":
                valid_by_event[row["event"]].append(row)
        validation = [row for rows in valid_by_event.values() for row in rows]
        train_plus_valid = train + validation
        if not validation:
            raise RuntimeError(f"horizonte {horizon}: nenhuma linha de validação")
        test_rows = [by_key[key] for key in test_keys]
        predictions = {}
        methods = {}
        for workbook in workbooks:
            rows_by_key = {row["key"]: row for row in workbook["rows"]}
            name = f"RNA {workbook['model_id'][:3]}"
            predictions[name] = {key: rows_by_key[key]["rna"] for key in test_keys}
            methods[name] = ("RNA fonte Q62", workbook["model_id"])
        predictions["Persistência"] = {key: by_key[key]["current"] for key in test_keys}
        methods["Persistência"] = ("baseline", "nivel_86510000")
        train_x = np.asarray([row["features"] for row in train], dtype=float)
        train_y = np.asarray([row["observed"] for row in train], dtype=float)
        full_x = np.asarray([row["features"] for row in train_plus_valid], dtype=float)
        full_y = np.asarray([row["observed"] for row in train_plus_valid], dtype=float)
        valid_x = np.asarray([row["features"] for row in validation], dtype=float)
        valid_y = np.asarray([row["observed"] for row in validation], dtype=float)
        tuning[str(horizon)] = {"validation_events": sorted(valid_by_event), "validation_points": len(validation), "selected": {}}
        for model_name in ("Ridge", "MLP", "Random Forest", "XGBoost"):
            candidates = []
            for label, estimator in estimator_grid(model_name):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    estimator.fit(train_x, train_y)
                score = mean_event_mae(estimator, valid_by_event, len(canonical["features"]))
                candidates.append((score, label, estimator))
            score, label, _ = min(candidates, key=lambda item: item[0])
            selected = dict(estimator_grid(model_name))[label]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                selected.fit(full_x, full_y)
            pred = selected.predict(np.asarray([row["features"] for row in test_rows], dtype=float))
            predictions[model_name] = {key: float(value) for key, value in zip(test_keys, pred)}
            methods[model_name] = ("baseline_tuned_validation", label)
            tuning[str(horizon)]["selected"][model_name] = {"configuration": label, "validation_event_mae_cm": round(score, 6), "train_points_after_tuning": len(train_plus_valid)}
        by_model_event = defaultdict(list)
        for model_name, pred_map in predictions.items():
            for event in EVENTS:
                rows = [{**by_key[key], "predicted": pred_map[key]} for key in keys_by_event.get(event, [])]
                metrics = metric_rows(rows, model_name, horizon, methods[model_name][0], methods[model_name][1])
                metrics["event"] = event
                metrics["n_common_event_points"] = len(rows)
                metrics["protocol"] = "tuned_validation_then_train_plus_validation"
                event_metrics.append(metrics)
                by_model_event[model_name].append(metrics)
            pooled = metric_rows([{**by_key[key], "predicted": pred_map[key]} for key in test_keys], model_name, horizon, methods[model_name][0], methods[model_name][1])
            event_mae = [item["mae_cm"] for item in by_model_event[model_name]]
            event_peak = [item["peak_abs_error_cm"] for item in by_model_event[model_name]]
            aggregate.append({**pooled, "protocol": "tuned_validation_then_train_plus_validation", "event_mae_mean_cm": round(float(np.mean(event_mae)), 6), "event_mae_median_cm": round(float(np.median(event_mae)), 6), "event_mae_worst_cm": round(float(np.max(event_mae)), 6), "event_peak_abs_error_mean_cm": round(float(np.mean(event_peak)), 6), "event_peak_abs_error_worst_cm": round(float(np.max(event_peak)), 6), "train_points": len(train_plus_valid), "validation_points": len(validation), "common_test_points": len(test_keys)})
    for horizon in sorted(by_horizon):
        horizon_rows = [item for item in aggregate if item["horizon_hours"] == horizon]
        horizon_events = defaultdict(list)
        for item in event_metrics:
            if item["horizon_hours"] == horizon:
                horizon_events[item["event"]].append(item)
        for item in horizon_rows:
            item["best_event_mae_count"] = sum(min(group, key=lambda candidate: candidate["mae_cm"])["model"] == item["model"] for group in horizon_events.values())

    output = {
        "schema_version": 1,
        "artifact_id": "mucum_q62_tuned_baselines",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "status": "research_only_test_frozen_after_validation_tuning",
        "research_only": True,
        "official_alert": False,
        "promotion_allowed": False,
        "purpose": "Rodada complementar: hiperparâmetros selecionados em eventos Validacao; baselines refitados em Treino + Validacao; teste comum Q62 congelado.",
        "method": {"tuning_partition": "Validacao", "fit_partition_after_tuning": "Treino + Validacao", "test_partition": "Teste", "test_events": list(EVENTS), "same_common_test_rows": True, "no_future_features": True, "selection_metric": "media do MAE por evento na validação", "initial_benchmark": INITIAL_JSON.relative_to(ROOT).as_posix()},
        "fairness_by_horizon": initial["fairness_by_horizon"],
        "tuning": tuning,
        "aggregate_metrics": sorted(aggregate, key=lambda item: (item["horizon_hours"], item["event_mae_mean_cm"])),
        "event_metrics": event_metrics,
        "skipped_models": [{"model": "LSTM/GRU", "status": "not_executed", "reason": "sem runtime temporal auditado neste contrato"}, {"model": "Transformer temporal", "status": "not_executed", "reason": "sem sequência temporal padronizada neste pacote"}, {"model": "Transformer-GNN", "status": "not_executed", "reason": "sem grafo hidrográfico multie estação validado"}],
        "sources": ["assets/data/mucum_q62_auditoria.json", "assets/audit_workbooks/"],
    }
    OUTPUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    result = build()
    print(json.dumps({"output": OUTPUT_JSON.relative_to(ROOT).as_posix(), "aggregate_rows": len(result["aggregate_metrics"]), "event_rows": len(result["event_metrics"])}, ensure_ascii=False))
