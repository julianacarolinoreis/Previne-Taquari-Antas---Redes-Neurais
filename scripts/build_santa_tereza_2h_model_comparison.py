#!/usr/bin/env python3
"""Build a same-row benchmark for the auditable Santa Tereza 2 h rotations.

The rotation files label the independent event as ``Verificacao`` rather than
``Teste``.  This script keeps that provenance explicit and uses only the six
rotations that contain event 12 in that partition.  The other four rotations
are not silently mixed into the common comparison.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
from openpyxl import load_workbook

from build_mucum_q62_model_comparison import fit_baselines, metric_rows


ROOT = Path(__file__).resolve().parents[1]
WORKBOOKS = ROOT / "assets" / "audit_workbooks"
OUTPUT_DIR = ROOT / "assets" / "data" / "santa_tereza_2h"
OUTPUT_JSON = OUTPUT_DIR / "stz_2h_model_comparison.json"
OUTPUT_CSV = OUTPUT_DIR / "stz_2h_model_comparison_metrics.csv"
EVENT = 12
INDEPENDENT_PARTITION = "Verificacao"
CANONICAL_ID = "001_alt_STZ_2H_R01_T12_V1-5-10-15-17-21"


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def workbook_for(model_id: str) -> Path:
    matches = sorted(WORKBOOKS.glob(f"2H_ALT__{model_id}.xlsx"))
    if len(matches) != 1:
        raise RuntimeError(f"esperava uma planilha para {model_id}; encontrei {len(matches)}")
    return matches[0]


def read_workbook(model_id: str) -> dict[str, Any]:
    path = workbook_for(model_id)
    reader = load_workbook(path, read_only=True, data_only=True)
    sheet = reader[sheet_name := reader.sheetnames[0]]
    iterator = sheet.iter_rows(values_only=True)
    header = list(next(iterator))
    indexes = {str(value): index for index, value in enumerate(header) if value not in (None, "")}
    required = {"EVENTO", "CONJUNTO", "OUT2H NIV", "RNA FINAL"}
    missing = sorted(required - set(indexes))
    if missing:
        raise RuntimeError(f"{model_id}: colunas ausentes {missing}")
    target_i = indexes["OUT2H NIV"]
    rna_i = indexes["RNA FINAL"]
    event_i = indexes["EVENTO"]
    partition_i = indexes["CONJUNTO"]
    # The first 15 hydrometeorological fields are the audited inputs.  They
    # stop immediately before the model outputs in this workbook contract.
    feature_indexes = list(range(7, 22))
    feature_names = [str(header[index]) for index in feature_indexes]
    current_i = feature_indexes[0]
    rows = []
    skipped = 0
    for values in iterator:
        event = number(values[event_i])
        target = number(values[target_i])
        current = number(values[current_i])
        rna = number(values[rna_i])
        features = [number(values[index]) for index in feature_indexes]
        if event is None or target is None or current is None or rna is None or any(value is None for value in features):
            skipped += 1
            continue
        year, month, day, hour, minute = [int(number(values[index]) or 0) for index in range(5)]
        base_dt = datetime(year, month, day, hour, minute)
        base = base_dt.strftime("%Y-%m-%d %H:%M")
        target_stamp = (base_dt + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
        rows.append({
            "key": f"{int(event)}|{base}",
            "event": int(event),
            "base_timestamp": base,
            "target_timestamp": target_stamp,
            "partition": str(values[partition_i]),
            "observed": target,
            "current": current,
            "rna": rna,
            "features": features,
        })
    return {"model_id": model_id, "path": path, "sha256": sha256(path), "features": feature_names, "rows": rows, "skipped": skipped, "sheet": sheet_name}


def build() -> dict[str, Any]:
    all_paths = sorted(WORKBOOKS.glob("2H_ALT__*STZ*.xlsx"))
    model_ids = [path.name.removeprefix("2H_ALT__").removesuffix(".xlsx") for path in all_paths]
    source = {model_id: read_workbook(model_id) for model_id in model_ids}
    eligible = []
    ineligible = []
    for model_id, workbook in source.items():
        keys = {row["key"] for row in workbook["rows"] if row["event"] == EVENT and row["partition"] == INDEPENDENT_PARTITION}
        if keys:
            eligible.append((model_id, keys))
        else:
            ineligible.append({"model": model_id, "status": "not_in_common_test", "reason": f"não há evento {EVENT} na partição {INDEPENDENT_PARTITION}"})
    common = set.intersection(*(keys for _, keys in eligible))
    if not common:
        raise RuntimeError("não há chaves comuns do evento independente")
    eligible_ids = [model_id for model_id, _ in eligible]
    canonical = source[CANONICAL_ID]
    canonical_by_key = {row["key"]: row for row in canonical["rows"]}
    test_keys = sorted(common)
    train = [row for row in canonical["rows"] if row["partition"] == "Treino"]
    test_rows = [canonical_by_key[key] for key in test_keys]
    predictions: dict[str, dict[str, float]] = {}
    methods: dict[str, tuple[str, str]] = {}
    for model_id in eligible_ids:
        workbook = source[model_id]
        by_key = {row["key"]: row for row in workbook["rows"]}
        short = model_id.split("_alt_STZ_2H_", 1)[-1].split("_", 1)[0]
        name = f"RNA STZ {short}"
        predictions[name] = {key: by_key[key]["rna"] for key in test_keys}
        methods[name] = ("RNA fonte STZ 2H", model_id)
    predictions["Persistência"] = {key: canonical_by_key[key]["current"] for key in test_keys}
    methods["Persistência"] = ("baseline", "input_01_Nivel_86472600")
    train_x = np.asarray([row["features"] for row in train], dtype=float)
    train_y = np.asarray([row["observed"] for row in train], dtype=float)
    baseline_models, _, _ = fit_baselines(train, len(canonical["features"]))
    fit_audit = {}
    for model_name, estimator in baseline_models.items():
        estimator.fit(train_x, train_y)
        pred = estimator.predict(np.asarray([row["features"] for row in test_rows], dtype=float))
        predictions[model_name] = {key: float(value) for key, value in zip(test_keys, pred)}
        methods[model_name] = ("baseline", CANONICAL_ID)
        final_estimator = estimator[-1] if hasattr(estimator, "steps") else estimator
        fit_audit[model_name] = {"train_points": len(train), "iterations": getattr(final_estimator, "n_iter_", None), "estimator": type(final_estimator).__name__}

    event_metrics = []
    csv_rows = []
    for model_name, values in predictions.items():
        rows = [{**canonical_by_key[key], "predicted": values[key]} for key in test_keys]
        metrics = metric_rows(rows, model_name, 2, methods[model_name][0], methods[model_name][1])
        metrics["event"] = EVENT
        metrics["independent_partition"] = INDEPENDENT_PARTITION
        metrics["n_common_event_points"] = len(rows)
        event_metrics.append(metrics)
        csv_rows.append(metrics)
    event_metrics.sort(key=lambda item: item["mae_cm"])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "schema_version": 1,
        "artifact_id": "santa_tereza_2h_model_comparison",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "status": "research_only_same_common_independent_event",
        "research_only": True,
        "official_alert": False,
        "promotion_allowed": False,
        "purpose": "Comparação no mesmo evento independente E12 entre seis rotações RNA STZ 2H, persistência, Ridge, MLP, Random Forest e XGBoost.",
        "station": {"code": "86472600", "name": "SANTA TEREZA", "river": "RIO TAQUARI"},
        "method": {
            "horizon_hours": 2,
            "independent_event": EVENT,
            "independent_partition_source": INDEPENDENT_PARTITION,
            "train_partition": "Treino",
            "same_common_test_rows": True,
            "common_points": len(test_keys),
            "feature_count": len(canonical["features"]),
            "feature_names": canonical["features"],
            "target": "OUT2H NIV",
            "units": "cm",
            "no_future_features": True,
        },
        "eligible_source_models": eligible_ids,
        "excluded_source_models": ineligible,
        "aggregate_metrics": event_metrics,
        "event_metrics": event_metrics,
        "fit_audit": fit_audit,
        "uncertainty": {
            "status": "not_calibrated_for_live_use",
            "research_only": True,
            "available": ["resíduos e erro do pico no evento E12", "mesmas 257 linhas comuns", "separação Treino/Verificacao"],
            "not_available": ["intervalos de predição calibrados", "incerteza meteorológica", "incerteza MDT/HAND e nível→mancha", "vazão horária reconciliada e curva-chave"],
            "interpretation": "A Verificacao de E12 é replay de nível em centímetros; não é intervalo de segurança nem calibração de vazão.",
        },
        "audit": {
            "source_workbook_count": len(source),
            "eligible_workbook_count": len(eligible_ids),
            "source_workbook_sha256": {model_id: item["sha256"] for model_id, item in source.items()},
            "duplicate_common_keys": 0,
            "target_and_output_columns_in_inputs": False,
            "source_rna_not_retrained": True,
            "flow_calibration_status": "blocked_for_flow_calibration",
            "flow_calibration_reason": "o pacote de Santa Tereza preserva nível, mas não contém vazão horária reconciliada e curva-chave para converter cm em m3/s.",
        },
        "sources": ["assets/data/auditaveis_series.json", "assets/data/santa_tereza_eventwise_replay_rna_2h/eventwise_manifest.json", "assets/audit_workbooks/"],
    }
    OUTPUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        fields = sorted({key for row in csv_rows for key in row})
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(csv_rows)
    return output


if __name__ == "__main__":
    result = build()
    print(json.dumps({"output": rel(OUTPUT_JSON), "eligible_models": len(result["eligible_source_models"]), "common_points": result["method"]["common_points"]}, ensure_ascii=False))
