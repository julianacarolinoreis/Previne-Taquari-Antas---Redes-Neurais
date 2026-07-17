#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Robô AO VIVO — PREVINE / Santa Tereza (86472600)
Roda no GitHub Actions (a cada 30 min):
  1) busca a telemetria da ANA (níveis das estações)
  2) monta os 15 inputs do melhor modelo de 2h (ALT)
  3) roda a RNA (.mat) -> variação prevista -> nível daqui a 2h
  4) escreve previsao_ao_vivo.json (que o site lê e mostra)

EXPERIMENTAL — não é alerta oficial.
"""
import sys, json, datetime as dt, urllib.request, xml.etree.ElementTree as ET
import numpy as np
from scipy.io import loadmat

BRT = dt.timezone(dt.timedelta(hours=-3))

def agora_brt():
    return dt.datetime.now(BRT).replace(tzinfo=None)

# ---- config ----
MODELO_MAT = "previne/assets/mat/rot_003_06_2h_alt_2H_ALT_C0472.mat"   # relativo à raiz do repo
HORIZONTE = "2h"
COMBO = "C0472"
BANKFULL_CM = 400           # zero da mancha (provisório): ancorado na cota de
                            # inundação oficial (15 m) via ANADEM — ver
                            # codigo_python/04_zero_regua/. Definitivo aguarda a
                            # cota oficial do zero da régua (SGB/ANA).
SAIDA = "previsao_ao_vivo.json"   # na RAIZ: é onde o simulador publicado lê
ANA = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ESTACOES = ["86472600", "86472000", "86125130", "86507000"]   # ST, R.Antas, Ituim, Carreiro
ULTIMA_RAW = {}
NOMES_ESTACOES = {
    "86472600": "Santa Tereza",
    "86472000": "Rio das Antas / Santa Tereza montante",
    "86125130": "Ituim",
    "86507000": "Carreiro",
}

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
    """Percorre o XML e monta {hora_cheia: nivel_cm}. Aceita variações de tag.

    A RNA foi treinada com dados horários. Por isso, a série do modelo usa
    apenas leituras exatamente na hora cheia. A última leitura bruta fica
    guardada separadamente para auditoria/frescor no site.
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
        if t.minute == 0 and t.second == 0:
            serie[t.replace(minute=0, second=0, microsecond=0)] = valor
    return serie, ultima_raw

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

def buscar_ana(cod, dias=5):
    """Retorna dict {hora_cheia: nivel_cm}. Usa uma janela de datas explícita
    (a ANA responde ErrorTable quando as datas vêm em branco); mantém o modo
    'datas em branco' apenas como reserva."""
    fim = agora_brt()
    ini = fim - dt.timedelta(days=dias)
    tentativas = [
        f"{ANA}?codEstacao={cod}&dataInicio={ini:%d/%m/%Y}&dataFim={fim:%d/%m/%Y}",
        f"{ANA}?codEstacao={cod}&dataInicio=&dataFim=",
    ]
    for url in tentativas:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "previne-robo/1.0"})
            xml = urllib.request.urlopen(req, timeout=60).read()
            serie, nbytes, ultima_raw = _serie_de_xml(xml)
            print(f"[ANA {cod}] {url.split('?')[1][:40]}... bytes={nbytes} linhas={len(serie)}")
            if ultima_raw:
                ULTIMA_RAW[cod] = ultima_raw
            if serie:
                return serie
            if nbytes:                          # veio resposta mas 0 linhas -> mostra amostra
                amostra = xml[:600].decode("utf-8", "replace").replace("\n", " ")
                print(f"[ANA {cod}] amostra: {amostra}")
        except Exception as e:
            print(f"[ANA {cod}] erro: {e}")
    return {}

def nivel(serie, t):
    return serie.get(t)                                     # nível na hora t (ou None)

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
        n("86472600", 0),      # K inp01  nível ST 86472600
        D("86472600", 1),      # L inp02  ST D-1h
        n("86472000", 0),      # M inp03  nível R.Antas 86472000
        D("86472000", 5),      # N inp04  Antas D-5h
        A("86472000", 20),     # O inp05  Antas A-20h  (passado, t-20/t-21)
        n("86125130", 0),      # P inp06  nível Ituim 86125130
        D("86125130", 12),     # Q inp07  Ituim D-12h
        n("86507000", 0),      # R inp08  nível Carreiro 86507000
        D("86507000", 16),     # S inp09  Carreiro D-16h
        D("86472600", 2),      # T inp10  ST D-2h
        D("86472600", 4),      # U inp11  ST D-4h
        A("86472600", 1),      # V inp12  ST A-1h
        A("86472600", 2),      # W inp13  ST A-2h
        A("86472600", 4),      # X inp14  ST A-4h
        A("86472600", 12),     # Y inp15  ST A-12h
    ]
    return inputs, st0

def diagnosticar_inputs_faltantes(series, t, inputs):
    """Explica quais leituras horarias faltaram para montar cada input."""
    especificacoes = [
        ("inp01", "Santa Tereza - nivel atual", "86472600", [0]),
        ("inp02", "Santa Tereza - nivel D-1h", "86472600", [0, 1]),
        ("inp03", "Rio das Antas montante - nivel atual", "86472000", [0]),
        ("inp04", "Rio das Antas montante - nivel D-5h", "86472000", [0, 5]),
        ("inp05", "Rio das Antas montante - aceleracao A-20h", "86472000", [0, 1, 20, 21]),
        ("inp06", "Ituim - nivel atual", "86125130", [0]),
        ("inp07", "Ituim - nivel D-12h", "86125130", [0, 12]),
        ("inp08", "Carreiro - nivel atual", "86507000", [0]),
        ("inp09", "Carreiro - nivel D-16h", "86507000", [0, 16]),
        ("inp10", "Santa Tereza - nivel D-2h", "86472600", [0, 2]),
        ("inp11", "Santa Tereza - nivel D-4h", "86472600", [0, 4]),
        ("inp12", "Santa Tereza - aceleracao A-1h", "86472600", [0, 1, 2]),
        ("inp13", "Santa Tereza - aceleracao A-2h", "86472600", [0, 1, 2, 3]),
        ("inp14", "Santa Tereza - aceleracao A-4h", "86472600", [0, 1, 4, 5]),
        ("inp15", "Santa Tereza - aceleracao A-12h", "86472600", [0, 1, 12, 13]),
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
    m = loadmat(mat_path, squeeze_me=True)
    wh = np.atleast_2d(np.asarray(m["wh"], float))    # (30,15)
    bh = np.asarray(m["bh"], float).ravel()           # (30,)
    ws = np.asarray(m["ws"], float).ravel()           # (30,)
    bs = float(np.atleast_1d(m["bs"])[0])
    ae = np.asarray(m["ae"], float).ravel()           # desvio por input
    be = np.asarray(m["be"], float).ravel()           # média por input
    au = float(np.atleast_1d(m["au"])[0])
    bu = float(np.atleast_1d(m["bu"])[0])
    logsig = lambda z: 1.0 / (1.0 + np.exp(-z))
    pn = (np.asarray(x, float) - be) / ae
    h  = logsig(wh.dot(pn) + bh)
    yn = logsig(ws.dot(h) + bs)
    return float(yn * au + bu)                        # variação prevista (cm)

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

def main():
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
