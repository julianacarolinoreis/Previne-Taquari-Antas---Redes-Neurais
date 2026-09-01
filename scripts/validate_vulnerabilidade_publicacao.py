#!/usr/bin/env python3
"""Valida o contrato mínimo dos dados e da página de vulnerabilidade.

Este teste é deliberadamente independente dos geradores: ele verifica os
artefatos publicados, os vínculos entre municípios/setores/grade e os
controles essenciais da interface. Falha cedo para evitar uma publicação
parcial no GitHub Pages.
"""

from __future__ import annotations

import json
import csv
import math
import re
import sqlite3
import sys
from html.parser import HTMLParser
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
VULN = ROOT / "assets" / "data" / "vulnerabilidade"
DOWNLOADS = VULN / "downloads"
FALLBACK_MANIFEST = VULN / "fallback-manifest.json"
TRIAGE_SPEC = VULN / "metadados" / "ESPECIFICACAO_FICHA_TRIAGEM_CENARIOS.json"
REFERENCIAS = VULN / "referencias"


def read_json(path: Path):
    # A publicação precisa ser UTF-8; não aceitar o fallback do Windows aqui.
    return json.loads(path.read_text(encoding="utf-8"))


def csv_rows(path: Path):
    """Return a CSV header and rows without normalising unknown/blank values."""
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        assert reader.fieldnames, f"{path}: CSV sem cabeÃ§alho"
        return list(reader.fieldnames), list(reader)


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


INDICADORES_COMPLETUDE = (
    "pop", "dom", "dom_ocupados", "mulheres", "c0_4", "c5_9", "i60_69",
    "i70m", "indigenas", "pretos_pardos", "dom_agua", "dom_esgoto",
    "n_resp", "renda_resp", "dens",
)


