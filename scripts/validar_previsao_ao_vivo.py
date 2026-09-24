#!/usr/bin/env python3
"""Valida o contrato mínimo do feed ao vivo antes da publicação."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "previsao_ao_vivo.json"
B_MAT = ROOT / "previne/assets/mat/RNAPREV__SANTA_TEREZA__02h__ALT__15inputs_VFINAL_20260731.mat"
B_SHA = "6E605B3DE4FD5AC53298EF9C82942EC9C7B53B21A43AB377C75989AFFFB258D0"
B_WORKBOOK = ROOT / "assets/audit_workbooks/modelo_2h_novo.xlsx"
B_WORKBOOK_SHA = "8F14E108498EC614953BBA347057E3E82BFC6B7CF5EC7BE5C532B3769A31474A"
P_MAT = ROOT / "previne/assets/mat/009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21.mat"
P_SHA = "9446EA5582F7EAFBFC1417AADA610AF258318EE1198A1E4D5C5A2C3FDECC685D"
P_WORKBOOK = ROOT / "assets/audit_workbooks/2H_ALT__009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21.xlsx"
P_WORKBOOK_SHA = "33487BF862AEA460C336BF098BBB3DEFE5DD2A0F1BD49396CFB78A18A34371E2"
FOUR_MAT = ROOT / "assets/mat/4H_ALT__V01_R00_BASELINE_nh52_nit10_cic100000.mat"
FOUR_SHA = "951394B8B8B3F2C45EE90379F85FE79EC274069692467DFDCF8222B58E281632"
FOUR_WORKBOOK = ROOT / "assets/audit_workbooks/4H_ALT__V01_R00_BASELINE_nh52_nit10_cic100000.xlsx"
FOUR_WORKBOOK_SHA = "EE1E3B4A06C35A61C7EAEFBB1128D61C47FC4582113C5CB65EA53BB5EBF57724"
FOUR_ID = "4H_ALT__V01_R00_BASELINE_nh52_nit10_cic100000"
FOUR_FB_ID = "4H_ALT_PRIO_12478_NH10_NIT10_CIC120000"
FOUR_FB_MAT = ROOT / "assets/mat/prioritario_prio_12478_nh10_nit10_cic120000.mat"
EIGHT_V1_MAT = ROOT / "previne/assets/mat/RNAPREV__SANTA_TEREZA__08h__ALT__V001__31inputs_63hiddens_20260821.mat"
EIGHT_V1_SHA = "CDA80F39A2A81644F7969984AD6AF262694508D5D56C3EB00CE4BF12B67A9571"
EIGHT_V1_ID = "STZ_H8_ALT_V001_31IN_63NH"
EIGHT_FB_ID = "T2_V1_3_NH_075_06_8h_alt_8H_ALT_C0217"
EIGHT_FB_MAT = ROOT / "assets/mat/T2_V1_3_NH_075_06_8h_alt_8H_ALT_C0217.mat"
EIGHT_V2_MAT = ROOT / "previne/assets/mat/RNAPREV__SANTA_TEREZA__08h__ALT__V002__28inputs_57hiddens_20260821.mat"
EIGHT_V2_SHA = "53424025359CED9A70DCCEEB4080B917992CF2DD3C8A2CBECB8CBB55AC2C1663"
EIGHT_FORMULA_CONTRACT = "stz_8h_excel_mae_20260825_v2"
EIGHT_FORMULAS = {
    "8h": (
        "modelo_8h_V001_CORRIGIDO_GUARDAS_20260825_235111.xlsx",
        "E675E77B671DBB6AC20E4A46230B851CA33B3A789AE6DBAA2A1C6409EB2BA9F6",
    ),
    "8h_v002": (
        "modelo_8h_V002_CORRIGIDO_GUARDAS_20260825_235111.xlsx",
        "9D036026B8DEDB7DA90F285CA39F1B13C53F194266D18DDFD46D106874044EDC",
    ),
}
REQUIRED = {"2h", "2h_versao_b", "4h", "8h", "8h_v002"}
REQUIRED_FIELDS = {"horizonte", "horizonte_h", "modelo", "tipo", "status"}
EXPECTED_HOURS = {"2h": 2, "2h_versao_b": 2, "4h": 4, "8h": 8, "8h_v002": 8}
EXPECTED_INPUTS = {"2h": 15, "2h_versao_b": 15, "4h": 26, "8h": 31, "8h_v002": 28}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def validate_data(data: dict, *, b_mat: Path = B_MAT) -> None:
    """Validate the public-feed contract without writing a feed."""
    if not isinstance(data, dict):
        raise SystemExit("feed precisa ser objeto JSON")
    serie_observada = data.get("serie_observada_ana")
    if not isinstance(serie_observada, list) or len(serie_observada) < 2:
        raise SystemExit("feed sem serie observada ANA suficiente para o panorama")
    horas_observadas = [str(p.get("hora") or "") for p in serie_observada if isinstance(p, dict)]
    niveis_observados = [p.get("nivel_cm") for p in serie_observada if isinstance(p, dict)]
    if len(horas_observadas) != len(serie_observada) or horas_observadas != sorted(horas_observadas):
        raise SystemExit("serie observada ANA invalida ou fora de ordem")
    if any(v is None for v in niveis_observados):
        raise SystemExit("serie observada ANA contem nivel ausente")
    if any(not (-500 <= float(v) <= 5000) for v in niveis_observados):
        raise SystemExit("serie observada ANA contem nivel fora da faixa plausivel")
    telemetria_publicada = data.get("telemetria_ultima_nivel_cm")
    if telemetria_publicada is not None and not (-500 <= float(telemetria_publicada) <= 5000):
        raise SystemExit("telemetria publicada fora da faixa plausivel")
    ultima_obs = serie_observada[-1]
    ultima_feed = str(data.get("telemetria_ultima_em") or "")[:16]
    if str(ultima_obs.get("hora") or "")[:16] != ultima_feed:
        raise SystemExit("ultimo ponto da serie observada nao coincide com a ultima telemetria publicada")
    if data.get("serie_observada_ana_n") != len(serie_observada):
        raise SystemExit("contador da serie observada ANA inconsistente")

    horizons = data.get("horizontes")
    if not isinstance(horizons, dict):
        raise SystemExit("feed sem objeto horizontes")
    keys = set(horizons)
    if keys != REQUIRED:
        raise SystemExit(f"horizontes inesperados: {sorted(keys)}; esperado {sorted(REQUIRED)}")
    if "cascata" in json.dumps(data, ensure_ascii=False).lower():
        raise SystemExit("feed ainda contem referencia legada a cascata")
    for key in REQUIRED:
        if not isinstance(horizons[key], dict):
            raise SystemExit(f"{key} precisa ser objeto")
    primary = horizons["2h"]
    shadow = horizons["2h_versao_b"]
    if primary.get("principal") is not True or primary.get("shadow_only"):
        raise SystemExit("2h principal com metadados inconsistentes")
    if shadow.get("shadow_only") is not True or shadow.get("principal"):
        raise SystemExit("2h versao B precisa permanecer em sombra")
    if horizons["8h"].get("principal") or horizons["8h_v002"].get("principal"):
        raise SystemExit("8h V001/V002 precisam permanecer experimentais")
    if horizons["8h_v002"].get("shadow_only") is not True:
        raise SystemExit("8h V002 precisa permanecer em sombra")
    for key, mat, mat_sha, workbook, workbook_sha, label in (
        ("2h", P_MAT, P_SHA, P_WORKBOOK, P_WORKBOOK_SHA, "modelo 2h principal"),
        ("2h_versao_b", b_mat, B_SHA, B_WORKBOOK, B_WORKBOOK_SHA, "versao B"),
        ("8h_v002", EIGHT_V2_MAT, EIGHT_V2_SHA, None, None, "modelo 8h V002"),
    ):
        item = horizons[key]
        if item.get("modelo_sha256") != mat_sha or sha256(mat) != mat_sha:
            raise SystemExit(f"hash do {label} nao confere")
        if workbook is not None:
            expected_ref = workbook.relative_to(ROOT).as_posix()
            if item.get("referencia_auditavel") != expected_ref:
                raise SystemExit(f"referencia auditavel do {label} nao confere")
            if item.get("referencia_auditavel_sha256") != workbook_sha or sha256(workbook) != workbook_sha:
                raise SystemExit(f"hash da referencia auditavel do {label} nao confere")

    four = horizons["4h"]
    if four.get("modelo") == FOUR_ID:
        if four.get("modelo_sha256") != FOUR_SHA or sha256(FOUR_MAT) != FOUR_SHA:
            raise SystemExit("hash do modelo 4h preferencial nao confere")
        if four.get("referencia_auditavel") != FOUR_WORKBOOK.relative_to(ROOT).as_posix():
            raise SystemExit("referencia auditavel do 4h preferencial nao confere")
        if four.get("referencia_auditavel_sha256") != FOUR_WORKBOOK_SHA or sha256(FOUR_WORKBOOK) != FOUR_WORKBOOK_SHA:
            raise SystemExit("hash da referencia auditavel do 4h preferencial nao confere")
    elif four.get("modelo") == FOUR_FB_ID:
        if four.get("modelo_sha256") != sha256(FOUR_FB_MAT):
            raise SystemExit("hash do fallback 4h nao confere")
        if four.get("fallback_ativo") is not True:
            raise SystemExit("fallback 4h precisa declarar fallback_ativo=true")
        if four.get("status_publicacao") != "fallback_operacional_experimental":
            raise SystemExit("fallback 4h sem status_publicacao explicito")
    else:
        raise SystemExit("modelo 4h nao autorizado no feed")

    eight = horizons["8h"]
    if eight.get("modelo") == EIGHT_V1_ID:
        if eight.get("modelo_sha256") != EIGHT_V1_SHA or sha256(EIGHT_V1_MAT) != EIGHT_V1_SHA:
            raise SystemExit("hash do modelo 8h V001 nao confere")
    elif eight.get("modelo") == EIGHT_FB_ID:
        if eight.get("modelo_sha256") != sha256(EIGHT_FB_MAT):
            raise SystemExit("hash do fallback 8h nao confere")
        if eight.get("fallback_ativo") is not True:
            raise SystemExit("fallback 8h precisa declarar fallback_ativo=true")
    else:
        raise SystemExit("modelo 8h nao autorizado no feed")

    for key in REQUIRED:
        item = horizons[key]
        if not isinstance(item, dict) or not REQUIRED_FIELDS.issubset(item):
            missing = sorted(REQUIRED_FIELDS - set(item)) if isinstance(item, dict) else sorted(REQUIRED_FIELDS)
            raise SystemExit(f"{key} sem campos obrigatorios: {missing}")
        if item.get("horizonte") != key:
            raise SystemExit(f"horizonte inconsistente em {key}")
        if item.get("horizonte_h") != EXPECTED_HOURS[key]:
            raise SystemExit(f"horizonte_h inconsistente em {key}")
        if not str(item.get("modelo") or "").strip() or not str(item.get("tipo") or "").strip():
            raise SystemExit(f"modelo/tipo ausente em {key}")
        if item.get("nivel_previsto_cm") is not None and item.get("status") is None:
            raise SystemExit(f"status ausente em {key}")
    for key in REQUIRED:
        item = horizons[key]
        if item.get("input_grade") != "hourly_exact":
            raise SystemExit(f"{key} sem grade hourly_exact")
        if item.get("input_contract_version") != "hourly_exact_v1":
            raise SystemExit(f"{key} sem contrato temporal hourly_exact_v1")
        # A grade temporal tambem vale quando o horizonte esta sem previsao:
        # um item indisponivel nao pode carregar uma base :15/:30/:45.
        hora_declarada = str(item.get("hora_modelo") or "")
        if hora_declarada:
            minuto = int(hora_declarada[14:16]) if len(hora_declarada) >= 16 and hora_declarada[14:16].isdigit() else -1
            segundo = int(hora_declarada[17:19]) if len(hora_declarada) >= 19 and hora_declarada[17:19].isdigit() else -1
            if minuto != 0 or segundo != 0:
                raise SystemExit(f"{key} fora da grade temporal: {hora_declarada}")
        audit = item.get("auditoria_inputs") or {}
        if item.get("nivel_previsto_cm") is None:
            if item.get("disponivel") is not False:
                raise SystemExit(f"{key} sem previsao precisa declarar disponivel=false")
            if audit.get("status") not in {"INVALIDO", "ATENCAO"}:
                raise SystemExit(f"{key} indisponivel sem auditoria de inputs explicita")
            continue
        if item.get("disponivel") is not True:
            raise SystemExit(f"{key} com previsao precisa declarar disponivel=true")
        if not (-500 <= float(item["nivel_previsto_cm"]) <= 5000):
            raise SystemExit(f"{key} publicou previsao fora da faixa plausivel")
        if audit.get("status") != "NORMAL":
            raise SystemExit(f"{key} publicou previsao com auditoria de inputs nao normal")
        if audit.get("formula_conferida_com_montador") is not True:
            raise SystemExit(f"{key} com formula de inputs nao conferida")
        if audit.get("n_inputs_nao_exatos", 0) != 0:
            raise SystemExit(f"{key} publicou inputs interpolados/vizinhos")
        vals = item.get("input_values_cm") or []
        expected_inputs = EXPECTED_INPUTS[key]
        if key == "4h" and item.get("modelo") == FOUR_FB_ID:
            expected_inputs = 5
        elif key == "8h" and item.get("modelo") == EIGHT_FB_ID:
            expected_inputs = 10
        if len(vals) != expected_inputs or item.get("inputs_total") != expected_inputs:
            raise SystemExit(f"{key} precisa publicar exatamente {expected_inputs} inputs")
        if key.startswith("8h") and (
            audit.get("usa_interpolacao_nivel") is not False
            or audit.get("usa_vizinho_nivel") is not False
        ):
            raise SystemExit(f"{key} sem declaracao estruturada de nivel exato")
    for key, (formula, formula_sha) in EIGHT_FORMULAS.items():
        item = horizons[key]
        audit = item.get("auditoria_inputs") or {}
        if key == "8h" and item.get("modelo") == EIGHT_FB_ID:
            if item.get("status_publicacao") != "fallback_operacional_experimental":
                raise SystemExit("fallback 8h sem status_publicacao explicito")
            if (
                audit.get("usa_interpolacao_nivel") is not False
                or audit.get("usa_vizinho_nivel") is not False
                or audit.get("ausencia_chuva_vira_zero") is not False
                or audit.get("janela_incompleta_vira_ausente") is not True
            ):
                raise SystemExit("fallback 8h sem contrato seguro de entradas")
            continue
        if item.get("formula_contract_version") != EIGHT_FORMULA_CONTRACT:
            raise SystemExit(f"{key} sem contrato das formulas do Excel-mae")
        if item.get("referencia_formula") != formula:
            raise SystemExit(f"{key} com referencia de formula inesperada")
        if item.get("referencia_formula_sha256") != formula_sha:
            raise SystemExit(f"{key} com hash da planilha-mae inesperado")
        fontes = item.get("fontes_chuva_8h") or {}
        if fontes.get("contrato_formula") != EIGHT_FORMULA_CONTRACT:
            raise SystemExit(f"{key} sem proveniencia das fontes de chuva")
        if fontes.get("grupo_18h_24h") != ["2851072", "A894", "432040401A"]:
            raise SystemExit(f"{key} com grupo 18h/24h divergente do Excel-mae")
        if fontes.get("grupo_6h") != ["A894", "432040401A"]:
            raise SystemExit(f"{key} com grupo 6h divergente do Excel-mae")
        if audit.get("ausencia_chuva_vira_zero") is not False and item.get("nivel_previsto_cm") is not None:
            raise SystemExit(f"{key} nao prova tratamento seguro de chuva ausente")
        if item.get("nivel_previsto_cm") is not None and audit.get("janela_incompleta_vira_ausente") is not True:
            raise SystemExit(f"{key} nao prova bloqueio de janela de chuva incompleta")
    four = horizons["4h"]
    audit = four.get("auditoria") or {}
    if audit.get("n_conferidas", 0) and audit.get("auditoria_versao") not in (None, "target_exact_v2"):
        raise SystemExit("auditoria 4h com versao de comparacao desconhecida")


def main() -> int:
    data = json.loads(FEED.read_text(encoding="utf-8"))
    validate_data(data)
    print(f"OK feed ao vivo: {', '.join(sorted(data['horizontes']))}; MAT B SHA={B_SHA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
