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
import sqlite3
import tempfile
from collections import defaultdict
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

CAMPOS_COMPLETUDE = tuple(dict.fromkeys((*SOMAVEIS, "renda_resp", "dens")))


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


def conhecido(props: dict, campo: str) -> bool:
    """True quando o campo tem valor publicado e nÃ£o estÃ¡ sob sigilo."""
    return props.get(campo) not in (None, "") and not bool(props.get(f"sigilo_{campo}"))


def anota_completude_unidade(props: dict, campos=CAMPOS_COMPLETUDE) -> dict:
    """Publica n_validos/n_total/completude no grão da própria feição."""
    for campo in campos:
        if campo not in props and f"sigilo_{campo}" not in props:
            continue
        flag = f"sigilo_{campo}"
        valido = conhecido(props, campo)
        props[f"{campo}_n_validos"] = 1 if valido else 0
        props[f"{campo}_n_total"] = 1
        props[f"{campo}_completude"] = 1.0 if valido else 0.0
    return props


def anota_recorte(props: dict, *, unidade: str) -> dict:
    """Mantém área, status de borda e métodos de recorte explícitos."""
    pct = props.get("area_pct_bacia", props.get("pct_na_bacia"))
    try:
        pct_num = float(pct)
    except (TypeError, ValueError):
        pct_num = 0.0
    props.setdefault("area_pct_bacia", pct)
    props.setdefault("status_borda_bacia", "parcial" if 0 < pct_num < 100 else "total")
    props.setdefault("metodo_area_bacia", "interseção geométrica em EPSG:5880")
    props.setdefault(
        "metodo_na_bacia",
        f"ponto_representativo_{unidade}_2022_within_bacia",
    )
    return props


