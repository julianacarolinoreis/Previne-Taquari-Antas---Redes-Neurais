#!/usr/bin/env python3
"""PREVINE AI Lab — fase 2: comparação controlada com redes temporais.

Todos os modelos usam as mesmas linhas-alvo elegíveis a uma janela máxima de
sequência. Os modelos estáticos recebem apenas o vetor do horário atual; LSTM,
GRU, TCN e Transformer recebem a sequência histórica. Perfis temporais são
selecionados exclusivamente no evento de validação de cada dobra causal. O
resultado nunca promove automaticamente um modelo para operação.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import warnings
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.base import clone

import ai_lab_auto_train as phase1

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
except Exception as exc:  # pragma: no cover - audited at runtime
    torch = None
    nn = None
    DataLoader = None
    TensorDataset = None
    TORCH_IMPORT_ERROR = repr(exc)
else:
    TORCH_IMPORT_ERROR = None


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "assets" / "data" / "ai_lab" / "experiments.json"
OUT_JSON = ROOT / "assets" / "data" / "ai_lab" / "auto_training_v2_latest.json"
OUT_CSV = ROOT / "assets" / "data" / "ai_lab" / "auto_training_v2_leaderboard.csv"

TEMPORAL_NAMES = ("LSTM", "GRU", "TCN", "Transformer temporal")


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    if torch is not None:
        torch.manual_seed(seed)
        torch.set_num_threads(2)
        try:
            torch.use_deterministic_algorithms(True)
        except Exception:
            pass


def build_sequence_samples(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    temporal = config.get("temporal", {})
    max_lookback = int(temporal.get("max_lookback_h", 8))
    expected_step = float(temporal.get("expected_step_minutes", 60))
    tolerance = float(temporal.get("step_tolerance_minutes", 5))
    by_event: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_event[int(row["event"])].append(row)
    samples: list[dict[str, Any]] = []
    gap_rejections = 0
    warmup_rejections = 0
    event_counts: dict[str, int] = {}
    for event, group in by_event.items():
        group.sort(key=lambda r: r["timestamp"])
        accepted = 0
        for idx, target_row in enumerate(group):
            if idx + 1 < max_lookback:
                warmup_rejections += 1
                continue
            window = group[idx - max_lookback + 1 : idx + 1]
            deltas = [
                (window[j]["timestamp"] - window[j - 1]["timestamp"]).total_seconds() / 60.0
                for j in range(1, len(window))
            ]
            if any(abs(delta - expected_step) > tolerance for delta in deltas):
                gap_rejections += 1
                continue
            sample = dict(target_row)
            sample["sequence"] = [list(row["features"]) for row in window]
            sample["features"] = list(target_row["features"])
            samples.append(sample)
            accepted += 1
        event_counts[str(event)] = accepted
    samples.sort(key=lambda r: (r["timestamp"], r["event"]))
    return samples, {
        "max_lookback_h": max_lookback,
        "expected_step_minutes": expected_step,
        "step_tolerance_minutes": tolerance,
        "eligible_sequence_rows": len(samples),
        "warmup_rows_removed": warmup_rejections,
        "gap_windows_removed": gap_rejections,
        "eligible_rows_by_event": event_counts,
    }


if nn is not None:
    class RNNRegressor(nn.Module):
        def __init__(self, kind: str, input_size: int, width: int):
            super().__init__()
            rnn_cls = nn.LSTM if kind == "LSTM" else nn.GRU
            self.rnn = rnn_cls(input_size=input_size, hidden_size=width, num_layers=1, batch_first=True)
            self.head = nn.Sequential(nn.LayerNorm(width), nn.Linear(width, 1))

        def forward(self, x):
            out, _ = self.rnn(x)
            return self.head(out[:, -1, :]).squeeze(-1)


    class TCNRegressor(nn.Module):
        def __init__(self, input_size: int, width: int):
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv1d(input_size, width, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.Conv1d(width, width, kernel_size=3, dilation=2, padding=2),
                nn.ReLU(),
                nn.Conv1d(width, width, kernel_size=3, dilation=4, padding=4),
                nn.ReLU(),
            )
            self.head = nn.Sequential(nn.LayerNorm(width), nn.Linear(width, 1))

        def forward(self, x):
            z = self.net(x.transpose(1, 2))[:, :, -1]
            return self.head(z).squeeze(-1)


    class TransformerRegressor(nn.Module):
        def __init__(self, input_size: int, width: int, max_len: int):
            super().__init__()
            nhead = 4 if width % 4 == 0 else 2
            self.project = nn.Linear(input_size, width)
            self.position = nn.Parameter(torch.zeros(1, max_len, width))
            nn.init.normal_(self.position, std=0.02)
            layer = nn.TransformerEncoderLayer(
                d_model=width,
                nhead=nhead,
                dim_feedforward=width * 2,
                dropout=0.10,
                activation="gelu",
                batch_first=True,
                norm_first=True,
            )
            self.encoder = nn.TransformerEncoder(layer, num_layers=1)
            self.head = nn.Sequential(nn.LayerNorm(width), nn.Linear(width, 1))

        def forward(self, x):
            z = self.project(x)
            z = z + self.position[:, : z.shape[1], :]
            z = self.encoder(z)
            return self.head(z[:, -1, :]).squeeze(-1)


def build_temporal_model(name: str, input_size: int, profile: dict[str, Any]):
    width = int(profile["width"])
    lookback = int(profile["lookback_h"])
    if name == "LSTM":
        return RNNRegressor("LSTM", input_size, width)
    if name == "GRU":
        return RNNRegressor("GRU", input_size, width)
    if name == "TCN":
        return TCNRegressor(input_size, width)
    if name == "Transformer temporal":
        return TransformerRegressor(input_size, width, lookback)
    raise KeyError(name)


def temporal_profiles(config: dict[str, Any]) -> list[dict[str, Any]]:
    temporal = config.get("temporal", {})
    supplied = temporal.get("profiles")
    if supplied:
        return [dict(item) for item in supplied]
    return [
        {"id": "short_4h_level", "lookback_h": 4, "width": 32, "learning_rate": 0.0010, "target_mode": "level"},
        {"id": "long_8h_level", "lookback_h": 8, "width": 48, "learning_rate": 0.0007, "target_mode": "level"},
        {"id": "short_4h_delta", "lookback_h": 4, "width": 32, "learning_rate": 0.0010, "target_mode": "delta"},
        {"id": "long_8h_delta", "lookback_h": 8, "width": 48, "learning_rate": 0.0007, "target_mode": "delta"},
    ]


def sequence_arrays(samples: list[dict[str, Any]], lookback: int) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray([row["sequence"][-lookback:] for row in samples], dtype=np.float32)
    y = np.asarray([row["target"] for row in samples], dtype=np.float32)
    return x, y


def scale_sequence(train_x: np.ndarray, other_x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    flat = train_x.reshape(-1, train_x.shape[-1])
    mean = flat.mean(axis=0)
    std = flat.std(axis=0)
    std[std < 1e-6] = 1.0
    return (train_x - mean) / std, (other_x - mean) / std, mean, std


def predict_torch(model, x: np.ndarray, y_mean: float, y_std: float, batch_size: int) -> np.ndarray:
    model.eval()
    tensor = torch.as_tensor(x, dtype=torch.float32)
    loader = DataLoader(TensorDataset(tensor), batch_size=batch_size, shuffle=False)
    output = []
    with torch.no_grad():
        for (xb,) in loader:
            pred = model(xb).cpu().numpy()
            output.append(pred)
    scaled = np.concatenate(output) if output else np.asarray([], dtype=float)
    return scaled * y_std + y_mean


def fit_temporal_profile(
    name: str,
    profile: dict[str, Any],
    train: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    test: list[dict[str, Any]],
    feature_count: int,
    temporal_cfg: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    if torch is None:
        raise RuntimeError(f"PyTorch indisponível: {TORCH_IMPORT_ERROR}")
    set_seed(seed)
    lookback = int(profile["lookback_h"])
    batch_size = int(temporal_cfg.get("batch_size", 64))
    epochs = int(temporal_cfg.get("epochs", 16))
    patience = int(temporal_cfg.get("patience", 3))
    weight_decay = float(temporal_cfg.get("weight_decay", 1e-4))
    target_mode = str(profile.get("target_mode", "level"))
    train_x, train_y_abs = sequence_arrays(train, lookback)
    val_x, val_y_abs = sequence_arrays(validation, lookback)
    test_x, _ = sequence_arrays(test, lookback)
    train_current = np.asarray([row["current"] for row in train], dtype=np.float32)
    val_current = np.asarray([row["current"] for row in validation], dtype=np.float32)
    test_current = np.asarray([row["current"] for row in test], dtype=np.float32)

    train_x, val_x, x_mean, x_std = scale_sequence(train_x, val_x)
    test_x = (test_x - x_mean) / x_std
    if target_mode == "delta":
        train_y_model = train_y_abs - train_current
    elif target_mode == "level":
        train_y_model = train_y_abs
    else:
        raise RuntimeError(f"target_mode inválido: {target_mode}")
    y_mean = float(train_y_model.mean())
    y_std = float(train_y_model.std())
    if y_std < 1e-6:
        y_std = 1.0
    train_y_scaled = (train_y_model - y_mean) / y_std

    model = build_temporal_model(name, feature_count, profile)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=float(profile.get("learning_rate", 0.001)), weight_decay=weight_decay
    )
    loss_name = str(profile.get("loss", "huber" if target_mode == "delta" else "mse")).lower()
    if loss_name == "huber":
        loss_fn = nn.HuberLoss(delta=float(profile.get("huber_delta", 1.0)))
    elif loss_name == "mse":
        loss_fn = nn.MSELoss()
    else:
        raise RuntimeError(f"loss inválida: {loss_name}")
    ds = TensorDataset(
        torch.as_tensor(train_x, dtype=torch.float32),
        torch.as_tensor(train_y_scaled, dtype=torch.float32),
    )
    loader = DataLoader(ds, batch_size=batch_size, shuffle=True)
    best_state = None
    best_val_mae = float("inf")
    best_epoch = 0
    stale = 0
    history = []
    for epoch in range(1, epochs + 1):
        model.train()
        losses = []
        for xb, yb in loader:
            optimizer.zero_grad(set_to_none=True)
            pred = model(xb)
            loss = loss_fn(pred, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=2.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        val_model_pred = predict_torch(model, val_x, y_mean, y_std, batch_size)
        val_pred = val_model_pred + val_current if target_mode == "delta" else val_model_pred
        val_mae = float(np.mean(np.abs(val_pred - val_y_abs)))
        history.append({"epoch": epoch, "train_mse_scaled": float(np.mean(losses)), "validation_mae_cm": val_mae})
        if val_mae + 1e-6 < best_val_mae:
            best_val_mae = val_mae
            best_epoch = epoch
            best_state = deepcopy(model.state_dict())
            stale = 0
        else:
            stale += 1
            if stale >= patience:
                break
    if best_state is None:
        raise RuntimeError(f"{name}/{profile['id']}: nenhum estado de validação")
    model.load_state_dict(best_state)
    val_model_pred = predict_torch(model, val_x, y_mean, y_std, batch_size)
    test_model_pred = predict_torch(model, test_x, y_mean, y_std, batch_size)
    val_pred = val_model_pred + val_current if target_mode == "delta" else val_model_pred
    test_pred = test_model_pred + test_current if target_mode == "delta" else test_model_pred
    validation_metric = phase1.metric(validation, val_pred)
    selection_score = (
        validation_metric["mae_cm"]
        + 0.25 * validation_metric["peak_abs_error_cm"]
        + 2.0 * validation_metric["peak_lag_abs_h"]
    )
    return {
        "profile": dict(profile),
        "target_mode": target_mode,
        "loss": loss_name,
        "best_epoch": best_epoch,
        "epochs_run": len(history),
        "parameter_count": int(sum(p.numel() for p in model.parameters())),
        "validation_metric": validation_metric,
        "validation_selection_score": float(selection_score),
        "test_pred": test_pred,
        "history_tail": history[-4:],
    }


def family_for(name: str) -> tuple[str, str]:
    if name == "Persistência":
        return "baseline", "baseline"
    if name in ("Ridge", "Elastic Net"):
        return "linear", "static_current_row"
    if name == "SVR":
        return "kernel", "static_current_row"
    if name == "MLP":
        return "neural tabular", "static_current_row"
    if name in ("Random Forest", "Extra Trees"):
        return "árvores", "static_current_row"
    if name in ("HistGradientBoosting", "XGBoost"):
        return "boosting", "static_current_row"
    return "neural temporal", "temporal_sequence"


def aggregate_leaderboard(per_fold: list[dict[str, Any]], folds_total: int, config: dict[str, Any]) -> list[dict[str, Any]]:
    names = sorted({row["model"] for row in per_fold})
    leaderboard = []
    for name in names:
        group = [row for row in per_fold if row["model"] == name]
        family, representation = family_for(name)
        nse_values = [row["nse"] for row in group if row.get("nse") is not None and math.isfinite(row["nse"])]
        profile_ids = [row.get("selected_profile") for row in group if row.get("selected_profile")]
        counts = Counter(profile_ids)
        dominant_profile = counts.most_common(1)[0][0] if counts else None
        leaderboard.append({
            "model": name,
            "family": family,
            "representation": representation,
            "fold_count": len(group),
            "median_mae_cm": float(np.median([row["mae_cm"] for row in group])),
            "mean_mae_cm": float(np.mean([row["mae_cm"] for row in group])),
            "worst_fold_mae_cm": float(np.max([row["mae_cm"] for row in group])),
            "median_rmse_cm": float(np.median([row["rmse_cm"] for row in group])),
            "median_nse": float(np.median(nse_values)) if nse_values else None,
            "median_abs_bias_cm": float(np.median([abs(row["bias_cm"]) for row in group])),
            "median_peak_abs_error_cm": float(np.median([row["peak_abs_error_cm"] for row in group])),
            "worst_peak_abs_error_cm": float(np.max([row["peak_abs_error_cm"] for row in group])),
            "median_peak_lag_abs_h": float(np.median([row["peak_lag_abs_h"] for row in group])),
            "worst_peak_lag_abs_h": float(np.max([row["peak_lag_abs_h"] for row in group])),
            "selected_profile_counts": dict(counts),
            "dominant_profile": dominant_profile,
        })
    leaderboard.sort(key=lambda row: (
        row["median_mae_cm"], row["median_rmse_cm"], row["worst_fold_mae_cm"],
        row["median_peak_abs_error_cm"], row["median_peak_lag_abs_h"],
    ))
    persistence = next((row for row in leaderboard if row["model"] == "Persistência"), None)
    max_lag = float(config.get("max_peak_lag_h", max(2, int(config["horizon_hours"]) * 2)))
    min_folds = int(config.get("min_folds", 3))
    for rank, row in enumerate(leaderboard, 1):
        row["rank"] = rank
        row["beats_persistence"] = bool(
            persistence and row["model"] != "Persistência" and row["median_mae_cm"] < persistence["median_mae_cm"]
        )
        row["beats_persistence_worst_fold"] = bool(
            persistence and row["model"] != "Persistência" and row["worst_fold_mae_cm"] < persistence["worst_fold_mae_cm"]
        )
        row["complete_fold_coverage"] = row["fold_count"] == folds_total
        row["shadow_eligible"] = bool(
            row["beats_persistence"]
            and row["beats_persistence_worst_fold"]
            and row["complete_fold_coverage"]
            and row["fold_count"] >= min_folds
            and (row["median_nse"] is not None and row["median_nse"] > 0)
            and row["worst_peak_lag_abs_h"] <= max_lag
        )
    return leaderboard


def run_experiment(config: dict[str, Any]) -> dict[str, Any]:
    raw_rows, feature_names, audit = phase1.load_rows(config)
    if int(audit.get("duplicate_event_timestamp_rows", 0)) != 0:
        raise RuntimeError("duplicidades evento-horário bloqueiam o treinamento temporal")
    temporal_cfg = config.get("temporal", {})
    if not temporal_cfg.get("enabled", True):
        raise RuntimeError("fase temporal desativada no contrato")
    if torch is None:
        raise RuntimeError(f"PyTorch indisponível: {TORCH_IMPORT_ERROR}")
    samples, sequence_audit = build_sequence_samples(raw_rows, config)
    folds = phase1.build_folds(samples, config)
    if len(folds) < int(config.get("min_folds", 3)):
        raise RuntimeError(f"dobras causais insuficientes após janela comum: {len(folds)}")

    seed = int(config.get("seed", 20261002))
    set_seed(seed)
    static_models = phase1.models(seed)
    profiles = temporal_profiles(config)
    max_lookback = int(sequence_audit["max_lookback_h"])
    if any(int(profile["lookback_h"]) > max_lookback for profile in profiles):
        raise RuntimeError("perfil temporal excede a janela comum")

    per_fold: list[dict[str, Any]] = []
    temporal_selection: list[dict[str, Any]] = []
    training_failures: list[dict[str, Any]] = []

    for fold_index, fold in enumerate(folds):
        train = fold["train_rows"]
        validation = fold["validation_rows"]
        test = fold["test_rows"]
        x_train = np.asarray([row["features"] for row in train], dtype=float)
        y_train = np.asarray([row["target"] for row in train], dtype=float)
        x_test = np.asarray([row["features"] for row in test], dtype=float)

        persistence_pred = np.asarray([row["current"] for row in test], dtype=float)
        persistence_metric = phase1.metric(test, persistence_pred)
        per_fold.append({
            "model": "Persistência", "family": "baseline", "representation": "baseline",
            "backend": "baseline", "fold": fold["id"], **persistence_metric,
        })

        for name, base in static_models.items():
            estimator = clone(base)
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    estimator.fit(x_train, y_train)
                pred = estimator.predict(x_test)
                m = phase1.metric(test, pred)
                family, representation = family_for(name)
                per_fold.append({
                    "model": name, "family": family, "representation": representation,
                    "backend": type(estimator).__name__, "fold": fold["id"],
                    "warning_count": len(caught), **m,
                })
            except Exception as exc:
                training_failures.append({"fold": fold["id"], "model": name, "stage": "static", "error": repr(exc)})

        for model_offset, name in enumerate(TEMPORAL_NAMES):
            trials = []
            for profile_offset, profile in enumerate(profiles):
                try:
                    trial = fit_temporal_profile(
                        name=name,
                        profile=profile,
                        train=train,
                        validation=validation,
                        test=test,
                        feature_count=len(feature_names),
                        temporal_cfg=temporal_cfg,
                        seed=seed + fold_index * 1009 + model_offset * 101 + profile_offset,
                    )
                    trials.append(trial)
                except Exception as exc:
                    training_failures.append({
                        "fold": fold["id"], "model": name, "profile": profile.get("id"),
                        "stage": "temporal_profile", "error": repr(exc),
                    })
            if not trials:
                continue
            best = min(trials, key=lambda item: item["validation_selection_score"])
            m = phase1.metric(test, best["test_pred"])
            per_fold.append({
                "model": name,
                "family": "neural temporal",
                "representation": "temporal_sequence",
                "backend": "pytorch-cpu",
                "fold": fold["id"],
                "selected_profile": best["profile"]["id"],
                "selected_lookback_h": int(best["profile"]["lookback_h"]),
                "selected_width": int(best["profile"]["width"]),
                "selected_target_mode": str(best["profile"].get("target_mode", "level")),
                "selected_loss": str(best.get("loss", best["profile"].get("loss", "mse"))),
                "best_epoch": int(best["best_epoch"]),
                "parameter_count": int(best["parameter_count"]),
                "validation_selection_score": float(best["validation_selection_score"]),
                **m,
            })
            temporal_selection.append({
                "fold": fold["id"],
                "model": name,
                "selected_profile": best["profile"],
                "best_epoch": best["best_epoch"],
                "parameter_count": best["parameter_count"],
                "validation_metric": best["validation_metric"],
                "validation_selection_score": best["validation_selection_score"],
                "all_profiles": [
                    {
                        "profile": trial["profile"],
                        "best_epoch": trial["best_epoch"],
                        "target_mode": trial.get("target_mode"),
                        "loss": trial.get("loss"),
                        "validation_metric": trial["validation_metric"],
                        "validation_selection_score": trial["validation_selection_score"],
                    }
                    for trial in trials
                ],
            })

    leaderboard = aggregate_leaderboard(per_fold, len(folds), config)
    fold_manifest = [{
        "fold_id": fold["id"],
        "train_events": fold["train_events"],
        "validation_event": fold["validation_event"],
        "test_event": fold["test_event"],
        "train_rows": len(fold["train_rows"]),
        "validation_rows": len(fold["validation_rows"]),
        "test_rows": len(fold["test_rows"]),
    } for fold in folds]

    return {
        "schema_version": 2,
        "artifact_id": "previne_ai_lab_auto_training_v2",
        "engine_version": "2.1-temporal-residual-robust",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "experiment_id": config["id"],
        "label": config["label"],
        "station": config.get("station"),
        "target": config.get("target_name", config["target_column"]),
        "horizon_hours": config["horizon_hours"],
        "status": "completed_research_training_v2",
        "research_only": True,
        "official_alert": False,
        "promotion_allowed": False,
        "protocol": {
            "same_common_target_rows": True,
            "common_sequence_window_h": max_lookback,
            "static_representation": "somente vetor do horário-alvo de origem, nas mesmas linhas elegíveis da coorte temporal",
            "temporal_representation": "sequência histórica encerrando no horário de emissão",
            "temporal_profile_selection": "somente evento de validação; evento de teste não participa da escolha",
            "temporal_target_search": "nível absoluto e delta de nível (nível futuro - nível atual) competem como perfis; delta é reconstruído para nível antes das métricas",
            "temporal_profile_score": "MAE_validacao + 0.25*erro_pico_validacao + 2*atraso_pico_validacao",
            "causal_event_folds": True,
            "future_columns_in_features": False,
            "baseline_required": "Persistência",
            "promotion": "nunca automática; gate libera apenas candidato de pesquisa para próxima etapa de sombra",
            "static_models": list(static_models.keys()) + ["Persistência"],
            "temporal_models": list(TEMPORAL_NAMES),
            "temporal_profiles": profiles,
            "gate_requires": [
                "MAE mediano menor que persistência",
                "pior MAE de dobra menor que persistência",
                "cobertura de todas as dobras",
                "NSE mediano positivo",
                "pior atraso do pico dentro do limite do contrato",
            ],
        },
        "data_audit": audit,
        "sequence_audit": sequence_audit,
        "folds": fold_manifest,
        "leaderboard": leaderboard,
        "shadow_candidates": [row for row in leaderboard if row["shadow_eligible"]],
        "shadow_queue_top3": [row for row in leaderboard if row["shadow_eligible"]][:3],
        "temporal_selection": temporal_selection,
        "training_failures": training_failures,
        "fold_metrics": per_fold,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default=None)
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    experiments = registry["experiments"]
    config = next((item for item in experiments if item["id"] == args.experiment), None) if args.experiment else next((item for item in experiments if item.get("enabled")), None)
    if config is None:
        raise SystemExit("experimento não encontrado")
    result = run_experiment(config)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = [
        "rank", "model", "family", "representation", "dominant_profile", "fold_count",
        "median_mae_cm", "mean_mae_cm", "worst_fold_mae_cm", "median_rmse_cm", "median_nse",
        "median_abs_bias_cm", "median_peak_abs_error_cm", "worst_peak_abs_error_cm",
        "median_peak_lag_abs_h", "worst_peak_lag_abs_h", "beats_persistence",
        "beats_persistence_worst_fold", "complete_fold_coverage", "shadow_eligible",
    ]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in result["leaderboard"]:
            writer.writerow({key: row.get(key) for key in fields})
    print(json.dumps({
        "experiment": result["experiment_id"],
        "engine_version": result["engine_version"],
        "models": len(result["leaderboard"]),
        "folds": len(result["folds"]),
        "temporal_models": list(TEMPORAL_NAMES),
        "shadow_candidates": [row["model"] for row in result["shadow_candidates"]],
        "training_failures": len(result["training_failures"]),
        "output": str(OUT_JSON.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
