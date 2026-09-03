"""QA lote 6 — paridade ST/Muçum: checklist, contingência, exposição v2, pontes, live-status."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mucum_mesa_contingency_combo() -> None:
    html = (ROOT / "pesquisas/estudo-caso-resposta-mucum.html").read_text(encoding="utf-8")
    js = (ROOT / "assets/js/mesa_mucum_v002.js").read_text(encoding="utf-8")
    assert 'value="combo"' in html
    assert "contingencyIs" in js
    assert "initContingency" in js


def test_mucum_checklist_sync_mesa_key() -> None:
    html = (ROOT / "pesquisas/estudo-caso-resposta-mucum.html").read_text(encoding="utf-8")
    assert "syncMesaValidation(R.MUC_MESA_KEY" in html
    assert "saveChecklist(s)" not in html


def test_fetch_exposure_peak_v2() -> None:
    js = (ROOT / "assets/js/resposta_operacional.js").read_text(encoding="utf-8")
    assert "exposicao_mucum_v2.json" in js
    assert "exposicao_santa_tereza_v2.json" in js


def test_export_decision_csv_mucum_mesa() -> None:
    js = (ROOT / "assets/js/resposta_operacional.js").read_text(encoding="utf-8")
    assert "MUC_MESA_KEY" in js
    assert "mesa_key" in js


def test_mucum_cenario_bridge_unknown() -> None:
    html = (ROOT / "pesquisas/mucum-rota-fuga-ruas-cenario.html").read_text(encoding="utf-8")
    assert "bridgeLayer" in html
    assert "MUC_PONTES_UNKNOWN" in html
    assert "UNKNOWN" in html


def test_mucum_previsao_live_status_note() -> None:
    html = (ROOT / "mucum_previsao_inundacao.html").read_text(encoding="utf-8")
    assert "live-status-note" in html
    assert "renderLiveStatus" in html


def test_mucum_contract_v2_exposure() -> None:
    contract = json.loads(
        (ROOT / "assets/data/estudo_caso_resposta_mucum_v002.json").read_text(encoding="utf-8")
    )
    assert "v2" in contract["spatial"]["source"]
    assert contract["spatial"]["exposure_at_peak"]["pop_grade"] == 2070


def test_stale_links_fixed() -> None:
    status = (ROOT / "pesquisa_status_mucum.html").read_text(encoding="utf-8")
    briefing = (ROOT / "pesquisas/briefing-gestores.html").read_text(encoding="utf-8")
    assert "Mesa V002" in status
    assert "Mesa V001" not in status
    assert "estudo-caso-resposta-mucum.html" in briefing


def test_sw_v8() -> None:
    sw = (ROOT / "sw.js").read_text(encoding="utf-8")
    assert "previne-resposta-v8" in sw


if __name__ == "__main__":
    for fn in (
        test_mucum_mesa_contingency_combo,
        test_mucum_checklist_sync_mesa_key,
        test_fetch_exposure_peak_v2,
        test_export_decision_csv_mucum_mesa,
        test_mucum_cenario_bridge_unknown,
        test_mucum_previsao_live_status_note,
        test_mucum_contract_v2_exposure,
        test_stale_links_fixed,
        test_sw_v8,
    ):
        fn()
    print("LOTE6_QA_OK")
