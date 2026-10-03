#!/usr/bin/env python3
"""Build reproducible PREVINE AI Lab shadow packages after controlled validation.

This step runs only after a temporal family has passed the research shadow gate.
It refits selected profile variants on the full historical common cohort and
serializes weights + normalization. These files are research shadow artifacts:
they do not change live models, alerts, thresholds, or public decisions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

import ai_lab_auto_train as phase1
import ai_lab_temporal_train as temporal

if temporal.torch is None:
    raise RuntimeError(f"PyTorch unavailable: {temporal.TORCH_IMPORT_ERROR}")

torch = temporal.torch
nn = temporal.nn
DataLoader = temporal.DataLoader
TensorDataset = temporal.TensorDataset

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "assets" / "data" / "ai_lab" / "experiments.json"
VALIDATION = ROOT / "assets" / "data" / "ai_lab" / "auto_training_v2_latest.json"
OUT_DIR = ROOT / "assets" / "data" / "ai_lab" / "shadow"
MANIFEST = OUT_DIR / "shadow_manifest_latest.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def profile_by_id(config: dict[str, Any], profile_id: str) -> dict[str, Any]:
    for profile in config.get("temporal", {}).get("profiles", []):
        if profile.get("id") == profile_id:
            return dict(profile)
    raise RuntimeError(f"profile not found in experiment contract: {profile_id}")


def final_epochs(selections: list[dict[str, Any]], profile_id: str) -> tuple[int, list[int]]:
    values = [
        int(item["best_epoch"])
        for item in selections
        if item.get("selected_profile", {}).get("id") == profile_id and item.get("best_epoch")
    ]
    if not values:
        values = [int(item["best_epoch"]) for item in selections if item.get("best_epoch")]
    if not values:
        raise RuntimeError(f"no validated epoch history for {profile_id}")
    # Conservative deterministic refit rule: median selected early-stopping epoch.
    epochs = max(3, int(math.floor(float(np.median(values)) + 0.5)))
    return epochs, values


def train_final_profile(
    model_name: str,
    profile: dict[str, Any],
    samples: list[dict[str, Any]],
    feature_count: int,
    temporal_cfg: dict[str, Any],
    seed: int,
    epochs: int,
) -> tuple[Any, dict[str, Any]]:
    temporal.set_seed(seed)
    lookback = int(profile["lookback_h"])
    batch_size = int(temporal_cfg.get("batch_size", 64))
    weight_decay = float(temporal_cfg.get("weight_decay", 1e-4))
    target_mode = str(profile.get("target_mode", "level"))

    x, y_abs = temporal.sequence_arrays(samples, lookback)
    current = np.asarray([row["current"] for row in samples], dtype=np.float32)
    flat = x.reshape(-1, x.shape[-1])
    x_mean = flat.mean(axis=0)
    x_std = flat.std(axis=0)
    x_std[x_std < 1e-6] = 1.0
    x_scaled = (x - x_mean) / x_std

    if target_mode == "delta":
        y_model = y_abs - current
    elif target_mode == "level":
        y_model = y_abs
    else:
        raise RuntimeError(f"invalid target_mode: {target_mode}")

    y_mean = float(y_model.mean())
    y_std = float(y_model.std())
    if y_std < 1e-6:
        y_std = 1.0
    y_scaled = (y_model - y_mean) / y_std

    model = temporal.build_temporal_model(model_name, feature_count, profile)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(profile.get("learning_rate", 0.001)),
        weight_decay=weight_decay,
    )
    loss_name = str(profile.get("loss", "huber" if target_mode == "delta" else "mse")).lower()
    if loss_name == "huber":
        loss_fn = nn.HuberLoss(delta=float(profile.get("huber_delta", 1.0)))
    elif loss_name == "mse":
        loss_fn = nn.MSELoss()
    else:
        raise RuntimeError(f"invalid loss: {loss_name}")

    dataset = TensorDataset(
        torch.as_tensor(x_scaled, dtype=torch.float32),
        torch.as_tensor(y_scaled, dtype=torch.float32),
    )
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
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
        history.append({"epoch": epoch, "train_loss_scaled": float(np.mean(losses))})

    audit = {
        "rows": len(samples),
        "lookback_h": lookback,
        "feature_count": feature_count,
        "target_mode": target_mode,
        "loss": loss_name,
        "epochs": epochs,
        "learning_rate": float(profile.get("learning_rate", 0.001)),
        "width": int(profile["width"]),
        "parameter_count": int(sum(parameter.numel() for parameter in model.parameters())),
        "x_mean": x_mean,
        "x_std": x_std,
        "y_mean": y_mean,
        "y_std": y_std,
        "history_tail": history[-4:],
    }
    return model, audit


def save_npz(model: Any, audit: dict[str, Any], path: Path) -> dict[str, str]:
    arrays: dict[str, Any] = {
        "normalization__x_mean": np.asarray(audit["x_mean"], dtype=np.float32),
        "normalization__x_std": np.asarray(audit["x_std"], dtype=np.float32),
        "normalization__y_mean": np.asarray([audit["y_mean"]], dtype=np.float32),
        "normalization__y_std": np.asarray([audit["y_std"]], dtype=np.float32),
    }
    key_map: dict[str, str] = {}
    for index, (state_name, tensor) in enumerate(model.state_dict().items()):
        stored = f"state__{index:03d}"
        arrays[stored] = tensor.detach().cpu().numpy()
        key_map[stored] = state_name
    np.savez_compressed(path, **arrays)
    return key_map


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default="stz_2h_auto_v1")
    args = parser.parse_args()

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    config = next((item for item in registry["experiments"] if item["id"] == args.experiment), None)
    if config is None:
        raise SystemExit("experiment not found")
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    if validation.get("experiment_id") != config["id"]:
        raise RuntimeError("validation artifact belongs to another experiment")
    if validation.get("engine_version") != "2.1-temporal-residual-robust":
        raise RuntimeError("shadow packaging requires the robust temporal engine")

    eligible_temporal = [
        row for row in validation.get("leaderboard", [])
        if row.get("representation") == "temporal_sequence" and row.get("shadow_eligible")
    ]
    if not eligible_temporal:
        raise RuntimeError("no temporal model passed the shadow gate")
    candidate = eligible_temporal[0]
    model_name = str(candidate["model"])
    selections = [
        item for item in validation.get("temporal_selection", [])
        if item.get("model") == model_name
    ]
    if not selections:
        raise RuntimeError("missing temporal selection audit")

    dominant_id = candidate.get("dominant_profile")
    latest_id = selections[-1].get("selected_profile", {}).get("id")
    profile_ids = []
    for value in (latest_id, dominant_id):
        if value and value not in profile_ids:
            profile_ids.append(value)

    raw_rows, feature_names, audit = phase1.load_rows(config)
    samples, sequence_audit = temporal.build_sequence_samples(raw_rows, config)
    if not samples:
        raise RuntimeError("empty common temporal cohort")
    source_end = max(row["timestamp"] for row in samples).isoformat(timespec="minutes")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    package_rows = []
    base_seed = int(config.get("seed", 20261002)) + 50000
    for index, profile_id in enumerate(profile_ids):
        profile = profile_by_id(config, profile_id)
        epochs, epoch_history = final_epochs(selections, profile_id)
        model, fit = train_final_profile(
            model_name=model_name,
            profile=profile,
            samples=samples,
            feature_count=len(feature_names),
            temporal_cfg=config.get("temporal", {}),
            seed=base_seed + index,
            epochs=epochs,
        )
        safe_profile = profile_id.replace("/", "_")
        weight_path = OUT_DIR / f"{model_name.lower().replace(' ', '_')}_{safe_profile}.npz"
        key_map = save_npz(model, fit, weight_path)
        role = "latest_causal_profile" if profile_id == latest_id else "dominant_cross_fold_profile"
        package_rows.append({
            "role": role,
            "model": model_name,
            "profile": profile,
            "final_fit": {
                "research_only_refit": True,
                "rows": fit["rows"],
                "trained_through": source_end,
                "epochs": fit["epochs"],
                "epoch_rule": "rounded median of early-stopping epochs from causal folds where this profile was selected",
                "selected_epoch_history": epoch_history,
                "parameter_count": fit["parameter_count"],
                "loss": fit["loss"],
                "normalization": "stored inside NPZ; fit on final historical refit cohort",
            },
            "weights": {
                "path": weight_path.relative_to(ROOT).as_posix(),
                "sha256": file_sha256(weight_path),
                "format": "numpy savez compressed; state_dict tensors + normalization",
                "state_key_map": key_map,
            },
        })

    manifest = {
        "schema_version": 1,
        "artifact_id": "previne_ai_lab_shadow_package",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "experiment_id": config["id"],
        "station": config.get("station"),
        "horizon_hours": config["horizon_hours"],
        "candidate_family": model_name,
        "status": "research_shadow_package_ready",
        "research_only": True,
        "shadow_only": True,
        "live_inference_enabled": False,
        "alerting_enabled": False,
        "automatic_promotion_allowed": False,
        "validation_source": VALIDATION.relative_to(ROOT).as_posix(),
        "validation_generated_at_utc": validation.get("generated_at_utc"),
        "validation_engine_version": validation.get("engine_version"),
        "validation_evidence": candidate,
        "data_contract": {
            "source_path": audit["source_path"],
            "source_sha256": audit["source_sha256"],
            "feature_names": feature_names,
            "feature_count": len(feature_names),
            "common_sequence_audit": sequence_audit,
        },
        "selection": {
            "latest_causal_fold": selections[-1].get("fold"),
            "latest_causal_profile": latest_id,
            "dominant_cross_fold_profile": dominant_id,
            "dominant_profile_counts": candidate.get("selected_profile_counts", {}),
            "packaging_policy": "package latest causal profile and dominant cross-fold profile when they differ",
        },
        "packages": package_rows,
        "safety": {
            "does_not_modify_live_rna": True,
            "does_not_emit_alerts": True,
            "does_not_change_thresholds": True,
            "next_required_step": "audited live shadow inference using exactly the same feature contract",
        },
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "manifest": MANIFEST.relative_to(ROOT).as_posix(),
        "candidate": model_name,
        "profiles": profile_ids,
        "packages": [item["weights"]["path"] for item in package_rows],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
