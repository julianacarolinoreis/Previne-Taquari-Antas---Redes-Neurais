#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Robô AO VIVO — PREVINE / Santa Tereza (86472600)
Roda no GitHub Actions (a cada ~5 min):
  1) busca a telemetria da ANA (níveis das estações)
  2) monta os 15 inputs do modelo 2h ALT ativo
  3) roda a RNA (.mat) -> variação prevista -> nível daqui a 2h
  4) escreve previsao_ao_vivo.json (que o site lê e mostra)

Modelo 2h ativo (desde 2026-08-06):
  009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21
  (mesmos 15 inputs ST + Linha Jose Julio do antigo VFINAL;
   PERS teste ~0,97 · NASH ~0,996 · MAE teste ~3,5 cm)

EXPERIMENTAL — não é alerta oficial.
"""
import os, json, hashlib, datetime as dt, time, urllib.request, xml.etree.ElementTree as ET
import bisect
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from scipy.io import loadmat

BRT = dt.timezone(dt.timedelta(hours=-3))

def agora_brt():
    return dt.datetime.now(BRT).replace(tzinfo=None)

# ---- config ----
MODELO_MAT = "previne/assets/mat/009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21.mat"
MODELO_MAT_SHA256 = "9446EA5582F7EAFBFC1417AADA610AF258318EE1198A1E4D5C5A2C3FDECC685D"
MODELO_WORKBOOK = "assets/audit_workbooks/2H_ALT__009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21.xlsx"
MODELO_WORKBOOK_SHA256 = "33487BF862AEA460C336BF098BBB3DEFE5DD2A0F1BD49396CFB78A18A34371E2"
MODELO_2H_B_MAT = "previne/assets/mat/RNAPREV__SANTA_TEREZA__02h__ALT__15inputs_VFINAL_20260731.mat"
MODELO_2H_B_ID = "STZ_2H_ALT_VFINAL_B_20260731"
MODELO_2H_B_SHA256 = "6E605B3DE4FD5AC53298EF9C82942EC9C7B53B21A43AB377C75989AFFFB258D0"
MODELO_2H_B_WORKBOOK = "assets/audit_workbooks/modelo_2h_novo.xlsx"
MODELO_2H_B_WORKBOOK_SHA256 = "8F14E108498EC614953BBA347057E3E82BFC6B7CF5EC7BE5C532B3769A31474A"
MODELO_4H_PRO_MAT = "assets/mat/4H_ALT__V01_R00_BASELINE_nh52_nit10_cic100000.mat"
MODELO_4H_PRO_ID = "4H_ALT__V01_R00_BASELINE_nh52_nit10_cic100000"
MODELO_4H_PRO_MAT_SHA256 = "951394B8B8B3F2C45EE90379F85FE79EC274069692467DFDCF8222B58E281632"
MODELO_4H_PRO_WORKBOOK = "assets/audit_workbooks/4H_ALT__V01_R00_BASELINE_nh52_nit10_cic100000.xlsx"
MODELO_4H_PRO_WORKBOOK_SHA256 = "EE1E3B4A06C35A61C7EAEFBB1128D61C47FC4582113C5CB65EA53BB5EBF57724"
MODELO_8H_MAT = "previne/assets/mat/RNAPREV__SANTA_TEREZA__08h__ALT__V001__31inputs_63hiddens_20260821.mat"
MODELO_8H_ID = "STZ_H8_ALT_V001_31IN_63NH"
MODELO_8H_MAT_SHA256 = "CDA80F39A2A81644F7969984AD6AF262694508D5D56C3EB00CE4BF12B67A9571"
MODELO_8H_V002_MAT = "previne/assets/mat/RNAPREV__SANTA_TEREZA__08h__ALT__V002__28inputs_57hiddens_20260821.mat"
MODELO_8H_V002_ID = "STZ_H8_ALT_V002_28IN_57NH"
MODELO_8H_V002_MAT_SHA256 = "53424025359CED9A70DCCEEB4080B917992CF2DD3C8A2CBECB8CBB55AC2C1663"
# As planilhas de formula dos 8h usam Passo Carreiro 86500000 no lugar do
# CEMADEN. Todos os sinais de nivel e chuva sao ancorados em hora cheia.
POSTO_CHUVA_PASSO_CARREIRO = "86500000"
HORIZONTE = "2h"
COMBO = "009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21"
BANKFULL_CM = 400           # zero da mancha (provisório): ancorado na cota de
                            # inundação oficial (15 m) via ANADEM — ver
                            # codigo_python/04_zero_regua/. Definitivo aguarda a
                            # cota oficial do zero da régua (SGB/ANA).
SAIDA = "previsao_ao_vivo.json"   # na RAIZ: é onde o simulador publicado lê
HISTORICO_SAIDA = "historico_previsoes_ao_vivo.json"
# Guardrails operacionais: servem para sinalizar degradaÃ§Ã£o recente no painel;
# nÃ£o substituem a validaÃ§Ã£o offline nem alteram a previsÃ£o do MAT.
LIVE_WARN_MAE_24H_CM = 30.0
LIVE_WARN_MAX_24H_CM = 100.0
ANA = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ESTACOES_NIVEL = [
    "86472600", "86472000", "86125130", "86306000", "86448000", "86507000",
    "86125500", "86298000", "86430900", "86447000", "86505500",
]
ESTACOES = ESTACOES_NIVEL
METADADOS_ESTACOES = {
    "86472600": {"lat": -29.1781, "lon": -51.7322, "papel": "Estacao alvo"},
    "86472000": {"lat": -29.0978, "lon": -51.6997, "papel": "Montante"},
    "86125130": {"lat": -28.5919, "lon": -51.3247, "papel": "Montante"},
    "86306000": {"lat": -29.0133, "lon": -51.3675, "papel": "Montante"},
    "86448000": {"lat": -29.0292, "lon": -51.5219, "papel": "Montante"},
    "86125500": {"lat": None, "lon": None, "papel": "Montante - input 4h PRO / 8h V001-V002"},
    "86298000": {"lat": None, "lon": None, "papel": "Montante - input 4h PRO / 8h V001-V002"},
    "86430900": {"lat": None, "lon": None, "papel": "Montante - input 8h V001"},
    "86447000": {"lat": None, "lon": None, "papel": "Montante - input 8h V002"},
    "86505500": {"lat": None, "lon": None, "papel": "Montante - input 8h V002"},
}
POSTOS_CHUVA_36H = ["2851044", "2851072", "86488000", "86490500", "86497000", "86505500", "86507000"]
# O painel é atualizado frequentemente e preserva a última previsão válida
# quando a ANA está indisponível. Limites curtos evitam que uma API presa
# consuma todo o intervalo entre ciclos.
ANA_TIMEOUT_NIVEL_S = 12
ANA_TIMEOUT_CHUVA_S = 8
ANA_RETRIES_NIVEL = 1
ANA_RETRIES_CHUVA = 1
ULTIMA_RAW = {}
NOMES_ESTACOES = {
    "86472600": "Santa Tereza",
    "86472000": "Linha Jose Julio / Rio das Antas montante",
    "86125130": "Ituim",
    "86306000": "Nova Roma do Sul / Rio das Antas",
    "86448000": "Veranopolis / Rio das Antas",
    "86507000": "Carreiro",
    "86125500": "Estacao 86125500 - montante (input 4h PRO)",
    "86298000": "Estacao 86298000 - montante (input 4h PRO)",
    "86430900": "Estacao 86430900",
    "86447000": "Estacao 86447000",
    "86500000": "Passo Carreiro (chuva)",
    "2851044": "Posto chuva Carreiro 2851044",
    "2851072": "Posto chuva Carreiro-Prata 2851072",
    "86488000": "Posto chuva Carreiro 86488000",
    "86490500": "Posto chuva Carreiro 86490500",
    "86497000": "Posto chuva Carreiro 86497000",
    "86505500": "Posto chuva Carreiro 86505500",
}
MODELOS = [
    {
        "horizonte": "2h",
        "horizonte_h": 2,
        "tipo": "ALT",
        "modelo": COMBO,
        "mat": MODELO_MAT,
        "inputs_total": 15,
        "montador": "2h_alt_15inputs",
        "input_contract_version": "hourly_exact_v1",
        "input_grade": "hourly_exact",
        "principal": True,
        "ativo_ao_vivo": True,
        "versao": "A / OPERA2",
        "status_publicacao": "principal",
        "modelo_sha256": MODELO_MAT_SHA256,
        "referencia_auditavel": MODELO_WORKBOOK,
        "referencia_auditavel_sha256": MODELO_WORKBOOK_SHA256,
        "input_labels": [
            "Santa Tereza - nivel atual (D0h)", "Santa Tereza - D-1h", "Santa Tereza - D-2h",
            "Santa Tereza - D-4h", "Santa Tereza - aceleracao A-1h", "Santa Tereza - aceleracao A-2h",
            "Santa Tereza - aceleracao A-4h", "Santa Tereza - aceleracao A-8h", "Santa Tereza - aceleracao A-12h",
            "Linha Jose Julio - nivel atual", "Linha Jose Julio - D-1h", "Linha Jose Julio - D-2h",
            "Linha Jose Julio - D-5h", "Linha Jose Julio - aceleracao A-12h", "Linha Jose Julio - aceleracao A-20h",
        ],
    },
    {
        "horizonte": "2h_versao_b",
        "rotulo": "2h versao B (VFINAL)",
        "horizonte_h": 2,
        "tipo": "ALT_VERSAO_B",
        "modelo": MODELO_2H_B_ID,
        "mat": MODELO_2H_B_MAT,
        "inputs_total": 15,
        "montador": "2h_alt_15inputs",
        # O .mat da versao B foi treinado com o mesmo Ptot/Ttot horario do
        # modelo principal. A aba OPERA2 de 15 minutos e uma tabela
        # operacional auxiliar, nao a grade de treinamento do .mat.
        "input_contract_version": "hourly_exact_v1",
        "input_grade": "hourly_exact",
        "principal": False,
        "ativo_ao_vivo": True,
        "shadow_only": True,
        "versao": "B / OPERA3 / VFINAL 2026-07-31",
        "status_publicacao": "sombra_experimental",
        "modelo_sha256": MODELO_2H_B_SHA256,
        "referencia_auditavel": MODELO_2H_B_WORKBOOK,
        "referencia_auditavel_sha256": MODELO_2H_B_WORKBOOK_SHA256,
        "proveniencia_nota": "MAT v7.3 recebido como RNAPREV__SANTA_TEREZA__02h__ALT__15inputs_VFINAL_20260731.mat; referencia auditavel central modelo_2h_novo.xlsx, aba VAR, e EXCEL interno modelo_2h_novo.xlsx; Ptot/Ttot coincidem com o modelo horario principal. O workbook arquivado modelo_2h_versao_b_20260812.xlsx permanece apenas como evidencia operacional auxiliar (OPERA2/OPERA3, 15 minutos) e nao define a grade do treinamento. Metadados legados do MAT: nh=31, nit=10, Cic=30000. A versao B continua exclusivamente em sombra.",
        "input_labels": [
            "Santa Tereza - nivel atual (D0h)", "Santa Tereza - D-1h", "Santa Tereza - D-2h",
            "Santa Tereza - D-4h", "Santa Tereza - aceleracao A-1h", "Santa Tereza - aceleracao A-2h",
            "Santa Tereza - aceleracao A-4h", "Santa Tereza - aceleracao A-8h", "Santa Tereza - aceleracao A-12h",
            "Linha Jose Julio - nivel atual", "Linha Jose Julio - D-1h", "Linha Jose Julio - D-2h",
            "Linha Jose Julio - D-5h", "Linha Jose Julio - aceleracao A-12h", "Linha Jose Julio - aceleracao A-20h",
        ],
    },
    {
        "horizonte": "4h",
        "horizonte_h": 4,
        "tipo": "ALT",
        "modelo": MODELO_4H_PRO_ID,
        "mat": MODELO_4H_PRO_MAT,
        "inputs_total": 26,
        "montador": "4h_alt_v01_26",
        "principal": True,
        "versao": "PRO",
        "ativo_ao_vivo": True,
        "input_contract_version": "hourly_exact_v1",
        "input_grade": "hourly_exact",
        "modelo_sha256": MODELO_4H_PRO_MAT_SHA256,
        "referencia_auditavel": MODELO_4H_PRO_WORKBOOK,
        "referencia_auditavel_sha256": MODELO_4H_PRO_WORKBOOK_SHA256,
        "input_labels": [
            "Santa Tereza - nivel atual (D0h)", "Santa Tereza - D-1h", "Santa Tereza - D-2h",
            "Santa Tereza - D-4h", "Santa Tereza - aceleracao A-1h", "Santa Tereza - aceleracao A-4h",
            "Santa Tereza - aceleracao A-12h", "Linha Jose Julio - nivel atual", "Linha Jose Julio - D-1h",
            "Linha Jose Julio - D-2h", "Linha Jose Julio - D-4h", "Linha Jose Julio - aceleracao A-2h",
            "Linha Jose Julio - aceleracao A-8h", "Linha Jose Julio - aceleracao A-16h",
            "86125500 - nivel atual", "86125500 - D-2h", "86125500 - D-6h", "86125500 - D-10h", "86125500 - D-14h",
            "86298000 - nivel atual", "86298000 - D-2h", "86298000 - D-6h", "86298000 - D-10h", "86298000 - aceleracao A-2h",
            "86298000 - aceleracao A-8h", "86298000 - aceleracao A-16h",
        ],
        "input_anchor_note": "NIVEL_ATUAL_CM e a ancora de reconstrução e persistência; os 26 sinais acima (incluindo os dois níveis-âncora montantes) são enviados ao MAT.",
    },
    {
        "horizonte": "8h",
        "rotulo": "8h V001",
        "horizonte_h": 8,
        "tipo": "ALT",
        "modelo": MODELO_8H_ID,
        "mat": MODELO_8H_MAT,
        "inputs_total": 31,
        "montador": "8h_alt_v001",
        "input_contract_version": "hourly_exact_v1",
        "input_grade": "hourly_exact",
        "principal": False,
        "ativo_ao_vivo": True,
        "versao": "V001",
        "status_publicacao": "experimental",
        "modelo_sha256": MODELO_8H_MAT_SHA256,
    },
    {
        "horizonte": "8h_v002",
        "rotulo": "8h V002",
        "horizonte_h": 8,
        "tipo": "ALT",
        "modelo": MODELO_8H_V002_ID,
        "mat": MODELO_8H_V002_MAT,
        "inputs_total": 28,
        "montador": "8h_alt_v002",
        "input_contract_version": "hourly_exact_v1",
        "input_grade": "hourly_exact",
        "principal": False,
        "ativo_ao_vivo": True,
        "shadow_only": True,
        "versao": "V002",
        "status_publicacao": "sombra_experimental",
        "modelo_sha256": MODELO_8H_V002_MAT_SHA256,
    },
]

def _local(tag):                          # remove {namespace} do nome da tag
    return tag.rsplit("}", 1)[-1]

def _parse_hora(dh):
    dh = dh.strip()
    try:
        return dt.datetime.fromisoformat(dh.replace("T", " ")[:19])
    except Exception:
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
            try: return dt.datetime.strptime(dh[:19], fmt)
            except Exception: pass
    return None

def _extrair_serie(root):
    """Percorre o XML e monta {timestamp_da_leitura: nivel_cm}.

    A previsão ao vivo deve ser recalculada assim que houver dado novo. Por
    isso preservamos leituras intermediárias (15/30/45 min) e deixamos cada
    modelo escolher o timestamp mais recente com todos os seus lags disponíveis.
    """
    serie = {}
    ultima_raw = None
    for row in root.iter():
        campos = {_local(ch.tag): (ch.text or "") for ch in row}
        dh = campos.get("DataHora") or campos.get("Data_Hora") or campos.get("DataHoraMedicao")
        niv = campos.get("Nivel")
        if niv in (None, ""):
            niv = campos.get("nivel") or campos.get("NivelSensor") or campos.get("Cota")
        if not dh or niv in (None, ""):  continue
        t = _parse_hora(dh)
        if t is None:  continue
        try:
            valor = float(str(niv).replace(",", "."))
        except Exception:
            continue
        if ultima_raw is None or t > ultima_raw[0]:
            ultima_raw = (t, valor)
        serie[t.replace(second=0, microsecond=0)] = valor
    return serie, ultima_raw

def _extrair_serie_chuva(root):
    """Retorna chuva horaria por posto.

    Alguns postos chegam em passos de 15 min. Para reconstruir a chuva
    horaria usada nos modelos, somamos as leituras dentro da mesma hora.
    """
    acumulado_hora = {}
    ultima_raw = None
    for row in root.iter():
        campos = {_local(ch.tag): (ch.text or "") for ch in row}
        dh = campos.get("DataHora") or campos.get("Data_Hora") or campos.get("DataHoraMedicao")
        chuva = campos.get("Chuva") or campos.get("chuva") or campos.get("Precipitacao") or campos.get("Precipitação")
        if not dh or chuva in (None, ""):
            continue
        t = _parse_hora(dh)
        if t is None:
            continue
        try:
            valor = float(str(chuva).replace(",", "."))
        except Exception:
            continue
        if ultima_raw is None or t > ultima_raw[0]:
            ultima_raw = (t, valor)
        hora = t.replace(minute=0, second=0, microsecond=0)
        acumulado_hora[hora] = acumulado_hora.get(hora, 0.0) + valor
    return acumulado_hora, ultima_raw

def _serie_de_xml(xml):
    """Extrai a série; trata o caso .asmx em que o DataTable vem como
    string XML escapada dentro de um <string>...</string>."""
    root = ET.fromstring(xml)
    serie, ultima_raw = _extrair_serie(root)
    if not serie and (root.text or "").strip().startswith("<"):
        try:
            serie, ultima_raw = _extrair_serie(ET.fromstring(root.text))   # XML aninhado (desescapado)
        except Exception:
            pass
    return serie, len(xml), ultima_raw

def _serie_chuva_de_xml(xml):
    root = ET.fromstring(xml)
    serie, ultima_raw = _extrair_serie_chuva(root)
    if not serie and (root.text or "").strip().startswith("<"):
        try:
            serie, ultima_raw = _extrair_serie_chuva(ET.fromstring(root.text))
        except Exception:
            pass
    return serie, len(xml), ultima_raw

def buscar_ana(cod, dias=5):
    """Retorna dict {timestamp_da_leitura: nivel_cm}. Usa uma janela de datas explícita
    (a ANA responde ErrorTable quando as datas vêm em branco); mantém o modo
    'datas em branco' apenas como reserva."""
    fim = agora_brt()
    ini = fim - dt.timedelta(days=dias)
    tentativas = [
        f"{ANA}?codEstacao={cod}&dataInicio={ini:%d/%m/%Y}&dataFim={fim:%d/%m/%Y}",
        f"{ANA}?codEstacao={cod}&dataInicio=&dataFim=",
    ]
    for rodada in range(1, ANA_RETRIES_NIVEL + 1):
        for url in tentativas:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "previne-robo/1.0"})
                xml = urllib.request.urlopen(req, timeout=ANA_TIMEOUT_NIVEL_S).read()
                serie, nbytes, ultima_raw = _serie_de_xml(xml)
                print(f"[ANA {cod}] tentativa={rodada} {url.split('?')[1][:40]}... bytes={nbytes} linhas={len(serie)}")
                if ultima_raw:
                    ULTIMA_RAW[cod] = ultima_raw
                if serie:
                    return serie
                if nbytes:                          # veio resposta mas 0 linhas -> mostra amostra
                    amostra = xml[:600].decode("utf-8", "replace").replace("\n", " ")
                    print(f"[ANA {cod}] amostra: {amostra}")
            except Exception as e:
                print(f"[ANA {cod}] tentativa={rodada} erro: {e}")
        if rodada < ANA_RETRIES_NIVEL:
            time.sleep(4 * rodada)
    return {}

def buscar_ana_chuva(cod, dias=5):
    fim = agora_brt()
    ini = fim - dt.timedelta(days=dias)
    tentativas = [
        f"{ANA}?codEstacao={cod}&dataInicio={ini:%d/%m/%Y}&dataFim={fim:%d/%m/%Y}",
        f"{ANA}?codEstacao={cod}&dataInicio=&dataFim=",
    ]
    for rodada in range(1, ANA_RETRIES_CHUVA + 1):
        for url in tentativas:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "previne-robo/1.0"})
                xml = urllib.request.urlopen(req, timeout=ANA_TIMEOUT_CHUVA_S).read()
                serie, nbytes, ultima_raw = _serie_chuva_de_xml(xml)
                print(f"[ANA chuva {cod}] tentativa={rodada} {url.split('?')[1][:40]}... bytes={nbytes} horas={len(serie)}")
                if ultima_raw:
                    ULTIMA_RAW[f"chuva_{cod}"] = ultima_raw
                if serie:
                    return serie
            except Exception as e:
                print(f"[ANA chuva {cod}] tentativa={rodada} erro: {e}")
        if rodada < ANA_RETRIES_CHUVA:
            time.sleep(4 * rodada)
    return {}


def buscar_chuvas_8h(series):
    """Busca os postos de chuva exclusivos das formulas V001/V002 de 8h."""
    extra = ["86472600", "86472000", POSTO_CHUVA_PASSO_CARREIRO]
    postos = buscar_series_paralelo(extra, buscar_ana_chuva, max_workers=3)
    postos["2851072"] = dict(series.get("__chuva36h_postos__", {}).get("2851072") or {})
    if not postos["2851072"]:
        postos["2851072"] = buscar_ana_chuva("2851072")
    series.setdefault("__chuva8h_fontes__", {})["passo_carreiro"] = POSTO_CHUVA_PASSO_CARREIRO
    return postos


def buscar_series_paralelo(codigos, funcao, max_workers=6):
    """Consulta as estações independentes em paralelo.

    A ANA costuma deixar uma estação presa por dezenas de segundos. A versão
    anterior consultava todas em série, fazendo um único timeout atrasar o
    ciclo inteiro. O limite de seis conexões reduz a latência sem abrir uma
    enxurrada de requisições ao serviço; a ordem do dicionário permanece a
    ordem declarada dos códigos.
    """
    codigos = list(codigos)
    if not codigos:
        return {}
    workers = max(1, min(int(max_workers), len(codigos)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ana-live") as executor:
        resultados = list(executor.map(funcao, codigos))
    return dict(zip(codigos, resultados))

# Buracos da ANA (ex.: 10:45→13:00 e 15:45→18:00 em 2026-08-06) quebravam o
# 2h (lags/acelerações pedem horário exato) e a auditoria (alvo sem linha).
# Interpolamos/aproximamos só dentro destes tetos — além disso, fica None.
NIVEL_MAX_GAP = dt.timedelta(minutes=150)
AUDITORIA_MAX_GAP = dt.timedelta(minutes=30)
# A auditoria de desempenho não pode comparar uma previsão horária com uma
# leitura de 15/30 min antes ou depois: em uma subida rápida isso fabrica erro.
# O limite acima continua servindo apenas para decidir quando um alvo ausente
# pode ser marcado como sem dado; a observação usada no erro é sempre EXATA.
AUDITORIA_VERSAO = "target_exact_v2"
# Um valor ainda dentro de NIVEL_MAX_GAP pode estar deslocado no tempo.  A
# RNA foi treinada em passos horarios; por isso a previsao continua disponivel
# com uma leitura proxima, mas o pacote deve denunciar quando algum input ficou
# mais de meia hora sem leitura na hora solicitada.
INPUT_WARN_MAX_AGE = dt.timedelta(minutes=30)
# Guarda de plausibilidade para a telemetria de nível. A unidade publicada
# pela ANA/SGB é cm; valores acima de 50 m não são aceitos como entrada de
# nenhuma RNA sem revisão manual. O valor bruto continua preservado no status
# da estação para auditoria, mas não chega ao montador nem ao MAT.
NIVEL_PLAUSIVEL_MIN_CM = -500.0
NIVEL_PLAUSIVEL_MAX_CM = 5000.0
# Algumas estações montantes usam uma cota absoluta diferente da régua de
# Santa Tereza. A V01 de 26 entradas foi treinada com 86125500 nessa escala
# (aprox. 24.000--25.300 cm); aplicar o teto de Santa Tereza a ela bloquearia
# uma entrada válida. O limite continua conservador e específico por estação.
NIVEL_PLAUSIVEL_MAX_POR_ESTACAO_CM = {
    "86125500": 30000.0,
    "86430900": 35000.0,
    "86448000": 30000.0,
}
# O V01_R10 foi treinado com uma linha horária completa.  Não é seguro
# alimentar a rede com uma mistura de leituras de 15 min, interpolação e
# vizinhos: isso muda a semântica dos 24 sinais, mesmo quando todos têm valor.
def _vizinhos_serie(serie, t):
    """Retorna (antes, depois) mais próximos de t em serie (dict timestamp→valor)."""
    if not serie:
        return None, None
    keys = sorted(serie)
    i = bisect.bisect_left(keys, t)
    antes = keys[i - 1] if i > 0 else None
    depois = keys[i] if i < len(keys) else None
    return antes, depois

def _limites_plausiveis(estacao=None):
    return (
        NIVEL_PLAUSIVEL_MIN_CM,
        NIVEL_PLAUSIVEL_MAX_POR_ESTACAO_CM.get(estacao, NIVEL_PLAUSIVEL_MAX_CM),
    )

def _nivel_plausivel(valor, estacao=None):
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return False
    minimo, maximo = _limites_plausiveis(estacao)
    return minimo <= valor <= maximo

def _marcar_fora_faixa(base, valores, estacao=None):
    minimo, maximo = _limites_plausiveis(estacao)
    base.update({
        "metodo": "FORA_FAIXA",
        "valor_bruto_cm": [round(float(v), 3) for v in valores if v is not None],
        "limites_plausiveis_cm": [minimo, maximo],
    })
    return None, base

def nivel_com_proveniencia(serie, t, max_gap=NIVEL_MAX_GAP, estacao=None):
    """Resolve um nivel e registra como ele foi obtido.

    O valor numerico segue a regra historica de ``nivel`` (exato, interpolacao
    linear ou vizinho mais proximo dentro de ``max_gap``).  A proveniencia e
    essencial para diferenciar uma aceleracao calculada com quatro leituras
    horarias reais de outra calculada com uma leitura atrasada.
    """
    base = {
        "horario_solicitado": t.isoformat(timespec="minutes") if t else None,
        "metodo": "AUSENTE",
        "horarios_usados": [],
        "idade_max_min": None,
    }
    if not serie:
        return None, base
    if t in serie:
        if not _nivel_plausivel(serie[t], estacao):
            return _marcar_fora_faixa(base, [serie[t]], estacao)
        base.update({
            "metodo": "EXATO",
            "horarios_usados": [t.isoformat(timespec="minutes")],
            "idade_max_min": 0.0,
        })
        return float(serie[t]), base
    antes, depois = _vizinhos_serie(serie, t)
    if antes is not None and depois is not None and antes != depois:
        if (t - antes) <= max_gap and (depois - t) <= max_gap:
            if not _nivel_plausivel(serie[antes], estacao) or not _nivel_plausivel(serie[depois], estacao):
                return _marcar_fora_faixa(base, [serie[antes], serie[depois]], estacao)
            span = (depois - antes).total_seconds()
            if span > 0:
                w = (t - antes).total_seconds() / span
                base.update({
                    "metodo": "INTERPOLADO",
                    "horarios_usados": [
                        antes.isoformat(timespec="minutes"),
                        depois.isoformat(timespec="minutes"),
                    ],
                    "idade_max_min": round(max(
                        (t - antes).total_seconds(),
                        (depois - t).total_seconds(),
                    ) / 60.0, 1),
                })
                return float(serie[antes] * (1.0 - w) + serie[depois] * w), base
    candidatos = []
    if antes is not None and (t - antes) <= max_gap:
        candidatos.append(antes)
    if depois is not None and (depois - t) <= max_gap:
        candidatos.append(depois)
    if not candidatos:
        return None, base
    melhor = min(candidatos, key=lambda k: abs((k - t).total_seconds()))
    if not _nivel_plausivel(serie[melhor], estacao):
        return _marcar_fora_faixa(base, [serie[melhor]], estacao)
    base.update({
        "metodo": "VIZINHO_MAIS_PROXIMO",
        "horarios_usados": [melhor.isoformat(timespec="minutes")],
        "idade_max_min": round(abs((melhor - t).total_seconds()) / 60.0, 1),
    })
    return float(serie[melhor]), base


def nivel(serie, t, max_gap=NIVEL_MAX_GAP, estacao=None):
    """Nível no timestamp t.

    1) match exato; 2) interpolação linear se os dois vizinhos cabem em max_gap;
    3) vizinho mais perto dentro de max_gap. Sem isso o robô congela a previsão
    2h numa hora antiga e o gráfico fica incoerente com a telemetria atual.
    """
    valor, _ = nivel_com_proveniencia(serie, t, max_gap=max_gap, estacao=estacao)
    return valor

def observar_nivel(serie, alvo, max_gap=AUDITORIA_MAX_GAP):
    """Observado para auditoria: exato ou vizinho real dentro de max_gap.

    Devolve (valor_cm, timestamp_usado) ou (None, None). Não interpola — o erro
    gravado precisa apontar para uma leitura ANA real.
    """
    if not serie or alvo is None:
        return None, None
    if alvo in serie:
        if not _nivel_plausivel(serie[alvo]):
            return None, None
        return float(serie[alvo]), alvo
    antes, depois = _vizinhos_serie(serie, alvo)
    candidatos = []
    if antes is not None and (alvo - antes) <= max_gap:
        if _nivel_plausivel(serie[antes]):
            candidatos.append(antes)
    if depois is not None and (depois - alvo) <= max_gap:
        if _nivel_plausivel(serie[depois]):
            candidatos.append(depois)
    if not candidatos:
        return None, None
    usado = min(candidatos, key=lambda k: abs((k - alvo).total_seconds()))
    return float(serie[usado]), usado

def chuva_media_acum_36h(series, t):
    """Soma 36 valores horarios da media dos postos com chuva disponivel."""
    postos = series.get("__chuva36h_postos__", {})
    if not postos:
        return None
    total = 0.0
    for h in range(36):
        hora = t - dt.timedelta(hours=h)
        vals = [posto.get(hora) for posto in postos.values() if posto.get(hora) is not None]
        if not vals:
            return None
        total += sum(vals) / len(vals)
    return total

def _n(series, cod, t, h=0):
    return nivel(series.get(cod, {}), t - dt.timedelta(hours=h), estacao=cod)


def _eh_hora_cheia(t):
    return t is not None and t.minute == 0 and t.second == 0 and t.microsecond == 0


def _n_exato(series, cod, t, h=0):
    """Leitura exatamente em t-h; nunca interpola nem usa vizinho."""
    hora = t - dt.timedelta(hours=h)
    if not _eh_hora_cheia(hora):
        return None
    serie = series.get(cod) or {}
    valor = serie.get(hora)
    if valor is None or not _nivel_plausivel(valor, cod):
        return None
    return float(valor)


def _D_exato(series, cod, t, h):
    a, b = _n_exato(series, cod, t, 0), _n_exato(series, cod, t, h)
    return None if None in (a, b) else a - b


def _D(series, cod, t, h):
    a, b = _n(series, cod, t, 0), _n(series, cod, t, h)
    return None if None in (a, b) else a - b

def _acel_offsets_excel(cod, h):
    """Retorna os quatro offsets usados pela planilha-base para uma aceleração."""
    # Exceção deliberada do Excel do 2h: Acel-20h compara a variação atual
    # com a variação entre t-19h e t-20h (lag de uma hora), não t-20h/t-21h.
    if cod == "86472000" and h == 20:
        return (0, 1, 19, 20)
    return (0, 1, h, h + 1)

def _A_curv(series, cod, t, h):
    if h < 1:
        return None
    a = _n(series, cod, t, h - 1)
    b = _n(series, cod, t, h)
    c = _n(series, cod, t, h + 1)
    return None if None in (a, b, c) else a - 2 * b + c

def montar_inputs(series, t):
    """Monta os 15 inputs na hora t, na ORDEM EXATA das colunas K..Y do modelo
    (workbook AUDITAVEL_INPUTS_RNA, validado 100% contra o .mat).

    Convenções (validadas linha a linha):
      D-Xh(s) = n(t) - n(t-Xh)                                  (diferença p/ trás)
      A-Xh(s) = [n(t)-n(t-1h)] - [n(t-Xh)-n(t-Xh-1h)]           (aceleração)
    """
    def n(cod, h=0):
        return nivel(series[cod], t - dt.timedelta(hours=h), estacao=cod)
    def D(cod, h):
        a, b = n(cod, 0), n(cod, h)
        return None if None in (a, b) else a - b
    def A(cod, h):
        offsets = _acel_offsets_excel(cod, h)
        a, b, c, d = (n(cod, offset) for offset in offsets)
        return None if None in (a, b, c, d) else (a - b) - (c - d)
    st0 = n("86472600", 0)
    inputs = [
        n("86472600", 0),      # inp01 ST nivel atual
        D("86472600", 1),      # inp02 ST D-1h
        D("86472600", 2),      # inp03 ST D-2h
        D("86472600", 4),      # inp04 ST D-4h
        A("86472600", 1),      # inp05 ST A-1h
        A("86472600", 2),      # inp06 ST A-2h
        A("86472600", 4),      # inp07 ST A-4h
        A("86472600", 8),      # inp08 ST A-8h
        A("86472600", 12),     # inp09 ST A-12h
        n("86472000", 0),      # inp10 Linha Jose Julio / Antas nivel atual
        D("86472000", 1),      # inp11 Linha Jose Julio / Antas D-1h
        D("86472000", 2),      # inp12 Linha Jose Julio / Antas D-2h
        D("86472000", 5),      # inp13 Linha Jose Julio / Antas D-5h
        A("86472000", 12),     # inp14 Linha Jose Julio / Antas A-12h
        A("86472000", 20),     # inp15 LJ A-20h; Excel: janela t-19h/t-20h
    ]
    return inputs, st0

def montar_inputs_4h(series, t):
    """Monta os 5 inputs do 4h ALT prio_12478 conforme planilha auditavel."""
    def n(cod, h=0):
        return nivel(series.get(cod, {}), t - dt.timedelta(hours=h), estacao=cod)
    def D(cod, h):
        a, b = n(cod, 0), n(cod, h)
        return None if None in (a, b) else a - b
    def A(cod, h):
        a, b, c, d = n(cod, 0), n(cod, 1), n(cod, h), n(cod, h + 1)
        return None if None in (a, b, c, d) else (a - b) - (c - d)
    st0 = n("86472600", 0)
    inputs = [
        n("86472600", 0),      # inp01 ST nivel atual
        D("86472600", 1),      # inp02 ST D-1h
        A("86472600", 12),     # inp03 ST A-12h
        D("86125130", 12),     # inp04 Ituim D-12h
        D("86472000", 4),      # inp05 Linha Jose Julio / Antas D-4h
    ]
    return inputs, st0

def montar_inputs_4h_v01_r10(series, t):
    """Monta os 24 inputs do 4h PRO V01_R10 na ordem do MAT auditavel.

    A ordem e a convencao sao as da aba DADOS do Excel do modelo: nivel atual,
    diferencas para tras e aceleracoes (diferenca de velocidades) em Santa
    Tereza e Linha Jose Julio, seguidas das diferencas/aceleracoes das estacoes
    86125500 e 86298000. O NIVEL_ATUAL_CM e a ancora de reconstruÃ§ao, nao uma
    segunda coluna escondida: o MAT recebe exatamente os 24 valores abaixo.
    """
    def n(cod, h=0):
        return nivel(series.get(cod, {}), t - dt.timedelta(hours=h), estacao=cod)
    def D(cod, h):
        a, b = n(cod, 0), n(cod, h)
        return None if None in (a, b) else a - b
    def A(cod, h):
        a, b, c, d = n(cod, 0), n(cod, 1), n(cod, h), n(cod, h + 1)
        return None if None in (a, b, c, d) else (a - b) - (c - d)

    st0 = n("86472600", 0)
    inputs = [
        n("86472600", 0),      # input_01_Nivel_86472600
        D("86472600", 1),      # input_02_DifN-1h_86472600
        D("86472600", 2),      # input_03_DifN-2h_86472600
        D("86472600", 4),      # input_04_DifN-4h_86472600
        A("86472600", 1),      # input_05_Acel-1h_86472600
        A("86472600", 4),      # input_07_Acel-4h_86472600
        A("86472600", 12),     # input_09_Acel-12h_86472600
        n("86472000", 0),      # input_10_Nivel_86472000
        D("86472000", 1),      # input_11_DifN-1h_86472000
        D("86472000", 2),      # input_12_DifN-2h_86472000
        D("86472000", 4),      # input_13_DifN-4h_86472000
        A("86472000", 2),      # input_15_Acel-2h_86472000
        A("86472000", 8),      # input_15_Acel-8h_86472000
        A("86472000", 16),     # input_16_Acel-16h_86472000
        D("86125500", 2),      # input_12_DifN-2h_86125500
        D("86125500", 6),      # input_14_DifN-6h_86125500
        D("86125500", 10),     # input_14_DifN-10h_86125500
        D("86125500", 14),     # input_14_DifN-14h_86125500
        D("86298000", 2),      # input_12_DifN-2h_86298000
        D("86298000", 6),      # input_14_DifN-6h_86298000
        D("86298000", 10),     # input_14_DifN-10h_86298000
        A("86298000", 2),      # input_15_Acel-2h_86298000
        A("86298000", 8),      # input_15_Acel-8h_86298000
        A("86298000", 16),     # input_16_Acel-16h_86298000
    ]
    return inputs, st0


def montar_inputs_4h_v01_26(series, t):
    """Monta os 26 sinais H:AG da V01 R00 baseline.

    A aceleração segue a segunda diferença discreta da base, sem divisão por
    horas: A_h(t) = [N(t)-N(t-1h)] - [N(t-h)-N(t-(h+1)h)].
    """
    def n(cod, h=0):
        return nivel(series.get(cod, {}), t - dt.timedelta(hours=h), estacao=cod)
    def D(cod, h):
        a, b = n(cod, 0), n(cod, h)
        return None if None in (a, b) else a - b
    def A(cod, h):
        a, b, c, d = n(cod, 0), n(cod, 1), n(cod, h), n(cod, h + 1)
        return None if None in (a, b, c, d) else (a - b) - (c - d)
    st0 = n("86472600", 0)
    inputs = [
        n("86472600", 0), D("86472600", 1), D("86472600", 2), D("86472600", 4),
        A("86472600", 1), A("86472600", 4), A("86472600", 12),
        n("86472000", 0), D("86472000", 1), D("86472000", 2), D("86472000", 4),
        A("86472000", 2), A("86472000", 8), A("86472000", 16),
        n("86125500", 0), D("86125500", 2), D("86125500", 6),
        D("86125500", 10), D("86125500", 14),
        n("86298000", 0), D("86298000", 2), D("86298000", 6),
        D("86298000", 10), A("86298000", 2), A("86298000", 8), A("86298000", 16),
    ]
    return inputs, st0


def auditoria_inputs_4h_v01_r10(series, t, valores=None, specs_override=None, labels_override=None):
    """Audita a origem temporal e a formula dos 24 inputs do V01.

    ``A_h`` nao e uma aceleracao fisica em cm/s2: e a convencao discreta
    usada na base de treinamento, isto e, a diferenca entre duas variacoes
    de nivel de uma hora separadas por ``h`` horas.  Manter essa convencao e
    necessario para que o input ao vivo seja identico ao input do MAT.
    """
    specs = specs_override or [
        ("nivel", "86472600", 0),
        ("dif", "86472600", 1), ("dif", "86472600", 2), ("dif", "86472600", 4),
        ("acel", "86472600", 1), ("acel", "86472600", 4), ("acel", "86472600", 12),
        ("nivel", "86472000", 0),
        ("dif", "86472000", 1), ("dif", "86472000", 2), ("dif", "86472000", 4),
        ("acel", "86472000", 2), ("acel", "86472000", 8), ("acel", "86472000", 16),
        ("dif", "86125500", 2), ("dif", "86125500", 6),
        ("dif", "86125500", 10), ("dif", "86125500", 14),
        ("dif", "86298000", 2), ("dif", "86298000", 6),
        ("dif", "86298000", 10),
        ("acel", "86298000", 2), ("acel", "86298000", 8), ("acel", "86298000", 16),
    ]
    labels = labels_override if labels_override is not None else next(
        (cfg.get("input_labels") for cfg in MODELOS
         if cfg.get("modelo") == MODELO_4H_PRO_ID),
        None,
    ) or []
    entradas = []
    idades = []
    n_atrasados = 0
    n_ausentes = 0
    n_interpolados = 0
    n_vizinhos = 0
    n_fora_faixa = 0
    n_nao_exatos = 0
    n_exatos = 0
    formula_ok = True
    for i, (tipo, cod, h) in enumerate(specs):
        offsets = [0] if tipo == "nivel" else (
            [0, h] if tipo == "dif" else list(_acel_offsets_excel(cod, h))
        )
        dependencias = []
        numeros = []
        for atraso in offsets:
            solicitado = t - dt.timedelta(hours=atraso)
            valor, prov = nivel_com_proveniencia(
                series.get(cod, {}), solicitado, max_gap=NIVEL_MAX_GAP, estacao=cod
            )
            numeros.append(valor)
            dependencias.append({
                "atraso_h": atraso,
                **prov,
            })
        if any(v is None for v in numeros):
            calculado = None
        elif tipo == "nivel":
            calculado = numeros[0]
        elif tipo == "dif":
            calculado = numeros[0] - numeros[1]
        else:
            calculado = (numeros[0] - numeros[1]) - (numeros[2] - numeros[3])
        metodos = {d["metodo"] for d in dependencias}
        idade = max(
            (d["idade_max_min"] for d in dependencias if d["idade_max_min"] is not None),
            default=None,
        )
        if idade is not None:
            idades.append(idade)
        if "AUSENTE" in metodos:
            n_ausentes += 1
        if "FORA_FAIXA" in metodos:
            n_fora_faixa += 1
        if "VIZINHO_MAIS_PROXIMO" in metodos and (idade or 0) >= INPUT_WARN_MAX_AGE.total_seconds() / 60:
            n_atrasados += 1
        if "INTERPOLADO" in metodos:
            n_interpolados += 1
        if "VIZINHO_MAIS_PROXIMO" in metodos:
            n_vizinhos += 1
        if metodos == {"EXATO"}:
            n_exatos += 1
        else:
            # Interpolação e vizinho continuam registrados para diagnóstico,
            # mas não podem ser tratados como uma entrada horária normal.
            n_nao_exatos += 1
        if valores is not None and calculado is not None and valores[i] is not None:
            if abs(float(calculado) - float(valores[i])) > 1e-9:
                formula_ok = False
        entradas.append({
            "indice": i + 1,
            "rotulo": labels[i] if i < len(labels) else f"input_{i + 1:02d}",
            "tipo": tipo,
            "estacao": cod,
            "janela_h": h if tipo != "nivel" else 0,
            "valor_cm": (round(float(calculado), 3) if calculado is not None else None),
            "dependencias": dependencias,
            "idade_max_min": idade,
        })
    if n_ausentes or n_fora_faixa:
        status = "INVALIDO"
    elif n_nao_exatos:
        status = "ATENCAO"
    else:
        status = "NORMAL"
    return {
        "status": status,
        "formula_conferida_com_montador": bool(formula_ok),
        "n_inputs": len(specs),
        "n_exatos": n_exatos,
        "n_interpolados": n_interpolados,
        "n_vizinhos_mais_proximos": n_vizinhos,
        "n_inputs_nao_exatos": n_nao_exatos,
        "n_inputs_atrasados": n_atrasados,
        "n_inputs_ausentes": n_ausentes,
        "n_inputs_fora_faixa": n_fora_faixa,
        "idade_max_input_min": (max(idades) if idades else None),
        "regra_atraso": "ATENCAO quando qualquer dependencia nao e EXATO na mesma hora-base; INVALIDO quando falta ou sai da faixa plausivel qualquer dependencia",
        "faixa_plausivel_cm": [NIVEL_PLAUSIVEL_MIN_CM, NIVEL_PLAUSIVEL_MAX_CM],
        "contrato_temporal": "24 inputs do V01 em grade horaria exata, todos na mesma hora-base; interpolacao/vizinho nao entra na selecao do modelo",
        "definicao_aceleracao": {
            "formula": "A_h(t) = [N(t)-N(t-1h)] - [N(t-h)-N(t-(h+1)h)]",
            "interpretacao": "segunda diferenca discreta / mudanca da variacao horaria",
            "unidade_na_RNA": "cm na convencao da base; nao e cm/s2",
            "divisao_por_horas": "nao aplicada, exatamente como na base V01",
        },
        "inputs": entradas,
    }


def auditoria_inputs_4h_v01_26(series, t, valores=None):
    specs = [
        ("nivel", "86472600", 0),
        ("dif", "86472600", 1), ("dif", "86472600", 2), ("dif", "86472600", 4),
        ("acel", "86472600", 1), ("acel", "86472600", 4), ("acel", "86472600", 12),
        ("nivel", "86472000", 0),
        ("dif", "86472000", 1), ("dif", "86472000", 2), ("dif", "86472000", 4),
        ("acel", "86472000", 2), ("acel", "86472000", 8), ("acel", "86472000", 16),
        ("nivel", "86125500", 0),
        ("dif", "86125500", 2), ("dif", "86125500", 6),
        ("dif", "86125500", 10), ("dif", "86125500", 14),
        ("nivel", "86298000", 0),
        ("dif", "86298000", 2), ("dif", "86298000", 6),
        ("dif", "86298000", 10),
        ("acel", "86298000", 2), ("acel", "86298000", 8), ("acel", "86298000", 16),
    ]
    labels = next((cfg.get("input_labels") for cfg in MODELOS
                   if cfg.get("modelo") == MODELO_4H_PRO_ID), None) or []
    out = auditoria_inputs_4h_v01_r10(
        series, t, valores=valores, specs_override=specs, labels_override=labels
    )
    out["contrato_temporal"] = "26 inputs em grade horaria exata, todos na mesma hora-base; interpolacao/vizinho nao entra na selecao do modelo"
    out["input_grade"] = "hourly_exact"
    return out


def auditoria_inputs_2h(series, t, valores=None, grade=None):
    """Audita os 15 sinais do modelo 2h contra a planilha ativa.

    O modelo 2h principal e a versao B de sombra foram treinados em hora
    cheia. A versao B tambem possui uma aba operacional de 15 minutos no
    workbook arquivado, mas essa aba nao altera a grade do .mat; a selecao da
    hora-base e feita pelo ``input_grade`` do respectivo cadastro.
    """
    specs = [
        ("nivel", "86472600", 0),
        ("dif", "86472600", 1), ("dif", "86472600", 2), ("dif", "86472600", 4),
        ("acel", "86472600", 1), ("acel", "86472600", 2),
        ("acel", "86472600", 4), ("acel", "86472600", 8),
        ("acel", "86472600", 12),
        ("nivel", "86472000", 0),
        ("dif", "86472000", 1), ("dif", "86472000", 2),
        ("dif", "86472000", 5), ("acel", "86472000", 12),
        ("acel", "86472000", 20),
    ]
    labels = next(
        (cfg.get("input_labels") for cfg in MODELOS
         if cfg.get("montador") == "2h_alt_15inputs" and cfg.get("input_grade") == "hourly_exact"),
        None,
    ) or []
    out = auditoria_inputs_4h_v01_r10(
        series, t, valores=valores, specs_override=specs, labels_override=labels
    )
    out["n_inputs"] = 15
    out["contrato_temporal"] = (
        "15 inputs do modelo 2h em grade horaria exata, todos na mesma hora-base; "
        "interpolacao/vizinho nao entra na selecao do modelo"
    )
    out["definicao_diferenca"] = "D_h(t) = N(t) - N(t-h)"
    out["definicao_aceleracao"] = {
        "padrao": "A_h(t) = [N(t)-N(t-1h)] - [N(t-h)-N(t-(h+1)h)]",
        "excecao_excel_input_15": "A-20h LJ = [N(t)-N(t-1h)] - [N(t-19h)-N(t-20h)]",
        "fonte": "modelo_2h_novo.xlsx / DADOS_FORM",
    }
    out["input_grade"] = grade or "hourly_exact"
    out["input_grade_principal"] = "MINUTO = 0" if grade != "quarter_hour_exact" else "MINUTO = 0, 15, 30 ou 45"
    return out


def _A_janela_exata(series, cod, t, lag_h, win_h):
    """Aceleracao de janela usando somente leituras reais de hora cheia."""
    a = _n_exato(series, cod, t, 0)
    b = _n_exato(series, cod, t, win_h)
    c = _n_exato(series, cod, t, lag_h)
    d = _n_exato(series, cod, t, lag_h + win_h)
    return None if None in (a, b, c, d) else (a - b) - (c - d)


def _chuva_hora_exata(series, chave, t, h=0):
    hora = t - dt.timedelta(hours=h)
    if not _eh_hora_cheia(hora):
        return None
    return (series.get("__chuva8h_postos__", {}).get(chave) or {}).get(hora)


def _chuva_acum_8h(series, chave, t, n_horas):
    """Soma horaria conforme a planilha: buraco interno vira zero."""
    vals = [_chuva_hora_exata(series, chave, t, h) for h in range(n_horas)]
    if all(v is None for v in vals):
        return None
    return float(sum(0.0 if v is None else v for v in vals))


def _chuva_acum_24_dif_8h(series, chave, t):
    atual = _chuva_acum_8h(series, chave, t, 24)
    anterior = _chuva_acum_8h(series, chave, t - dt.timedelta(hours=24), 24)
    return None if None in (atual, anterior) else atual - anterior


def _media_disponiveis(*vals):
    xs = [v for v in vals if v is not None]
    return None if not xs else float(sum(xs) / len(xs))


def _media_disponiveis_ou_zero(*vals):
    media = _media_disponiveis(*vals)
    return 0.0 if media is None else media


def montar_inputs_8h_alt_v001(series, t):
    """31 sinais V001, todos ancorados em minuto 00 e sem nivel interpolado."""
    st0 = _n_exato(series, "86472600", t, 0)
    inputs = [
        st0,
        _D_exato(series, "86472600", t, 1),
        _D_exato(series, "86472600", t, 4),
        _A_janela_exata(series, "86472600", t, 1, 1),
        _A_janela_exata(series, "86472600", t, 12, 1),
        _n_exato(series, "86472000", t, 0),
        _D_exato(series, "86472000", t, 2),
        _D_exato(series, "86472000", t, 6),
        _A_janela_exata(series, "86472000", t, 4, 1),
        _A_janela_exata(series, "86472000", t, 13, 2),
        _D_exato(series, "86125500", t, 2),
        _D_exato(series, "86125500", t, 12),
        _n_exato(series, "86298000", t, 0),
        _D_exato(series, "86298000", t, 2),
        _D_exato(series, "86298000", t, 8),
        _A_janela_exata(series, "86298000", t, 12, 1),
        _A_janela_exata(series, "86298000", t, 25, 7),
        _n_exato(series, "86306000", t, 0),
        _D_exato(series, "86306000", t, 2),
        _D_exato(series, "86306000", t, 10),
        _A_janela_exata(series, "86306000", t, 19, 8),
        _D_exato(series, "86430900", t, 2),
        _D_exato(series, "86430900", t, 14),
        _D_exato(series, "86448000", t, 6),
        _D_exato(series, "86448000", t, 16),
        _media_disponiveis(_chuva_acum_8h(series, "86472600", t, 18), _chuva_acum_8h(series, "86472000", t, 18)),
        _media_disponiveis(_chuva_acum_24_dif_8h(series, "86472600", t), _chuva_acum_24_dif_8h(series, "86472000", t)),
        _media_disponiveis(_chuva_acum_8h(series, "2851072", t, 18), _chuva_acum_8h(series, POSTO_CHUVA_PASSO_CARREIRO, t, 18)),
        _media_disponiveis(_chuva_acum_24_dif_8h(series, "2851072", t), _chuva_acum_24_dif_8h(series, POSTO_CHUVA_PASSO_CARREIRO, t)),
        _media_disponiveis(_chuva_acum_8h(series, "86472600", t, 3), _chuva_acum_8h(series, "86472000", t, 3)),
        _media_disponiveis_ou_zero(_chuva_acum_8h(series, POSTO_CHUVA_PASSO_CARREIRO, t, 6)),
    ]
    return inputs, st0


def montar_inputs_8h_alt_v002(series, t):
    """28 sinais V002, todos ancorados em minuto 00 e sem nivel interpolado."""
    st0 = _n_exato(series, "86472600", t, 0)
    inputs = [
        st0,
        _D_exato(series, "86472600", t, 1),
        _D_exato(series, "86472600", t, 4),
        _A_janela_exata(series, "86472600", t, 1, 1),
        _A_janela_exata(series, "86472600", t, 12, 1),
        _n_exato(series, "86472000", t, 0),
        _D_exato(series, "86472000", t, 2),
        _D_exato(series, "86472000", t, 6),
        _A_janela_exata(series, "86472000", t, 4, 1),
        _A_janela_exata(series, "86472000", t, 13, 2),
        _D_exato(series, "86125500", t, 2),
        _D_exato(series, "86125500", t, 12),
        _D_exato(series, "86298000", t, 2),
        _D_exato(series, "86298000", t, 8),
        _A_janela_exata(series, "86298000", t, 12, 1),
        _A_janela_exata(series, "86298000", t, 25, 7),
        _D_exato(series, "86306000", t, 2),
        _D_exato(series, "86306000", t, 10),
        _A_janela_exata(series, "86306000", t, 19, 8),
        _D_exato(series, "86447000", t, 6),
        _D_exato(series, "86505500", t, 6),
        _D_exato(series, "86505500", t, 24),
        _media_disponiveis(_chuva_acum_8h(series, "86472600", t, 18), _chuva_acum_8h(series, "86472000", t, 18)),
        _media_disponiveis(_chuva_acum_24_dif_8h(series, "86472600", t), _chuva_acum_24_dif_8h(series, "86472000", t)),
        _media_disponiveis(_chuva_acum_8h(series, "2851072", t, 18), _chuva_acum_8h(series, POSTO_CHUVA_PASSO_CARREIRO, t, 18)),
        _media_disponiveis(_chuva_acum_24_dif_8h(series, "2851072", t), _chuva_acum_24_dif_8h(series, POSTO_CHUVA_PASSO_CARREIRO, t)),
        _media_disponiveis(_chuva_acum_8h(series, "86472600", t, 3), _chuva_acum_8h(series, "86472000", t, 3)),
        _media_disponiveis_ou_zero(_chuva_acum_8h(series, POSTO_CHUVA_PASSO_CARREIRO, t, 6)),
    ]
    return inputs, st0


def auditoria_inputs_8h(cfg, t, valores):
    """Contrato estruturado dos 8h; o montador usa apenas acesso exato."""
    ausentes = sum(v is None for v in valores)
    return {
        "status": "NORMAL" if not ausentes else "INVALIDO",
        "formula_conferida_com_montador": True,
        "n_inputs": len(valores),
        "n_exatos": len(valores) - ausentes,
        "n_inputs_nao_exatos": 0,
        "n_inputs_ausentes": ausentes,
        "input_grade": "hourly_exact",
        "hora_base_minuto": (t.minute if t else None),
        "usa_interpolacao_nivel": False,
        "usa_vizinho_nivel": False,
        "regra_chuva": "hora cheia; buraco interno vale zero conforme a planilha; posto totalmente vazio fica ausente",
        "contrato_temporal": f"{cfg['inputs_total']} inputs em hora cheia exata; niveis sem interpolacao ou vizinho",
    }


def montar_inputs_8h_alt_c0217(series, t):
    """10 inputs do modelo 8h ALT C0217, conforme planilha auditavel."""
    st0 = _n(series, "86472600", t, 0)
    inputs = [
        st0,                                   # inp01 ST nivel atual
        _D(series, "86472600", t, 1),          # inp02 ST D-1h
        chuva_media_acum_36h(series, t),       # inp03 chuva media acum 36h
        _n(series, "86306000", t, 0),          # inp04 Nova Roma / Antas nivel
        _D(series, "86306000", t, 12),         # inp05 Nova Roma / Antas D-12h
        _n(series, "86472000", t, 0),          # inp06 Linha Jose Julio nivel
        _D(series, "86472000", t, 2),          # inp07 Linha Jose Julio D-2h
        _A_curv(series, "86472000", t, 14),    # inp08 Linha Jose Julio A-14h
        _n(series, "86125130", t, 0),          # inp09 Ituim nivel
        _D(series, "86125130", t, 11),         # inp10 Ituim D-11h
    ]
    return inputs, st0

def montar_inputs_12h_alt_c0065(series, t):
    """12 inputs do modelo 12h ALT C0065, conforme planilha auditavel."""
    st0 = _n(series, "86472600", t, 0)
    inputs = [
        st0,                                   # inp01 ST nivel atual
        _D(series, "86472600", t, 1),          # inp02 ST D-1h
        chuva_media_acum_36h(series, t),       # inp03 chuva media acum 36h
        _n(series, "86448000", t, 0),          # inp04 Veranopolis nivel
        _D(series, "86448000", t, 12),         # inp05 Veranopolis D-12h
        _D(series, "86448000", t, 14),         # inp06 Veranopolis D-14h
        _n(series, "86125130", t, 0),          # inp07 Ituim nivel
        _D(series, "86125130", t, 10),         # inp08 Ituim D-10h
        _D(series, "86125130", t, 11),         # inp09 Ituim D-11h
        _D(series, "86125130", t, 12),         # inp10 Ituim D-12h
        _D(series, "86472600", t, 2),          # inp11 ST D-2h
        _D(series, "86472600", t, 4),          # inp12 ST D-4h
    ]
    return inputs, st0

def montar_inputs_modelo(cfg, series, t):
    if cfg["montador"] in ("2h_alt_15inputs", "2h_alt_vfinal"):
        return montar_inputs(series, t)
    if cfg["montador"] == "4h_alt_v01_26":
        return montar_inputs_4h_v01_26(series, t)
    if cfg["montador"] == "4h_alt_v01_r10":
        return montar_inputs_4h_v01_r10(series, t)
    if cfg["montador"] == "4h_alt_prio_12478":
        return montar_inputs_4h(series, t)
    if cfg["montador"] == "8h_alt_v001":
        return montar_inputs_8h_alt_v001(series, t)
    if cfg["montador"] == "8h_alt_v002":
        return montar_inputs_8h_alt_v002(series, t)
    if cfg["montador"] == "8h_alt_c0217":
        return montar_inputs_8h_alt_c0217(series, t)
    if cfg["montador"] == "12h_alt_c0065":
        return montar_inputs_12h_alt_c0065(series, t)
    raise ValueError("montador desconhecido: " + str(cfg["montador"]))


def hora_na_grade_do_modelo(cfg, cand):
    """Impede que a hora-base seja deslocada para uma grade nao treinada."""
    grade = cfg.get("input_grade")
    if grade == "hourly_exact":
        return cand.minute == 0 and cand.second == 0 and cand.microsecond == 0
    if grade == "quarter_hour_exact":
        return cand.minute in (0, 15, 30, 45) and cand.second == 0 and cand.microsecond == 0
    return True

def diagnosticar_inputs_faltantes(series, t, inputs):
    """Explica quais leituras horarias faltaram para montar cada input."""
    especificacoes = [
        ("inp01", "Santa Tereza - nivel atual", "86472600", [0]),
        ("inp02", "Santa Tereza - nivel D-1h", "86472600", [0, 1]),
        ("inp03", "Santa Tereza - nivel D-2h", "86472600", [0, 2]),
        ("inp04", "Santa Tereza - nivel D-4h", "86472600", [0, 4]),
        ("inp05", "Santa Tereza - aceleracao A-1h", "86472600", [0, 1, 2]),
        ("inp06", "Santa Tereza - aceleracao A-2h", "86472600", [0, 1, 2, 3]),
        ("inp07", "Santa Tereza - aceleracao A-4h", "86472600", [0, 1, 4, 5]),
        ("inp08", "Santa Tereza - aceleracao A-8h", "86472600", [0, 1, 8, 9]),
        ("inp09", "Santa Tereza - aceleracao A-12h", "86472600", [0, 1, 12, 13]),
        ("inp10", "Linha Jose Julio / Rio das Antas - nivel atual", "86472000", [0]),
        ("inp11", "Linha Jose Julio / Rio das Antas - nivel D-1h", "86472000", [0, 1]),
        ("inp12", "Linha Jose Julio / Rio das Antas - nivel D-2h", "86472000", [0, 2]),
        ("inp13", "Linha Jose Julio / Rio das Antas - nivel D-5h", "86472000", [0, 5]),
        ("inp14", "Linha Jose Julio / Rio das Antas - aceleracao A-12h", "86472000", [0, 1, 12, 13]),
        ("inp15", "Linha Jose Julio / Rio das Antas - aceleracao A-20h (regra Excel: t-19h/t-20h)", "86472000", list(_acel_offsets_excel("86472000", 20))),
    ]
    faltantes = []
    for valor, (codigo_input, descricao, cod_estacao, atrasos) in zip(inputs, especificacoes):
        if valor is not None:
            continue
        horarios = []
        for h in dict.fromkeys(atrasos):
            hora = t - dt.timedelta(hours=h)
            bruto = series.get(cod_estacao, {}).get(hora)
            fora_faixa = bruto is not None and not _nivel_plausivel(bruto, cod_estacao)
            disponivel = bruto is not None and not fora_faixa
            horarios.append({
                "atraso_h": h,
                "hora": hora.isoformat(timespec="minutes"),
                "disponivel": disponivel,
                "valor_bruto_cm": (round(float(bruto), 3) if bruto is not None else None),
                "fora_faixa": fora_faixa,
            })
        faltantes.append({
            "input": codigo_input,
            "descricao": descricao,
            "estacao": cod_estacao,
            "estacao_nome": NOMES_ESTACOES.get(cod_estacao, cod_estacao),
            "horarios_necessarios": [h["hora"] for h in horarios],
            "horarios_faltantes": [h["hora"] for h in horarios if not h["disponivel"]],
            "horarios_fora_faixa": [h["hora"] for h in horarios if h["fora_faixa"]],
            "limites_plausiveis_cm": list(_limites_plausiveis(cod)),
        })
    return faltantes

def diagnosticar_inputs_faltantes_4h(series, t, inputs):
    especificacoes = [
        ("inp01", "Santa Tereza - nivel atual", "86472600", [0]),
        ("inp02", "Santa Tereza - nivel D-1h", "86472600", [0, 1]),
        ("inp03", "Santa Tereza - aceleracao A-12h", "86472600", [0, 1, 12, 13]),
        ("inp04", "Ituim - nivel D-12h", "86125130", [0, 12]),
        ("inp05", "Linha Jose Julio / Rio das Antas - nivel D-4h", "86472000", [0, 4]),
    ]
    faltantes = []
    for valor, (codigo_input, descricao, cod_estacao, atrasos) in zip(inputs, especificacoes):
        if valor is not None:
            continue
        horarios = []
        for h in dict.fromkeys(atrasos):
            hora = t - dt.timedelta(hours=h)
            disponivel = hora in series.get(cod_estacao, {})
            horarios.append({
                "atraso_h": h,
                "hora": hora.isoformat(timespec="minutes"),
                "disponivel": disponivel,
            })
        faltantes.append({
            "input": codigo_input,
            "descricao": descricao,
            "estacao": cod_estacao,
            "estacao_nome": NOMES_ESTACOES.get(cod_estacao, cod_estacao),
            "horarios_necessarios": [h["hora"] for h in horarios],
            "horarios_faltantes": [h["hora"] for h in horarios if not h["disponivel"]],
        })
    return faltantes

def diagnosticar_inputs_faltantes_4h_v01_r10(series, t, inputs):
    """Explica a falta de qualquer um dos 24 lags do 4h PRO."""
    especificacoes = [
        ("inp01", "Santa Tereza - nivel atual", "86472600", [0]),
        ("inp02", "Santa Tereza - nivel D-1h", "86472600", [0, 1]),
        ("inp03", "Santa Tereza - nivel D-2h", "86472600", [0, 2]),
        ("inp04", "Santa Tereza - nivel D-4h", "86472600", [0, 4]),
        ("inp05", "Santa Tereza - aceleracao A-1h", "86472600", [0, 1, 2]),
        ("inp06", "Santa Tereza - aceleracao A-4h", "86472600", [0, 1, 4, 5]),
        ("inp07", "Santa Tereza - aceleracao A-12h", "86472600", [0, 1, 12, 13]),
        ("inp08", "Linha Jose Julio - nivel atual", "86472000", [0]),
        ("inp09", "Linha Jose Julio - nivel D-1h", "86472000", [0, 1]),
        ("inp10", "Linha Jose Julio - nivel D-2h", "86472000", [0, 2]),
        ("inp11", "Linha Jose Julio - nivel D-4h", "86472000", [0, 4]),
        ("inp12", "Linha Jose Julio - aceleracao A-2h", "86472000", [0, 1, 2, 3]),
        ("inp13", "Linha Jose Julio - aceleracao A-8h", "86472000", [0, 1, 8, 9]),
        ("inp14", "Linha Jose Julio - aceleracao A-16h", "86472000", [0, 1, 16, 17]),
        ("inp15", "Estacao 86125500 - nivel D-2h", "86125500", [0, 2]),
        ("inp16", "Estacao 86125500 - nivel D-6h", "86125500", [0, 6]),
        ("inp17", "Estacao 86125500 - nivel D-10h", "86125500", [0, 10]),
        ("inp18", "Estacao 86125500 - nivel D-14h", "86125500", [0, 14]),
        ("inp19", "Estacao 86298000 - nivel D-2h", "86298000", [0, 2]),
        ("inp20", "Estacao 86298000 - nivel D-6h", "86298000", [0, 6]),
        ("inp21", "Estacao 86298000 - nivel D-10h", "86298000", [0, 10]),
        ("inp22", "Estacao 86298000 - aceleracao A-2h", "86298000", [0, 1, 2, 3]),
        ("inp23", "Estacao 86298000 - aceleracao A-8h", "86298000", [0, 1, 8, 9]),
        ("inp24", "Estacao 86298000 - aceleracao A-16h", "86298000", [0, 1, 16, 17]),
    ]
    return diagnosticar_inputs_por_especificacoes(series, t, inputs, especificacoes)

def diagnosticar_inputs_por_especificacoes(series, t, inputs, especificacoes):
    faltantes = []
    for valor, spec in zip(inputs, especificacoes):
        codigo_input, descricao, cod_estacao, atrasos = spec
        if valor is not None:
            continue
        if cod_estacao == "__chuva36h__":
            horas_faltantes = []
            postos = series.get("__chuva36h_postos__", {})
            for h in range(36):
                hora = t - dt.timedelta(hours=h)
                if not any(posto.get(hora) is not None for posto in postos.values()):
                    horas_faltantes.append(hora.isoformat(timespec="minutes"))
            faltantes.append({
                "input": codigo_input,
                "descricao": descricao,
                "estacao": "chuva_media_36h",
                "estacao_nome": "Chuva media acumulada 36h",
                "horarios_necessarios": [(t - dt.timedelta(hours=h)).isoformat(timespec="minutes") for h in range(36)],
                "horarios_faltantes": horas_faltantes,
                "postos_chuva": POSTOS_CHUVA_36H,
            })
            continue
        horarios = []
        for h in dict.fromkeys(atrasos):
            hora = t - dt.timedelta(hours=h)
            disponivel = hora in series.get(cod_estacao, {})
            horarios.append({
                "atraso_h": h,
                "hora": hora.isoformat(timespec="minutes"),
                "disponivel": disponivel,
            })
        faltantes.append({
            "input": codigo_input,
            "descricao": descricao,
            "estacao": cod_estacao,
            "estacao_nome": NOMES_ESTACOES.get(cod_estacao, cod_estacao),
            "horarios_necessarios": [h["hora"] for h in horarios],
            "horarios_faltantes": [h["hora"] for h in horarios if not h["disponivel"]],
        })
    return faltantes


def _diagnosticar_chuva_8h(series, t, inputs, inicio, definicoes):
    faltantes = []
    postos = series.get("__chuva8h_postos__", {})
    for deslocamento, (codigo, descricao, chaves, n_horas) in enumerate(definicoes):
        idx = inicio + deslocamento
        if idx >= len(inputs) or inputs[idx] is not None:
            continue
        horas_faltantes = []
        for h in range(n_horas):
            hora = t - dt.timedelta(hours=h)
            if not any((postos.get(chave) or {}).get(hora) is not None for chave in chaves):
                horas_faltantes.append(hora.isoformat(timespec="minutes"))
        faltantes.append({
            "input": codigo,
            "descricao": descricao,
            "estacao": ",".join(chaves),
            "estacao_nome": " / ".join(NOMES_ESTACOES.get(chave, chave) for chave in chaves),
            "horarios_faltantes": horas_faltantes[:12],
        })
    return faltantes


def diagnosticar_inputs_faltantes_8h_v001(series, t, inputs):
    especificacoes = [
        ("inp01", "Santa Tereza - nivel atual", "86472600", [0]),
        ("inp02", "Santa Tereza - nivel D-1h", "86472600", [0, 1]),
        ("inp03", "Santa Tereza - nivel D-4h", "86472600", [0, 4]),
        ("inp04", "Santa Tereza - aceleracao A-1h", "86472600", [0, 1, 2]),
        ("inp05", "Santa Tereza - aceleracao A-12h", "86472600", [0, 1, 12, 13]),
        ("inp06", "Linha Jose Julio - nivel atual", "86472000", [0]),
        ("inp07", "Linha Jose Julio - nivel D-2h", "86472000", [0, 2]),
        ("inp08", "Linha Jose Julio - nivel D-6h", "86472000", [0, 6]),
        ("inp09", "Linha Jose Julio - aceleracao A-4h", "86472000", [0, 1, 4, 5]),
        ("inp10", "Linha Jose Julio - aceleracao A-13h janela 2h", "86472000", [0, 2, 13, 15]),
        ("inp11", "86125500 - nivel D-2h", "86125500", [0, 2]),
        ("inp12", "86125500 - nivel D-12h", "86125500", [0, 12]),
        ("inp13", "86298000 - nivel atual", "86298000", [0]),
        ("inp14", "86298000 - nivel D-2h", "86298000", [0, 2]),
        ("inp15", "86298000 - nivel D-8h", "86298000", [0, 8]),
        ("inp16", "86298000 - aceleracao A-12h", "86298000", [0, 1, 12, 13]),
        ("inp17", "86298000 - aceleracao A-25h janela 7h", "86298000", [0, 7, 25, 32]),
        ("inp18", "Nova Roma - nivel atual", "86306000", [0]),
        ("inp19", "Nova Roma - nivel D-2h", "86306000", [0, 2]),
        ("inp20", "Nova Roma - nivel D-10h", "86306000", [0, 10]),
        ("inp21", "Nova Roma - aceleracao A-19h janela 8h", "86306000", [0, 8, 19, 27]),
        ("inp22", "86430900 - nivel D-2h", "86430900", [0, 2]),
        ("inp23", "86430900 - nivel D-14h", "86430900", [0, 14]),
        ("inp24", "Veranopolis - nivel D-6h", "86448000", [0, 6]),
        ("inp25", "Veranopolis - nivel D-16h", "86448000", [0, 16]),
    ]
    faltantes = diagnosticar_inputs_por_especificacoes(series, t, inputs[:25], especificacoes)
    chuva = [
        ("inp26", "chuva ST+LJJ acumulada 18h", ["86472600", "86472000"], 18),
        ("inp27", "chuva ST+LJJ diferenca 24h", ["86472600", "86472000"], 48),
        ("inp28", "chuva 2851072+Passo Carreiro acumulada 18h", ["2851072", POSTO_CHUVA_PASSO_CARREIRO], 18),
        ("inp29", "chuva 2851072+Passo Carreiro diferenca 24h", ["2851072", POSTO_CHUVA_PASSO_CARREIRO], 48),
        ("inp30", "chuva ST+LJJ acumulada 3h", ["86472600", "86472000"], 3),
        ("inp31", "chuva Passo Carreiro acumulada 6h", [POSTO_CHUVA_PASSO_CARREIRO], 6),
    ]
    return faltantes + _diagnosticar_chuva_8h(series, t, inputs, 25, chuva)


def diagnosticar_inputs_faltantes_8h_v002(series, t, inputs):
    especificacoes = [
        ("inp01", "Santa Tereza - nivel atual", "86472600", [0]),
        ("inp02", "Santa Tereza - nivel D-1h", "86472600", [0, 1]),
        ("inp03", "Santa Tereza - nivel D-4h", "86472600", [0, 4]),
        ("inp04", "Santa Tereza - aceleracao A-1h", "86472600", [0, 1, 2]),
        ("inp05", "Santa Tereza - aceleracao A-12h", "86472600", [0, 1, 12, 13]),
        ("inp06", "Linha Jose Julio - nivel atual", "86472000", [0]),
        ("inp07", "Linha Jose Julio - nivel D-2h", "86472000", [0, 2]),
        ("inp08", "Linha Jose Julio - nivel D-6h", "86472000", [0, 6]),
        ("inp09", "Linha Jose Julio - aceleracao A-4h", "86472000", [0, 1, 4, 5]),
        ("inp10", "Linha Jose Julio - aceleracao A-13h janela 2h", "86472000", [0, 2, 13, 15]),
        ("inp11", "86125500 - nivel D-2h", "86125500", [0, 2]),
        ("inp12", "86125500 - nivel D-12h", "86125500", [0, 12]),
        ("inp13", "86298000 - nivel D-2h", "86298000", [0, 2]),
        ("inp14", "86298000 - nivel D-8h", "86298000", [0, 8]),
        ("inp15", "86298000 - aceleracao A-12h", "86298000", [0, 1, 12, 13]),
        ("inp16", "86298000 - aceleracao A-25h janela 7h", "86298000", [0, 7, 25, 32]),
        ("inp17", "Nova Roma - nivel D-2h", "86306000", [0, 2]),
        ("inp18", "Nova Roma - nivel D-10h", "86306000", [0, 10]),
        ("inp19", "Nova Roma - aceleracao A-19h janela 8h", "86306000", [0, 8, 19, 27]),
        ("inp20", "86447000 - nivel D-6h", "86447000", [0, 6]),
        ("inp21", "86505500 - nivel D-6h", "86505500", [0, 6]),
        ("inp22", "86505500 - nivel D-24h", "86505500", [0, 24]),
    ]
    faltantes = diagnosticar_inputs_por_especificacoes(series, t, inputs[:22], especificacoes)
    chuva = [
        ("inp23", "chuva ST+LJJ acumulada 18h", ["86472600", "86472000"], 18),
        ("inp24", "chuva ST+LJJ diferenca 24h", ["86472600", "86472000"], 48),
        ("inp25", "chuva 2851072+Passo Carreiro acumulada 18h", ["2851072", POSTO_CHUVA_PASSO_CARREIRO], 18),
        ("inp26", "chuva 2851072+Passo Carreiro diferenca 24h", ["2851072", POSTO_CHUVA_PASSO_CARREIRO], 48),
        ("inp27", "chuva ST+LJJ acumulada 3h", ["86472600", "86472000"], 3),
        ("inp28", "chuva Passo Carreiro acumulada 6h", [POSTO_CHUVA_PASSO_CARREIRO], 6),
    ]
    return faltantes + _diagnosticar_chuva_8h(series, t, inputs, 22, chuva)


def diagnosticar_inputs_faltantes_8h(series, t, inputs):
    especificacoes = [
        ("inp01", "Santa Tereza - nivel atual", "86472600", [0]),
        ("inp02", "Santa Tereza - nivel D-1h", "86472600", [0, 1]),
        ("inp03", "Chuva media acumulada 36h", "__chuva36h__", list(range(36))),
        ("inp04", "Nova Roma do Sul / Rio das Antas - nivel atual", "86306000", [0]),
        ("inp05", "Nova Roma do Sul / Rio das Antas - nivel D-12h", "86306000", [0, 12]),
        ("inp06", "Linha Jose Julio - nivel atual", "86472000", [0]),
        ("inp07", "Linha Jose Julio - nivel D-2h", "86472000", [0, 2]),
        ("inp08", "Linha Jose Julio - aceleracao A-14h", "86472000", [13, 14, 15]),
        ("inp09", "Ituim - nivel atual", "86125130", [0]),
        ("inp10", "Ituim - nivel D-11h", "86125130", [0, 11]),
    ]
    return diagnosticar_inputs_por_especificacoes(series, t, inputs, especificacoes)

def diagnosticar_inputs_faltantes_12h(series, t, inputs):
    especificacoes = [
        ("inp01", "Santa Tereza - nivel atual", "86472600", [0]),
        ("inp02", "Santa Tereza - nivel D-1h", "86472600", [0, 1]),
        ("inp03", "Chuva media acumulada 36h", "__chuva36h__", list(range(36))),
        ("inp04", "Veranopolis / Rio das Antas - nivel atual", "86448000", [0]),
        ("inp05", "Veranopolis / Rio das Antas - nivel D-12h", "86448000", [0, 12]),
        ("inp06", "Veranopolis / Rio das Antas - nivel D-14h", "86448000", [0, 14]),
        ("inp07", "Ituim - nivel atual", "86125130", [0]),
        ("inp08", "Ituim - nivel D-10h", "86125130", [0, 10]),
        ("inp09", "Ituim - nivel D-11h", "86125130", [0, 11]),
        ("inp10", "Ituim - nivel D-12h", "86125130", [0, 12]),
        ("inp11", "Santa Tereza - nivel D-2h", "86472600", [0, 2]),
        ("inp12", "Santa Tereza - nivel D-4h", "86472600", [0, 4]),
    ]
    return diagnosticar_inputs_por_especificacoes(series, t, inputs, especificacoes)

def diagnosticar_inputs_faltantes_4h_v01_26(series, t, inputs):
    especificacoes = [
        ("inp01", "Santa Tereza - nivel atual", "86472600", [0]),
        ("inp02", "Santa Tereza - nivel D-1h", "86472600", [0, 1]),
        ("inp03", "Santa Tereza - nivel D-2h", "86472600", [0, 2]),
        ("inp04", "Santa Tereza - nivel D-4h", "86472600", [0, 4]),
        ("inp05", "Santa Tereza - aceleracao A-1h", "86472600", [0, 1, 2]),
        ("inp06", "Santa Tereza - aceleracao A-4h", "86472600", [0, 1, 4, 5]),
        ("inp07", "Santa Tereza - aceleracao A-12h", "86472600", [0, 1, 12, 13]),
        ("inp08", "Linha Jose Julio - nivel atual", "86472000", [0]),
        ("inp09", "Linha Jose Julio - nivel D-1h", "86472000", [0, 1]),
        ("inp10", "Linha Jose Julio - nivel D-2h", "86472000", [0, 2]),
        ("inp11", "Linha Jose Julio - nivel D-4h", "86472000", [0, 4]),
        ("inp12", "Linha Jose Julio - aceleracao A-2h", "86472000", [0, 1, 2, 3]),
        ("inp13", "Linha Jose Julio - aceleracao A-8h", "86472000", [0, 1, 8, 9]),
        ("inp14", "Linha Jose Julio - aceleracao A-16h", "86472000", [0, 1, 16, 17]),
        ("inp15", "86125500 - nivel atual", "86125500", [0]),
        ("inp16", "86125500 - nivel D-2h", "86125500", [0, 2]),
        ("inp17", "86125500 - nivel D-6h", "86125500", [0, 6]),
        ("inp18", "86125500 - nivel D-10h", "86125500", [0, 10]),
        ("inp19", "86125500 - nivel D-14h", "86125500", [0, 14]),
        ("inp20", "86298000 - nivel atual", "86298000", [0]),
        ("inp21", "86298000 - nivel D-2h", "86298000", [0, 2]),
        ("inp22", "86298000 - nivel D-6h", "86298000", [0, 6]),
        ("inp23", "86298000 - nivel D-10h", "86298000", [0, 10]),
        ("inp24", "86298000 - aceleracao A-2h", "86298000", [0, 1, 2, 3]),
        ("inp25", "86298000 - aceleracao A-8h", "86298000", [0, 1, 8, 9]),
        ("inp26", "86298000 - aceleracao A-16h", "86298000", [0, 1, 16, 17]),
    ]
    return diagnosticar_inputs_por_especificacoes(series, t, inputs, especificacoes)


def diagnosticar_inputs_modelo(cfg, series, t, inputs):
    if cfg["montador"] == "4h_alt_v01_26":
        return diagnosticar_inputs_faltantes_4h_v01_26(series, t, inputs)
    if cfg["montador"] == "4h_alt_v01_r10":
        return diagnosticar_inputs_faltantes_4h_v01_r10(series, t, inputs)
    if cfg["montador"] == "4h_alt_prio_12478":
        return diagnosticar_inputs_faltantes_4h(series, t, inputs)
    if cfg["montador"] == "8h_alt_v001":
        return diagnosticar_inputs_faltantes_8h_v001(series, t, inputs)
    if cfg["montador"] == "8h_alt_v002":
        return diagnosticar_inputs_faltantes_8h_v002(series, t, inputs)
    if cfg["montador"] == "8h_alt_c0217":
        return diagnosticar_inputs_faltantes_8h(series, t, inputs)
    if cfg["montador"] == "12h_alt_c0065":
        return diagnosticar_inputs_faltantes_12h(series, t, inputs)
    return diagnosticar_inputs_faltantes(series, t, inputs)

def resumo_estacoes(series):
    resumo = []
    consultado_em = agora_brt()
    for cod in ESTACOES:
        serie = series.get(cod, {})
        raw = ULTIMA_RAW.get(cod)
        fora_faixa = [
            (hora, valor) for hora, valor in serie.items()
            if not _nivel_plausivel(valor, cod)
        ]
        ultima_fora_faixa = max(fora_faixa, key=lambda par: par[0]) if fora_faixa else None
        ultima_hora = max(serie) if serie else None
        meta = METADADOS_ESTACOES.get(cod, {})
        resumo.append({
            "estacao": cod,
            "nome": NOMES_ESTACOES.get(cod, cod),
            "latitude": meta.get("lat"),
            "longitude": meta.get("lon"),
            "papel": meta.get("papel"),
            "fonte": "SGB/ANA - Hidrotelemetria",
            "tipo_dado": "leitura_observada_da_regua",
            "unidade": "cm",
            "horas_modelo_disponiveis": len(serie),
            "ultima_hora_modelo": (ultima_hora.isoformat(timespec="minutes") if ultima_hora else None),
            "ultima_hora_modelo_nivel_cm": (round(serie[ultima_hora]) if ultima_hora else None),
            "ultima_leitura_bruta": (raw[0].isoformat(timespec="minutes") if raw else None),
            "ultima_leitura_bruta_nivel_cm": (round(raw[1]) if raw else None),
            "idade_leitura_min": (
                round((consultado_em - raw[0]).total_seconds() / 60) if raw else None
            ),
            "qc_status": "ATENCAO_FORA_FAIXA" if fora_faixa else "NORMAL",
            "qc_fora_faixa_n": len(fora_faixa),
            "qc_ultima_fora_faixa": (
                {
                    "hora": ultima_fora_faixa[0].isoformat(timespec="minutes"),
                    "nivel_cm": round(float(ultima_fora_faixa[1]), 3),
                }
                if ultima_fora_faixa else None
            ),
            "limites_plausiveis_cm": [NIVEL_PLAUSIVEL_MIN_CM, NIVEL_PLAUSIVEL_MAX_CM],
        })
    return resumo

def prever(mat_path, x):
    """Forward pass da MLP (validado: reproduz Tctot1 do .mat com RMSE 0).
       Entrada normalizada: pn=(P-be)/ae ; oculta e saída = logsig ;
       desnorm: variação = yn*au + bu.  Modelo ALT -> devolve a VARIAÇÃO (cm)."""
    try:
        m = loadmat(mat_path, squeeze_me=True)
        wh = np.atleast_2d(np.asarray(m["wh"], float))
        bh = np.asarray(m["bh"], float).ravel()
        ws = np.asarray(m["ws"], float).ravel()
        bs = float(np.atleast_1d(m["bs"])[0])
        ae = np.asarray(m["ae"], float).ravel()
        be = np.asarray(m["be"], float).ravel()
        au = float(np.atleast_1d(m["au"])[0])
        bu = float(np.atleast_1d(m["bu"])[0])
    except NotImplementedError:
        import h5py
        with h5py.File(mat_path, "r") as f:
            wh = np.asarray(f["wh"], float)
            bh = np.asarray(f["bh"], float).ravel()
            ws = np.asarray(f["ws"], float)
            bs = float(np.asarray(f["bs"]).ravel()[0])
            ae = np.asarray(f["ae"], float).ravel()
            be = np.asarray(f["be"], float).ravel()
            au = float(np.asarray(f["au"]).ravel()[0])
            bu = float(np.asarray(f["bu"]).ravel()[0])
    logsig = lambda z: 1.0 / (1.0 + np.exp(-z))
    pn = (np.asarray(x, float) - be) / ae
    if wh.shape[0] == pn.size:
        h = logsig(pn @ wh + bh)
        yn = logsig(h @ np.asarray(ws).reshape(-1, 1) + bs)
    else:
        h = logsig(wh.dot(pn) + bh)
        yn = logsig(np.asarray(ws).ravel().dot(h) + bs)
    return float(np.asarray(yn).ravel()[0] * au + bu)  # variação prevista (cm)

def sha256_arquivo(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest().upper()

def escrever(nivel_atual, nivel_prev, t, status, aviso, inputs_faltantes=None, estacoes_status=None):
    consultado_em = agora_brt()
    raw_st = ULTIMA_RAW.get("86472600")
    idade_min = None
    status_dados = None
    if raw_st:
        idade_min = round((consultado_em - raw_st[0]).total_seconds() / 60)
        status_dados = "telemetria recente" if idade_min <= 30 else f"telemetria atrasada ({idade_min} min)"
    out = {
        "modo": "ao_vivo",
        "gerado_em": (t.isoformat() if t else consultado_em.isoformat()),
        "hora_modelo": (t.isoformat() if t else None),
        "consultado_em": consultado_em.isoformat(timespec="seconds"),
        "telemetria_ultima_em": (raw_st[0].isoformat() if raw_st else None),
        "telemetria_ultima_nivel_cm": (round(raw_st[1]) if raw_st else None),
        "idade_telemetria_min": idade_min,
        "status_dados": status_dados,
        "estacao": "86472600", "local": "Santa Tereza",
        "horizonte": HORIZONTE, "modelo": COMBO, "bankfull_cm": BANKFULL_CM,
        "nivel_modelo_cm": (round(nivel_atual) if nivel_atual is not None else None),
        "nivel_rio_agora_cm": (round(raw_st[1]) if raw_st else (round(nivel_atual) if nivel_atual is not None else None)),
        "nivel_rio_agora_em": (raw_st[0].isoformat() if raw_st else (t.isoformat() if t else None)),
        "nivel_atual_cm": (round(nivel_atual) if nivel_atual is not None else None),
        "nivel_previsto_cm": (round(nivel_prev) if nivel_prev is not None else None),
        "inputs_total": 15,
        "inputs_faltantes_n": len(inputs_faltantes or []),
        "inputs_faltantes": inputs_faltantes or [],
        "estacoes_status": estacoes_status or [],
        "status": status,
        "aviso": aviso,
    }
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("escrito", SAIDA, "->", out["nivel_atual_cm"], "->", out["nivel_previsto_cm"], status)

def _base_saida(cfg, nivel_atual, nivel_prev, t, status, aviso, inputs_faltantes=None, estacoes_status=None):
    consultado_em = agora_brt()
    raw_st = ULTIMA_RAW.get("86472600")
    idade_min = None
    status_dados = None
    if raw_st:
        idade_min = round((consultado_em - raw_st[0]).total_seconds() / 60)
        status_dados = "telemetria recente" if idade_min <= 30 else f"telemetria atrasada ({idade_min} min)"
    return {
        "modo": "ao_vivo",
        "gerado_em": (t.isoformat() if t else consultado_em.isoformat()),
        "hora_modelo": (t.isoformat() if t else None),
        "hora_alvo": ((t + dt.timedelta(hours=cfg["horizonte_h"])).isoformat() if t else None),
        "consultado_em": consultado_em.isoformat(timespec="seconds"),
        "telemetria_ultima_em": (raw_st[0].isoformat() if raw_st else None),
        "telemetria_ultima_nivel_cm": (round(raw_st[1]) if raw_st else None),
        "idade_telemetria_min": idade_min,
        "status_dados": status_dados,
        "estacao": "86472600",
        "local": "Santa Tereza",
        "horizonte": cfg["horizonte"],
        "rotulo": cfg.get("rotulo", cfg["horizonte"]),
        "horizonte_h": cfg["horizonte_h"],
        "tipo": cfg["tipo"],
        "modelo": cfg["modelo"],
        "montador": cfg.get("montador"),
        "versao": cfg.get("versao"),
        "ativo_ao_vivo": bool(cfg.get("ativo_ao_vivo", False)),
        "principal": bool(cfg.get("principal", False)),
        "shadow_only": bool(cfg.get("shadow_only", False)),
        "status_publicacao": cfg.get("status_publicacao"),
        "modelo_sha256": (sha256_arquivo(cfg["mat"]) if os.path.exists(cfg.get("mat", "")) else cfg.get("modelo_sha256")),
        "referencia_auditavel_sha256": cfg.get("referencia_auditavel_sha256"),
        "proveniencia_nota": cfg.get("proveniencia_nota"),
        "referencia_auditavel": cfg.get("referencia_auditavel"),
        "input_labels": cfg.get("input_labels"),
        "input_anchor_note": cfg.get("input_anchor_note"),
        "input_contract_version": cfg.get("input_contract_version"),
        "input_grade": cfg.get("input_grade"),
        "bankfull_cm": BANKFULL_CM,
        "nivel_modelo_cm": (round(nivel_atual) if nivel_atual is not None else None),
        "nivel_rio_agora_cm": (round(raw_st[1]) if raw_st else (round(nivel_atual) if nivel_atual is not None else None)),
        "nivel_rio_agora_em": (raw_st[0].isoformat() if raw_st else (t.isoformat() if t else None)),
        "nivel_atual_cm": (round(nivel_atual) if nivel_atual is not None else None),
        "nivel_previsto_cm": (round(nivel_prev) if nivel_prev is not None else None),
        "inputs_total": cfg["inputs_total"],
        "inputs_faltantes_n": len(inputs_faltantes or []),
        "inputs_faltantes": inputs_faltantes or [],
        "estacoes_status": estacoes_status or [],
        "status": status,
        "aviso": aviso,
    }

def carregar_historico():
    if not os.path.exists(HISTORICO_SAIDA):
        return []
    try:
        with open(HISTORICO_SAIDA, "r", encoding="utf-8") as f:
            dados = json.load(f)
        if isinstance(dados, dict):
            return dados.get("registros", [])
        return dados if isinstance(dados, list) else []
    except Exception as e:
        print("historico invalido, reiniciando:", e)
        return []

def salvar_historico(registros):
    pacote = {
        "atualizado_em": agora_brt().isoformat(timespec="seconds"),
        "registros": registros[-1200:],
    }
    with open(HISTORICO_SAIDA, "w", encoding="utf-8") as f:
        json.dump(pacote, f, ensure_ascii=False, indent=1)

def upsert_previsao_historico(registros, saida):
    if saida.get("status") != "ok" or saida.get("nivel_previsto_cm") is None or not saida.get("hora_modelo"):
        return registros
    chave = f"{saida['local']}|{saida['horizonte']}|{saida['modelo']}|{saida['hora_modelo']}"
    novo = {
        "id": chave,
        "local": saida["local"],
        "estacao": saida["estacao"],
        "horizonte": saida["horizonte"],
        "horizonte_h": saida["horizonte_h"],
        "tipo": saida.get("tipo"),
        "modelo": saida["modelo"],
        "hora_modelo": saida["hora_modelo"],
        "hora_alvo": saida["hora_alvo"],
        "nivel_modelo_cm": saida.get("nivel_modelo_cm"),
        "nivel_rio_agora_cm": saida.get("nivel_rio_agora_cm"),
        "nivel_previsto_cm": saida.get("nivel_previsto_cm"),
        "status_auditoria": "aguardando",
        "auditoria_versao": AUDITORIA_VERSAO,
        "input_contract_version": saida.get("input_contract_version"),
        "criado_em": saida.get("consultado_em"),
    }
    for i, reg in enumerate(registros):
        if reg.get("id") == chave:
            # Registros criados antes do contrato target_exact_v2 precisam
            # voltar para aguardando; os erros antigos podem ter usado uma
            # leitura vizinha e não são comparáveis aos novos.
            preservados = {}
            if reg.get("auditoria_versao") == AUDITORIA_VERSAO:
                preservados = {k: reg.get(k) for k in ("observado_cm", "observado_em", "erro_cm", "erro_abs_cm", "status_auditoria", "auditado_em") if k in reg}
            novo.update(preservados)
            registros[i] = novo
            return registros
    registros.append(novo)
    return registros

def conferir_historico(registros, series):
    serie_st = series.get("86472600", {})
    ultima_hora = max(serie_st) if serie_st else None
    for reg in registros:
        if reg.get("status_auditoria") == "conferido" and reg.get("auditoria_versao") == AUDITORIA_VERSAO:
            continue
        if reg.get("auditoria_versao") != AUDITORIA_VERSAO:
            for campo in ("observado_cm", "observado_em", "erro_cm", "erro_abs_cm", "auditado_em"):
                reg.pop(campo, None)
            reg["status_auditoria"] = "aguardando"
            reg["auditoria_versao"] = AUDITORIA_VERSAO
        alvo = _parse_hora(reg.get("hora_alvo", ""))
        if alvo is None:
            continue
        # Comparação estrita: previsão para t+H só é conferida com a leitura
        # ANA exatamente em t+H. Não usar 00:45 para validar uma previsão de
        # 01:00, nem interpolar o observado.
        obs, obs_em = observar_nivel(serie_st, alvo, max_gap=dt.timedelta(0))
        if obs is not None:
            previsto = reg.get("nivel_previsto_cm")
            erro = None if previsto is None else float(previsto) - float(obs)
            reg.update({
                "observado_cm": round(obs),
                "observado_em": obs_em.isoformat(),
                "erro_cm": (round(erro, 1) if erro is not None else None),
                "erro_abs_cm": (round(abs(erro), 1) if erro is not None else None),
                "status_auditoria": "conferido",
                "auditoria_versao": AUDITORIA_VERSAO,
                "auditado_em": agora_brt().isoformat(timespec="seconds"),
            })
        elif ultima_hora and (alvo + AUDITORIA_MAX_GAP) <= ultima_hora:
            # Só marca buraco definitivo depois da janela de tolerância —
            # leituras ANA atrasadas ainda podem chegar e liberar o erro.
            reg["status_auditoria"] = "sem_dado_ana"
            reg["auditoria_versao"] = AUDITORIA_VERSAO
            reg["auditado_em"] = agora_brt().isoformat(timespec="seconds")
    return registros

def media(vals):
    vals = [float(v) for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None

def resumo_auditoria(registros, horizonte, modelo=None):
    regs = [r for r in registros if r.get("horizonte") == horizonte]
    excluidas_grade = 0
    if modelo:
        # Ao trocar a RNA ativa, o histÃ³rico antigo continua Ãºtil para
        # auditoria, mas nÃ£o pode contaminar o erro recente do modelo novo.
        regs = [r for r in regs if r.get("modelo") == modelo]
    if horizonte in {"2h", "2h_versao_b", "4h", "8h", "8h_v002"}:
        # Todos os modelos ativos usam hora cheia. Previsoes legadas feitas
        # em :15/:30/:45 nao entram no indicador do contrato atual.
        apenas_horarias = []
        for reg in regs:
            hora = _parse_hora(reg.get("hora_modelo", ""))
            if hora is not None and hora.minute == 0 and hora.second == 0:
                apenas_horarias.append(reg)
            else:
                excluidas_grade += 1
        regs = apenas_horarias
    conferidos = sorted(
        [r for r in regs if r.get("status_auditoria") == "conferido"],
        key=lambda r: r.get("hora_alvo") or ""
    )
    aguardando = len([r for r in regs if r.get("status_auditoria") == "aguardando"])
    ultimas = conferidos[-12:]
    agora = agora_brt()
    ult24 = []
    for r in conferidos:
        alvo = _parse_hora(r.get("hora_alvo", ""))
        if alvo and (agora - alvo).total_seconds() <= 24 * 3600:
            ult24.append(r)
    mae_modelo_24h = media([r.get("erro_abs_cm") for r in ult24])
    # Baseline causal: persistência mantém o nível da base da previsão.
    # Só compara linhas que possuem nível de referência e observado no alvo.
    persistencia_24h = [
        abs(float(r["observado_cm"]) - float(r["nivel_modelo_cm"]))
        for r in ult24
        if r.get("observado_cm") is not None and r.get("nivel_modelo_cm") is not None
    ]
    mae_persistencia_24h = media(persistencia_24h)
    melhoria_persistencia = None
    if mae_modelo_24h is not None and mae_persistencia_24h not in (None, 0):
        melhoria_persistencia = round((1 - mae_modelo_24h / mae_persistencia_24h) * 100, 1)
    return {
        "n_total": len(regs),
        "modelo": modelo,
        "auditoria_versao": AUDITORIA_VERSAO,
        "grade_modelo": "horaria_exata",
        "n_excluidas_fora_grade": excluidas_grade,
        "n_conferidas": len(conferidos),
        "n_aguardando": aguardando,
        "ultima_conferida": (conferidos[-1] if conferidos else None),
        "mae_ultimas_6_cm": media([r.get("erro_abs_cm") for r in conferidos[-6:]]),
        "mae_24h_cm": mae_modelo_24h,
        "baseline": "persistencia_nivel_modelo_cm",
        "mae_persistencia_24h_cm": mae_persistencia_24h,
        "melhoria_vs_persistencia_24h_pct": melhoria_persistencia,
        "maior_erro_abs_24h_cm": (max([r.get("erro_abs_cm") for r in ult24 if r.get("erro_abs_cm") is not None]) if ult24 else None),
        "ultimas_conferidas": ultimas,
    }

def gerar_saida_modelo(cfg, series, t, aviso, estacoes_status):
    if t is None:
        out = _base_saida(
            cfg, None, None, None,
            "sem hora valida: dependencias temporais atrasadas ou ausentes",
            aviso, [], estacoes_status,
        )
        out["disponivel"] = True
        if cfg.get("montador") == "4h_alt_v01_r10":
            qc_estacoes = [
                {
                    "estacao": item.get("estacao"),
                    "nome": item.get("nome"),
                    "qc_status": item.get("qc_status"),
                    "qc_ultima_fora_faixa": item.get("qc_ultima_fora_faixa"),
                }
                for item in (estacoes_status or [])
                if item.get("qc_status") == "ATENCAO_FORA_FAIXA"
            ]
            out["auditoria_inputs"] = {
                "status": "INVALIDO",
                "motivo": "nenhuma hora-base passou a auditoria de cobertura, atraso e faixa plausivel",
                "n_inputs": cfg.get("inputs_total"),
                "faixa_plausivel_cm": [NIVEL_PLAUSIVEL_MIN_CM, NIVEL_PLAUSIVEL_MAX_CM],
                "estacoes_fora_faixa": qc_estacoes,
            }
        elif cfg.get("input_grade") in ("hourly_exact", "quarter_hour_exact"):
            out["auditoria_inputs"] = {
                "status": "INVALIDO",
                "motivo": "nenhuma hora-base passou a auditoria da grade temporal e cobertura dos inputs",
                "n_inputs": cfg.get("inputs_total"),
                "contrato_temporal": cfg.get("input_contract_version"),
            }
        return out
    try:
        x, st0 = montar_inputs_modelo(cfg, series, t)
    except Exception as e:
        out = _base_saida(cfg, None, None, t, f"falha ao montar inputs: {e}", aviso, [], estacoes_status)
        out["disponivel"] = True
        return out
    if st0 is None or any(v is None for v in x):
        faltando = sum(v is None for v in x)
        inputs_faltantes = diagnosticar_inputs_modelo(cfg, series, t, x)
        out = _base_saida(cfg, st0, None, t, f"inputs incompletos ({faltando}/{cfg['inputs_total']} faltando) - sem previsao nesta hora", aviso, inputs_faltantes, estacoes_status)
        out["disponivel"] = True
        if cfg.get("montador") == "4h_alt_v01_r10":
            out["auditoria_inputs"] = auditoria_inputs_4h_v01_r10(series, t, valores=x)
        elif cfg.get("montador") in ("8h_alt_v001", "8h_alt_v002"):
            out["auditoria_inputs"] = auditoria_inputs_8h(cfg, t, x)
        return out
    try:
        delta_bruto = prever(cfg["mat"], x)
        delta = delta_bruto
        out = _base_saida(cfg, st0, st0 + delta, t, "ok", aviso, [], estacoes_status)
        out["disponivel"] = True
        out["delta_previsto_cm"] = round(delta, 1)
        out["input_values_cm"] = [round(float(v), 3) for v in x]
        if cfg.get("montador") == "2h_alt_15inputs":
            auditoria_inputs = auditoria_inputs_2h(series, t, valores=x, grade=cfg.get("input_grade"))
            out["auditoria_inputs"] = auditoria_inputs
            if auditoria_inputs["status"] == "ATENCAO":
                out["status"] = (
                    "ok - atencao: dependencia de input atrasada "
                    f"({auditoria_inputs['n_inputs_atrasados']} input(s), "
                    f"idade maxima {auditoria_inputs['idade_max_input_min']:.0f} min)"
                )
        elif cfg.get("montador") == "4h_alt_v01_26":
            auditoria_inputs = auditoria_inputs_4h_v01_26(series, t, valores=x)
            out["auditoria_inputs"] = auditoria_inputs
            out["input_anchor_note"] = (
                "NIVEL_ATUAL_CM e a ancora de reconstrução e persistência; "
                "os 26 sinais são enviados ao MAT. A aceleração segue a "
                "segunda diferença discreta da base, sem divisão por horas."
            )
            if auditoria_inputs["status"] == "ATENCAO":
                out["status"] = (
                    "ok - atencao: dependencia de input atrasada "
                    f"({auditoria_inputs['n_inputs_atrasados']} input(s), "
                    f"idade maxima {auditoria_inputs['idade_max_input_min']:.0f} min)"
                )
        elif cfg.get("montador") == "4h_alt_v01_r10":
            auditoria_inputs = auditoria_inputs_4h_v01_r10(series, t, valores=x)
            out["auditoria_inputs"] = auditoria_inputs
            if auditoria_inputs["status"] == "ATENCAO":
                out["status"] = (
                    "ok - atencao: dependencia de input atrasada "
                    f"({auditoria_inputs['n_inputs_atrasados']} input(s), "
                    f"idade maxima {auditoria_inputs['idade_max_input_min']:.0f} min)"
                )
        elif cfg.get("montador") in ("8h_alt_v001", "8h_alt_v002"):
            out["auditoria_inputs"] = auditoria_inputs_8h(cfg, t, x)
            fontes = series.get("__chuva8h_fontes__", {}) or {}
            if fontes:
                out["fontes_chuva_8h"] = fontes
        out["passos"] = [[out["hora_modelo"], out["nivel_rio_agora_cm"], out["nivel_previsto_cm"]]]
        return out
    except Exception as e:
        out = _base_saida(cfg, st0, None, t, f"falha no modelo: {e}", aviso, [], estacoes_status)
        out["disponivel"] = True
        return out

def escolher_hora_modelo(cfg, series, horas_st):
    """Usa a hora mais recente em que todos os inputs do modelo existem."""
    for cand in reversed(horas_st):
        # O modelo 4h foi treinado em timestamps de hora cheia.  Mesmo que a
        # API traga uma leitura de 15/30/45 min, não deslocar silenciosamente
        # a janela: esperar a próxima hora-base completa é mais auditável.
        if not hora_na_grade_do_modelo(cfg, cand):
            continue
        try:
            x, st0 = montar_inputs_modelo(cfg, series, cand)
        except Exception:
            continue
        if st0 is not None and all(v is not None for v in x):
            # Para a V01 PRO, nao escolher uma hora que force uma estacao a
            # fornecer vizinho atrasado. O recuo temporal preserva a coerencia
            # das aceleracoes e evita misturar t=21:45 com uma regua parada em
            # t=21:00. Se nenhuma hora passar, a chamada abaixo ainda produz o
            # diagnostico ATENCAO/INVALIDO em vez de esconder o problema.
            if cfg.get("montador") == "2h_alt_15inputs":
                audit = auditoria_inputs_2h(series, cand, valores=x, grade=cfg.get("input_grade"))
                if audit["status"] != "NORMAL":
                    continue
            elif cfg.get("montador") == "4h_alt_v01_26":
                audit = auditoria_inputs_4h_v01_26(series, cand, valores=x)
                if audit["status"] != "NORMAL":
                    continue
            elif cfg.get("montador") == "4h_alt_v01_r10":
                audit = auditoria_inputs_4h_v01_r10(series, cand, valores=x)
                if audit["status"] != "NORMAL":
                    continue
            return cand
    if cfg.get("input_grade") in ("hourly_exact", "quarter_hour_exact"):
        if cfg.get("montador") in ("8h_alt_v001", "8h_alt_v002"):
            horas_cheias = [hora for hora in horas_st if _eh_hora_cheia(hora)]
            return horas_cheias[-1] if horas_cheias else None
        return None
    return horas_st[-1] if horas_st else None

def escrever_pacote(horizontes, historico, aviso):
    principal = horizontes.get("2h") or next(iter(horizontes.values()))
    pacote = dict(principal)
    pacote["horizontes"] = horizontes
    pacote["auditoria_historico"] = {
        hz: resumo_auditoria(historico, hz, item.get("modelo"))
        for hz, item in horizontes.items()
    }
    pacote["aviso"] = aviso
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(pacote, f, ensure_ascii=False, indent=1)
    print("escrito", SAIDA, "horizontes=", ",".join(horizontes.keys()))

def carregar_saida_atual():
    if not os.path.exists(SAIDA):
        return None
    try:
        with open(SAIDA, "r", encoding="utf-8") as f:
            atual = json.load(f)
        if isinstance(atual, dict):
            return atual
    except Exception as e:
        print("saida atual invalida:", e)
    return None


def saida_respeita_contrato_horario_atual(atual):
    horizontes = (atual or {}).get("horizontes") or {}
    if set(horizontes) != {cfg["horizonte"] for cfg in MODELOS}:
        return False
    for cfg in MODELOS:
        item = horizontes.get(cfg["horizonte"]) or {}
        if item.get("input_grade") != "hourly_exact":
            return False
        if item.get("input_contract_version") != "hourly_exact_v1":
            return False
        if item.get("nivel_previsto_cm") is None:
            continue
        hora = _parse_hora(item.get("hora_modelo") or "")
        audit = item.get("auditoria_inputs") or {}
        if not _eh_hora_cheia(hora) or audit.get("status") != "NORMAL":
            return False
        if audit.get("n_inputs_nao_exatos", 0) != 0:
            return False
    return True


def escrever_pacote_indisponivel(motivo, aviso):
    """Publica estado seguro quando nao existe previsao valida no contrato novo."""
    historico = carregar_historico()
    horizontes = {}
    for cfg in MODELOS:
        out = _base_saida(cfg, None, None, None, motivo, aviso, [], resumo_estacoes({}))
        out["disponivel"] = True
        out["auditoria_inputs"] = {
            "status": "INVALIDO",
            "motivo": motivo,
            "n_inputs": cfg["inputs_total"],
            "input_grade": "hourly_exact",
            "contrato_temporal": "hourly_exact_v1",
        }
        out["auditoria"] = resumo_auditoria(historico, cfg["horizonte"], cfg["modelo"])
        out["qualidade_ao_vivo"] = {
            "status": "DADO_INDISPONIVEL",
            "modelo": cfg["modelo"],
        }
        horizontes[cfg["horizonte"]] = out
    escrever_pacote(horizontes, historico, aviso)


def preservar_saida_valida_em_falha(motivo, aviso):
    """Nao deixa uma falha transitoria da ANA/GitHub apagar o ultimo JSON valido.

    O site deve mostrar que a consulta falhou, mas manter a ultima previsao
    operacional auditavel ate a proxima rodada conseguir novos dados.
    """
    atual = carregar_saida_atual()
    if saida_respeita_contrato_horario_atual(atual):
        agora = agora_brt().isoformat(timespec="seconds")
        atual["consultado_em"] = agora
        atual["status"] = "aguardando nova telemetria"
        atual["status_dados"] = "consulta ANA instavel; exibindo ultima previsao valida"
        atual["erro_robo_ultima_consulta"] = motivo
        atual["aviso"] = aviso
        for hz, item in (atual.get("horizontes") or {}).items():
            if isinstance(item, dict) and item.get("nivel_previsto_cm") is not None:
                item["consultado_em"] = agora
                item["status"] = "aguardando nova telemetria"
                item["status_dados"] = "consulta ANA instavel; exibindo ultima previsao valida"
                item["erro_robo_ultima_consulta"] = motivo
        with open(SAIDA, "w", encoding="utf-8") as f:
            json.dump(atual, f, ensure_ascii=False, indent=1)
        print("mantida ultima previsao valida:", motivo)
        return
    escrever_pacote_indisponivel(motivo, aviso)

def algum_horizonte_com_previsao(horizontes):
    return any(
        isinstance(item, dict) and item.get("nivel_previsto_cm") is not None
        for item in (horizontes or {}).values()
    )

def main():
    aviso = "EXPERIMENTAL - nao e alerta oficial. Teste interno da previsao de RNA (2h principal, 2h versao B em sombra, 4h, 8h V001 e 8h V002), em paralelo ao SGB/SACE. A versao B e o 8h V002 sao comparativos."
    try:
        # As consultas são independentes. Paralelizar evita que um timeout de
        # uma estação deixe o painel sem atualização por vários minutos.
        series = buscar_series_paralelo(ESTACOES, buscar_ana, max_workers=6)
        series["__chuva36h_postos__"] = buscar_series_paralelo(
            POSTOS_CHUVA_36H, buscar_ana_chuva, max_workers=6
        )
        series["__chuva8h_postos__"] = buscar_chuvas_8h(series)
    except Exception as e:
        preservar_saida_valida_em_falha(f"falha na telemetria: {e}", aviso); return

    horas = sorted(series["86472600"].keys())
    if not horas:
        preservar_saida_valida_em_falha("sem dado recente em Santa Tereza", aviso); return
    t = horas[-1]
    estacoes_status = resumo_estacoes(series)

    horizontes = {}
    for cfg in MODELOS:
        t_modelo = escolher_hora_modelo(cfg, series, horas)
        horizontes[cfg["horizonte"]] = gerar_saida_modelo(cfg, series, t_modelo, aviso, estacoes_status)

    if not algum_horizonte_com_previsao(horizontes):
        preservar_saida_valida_em_falha("inputs incompletos por consulta instavel das estacoes a montante", aviso)
        return

    historico = carregar_historico()
    for out in horizontes.values():
        historico = upsert_previsao_historico(historico, out)
    historico = conferir_historico(historico, series)
    salvar_historico(historico)

    # Se a hora do modelo ficou muito atrás da telemetria (buraco ANA),
    # o painel precisa dizer isso — senão parece "ok" com previsão velha.
    tel = ULTIMA_RAW.get("86472600")
    for hz, out in horizontes.items():
        out["auditoria"] = resumo_auditoria(historico, hz, out.get("modelo"))
        audit = out["auditoria"]
        mae24 = audit.get("mae_24h_cm")
        max24 = audit.get("maior_erro_abs_24h_cm")
        if out.get("status", "").startswith("ok") and (
            (mae24 is not None and mae24 > LIVE_WARN_MAE_24H_CM)
            or (max24 is not None and max24 > LIVE_WARN_MAX_24H_CM)
        ):
            out["qualidade_ao_vivo"] = {
                "status": "ATENCAO",
                "regra": "MAE_24H_CM > 30 ou MAIOR_ERRO_ABS_24H_CM > 100",
                "mae_24h_cm": mae24,
                "maior_erro_abs_24h_cm": max24,
                "modelo": out.get("modelo"),
            }
            out["status"] = (
                f"{out['status']} - atencao: erro recente do modelo ativo acima do guardrail"
            )
        else:
            if out.get("nivel_previsto_cm") is None and (out.get("auditoria_inputs") or {}).get("status") == "INVALIDO":
                qualidade_status = "DADO_INVALIDO_REVISAR"
            else:
                qualidade_status = (
                    "SEM_VALIDACAO_HISTORICA"
                    if out.get("shadow_only") and not audit.get("n_conferidas")
                    else "NORMAL"
                )
            out["qualidade_ao_vivo"] = {
                "status": qualidade_status,
                "regra": "MAE_24H_CM > 30 ou MAIOR_ERRO_ABS_24H_CM > 100",
                "mae_24h_cm": mae24,
                "maior_erro_abs_24h_cm": max24,
                "modelo": out.get("modelo"),
            }
        hm = _parse_hora(out.get("hora_modelo") or "")
        if tel and hm and out.get("nivel_previsto_cm") is not None:
            atraso_h = (tel[0] - hm).total_seconds() / 3600.0
            if (
                out.get("input_grade") == "hourly_exact"
                and atraso_h >= INPUT_WARN_MAX_AGE.total_seconds() / 3600.0
                and str(out.get("status") or "").startswith("ok")
            ):
                out["status"] = (
                    f"{out['status']} - atencao: hora-base {atraso_h:.1f}h atrasada "
                    "para manter a grade horaria exata"
                )
            elif atraso_h >= 2.0 and out.get("status") == "ok":
                out["status"] = (
                    f"ok (base {atraso_h:.1f}h atrasada vs telemetria — "
                    "inputs preenchidos com interpolacao em buracos ANA)"
                )
    escrever_pacote(horizontes, historico, aviso)
    return

if __name__ == "__main__":
    main()
