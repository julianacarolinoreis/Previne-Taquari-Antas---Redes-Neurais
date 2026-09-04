#!/usr/bin/env python3
"""Exporta pacote de handoff para treino MIMO nativo em MATLAB (2h+4h).

Gera CSVs alinhados + manifesto JSON. Não promove modelo ao vivo.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from mimo_core import align_horizons

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "assets/data/research_mimo_matlab_handoff"
MATLAB_DIR = Path(__file__).resolve().parent / "matlab"


def _write_csv(path: Path, header: list[str], rows: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(",".join(header) + "\n")
        for row in rows:
            f.write(",".join(f"{float(v):.10g}" for v in row) + "\n")


def export_package(out_dir: Path = OUT_DIR) -> dict:
    aligned = align_horizons(["2h", "4h"])
    ds2, ds4 = aligned["datasets"]
    rows = aligned["rows"]

    n_in = ds2.n_inputs
    header = (
        [f"x{i+1}" for i in range(n_in)]
        + ["atual_cm", "delta_2h_cm", "delta_4h_cm", "target_2h_cm", "target_4h_cm", "split", "event"]
    )

    table = []
    for row in rows:
        i2, i4 = row["indices"]
        x = ds2.inputs[i2]
        atual = float(ds2.atual[i2])
        d2 = float(ds2.delta[i2])
        d4 = float(ds4.delta[i4])
        event = row["event"] if row["event"] is not None else -1
        table.append([*x, atual, d2, d4, atual + d2, atual + d4, float(row["split"]), float(event)])
    table = np.asarray(table, float)

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "mimo_aligned_2h4h_15in.csv"
    _write_csv(csv_path, header, table)

    # splits separados para scripts MATLAB simples
    for split_id, name in [(1, "treino"), (2, "validacao"), (3, "teste")]:
        mask = table[:, -2] == split_id
        _write_csv(out_dir / f"mimo_aligned_2h4h_15in_{name}.csv", header, table[mask])

    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "research_only": True,
        "official_alert": False,
        "station": "86472600",
        "horizons_h": [2, 4],
        "n_inputs": n_in,
        "n_rows": int(table.shape[0]),
        "split_counts": {
            "treino": int(np.sum(table[:, -2] == 1)),
            "validacao": int(np.sum(table[:, -2] == 2)),
            "teste": int(np.sum(table[:, -2] == 3)),
        },
        "alignment_key": "atual + inputs[0:3] arredondados a 0,1 cm",
        "target": "deltas ALT (cm) para 2h e 4h; nível absoluto = atual + delta",
        "source_mats": {
            "2h": str(ds2.mat_path.relative_to(ROOT)),
            "4h": str(ds4.mat_path.relative_to(ROOT)),
        },
        "files": {
            "all": csv_path.name,
            "treino": "mimo_aligned_2h4h_15in_treino.csv",
            "validacao": "mimo_aligned_2h4h_15in_validacao.csv",
            "teste": "mimo_aligned_2h4h_15in_teste.csv",
            "matlab_script": "codigo_python/11_experimento_mimo/matlab/train_mimo_2h4h_stz.m",
            "matlab_readme": "codigo_python/11_experimento_mimo/matlab/README.md",
        },
        "protocol": {
            "activation": "logsig / unisig (estilo PREVINE)",
            "outputs": 2,
            "early_stopping": "mínimo EQ validação; patience sugerida 40",
            "compare_against": [
                "Direct scratch Python (mesmo CSV)",
                "mat_reference_metrics_teste (NASH 2h≈0,9962 · 4h≈0,9926)",
            ],
            "do_not": [
                "promover ao robô ao vivo sem revisão",
                "usar replay alinhado NASH≈1 como teto",
            ],
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # espelho leve no diretório matlab
    MATLAB_DIR.mkdir(parents=True, exist_ok=True)
    (MATLAB_DIR / "DATA_PATH.txt").write_text(
        str((ROOT / "assets/data/research_mimo_matlab_handoff").resolve()) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    m = export_package()
    print(json.dumps({"ok": True, "n_rows": m["n_rows"], "splits": m["split_counts"]}, ensure_ascii=False))
