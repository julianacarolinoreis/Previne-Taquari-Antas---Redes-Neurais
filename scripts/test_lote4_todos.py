"""QA lote 4 — roteiro 90 min, checklist unificado, exposição v2, benchmark."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_roteiro_90_briefing() -> None:
    js = (ROOT / "assets/js/briefing_roteiro_90.js").read_text(encoding="utf-8")
    assert "PREVINE_ROTEIRO_90" in js
    assert len(re.findall(r"title:", js)) >= 8
    html = (ROOT / "pesquisas/briefing-gestores.html").read_text(encoding="utf-8")
    assert "briefing_roteiro_90.js" in html
    assert "roteiro-90-mount" in html


def test_checklist_sync_api() -> None:
    js = (ROOT / "assets/js/resposta_operacional.js").read_text(encoding="utf-8")
    assert "syncMesaValidation" in js
    assert "mesaChecklistProgress" in js
    st = (ROOT / "pesquisas/estudo-caso-resposta-santa-tereza.html").read_text(encoding="utf-8")
    assert "syncMesaValidation" in st
    centro = (ROOT / "pesquisas/centro-resposta.html").read_text(encoding="utf-8")
    assert "check-mesa-sync" in centro
    assert "mesaChecklistProgress" in centro


def test_exposicao_v2_json() -> None:
    for name in ("exposicao_mucum_v2.json", "exposicao_santa_tereza_v2.json"):
        data = json.loads((ROOT / "assets/data/exposicao_cruzada" / name).read_text(encoding="utf-8"))
        assert data["schema_version"] == 2
        assert data["metodo"]["versao"] == "v2-areal"
        assert len(data["niveis"]) >= 4
    muc = json.loads((ROOT / "assets/data/exposicao_cruzada/exposicao_mucum_v2.json").read_text())
    peak = next(n for n in muc["niveis"] if abs(n["hand_m"] - 17.02) < 0.01)
    assert peak["grade_200m"]["pop"] == 2070
    st = json.loads((ROOT / "assets/data/exposicao_cruzada/exposicao_santa_tereza_v2.json").read_text())
    peak_st = next(n for n in st["niveis"] if abs(n["hand_m"] - 15.0) < 0.01)
    assert peak_st["grade_200m"]["pop"] == 336


def test_exposicao_cruzada_v2_ui() -> None:
    html = (ROOT / "pesquisas/exposicao-cruzada.html").read_text(encoding="utf-8")
    assert "v1 + v2" in html
    assert "v1v2-compare" in html
    assert "exposicao_mucum_v2.json" in html
    assert "st-level-rows" in html


def test_benchmark_hidrodinamica() -> None:
    idx = json.loads((ROOT / "assets/data/benchmark_hidrodinamica/indice.json").read_text(encoding="utf-8"))
    assert idx["schema_version"] == 1
    assert len(idx["subareas"]) >= 2
    page = (ROOT / "pesquisas/benchmark-hand-hidrodinamica.html").read_text(encoding="utf-8")
    assert "benchmark_hidrodinamica/indice.json" in page
    block = (ROOT / "assets/js/hand_vs_hidro_block.js").read_text(encoding="utf-8")
    assert "benchmark-hand-hidrodinamica.html" in block


def test_revisao_lote4_atualizada() -> None:
    html = (ROOT / "pesquisas/revisao-multiperspectiva.html").read_text(encoding="utf-8")
    assert "roteiro 90 min cronometrado" in html
    assert "v2 (interseção areal" in html
    assert "benchmark-hand-hidrodinamica.html" in html
    assert "Falta: roteiro 90 min" not in html
    assert "Falta: exposição v2" not in html


def test_sw_v5_assets() -> None:
    sw = (ROOT / "sw.js").read_text(encoding="utf-8")
    assert "previne-resposta-v7" in sw
    assert "briefing_roteiro_90.js" in sw
    assert "exposicao_mucum_v2.json" in sw


if __name__ == "__main__":
    for fn in (
        test_roteiro_90_briefing,
        test_checklist_sync_api,
        test_exposicao_v2_json,
        test_exposicao_cruzada_v2_ui,
        test_benchmark_hidrodinamica,
        test_revisao_lote4_atualizada,
        test_sw_v5_assets,
    ):
        fn()
    print("LOTE4_TODOS_QA_OK")
