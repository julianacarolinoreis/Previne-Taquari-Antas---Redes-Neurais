#!/usr/bin/env python3
"""Cross-check NumPy shadow TCN inference against the audited PyTorch model."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import ai_lab_auto_train as phase1
import ai_lab_temporal_train as temporal

ROOT = Path(__file__).resolve().parents[1]

import sys
sys.path.insert(0, str(ROOT / "previne" / "robo"))
import ai_lab_shadow_tcn as shadow  # noqa: E402


def main() -> int:
    if temporal.torch is None:
        raise RuntimeError(f"PyTorch unavailable: {temporal.TORCH_IMPORT_ERROR}")
    torch = temporal.torch
    registry = json.loads((ROOT / "assets/data/ai_lab/experiments.json").read_text(encoding="utf-8"))
    config = next(item for item in registry["experiments"] if item["id"] == "stz_2h_auto_v1")
    manifest = shadow.load_manifest(ROOT)
    raw_rows, features, _ = phase1.load_rows(config)
    samples, _ = temporal.build_sequence_samples(raw_rows, config)
    probes = samples[-8:]
    if len(probes) < 3:
        raise RuntimeError("insufficient probe rows")

    comparisons = []
    for package in manifest["packages"]:
        profile = package["profile"]
        model = temporal.build_temporal_model(manifest["candidate_family"], len(features), profile)
        state_np, norm = shadow._load_arrays(ROOT, package)
        state_torch = {name: torch.as_tensor(value, dtype=torch.float32) for name, value in state_np.items()}
        model.load_state_dict(state_torch)
        model.eval()
        lookback = int(profile["lookback_h"])
        for sample in probes:
            sequence = np.asarray(sample["sequence"][-lookback:], dtype=np.float32)
            numpy_result = shadow.predict_package(ROOT, package, sequence, sample["current"])
            scaled = (sequence - norm["x_mean"]) / norm["x_std"]
            with torch.no_grad():
                pred_scaled = float(model(torch.as_tensor(scaled[None, :, :], dtype=torch.float32)).cpu().numpy()[0])
            target_value = pred_scaled * float(norm["y_std"][0]) + float(norm["y_mean"][0])
            if profile.get("target_mode") == "delta":
                torch_level = float(sample["current"]) + target_value
            else:
                torch_level = target_value
            error = abs(torch_level - float(numpy_result["level_forecast_cm"]))
            comparisons.append({
                "profile": profile["id"],
                "timestamp": sample["timestamp"].isoformat(timespec="minutes"),
                "torch_level_cm": torch_level,
                "numpy_level_cm": numpy_result["level_forecast_cm"],
                "abs_difference_cm": error,
            })
            if error > 1e-3:
                raise AssertionError(f"NumPy/PyTorch mismatch {error:.8f} cm for {profile['id']}")
    print(json.dumps({
        "status": "OK",
        "comparisons": len(comparisons),
        "max_abs_difference_cm": max(row["abs_difference_cm"] for row in comparisons),
        "profiles": sorted({row["profile"] for row in comparisons}),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
