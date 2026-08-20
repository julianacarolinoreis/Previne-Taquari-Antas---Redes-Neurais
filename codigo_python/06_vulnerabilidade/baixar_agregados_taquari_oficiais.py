#!/usr/bin/env python3
"""Baixa, filtra e normaliza os agregados municipais oficiais do Censo 2022.

Os quatro CSVs gerados para a bacia mantêm o formato publicado pelo IBGE
(UTF-8, separador ``;``), mas contêm somente os 118 municípios que a página
analisa.  O JSON normalizado é o contrato pequeno consumido pela interface.

Uso local (já com os ZIPs baixados):
    python baixar_agregados_taquari_oficiais.py --raw-dir _ibge_raw

Sem ``--raw-dir`` o script baixa os nove ZIPs municipais do FTP oficial e
consulta as tabelas municipais PcD/TEA do SIDRA. Nenhum valor ausente é
convertido em zero.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VULN = ROOT / "assets" / "data" / "vulnerabilidade"
DOWNLOADS = VULN / "downloads"
REFERENCIAS = VULN / "referencias"
MUNICIPIOS = DOWNLOADS / "municipios_combinados.geojson"

FTP_MUNICIPAL = (
    "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/"
    "Agregados_por_Setores_Censitarios/Agregados_por_Municipio_csv/"
)
FTP_ENTORNO = (
    "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/"
    "Agregados_por_Setores_Censitarios_Caracteristicas_urbanisticas_do_entorno_dos_domicilios/"
    "Agregados_por_Municipio_csv/"
)
SIDRA_BASE = "https://apisidra.ibge.gov.br/values"

ARQUIVOS = {
    "pessoa": "Agregados_por_municipios_pessoa_BR.csv",
    "basico": "Agregados_por_municipios_basico_BR.csv",
    "demografia": "Agregados_por_municipios_demografia_BR.csv",
    "cor_raca": "Agregados_por_municipios_cor_ou_raca_BR.csv",
    "domicilio": "Agregados_por_municipios_caracteristicas_domicilio1_BR.csv",
    "domicilio2": "Agregados_por_municipios_caracteristicas_domicilio2_BR.csv",
    "domicilio3": "Agregados_por_municipios_caracteristicas_domicilio3_BR.csv",
    "entorno_domicilios": "Agregados_por_municipios_entorno_domic%C3%ADlios_BR.csv",
    "entorno_faces": "Agregados_por_municipios_entorno_faces_BR.csv",
    "entorno_moradores": "Agregados_por_municipios_entorno_moradores_BR.csv",
}

# ZIPs atuais do FTP. O nome da versão do básico muda quando o IBGE publica
# revisão; a lista é deliberadamente explícita para tornar a atualização visível.
ZIP_URLS = {
    "basico": FTP_MUNICIPAL + "Agregados_por_municipios_basico_BR_20260520.zip",
    "demografia": FTP_MUNICIPAL + "Agregados_por_municipios_demografia_BR.zip",
    "cor_raca": FTP_MUNICIPAL + "Agregados_por_municipios_cor_ou_raca_BR.zip",
    "domicilio": FTP_MUNICIPAL + "Agregados_por_municipios_caracteristicas_domicilio1_BR.zip",
    "domicilio2": FTP_MUNICIPAL + "Agregados_por_municipios_caracteristicas_domicilio2_BR_20250417.zip",
    "domicilio3": FTP_MUNICIPAL + "Agregados_por_municipios_caracteristicas_domicilio3_BR_20250417.zip",
    "entorno_domicilios": FTP_ENTORNO + "Agregados_por_municipios_entorno_domic%C3%ADlios_BR.zip",
    "entorno_faces": FTP_ENTORNO + "Agregados_por_municipios_entorno_faces_BR.zip",
    "entorno_moradores": FTP_ENTORNO + "Agregados_por_municipios_entorno_moradores_BR.zip",
}

OUT_FILES = {
    "pessoa": "Agregados_taquari_pessoa.csv",
    "domicilio": "Agregados_taquari_domicilio.csv",
    "entorno": "Agregados_taquari_entorno.csv",
    "pcd_tea": "Agregados_taquari_PCD_TEA_municipio.csv",
}


def get_bytes(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "PREVINE-agregados/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def read_target_codes() -> tuple[list[str], dict[str, str]]:
    data = json.loads(MUNICIPIOS.read_text(encoding="utf-8"))
    rows = data.get("features", [])
    codes, names = [], {}
    for feature in rows:
        props = feature.get("properties", {})
        code = str(props.get("cod_mun", "")).strip()
        if not code or code in names:
            raise ValueError(f"código municipal ausente/duplicado: {code!r}")
        codes.append(code)
        names[code] = str(props.get("nome", "")).strip()
    if len(codes) != 118:
        raise ValueError(f"esperados 118 municípios, encontrados {len(codes)}")
    return codes, names


def ensure_raw(raw_dir: Path) -> dict[str, Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for key, url in ZIP_URLS.items():
        dest = raw_dir / Path(urllib.parse.urlparse(url).path).name
        if not dest.exists() or dest.stat().st_size == 0:
            print(f"baixando {key}: {url}", file=sys.stderr)
            dest.write_bytes(get_bytes(url))
        paths[key] = dest
    return paths


def csv_from_zip(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with zipfile.ZipFile(path) as archive:
        members = [m for m in archive.namelist() if m.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"{path}: esperado um CSV, encontrados {members}")
        raw = archive.read(members[0])
    # Os pacotes atuais do FTP trazem latin-1 apesar de a documentação dizer
    # UTF-8. Detectar BOM/UTF-8 e cair para latin-1 evita corromper acentos.
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    reader = csv.DictReader(io.StringIO(text), delimiter=";", quotechar='"')
    if not reader.fieldnames or "CD_MUN" not in reader.fieldnames:
        raise ValueError(f"{path}: CSV sem CD_MUN")
    return list(reader.fieldnames), list(reader)


def filter_rows(rows: list[dict[str, str]], codes: set[str]) -> list[dict[str, str]]:
    selected = [row for row in rows if str(row.get("CD_MUN", "")).strip() in codes]
    selected.sort(key=lambda row: str(row.get("CD_MUN", "")))
    if {str(row.get("CD_MUN", "")).strip() for row in selected} != codes:
        missing = sorted(codes - {str(row.get("CD_MUN", "")).strip() for row in selected})
        raise ValueError(f"municípios ausentes no arquivo: {missing}")
    return selected


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in rows)


def clean(value: str | None):
    if value is None:
        return None
    value = str(value).strip()
    if value in {"", "X", ".", "..", "...", "-"}:
        return None
    try:
        number = float(value.replace(",", "."))
    except ValueError:
        return value
    return int(number) if number.is_integer() else number


def add(a, b):
    a, b = clean(a), clean(b)
    if a is None and b is None:
        return None
    return (a or 0) + (b or 0)


def pct(num, den):
    num, den = clean(num), clean(den)
    if num is None or den in (None, 0):
        return None
    return round(float(num) / float(den) * 100, 2)


def sidra_value(code: str, table: str, variables: str) -> dict[str, object]:
    url = f"{SIDRA_BASE}/t/{table}/v/{variables}/n6/{code}/p/2022"
    last_error = None
    for attempt in range(3):
        try:
            payload = json.loads(get_bytes(url, timeout=60).decode("utf-8"))
            if len(payload) < 2:
                raise ValueError("SIDRA sem linha de dados")
            return {str(row.get("D1C", "")): clean(row.get("V")) for row in payload[1:]}
        except Exception as exc:  # pragma: no cover - rede externa
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"SIDRA {table}/{code}: {last_error}")


def load_sidra(codes: list[str]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    # PcD: V12785 pessoas com deficiência (2+); V13403 percentual.
    # TEA: V13267 população residente; V13408 percentual diagnosticado.
    def one(code):
        pcd = sidra_value(code, "10125", "12785,13403")
        tea = sidra_value(code, "10145", "13267,13408")
        return code, {
            "pcd_pessoas_2mais": pcd.get("12785"),
            "pcd_pct_2mais": pcd.get("13403"),
            "tea_pessoas": tea.get("13267"),
            "tea_pct": tea.get("13408"),
            "fonte_pcd": "SIDRA IBGE · tabela 10125 · 2022",
            "fonte_tea": "SIDRA IBGE · tabela 10145 · 2022",
        }

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(one, code) for code in codes]
        for future in as_completed(futures):
            code, values = future.result()
            result[code] = values
    return result


def normalize(all_rows: dict[str, dict[str, str]], sidra: dict[str, dict[str, object]], names: dict[str, str]):
    records = []
    for code in sorted(names):
        basic = all_rows["basico"][code]
        demo = all_rows["demografia"][code]
        race = all_rows["cor_raca"][code]
        dom = all_rows["domicilio"][code]
        dom2 = all_rows["domicilio2"][code]
        dom3 = all_rows["domicilio3"][code]
        envd = all_rows["entorno_domicilios"][code]
        envf = all_rows["entorno_faces"][code]
        envm = all_rows["entorno_moradores"][code]
        record = {
            "cod_mun": code,
            "nome": names[code],
            "referencia": "Censo 2022",
            "populacao": clean(basic.get("v0001")),
            "moradores_demografia": clean(demo.get("V01006")),
            "homens": clean(demo.get("V01007")),
            "mulheres": clean(demo.get("V01008")),
            "criancas_0_4": clean(demo.get("V01031")),
            "criancas_5_9": clean(demo.get("V01032")),
            "idosos_60_69": clean(demo.get("V01040")),
            "idosos_70_mais": clean(demo.get("V01041")),
            "indigenas": clean(race.get("V01321")),
            "pretos_pardos": add(race.get("V01318"), race.get("V01320")),
            "dom_ocupados_oficial": clean(dom.get("V00001")),
            "dom_improvisados": clean(dom.get("V00002")),
            "dom_coletivos_com_morador": clean(dom.get("V00003")),
            "dom_agua_rede": clean(dom2.get("V00111")),
            "dom_esgoto_rede": clean(dom2.get("V00309")),
            "entorno_dom_total": clean(envd.get("V05000")),
            "entorno_dom_via_pavimentada": clean(envd.get("V05006")),
            "entorno_dom_bueiro": clean(envd.get("V05009")),
            "entorno_dom_iluminacao": clean(envd.get("V05012")),
            "entorno_dom_ponto_onibus": clean(envd.get("V05015")),
            "entorno_dom_rampa": clean(envd.get("V05027")),
            "entorno_dom_sem_arvore": clean(envd.get("V05030")),
            "entorno_dom_1_2_arvores": clean(envd.get("V05031")),
            "entorno_dom_3_4_arvores": clean(envd.get("V05032")),
            "entorno_dom_5_mais_arvores": clean(envd.get("V05033")),
            "entorno_pavimentada_pct": pct(envd.get("V05006"), envd.get("V05000")),
            "entorno_bueiro_pct": pct(envd.get("V05009"), envd.get("V05000")),
            "entorno_iluminacao_pct": pct(envd.get("V05012"), envd.get("V05000")),
            "entorno_ponto_onibus_pct": pct(envd.get("V05015"), envd.get("V05000")),
            "entorno_rampa_pct": pct(envd.get("V05027"), envd.get("V05000")),
            # Os arquivos de entorno têm universos diferentes; preservamos
            # estes campos sem somar faces/moradores aos domicílios.
            # No arquivo de faces, o universo total é V05400 (V05100 pertence
            # a outra família de variáveis e não existe neste layout).
            "entorno_faces_total": clean(envf.get("V05400")),
            "entorno_moradores_total": clean(envm.get("V05200")),
            **sidra.get(code, {}),
        }
        records.append(record)
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, help="pasta com os ZIPs municipais; se omitida, baixa do FTP")
    parser.add_argument("--skip-sidra", action="store_true", help="não consultar SIDRA; exige pcd_tea.json ao lado do raw-dir")
    args = parser.parse_args()
    codes, names = read_target_codes()
    raw_dir = args.raw_dir or (ROOT / "_ibge_raw_agregados")
    paths = ensure_raw(raw_dir)
    all_rows: dict[str, dict[str, dict[str, str]]] = {}
    filtered: dict[str, list[dict[str, str]]] = {}
    fields_by_file: dict[str, list[str]] = {}
    for key, path in paths.items():
        fields, rows = csv_from_zip(path)
        selected = filter_rows(rows, set(codes))
        fields_by_file[key] = fields
        filtered[key] = selected
        all_rows[key] = {str(row["CD_MUN"]): row for row in selected}
    if args.skip_sidra:
        sidra = json.loads((raw_dir / "pcd_tea.json").read_text(encoding="utf-8"))
    else:
        sidra = load_sidra(codes)
        (raw_dir / "pcd_tea.json").write_text(json.dumps(sidra, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Quatro arquivos que correspondem aos anexos recebidos pelo usuário.
    pessoa_fields = list(dict.fromkeys(fields_by_file["basico"] + fields_by_file["demografia"] + fields_by_file["cor_raca"]))
    pessoa_rows = []
    for code in codes:
        pessoa_rows.append({**all_rows["basico"][code], **all_rows["demografia"][code], **all_rows["cor_raca"][code]})
    write_csv(DOWNLOADS / OUT_FILES["pessoa"], pessoa_fields, pessoa_rows)
    domicilio_fields = list(dict.fromkeys(fields_by_file["domicilio"] + fields_by_file["domicilio2"] + fields_by_file["domicilio3"]))
    domicilio_rows = [{**all_rows["domicilio"][code], **all_rows["domicilio2"][code], **all_rows["domicilio3"][code]} for code in codes]
    write_csv(DOWNLOADS / OUT_FILES["domicilio"], domicilio_fields, domicilio_rows)
    entorno_fields = list(dict.fromkeys(fields_by_file["entorno_domicilios"] + fields_by_file["entorno_faces"] + fields_by_file["entorno_moradores"]))
    entorno_rows = [{**all_rows["entorno_domicilios"][code], **all_rows["entorno_faces"][code], **all_rows["entorno_moradores"][code]} for code in codes]
    write_csv(DOWNLOADS / OUT_FILES["entorno"], entorno_fields, entorno_rows)

    normalized = normalize(all_rows, sidra, names)
    pcd_fields = ["CD_MUN", "NM_MUN", "ano", "pcd_pessoas_2mais", "pcd_pct_2mais", "tea_pessoas", "tea_pct", "fonte_pcd", "fonte_tea"]
    pcd_rows = [{
        "CD_MUN": m["cod_mun"], "NM_MUN": m["nome"], "ano": "2022",
        "pcd_pessoas_2mais": m.get("pcd_pessoas_2mais"), "pcd_pct_2mais": m.get("pcd_pct_2mais"),
        "tea_pessoas": m.get("tea_pessoas"), "tea_pct": m.get("tea_pct"),
        "fonte_pcd": m.get("fonte_pcd", ""), "fonte_tea": m.get("fonte_tea", ""),
    } for m in normalized]
    write_csv(DOWNLOADS / OUT_FILES["pcd_tea"], pcd_fields, pcd_rows)
    payload = {
        "meta": {
            "schema": 1,
            "gerado_em_utc": date.today().isoformat(),
            "referencia": "Censo 2022",
            "escopo": "118 municípios intersectantes da bacia Taquari-Antas; indicadores municipais, não recorte setorial na bacia",
            "fontes": {
                "agregados_municipais": FTP_MUNICIPAL,
                "pcd": "https://sidra.ibge.gov.br/tabela/10125",
                "tea": "https://sidra.ibge.gov.br/tabela/10145",
            },
            "observacoes": [
                "Valores IBGE com X, ., .. ou ... permanecem ausentes; não foram convertidos em zero.",
                "PcD/TEA são resultados preliminares da amostra, disponíveis no nível municipal; não são estimativas setoriais nem dentro da bacia.",
                "Entorno descreve domicílios/face/moradores selecionados pelo IBGE; não é inventário de pavimentação, drenagem ou acessibilidade de toda a malha viária.",
                "Use CD_MUN como chave para juntar os CSVs aos municípios_combinados.geojson.",
            ],
        },
        "municipios": normalized,
    }
    REFERENCIAS.mkdir(parents=True, exist_ok=True)
    (REFERENCIAS / "agregados_taquari_indicadores.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"municipios": len(normalized), "arquivos": list(OUT_FILES.values()), "json": str(REFERENCIAS / "agregados_taquari_indicadores.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
