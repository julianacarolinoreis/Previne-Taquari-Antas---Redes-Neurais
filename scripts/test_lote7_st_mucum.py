"""QA lote 7 — grade v2 overlay, export campo, exposição v2 mesa ST."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_exposicao_overlay_module() -> None:
    js = (ROOT / "assets/js/exposicao_grade_overlay.js").read_text(encoding="utf-8")
    assert "PREVINE_EXPOSICAO_OVERLAY" in js
    assert "grade_exposta_mucum_v2.geojson" in js
    assert "grade_exposta_santa_tereza_v2.geojson" in js


def test_previsao_maps_wire_overlay() -> None:
    muc = (ROOT / "mucum_previsao_inundacao.html").read_text(encoding="utf-8")
    st = (ROOT / "santa_tereza_previsao_inundacao.html").read_text(encoding="utf-8")
    for html in (muc, st):
        assert "exposicao_grade_overlay.js" in html
        assert "PREVINE_EXPOSICAO_OVERLAY.mount" in html


def test_field_validation_export_api() -> None:
    js = (ROOT / "assets/js/resposta_operacional.js").read_text(encoding="utf-8")
    assert "buildFieldValidationPayload" in js
    assert "exportFieldValidationCsv" in js
    assert "syncRotaFieldChecks" in js


def test_rotas_field_export_parity() -> None:
    muc = (ROOT / "pesquisas/mucum-rota-fuga-ruas.html").read_text(encoding="utf-8")
    st = (ROOT / "pesquisas/santa-tereza-rota-fuga-ruas.html").read_text(encoding="utf-8")
    assert "buildFieldValidationPayload" in muc
    assert "buildFieldValidationPayload" in st
    assert "syncRotaFieldChecks" in muc
    assert "syncRotaFieldChecks" in st
    assert "fieldChecksBox" in st
    assert "field_checks" in muc or "fieldChecks" in muc


def test_st_mesa_exposure_compare() -> None:
    html = (ROOT / "pesquisas/estudo-caso-resposta-santa-tereza.html").read_text(encoding="utf-8")
    assert "exp-v1-pop" in html
    assert "exp-v2-pop" in html
    assert "exposicao_santa_tereza_v2.json" in html


def test_modo_campo_exposure_both() -> None:
    html = (ROOT / "pesquisas/modo-campo.html").read_text(encoding="utf-8")
    assert "R.fetchExposurePeak(current)" in html


def test_sw_v8() -> None:
    sw = (ROOT / "sw.js").read_text(encoding="utf-8")
    assert "previne-resposta-v8" in sw


if __name__ == "__main__":
    for fn in (
        test_exposicao_overlay_module,
        test_previsao_maps_wire_overlay,
        test_field_validation_export_api,
        test_rotas_field_export_parity,
        test_st_mesa_exposure_compare,
        test_modo_campo_exposure_both,
        test_sw_v8,
    ):
        fn()
    print("LOTE7_QA_OK")
