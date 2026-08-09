#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera os downloads auditáveis da área de vulnerabilidade.

O arquivo por setor combina os indicadores do Censo 2022 com o contexto
municipal disponível no site (contagens de pontos do IEDE-RS e ICM). A junção
não transforma dado municipal em dado setorial: os campos herdados recebem
prefixo ``mun_`` e essa limitação é documentada no catálogo e no LEIA-ME.

O script usa apenas a biblioteca padrão para poder rodar tanto depois do robô
do IBGE quanto depois do robô de serviços públicos.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import geopandas as gpd


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "assets" / "data"
VULN = DATA / "vulnerabilidade"
SERV = DATA / "servicos"
OUT = VULN / "downloads"

SERVICOS = ("ubs", "hospitais", "escolas", "bombeiros")
SOMAVEIS = (
    "pop",
    "dom",
    "dom_ocupados",
    "mulheres",
    "c0_4",
    "c5_9",
    "i60_69",
    "i70m",
    "indigenas",
    "pretos_pardos",
    "dom_agua",
    "dom_esgoto",
    "n_resp",
)

CAMPOS_SUJEITOS_A_SIGILO = (
    "dom",
    "dom_ocupados",
    "mulheres",
    "c0_4",
    "c5_9",
    "i60_69",
    "i70m",
    "indigenas",
    "pretos_pardos",
    "dom_agua",
    "dom_esgoto",
    "renda_resp",
    "n_resp",
)
CAMPOS_SIGILO_LEGADO = tuple(
    campo for campo in CAMPOS_SUJEITOS_A_SIGILO if campo not in ("dom", "dom_ocupados")
)


def ler_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def gravar_json(path: Path, value, *, compacto: bool = False) -> None:
    if compacto:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def numero(value):
    if value in (None, ""):
        return 0.0
    return float(value)


def inteiro(value) -> int:
    return int(round(numero(value)))


def padrao_sigilo_legado(props: dict) -> bool:
    """Reconhece a omissão confirmada nos ativos gerados antes das flags de sigilo.

    O IBGE publica ``X`` em grande parte das variáveis de setores com menos de
    cinco DPPO. A versão antiga do robô converteu esses X em zero. O padrão só é
    aplicado aos ativos legados: população positiva e todos os indicadores
    temáticos selecionados zerados, embora o total básico de domicílios exista.
    """
    if numero(props.get("pop")) <= 0:
        return False
    conferir = (
        "mulheres", "c0_4", "c5_9", "i60_69", "i70m", "indigenas",
        "pretos_pardos", "dom_agua", "dom_esgoto", "n_resp",
    )
    return all(numero(props.get(campo)) == 0 for campo in conferir)


def quantis_mapa(values: list[float]) -> list[float]:
    """Mesma regra da interface: zero isolado quando existe e 4 cortes no total."""
    vals = sorted(v for v in values if v == v)  # remove NaN
    if not vals:
        return [0.0, 0.0, 0.0, 0.0]
    positivos = [v for v in vals if v > 0]
    if len(positivos) < len(vals) and positivos:
        base = positivos
        probs = (0.25, 0.50, 0.75)
        return [0.0, *[base[min(len(base) - 1, int(p * len(base)))] for p in probs]]
    probs = (0.20, 0.40, 0.60, 0.80)
    return [vals[min(len(vals) - 1, int(p * len(vals)))] for p in probs]


def csv_bytes(rows: list[dict], columns: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=columns,
        delimiter=";",
        extrasaction="ignore",
        lineterminator="\r\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def escrever_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.write_bytes(csv_bytes(rows, columns))


def bytes_portaveis(path: Path) -> bytes:
    """Normaliza fim de linha de fontes textuais entre Windows e Linux."""
    raw = path.read_bytes()
    if path.suffix.lower() not in {".py", ".md", ".txt", ".json", ".geojson", ".csv"}:
        return raw
    try:
        texto = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw
    return texto.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def hash_entradas(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.as_posix()):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes_portaveis(path))
        digest.update(b"\0")
    return digest.hexdigest()


