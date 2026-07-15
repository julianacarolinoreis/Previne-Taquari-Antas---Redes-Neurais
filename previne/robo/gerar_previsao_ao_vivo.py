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

# ---- config ----
MODELO_MAT = "assets/mat/rot_003_06_2h_alt_2H_ALT_C0472.mat"   # <- Dispatch commita o .mat aqui
HORIZONTE = "2h"
COMBO = "C0472"
BANKFULL_CM = 300           # calibração régua<->leito (mesma do site)
SAIDA = "previsao_ao_vivo.json"
ANA = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ESTACOES = ["86472600", "86472000", "86125130", "86507000"]   # ST, R.Antas, Ituim, Carreiro

def buscar_ana(cod):
    """Retorna dict {datetime_hora_cheia: nivel_cm} da estação.
    Datas em branco: a ANA devolve a série recente (últimos registros)."""
    url = f"{ANA}?codEstacao={cod}&dataInicio=&dataFim="
    req = urllib.request.Request(url, headers={"User-Agent": "previne-robo/1.0"})
    xml = urllib.request.urlopen(req, timeout=60).read()
    root = ET.fromstring(xml)
    def local(tag):                     # remove {namespace} do nome
        return tag.rsplit("}", 1)[-1]
    serie = {}
    for row in root.iter():
        campos = {local(ch.tag): (ch.text or "") for ch in row}
        dh, niv = campos.get("DataHora"), campos.get("Nivel")
        if not dh or niv in (None, ""):  continue
        try:
            t = dt.datetime.fromisoformat(dh.strip().replace("T", " ")[:19])
        except Exception:
            try: t = dt.datetime.strptime(dh.strip()[:16], "%d/%m/%Y %H:%M")
            except Exception: continue
        t = t.replace(minute=0, second=0, microsecond=0)     # normaliza p/ hora cheia
        try: serie[t] = float(str(niv).replace(",", "."))
        except Exception: pass
    return serie

def nivel(serie, t):
    return serie.get(t)                                     # nível na hora t (ou None)

def montar_inputs(series, t):
    """Monta os 15 inputs na hora t, na ORDEM EXATA das colunas K..Y do modelo
    (workbook AUDITAVEL_INPUTS_RNA, validado 100% contra o .mat).

    Convenções (validadas linha a linha):
      D-Xh(s) = n(t) - n(t-Xh)                                  (diferença p/ trás)
      A-Xh(s) = [n(t)-n(t-1h)] - [n(t-Xh)-n(t-Xh-1h)]           (aceleração)
    """
    ST, ANT, ITU, CAR = (series["86472600"], series["86472000"],
                         series["86125130"], series["86507000"])
    def n(s, h=0): return nivel(s, t - dt.timedelta(hours=h))
    def D(s, h):
        a, b = n(s, 0), n(s, h)
        return None if None in (a, b) else a - b
    def A(s, h):
        a, b, c, d = n(s, 0), n(s, 1), n(s, h), n(s, h + 1)
        return None if None in (a, b, c, d) else (a - b) - (c - d)
    st0 = n(ST, 0)
    inputs = [
        n(ST, 0),        # K inp01  nível ST 86472600
        D(ST, 1),        # L inp02  ST D-1h
        n(ANT, 0),       # M inp03  nível R.Antas 86472000
        D(ANT, 5),       # N inp04  Antas D-5h
        A(ANT, 20),      # O inp05  Antas A-20h  (passado, t-20/t-21)
        n(ITU, 0),       # P inp06  nível Ituim 86125130
        D(ITU, 12),      # Q inp07  Ituim D-12h
        n(CAR, 0),       # R inp08  nível Carreiro 86507000
        D(CAR, 16),      # S inp09  Carreiro D-16h
        D(ST, 2),        # T inp10  ST D-2h
        D(ST, 4),        # U inp11  ST D-4h
        A(ST, 1),        # V inp12  ST A-1h
        A(ST, 2),        # W inp13  ST A-2h
        A(ST, 4),        # X inp14  ST A-4h
        A(ST, 12),       # Y inp15  ST A-12h
    ]
    return inputs, st0

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

def escrever(nivel_atual, nivel_prev, t, status, aviso):
    out = {
        "modo": "ao_vivo",
        "gerado_em": (t.isoformat() if t else dt.datetime.now().isoformat()),
        "estacao": "86472600", "local": "Santa Tereza",
        "horizonte": HORIZONTE, "modelo": COMBO, "bankfull_cm": BANKFULL_CM,
        "nivel_atual_cm": (round(nivel_atual) if nivel_atual is not None else None),
        "nivel_previsto_cm": (round(nivel_prev) if nivel_prev is not None else None),
        "status": status,
        "aviso": aviso,
    }
    json.dump(out, open(SAIDA, "w"), ensure_ascii=False, indent=1)
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
    if st0 is None or any(v is None for v in x):
        faltando = sum(v is None for v in x)
        escrever(st0, None, t, f"inputs incompletos ({faltando}/15 faltando) — sem previsão nesta hora", aviso); return
    try:
        delta = prever(MODELO_MAT, x)
        escrever(st0, st0 + delta, t, "ok", aviso)
    except Exception as e:
        escrever(st0, None, t, f"falha no modelo: {e}", aviso)

if __name__ == "__main__":
    main()
