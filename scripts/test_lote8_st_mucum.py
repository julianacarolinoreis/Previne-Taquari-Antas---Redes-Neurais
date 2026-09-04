"""QA lote 8 — mesa Muçum v1/v2 + mensagem, overlay rotas, hub/SW."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mucum_mesa_exposure_compare() -> None:
    html = (ROOT / "pesquisas/estudo-caso-resposta-mucum.html").read_text(encoding="utf-8")
    js = (ROOT / "assets/js/mesa_mucum_v002.js").read_text(encoding="utf-8")
    assert "exp-v1-pop" in html
    assert "exp-v2-pop" in html
    assert "exposicao_mucum.json" in html
    assert "exposureV1" in js


def test_mucum_mesa_message_draft() -> None:
    html = (ROOT / "pesquisas/estudo-caso-resposta-mucum.html").read_text(encoding="utf-8")
    js = (ROOT / "assets/js/mesa_mucum_v002.js").read_text(encoding="utf-8")
    assert "messageDraft" in html
    assert "copyMessage" in html
    assert "buildMessageDraft" in js
    assert "RASCUNHO — NÃO É ALERTA" in js


def test_rota_exposicao_overlay() -> None:
    muc = (ROOT / "pesquisas/mucum-rota-fuga-ruas.html").read_text(encoding="utf-8")
    st = (ROOT / "pesquisas/santa-tereza-rota-fuga-ruas.html").read_text(encoding="utf-8")
    for html in (muc, st):
        assert "exposicao_grade_overlay.js" in html
        assert "PREVINE_EXPOSICAO_OVERLAY.mount" in html


def test_dashboard_exposicao_v2_copy() -> None:
    js = (ROOT / "assets/js/bacia_dashboard.js").read_text(encoding="utf-8")
    assert "areal" in js
    assert "centroide" not in js.split("layer-exposicao")[1][:200]


def test_hub_narrative() -> None:
    centro = (ROOT / "pesquisas/centro-resposta.html").read_text(encoding="utf-8")
    briefing = (ROOT / "pesquisas/briefing-gestores.html").read_text(encoding="utf-8")
    revisao = (ROOT / "pesquisas/revisao-multiperspectiva.html").read_text(encoding="utf-8")
    assert "Rota Muçum Etapa 2" in centro
    assert "Sala Muçum" not in centro or "Arquivo · painel Muçum" in centro
    assert "estudo-caso-resposta-mucum.html" in briefing
    assert "Mesa Muçum V002" in revisao


def test_sw_v9_shell() -> None:
    sw = (ROOT / "sw.js").read_text(encoding="utf-8")
    assert "previne-resposta-v9" in sw
    assert "exposicao_grade_overlay.js" in sw
    assert "exposicao_santa_tereza.json" in sw


if __name__ == "__main__":
    for fn in (
        test_mucum_mesa_exposure_compare,
        test_mucum_mesa_message_draft,
        test_rota_exposicao_overlay,
        test_dashboard_exposicao_v2_copy,
        test_hub_narrative,
        test_sw_v9_shell,
    ):
        fn()
    print("LOTE8_QA_OK")