def enriquece_recorte_municipal(props: dict, setores: list[dict]) -> dict:
    """Adiciona aliases e somas do recorte dentro da bacia ao municÃ­pio.

    Os campos sem prefixo continuam sendo o agregado municipal inteiro. Os
    campos ``*_bacia`` sÃ£o somas/mÃ©dias apenas dos setores com ponto
    representativo dentro da bacia; cada um traz contagem de registros vÃ¡lidos,
    total de setores e completude. A rotina Ã© idempotente e tambÃ©m permite
    regenerar os downloads a partir de um pacote legado.
    """
    todos = list(setores)
    dentro = [p for p in todos if inteiro(p.get("na_bacia")) == 1]
    props.setdefault("pop_mun", props.get("pop"))
    props.setdefault("dom_mun", props.get("dom"))
    props.setdefault("area_pct_bacia", props.get("pct_na_bacia"))
    props.setdefault("metodo_recorte_bacia", "ponto_representativo_setor_2022")
    anota_recorte(props, unidade="municipio")
    props["n_setores_municipio"] = len(todos)
    props["n_setores_bacia"] = len(dentro)

    # Densidade no recorte: a geração principal calcula a área exata em
    # EPSG:5880; este fallback conserva compatibilidade com ativos legados,
    # estimando a Ã¡rea intersectada a partir da densidade municipal e de
    # area_pct_bacia. Sem setor representativo, nÃ£o publica zero fictÃ­cio.
    if props.get("dens_bacia") in (None, ""):
        pop_bacia = numero(props.get("pop_bacia"))
        dens_mun = numero(props.get("dens"))
        pop_mun = numero(props.get("pop"))
        area_pct = numero(props.get("area_pct_bacia"))
        if len(dentro) and not bool(props.get("sigilo_pop_bacia")) and pop_bacia is not None and dens_mun > 0 and pop_mun > 0 and area_pct > 0:
            area_intersectada = (pop_mun / dens_mun) * area_pct / 100.0
            props["dens_bacia"] = round(pop_bacia / area_intersectada, 1) if area_intersectada > 0 else None
        else:
            props["dens_bacia"] = None
    props["sigilo_dens_bacia"] = (
        bool(props.get("sigilo_dens_bacia"))
        or bool(props.get("sigilo_pop_bacia"))
        or not len(dentro)
    )
    props["dens_bacia_n_validos"] = 1 if props.get("dens_bacia") is not None else 0
    props["dens_bacia_n_total"] = 1
    props["dens_bacia_completude"] = 1.0 if props.get("dens_bacia") is not None else 0.0

    # Completude do agregado municipal inteiro: o denominador é o número de
    # setores do município, não um valor preenchido artificialmente.
    for campo in CAMPOS_COMPLETUDE:
        validos = sum(1 for p in todos if conhecido(p, campo))
        props[f"{campo}_n_validos"] = validos
        props[f"{campo}_n_total"] = len(todos)
        props[f"{campo}_completude"] = round(validos / len(todos), 6) if todos else 0.0

    for campo in SOMAVEIS:
        valores = [p.get(campo) for p in dentro if conhecido(p, campo)]
        if campo == "pop":
            # Sem setor dentro, pop_bacia=0; com setores mas todos sob X,
            # publica UNKNOWN (null) em vez de um zero fictício.
            props["pop_bacia"] = (
                sum(numero(v) for v in valores) if valores else (0 if not dentro else None)
            )
        else:
            props[f"{campo}_bacia"] = sum(numero(v) for v in valores) if valores else None
        validos = len(valores)
        props[f"{campo}_bacia_n_validos"] = validos
        props[f"{campo}_bacia_n_total"] = len(dentro)
        props[f"{campo}_bacia_completude"] = round(validos / len(dentro), 6) if dentro else 0.0
        flag = f"sigilo_{campo}"
        if any(bool(p.get(flag)) for p in dentro):
            props[f"sigilo_{campo}_bacia"] = True
        else:
            props[f"sigilo_{campo}_bacia"] = False

    if "renda_resp" in {k for p in todos for k in p}:
        ponderados = [
            p for p in dentro
            if conhecido(p, "renda_resp") and conhecido(p, "n_resp") and numero(p.get("n_resp")) > 0
        ]
        den = sum(numero(p.get("n_resp")) for p in ponderados)
        props["renda_resp_bacia"] = (
            round(sum(numero(p.get("renda_resp")) * numero(p.get("n_resp")) for p in ponderados) / den, 0)
            if den else None
        )
        props["renda_resp_bacia_n_validos"] = len(ponderados)
        props["renda_resp_bacia_n_total"] = len(dentro)
        props["renda_resp_bacia_completude"] = round(len(ponderados) / len(dentro), 6) if dentro else 0.0
        props["sigilo_renda_resp_bacia"] = any(
            bool(p.get("sigilo_renda_resp")) or bool(p.get("sigilo_n_resp")) for p in dentro
        )
    return props


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


def nome_camada_gpkg(nome: str, usados: set[str]) -> str:
    """Converte o caminho lógico da camada em um nome de layer GeoPackage."""
    base = re.sub(r"[^A-Za-z0-9_]+", "_", nome).strip("_").lower() or "camada"
    candidato = base
    i = 1
    while candidato in usados:
        candidato = f"{base}_{i}"
        i += 1
    usados.add(candidato)
    return candidato


