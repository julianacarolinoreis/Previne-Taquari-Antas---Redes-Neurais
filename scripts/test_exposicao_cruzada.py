"""QA do produto de exposição cruzada e contrato Muçum V002."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP_MUC = ROOT / "assets" / "data" / "exposicao_cruzada" / "exposicao_mucum.json"
CONTRACT = ROOT / "assets" / "data" / "estudo_caso_resposta_mucum_v002.json"
CONTOURS = ROOT / "assets" / "data" / "mucum_inundacao" / "contornos_mancha.json"
MESA = ROOT / "pesquisas" / "estudo-caso-resposta-mucum.html"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_exposicao_mucum_structure() -> None:
    data = load(EXP_MUC)
    assert data["schema_version"] == 1
    assert data["cod_ibge"] == "4312609"
    assert len(data["niveis"]) >= 6
    peak = next(n for n in data["niveis"] if abs(n["hand_m"] - 17.02) < 0.01)
    assert peak["grade_200m"]["pop"] > 1000
    assert peak["pct_pop_municipio"] > 40
    assert "metodo" in data and "centroide" in data["metodo"]["criterio"].lower()


def test_contornos_extendidos_25m() -> None:
    contours = load(CONTOURS)
    levels = {f["properties"]["nivel_m"] for f in contours["features"]}
    assert 17.0 in levels
    assert 25.0 in levels
    assert max(contours["metadata"]["niveis_m"]) == 25.0


def test_mucum_v002_contract() -> None:
    c = load(CONTRACT)
    assert c["schema_version"] == 2
    assert c["artifact_id"] == "muc-response-exercise-v002"
    assert len(c["zones"]) == 4
    assert c["spatial"]["hand_contours_max_m"] == 25.0
    assert c["spatial"]["exposure_at_peak"]["pop_grade"] == 2117
    for src in c["sources"]:
        assert (ROOT / src["path"]).is_file(), src["path"]


def test_mesa_page_references_v002() -> None:
    html = MESA.read_text(encoding="utf-8")
    assert "estudo_caso_resposta_mucum_v002.json" in html
    assert "mesa_mucum_v002.js" in html
    assert "Plantão" in html
    assert "Scoreboard" in html
    assert "export-unified" in html
    assert "sombra" in html


if __name__ == "__main__":
    for fn in (
        test_exposicao_mucum_structure,
        test_contornos_extendidos_25m,
        test_mucum_v002_contract,
        test_mesa_page_references_v002,
    ):
        fn()
    print("EXPOSICAO_CRUZADA_QA_OK")
