#!/usr/bin/env python3
"""Valida o contrato mínimo dos dados e da página de vulnerabilidade.

Este teste é deliberadamente independente dos geradores: ele verifica os
artefatos publicados, os vínculos entre municípios/setores/grade e os
controles essenciais da interface. Falha cedo para evitar uma publicação
parcial no GitHub Pages.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from html.parser import HTMLParser
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
VULN = ROOT / "assets" / "data" / "vulnerabilidade"
DOWNLOADS = VULN / "downloads"


def read_json(path: Path):
    # A publicação precisa ser UTF-8; não aceitar o fallback do Windows aqui.
    return json.loads(path.read_text(encoding="utf-8"))


def feature_collection(path: Path) -> list[dict]:
    value = read_json(path)
    assert value.get("type") == "FeatureCollection", f"{path}: não é FeatureCollection"
    features = value.get("features")
    assert isinstance(features, list), f"{path}: features inválido"
    return features


def walk_coordinates(value):
    if isinstance(value, (list, tuple)):
        if len(value) >= 2 and all(isinstance(x, (int, float)) for x in value[:2]):
            yield float(value[0]), float(value[1])
        else:
            for child in value:
                yield from walk_coordinates(child)


def validate_geometry(feature: dict, path: Path) -> None:
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates")
    assert coords is not None, f"{path}: geometria sem coordinates"
    for lon, lat in walk_coordinates(coords):
        assert -180 <= lon <= 180 and -90 <= lat <= 90, f"{path}: coordenada inválida"


class IDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("href"):
            self.hrefs.append(attrs["href"])


def main() -> int:
    municipios = feature_collection(VULN / "municipios.geojson")
    raw_codes = [f.get("properties", {}).get("cod_mun") for f in municipios]
    assert all(code not in (None, "") for code in raw_codes), "cod_mun municipal ausente"
    codes = {str(code) for code in raw_codes}
    assert len(codes) == len(municipios), "cod_mun municipal duplicado"
    assert len(codes) == 118, f"cobertura municipal inesperada: {len(codes)}"
    for feature in municipios:
        validate_geometry(feature, VULN / "municipios.geojson")
        assert "dens_bacia" in feature.get("properties", {}), "dens_bacia municipal ausente"

    for kind in ("setores", "grade"):
        files = {p.stem for p in (VULN / kind).glob("*.geojson")}
        assert files == codes, f"{kind}: arquivos divergem da malha municipal"
        for code in files:
            features = feature_collection(VULN / kind / f"{code}.geojson")
            assert features, f"{kind}/{code}: camada vazia"
            for feature in features:
                validate_geometry(feature, VULN / kind / f"{code}.geojson")
                props = feature.get("properties", {})
                assert "area_pct_bacia" in props, f"{kind}/{code}: area_pct_bacia ausente"
                assert 0 <= float(props["area_pct_bacia"] or 0) <= 100, f"{kind}/{code}: area_pct_bacia inválida"

    combined = feature_collection(DOWNLOADS / "setores_na_bacia_combinados.geojson")
    assert combined, "setores combinados vazio"
    assert all(f.get("properties", {}).get("na_bacia") == 1 for f in combined), "recorte setorial fora da bacia"
    assert all("area_pct_bacia" in f.get("properties", {}) for f in combined), "area_pct_bacia ausente no combinado"

    catalog = read_json(DOWNLOADS / "catalogo.json")
    assert catalog.get("crs_geojson") == "EPSG:4326", "CRS GeoJSON inesperado"
    assert catalog.get("contagens", {}).get("municipios") == len(codes), "catálogo municipal divergente"
    assert catalog.get("qualidade", {}).get("arquivos_setor_iguais_aos_municipios") is True
    assert catalog.get("qualidade", {}).get("arquivos_grade_iguais_aos_municipios") is True

    # Contrato de codificação dos ativos consumidos por terceiros.
    read_json(VULN / "indicadores_municipios.json")
    servicos = read_json(ROOT / "assets" / "data" / "servicos" / "contagem_municipios.json")
    assert servicos.get("gerado_em_utc"), "contagem de serviços sem data de captura do pacote"

    gpkg_zip = DOWNLOADS / "geopackage_arcgis_qgis.zip"
    with ZipFile(gpkg_zip) as archive:
        gpkg_names = [name for name in archive.namelist() if name.endswith(".gpkg")]
        assert len(gpkg_names) == 1, "GeoPackage ausente ou duplicado no ZIP"
        with archive.open(gpkg_names[0]) as src:
            temp = DOWNLOADS / ".validate_previne.gpkg"
            temp.write_bytes(src.read())
    try:
        conn = sqlite3.connect(temp)
        try:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "GeoPackage inválido"
            layers = {row[0] for row in conn.execute("SELECT table_name FROM gpkg_contents")}
        finally:
            conn.close()
        assert layers, "GeoPackage sem camadas"
    finally:
        temp.unlink(missing_ok=True)

    html = (ROOT / "vulnerabilidade.html").read_text(encoding="utf-8")
    parser = IDs()
    parser.feed(html)
    required_ids = {
        "map", "leg", "comparacaoTitulo", "comparacaoBody", "comparacaoBaixar",
        "selectionPanel", "printDialog", "downloadMeta", "escopos", "triagem",
        "proveniencia", "atalhoTabela",
    }
    missing = required_ids - parser.ids
    assert not missing, f"IDs essenciais ausentes: {sorted(missing)}"
    local_links = [h.split("#", 1)[0].split("?", 1)[0] for h in parser.hrefs if h.startswith("assets/")]
    missing_links = [h for h in local_links if not (ROOT / h).exists()]
    assert not missing_links, f"links locais quebrados: {missing_links}"
    # O mesmo pacote pode aparecer uma vez no centro de downloads e outra na
    # documentação; o teste acima verifica que toda ocorrência aponta para um
    # arquivo existente, enquanto a revisão editorial trata rótulos duplicados.
    assert "unpkg.com" in html and "integrity=" in html, "Leaflet sem SRI declarado"

    print(json.dumps({
        "municipios": len(codes),
        "setores_na_bacia": len(combined),
        "gpkg_camadas": len(layers),
        "html_ids": len(parser.ids),
        "status": "OK",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"VALIDACAO_VULNERABILIDADE_FALHOU: {exc}", file=sys.stderr)
        raise SystemExit(1)
