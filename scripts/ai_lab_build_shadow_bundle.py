#!/usr/bin/env python3
"""Build research-only shadow deployment bundles from the latest AI Lab gate.

This stage refits already-selected candidates on all eligible historical rows.
It does not recompute validation metrics and never promotes a model to official
operation. Binary weights are intended for GitHub Actions artifacts; only the
small manifest is committed to the public repository.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

import ai_lab_auto_train as phase1
import ai_lab_temporal_train as temporal


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "assets" / "data" / "ai_lab" / "experiments.json"
RESULT = ROOT / "assets" / "data" / "ai_lab" / "auto_training_v2_latest.json"
MANIFEST = ROOT / "assets" / "data" / "ai_lab" / "shadow_bundle_manifest.json"
OUTDIR = ROOT / "artifacts" / "ai_lab_shadow"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_experiment(registry: dict, experiment_id: str) -> dict:
    for item in registry.get("experiments", []):
        if item.get("id") == experiment_id:
            return item
    raise RuntimeError(f"experimento ausente: {experiment_id}")


def metric_snapshot(row: dict | None) -> dict | None:
    if not row:
        return None
    keys = [
        "rank", "model", "family", "representation", "dominant_profile", "fold_count",
        "median_mae_cm", "mean_mae_cm", "worst_fold_mae_cm", "median_rmse_cm",
        "median_nse", "median_abs_bias_cm", "median_peak_abs_error_cm",
        "worst_peak_abs_error_cm", "median_peak_lag_abs_h", "worst_peak_lag_abs_h",
        "shadow_eligible",
    ]
    return {key: row.get(key) for key in keys}


def profile_by_id(config: dict, profile_id: str) -> dict:
    for profile in config.get("temporal", {}).get("profiles", []):
        if profile.get("id") == profile_id:
            return dict(profile)
    raise RuntimeError(f"perfil temporal ausente no contrato: {profile_id}")


def selected_epochs(result: dict, model_name: str, profile_id: str, fallback: int) -> int:
    epochs = []
    for item in result.get("temporal_selection", []):
        profile = item.get("selected_profile") or {}
        if item.get("model") == model_name and profile.get("id") == profile_id:
            value = item.get("best_epoch")
            if value is not None:
                epochs.append(int(value))
    if not epochs:
        return int(fallback)
    return max(1, int(round(float(np.median(epochs)))))


def refit_temporal(config: dict, result: dict, samples: list[dict], feature_names: list[str], row: dict) -> dict:
    model_name = str(row["model"])
    profile_id = str(row["dominant_profile"])
    profile = profile_by_id(config, profile_id)
    lookback = int(profile["lookback_h"])
    x, y_abs = temporal.sequence_arrays(samples, lookback)
    current = np.asarray([sample["current"] for sample in samples], dtype=np.float32)

    flat = x.reshape(-1, x.shape[-1])
    x_mean = flat.mean(axis=0)
    x_std = flat.std(axis=0)
    x_std[x_std < 1e-6] = 1.0
    x_scaled = (x - x_mean) / x_std

    target_mode = str(profile.get("target_mode", "level"))
    if target_mode == "delta":
        y_model = y_abs - current
    elif target_mode == "level":
        y_model = y_abs
    else:
        raise RuntimeError(f"target_mode inválido: {target_mode}")
    y_mean = float(y_model.mean())
    y_std = float(y_model.std())
    if y_std < 1e-6:
        y_std = 1.0
    y_scaled = (y_model - y_mean) / y_std

    seed = int(config.get("seed", 20261002)) + 7001
    temporal.set_seed(seed)
    model = temporal.build_temporal_model(model_name, len(feature_names), profile)
    loss_name = str(profile.get("loss", "huber" if target_mode == "delta" else "mse")).lower()
    if loss_name == "huber":
        loss_fn = torch.nn.HuberLoss(delta=float(profile.get("huber_delta", 1.0)))
    else:
        loss_fn = torch.nn.MSELoss()
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(profile.get("learning_rate", 0.001)),
        weight_decay=float(config.get("temporal", {}).get("weight_decay", 1e-4)),
    )
    batch_size = int(config.get("temporal", {}).get("batch_size", 64))
    epochs = selected_epochs(
        result, model_name, profile_id, int(config.get("temporal", {}).get("epochs", 16))
    )
    dataset = TensorDataset(
        torch.as_tensor(x_scaled, dtype=torch.float32),
        torch.as_tensor(y_scaled, dtype=torch.float32),
    )
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    history = []
    model.train()
    for epoch in range(1, epochs + 1):
        losses = []
        for xb, yb in loader:
            optimizer.zero_grad(set_to_none=True)
            pred = model(xb)
            loss = loss_fn(pred, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=2.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        history.append(float(np.mean(losses)))

    OUTDIR.mkdir(parents=True, exist_ok=True)
    path = OUTDIR / f"{config['id']}__{model_name.lower().replace(' ','_')}__shadow.pt"
    payload = {
        "bundle_contract_version": 1,
        "research_only": True,
        "official_alert": False,
        "model_name": model_name,
        "profile": profile,
        "epochs_refit": epochs,
        "feature_names": feature_names,
        "current_level_column": config["current_level_column"],
        "target_column": config["target_column"],
        "target_mode": target_mode,
        "x_mean": torch.as_tensor(x_mean),
        "x_std": torch.as_tensor(x_std),
        "y_mean": y_mean,
        "y_std": y_std,
        "state_dict": model.state_dict(),
        "training_rows": len(samples),
        "source_sha256": result["data_audit"]["source_sha256"],
    }
    torch.save(payload, path)
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
        "model": model_name,
        "profile": profile,
        "epochs_refit": epochs,
        "training_rows": len(samples),
        "target_mode": target_mode,
        "loss": loss_name,
        "last_train_loss_scaled": history[-1] if history else None,
    }


def refit_static(config: dict, samples: list[dict], row: dict) -> dict:
    model_name = str(row["model"])
    candidates = phase1.models(int(config.get("seed", 20261002)))
    if model_name not in candidates:
        raise RuntimeError(f"modelo estático não empacotável: {model_name}")
    estimator = candidates[model_name]
    x = np.asarray([sample["features"] for sample in samples], dtype=float)
    y = np.asarray([sample["target"] for sample in samples], dtype=float)
    estimator.fit(x, y)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    path = OUTDIR / f"{config['id']}__{model_name.lower().replace(' ','_')}__shadow.joblib"
    joblib.dump({
        "bundle_contract_version": 1,
        "research_only": True,
        "official_alert": False,
        "model_name": model_name,
        "feature_names": result_feature_names,
        "current_level_column": config["current_level_column"],
        "target_column": config["target_column"],
        "estimator": estimator,
        "training_rows": len(samples),
    }, path)
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
        "model": model_name,
        "training_rows": len(samples),
    }


registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
result = json.loads(RESULT.read_text(encoding="utf-8"))
config = find_experiment(registry, result["experiment_id"])
rows, result_feature_names, audit = phase1.load_rows(config)
samples, sequence_audit = temporal.build_sequence_samples(rows, config)

leaderboard = result.get("leaderboard", [])
temporal_candidate = next(
    (row for row in leaderboard if row.get("representation") == "temporal_sequence" and row.get("shadow_eligible")),
    None,
)
static_candidate = next(
    (row for row in leaderboard if row.get("representation") == "static_current_row" and row.get("shadow_eligible")),
    None,
)
if temporal_candidate is None:
    raise RuntimeError("nenhuma rede temporal passou ao gate de sombra")
if static_candidate is None:
    raise RuntimeError("nenhum comparador estático passou ao gate de sombra")

temporal_bundle = refit_temporal(config, result, samples, result_feature_names, temporal_candidate)
static_bundle = refit_static(config, samples, static_candidate)

manifest = {
    "schema_version": 1,
    "artifact_id": "previne_ai_lab_shadow_bundle",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "experiment_id": result["experiment_id"],
    "station": result.get("station"),
    "horizon_hours": result.get("horizon_hours"),
    "research_only": True,
    "official_alert": False,
    "promotion_allowed": False,
    "purpose": "Pacote para inferência comparativa em sombra; não publica previsão oficial.",
    "source": {
        "path": audit["source_path"],
        "sha256": audit["source_sha256"],
        "training_result_sha256": file_sha256(RESULT),
        "eligible_sequence_rows": sequence_audit["eligible_sequence_rows"],
        "feature_count": len(result_feature_names),
        "feature_names": result_feature_names,
    },
    "temporal_candidate": {
        "metrics": metric_snapshot(temporal_candidate),
        "bundle": temporal_bundle,
    },
    "static_comparator": {
        "metrics": metric_snapshot(static_candidate),
        "bundle": static_bundle,
    },
    "next_gate": [
        "reproduzir inputs ao vivo na mesma ordem e unidade",
        "executar sem publicar alerta",
        "comparar erro somente quando o observado futuro estiver disponível",
        "acumular eventos independentes antes de qualquer promoção",
    ],
}
MANIFEST.parent.mkdir(parents=True, exist_ok=True)
MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({
    "temporal": temporal_candidate["model"],
    "static": static_candidate["model"],
    "temporal_profile": temporal_candidate.get("dominant_profile"),
    "manifest": str(MANIFEST.relative_to(ROOT)),
}, ensure_ascii=False))
