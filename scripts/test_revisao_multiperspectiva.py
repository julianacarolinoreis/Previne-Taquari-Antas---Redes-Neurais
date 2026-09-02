"""QA da revisão multiperspectiva e melhorias transversais."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_briefing_exposicao_calculado() -> None:
    html = (ROOT / "pesquisas" / "briefing-gestores.html").read_text(encoding="utf-8")
    assert "CALCULADO v1" in html
    assert "Exposição: UNKNOWN" not in html


def test_modo_campo_checklist_expandido() -> None:
    html = (ROOT / "pesquisas" / "modo-campo.html").read_text(encoding="utf-8")
    for key in ("bridge_ok", "pcd_ok", "radio_ok", "night_ok"):
        assert key in html
    assert "Mensagem rádio/WhatsApp" in html


def test_research_guard_assets() -> None:
    js = (ROOT / "assets/js/previne_research_guard.js").read_text(encoding="utf-8")
    css = (ROOT / "assets/css/previne_research_guard.css").read_text(encoding="utf-8")
    assert "previne-research-guard" in js
    assert "previne-research-guard" in css


def test_revisao_multiperspectiva_page() -> None:
    html = (ROOT / "pesquisas" / "revisao-multiperspectiva.html").read_text(encoding="utf-8")
    assert "Revisão multiperspectiva" in html
    assert "Bombeiro" in html and "Defesa Civil" in html
    assert "Agenda de pesquisa" in html
    assert "67" in html


def test_pesquisas_gestor_filter() -> None:
    html = (ROOT / "pesquisas.html").read_text(encoding="utf-8")
    assert 'data-category="gestor"' in html
    assert "gestorMeetingHrefs" in html
    assert "revisao-multiperspectiva.html" in html


def test_index_gestor_links() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "centro-resposta.html" in html
    assert "282 modelos" in html


def test_painel_evacuacao_bloqueado() -> None:
    html = (ROOT / "pesquisas" / "santa-tereza-painel-evacuacao.html").read_text(encoding="utf-8")
    assert "previne_research_guard.js" in html
    assert "bloqueada" in html.lower() or "bloqueado" in html.lower()


def test_sace_snapshots_guard() -> None:
    for name in ("sace-mucum-live-20260811.html", "sace-mucum-anchor-live.html", "sace-mucum-anchor-20260812.html"):
        html = (ROOT / "pesquisas" / name).read_text(encoding="utf-8")
        assert "previne_research_guard.js" in html
        assert 'data-mode="snapshot"' in html


def test_todas_paginas_guard_ou_gestor() -> None:
    """67 HTML (exceto rascunhos) devem ter gestor_chrome.js ou previne_research_guard.js."""
    pages = sorted(
        p for p in ROOT.rglob("*.html") if "rascunhos/" not in str(p).replace("\\", "/")
    )
    assert len(pages) == 67, f"esperado 67 páginas, encontrado {len(pages)}"
    missing = []
    for p in pages:
        html = p.read_text(encoding="utf-8")
        if "gestor_chrome.js" not in html and "previne_research_guard.js" not in html:
            missing.append(str(p.relative_to(ROOT)))
    assert not missing, "sem guard/gestor: " + ", ".join(missing)


def test_inventario_67_linhas() -> None:
    html = (ROOT / "pesquisas" / "revisao-multiperspectiva.html").read_text(encoding="utf-8")
    import re
    rows = re.findall(r'\["[^"]+","[KFRA]","[^"]+"\]', html)
    assert len(rows) == 67, f"esperado 67 linhas no inventário, encontrado {len(rows)}"
    assert "demais entradas RNA" not in html


if __name__ == "__main__":
    for fn in (
        test_briefing_exposicao_calculado,
        test_modo_campo_checklist_expandido,
        test_research_guard_assets,
        test_revisao_multiperspectiva_page,
        test_pesquisas_gestor_filter,
        test_index_gestor_links,
        test_painel_evacuacao_bloqueado,
        test_sace_snapshots_guard,
        test_todas_paginas_guard_ou_gestor,
        test_inventario_67_linhas,
    ):
        fn()
    print("REVISAO_MULTIPERSPECTIVA_QA_OK")
