#!/usr/bin/env python3
"""Pure-NumPy inference for PREVINE AI Lab TCN shadow packages.

This module intentionally has no PyTorch dependency. It loads the audited NPZ
export created by scripts/ai_lab_build_shadow_package.py and reproduces the
small TCN forward pass for research shadow inference.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(root: Path, relative: str = "assets/data/ai_lab/shadow/shadow_manifest_latest.json") -> dict[str, Any]:
    path = root / relative
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("research_only") or not data.get("shadow_only"):
        raise RuntimeError("AI Lab package is not explicitly research shadow-only")
    if data.get("alerting_enabled") is not False:
        raise RuntimeError("AI Lab shadow package must keep alerting disabled")
    return data


def select_package(manifest: dict[str, Any], profile_id: str) -> dict[str, Any]:
    for item in manifest.get("packages", []):
        if item.get("profile", {}).get("id") == profile_id:
            return item
    raise KeyError(f"shadow profile not found: {profile_id}")


def _load_arrays(root: Path, package: dict[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    info = package["weights"]
    path = root / info["path"]
    actual = sha256(path)
    expected = str(info["sha256"]).lower()
    if actual.lower() != expected:
        raise RuntimeError(f"shadow weights hash mismatch: {path}")
    archive = np.load(path, allow_pickle=False)
    state_map = info.get("state_key_map", {})
    state = {state_name: np.asarray(archive[stored]) for stored, state_name in state_map.items()}
    norm = {
        "x_mean": np.asarray(archive["normalization__x_mean"], dtype=float),
        "x_std": np.asarray(archive["normalization__x_std"], dtype=float),
        "y_mean": np.asarray(archive["normalization__y_mean"], dtype=float),
        "y_std": np.asarray(archive["normalization__y_std"], dtype=float),
    }
    return state, norm


def _conv1d(x: np.ndarray, weight: np.ndarray, bias: np.ndarray, padding: int, dilation: int) -> np.ndarray:
    # x: channels_in × length; weight: channels_out × channels_in × kernel
    cin, length = x.shape
    cout, win, kernel = weight.shape
    if cin != win:
        raise ValueError(f"conv channel mismatch: {cin} != {win}")
    out = np.empty((cout, length), dtype=float)
    for t in range(length):
        acc = np.asarray(bias, dtype=float).copy()
        for k in range(kernel):
            source = t - padding + k * dilation
            if 0 <= source < length:
                acc += weight[:, :, k] @ x[:, source]
        out[:, t] = acc
    return out


def _layer_norm(vector: np.ndarray, weight: np.ndarray, bias: np.ndarray, eps: float = 1e-5) -> np.ndarray:
    mean = float(np.mean(vector))
    var = float(np.mean((vector - mean) ** 2))
    return ((vector - mean) / np.sqrt(var + eps)) * weight + bias


def forward_tcn_scaled(sequence_scaled: np.ndarray, state: dict[str, np.ndarray]) -> float:
    x = np.asarray(sequence_scaled, dtype=float)
    if x.ndim != 2:
        raise ValueError("sequence must be lookback × features")
    z = x.T
    z = _conv1d(z, state["net.0.weight"], state["net.0.bias"], padding=1, dilation=1)
    z = np.maximum(z, 0.0)
    z = _conv1d(z, state["net.2.weight"], state["net.2.bias"], padding=2, dilation=2)
    z = np.maximum(z, 0.0)
    z = _conv1d(z, state["net.4.weight"], state["net.4.bias"], padding=4, dilation=4)
    z = np.maximum(z, 0.0)
    last = z[:, -1]
    last = _layer_norm(last, state["head.0.weight"], state["head.0.bias"])
    value = state["head.1.weight"] @ last + state["head.1.bias"]
    return float(np.asarray(value).reshape(-1)[0])


def predict_package(root: Path, package: dict[str, Any], sequence: list[list[float]] | np.ndarray, current_level_cm: float) -> dict[str, Any]:
    profile = package["profile"]
    expected_lookback = int(profile["lookback_h"])
    x = np.asarray(sequence, dtype=float)
    if x.ndim != 2 or x.shape[0] != expected_lookback:
        raise ValueError(f"expected sequence {expected_lookback}×features, found {x.shape}")
    state, norm = _load_arrays(root, package)
    if x.shape[1] != norm["x_mean"].shape[0]:
        raise ValueError("feature count differs from shadow package normalization")
    scaled = (x - norm["x_mean"]) / norm["x_std"]
    pred_scaled = forward_tcn_scaled(scaled, state)
    target_value = pred_scaled * float(norm["y_std"][0]) + float(norm["y_mean"][0])
    mode = str(profile.get("target_mode", "level"))
    if mode == "delta":
        delta = float(target_value)
        level = float(current_level_cm) + delta
    elif mode == "level":
        level = float(target_value)
        delta = level - float(current_level_cm)
    else:
        raise RuntimeError(f"unsupported target mode: {mode}")
    return {
        "profile_id": profile.get("id"),
        "lookback_h": expected_lookback,
        "target_mode": mode,
        "level_forecast_cm": level,
        "delta_forecast_cm": delta,
        "weights_sha256": package["weights"]["sha256"],
    }
