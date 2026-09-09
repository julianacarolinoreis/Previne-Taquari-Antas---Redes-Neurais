#!/usr/bin/env python3
"""Exporta pesos do MIMO PREVINE campeão (pesquisa — NÃO operacional)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from mimo_core import align_horizons
from run_experiment import train_mimo_variants

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "assets/data/research_mimo_python_weights"


def export_champion_weights(
    out_dir: Path = OUT_DIR,
    *,
    hidden_sizes=(52,),
    seeds=tuple(range(1, 11)),
    max_cycles=100000,
    patience_previne=15000,
) -> dict:
    aligned = align_horizons(["2h", "4h"])
    rows, ds = aligned["rows"], aligned["datasets"]
    specs = [(0, 0), (1, 1)]
    train_rows = [r for r in rows if r["split"] == 1]
    y_tr = np.asarray(
        [[ds[0].delta[r["indices"][0]], ds[1].delta[r["indices"][1]]] for r in train_rows],
        float,
    )
    rising_w = np.where((y_tr[:, 1] - y_tr[:, 0]) > 0, 2.0, 1.0)

    payload, model = train_mimo_variants(
        rows,
        ds,
        1,  # 26 inputs do 4h
        specs,
        list(hidden_sizes),
        name_suffix="_export_champ_26in",
        protocol="previne",
        sample_weights_tr=rising_w,
        seeds=seeds,
        max_cycles=max_cycles,
        patience_previne=patience_previne,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    npz_path = out_dir / "mimo_previne_2h4h_26in_nh52.npz"
    meta_path = out_dir / "manifest.json"
    np.savez_compressed(
        npz_path,
        wh=model.wh,
        bh=model.bh,
        ws=model.ws,
        bs=model.bs,
        ae=model.x_std,  # PREVINE ae
        be=model.x_mean,  # PREVINE be
        au=model.y_std,
        bu=model.y_mean,
    )
    teste = payload["splits"]["teste"]
    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "research_only": True,
        "official_alert": False,
        "do_not_promote_live": True,
        "station": "86472600",
        "protocol": "previne",
        "n_inputs": 26,
        "n_outputs": 2,
        "horizons_h": [2, 4],
        "input_source": "4h Direct feature set (26in)",
        "labels": "Ttot1 observation deltas",
        "hidden": int(model.n_hidden),
        "training": payload.get("training"),
        "teste_metrics": {
            hz: {
                k: round(float(v[k]), 4) if isinstance(v[k], float) else v[k]
                for k in ("nash", "pers", "e95", "mae", "n")
            }
            for hz, v in teste.items()
        },
        "files": {"weights_npz": npz_path.name},
        "forward": "pn=(x-be)/ae; h=logsig(pn@wh.T+bh); yn=logsig(h@ws.T+bs); delta=yn*au+bu; nivel=atual+delta",
        "note": "Pacote de pesquisa. Não substitui Direct .mat operacionais nem alerta oficial.",
    }
    meta_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(export_champion_weights(), ensure_ascii=False, indent=2))
