#!/usr/bin/env python3
"""Run PREVINE AI Lab research-only shadow inference for Santa Tereza +2 h."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import torch

import ai_lab_temporal_train as temporal


ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "assets" / "data" / "ai_lab" / "live_inputs_stz_2h.json"
MANIFEST = ROOT / "assets" / "data" / "ai_lab" / "shadow_bundle_manifest.json"
LIVE = ROOT / "previsao_ao_vivo.json"
OUT = ROOT / "assets" / "data" / "ai_lab" / "shadow_live_latest.json"
HISTORY = ROOT / "assets" / "data" / "ai_lab" / "shadow_live_history.json"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_local(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def find_file(base: Path, name: str) -> Path:
    matches = list(base.rglob(name))
    if not matches:
        raise FileNotFoundError(f"{name} ausente em {base}")
    return matches[0]


def write_status(status: str, note: str, extra: dict | None = None) -> None:
    payload = {
        "schema_version": 1,
        "artifact_id": "previne_ai_lab_shadow_live",
        "generated_at_utc": now_utc(),
        "research_only": True,
        "official_alert": False,
        "promotion_allowed": False,
        "status": status,
        "note": note,
    }
    if extra:
        payload.update(extra)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_window(inputs: dict, manifest: dict) -> tuple[np.ndarray, datetime, float]:
    if not inputs.get("ready"):
        raise RuntimeError(f"janela não pronta: {inputs.get('status')}")
    rows = inputs.get("rows") or []
    if len(rows) != 8:
        raise RuntimeError(f"janela precisa de 8 linhas; recebeu {len(rows)}")
    expected = (manifest.get("source") or {}).get("feature_names") or []
    actual = inputs.get("feature_names") or []
    if actual != expected:
        raise RuntimeError("ordem/nome das features diverge do pacote de treinamento")
    source_hash = str(inputs.get("source_workbook_sha256") or "").lower()
    expected_hash = str((manifest.get("source") or {}).get("sha256") or "").lower()
    if source_hash != expected_hash:
        raise RuntimeError("hash do workbook da janela ao vivo diverge do treinamento")
    times = [parse_local(row.get("hora_modelo")) for row in rows]
    if any(t is None for t in times):
        raise RuntimeError("timestamp inválido na janela")
    for i in range(1, len(times)):
        if times[i] - times[i - 1] != timedelta(hours=1):
            raise RuntimeError("janela não é horária consecutiva")
    vectors = []
    for row in rows:
        values = row.get("input_values_cm") or []
        if len(values) != len(expected):
            raise RuntimeError("número de features inválido na janela")
        vector = [float(v) for v in values]
        if not all(math.isfinite(v) for v in vector):
            raise RuntimeError("feature não finita na janela")
        vectors.append(vector)
    current = float(rows[-1]["nivel_atual_cm"])
    return np.asarray(vectors, dtype=np.float32), times[-1], current


def predict_temporal(artifact_dir: Path, manifest: dict, x: np.ndarray, current: float) -> tuple[float, dict]:
    info = (manifest.get("temporal_candidate") or {}).get("bundle") or {}
    filename = Path(info["path"]).name
    model_path = find_file(artifact_dir, filename)
    payload = torch.load(model_path, map_location="cpu", weights_only=False)
    profile = dict(payload["profile"])
    model_name = str(payload["model_name"])
    feature_names = payload["feature_names"]
    if x.shape != (int(profile["lookback_h"]), len(feature_names)):
        raise RuntimeError(f"shape temporal inválido: {x.shape}")
    x_mean = np.asarray(payload["x_mean"], dtype=np.float32)
    x_std = np.asarray(payload["x_std"], dtype=np.float32)
    scaled = (x - x_mean) / x_std
    model = temporal.build_temporal_model(model_name, len(feature_names), profile)
    model.load_state_dict(payload["state_dict"])
    model.eval()
    with torch.no_grad():
        raw_scaled = float(model(torch.as_tensor(scaled[None, :, :], dtype=torch.float32)).item())
    raw = raw_scaled * float(payload["y_std"]) + float(payload["y_mean"])
    predicted = current + raw if payload.get("target_mode") == "delta" else raw
    return float(predicted), {
        "model": model_name,
        "profile": profile,
        "epochs_refit": payload.get("epochs_refit"),
        "target_mode": payload.get("target_mode"),
        "bundle_sha256": info.get("sha256"),
    }


def predict_static(artifact_dir: Path, manifest: dict, x_last: np.ndarray) -> tuple[float, dict]:
    info = (manifest.get("static_comparator") or {}).get("bundle") or {}
    filename = Path(info["path"]).name
    model_path = find_file(artifact_dir, filename)
    payload = joblib.load(model_path)
    estimator = payload["estimator"]
    predicted = float(estimator.predict(np.asarray([x_last], dtype=float))[0])
    return predicted, {
        "model": payload.get("model_name"),
        "bundle_sha256": info.get("sha256"),
    }


def observation_map(live: dict) -> dict[str, float]:
    out = {}
    for row in live.get("serie_observada_ana") or []:
        hour = parse_local(row.get("hora"))
        value = row.get("nivel_cm")
        if hour is None or value is None or hour.minute != 0:
            continue
        out[hour.isoformat(timespec="minutes")] = float(value)
    return out


def summarize(records: list[dict], key: str) -> dict:
    errors = []
    for row in records:
        obs = row.get("observado_cm")
        pred = row.get(key)
        if obs is None or pred is None:
            continue
        errors.append(float(pred) - float(obs))
    if not errors:
        return {"n_conferidas": 0, "mae_cm": None, "rmse_cm": None, "bias_cm": None, "max_abs_cm": None}
    arr = np.asarray(errors, dtype=float)
    return {
        "n_conferidas": int(len(arr)),
        "mae_cm": float(np.mean(np.abs(arr))),
        "rmse_cm": float(np.sqrt(np.mean(arr ** 2))),
        "bias_cm": float(np.mean(arr)),
        "max_abs_cm": float(np.max(np.abs(arr))),
    }


def update_history(current: dict, live: dict) -> dict:
    package = load_json(HISTORY, {"schema_version": 1, "registros": []})
    records = package.get("registros") or []
    obs_map = observation_map(live)
    for row in records:
        if row.get("observado_cm") is not None:
            continue
        target = parse_local(row.get("hora_alvo"))
        if target is None:
            continue
        key = target.isoformat(timespec="minutes")
        if key in obs_map:
            obs = obs_map[key]
            row["observado_cm"] = obs
            row["auditado_em_utc"] = now_utc()
            for pred_key, error_key in (
                ("temporal_previsto_cm", "temporal_erro_cm"),
                ("static_previsto_cm", "static_erro_cm"),
                ("modelo_operacional_previsto_cm", "operacional_erro_cm"),
            ):
                pred = row.get(pred_key)
                row[error_key] = None if pred is None else float(pred) - obs
    key = current["id"]
    replaced = False
    for i, row in enumerate(records):
        if row.get("id") == key:
            observed_fields = {k: row.get(k) for k in (
                "observado_cm", "auditado_em_utc", "temporal_erro_cm",
                "static_erro_cm", "operacional_erro_cm"
            ) if k in row}
            merged = dict(current)
            merged.update(observed_fields)
            records[i] = merged
            replaced = True
            break
    if not replaced:
        records.append(current)
    records = records[-1200:]
    package = {
        "schema_version": 1,
        "artifact_id": "previne_ai_lab_shadow_live_history",
        "updated_at_utc": now_utc(),
        "research_only": True,
        "official_alert": False,
        "registros": records,
        "metrics": {
            "temporal": summarize(records, "temporal_previsto_cm"),
            "static": summarize(records, "static_previsto_cm"),
            "operational_reference": summarize(records, "modelo_operacional_previsto_cm"),
        },
    }
    HISTORY.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return package


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args()
    artifact_dir = Path(args.artifact_dir)
    manifest = load_json(MANIFEST, {})
    inputs = load_json(INPUTS, {})
    live = load_json(LIVE, {})
    if not manifest:
        write_status("WAITING_MODEL_BUNDLE", "manifesto do pacote sombra ainda não existe")
        return
    if not inputs:
        write_status("WAITING_INPUT_WINDOW", "janela ao vivo 8x15 ainda não foi publicada")
        return
    try:
        x, base_hour, current = validate_window(inputs, manifest)
        temporal_pred, temporal_meta = predict_temporal(artifact_dir, manifest, x, current)
        static_pred, static_meta = predict_static(artifact_dir, manifest, x[-1])
    except Exception as exc:
        write_status("BLOCKED_INPUT_OR_MODEL_CONTRACT", str(exc), {
            "input_status": inputs.get("status"),
            "rows_valid": inputs.get("rows_valid"),
        })
        return

    target_hour = base_hour + timedelta(hours=int(manifest.get("horizon_hours") or 2))
    h2 = (live.get("horizontes") or {}).get("2h") or {}
    operational_pred = h2.get("nivel_previsto_cm")
    record = {
        "id": f"STZ|AI_LAB_SHADOW|2h|{base_hour.isoformat(timespec='seconds')}",
        "hora_modelo": base_hour.isoformat(timespec="seconds"),
        "hora_alvo": target_hour.isoformat(timespec="seconds"),
        "nivel_atual_cm": current,
        "temporal_modelo": temporal_meta["model"],
        "temporal_profile": temporal_meta["profile"].get("id"),
        "temporal_previsto_cm": round(temporal_pred, 3),
        "temporal_delta_cm": round(temporal_pred - current, 3),
        "static_modelo": static_meta["model"],
        "static_previsto_cm": round(static_pred, 3),
        "modelo_operacional": h2.get("modelo"),
        "modelo_operacional_previsto_cm": operational_pred,
        "observado_cm": None,
        "status": "SHADOW_ONLY",
        "research_only": True,
        "official_alert": False,
        "generated_at_utc": now_utc(),
    }
    history = update_history(record, live)
    latest = {
        "schema_version": 1,
        "artifact_id": "previne_ai_lab_shadow_live",
        "generated_at_utc": now_utc(),
        "station": manifest.get("station"),
        "horizon_hours": manifest.get("horizon_hours"),
        "research_only": True,
        "official_alert": False,
        "promotion_allowed": False,
        "status": "SHADOW_RUNNING",
        "input_contract": {
            "ready": inputs.get("ready"),
            "rows_valid": inputs.get("rows_valid"),
            "feature_count": inputs.get("feature_count"),
            "hora_referencia": inputs.get("hora_referencia"),
            "source_workbook_sha256": inputs.get("source_workbook_sha256"),
        },
        "prediction": record,
        "bundle": {
            "temporal": temporal_meta,
            "static": static_meta,
        },
        "live_audit_metrics": history.get("metrics"),
        "note": "Inferência de pesquisa em sombra. Não entra na previsão oficial nem em alerta.",
    }
    OUT.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": latest["status"],
        "hora_modelo": record["hora_modelo"],
        "temporal_modelo": record["temporal_modelo"],
        "temporal_previsto_cm": record["temporal_previsto_cm"],
        "static_previsto_cm": record["static_previsto_cm"],
        "operational_reference_cm": operational_pred,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
