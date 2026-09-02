#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes mínimos do inventário de terreno."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "assets" / "data" / "hec_hms_audit" / "terrain_inventory_latest.json"


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["rasters"]
    assert all(item["crs"] == "EPSG:4326" for item in report["rasters"])
    regional = [item for item in report["rasters"] if "santa_tereza_anadem_30m" in item["path"]]
    assert regional
    assert regional[0]["point_coverage"]["86472600"] is True
    assert regional[0]["point_coverage"]["86472000"] is True
    assert any("_ortho" in item["path"] and "confirmar" in item["semantic_note"] for item in report["rasters"])
    print("PASS: inventário de terreno e cobertura das estações")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
