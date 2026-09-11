#!/usr/bin/env python3
"""Tests for multi-site nível decision artifact (RNA primary, HEC parked)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
SCRIPT = ROOT / "scripts" / "build_estudo_decisao_previsao_nivel_multi_alvo.py"


def test_builder_writes_locked_rna_decision() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "decidido_rna_nivel_multi_alvo_hec_estacionado" in proc.stdout

    data = json.loads((OUT / "decisao_previsao_nivel_multi_alvo_latest.json").read_text(encoding="utf-8"))
    assert data["status"] == "decidido_rna_nivel_multi_alvo_hec_estacionado"
    assert data["decision"]["chosen_path"] == "RNA_nivel_por_estacao_com_mascara"
    assert data["decision"]["stz_rating_curve"]["exists"] is False
    assert data["decision"]["stz_rating_curve"]["impact_on_nivel_rna"] == "nenhum"
    assert "HEC-HMS / gêmeo HEC como caminho principal de previsão de nível" in data["decision"]["not_chosen_as_primary"]

    codes = {c["station_code"] for c in data["candidates"]}
    assert "86472600" in codes and "86510000" in codes
    targets = [c for c in data["candidates"] if c["tier"] == "alvo_operacional_rna"]
    assert {t["station_code"] for t in targets} == {"86472600", "86510000"}
    for t in targets:
        assert t["needs_rating_curve_for_nivel_rna"] is False

    html = (OUT / "decisao_previsao_nivel_multi_alvo.html").read_text(encoding="utf-8")
    assert "RNA, não HEC-primeiro" in html
    assert "86472600" in html

    checklist = json.loads((OUT / "stz_q_unlock_checklist_latest.json").read_text(encoding="utf-8"))
    assert checklist.get("hec_primary") is False
    assert "RNA" in checklist.get("note_for_nivel_forecast", "")


if __name__ == "__main__":
    test_builder_writes_locked_rna_decision()
    print("ok")