def validate_recorte_e_completude(props: dict, contexto: str) -> None:
    """Exige metadados que impedem leitura de borda/parcial como completo."""
    assert "area_pct_bacia" in props, f"{contexto}: area_pct_bacia ausente"
    area = float(props.get("area_pct_bacia") or 0)
    assert 0 <= area <= 100, f"{contexto}: area_pct_bacia inválida"
    assert props.get("status_borda_bacia") in {"total", "parcial"}, f"{contexto}: status_borda_bacia inválido"
    assert props.get("metodo_area_bacia"), f"{contexto}: metodo_area_bacia ausente"
    assert props.get("metodo_na_bacia"), f"{contexto}: metodo_na_bacia ausente"
    esperado = "parcial" if 0 < area < 100 else "total"
    assert props["status_borda_bacia"] == esperado, f"{contexto}: status de borda incoerente"
    for campo in INDICADORES_COMPLETUDE:
        if campo not in props:
            continue
        trio = [f"{campo}_n_validos", f"{campo}_n_total", f"{campo}_completude"]
        assert all(k in props for k in trio), f"{contexto}/{campo}: metadados de completude ausentes"
        n_validos, n_total = int(props[trio[0]] or 0), int(props[trio[1]] or 0)
        completude = float(props[trio[2]] or 0)
        assert 0 <= n_validos <= n_total, f"{contexto}/{campo}: n_validos/n_total inválidos"
        assert 0 <= completude <= 1, f"{contexto}/{campo}: completude inválida"
        esperado_comp = round(n_validos / n_total, 6) if n_total else 0.0
        assert abs(completude - esperado_comp) <= 1e-6, f"{contexto}/{campo}: completude incoerente"


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
        props = feature.get("properties", {})
        assert "dens_bacia" in props, "dens_bacia municipal ausente"
        validate_recorte_e_completude(props, "municipio")
        # No grão municipal, completude é calculada sobre todos os setores
        # do município. Impede que uma anotação de feição (1/1) mascare o
        # denominador real, sobretudo nos municípios de borda sem setor na
        # bacia.
        n_setores = int(props.get("n_setores_municipio") or 0)
        if n_setores:
            for campo in INDICADORES_COMPLETUDE:
                chave = f"{campo}_n_total"
                if chave in props:
                    assert int(props[chave] or 0) == n_setores, (
                        f"municipio/{props.get('cod_mun')}/{campo}: "
                        f"n_total deve ser n_setores_municipio ({n_setores})"
                    )

    for kind in ("setores", "grade"):
        files = {p.stem for p in (VULN / kind).glob("*.geojson")}
        assert files == codes, f"{kind}: arquivos divergem da malha municipal"
        for code in files:
            features = feature_collection(VULN / kind / f"{code}.geojson")
            assert features, f"{kind}/{code}: camada vazia"
            for feature in features:
                validate_geometry(feature, VULN / kind / f"{code}.geojson")
                props = feature.get("properties", {})
                validate_recorte_e_completude(props, f"{kind}/{code}")
                assert 0 <= float(props["area_pct_bacia"] or 0) <= 100, f"{kind}/{code}: area_pct_bacia inválida"

    catalog = read_json(DOWNLOADS / "catalogo.json")
    combined = feature_collection(DOWNLOADS / "setores_na_bacia_combinados.geojson")
    assert combined, "setores combinados vazio"
    assert all(f.get("properties", {}).get("na_bacia") == 1 for f in combined), "recorte setorial fora da bacia"
    for i, feature in enumerate(combined):
        validate_recorte_e_completude(feature.get("properties", {}), f"setores_na_bacia_combinados/{i}")
    assert all("area_pct_bacia" in f.get("properties", {}) for f in combined), "area_pct_bacia ausente no combinado"
    # A camada completa é publicada para auditoria de borda no QGIS/ArcGIS;
    # ela deve conter exatamente os setores dos 118 municípios intersectantes,
    # inclusive os que ficam fora do recorte por ponto representativo.
    combined_all = feature_collection(DOWNLOADS / "setores_municipios_intersectantes_combinados.geojson")
    assert len(combined_all) == int(catalog.get("contagens", {}).get("setores_municipios_intersectantes", 0)), (
        "camada completa de setores divergente do catálogo"
    )
    assert {f.get("properties", {}).get("na_bacia") for f in combined_all} <= {0, 1}, (
        "setores completos sem na_bacia binário"
    )

    assert catalog.get("crs_geojson") == "EPSG:4326", "CRS GeoJSON inesperado"
    assert catalog.get("contagens", {}).get("municipios") == len(codes), "catálogo municipal divergente"
    assert catalog.get("qualidade", {}).get("arquivos_setor_iguais_aos_municipios") is True
    assert catalog.get("qualidade", {}).get("arquivos_grade_iguais_aos_municipios") is True

    # The cross-origin fallback must point at the validated snapshot, not the
    # mutable ``main`` branch. Keep the decision auditable in a manifest.
    fallback = read_json(FALLBACK_MANIFEST)
    commit = str(fallback.get("commit", ""))
    assert re.fullmatch(r"[0-9a-f]{40}", commit), "fallback sem SHA de commit"
    assert fallback.get("repository") == "julianacarolinoreis/Previne-Taquari-Antas---Redes-Neurais"
    assert fallback.get("path") == "assets/data/vulnerabilidade"
    fallback_url = str(fallback.get("url", ""))
    assert fallback_url.endswith(f"/{commit}/assets/data/vulnerabilidade")

    # Contrato de codificação dos ativos consumidos por terceiros.
    read_json(VULN / "indicadores_municipios.json")
    # Agregados municipais oficiais recuperados a partir do Censo/SIDRA. Eles
    # são publicados como arquivos separados e nunca substituem os campos
    # setoriais *_bacia da camada principal.
    agregados_json = read_json(REFERENCIAS / "agregados_taquari_indicadores.json")
    agregados_rows = agregados_json.get("municipios", [])
    assert len(agregados_rows) == len(codes), "agregados normalizados sem os 118 municípios"
    assert {str(row.get("cod_mun")) for row in agregados_rows} == codes, "agregados com códigos municipais divergentes"
    assert (REFERENCIAS / "README_AGREGADOS_TAQUARI.md").read_text(encoding="utf-8").strip()
    dict_path = REFERENCIAS / "DICIONARIO_AGREGADOS_TAQUARI.csv"
    dict_fields, dict_rows = csv_rows(dict_path)
    assert {"campo", "unidade", "universo", "fonte", "observacao"} <= set(dict_fields)
    assert len(dict_rows) >= 30, "dicionário dos agregados incompleto"
    aggregate_csvs = {
        DOWNLOADS / "Agregados_taquari_pessoa.csv",
        DOWNLOADS / "Agregados_taquari_domicilio.csv",
        DOWNLOADS / "Agregados_taquari_entorno.csv",
        DOWNLOADS / "Agregados_taquari_PCD_TEA_municipio.csv",
    }
    for path in aggregate_csvs:
        fields, rows = csv_rows(path)
        assert len(rows) == len(codes), f"{path}: esperado um registro por município"
        assert len(fields) == len(set(fields)), f"{path}: cabeçalhos duplicados"
        assert {str(row.get("CD_MUN")) for row in rows} == codes, f"{path}: códigos divergentes"
    pcd_rows = {str(row["CD_MUN"]): row for row in csv_rows(DOWNLOADS / "Agregados_taquari_PCD_TEA_municipio.csv")[1]}
    for row in agregados_rows:
        for key in ("pcd_pct_2mais", "tea_pct"):
            value = row.get(key)
            assert value is None or 0 <= float(value) <= 100, f"agregado/{row.get('cod_mun')}/{key}: percentual inválido"
        for key in ("pcd_pessoas_2mais", "tea_pessoas", "dom_improvisados", "dom_coletivos_com_morador"):
            value = row.get(key)
            assert value is None or float(value) >= 0, f"agregado/{row.get('cod_mun')}/{key}: contagem negativa"
    assert pcd_rows["4312351"]["tea_pessoas"] == "", "TEA ausente deve permanecer vazio, não zero"
    municipal_fields, municipal_rows = csv_rows(DOWNLOADS / "municipios_combinados.csv")
    municipal_by_code = {str(row["cod_mun"]): row for row in municipal_rows}
    assert set(municipal_by_code) == codes, "municípios combinados sem a chave municipal completa"
    for key in ("mulheres", "indigenas", "pretos_pardos", "entorno_faces_total", "entorno_moradores_total"):
        alias = f"mun_{key}"
        assert alias in municipal_fields, f"alias oficial ausente no GIS: {alias}"
        for row in agregados_rows:
            expected = row.get(key)
            actual = municipal_by_code[str(row["cod_mun"])].get(alias, "")
            if expected is None:
                assert actual in {"", "None", "null"}, f"alias {alias} deveria permanecer vazio"
            else:
                assert abs(float(actual) - float(expected)) < 1e-9, f"alias {alias} divergente em {row['cod_mun']}"
    servicos = read_json(ROOT / "assets" / "data" / "servicos" / "contagem_municipios.json")
    assert servicos.get("gerado_em_utc"), "contagem de serviços sem data de captura do pacote"

    # IEDE is a partial register: a missing field means UNKNOWN, never zero.
    service_catalog = catalog.get("cobertura_servicos", {})
    service_rows = servicos.get("municipios", [])
    service_codes = [str(row.get("cod_mun")) for row in service_rows]
    assert len(service_codes) == len(set(service_codes)) == len(codes), "contagem IEDE sem os 118 municípios"
    for kind in ("ubs", "escolas", "hospitais", "bombeiros"):
        unknown = [row for row in service_rows if row.get(f"{kind}_status") == "unknown" and row.get(kind) is None]
        known = [row for row in service_rows if row.get(f"{kind}_status") == "published" and row.get(kind) is not None]
        meta = service_catalog.get(kind, {})
        assert meta.get("status") == "cadastro_IEDE_parcial_nao_inventario", f"IEDE {kind}: status sem UNKNOWN"
        assert len(unknown) == meta.get("municipios_sem_ponto_publicado", meta.get("municipios_sem_ponto_na_camada")), f"IEDE {kind}: desconhecidos divergentes"
        assert len(known) == meta.get("municipios_com_ponto"), f"IEDE {kind}: cobertura divergente"
        assert sum(float(row[kind]) for row in known) == meta.get("pontos_publicados"), f"IEDE {kind}: pontos divergentes"
        assert all(float(row[kind]) >= 0 and math.isfinite(float(row[kind])) for row in known)
        assert all(row.get(f"{kind}_status") in {"published", "unknown"} for row in service_rows)

    # Published completeness must reconcile totals, suppression and valid
    # records. Nulls may overlap suppression, so they are not summed twice.
    expected_totals = {"municipios_agregados": len(codes), "setores_na_bacia": len(combined)}
    for scope, fields in catalog.get("completude", {}).items():
        if scope not in expected_totals:
            continue
        total_esperado = expected_totals[scope]
        assert isinstance(fields, dict) and fields, f"completude {scope} vazia"
        for campo, stats in fields.items():
            total = int(stats.get("registros_total", -1))
            validos = int(stats.get("registros_validos", -1))
            sigilo = int(stats.get("registros_sigilo", -1))
            nulos = int(stats.get("registros_nulos", -1))
            assert total == total_esperado, f"completude {scope}/{campo}: total divergente"
            assert 0 <= validos <= total and 0 <= sigilo <= total and 0 <= nulos <= total
            assert math.isclose(float(stats.get("completude", -1)), validos / total, rel_tol=0, abs_tol=2e-6)

    gpkg_zip = DOWNLOADS / "geopackage_arcgis_qgis.zip"
    with ZipFile(DOWNLOADS / "dados_combinados_taquari_antas.zip") as archive:
        assert "setores_municipios_intersectantes_combinados.geojson" in archive.namelist(), (
            "pacote combinado sem camada completa de setores"
        )
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
        assert "setores_municipios_intersectantes_combinados" in layers, (
            "GeoPackage sem camada completa de setores para auditoria de borda"
        )
    finally:
        temp.unlink(missing_ok=True)

    html = (ROOT / "vulnerabilidade.html").read_text(encoding="utf-8")
    parser = IDs()
    parser.feed(html)
    required_ids = {
        "map", "leg", "comparacaoTitulo", "comparacaoBody", "comparacaoBaixar",
        "selectionPanel", "printDialog", "downloadMeta", "escopos", "triagem",
        "proveniencia", "atalhoTabela", "locationPicker", "startHere",
        "startHereState", "startHereNote",
        "downloadVistaMeta",
    }
    missing = required_ids - parser.ids
    assert not missing, f"IDs essenciais ausentes: {sorted(missing)}"
    local_links = [h.split("#", 1)[0].split("?", 1)[0] for h in parser.hrefs if h.startswith("assets/")]
    missing_links = [h for h in local_links if not (ROOT / h).exists()]
    assert not missing_links, f"links locais quebrados: {missing_links}"

    # As novas camadas de referência são leves e precisam permanecer
    # publicáveis mesmo quando as fontes online estiverem indisponíveis.
    resiliencia = read_json(REFERENCIAS / "resiliencia_municipios.json")
    assert resiliencia.get("municipios_fonte") == 264, "snapshot do Observatório sem cobertura declarada"
    irm_rows = resiliencia.get("features", [])
    assert len(irm_rows) == len(codes), "IRM sem um registro por município candidato"
    assert {"cod_mun", "irm_faixa", "irm_status", "irm_score_0a100"} <= set(irm_rows[0]), "campos IRM ausentes"
    tiles = feature_collection(REFERENCIAS / "open_buildings_tiles.geojson")
    assert tiles and all((f.get("properties") or {}).get("tile_url") for f in tiles), "índice Open Buildings sem URLs"
    obitos = feature_collection(REFERENCIAS / "obitos.geojson")
    assert len(obitos) == 179, "Óbitos: quantidade de pontos válidos divergente"
    for feature in obitos:
        validate_geometry(feature, REFERENCIAS / "obitos.geojson")
        props = feature.get("properties") or {}
        assert {"registro_id", "latitude", "longitude", "na_bacia_publicada"} <= set(props), "Óbitos: campos mínimos ausentes"
        assert props["na_bacia_publicada"] in {0, 1}, "Óbitos: recorte inválido"
    obitos_meta = read_json(REFERENCIAS / "obitos_metadata.json")
    assert obitos_meta.get("registros_fonte") == 185, "Óbitos: total de origem divergente"
    assert obitos_meta.get("coordenadas_validas_publicadas") == len(obitos), "Óbitos: metadados de coordenadas divergentes"
    assert obitos_meta.get("registros_sem_coordenada") == 6, "Óbitos: registros sem coordenada divergentes"
    assert (REFERENCIAS / "README.md").read_text(encoding="utf-8").strip(), "README das referências vazio"
    assert "Estradas DAER/RS" in html and "Open Buildings" in html and "Óbitos" in html and "Resiliência" in html, "novas referências não declaradas na página"
    assert "Agregados_taquari_PCD_TEA_municipio.csv" in html and "agregados_taquari_indicadores.json" in html, "agregados oficiais não declarados na página"

    # Export contracts carry enough provenance to be usable outside the map;
    # keep the triage metadata/specification alongside the CSVs.
    csv_contracts = {
        DOWNLOADS / "municipios_combinados.csv": ({"cod_mun", "metodo_recorte_bacia", "pop_bacia_completude", "pop_n_validos", "pop_n_total", "status_borda_bacia", "metodo_area_bacia", "metodo_na_bacia"}, len(codes)),
        DOWNLOADS / "setores_na_bacia_combinados.csv": ({"setor", "na_bacia", "area_pct_bacia", "sigilo_pop", "pop_n_validos", "pop_n_total", "pop_completude", "status_borda_bacia", "metodo_area_bacia", "metodo_na_bacia"}, len(combined)),
        DOWNLOADS / "grade_200m_na_bacia_combinada.csv": ({"area_pct_bacia", "na_bacia", "pop_n_validos", "pop_n_total", "pop_completude", "status_borda_bacia", "metodo_area_bacia", "metodo_na_bacia"}, catalog.get("contagens", {}).get("celulas_grade_na_bacia")),
    }
    for path, (required_columns, expected_rows) in csv_contracts.items():
        columns, rows = csv_rows(path)
        assert len(columns) == len(set(columns)), f"{path}: cabeÃ§alhos duplicados"
        assert required_columns <= set(columns), f"{path}: metadados/campos ausentes"
        assert len(rows) == expected_rows, f"{path}: nÃºmero de linhas divergente"

    triage = read_json(TRIAGE_SPEC)
    assert triage.get("source_catalog") == "assets/data/vulnerabilidade/downloads/catalogo.json"
    triage_columns = set(triage.get("triagem", {}).get("required_output_columns", []))
    assert {"status_dado", "service_coverage_status", "rule_version"} <= triage_columns
    triage_statuses = set(triage.get("triagem", {}).get("status_dado_values", []))
    assert {"publicado", "suprimido", "sem_ponto_publicado", "fora_cobertura"} <= triage_statuses
    assert any("fora_cobertura" in guard and "zero" in guard for guard in triage.get("triagem", {}).get("guardrails", []))

    # The combined ZIP must expose the same export and provenance contract.
    with ZipFile(DOWNLOADS / "dados_combinados_taquari_antas.zip") as archive:
        names = set(archive.namelist())
        for required in (
            "municipios_combinados.csv",
            "setores_na_bacia_combinados.csv",
            "grade_200m_na_bacia_combinada.csv",
            "catalogo.json",
            "metadados/ESPECIFICACAO_FICHA_TRIAGEM_CENARIOS.json",
            "referencias/resiliencia_municipios.json",
            "referencias/open_buildings_tiles.geojson",
            "referencias/obitos.geojson",
            "referencias/obitos_metadata.json",
            "referencias/obitos_source.zip",
            "referencias/README_OBITOS.md",
            "referencias/agregados_taquari_indicadores.json",
            "agregados/Agregados_taquari_pessoa.csv",
            "agregados/Agregados_taquari_domicilio.csv",
            "agregados/Agregados_taquari_entorno.csv",
            "agregados/Agregados_taquari_PCD_TEA_municipio.csv",
        ):
            assert required in names, f"ZIP sem export/metadado: {required}"

    # O mesmo pacote pode aparecer uma vez no centro de downloads e outra na
    # documentação; o teste acima verifica que toda ocorrência aponta para um
    # arquivo existente, enquanto a revisão editorial trata rótulos duplicados.
    assert "unpkg.com" in html and "integrity=" in html, "Leaflet sem SRI declarado"
    assert f'DATA_FALLBACK_COMMIT = "{commit}"' in html, "HTML e manifest de fallback divergentes"
    assert "/main/assets/data/vulnerabilidade" not in html, "fallback ainda aponta para branch mutavel"
    assert "Content-Security-Policy" in html and 'name="referrer"' in html, "polÃ­tica de seguranÃ§a ausente"
    assert "Permissions-Policy" in html, "Permissions-Policy ausente"

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
