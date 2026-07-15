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
    """Monta os 15 inputs na hora t. Ordem/def confirmadas com a aba INPUTS do modelo."""
    ST, ANT, ITU, CAR = (series["86472600"], series["86472000"], series["86125130"], series["86507000"])
    def n(s, h=0): return nivel(s, t - dt.timedelta(hours=h))
    # ST 86472600
    st0 = n(ST, 0)
    d1  = None if None in (st0, n(ST,1)) else st0 - n(ST,1)   # Δ1h
    d2  = None if None in (st0, n(ST,2)) else st0 - n(ST,2)   # Δ2h
    d4  = None if None in (st0, n(ST,4)) else st0 - n(ST,4)   # Δ4h
    def dd(k):  # 2ª derivada na escala k:  n(t) - 2 n(t-k) + n(t-2k)
        a, b, c = n(ST,0), n(ST,k), n(ST,2*k)
        return None if None in (a,b,c) else a - 2*b + c
    inputs = [
        st0, d1, d2, d4, dd(1), dd(2), dd(4), dd(12),          # ST: 8
        n(ANT,0), n(ANT,5), n(ANT,20),                          # R.Antas 86472000: nível, D-5h, A-20h
        n(ITU,0), n(ITU,12),                                    # Ituim 86125130: nível, D-12h
        n(CAR,0), n(CAR,16),                                    # Carreiro 86507000: nível, D-16h
    ]
    return inputs, st0

def prever(mat_path, x):
    """Forward pass da MLP (MATLAB feedforwardnet). x: lista de 15 inputs.
       *** A confirmar com a estrutura real do .mat (nomes das variáveis) ***
       Padrão MATLAB: mapminmax nos inputs -> tansig(IW*xn+b1) -> purelin(LW*h+b2) -> denorm.
       Modelo ALT devolve a VARIAÇÃO (Δnível em 2h)."""
    m = loadmat(mat_path)
    # nomes tentativos — Dispatch confirma/ajusta:
    def pick(*names):
        for nm in names:
            if nm in m: return np.array(m[nm]).squeeze()
        raise KeyError(f"variável não encontrada no .mat: {names}")
    IW = np.atleast_2d(pick("IW","W1","iw","net_IW"))
    b1 = pick("b1","B1","bias1")
    LW = np.atleast_2d(pick("LW","W2","lw","net_LW"))
    b2 = float(np.atleast_1d(pick("b2","B2","bias2"))[0])
    xin = np.array(x, dtype=float)
    # normalização de entrada (mapminmax) — se salva no .mat
    xmin = pick("xmin","inmin","xoffset") if any(k in m for k in ("xmin","inmin","xoffset")) else xin*0-1
    xmax = pick("xmax","inmax") if any(k in m for k in ("xmax","inmax")) else xin*0+1
    xn = 2*(xin - xmin)/(np.where(xmax-xmin==0,1,xmax-xmin)) - 1
    h = np.tanh(IW.dot(xn) + b1)                # tansig
    yn = LW.dot(h) + b2                          # purelin
    yn = float(np.atleast_1d(yn)[0])
    ymin = float(np.atleast_1d(pick("ymin","outmin"))[0]) if any(k in m for k in ("ymin","outmin")) else -1
    ymax = float(np.atleast_1d(pick("ymax","outmax"))[0]) if any(k in m for k in ("ymax","outmax")) else 1
    y = (yn + 1)/2*(ymax - ymin) + ymin
    return y                                     # variação prevista (cm)

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