def zip_deterministico(path: Path, files: list[tuple[str, bytes]]) -> None:
    """Cria ZIP reproduzível: ordem, relógio e permissões são fixos."""
    with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=9) as zf:
        for name, payload in sorted(files):
            info = ZipInfo(name, date_time=(2022, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, payload)


def campo_shapefile(nome: str, usados: set[str]) -> str:
    """Converte atributo para o limite de 10 caracteres do DBF, sem colisão."""
    base = re.sub(r"[^A-Za-z0-9_]", "_", nome).upper()[:10] or "CAMPO"
    candidato = base
    i = 1
    while candidato in usados:
        sufixo = str(i)
        candidato = (base[: 10 - len(sufixo)] + sufixo)[:10]
        i += 1
    usados.add(candidato)
    return candidato


def gerar_shapefiles(features_por_nome: dict[str, list[dict]], destino: Path) -> tuple[bytes, dict[str, dict[str, str]]]:
    """Gera um ZIP de shapefiles UTF-8 para ArcGIS/QGIS e um dicionário de campos.

    O pacote usa EPSG:4326, inclui .cpg UTF-8 e mantém cada camada em sua pasta.
    O arquivo DBF recebe uma data fixa para que o ZIP continue reproduzível.
    """
    temp = Path(tempfile.mkdtemp(prefix="previne_shp_"))
    arquivos: list[tuple[str, bytes]] = []
    mapa_campos: dict[str, dict[str, str]] = {}
    try:
        for nome, features in sorted(features_por_nome.items()):
            if not features:
                continue
            usados: set[str] = set()
            campos: dict[str, str] = {}
            registros = []
            for feature in features:
                props = feature.get("properties") or {}
                out_props = {}
                for campo, valor in props.items():
                    if campo not in campos:
                        campos[campo] = campo_shapefile(campo, usados)
                    curto = campos[campo]
                    # DBF não tem booleano nem listas; valores complexos viram texto.
                    if isinstance(valor, (dict, list)):
                        valor = json.dumps(valor, ensure_ascii=False, separators=(",", ":"))
                    out_props[curto] = valor
                registros.append({"type": "Feature", "properties": out_props, "geometry": feature.get("geometry")})
            pasta = temp / nome
            pasta.parent.mkdir(parents=True, exist_ok=True)
            shp_path = pasta.with_suffix(".shp")
            gdf = gpd.GeoDataFrame.from_features(registros, crs="EPSG:4326")
            gdf.to_file(shp_path, driver="ESRI Shapefile", encoding="UTF-8", index=False)
            mapa_campos[nome] = campos
            for sidecar in sorted(shp_path.parent.glob(shp_path.stem + ".*")):
                rel = sidecar.relative_to(temp).as_posix()
                payload = sidecar.read_bytes()
                if sidecar.suffix.lower() == ".dbf" and len(payload) >= 4:
                    payload = payload[:1] + bytes((122, 1, 1)) + payload[4:]
                arquivos.append((rel, payload))
            if not any(rel == f"{nome}.cpg" for rel, _ in arquivos):
                arquivos.append((f"{nome}.cpg", b"UTF-8\n"))
        readme = (
            "PACOTE SHAPEFILE — PREVINE / VULNERABILIDADE\n\n"
            "CRS de todas as camadas: EPSG:4326 (WGS 84).\n"
            "Cada camada contém .shp, .shx, .dbf, .prj e .cpg em UTF-8.\n"
            "O formato Shapefile limita nomes de campos a 10 caracteres; consulte\n"
            "campos.csv para a correspondência entre o nome original e o abreviado.\n"
            "Ausência de ponto nas camadas de serviços não significa inexistência.\n"
        ).encode("utf-8")
        arquivos.append(("README_SHAPEFILE.txt", readme))
        linhas = ["camada;campo_original;campo_shapefile\n"]
        for camada, campos in sorted(mapa_campos.items()):
            for original, curto in campos.items():
                linhas.append(f"{camada};{original};{curto}\n")
        arquivos.append(("campos.csv", "".join(linhas).encode("utf-8")))
        stream = io.BytesIO()
        # ZipFile precisa de um caminho; usamos arquivo temporário e retornamos bytes.
        zip_path = temp / "shapefiles_arcgis_qgis.zip"
        zip_deterministico(zip_path, arquivos)
        return zip_path.read_bytes(), mapa_campos
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def contexto_municipal(mun: dict, serv: dict, icm: dict) -> dict:
    return {
        "municipio": mun["nome"],
        "cod_mun": str(mun["cod_mun"]),
        "mun_pct_na_bacia": mun.get("pct_na_bacia", ""),
        "mun_pop_total": mun.get("pop", ""),
        "mun_pop_na_bacia": mun.get("pop_bacia", ""),
        "mun_ubs_iede": serv.get("ubs", 0),
        "mun_hospitais_iede": serv.get("hospitais", 0),
        "mun_escolas_iede": serv.get("escolas", 0),
        "mun_bombeiros_iede": serv.get("bombeiros", 0),
        "mun_servicos_cobertura": "cadastro_IEDE_parcial_nao_inventario",
        "mun_icm_faixa": icm.get("faixa", ""),
        "mun_icm_pontos": icm.get("pontuacao_total", ""),
        "mun_icm_prioritario": (
            "" if "prioritario" not in icm else ("sim" if icm["prioritario"] else "não")
        ),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    municipios_fc = ler_json(VULN / "municipios.geojson")
    municipios = [feature["properties"] for feature in municipios_fc["features"]]
    mun_por_cod = {str(m["cod_mun"]): m for m in municipios}
    codigos = set(mun_por_cod)
    if len(codigos) != len(municipios):
        raise RuntimeError("cod_mun duplicado em municipios.geojson")

    setores_paths = sorted((VULN / "setores").glob("*.geojson"))
    grade_paths = sorted((VULN / "grade").glob("*.geojson"))
    setores_codigos = {p.stem for p in setores_paths}
    grade_codigos = {p.stem for p in grade_paths}
    if setores_codigos != codigos:
        raise RuntimeError(
            "arquivos de setores não correspondem aos municípios atuais; "
            f"órfãos={sorted(setores_codigos-codigos)}, faltantes={sorted(codigos-setores_codigos)}"
        )
    if grade_codigos != codigos:
        raise RuntimeError(
            "arquivos da grade não correspondem aos municípios atuais; "
            f"órfãos={sorted(grade_codigos-codigos)}, faltantes={sorted(codigos-grade_codigos)}"
        )

    serv_json = ler_json(SERV / "contagem_municipios.json")
    serv_por_cod = {str(m["cod_mun"]): m for m in serv_json.get("municipios", [])}
    serv_extras = set(serv_por_cod) - codigos
    if serv_extras:
        raise RuntimeError(f"serviços com municípios órfãos: {sorted(serv_extras)}")

    icm_json = ler_json(DATA / "icm_municipios.json")
    icm_por_cod = {str(m["cod_ibge"]): m for m in icm_json.get("municipios", [])}
    if set(icm_por_cod) != codigos:
        raise RuntimeError(
            "cobertura ICM diferente da malha municipal; "
            f"órfãos={sorted(set(icm_por_cod)-codigos)}, faltantes={sorted(codigos-set(icm_por_cod))}"
        )

    setor_features: list[dict] = []
    setor_ids: set[str] = set()
    setores_com_sigilo: set[str] = set()
    somas_por_mun: dict[str, dict[str, float]] = {}
    pop_bacia_por_mun: dict[str, float] = {}
    for cod in sorted(codigos):
        fc = ler_json(VULN / "setores" / f"{cod}.geojson")
        ctx = contexto_municipal(mun_por_cod[cod], serv_por_cod.get(cod, {}), icm_por_cod[cod])
        somas_por_mun[cod] = {campo: 0.0 for campo in SOMAVEIS}
        pop_bacia_por_mun[cod] = 0.0
        for feature in fc.get("features", []):
            props = dict(feature.get("properties") or {})
            setor = str(props.get("setor", ""))
            if not setor or setor in setor_ids:
                raise RuntimeError(f"setor ausente ou duplicado: {setor!r}")
            setor_ids.add(setor)
            if props.get("na_bacia") not in (0, 1, 0.0, 1.0):
                raise RuntimeError(f"na_bacia inválido no setor {setor}")
            legado = not any(k.startswith("sigilo_") for k in props) and padrao_sigilo_legado(props)
            for campo in CAMPOS_SUJEITOS_A_SIGILO:
                flag = bool(props.get(f"sigilo_{campo}")) or (
                    legado and campo in CAMPOS_SIGILO_LEGADO and campo in props
                )
                props[f"sigilo_{campo}"] = 1 if flag else 0
                if flag:
                    props[campo] = None
                    setores_com_sigilo.add(setor)
            for campo in SOMAVEIS:
                valor = numero(props.get(campo))
                if valor < 0:
                    raise RuntimeError(f"{campo} negativo no setor {setor}")
                somas_por_mun[cod][campo] += valor
            if numero(props.get("mulheres")) > numero(props.get("pop")):
                raise RuntimeError(f"mulheres > população no setor {setor}")
            base_dom = props.get("dom_ocupados")
            limite_dom = numero(base_dom) if base_dom is not None else numero(props.get("dom"))
            if numero(props.get("dom_agua")) > limite_dom:
                raise RuntimeError(f"dom_agua > base domiciliar no setor {setor}")
            if numero(props.get("dom_esgoto")) > limite_dom:
                raise RuntimeError(f"dom_esgoto > base domiciliar no setor {setor}")
            if inteiro(props.get("na_bacia")) == 1:
                pop_bacia_por_mun[cod] += numero(props.get("pop"))

            combinado = {**props, **ctx}
            setor_features.append(
                {"type": "Feature", "properties": combinado, "geometry": feature.get("geometry")}
            )

    for cod, mun in mun_por_cod.items():
        for campo in SOMAVEIS:
            if campo not in mun:
                continue
            if abs(somas_por_mun[cod][campo] - numero(mun[campo])) > 0.01:
                raise RuntimeError(
                    f"agregado municipal divergente: {cod} {campo} "
                    f"setores={somas_por_mun[cod][campo]} município={mun[campo]}"
                )
        if abs(pop_bacia_por_mun[cod] - numero(mun.get("pop_bacia"))) > 0.01:
            raise RuntimeError(f"pop_bacia divergente no município {cod}")

    bruto_path = VULN / "brutos" / "setores_bacia_indicadores.csv"
    with bruto_path.open("r", encoding="utf-8-sig", newline="") as stream:
        bruto_ids = {str(row["setor"]) for row in csv.DictReader(stream)}
    if bruto_ids != setor_ids:
        raise RuntimeError(
            "setores do CSV bruto diferem dos GeoJSON; "
            f"somente_csv={len(bruto_ids-setor_ids)}, somente_geo={len(setor_ids-bruto_ids)}"
        )

    setores_na_bacia = [
        feature for feature in setor_features if inteiro(feature["properties"].get("na_bacia")) == 1
    ]
    linhas_setores = [feature["properties"] for feature in setor_features]
    linhas_setores_bacia = [feature["properties"] for feature in setores_na_bacia]
    col_setores = list(linhas_setores[0])

    mun_features: list[dict] = []
    linhas_mun: list[dict] = []
    for feature in municipios_fc["features"]:
        cod = str(feature["properties"]["cod_mun"])
        combinado = {
            **feature["properties"],
            **{k: v for k, v in contexto_municipal(
                mun_por_cod[cod], serv_por_cod.get(cod, {}), icm_por_cod[cod]
            ).items() if k not in ("municipio", "cod_mun", "mun_pct_na_bacia", "mun_pop_total", "mun_pop_na_bacia")},
        }
        linhas_mun.append(combinado)
        mun_features.append(
            {"type": "Feature", "properties": combinado, "geometry": feature.get("geometry")}
        )
    col_mun = list(linhas_mun[0])

    grade_features_bacia: list[dict] = []
    linhas_grade_bacia: list[dict] = []
    for cod in sorted(codigos):
        ctx = contexto_municipal(mun_por_cod[cod], serv_por_cod.get(cod, {}), icm_por_cod[cod])
        for feature in ler_json(VULN / "grade" / f"{cod}.geojson").get("features", []):
            props = dict(feature.get("properties") or {})
            if inteiro(props.get("na_bacia")) != 1:
                continue
            props.setdefault("universo_dom", "domicilios_ocupados_grade_ibge_2022")
            if not props.get("id_grade"):
                geo_bytes = json.dumps(
                    feature.get("geometry"), sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                props["id_grade_previne"] = "previne_" + hashlib.sha256(geo_bytes).hexdigest()[:16]
            combinado = {**props, **ctx}
            linhas_grade_bacia.append(combinado)
            grade_features_bacia.append({
                "type": "Feature", "properties": combinado, "geometry": feature.get("geometry")
            })
    col_grade = list(linhas_grade_bacia[0])

    csv_mun = OUT / "municipios_combinados.csv"
    csv_set_bacia = OUT / "setores_na_bacia_combinados.csv"
    csv_set_todos = OUT / "setores_municipios_intersectantes_combinados.csv"
    gj_mun = OUT / "municipios_combinados.geojson"
    gj_set_bacia = OUT / "setores_na_bacia_combinados.geojson"
    csv_grade_bacia = OUT / "grade_200m_na_bacia_combinada.csv"
    gj_grade_bacia = OUT / "grade_200m_na_bacia_combinada.geojson"
    escrever_csv(csv_mun, linhas_mun, col_mun)
    escrever_csv(csv_set_bacia, linhas_setores_bacia, col_setores)
    escrever_csv(csv_set_todos, linhas_setores, col_setores)
    escrever_csv(csv_grade_bacia, linhas_grade_bacia, col_grade)
    gravar_json(gj_mun, {"type": "FeatureCollection", "features": mun_features}, compacto=True)
    gravar_json(
        gj_set_bacia,
        {"type": "FeatureCollection", "features": setores_na_bacia},
        compacto=True,
    )
    grade_geojson_bytes = json.dumps(
        {"type": "FeatureCollection", "features": grade_features_bacia},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    # O GeoJSON da grade tem ~28 MB descompactado. Ele fica dentro do ZIP para
    # evitar duplicar esse volume no Git/GitHub Pages; o CSV permanece direto.
    if gj_grade_bacia.exists():
        gj_grade_bacia.unlink()

    # Pacote interoperável para ArcGIS/QGIS. O GeoJSON continua sendo a fonte
    # aberta; aqui entregamos as mesmas camadas no formato Shapefile clássico.
    camadas_shp = {
        "municipios_combinados": mun_features,
        "setores_na_bacia_combinados": setores_na_bacia,
        "grade_200m_na_bacia": grade_features_bacia,
    }
    bacia_path = VULN / "bacia.geojson"
    if bacia_path.exists():
        camadas_shp["bacia_taquari_antas"] = ler_json(bacia_path).get("features", [])
    for tipo in (*SERVICOS, "abrigos"):
        path = SERV / f"{tipo}.geojson"
        if path.exists():
            camadas_shp[f"servicos/{tipo}"] = ler_json(path).get("features", [])
    for path in sorted((VULN / "perigo").glob("*.geojson")):
        camadas_shp[f"perigo/{path.stem}"] = ler_json(path).get("features", [])
    shapefile_zip_bytes, shapefile_campos = gerar_shapefiles(
        camadas_shp, OUT / "shapefiles_arcgis_qgis.zip"
    )
    shapefile_zip = OUT / "shapefiles_arcgis_qgis.zip"
    shapefile_zip.write_bytes(shapefile_zip_bytes)

    inputs = [
        Path(__file__).resolve(),
        VULN / "municipios.geojson",
        bruto_path,
        VULN / "brutos" / "FONTES.md",
        SERV / "contagem_municipios.json",
        SERV / "FONTES.md",
        DATA / "icm_municipios.json",
        *setores_paths,
        *grade_paths,
        *[SERV / f"{tipo}.geojson" for tipo in SERVICOS if (SERV / f"{tipo}.geojson").exists()],
        *([SERV / "abrigos.geojson"] if (SERV / "abrigos.geojson").exists() else []),
        *sorted((VULN / "perigo").glob("*.geojson")),
        *([VULN / "perigo" / "README.md"] if (VULN / "perigo" / "README.md").exists() else []),
    ]
    entradas_sha = hash_entradas(inputs)
    antigo = {}
    catalogo_path = OUT / "catalogo.json"
    if catalogo_path.exists():
        try:
            antigo = ler_json(catalogo_path)
        except (OSError, ValueError):
            antigo = {}
    if antigo.get("hash_entradas_sha256") == entradas_sha:
        gerado_em = antigo.get("gerado_em_utc")
    else:
        gerado_em = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    cobertura_servicos = {}
    for tipo in SERVICOS:
        valores = [inteiro(serv_por_cod.get(cod, {}).get(tipo)) for cod in codigos]
        cobertura_servicos[tipo] = {
            "pontos_publicados": sum(valores),
            "municipios_com_ponto": sum(v > 0 for v in valores),
            "municipios_sem_ponto_na_camada": sum(v == 0 for v in valores),
            "status": "cadastro_IEDE_parcial_nao_inventario",
        }

    def classificacoes(rows: list[dict], campos: list[tuple[str, str | None]]) -> dict:
        saida = {}
        for campo, base_pct in campos:
            validas = [row for row in rows if not bool(row.get(f"sigilo_{campo}"))]
            valores = [numero(row.get(campo)) for row in validas]
            item = {"abs": quantis_mapa(valores)}
            if base_pct:
                item["pct"] = quantis_mapa([
                    numero(row.get(campo)) / numero(row.get(base_pct)) * 100
                    if numero(row.get(base_pct)) > 0 else 0
                    for row in validas
                ])
            saida[campo] = item
        return saida

    tem_dom_ocupados = any("dom_ocupados" in row for row in linhas_mun)
    campos_sociais = [
        ("mulheres", "pop"), ("c0_4", "pop"), ("c5_9", "pop"),
        ("i60_69", "pop"), ("i70m", "pop"), ("indigenas", "pop"),
        ("pretos_pardos", "pop"), ("renda_resp", None),
        ("dom_agua", "dom_ocupados" if tem_dom_ocupados else None),
        ("dom_esgoto", "dom_ocupados" if tem_dom_ocupados else None),
        ("dom_ocupados", None), ("dens", None),
        ("dom", None), ("pop", None),
    ]
    campos_sociais = [
        item for item in campos_sociais
        if any(item[0] in row for row in linhas_mun)
    ]
    classes_municipios = classificacoes(linhas_mun, campos_sociais)
    for tipo in SERVICOS:
        campo_mun = f"mun_{tipo}_iede"
        valores = [
            numero(row.get(campo_mun)) / numero(row.get("pop")) * 10000
            if numero(row.get("pop")) > 0 else 0
            for row in linhas_mun
        ]
        classes_municipios[f"svc_{tipo}"] = {"abs": quantis_mapa(valores)}
    classes_setores = classificacoes(linhas_setores_bacia, campos_sociais)
    classes_grade = classificacoes(linhas_grade_bacia, [("pop", None), ("dom", None)])

    catalogo = {
        "schema_versao": 2,
        "titulo": "Dados combinados de vulnerabilidade — bacia Taquari-Antas",
        "gerado_em_utc": gerado_em,
        "hash_entradas_sha256": entradas_sha,
        "crs_geojson": "EPSG:4326",
        "crs_shapefile": "EPSG:4326",
        "formatos_gis": {
            "shapefile_zip": "shapefiles_arcgis_qgis.zip",
            "camadas": sorted(shapefile_campos),
            "observacao": "Shapefile limita nomes de campos a 10 caracteres; correspondência em campos.csv.",
        },
        "referencia_censo": 2022,
        "contagens": {
            "municipios": len(municipios),
            "setores_municipios_intersectantes": len(setor_features),
            "setores_na_bacia": len(setores_na_bacia),
            "celulas_grade_na_bacia": len(linhas_grade_bacia),
            "celulas_grade": sum(len(ler_json(path).get("features", [])) for path in grade_paths),
            "populacao_setorial_na_bacia": sum(
                inteiro(feature["properties"].get("pop")) for feature in setores_na_bacia
            ),
        },
        "cobertura_servicos": cobertura_servicos,
        "camadas_perigo": {
            "sgb_santa_tereza_2025": {
                "feicoes": 37,
                "cobertura": "somente_municipio_4317251",
                "status": "setorizacao_oficial_nao_mancha_continua",
                "fonte": "Serviço Geológico do Brasil (SGB)",
            }
        },
        "classificacoes_quantis": {
            "municipio": classes_municipios,
            "setor": classes_setores,
            "grade": classes_grade,
            "nota": "cortes calculados no recorte completo da bacia; zeros formam classe própria quando presentes",
        },
        "qualidade": {
            "cod_mun_unicos": True,
            "setor_unico": True,
            "arquivos_setor_iguais_aos_municipios": True,
            "arquivos_grade_iguais_aos_municipios": True,
            "agregados_municipais_conferidos": True,
            "cobertura_icm_municipal": "completa",
            "setores_com_dado_suprimido": len(setores_com_sigilo),
            "percentuais_agua_esgoto": (
                "denominador_oficial_V00001_publicado"
                if tem_dom_ocupados else
                "bloqueados_ate_publicar_denominador_oficial_V00001"
            ),
        },
        "advertencias": [
            "Censo 2022 é um retrato, não dado em tempo real.",
            "Municípios de borda aparecem por inteiro; use na_bacia=1 para o recorte setorial da bacia.",
            "Campos mun_* repetidos nos setores são contexto municipal e não medição setorial.",
            "Contagens mun_*_iede refletem pontos presentes nas camadas consultadas; ausência não prova zero serviços.",
            "Valores X suprimidos pelo IBGE são nulos e têm flag sigilo_<campo>; não são zeros.",
            (
                "Água e esgoto usam V00001 (domicílios particulares permanentes ocupados) como denominador."
                if tem_dom_ocupados else
                "Percentuais de água e esgoto estão bloqueados neste pacote: falta regerar os dados com V00001."
            ),
            "Risco de inundação exige cruzamento posterior com uma camada de perigo validada.",
            "A camada SGB de risco cobre somente Santa Tereza e não deve ser extrapolada para a bacia.",
        ],
        "arquivos": [
            "municipios_combinados.csv",
            "municipios_combinados.geojson",
            "setores_na_bacia_combinados.csv",
            "setores_na_bacia_combinados.geojson",
            "setores_municipios_intersectantes_combinados.csv",
            "grade_200m_na_bacia_combinada.csv",
            "grade_200m_na_bacia_combinada.geojson (dentro do ZIP)",
            "perigo/setores_risco_sgb_santa_tereza.geojson (dentro do ZIP)",
            "shapefiles_arcgis_qgis.zip",
            "dados_combinados_taquari_antas.zip",
        ],
    }
    gravar_json(catalogo_path, catalogo)

    leia_me = f"""DADOS COMBINADOS — BACIA TAQUARI-ANTAS

Referência social: Censo Demográfico IBGE 2022.
CRS dos GeoJSON: EPSG:4326.

O pacote contém:
- municipios_combinados: 1 linha/feição por município que intersecta a bacia;
- setores_na_bacia_combinados: somente setores cujo ponto representativo está na bacia;
- setores_municipios_intersectantes_combinados: todos os setores dos municípios de borda;
- grade_200m_na_bacia_combinada: células da grade estatística dentro da bacia;
- servicos/*.geojson: pontos publicados pelo IEDE-RS, separados por tipo;
- perigo/: setores oficiais de risco do SGB em Santa Tereza (levantamento 2025);
- shapefiles_arcgis_qgis.zip: camadas para ArcGIS/QGIS (EPSG:4326, UTF-8);
- fontes/: documentação de origem.

Grão e junções:
- indicadores sem prefixo são do setor ou do município indicado pelo nome do arquivo;
- campos mun_* repetidos no setor são atributos municipais, não dados setoriais;
- na_bacia=1 identifica o recorte setorial adotado pelo projeto;
- id_grade é o identificador oficial quando disponível; id_grade_previne é um
  identificador técnico derivado da geometria para os ativos legados;
- contagens *_iede são cadastros parciais das camadas disponíveis no IEDE-RS.
  Ausência de ponto não deve ser interpretada como inexistência do serviço.
- flags sigilo_<campo>=1 indicam valor X omitido pelo IBGE; o valor correspondente
  fica vazio/nulo e não deve ser convertido em zero.
- água e esgoto têm universo de domicílios particulares permanentes ocupados;
  o percentual só é publicado quando V00001 (dom_ocupados) está disponível.

Contagens verificadas nesta geração:
- {len(municipios)} municípios;
- {len(setor_features)} setores nos municípios que tocam a bacia;
- {len(setores_na_bacia)} setores dentro da bacia;
- {len(linhas_grade_bacia)} células de 200 m dentro da bacia;
- {len(setores_com_sigilo)} setores com ao menos um indicador suprimido;
- {sum(inteiro(f['properties'].get('pop')) for f in setores_na_bacia):,} habitantes no recorte setorial.

Leia catalogo.json para os testes de qualidade e advertências.
"""
    (OUT / "LEIA-ME.txt").write_text(leia_me, encoding="utf-8")

    zip_files: list[tuple[str, bytes]] = []
    for path in (
        csv_mun, csv_set_bacia, csv_set_todos, gj_mun, gj_set_bacia,
        csv_grade_bacia, catalogo_path, OUT / "LEIA-ME.txt"
    ):
        zip_files.append((path.name, path.read_bytes()))
    zip_files.append(("shapefiles_arcgis_qgis.zip", shapefile_zip_bytes))
    zip_files.append(("grade_200m_na_bacia_combinada.geojson", grade_geojson_bytes))
    for tipo in (*SERVICOS, "abrigos"):
        path = SERV / f"{tipo}.geojson"
        if path.exists():
            zip_files.append((f"servicos/{path.name}", path.read_bytes()))
    for path in sorted((VULN / "perigo").glob("*")):
        if path.is_file():
            zip_files.append((f"perigo/{path.name}", bytes_portaveis(path)))
    for path, name in (
        (VULN / "brutos" / "FONTES.md", "fontes/FONTES_VULNERABILIDADE.md"),
        (SERV / "FONTES.md", "fontes/FONTES_SERVICOS.md"),
    ):
        if path.exists():
            zip_files.append((name, bytes_portaveis(path)))
    zip_deterministico(OUT / "dados_combinados_taquari_antas.zip", zip_files)

    print(json.dumps(catalogo["contagens"], ensure_ascii=False, indent=2))
    print("DOWNLOADS COMBINADOS ->", OUT)


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
