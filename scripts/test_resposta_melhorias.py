"""QA das melhorias operacionais: feeds enriquecidos, lacunas atualizadas, fichas jusante."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_centro_resposta_gaps_updated() -> None:
    html = (ROOT / "pesquisas" / "centro-resposta.html").read_text(encoding="utf-8")
    assert "Exposição · CALCULADO" in html
    assert "Exposição · UNKNOWN" not in html
    assert "plano jul/2026 digitalizado" in html
    assert "fetchExposurePeak" in html


def test_bacia_dashboard_exposure_layer() -> None:
    js = (ROOT / "assets/js/bacia_dashboard.js").read_text(encoding="utf-8")
    assert "layer-exposicao', 'CALCULADO" in js or "layer-exposicao', 'CALCULADO (ST/Muçum)" in js
    assert "Muçum ainda sem sala V002" not in js


def test_resposta_operacional_exports() -> None:
    js = (ROOT / "assets/js/resposta_operacional.js").read_text(encoding="utf-8")
    assert "MUC_MESA_KEY" in js
    assert "fetchExposurePeak" in js
    assert "summarizeHorizons" in js
    assert "summarizePair" in js


def test_ficha_jusante_proxy() -> None:
    js = (ROOT / "assets/js/ficha_jusante.js").read_text(encoding="utf-8")
    html = (ROOT / "pesquisa_status_encantado.html").read_text(encoding="utf-8")
    assert "exposure-note" in html
    assert "proxy-levels" in html
    assert "fetchLive('mucum')" in js


def test_exposure_files_present() -> None:
    indice = json.loads((ROOT / "assets/data/exposicao_cruzada/indice.json").read_text(encoding="utf-8"))
    assert "mucum" in indice["cidades"]
    assert (ROOT / "assets/data/mucum_contingencia_202607.json").is_file()


if __name__ == "__main__":
    for fn in (
        test_centro_resposta_gaps_updated,
        test_bacia_dashboard_exposure_layer,
        test_resposta_operacional_exports,
        test_ficha_jusante_proxy,
        test_exposure_files_present,
    ):
        fn()
    print("RESPOSTA_MELHORIAS_QA_OK")
