#!/usr/bin/env python3
"""Extract a G040 polygon clip from the official ANA/SNIRH BHO6 GeoPackage.

This helper intentionally does NOT download the national BHO6 GeoPackage.
Provide a local copy of GEOFT_BHO_AREA_DRENAGEM.gpkg and the script will use
GDAL/ogr2ogr to extract only COBACIA values in the G040 family (786%).

The resulting GeoJSON is the optional same-version polygon input consumed by
build_g040_incremental_geometries.py.

Research only.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = (
    ROOT
    / "assets/data/hec_hms_g040_full_basin/bho6_area_drenagem_g040.geojson"
)
OFFICIAL_SOURCE = (
    "https://metadados.snirh.gov.br/files/"
    "32e309da-a8c1-443f-90ac-0cd79ce6a33d/geoft_bho_area_drenagem.gpkg"
)


def run(cmd):
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ).stdout


def discover_layers(source: Path) -> list[str]:
    out = run(["ogrinfo", "-ro", str(source)])
    layers = []
    for line in out.splitlines():
        m = re.match(r"^\s*\d+\s*:\s*(.+?)(?:\s*\(|$)", line)
        if m:
            layers.append(m.group(1).strip())
    return layers


def choose_layer(layers: list[str], explicit: str | None) -> str:
    if explicit:
        if explicit not in layers:
            raise RuntimeError(
                f"requested layer {explicit!r} not found; available={layers}"
            )
        return explicit
    ranked = [
        x
        for x in layers
        if "area" in x.lower() and "dren" in x.lower()
    ]
    if len(ranked) == 1:
        return ranked[0]
    if len(layers) == 1:
        return layers[0]
    raise RuntimeError(
        "could not select BHO6 drainage-area layer unambiguously; "
        f"available={layers}. Pass --layer."
    )


def validate_output(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") or []
    codes = []
    invalid = 0
    for ft in features:
        props = {
            str(k).lower(): v
            for k, v in (ft.get("properties") or {}).items()
        }
        code = props.get("cobacia")
        if code in (None, ""):
            invalid += 1
            continue
        codes.append(str(code))
    wrong_family = [x for x in codes if not x.startswith("786")]
    if not features or not codes:
        raise RuntimeError("extracted clip contains no usable BHO6 polygons")
    if wrong_family:
        raise RuntimeError(
            f"clip contains {len(wrong_family)} COBACIA values outside 786"
        )
    return {
        "feature_count": len(features),
        "usable_cobacia_count": len(codes),
        "unique_cobacia_count": len(set(codes)),
        "invalid_features": invalid,
        "all_codes_g040_family": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Local official geoft_bho_area_drenagem.gpkg file.",
    )
    ap.add_argument("--layer", default=None)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    if not args.source.exists():
        raise FileNotFoundError(args.source)
    if shutil.which("ogrinfo") is None or shutil.which("ogr2ogr") is None:
        raise RuntimeError(
            "GDAL command-line tools are required (ogrinfo and ogr2ogr)."
        )

    layers = discover_layers(args.source)
    layer = choose_layer(layers, args.layer)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()

    # SQLite CAST avoids relying on whether COBACIA is stored as text/integer.
    sql = (
        f'SELECT * FROM "{layer}" '
        "WHERE CAST(COBACIA AS TEXT) LIKE '786%'"
    )
    run(
        [
            "ogr2ogr",
            "-f",
            "GeoJSON",
            str(args.out),
            str(args.source),
            "-dialect",
            "SQLite",
            "-sql",
            sql,
            "-t_srs",
            "EPSG:4326",
        ]
    )
    audit = validate_output(args.out)
    audit.update(
        {
            "source_file": str(args.source),
            "source_layer": layer,
            "official_download_reference": OFFICIAL_SOURCE,
            "output": str(args.out),
        }
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