def gerar_geopackage(features_por_nome: dict[str, list[dict]]) -> tuple[bytes, dict[str, str]]:
    """Gera um GeoPackage único com campos completos para QGIS e ArcGIS Pro.

    O Shapefile continua sendo publicado para compatibilidade ampla, mas o
    GeoPackage evita o limite de dez caracteres dos campos DBF. A camada
    lógica (por exemplo, ``servicos/ubs``) é preservada em um CSV de
    correspondência porque o GPKG usa nomes de layer sem barras.
    """
    temp = Path(tempfile.mkdtemp(prefix="previne_gpkg_"))
    try:
        gpkg = temp / "previne_vulnerabilidade.gpkg"
        usados: set[str] = set()
        mapa_camadas: dict[str, str] = {}
        for nome, features in sorted(features_por_nome.items()):
            if not features:
                continue
            layer = nome_camada_gpkg(nome, usados)
            registros = []
            for feature in features:
                props = dict(feature.get("properties") or {})
                # GeoPackage aceita texto, números e nulos, mas não objetos
                # aninhados; manter listas/dicionários como JSON legível.
                for campo, valor in list(props.items()):
                    if isinstance(valor, (dict, list)):
                        props[campo] = json.dumps(valor, ensure_ascii=False, separators=(",", ":"))
                registros.append({
                    "type": "Feature",
                    "properties": props,
                    "geometry": feature.get("geometry"),
                })
            gdf = gpd.GeoDataFrame.from_features(registros, crs="EPSG:4326")
            gdf.to_file(gpkg, layer=layer, driver="GPKG", engine="pyogrio", index=False)
            mapa_camadas[nome] = layer

        # O driver grava o horário atual em gpkg_contents. Fixamos esse campo
        # para que a publicação continue reproduzível quando as entradas não
        # mudarem, como já ocorre com os demais ZIPs do pacote.
        with sqlite3.connect(gpkg) as conn:
            conn.execute(
                "UPDATE gpkg_contents SET last_change = ?",
                ("2022-01-01T00:00:00.000Z",),
            )
            conn.commit()

        readme = (
            "PACOTE GEOPACKAGE — PREVINE / VULNERABILIDADE\n\n"
            "Arquivo: previne_vulnerabilidade.gpkg\n"
            "CRS de todas as camadas: EPSG:4326 (WGS 84).\n"
            "Os nomes originais e os nomes dos layers estão em camadas.csv.\n"
            "O GeoPackage preserva os nomes completos dos campos, ao contrário\n"
            "do Shapefile, que limita nomes a dez caracteres.\n"
            "Ausência de ponto nas camadas de serviços não significa inexistência.\n"
        ).encode("utf-8")
        linhas = ["camada_original;layer_geopackage\n"]
        for original, layer in sorted(mapa_camadas.items()):
            linhas.append(f"{original};{layer}\n")
        arquivos = [
            ("previne_vulnerabilidade.gpkg", gpkg.read_bytes()),
            ("README_GEOPACKAGE.txt", readme),
            ("camadas.csv", "".join(linhas).encode("utf-8")),
        ]
        zip_path = temp / "geopackage_arcgis_qgis.zip"
        zip_deterministico(zip_path, arquivos)
        return zip_path.read_bytes(), mapa_camadas
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def contexto_municipal(mun: dict, serv: dict, icm: dict) -> dict:
    contexto = {
        "municipio": mun["nome"],
        "cod_mun": str(mun["cod_mun"]),
        "mun_pct_na_bacia": mun.get("pct_na_bacia", ""),
        "mun_pop_total": mun.get("pop", ""),
        "mun_pop_na_bacia": mun.get("pop_bacia", ""),
        "mun_ubs_iede": serv.get("ubs"),
        "mun_hospitais_iede": serv.get("hospitais"),
        "mun_escolas_iede": serv.get("escolas"),
        "mun_bombeiros_iede": serv.get("bombeiros"),
        "mun_servicos_cobertura": "cadastro_IEDE_parcial_nao_inventario",
        "mun_icm_faixa": icm.get("faixa", ""),
        "mun_icm_pontos": icm.get("pontuacao_total", ""),
        "mun_icm_prioritario": (
            "" if "prioritario" not in icm else ("sim" if icm["prioritario"] else "não")
        ),
    }
    for tipo in SERVICOS:
        valor = serv.get(tipo)
        contexto[f"mun_{tipo}_iede_status"] = serv.get(
            f"{tipo}_status", "published" if valor is not None else "unknown"
        )
    return contexto


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
    cobertura_serv_json = serv_json.get("cobertura_por_tipo") or {}
    faltam_cobertura = set(SERVICOS) - set(cobertura_serv_json)
    if faltam_cobertura:
        raise RuntimeError(
            "contagem_municipios.json sem cobertura_por_tipo: "
            f"{sorted(faltam_cobertura)}"
        )
    for cod, registro in serv_por_cod.items():
        for tipo in SERVICOS:
            estado = registro.get(f"{tipo}_status")
            if estado not in {"published", "unknown"}:
                raise RuntimeError(f"status de serviço inválido: {cod} {tipo}={estado!r}")
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

            anota_completude_unidade(props)
            anota_recorte(props, unidade="setor")
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

    def valida_subconjunto_linhas(rows: list[dict], numerador: str, denominador: str, escopo: str) -> int:
        excedentes = [
            {"setor": row.get("setor"), numerador: row.get(numerador), denominador: row.get(denominador)}
            for row in rows
            if row.get(numerador) is not None and row.get(denominador) is not None
            and numero(row.get(numerador)) > numero(row.get(denominador))
        ]
        if excedentes:
            raise RuntimeError(
                f"{numerador} excede {denominador} em {len(excedentes)} registro(s) ({escopo}); "
                f"amostra={excedentes[:5]}"
            )
        return 0

    for escopo, rows in (("setores_municipios_intersectantes", setor_features), ("setores_na_bacia", setores_na_bacia)):
        valida_subconjunto_linhas([f["properties"] for f in rows], "dom_ocupados", "dom", escopo)
        for campo in ("dom_agua", "dom_esgoto"):
            valida_subconjunto_linhas([f["properties"] for f in rows], campo, "dom_ocupados", escopo)
    for feature in setor_features:
        props = feature["properties"]
        for campo in CAMPOS_SUJEITOS_A_SIGILO:
            if bool(props.get(f"sigilo_{campo}")) and props.get(campo) is not None:
                raise RuntimeError(f"{campo}: valor publicado junto com sigilo no setor {props.get('setor')}")

    linhas_setores = [feature["properties"] for feature in setor_features]
    linhas_setores_bacia = [feature["properties"] for feature in setores_na_bacia]
    col_setores = list(linhas_setores[0])

    setores_por_mun: dict[str, list[dict]] = defaultdict(list)
    for feature in setor_features:
        setores_por_mun[str(feature["properties"].get("cod_mun"))].append(feature["properties"])

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
        combinado = enriquece_recorte_municipal(combinado, setores_por_mun.get(cod, []))
        anota_recorte(combinado, unidade="municipio")
        linhas_mun.append(combinado)
        mun_features.append(
            {"type": "Feature", "properties": combinado, "geometry": feature.get("geometry")}
        )
    col_mun = list(linhas_mun[0])
    valida_subconjunto_linhas(linhas_mun, "dom_ocupados", "dom", "municipios")
    for campo in ("dom_agua", "dom_esgoto"):
        valida_subconjunto_linhas(linhas_mun, campo, "dom_ocupados", "municipios")

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
            anota_completude_unidade(props, campos=("pop", "dom"))
            anota_recorte(props, unidade="grade")
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
    geopackage_zip_bytes, geopackage_camadas = gerar_geopackage(camadas_shp)
    geopackage_zip = OUT / "geopackage_arcgis_qgis.zip"
    geopackage_zip.write_bytes(geopackage_zip_bytes)

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
        *[p for p in sorted((VULN / "metadados").glob("*")) if p.is_file()],
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
        valores = [serv_por_cod.get(cod, {}).get(tipo) for cod in codigos]
        conhecidos_tipo = [inteiro(v) for v in valores if v not in (None, "")]
        cobertura_servicos[tipo] = {
            "municipios_total": len(valores),
            "pontos_publicados": sum(conhecidos_tipo),
            "municipios_com_ponto": sum(v > 0 for v in conhecidos_tipo),
            "municipios_sem_ponto_publicado": sum(v in (None, "") for v in valores),
            # compatibilidade nominal; agora significa desconhecido no cadastro,
            # não zero observado.
            "municipios_sem_ponto_na_camada": sum(v in (None, "") for v in valores),
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

    def classificacoes_bacia(rows: list[dict], campos: list[tuple[str, str | None]]) -> dict:
        """Cortes fixos para os valores *_bacia publicados no mapa padrão."""
        saida = {}
        for campo, base_pct in campos:
            campo_bacia = "pop_bacia" if campo == "pop" else f"{campo}_bacia"
            base_bacia = None if base_pct is None else ("pop_bacia" if base_pct == "pop" else f"{base_pct}_bacia")
            flag = f"sigilo_{campo_bacia}"
            # Municípios de borda sem setor representativo não são zeros
            # observados: ficam fora dos cortes publicados da escala bacia.
            validas = [row for row in rows
                       if numero(row.get("n_setores_bacia")) > 0
                       and conhecido(row, campo_bacia)]
            item = {"abs": quantis_mapa([numero(row.get(campo_bacia)) for row in validas])}
            if base_bacia:
                pct = [
                    numero(row.get(campo_bacia)) / numero(row.get(base_bacia)) * 100
                    for row in validas
                    if numero(row.get(base_bacia)) > 0
                ]
                item["pct"] = quantis_mapa(pct)
            saida[campo] = item
        return saida

    def perfil_completude(rows: list[dict], campos: list[str]) -> dict:
        """Perfil estÃ¡vel de validade/sigilo para o catÃ¡logo e auditorias."""
        total = len(rows)
        saida = {}
        for campo in campos:
            flag = f"sigilo_{campo}"
            validos = sum(1 for row in rows if conhecido(row, campo))
            sigilos = sum(1 for row in rows if bool(row.get(flag)))
            nulos = sum(1 for row in rows if row.get(campo) in (None, ""))
            saida[campo] = {
                "registros_total": total,
                "registros_validos": validos,
                "registros_sigilo": sigilos,
                "registros_nulos": nulos,
                "completude": round(validos / total, 6) if total else 0.0,
            }
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
    classes_municipios_bacia = classificacoes_bacia(linhas_mun, campos_sociais)
    for tipo in SERVICOS:
        campo_mun = f"mun_{tipo}_iede"
        valores = [
            numero(row.get(campo_mun)) / numero(row.get("pop")) * 10000
            if numero(row.get("pop")) > 0 else 0
            for row in linhas_mun
            if row.get(campo_mun) not in (None, "")
        ]
        classes_municipios[f"svc_{tipo}"] = {"abs": quantis_mapa(valores)}
    classes_setores = classificacoes(linhas_setores_bacia, campos_sociais)
    classes_grade = classificacoes(linhas_grade_bacia, [("pop", None), ("dom", None)])

    campos_completude = [
        campo for campo in (*SOMAVEIS, "renda_resp")
        if any(campo in row for row in linhas_setores_bacia)
    ]
    completude_setores_bacia = perfil_completude(linhas_setores_bacia, campos_completude)
    completude_municipios = perfil_completude(linhas_mun, campos_completude)
    validacoes_denominadores = {
        "dom_ocupados_le_dom": {"setores": 0, "setores_na_bacia": 0, "municipios": 0},
        "dom_agua_le_dom_ocupados": {"setores": 0, "setores_na_bacia": 0, "municipios": 0},
        "dom_esgoto_le_dom_ocupados": {"setores": 0, "setores_na_bacia": 0, "municipios": 0},
    }
    recorte_borda = {
        "metodo_setor": "ponto_representativo_setor_2022_within_bacia",
        "metodo_area_unidade": "interseção geométrica da unidade/bacia em CRS EPSG:5880; publicado como area_pct_bacia",
        "metodo_area_pct": "interseção geométrica município/bacia em CRS projetado",
        "campo_area_pct": "pct_na_bacia (alias area_pct_bacia)",
        "municipios_intersectantes": len(linhas_mun),
        "municipios_parciais_area": sum(0 < numero(row.get("pct_na_bacia")) < 100 for row in linhas_mun),
        "municipios_area_pct_com_pop_bacia_zero": [
            {"cod_mun": row.get("cod_mun"), "nome": row.get("nome"), "area_pct_bacia": row.get("pct_na_bacia")}
            for row in linhas_mun
            if numero(row.get("pct_na_bacia")) > 0 and numero(row.get("pop_bacia")) == 0
        ],
    }

    catalogo = {
        "schema_versao": 3,
        "titulo": "Dados combinados de vulnerabilidade — bacia Taquari-Antas",
        "gerado_em_utc": gerado_em,
        "hash_entradas_sha256": entradas_sha,
        "crs_geojson": "EPSG:4326",
        "crs_shapefile": "EPSG:4326",
        "crs_geopackage": "EPSG:4326",
        "formatos_gis": {
            "shapefile_zip": "shapefiles_arcgis_qgis.zip",
            "geopackage_zip": "geopackage_arcgis_qgis.zip",
            "camadas": sorted(shapefile_campos),
            "camadas_geopackage": geopackage_camadas,
            "observacao": (
                "Shapefile limita nomes de campos a 10 caracteres; correspondência em campos.csv. "
                "GeoPackage preserva os nomes completos dos campos."
            ),
        },
        "referencia_censo": 2022,
        "recorte_bacia": recorte_borda,
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
        "completude": {
            "setores_na_bacia": completude_setores_bacia,
            "municipios_agregados": completude_municipios,
            "nota": "validos excluem valores nulos e registros com sigilo_<campo>=1; somas *_bacia sÃ£o conhecidas quando hÃ¡ ao menos um setor vÃ¡lido",
        },
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
            "municipio_bacia": classes_municipios_bacia,
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
            "validacoes_denominadores": validacoes_denominadores,
            "campos_recorte_municipal": [
                "pop_mun", "dom_mun", "pop_bacia", "dens_bacia", "area_pct_bacia",
                "n_setores_municipio", "n_setores_bacia", "metodo_recorte_bacia",
            ],
            "recorte_area_unidade": "area_pct_bacia publicado em setores e grade; EPSG:5880; na_bacia segue ponto representativo",
            "campos_completude_por_indicador": [
                "<campo>_n_validos", "<campo>_n_total", "<campo>_completude"
            ],
            "campos_metodo_recorte": [
                "area_pct_bacia", "status_borda_bacia", "metodo_area_bacia", "metodo_na_bacia"
            ],
        },
        "advertencias": [
            "Censo 2022 é um retrato, não dado em tempo real.",
            "Municípios de borda aparecem por inteiro; use na_bacia=1 para o recorte setorial da bacia.",
            "Campos mun_* repetidos nos setores são contexto municipal e não medição setorial.",
            "Contagens mun_*_iede refletem pontos presentes nas camadas consultadas; ausência não prova zero serviços.",
            "Ausência de ponto IEDE é publicada como null/unknown; não é zero observado.",
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
            "geopackage_arcgis_qgis.zip",
            "dados_combinados_taquari_antas.zip",
            *[
                f"metadados/{p.name}"
                for p in sorted((VULN / "metadados").glob("*"))
                if p.is_file()
            ],
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
- geopackage_arcgis_qgis.zip: um GeoPackage com campos completos para QGIS/ArcGIS Pro;
- fontes/: documentação de origem.
- metadados/: escopo, dicionário de campos, inventário de camadas, estilos e citação.

Grão e junções:
- indicadores sem prefixo são do setor ou do município indicado pelo nome do arquivo;
- campos mun_* repetidos no setor são atributos municipais, não dados setoriais;
- na_bacia=1 identifica o recorte setorial adotado pelo projeto;
- nos municípios, campos sem prefixo (e aliases *_mun) são o agregado municipal inteiro;
- pop_bacia e os campos *_bacia são o recorte dos setores cujo ponto representativo
  está dentro do limite; *_bacia_n_validos, *_bacia_n_total e *_bacia_completude
  mostram quanto foi publicado e n_setores_bacia mostra o denominador espacial;
- area_pct_bacia (alias de pct_na_bacia) é a porcentagem geométrica do município
  intersectada pela bacia; não é uma porcentagem de população. Água/esgoto
  continuam com V00001 como denominador e devem ser lidos com a completude/flag;
- area_pct_bacia nas camadas de setor/grade é a fração geométrica da unidade
  que cruza o limite, calculada em EPSG:5880; na_bacia continua sendo o filtro
  por ponto representativo usado para a soma publicada;
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

O catálogo também publica a contagem de registros válidos, nulos, sob sigilo e
o método de recorte de borda. Municípios com área na bacia e pop_bacia=0 ficam
explicitamente listados para revisão, pois isso não prova ausência de população.

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
    zip_files.append(("geopackage_arcgis_qgis.zip", geopackage_zip_bytes))
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
    for path in sorted((VULN / "metadados").glob("*")):
        if path.is_file():
            zip_files.append((f"metadados/{path.name}", bytes_portaveis(path)))
    zip_deterministico(OUT / "dados_combinados_taquari_antas.zip", zip_files)

    print(json.dumps(catalogo["contagens"], ensure_ascii=False, indent=2))
    print("DOWNLOADS COMBINADOS ->", OUT)


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
