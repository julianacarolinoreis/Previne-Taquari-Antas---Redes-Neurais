"""QA lote 10 — rollup centro, chrome updatePlace, soft maps, rota persist, overlay cenários."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ops_rollup_apis() -> None:
    js = (ROOT / "assets/js/resposta_operacional.js").read_text(encoding="utf-8")
    assert "campoChecklistProgress" in js
    assert "abrigoInventorySummary" in js
    assert "loadRotaFieldChecks" in js
    assert "previne_rota_field_v1_" in js
    assert "previne_campo_check_v1" in js
    assert "campo_place" in js
    assert "abrigo_place" in js


def test_gestor_chrome_update_place() -> None:
    js = (ROOT / "assets/js/gestor_chrome.js").read_text(encoding="utf-8")
    assert "PREVINE_GESTOR_CHROME" in js
    assert "updatePlace" in js
    assert 'data-chrome-tab="mapa"' in js
    assert 'data-chrome-tab="resposta"' in js
    assert 'data-chrome-tab="ficha"' in js


def test_centro_rollup() -> None:
    html = (ROOT / "pesquisas/centro-resposta.html").read_text(encoding="utf-8")
    assert 'id="ops-rollup"' in html
    assert "campoChecklistProgress" in html
    assert "abrigoInventorySummary" in html


def test_modo_campo_chrome_sync() -> None:
    html = (ROOT / "pesquisas/modo-campo.html").read_text(encoding="utf-8")
    assert "PREVINE_GESTOR_CHROME.updatePlace" in html


def test_mapas_soft_copy_and_hand() -> None:
    for rel in (
        "pesquisas/mucum-mapa-impacto.html",
        "pesquisas/santa-tereza-mapa-impacto.html",
        "pesquisas/mucum-mapa-margem.html",
        "pesquisas/santa-tereza-mapa-margem.html",
    ):
        html = (ROOT / rel).read_text(encoding="utf-8")
        assert "não é ordem de saída" in html, rel
        assert "hand_vs_hidro_block.js" in html, rel
        assert "crítica — margem esgotada (cenário)" in html, rel
        assert "pessoas precisam sair" not in html, rel
        assert "crítica — resgate" not in html, rel


def test_cenarios_overlay_v2() -> None:
    for rel, place in (
        ("pesquisas/mucum-rota-fuga-ruas-cenario.html", "mucum"),
        ("pesquisas/santa-tereza-rota-fuga-ruas-cenario.html", "santa"),
    ):
        html = (ROOT / rel).read_text(encoding="utf-8")
        assert "exposicao_grade_overlay.js" in html, rel
        assert "PREVINE_EXPOSICAO_OVERLAY" in html, rel
        assert f"place:'{place}'" in html, rel
        assert "layerControl" in html, rel


def test_rota_field_persist() -> None:
    for rel, place in (
        ("pesquisas/mucum-rota-fuga-ruas.html", "mucum"),
        ("pesquisas/santa-tereza-rota-fuga-ruas.html", "santa"),
    ):
        html = (ROOT / rel).read_text(encoding="utf-8")
        assert f"loadRotaFieldChecks('{place}')" in html, rel
        # resposta_operacional must load before fieldChecks init
        assert html.find("resposta_operacional.js") < html.find("loadRotaFieldChecks"), rel


def test_briefing_abrigo_campo() -> None:
    html = (ROOT / "pesquisas/briefing-gestores.html").read_text(encoding="utf-8")
    assert "campoChecklistProgress" in html
    assert "abrigoInventorySummary" in html


def test_revisao_ghost() -> None:
    html = (ROOT / "pesquisas/revisao-multiperspectiva.html").read_text(encoding="utf-8")
    assert "inventário ghost" in html


def test_sw_v11() -> None:
    sw = (ROOT / "sw.js").read_text(encoding="utf-8")
    assert "previne-resposta-v11" in sw


if __name__ == "__main__":
    for fn in (
        test_ops_rollup_apis,
        test_gestor_chrome_update_place,
        test_centro_rollup,
        test_modo_campo_chrome_sync,
        test_mapas_soft_copy_and_hand,
        test_cenarios_overlay_v2,
        test_rota_field_persist,
        test_briefing_abrigo_campo,
        test_revisao_ghost,
        test_sw_v11,
    ):
        fn()
    print("LOTE10_QA_OK")
