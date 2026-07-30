#!/usr/bin/env python3
"""Gera uma grade PNG compacta para consulta de altitude no mapa web."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling


def gerar_grade(origem: Path, destino_png: Path, destino_json: Path, passo: int) -> None:
    with rasterio.open(origem) as src:
        largura = math.ceil(src.width / passo)
        altura = math.ceil(src.height / passo)
        grade = src.read(
            1,
            out_shape=(altura, largura),
            masked=True,
            resampling=Resampling.nearest,
        )
        bounds = src.bounds
        crs = str(src.crs)

    valores = np.asarray(grade.filled(np.nan), dtype=np.float32)
    validos = np.isfinite(valores)
    decimetros = np.zeros(valores.shape, dtype=np.uint16)
    decimetros[validos] = np.clip(
        np.rint(valores[validos] * 10), 0, np.iinfo(np.uint16).max
    ).astype(np.uint16)

    rgba = np.zeros((*valores.shape, 4), dtype=np.uint8)
    rgba[..., 0] = (decimetros >> 8).astype(np.uint8)
    rgba[..., 1] = (decimetros & 255).astype(np.uint8)
    rgba[..., 3] = np.where(validos, 255, 0).astype(np.uint8)

    destino_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(destino_png, optimize=True)

    metadados = {
        "cols": largura,
        "rows": altura,
        "bounds": {
            "west": bounds.left,
            "south": bounds.bottom,
            "east": bounds.right,
            "north": bounds.top,
        },
        "W": bounds.left,
        "S": bounds.bottom,
        "E": bounds.right,
        "N": bounds.top,
        "unidade": "m",
        "scale_m": 0.1,
        "escala": 0.1,
        "codificacao": "uint16_decimetros_em_rg",
        "resolucao_aproximada_m": passo * 2,
        "crs": crs,
        "fonte": origem.name,
        "png": destino_png.name,
    }
    destino_json.write_text(
        json.dumps(metadados, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    minimo = float(np.nanmin(valores))
    maximo = float(np.nanmax(valores))
    print(
        f"{destino_png}: {largura}x{altura}, {destino_png.stat().st_size:,} bytes, "
        f"{minimo:.1f} a {maximo:.1f} m"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("origem", type=Path)
    parser.add_argument("destino_png", type=Path)
    parser.add_argument("destino_json", type=Path)
    parser.add_argument("--passo", type=int, default=5)
    args = parser.parse_args()
    gerar_grade(args.origem, args.destino_png, args.destino_json, args.passo)


if __name__ == "__main__":
    main()
