"""QA dos cinco entregáveis operacionais (plantão ST, exposição, validação, ginásio, SGB×HAND)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_st_plantao_assets() -> None:
    html = (ROOT / "pesquisas" / "estudo-caso-resposta-santa-tereza.html").read_text(encoding="utf-8")
    js = (ROOT / "assets/js/mesa_st_plantao.js").read_text(encoding="utf-8")
    assert "mesa_st_plantao.js" in html
    assert "Plantão · feed ao vivo" in html
    assert "fetch(" not in html
    assert "fetchLive" in js
    assert "PREVINE_MESA_ST" in js
    assert "PREVINE_RESPOSTA" in js


def test_grade_exposta_geojson() -> None:
    for key, pop_min in (("mucum", 2000), ("santa_tereza", 300)):
        path = ROOT / "assets/data/exposicao_cruzada" / f"grade_exposta_{key}.geojson"
        data = load(path)
        assert data["type"] == "FeatureCollection"
        assert data["metadata"]["celulas"] == len(data["features"])
        assert data["metadata"]["pop"] >= pop_min


def test_validacao_eventos() -> None:
    rel = load(ROOT / "assets/data/validacao_eventos/relatorio_2023_2024.json")
    assert rel["schema_version"] == 1
    assert len(rel["eventos"]) >= 3
    ids = {e["id"] for e in rel["eventos"]}
    assert "st-set-2023" in ids and "st-mai-2024" in ids
    for ev in rel["eventos"]:
        assert ev["taxa_concordancia_pct"] is not None


def test_ginasio_reconciliado() -> None:
    contract = load(ROOT / "assets/data/estudo_caso_resposta_v002.json")
    route = load(ROOT / "assets/data/rota_fuga_santa_tereza_cenario.json")
    shelter = load(ROOT / "assets/data/servicos/abrigos.geojson")["features"][0]
    ps = route["meta"]["ponto_seguro"]
    assert contract["shelter"]["route_reference"]["status"] == "reconciled_abrigos_geojson"
    assert abs(ps["lat"] - (-29.168793)) < 0.0001
    assert abs(ps["lon"] - (-51.7327164)) < 0.0001
    assert ps["confirmado"] is True


def test_sgb_hand_cruzamento() -> None:
    data = load(ROOT / "assets/data/vulnerabilidade/perigo/sgb_hand_cruzamento_st.json")
    geo = load(ROOT / "assets/data/vulnerabilidade/perigo/sgb_hand_cruzamento_st.geojson")
    assert data["totais"]["setores"] == 37
    assert len(geo["features"]) == 37
    assert any(s["inundacao"] for s in data["setores"])


def test_vulnerabilidade_exposicao_ui() -> None:
    html = (ROOT / "vulnerabilidade.html").read_text(encoding="utf-8")
    assert 'id="exposicao"' in html
    assert "grade_exposta_" in html
    assert "Exposição HAND" in html


if __name__ == "__main__":
    for fn in (
        test_st_plantao_assets,
        test_grade_exposta_geojson,
        test_validacao_eventos,
        test_ginasio_reconciliado,
        test_sgb_hand_cruzamento,
        test_vulnerabilidade_exposicao_ui,
    ):
        fn()
    print("RESPOSTA_TODOS_QA_OK")
