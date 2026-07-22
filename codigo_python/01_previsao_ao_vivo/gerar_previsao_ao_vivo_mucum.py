#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Robô AO VIVO — PREVINE / Muçum (86510000)
Espelha o robô do Santa Tereza. Roda no GitHub Actions (a cada 30 min):
  1) busca a telemetria da ANA (níveis de Muçum e da montante Santa Tereza)
  2) monta os inputs do modelo campeão de 2h na ordem exata
  3) roda a RNA (.mat) -> variação prevista -> nível daqui a 2h
  4) escreve previsao_ao_vivo_mucum.json (que o site lê e mostra)

EXPERIMENTAL — não é alerta oficial.

Campeão 2h: MUC_H2_ALT_STC002_R2M001 (10 inputs, 20 neurônios, PERS_teste 0.83).
Receita dos 10 inputs (confirmada pelo Dispatch):
  Muçum 86510000:  nível atual (D0h) + vel_nivel D1h, D2h, D3h, D4h
  S.Tereza 86472600: vel_nivel D14h, D15h, D16h, D17h, D18h   (~16h de trânsito)
Convenção vel_nivel D-Xh = n(t) - n(t-Xh)  (mesma do robô do Santa Tereza).
A ordem/definição é validada contra o próprio .mat com `--validar`
(reproduz DADOS/Tctot1 com RMSE ~0) antes de confiar no ao vivo.
"""
import sys, os, json, datetime as dt, urllib.request, xml.etree.ElementTree as ET
import numpy as np
from scipy.io import loadmat

BRT = dt.timezone(dt.timedelta(hours=-3))
def agora_brt(): return dt.datetime.now(BRT).replace(tzinfo=None)

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# ---- config ----
MODELO_MAT = os.path.join(RAIZ, "assets", "mat", "MUC_H2_ALT_STC002_R2M001.mat")
INPUTS_JSON = os.path.join(RAIZ, "assets", "data", "mucum_modelo_inputs.json")
HORIZONTE = "2h"
COMBO = "STC002_R2M001"
BANKFULL_CM = 500            # nível normal / zero da mancha (régua 86510000)
ALVO = "86510000"
SAIDA = os.path.join(RAIZ, "previsao_ao_vivo_mucum.json")
ANA = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ULTIMA_RAW = {}

def carregar_receita():
    """Lê a receita dos inputs do modelo campeão 2h do mucum_modelo_inputs.json.
       Retorna a lista de inputs ordenada e o conjunto de estações usadas."""
    d = json.load(open(INPUTS_JSON, encoding="utf-8"))
    ins = sorted(d["modelo_campeao_2h"]["inputs"], key=lambda x: x["ordem"])
    estacoes = sorted({str(i["estacao"]) for i in ins})
    return ins, estacoes

RECEITA, ESTACOES = carregar_receita()

# --------- telemetria ANA (idêntica ao robô do Santa Tereza) ----------
def _local(tag): return tag.rsplit("}", 1)[-1]
def _parse_hora(dh):
    dh = dh.strip()
    try: return dt.datetime.fromisoformat(dh.replace("T", " ")[:19])
    except Exception:
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
            try: return dt.datetime.strptime(dh[:19], fmt)
            except Exception: pass
    return None

def _extrair_serie(root):
    serie = {}; ultima_raw = None
    for row in root.iter():
        campos = {_local(ch.tag): (ch.text or "") for ch in row}
        dh = campos.get("DataHora") or campos.get("Data_Hora") or campos.get("DataHoraMedicao")
        niv = campos.get("Nivel")
        if niv in (None, ""): niv = campos.get("nivel") or campos.get("NivelSensor") or campos.get("Cota")
        if not dh or niv in (None, ""): continue
        t = _parse_hora(dh)
        if t is None: continue
        try: valor = float(str(niv).replace(",", "."))
        except Exception: continue
        if ultima_raw is None or t > ultima_raw[0]: ultima_raw = (t, valor)
        if t.minute == 0 and t.second == 0:
            serie[t.replace(minute=0, second=0, microsecond=0)] = valor
    return serie, ultima_raw

def _serie_de_xml(xml):
    root = ET.fromstring(xml); serie, ultima_raw = _extrair_serie(root)
    if not serie and (root.text or "").strip().startswith("<"):
        try: serie, ultima_raw = _extrair_serie(ET.fromstring(root.text))
        except Exception: pass
    return serie, len(xml), ultima_raw

def buscar_ana(cod, dias=5):
    fim = agora_brt(); ini = fim - dt.timedelta(days=dias)
    tentativas = [
        f"{ANA}?codEstacao={cod}&dataInicio={ini:%d/%m/%Y}&dataFim={fim:%d/%m/%Y}",
        f"{ANA}?codEstacao={cod}&dataInicio=&dataFim=",
    ]
    for url in tentativas:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "previne-robo/1.0"})
            xml = urllib.request.urlopen(req, timeout=60).read()
            serie, nbytes, ultima_raw = _serie_de_xml(xml)
            print(f"[ANA {cod}] bytes={nbytes} linhas={len(serie)}")
            if ultima_raw: ULTIMA_RAW[cod] = ultima_raw
            if serie: return serie
        except Exception as e:
            print(f"[ANA {cod}] erro: {e}")
    return {}

def nivel(serie, t): return serie.get(t)

# --------- inputs (dirigidos pela receita do .json, na ordem exata) ----------
def montar_inputs(series, t):
    """Monta os inputs na hora t, na ORDEM EXATA do modelo (campo `ordem`).
       Validado contra o .mat (`--validar`, RMSE 0):
         nivel      -> n(t)
         vel_nivel  -> n(t) - n(t - defasagem_h)   (variação acumulada em X h)
    """
    def n(cod, h=0):
        return nivel(series[str(cod)], t - dt.timedelta(hours=h))
    x = []
    for inp in RECEITA:
        cod, tipo, h = inp["estacao"], inp["tipo"], inp["defasagem_h"]
        if tipo == "nivel":
            x.append(n(cod, 0))
        elif tipo == "vel_nivel":
            a, b = n(cod, 0), n(cod, h)
            x.append(None if None in (a, b) else a - b)
        else:
            raise ValueError(f"tipo de input não suportado: {tipo}")
    nivel_alvo = nivel(series[ALVO], t)
    return x, nivel_alvo

# --------- forward pass (idêntico ao ST; genérico p/ n_inputs/n_neuronios) ----------
def prever(mat_path, x):
    m = loadmat(mat_path, squeeze_me=True)
    wh = np.atleast_2d(np.asarray(m["wh"], float))
    bh = np.asarray(m["bh"], float).ravel()
    ws = np.asarray(m["ws"], float).ravel()
    bs = float(np.atleast_1d(m["bs"])[0])
    ae = np.asarray(m["ae"], float).ravel()
    be = np.asarray(m["be"], float).ravel()
    au = float(np.atleast_1d(m["au"])[0])
    bu = float(np.atleast_1d(m["bu"])[0])
    logsig = lambda z: 1.0 / (1.0 + np.exp(-z))
    pn = (np.asarray(x, float) - be) / ae
    h = logsig(wh.dot(pn) + bh)
    yn = logsig(ws.dot(h) + bs)
    return float(yn * au + bu)   # variação prevista (cm)

def validar(mat_path):
    """Confere que a cadeia (input cru -> normalização -> MLP -> desnorm)
       reproduz as predições armazenadas no .mat (pred_target_tot). RMSE ~0.
       Também confere a normalização de entrada: (DADOS - be)/ae == ptot."""
    m = loadmat(mat_path, squeeze_me=True)
    n_in = np.asarray(m["wh"], float).shape[1]
    print("n_inputs:", n_in, "| n_neuronios:", np.asarray(m["wh"], float).shape[0])
    X = np.asarray(m["DADOS"], float)[:, :n_in]
    be = np.asarray(m["be"], float).ravel(); ae = np.asarray(m["ae"], float).ravel()
    if "ptot" in m:
        err = float(np.max(np.abs(((X - be) / ae).T - np.asarray(m["ptot"], float))))
        print(f"normalização (X-be)/ae == ptot: max|erro| = {err:.6f}  (esperado ~0)")
    pred = np.array([prever(mat_path, X[i]) for i in range(len(X))])
    if "pred_target_tot" in m:
        ref = np.asarray(m["pred_target_tot"], float).ravel()
        k = min(len(pred), len(ref)); rmse = float(np.sqrt(np.mean((pred[:k]-ref[:k])**2)))
        print(f"RMSE(forward vs pred_target_tot) = {rmse:.6f} cm  (esperado ~0)  n={k}")
        print("amostra pred:", [round(float(v),1) for v in pred[:5]],
              "| ref:", [round(float(v),1) for v in ref[:5]])

# --------- saída ----------
def escrever(nivel_atual, nivel_prev, t, status, aviso):
    consultado_em = agora_brt(); raw = ULTIMA_RAW.get(ALVO)
    idade = round((consultado_em - raw[0]).total_seconds()/60) if raw else None
    hora_alvo = (t + dt.timedelta(hours=2)).isoformat() if t else None
    out = {
        "modo": "ao_vivo",
        "gerado_em": (t.isoformat() if t else consultado_em.isoformat()),
        "hora_modelo": (t.isoformat() if t else None),
        "hora_alvo": hora_alvo,
        "consultado_em": consultado_em.isoformat(timespec="seconds"),
        "telemetria_ultima_em": (raw[0].isoformat() if raw else None),
        "telemetria_ultima_nivel_cm": (round(raw[1]) if raw else None),
        "idade_telemetria_min": idade,
        "status_dados": (None if idade is None else ("telemetria recente" if idade <= 120 else f"telemetria atrasada ({idade} min)")),
        "estacao": ALVO, "local": "Muçum",
        "horizonte": HORIZONTE, "horizonte_h": 2, "modelo": COMBO, "bankfull_cm": BANKFULL_CM,
        "nivel_atual_cm": (round(nivel_atual) if nivel_atual is not None else None),
        "nivel_rio_agora_cm": (round(nivel_atual) if nivel_atual is not None else None),
        "nivel_previsto_cm": (round(nivel_prev) if nivel_prev is not None else None),
        "status": status, "aviso": aviso,
    }
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("escrito", SAIDA, "->", out["nivel_atual_cm"], "->", out["nivel_previsto_cm"], status)

def main():
    aviso = "EXPERIMENTAL — não é alerta oficial. Camada espacial da previsão de RNA (2h) para Muçum."
    if not os.path.exists(MODELO_MAT):
        print("MODELO_MAT ausente:", MODELO_MAT); escrever(None, None, None, "modelo .mat ausente no repo", aviso); return
    series = {c: buscar_ana(c) for c in ESTACOES}
    horas = sorted(series[ALVO].keys())
    if not horas:
        escrever(None, None, None, "sem dado recente em Muçum", aviso); return
    # A montante (86472600) pode não ter leitura na última hora da Muçum; procura
    # a hora mais recente (até 12 h atrás) em que TODOS os inputs estão disponíveis.
    t_ultimo = horas[-1]
    muc_ultimo = nivel(series[ALVO], t_ultimo)
    melhor = None
    for t in [h for h in reversed(horas) if (t_ultimo - h) <= dt.timedelta(hours=12)]:
        x, muc0 = montar_inputs(series, t)
        if muc0 is not None and all(v is not None for v in x):
            melhor = (t, x, muc0); break
    if melhor is None:
        x, muc0 = montar_inputs(series, t_ultimo)
        faltando = sum(v is None for v in x)
        escrever(muc_ultimo, None, t_ultimo,
                 f"inputs incompletos ({faltando}/{len(x)} faltando) — sem previsão nesta hora", aviso); return
    t, x, muc0 = melhor
    try:
        delta = prever(MODELO_MAT, x)
        # nível atual = leitura mais recente da régua; previsto = nível na hora t + variação
        escrever(muc_ultimo, muc0 + delta, t, "ok", aviso)
    except Exception as e:
        escrever(muc_ultimo, None, t, f"falha no modelo: {e}", aviso)

if __name__ == "__main__":
    if "--validar" in sys.argv:
        validar(MODELO_MAT)
    else:
        main()
