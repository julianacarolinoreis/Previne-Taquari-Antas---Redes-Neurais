#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Robô AO VIVO — PREVINE / Santa Tereza (86472600)
Roda no GitHub Actions (a cada ~15 min):
  1) busca a telemetria da ANA (níveis das estações)
  2) monta os 15 inputs do melhor modelo de 2h (ALT)
  3) roda a RNA (.mat) -> variação prevista -> nível daqui a 2h
  4) escreve previsao_ao_vivo.json (que o site lê e mostra)

EXPERIMENTAL — não é alerta oficial.
"""
import os, sys, json, datetime as dt, time, urllib.request, xml.etree.ElementTree as ET
import numpy as np
from scipy.io import loadmat

BRT = dt.timezone(dt.timedelta(hours=-3))

def agora_brt():
    return dt.datetime.now(BRT).replace(tzinfo=None)

# ---- config ----
MODELO_MAT = "previne/assets/mat/RNAPREV__SANTA_TEREZA__02h__ALT__15inputs_VFINAL.mat"   # relativo à raiz do repo
HORIZONTE = "2h"
COMBO = "VFINAL_15IN"
BANKFULL_CM = 400           # zero da mancha (provisório): ancorado na cota de
                            # inundação oficial (15 m) via ANADEM — ver
                            # codigo_python/04_zero_regua/. Definitivo aguarda a
                            # cota oficial do zero da régua (SGB/ANA).
SAIDA = "previsao_ao_vivo.json"   # na RAIZ: é onde o simulador publicado lê
HISTORICO_SAIDA = "historico_previsoes_ao_vivo.json"
ANA = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ESTACOES_NIVEL = ["86472600", "86472000", "86125130", "86306000", "86448000"]
ESTACOES = ESTACOES_NIVEL
POSTOS_CHUVA_36H = ["2851044", "2851072", "86488000", "86490500", "86497000", "86505500", "86507000"]
ANA_TIMEOUT_NIVEL_S = 25
ANA_TIMEOUT_CHUVA_S = 15
ANA_RETRIES_NIVEL = 2
ANA_RETRIES_CHUVA = 1
ULTIMA_RAW = {}
NOMES_ESTACOES = {
    "86472600": "Santa Tereza",
    "86472000": "Linha Jose Julio / Rio das Antas montante",
    "86125130": "Ituim",
    "86306000": "Nova Roma do Sul / Rio das Antas",
    "86448000": "Veranopolis / Rio das Antas",
    "86507000": "Carreiro",
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
        "montador": "2h_alt_vfinal",
        "principal": True,
    },
    {
        "horizonte": "4h",
        "horizonte_h": 4,
        "tipo": "ALT",
        "modelo": "4H_ALT_PRIO_12478",
        "mat": "previne/assets/mat/RNAPREV__SANTA_TEREZA__04h__ALT__prio_12478.mat",
        "inputs_total": 5,
        "montador": "4h_alt_prio_12478",
        "principal": False,
    },
    {
        "horizonte": "4h_cascata",
        "rotulo": "4h cascata",
        "horizonte_h": 4,
        "tipo": "ALT_CASCATA",
        "modelo": "4H_ALT_CASCATA2H_C002_ALT2H",
        "mat": "previne/assets/mat/RNAPREV__SANTA_TEREZA__04h__ALT__CASCATA2H_C002_ALT2H.mat",
        "inputs_total": 6,
        "montador": "4h_alt_cascata_2h_alt",
        "principal": False,
        "cascata": {
            "modelo_base": COMBO,
            "modelo_base_horizonte": "2h",
            "input_nome": "delta previsto pela RNA 2h",
        },
    },
    {
        "horizonte": "8h",
        "horizonte_h": 8,
        "tipo": "ALT",
        "modelo": "8H_ALT_C0217",
        "mat": "previne/assets/mat/RNAPREV__SANTA_TEREZA__08h__ALT__C0217.mat",
        "inputs_total": 10,
        "montador": "8h_alt_c0217",
        "principal": False,
        "teste_interno": True,
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

def nivel(serie, t):
    return serie.get(t)                                     # nível no timestamp t (ou None)

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
    return nivel(series.get(cod, {}), t - dt.timedelta(hours=h))

def _D(series, cod, t, h):
    a, b = _n(series, cod, t, 0), _n(series, cod, t, h)
    return None if None in (a, b) else a - b

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
        return nivel(series[cod], t - dt.timedelta(hours=h))
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
        A("86472000", 20),     # inp15 Linha Jose Julio / Antas A-20h
    ]
    return inputs, st0

def montar_inputs_4h(series, t):
    """Monta os 5 inputs do 4h ALT prio_12478 conforme planilha auditavel."""
    def n(cod, h=0):
        return nivel(series.get(cod, {}), t - dt.timedelta(hours=h))
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

def montar_inputs_4h_cascata_2h_alt(series, t):
    """Modelo 4h em cascata: inputs do 4h ALT + delta previsto pela RNA 2h."""
    inputs4, st0 = montar_inputs_4h(series, t)
    delta_2h = None
    try:
        x2h, st2h = montar_inputs(series, t)
        if st2h is not None and all(v is not None for v in x2h):
            delta_2h = prever(MODELO_MAT, x2h)
    except Exception:
        delta_2h = None
    return inputs4 + [delta_2h], st0

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
    if cfg["montador"] == "2h_alt_vfinal":
        return montar_inputs(series, t)
    if cfg["montador"] == "4h_alt_prio_12478":
        return montar_inputs_4h(series, t)
    if cfg["montador"] == "4h_alt_cascata_2h_alt":
        return montar_inputs_4h_cascata_2h_alt(series, t)
    if cfg["montador"] == "8h_alt_c0217":
        return montar_inputs_8h_alt_c0217(series, t)
    if cfg["montador"] == "12h_alt_c0065":
        return montar_inputs_12h_alt_c0065(series, t)
    raise ValueError("montador desconhecido: " + str(cfg["montador"]))

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
        ("inp15", "Linha Jose Julio / Rio das Antas - aceleracao A-20h", "86472000", [0, 1, 20, 21]),
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

def diagnosticar_inputs_faltantes_4h_cascata_2h_alt(series, t, inputs):
    faltantes = diagnosticar_inputs_faltantes_4h(series, t, inputs[:5])
    if len(inputs) > 5 and inputs[5] is None:
        dependencias = []
        try:
            x2h, _ = montar_inputs(series, t)
            dependencias = diagnosticar_inputs_faltantes(series, t, x2h)
        except Exception as e:
            dependencias = [{"input": "RNA_2H", "descricao": f"falha ao montar RNA 2h: {e}"}]
        faltantes.append({
            "input": "inp06",
            "descricao": "delta previsto pela RNA 2h usado como input da cascata 4h",
            "estacao": "RNA_2H",
            "estacao_nome": "RNA Santa Tereza 2h ALT",
            "horarios_necessarios": [t.isoformat(timespec="minutes")],
            "horarios_faltantes": [t.isoformat(timespec="minutes")],
            "dependencias_faltantes": dependencias,
        })
    return faltantes

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

def diagnosticar_inputs_modelo(cfg, series, t, inputs):
    if cfg["montador"] == "4h_alt_prio_12478":
        return diagnosticar_inputs_faltantes_4h(series, t, inputs)
    if cfg["montador"] == "4h_alt_cascata_2h_alt":
        return diagnosticar_inputs_faltantes_4h_cascata_2h_alt(series, t, inputs)
    if cfg["montador"] == "8h_alt_c0217":
        return diagnosticar_inputs_faltantes_8h(series, t, inputs)
    if cfg["montador"] == "12h_alt_c0065":
        return diagnosticar_inputs_faltantes_12h(series, t, inputs)
    return diagnosticar_inputs_faltantes(series, t, inputs)

def resumo_estacoes(series):
    resumo = []
    for cod in ESTACOES:
        serie = series.get(cod, {})
        raw = ULTIMA_RAW.get(cod)
        ultima_hora = max(serie) if serie else None
        resumo.append({
            "estacao": cod,
            "nome": NOMES_ESTACOES.get(cod, cod),
            "horas_modelo_disponiveis": len(serie),
            "ultima_hora_modelo": (ultima_hora.isoformat(timespec="minutes") if ultima_hora else None),
            "ultima_hora_modelo_nivel_cm": (round(serie[ultima_hora]) if ultima_hora else None),
            "ultima_leitura_bruta": (raw[0].isoformat(timespec="minutes") if raw else None),
            "ultima_leitura_bruta_nivel_cm": (round(raw[1]) if raw else None),
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

def escrever(nivel_atual, nivel_prev, t, status, aviso, inputs_faltantes=None, estacoes_status=None):
    consultado_em = agora_brt()
    raw_st = ULTIMA_RAW.get("86472600")
    idade_min = None
    status_dados = None
    if raw_st:
        idade_min = round((consultado_em - raw_st[0]).total_seconds() / 60)
        status_dados = "telemetria recente" if idade_min <= 120 else f"telemetria atrasada ({idade_min} min)"
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
        status_dados = "telemetria recente" if idade_min <= 120 else f"telemetria atrasada ({idade_min} min)"
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
        "criado_em": saida.get("consultado_em"),
    }
    for i, reg in enumerate(registros):
        if reg.get("id") == chave:
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
        if reg.get("status_auditoria") == "conferido":
            continue
        alvo = _parse_hora(reg.get("hora_alvo", ""))
        if alvo is None:
            continue
        obs = serie_st.get(alvo)
        if obs is not None:
            previsto = reg.get("nivel_previsto_cm")
            erro = None if previsto is None else float(previsto) - float(obs)
            reg.update({
                "observado_cm": round(obs),
                "observado_em": alvo.isoformat(),
                "erro_cm": (round(erro, 1) if erro is not None else None),
                "erro_abs_cm": (round(abs(erro), 1) if erro is not None else None),
                "status_auditoria": "conferido",
                "auditado_em": agora_brt().isoformat(timespec="seconds"),
            })
        elif ultima_hora and alvo <= ultima_hora:
            reg["status_auditoria"] = "sem_dado_ana"
            reg["auditado_em"] = agora_brt().isoformat(timespec="seconds")
    return registros

def media(vals):
    vals = [float(v) for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None

def resumo_auditoria(registros, horizonte):
    regs = [r for r in registros if r.get("horizonte") == horizonte]
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
    return {
        "n_total": len(regs),
        "n_conferidas": len(conferidos),
        "n_aguardando": aguardando,
        "ultima_conferida": (conferidos[-1] if conferidos else None),
        "mae_ultimas_6_cm": media([r.get("erro_abs_cm") for r in conferidos[-6:]]),
        "mae_24h_cm": media([r.get("erro_abs_cm") for r in ult24]),
        "maior_erro_abs_24h_cm": (max([r.get("erro_abs_cm") for r in ult24 if r.get("erro_abs_cm") is not None]) if ult24 else None),
        "ultimas_conferidas": ultimas,
    }

def gerar_saida_modelo(cfg, series, t, aviso, estacoes_status):
    try:
        x, st0 = montar_inputs_modelo(cfg, series, t)
    except Exception as e:
        return _base_saida(cfg, None, None, t, f"falha ao montar inputs: {e}", aviso, [], estacoes_status)
    if st0 is None or any(v is None for v in x):
        faltando = sum(v is None for v in x)
        inputs_faltantes = diagnosticar_inputs_modelo(cfg, series, t, x)
        return _base_saida(cfg, st0, None, t, f"inputs incompletos ({faltando}/{cfg['inputs_total']} faltando) - sem previsao nesta hora", aviso, inputs_faltantes, estacoes_status)
    try:
        delta = prever(cfg["mat"], x)
        out = _base_saida(cfg, st0, st0 + delta, t, "ok", aviso, [], estacoes_status)
        out["delta_previsto_cm"] = round(delta, 1)
        if cfg.get("cascata"):
            out["modo_cascata"] = True
            out["modelo_base_2h"] = cfg["cascata"]["modelo_base"]
            out["input_cascata_nome"] = cfg["cascata"]["input_nome"]
            out["input_cascata_2h_cm"] = round(float(x[-1]), 1)
            out["observacao_cascata"] = "Modelo 4h ALT alimentado com a previsao do modelo 2h ALT na mesma hora-base."
        out["passos"] = [[out["hora_modelo"], out["nivel_rio_agora_cm"], out["nivel_previsto_cm"]]]
        return out
    except Exception as e:
        return _base_saida(cfg, st0, None, t, f"falha no modelo: {e}", aviso, [], estacoes_status)

def escolher_hora_modelo(cfg, series, horas_st):
    """Usa a hora mais recente em que todos os inputs do modelo existem."""
    for cand in reversed(horas_st):
        try:
            x, st0 = montar_inputs_modelo(cfg, series, cand)
        except Exception:
            continue
        if st0 is not None and all(v is not None for v in x):
            return cand
    return horas_st[-1] if horas_st else None

def escrever_pacote(horizontes, historico, aviso):
    principal = horizontes.get("2h") or next(iter(horizontes.values()))
    pacote = dict(principal)
    pacote["horizontes"] = horizontes
    pacote["auditoria_historico"] = {
        hz: resumo_auditoria(historico, hz) for hz in horizontes.keys()
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

def preservar_saida_valida_em_falha(motivo, aviso):
    """Nao deixa uma falha transitoria da ANA/GitHub apagar o ultimo JSON valido.

    O site deve mostrar que a consulta falhou, mas manter a ultima previsao
    operacional auditavel ate a proxima rodada conseguir novos dados.
    """
    atual = carregar_saida_atual()
    if atual and atual.get("nivel_previsto_cm") is not None and atual.get("hora_modelo"):
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
    escrever(None, None, None, motivo, aviso)

def main():
    aviso = "EXPERIMENTAL - nao e alerta oficial. Teste interno da previsao de RNA (2h, 4h, 4h cascata e 8h), em paralelo ao SGB/SACE."
    try:
        series = {c: buscar_ana(c) for c in ESTACOES}
        series["__chuva36h_postos__"] = {c: buscar_ana_chuva(c) for c in POSTOS_CHUVA_36H}
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

    historico = carregar_historico()
    for out in horizontes.values():
        historico = upsert_previsao_historico(historico, out)
    historico = conferir_historico(historico, series)
    salvar_historico(historico)

    for hz, out in horizontes.items():
        out["auditoria"] = resumo_auditoria(historico, hz)
    escrever_pacote(horizontes, historico, aviso)
    return

    aviso = "EXPERIMENTAL — não é alerta oficial. Camada espacial da previsão de RNA (2h), em paralelo ao SGB/SACE."
    try:
        series = {c: buscar_ana(c) for c in ESTACOES}
    except Exception as e:
        escrever(None, None, None, f"falha na telemetria: {e}", aviso); return
    # última hora com nível em ST
    horas = sorted(series["86472600"].keys())
    if not horas:
        escrever(None, None, None, "sem dado recente em Santa Tereza", aviso); return
    t = horas[-1]
    x, st0 = montar_inputs(series, t)
    estacoes_status = resumo_estacoes(series)
    if st0 is None or any(v is None for v in x):
        faltando = sum(v is None for v in x)
        inputs_faltantes = diagnosticar_inputs_faltantes(series, t, x)
        escrever(st0, None, t, f"inputs incompletos ({faltando}/15 faltando) — sem previsão nesta hora", aviso, inputs_faltantes, estacoes_status); return
    try:
        delta = prever(MODELO_MAT, x)
        escrever(st0, st0 + delta, t, "ok", aviso, [], estacoes_status)
    except Exception as e:
        escrever(st0, None, t, f"falha no modelo: {e}", aviso, [], estacoes_status)

if __name__ == "__main__":
    main()
