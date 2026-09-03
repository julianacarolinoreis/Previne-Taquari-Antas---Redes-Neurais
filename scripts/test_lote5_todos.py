"""QA lote 5 — redirect rota, abrigo ST, campo sync, datum, grade v2, combo."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_rota_fuga_redirect() -> None:
    html = (ROOT / "pesquisas/santa-tereza-rota-fuga.html").read_text(encoding="utf-8")
    assert "santa-tereza-rota-fuga-ruas.html" in html
    assert len(html) < 2000
    assert "Leaflet" not in html


def test_st_mesa_abrigo_form() -> None:
    html = (ROOT / "pesquisas/estudo-caso-resposta-santa-tereza.html").read_text(encoding="utf-8")
    assert "abrigo_capacidade_form.js" in html
    assert "abrigo-capacidade-mount" in html


def test_modo_campo_sync() -> None:
    js = (ROOT / "assets/js/resposta_operacional.js").read_text(encoding="utf-8")
    assert "syncFieldChecklist" in js
    campo = (ROOT / "pesquisas/modo-campo.html").read_text(encoding="utf-8")
    assert "syncFieldChecklist" in campo


def test_datum_cadeia() -> None:
    idx = json.loads((ROOT / "assets/data/datum_cadeia/indice.json").read_text(encoding="utf-8"))
    assert len(idx["estacoes"]) == 2
    page = (ROOT / "pesquisas/datum-cadeia.html").read_text(encoding="utf-8")
    assert "datum_cadeia/indice.json" in page


def test_grade_exposta_v2_geojson() -> None:
    for key in ("mucum", "santa_tereza"):
        gj = json.loads((ROOT / "assets/data/exposicao_cruzada" / f"grade_exposta_{key}_v2.geojson").read_text())
        assert gj["metadata"]["schema_version"] == 2
        assert gj["metadata"]["celulas"] >= 30
    muc = json.loads((ROOT / "assets/data/exposicao_cruzada/grade_exposta_mucum_v2.geojson").read_text())
    assert muc["metadata"]["pop"] == 2070


def test_st_contingency_combo() -> None:
    html = (ROOT / "pesquisas/estudo-caso-resposta-santa-tereza.html").read_text(encoding="utf-8")
    assert 'value="combo"' in html
    assert "contingencyIsForZone" in html


def test_vulnerabilidade_v2_layer() -> None:
    html = (ROOT / "vulnerabilidade.html").read_text(encoding="utf-8")
    assert "Exposição v2 · areal" in html
    assert "grade_exposta_${key}_v2.geojson" in html or "grade_exposta_" in html and "_v2.geojson" in html


if __name__ == "__main__":
    for fn in (
        test_rota_fuga_redirect,
        test_st_mesa_abrigo_form,
        test_modo_campo_sync,
        test_datum_cadeia,
        test_grade_exposta_v2_geojson,
        test_st_contingency_combo,
        test_vulnerabilidade_v2_layer,
    ):
        fn()
    print("LOTE5_QA_OK")
