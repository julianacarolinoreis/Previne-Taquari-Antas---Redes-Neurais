"""QA das pendências multiperspectiva (lote 2)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mesa_facilitador_assets() -> None:
    js = (ROOT / "assets/js/mesa_facilitador.js").read_text(encoding="utf-8")
    assert "mesa-facilitador" in js
    assert "PREVINE_MESA_FACILITADOR" in js


def test_mesas_v002_facilitador_wired() -> None:
    for name in ("estudo-caso-resposta-santa-tereza.html", "estudo-caso-resposta-mucum.html"):
        html = (ROOT / "pesquisas" / name).read_text(encoding="utf-8")
        assert "mesa_facilitador.js" in html
        assert "facilitador-mount" in html
        assert "facil-hide" in html


def test_abrigo_form_wired() -> None:
    js = (ROOT / "assets/js/abrigo_capacidade_form.js").read_text(encoding="utf-8")
    assert "PREVINE_ABRIGO_FORM" in js
    for name in ("briefing-gestores.html", "modo-campo.html", "estudo-caso-resposta-mucum.html"):
        html = (ROOT / "pesquisas" / name).read_text(encoding="utf-8")
        assert "abrigo_capacidade_form.js" in html
        assert "abrigo-capacidade-mount" in html


def test_hand_vs_hidro_block_on_maps() -> None:
    pages = [
        "santa_tereza_previsao_inundacao.html",
        "mucum_previsao_inundacao.html",
        "santa_tereza_inundacao.html",
        "mucum_inundacao.html",
        "pesquisas/mancha-inundacao-santa-tereza.html",
        "pesquisas/santa-tereza-rota-fuga-ruas.html",
        "pesquisas/mucum-rota-fuga-ruas.html",
    ]
    for rel in pages:
        html = (ROOT / rel).read_text(encoding="utf-8")
        assert "hand_vs_hidro_block.js" in html, rel


def test_st_rota_ponte_unknown_layer() -> None:
    html = (ROOT / "pesquisas/santa-tereza-rota-fuga-ruas.html").read_text(encoding="utf-8")
    assert "bridgesToggle" in html
    assert "ST_PONTES_UNKNOWN" in html
    assert "bridgeLayer" in html
    scen = (ROOT / "pesquisas/santa-tereza-rota-fuga-ruas-cenario.html").read_text(encoding="utf-8")
    assert "bridgeLayer" in scen


def test_revisao_pendencias_atualizadas() -> None:
    html = (ROOT / "pesquisas/revisao-multiperspectiva.html").read_text(encoding="utf-8")
    assert "Modo facilitador nas mesas V002" in html
    assert "Formulário exportável" in html
    assert "roteiro 90 min cronometrado" in html
    assert "v2 (interseção areal" in html
    assert "benchmark-hand-hidrodinamica.html" in html
    assert "Falta: bloco HAND vs hidrodinâmica" not in html


if __name__ == "__main__":
    for fn in (
        test_mesa_facilitador_assets,
        test_mesas_v002_facilitador_wired,
        test_abrigo_form_wired,
        test_hand_vs_hidro_block_on_maps,
        test_st_rota_ponte_unknown_layer,
        test_revisao_pendencias_atualizadas,
    ):
        fn()
    print("PENDENCIAS_MULTIPERSPECTIVA_QA_OK")
