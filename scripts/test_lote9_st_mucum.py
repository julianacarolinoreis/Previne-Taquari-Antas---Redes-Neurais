"""QA lote 9 — abrigo seeds, modo campo place sync, ST ata, briefing dual."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_abrigo_seeds_api() -> None:
    js = (ROOT / "assets/js/abrigo_capacidade_form.js").read_text(encoding="utf-8")
    assert "Ginásio de Esportes" in js
    assert "setMunicipio" in js
    assert "mucum_contingencia_202607.json" in js
    assert "capacidade_planejada" in js
    assert 'aberto">desconhecido' in js or 'value="desconhecido"' in js


def test_modo_campo_place_sync() -> None:
    html = (ROOT / "pesquisas/modo-campo.html").read_text(encoding="utf-8")
    assert "PREVINE_ABRIGO_FORM.setMunicipio" in html
    assert "searchParams.set('place'" in html
    assert "q === 'mucum'" in html


def test_st_mesa_ata_unificada() -> None:
    html = (ROOT / "pesquisas/estudo-caso-resposta-santa-tereza.html").read_text(encoding="utf-8")
    assert 'id="exportUnified"' in html
    assert "exportUnifiedAta" in html


def test_briefing_dual_mesa_status() -> None:
    html = (ROOT / "pesquisas/briefing-gestores.html").read_text(encoding="utf-8")
    assert "briefing-resposta-status" in html
    assert "mesaChecklistProgress" in html
    assert "Muçum V002" in html
    assert "v2 areal" in html


def test_roteiro_mesas_dual() -> None:
    js = (ROOT / "assets/js/briefing_roteiro_90.js").read_text(encoding="utf-8")
    assert "Mesas V002" in js
    assert "ST ou Muçum" in js


def test_mucum_cenario_hand_block() -> None:
    html = (ROOT / "pesquisas/mucum-rota-fuga-ruas-cenario.html").read_text(encoding="utf-8")
    assert "hand_vs_hidro_block.js" in html


def test_sw_v10() -> None:
    sw = (ROOT / "sw.js").read_text(encoding="utf-8")
    assert "previne-resposta-v10" in sw
    assert "mucum_contingencia_202607.json" in sw


if __name__ == "__main__":
    for fn in (
        test_abrigo_seeds_api,
        test_modo_campo_place_sync,
        test_st_mesa_ata_unificada,
        test_briefing_dual_mesa_status,
        test_roteiro_mesas_dual,
        test_mucum_cenario_hand_block,
        test_sw_v10,
    ):
        fn()
    print("LOTE9_QA_OK")
