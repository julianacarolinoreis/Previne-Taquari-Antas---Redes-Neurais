#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Robô AO VIVO — PREVINE / Muçum (estação-alvo 86510000)
Espelha o robô do Santa Tereza. Roda no GitHub Actions (a cada 15 min):
  1) busca a telemetria da ANA (Muçum + montante Santa Tereza + auxiliares)
  2) para CADA horizonte cujo .mat já está no repo, monta os inputs na ordem
     exata (dirigida por mucum_modelo_inputs.json) e roda a RNA
  3) escreve previsao_ao_vivo_mucum.json no schema do ST (horizontes{...},
     passos) — a página monta os botões de horizonte a partir daí.

MULTI-HORIZONTE E AUTOSSUFICIENTE: lê os modelos recomendados do JSON. Os
horizontes 4h/8h/12h aparecem sozinhos assim que o Dispatch commitar os .mat
correspondentes em assets/mat/ — sem tocar neste código.

vel_nivel D-Xh = n(t) - n(t-Xh). Cada .mat é validável com `--validar <mat>`
(reproduz pred_target_tot com RMSE ~0) antes de confiar no ao vivo.
EXPERIMENTAL — não é alerta oficial.
"""
import sys, os, json, datetime as dt, urllib.request, xml.etree.ElementTree as ET
import numpy as np
from scipy.io import loadmat

BRT = dt.timezone(dt.timedelta(hours=-3))
def agora_brt(): return dt.datetime.now(BRT).replace(tzinfo=None)

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INPUTS_JSON = os.path.join(RAIZ, "assets", "data", "mucum_modelo_inputs.json")
MAT_DIR = os.path.join(RAIZ, "assets", "mat")
SAIDA = os.path.join(RAIZ, "previsao_ao_vivo_mucum.json")
BANKFULL_CM = 500            # nível normal / zero da mancha (régua 86510000)
ALVO = "86510000"
LOCAL = "Muçum"
AVISO = "EXPERIMENTAL — não é alerta oficial. Camada espacial da previsão de RNA para Muçum."
ANA = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ULTIMA_RAW = {}


# ---------- configuração dos modelos (a partir do JSON) ----------
def _cfg(m, hh):
    ins = sorted(m["inputs"], key=lambda x: x["ordem"])
    mid = m["modelo_id"]
    mat = m.get("arquivo_mat") or f"assets/mat/{mid}.mat"
    return {
        "horizonte_h": hh, "horizonte": f"{hh}h", "rotulo": f"{hh}h",
        "tipo": m.get("tipo_modelo", "ALT"), "modelo": mid,
        "combo": m.get("combo_id", mid),
        "mat": os.path.join(RAIZ, mat) if mat.startswith("assets") else os.path.join(MAT_DIR, os.path.basename(mat)),
        "inputs": ins,
        "estacoes": sorted({str(i["estacao"]) for i in ins}),
        "n_inputs": len(ins),
    }

def carregar_modelos():
    """2h campeão + um modelo por horizonte (4h/8h/12h) do JSON."""
    d = json.load(open(INPUTS_JSON, encoding="utf-8"))
    modelos = [_cfg(d["modelo_campeao_2h"], 2)]
    vistos = {2}
    for m in d.get("modelos_recomendados_outros_horizontes", []):
        hh = int(m["horizonte_h"])
        if hh in vistos:          # um por horizonte (prefere o 1º da lista)
            continue
        vistos.add(hh)
        modelos.append(_cfg(m, hh))
    return modelos


# ---------- telemetria ANA (idêntica ao robô do Santa Tereza) ----------
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

def buscar_ana(cod, dias=6, tentativas_rede=3):
    """Telemetria da ANA. O endpoint às vezes devolve vazio/erro de forma
    transitória, então tenta algumas vezes com backoff curto antes de desistir."""
    import time
    fim = agora_brt(); ini = fim - dt.timedelta(days=dias)
    urls = [
        f"{ANA}?codEstacao={cod}&dataInicio={ini:%d/%m/%Y}&dataFim={fim:%d/%m/%Y}",
        f"{ANA}?codEstacao={cod}&dataInicio=&dataFim=",
    ]
    for attempt in range(tentativas_rede):
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "previne-robo/1.0"})
                xml = urllib.request.urlopen(req, timeout=60).read()
                serie, nbytes, ultima_raw = _serie_de_xml(xml)
                print(f"[ANA {cod}] tent={attempt+1} bytes={nbytes} linhas={len(serie)}")
                if ultima_raw: ULTIMA_RAW[cod] = ultima_raw
                if serie: return serie
            except Exception as e:
                print(f"[ANA {cod}] tent={attempt+1} erro: {e}")
        if attempt < tentativas_rede - 1:
            time.sleep(4 * (attempt + 1))
    return {}

def nivel(serie, t): return serie.get(t)


# ---------- inputs / inferência ----------
def montar_inputs(cfg, series, t):
    """Monta os inputs de um modelo na hora t, na ordem exata (campo `ordem`).
       nivel -> n(t) ; vel_nivel -> n(t) - n(t - defasagem_h)."""
    def n(cod, h=0):
        s = series.get(str(cod))
        return None if s is None else nivel(s, t - dt.timedelta(hours=h))
    x = []
    for inp in cfg["inputs"]:
        cod, tipo, h = inp["estacao"], inp["tipo"], inp["defasagem_h"]
        if tipo == "nivel":
            x.append(n(cod, 0))
        elif tipo == "vel_nivel":
            a, b = n(cod, 0), n(cod, h)
            x.append(None if None in (a, b) else a - b)
        else:
            raise ValueError(f"tipo de input não suportado: {tipo}")
    return x

def prever(mat_path, x):
    m = loadmat(mat_path, squeeze_me=True)
    wh = np.atleast_2d(np.asarray(m["wh"], float)); bh = np.asarray(m["bh"], float).ravel()
    ws = np.asarray(m["ws"], float).ravel(); bs = float(np.atleast_1d(m["bs"])[0])
    ae = np.asarray(m["ae"], float).ravel(); be = np.asarray(m["be"], float).ravel()
    au = float(np.atleast_1d(m["au"])[0]); bu = float(np.atleast_1d(m["bu"])[0])
    logsig = lambda z: 1.0 / (1.0 + np.exp(-z))
    pn = (np.asarray(x, float) - be) / ae
    h = logsig(wh.dot(pn) + bh)
    yn = logsig(ws.dot(h) + bs)
    return float(yn * au + bu)   # variação prevista (cm)

def melhor_hora(cfg, series, horas):
    """Hora mais recente (até 12 h atrás) em que TODOS os inputs do modelo existem."""
    if not horas: return None
    t_ult = horas[-1]
    for t in [h for h in reversed(horas) if (t_ult - h) <= dt.timedelta(hours=12)]:
        x = montar_inputs(cfg, series, t)
        if all(v is not None for v in x):
            return t, x
    return None


# ---------- saída (schema do Santa Tereza) ----------
def base_saida(cfg, nivel_agora, nivel_prev, t, status, faltantes=None):
    consultado = agora_brt(); raw = ULTIMA_RAW.get(ALVO)
    idade = round((consultado - raw[0]).total_seconds() / 60) if raw else None
    hora_alvo = (t + dt.timedelta(hours=cfg["horizonte_h"])).isoformat() if t else None
    out = {
        "modo": "ao_vivo",
        "gerado_em": (t.isoformat() if t else consultado.isoformat()),
        "hora_modelo": (t.isoformat() if t else None),
        "hora_alvo": hora_alvo,
        "consultado_em": consultado.isoformat(timespec="seconds"),
        "telemetria_ultima_em": (raw[0].isoformat() if raw else None),
        "telemetria_ultima_nivel_cm": (round(raw[1]) if raw else None),
        "idade_telemetria_min": idade,
        "status_dados": (None if idade is None else ("telemetria recente" if idade <= 120 else f"telemetria atrasada ({idade} min)")),
        "estacao": ALVO, "local": LOCAL,
        "horizonte": cfg["horizonte"], "rotulo": cfg["rotulo"], "horizonte_h": cfg["horizonte_h"],
        "tipo": cfg["tipo"], "modelo": cfg["modelo"], "combo": cfg["combo"], "bankfull_cm": BANKFULL_CM,
        "nivel_modelo_cm": (round(nivel_agora) if nivel_agora is not None else None),
        "nivel_rio_agora_cm": (round(nivel_agora) if nivel_agora is not None else None),
        "nivel_atual_cm": (round(nivel_agora) if nivel_agora is not None else None),
        "nivel_previsto_cm": (round(nivel_prev) if nivel_prev is not None else None),
        "inputs_total": cfg["n_inputs"], "inputs_faltantes_n": len(faltantes or []),
        "inputs_faltantes": faltantes or [], "estacoes_status": [],
        "status": status, "aviso": AVISO,
    }
    if nivel_prev is not None and nivel_agora is not None:
        out["delta_previsto_cm"] = round(nivel_prev - nivel_agora, 1)
        out["passos"] = [[out["hora_modelo"], out["nivel_rio_agora_cm"], out["nivel_previsto_cm"]]]
    return out


def _tem_previsao(d):
    return bool(d) and d.get("nivel_previsto_cm") is not None

def escrever(top, horizontes, max_stale_h=6):
    top = dict(top)
    if horizontes:
        top["horizontes"] = horizontes
    # Resiliência: se este ciclo NÃO tem previsão (telemetria da ANA falhou),
    # preserva a última previsão boa (se ainda recente) em vez de apagá-la —
    # assim a página não "cai" para o replay num hiccup transitório da ANA.
    if not _tem_previsao(top) and os.path.exists(SAIDA):
        try:
            ant = json.load(open(SAIDA, encoding="utf-8"))
            hm = ant.get("hora_modelo")
            if _tem_previsao(ant) and hm:
                idade_h = (agora_brt() - dt.datetime.fromisoformat(hm)).total_seconds() / 3600
                if idade_h <= max_stale_h:
                    print(f"telemetria falhou neste ciclo; mantendo última previsão boa ({idade_h:.1f} h) — não sobrescreve")
                    return
        except Exception as e:
            print("não consegui ler JSON anterior:", e)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(top, f, ensure_ascii=False, indent=1)
    hs = ",".join(horizontes.keys()) if horizontes else "-"
    print("escrito", SAIDA, "->", top.get("nivel_atual_cm"), "->", top.get("nivel_previsto_cm"),
          "| horizontes:", hs, "|", top.get("status"))


def main():
    modelos = carregar_modelos()
    disponiveis = [c for c in modelos if os.path.exists(c["mat"])]
    print("modelos:", [(c["horizonte"], os.path.basename(c["mat"]), "OK" if os.path.exists(c["mat"]) else "sem .mat") for c in modelos])
    if not disponiveis:
        escrever(base_saida(modelos[0], None, None, None, "nenhum .mat disponível no repo"), {}); return

    estacoes = sorted({e for c in disponiveis for e in c["estacoes"]})
    series = {e: buscar_ana(e) for e in estacoes}
    horas_muc = sorted(series.get(ALVO, {}).keys())
    nivel_agora = nivel(series.get(ALVO, {}), horas_muc[-1]) if horas_muc else None
    if not horas_muc:
        # tenta o 2h só para registrar o estado
        escrever(base_saida(disponiveis[0], nivel_agora, None, None, "sem dado recente em Muçum"), {}); return

    horizontes = {}
    for cfg in disponiveis:
        mh = melhor_hora(cfg, series, horas_muc)
        if mh is None:
            x = montar_inputs(cfg, series, horas_muc[-1])
            falt = sum(v is None for v in x)
            horizontes[cfg["horizonte"]] = base_saida(
                cfg, nivel_agora, None, horas_muc[-1],
                f"inputs incompletos ({falt}/{cfg['n_inputs']} faltando) — sem previsão nesta hora")
            continue
        t, x = mh
        try:
            delta = prever(cfg["mat"], x)
            nivel_base = nivel(series[ALVO], t)     # nível na hora-base do modelo
            horizontes[cfg["horizonte"]] = base_saida(cfg, nivel_agora, nivel_base + delta, t, "ok")
        except Exception as e:
            horizontes[cfg["horizonte"]] = base_saida(cfg, nivel_agora, None, t, f"falha no modelo: {e}")

    # topo = 2h (ou o primeiro horizonte disponível)
    principal = horizontes.get("2h") or next(iter(horizontes.values()))
    escrever(principal, horizontes)


def validar(mat_path):
    m = loadmat(mat_path, squeeze_me=True)
    n_in = np.asarray(m["wh"], float).shape[1]
    print("n_inputs:", n_in, "| n_neuronios:", np.asarray(m["wh"], float).shape[0])
    X = np.asarray(m["DADOS"], float)[:, :n_in]
    be = np.asarray(m["be"], float).ravel(); ae = np.asarray(m["ae"], float).ravel()
    if "ptot" in m:
        err = float(np.max(np.abs(((X - be) / ae).T - np.asarray(m["ptot"], float))))
        print(f"(X-be)/ae == ptot: max|erro| = {err:.6f}  (esperado ~0)")
    pred = np.array([prever(mat_path, X[i]) for i in range(len(X))])
    if "pred_target_tot" in m:
        ref = np.asarray(m["pred_target_tot"], float).ravel()
        k = min(len(pred), len(ref)); rmse = float(np.sqrt(np.mean((pred[:k] - ref[:k]) ** 2)))
        print(f"RMSE(forward vs pred_target_tot) = {rmse:.6f} cm (esperado ~0) n={k}")


if __name__ == "__main__":
    if "--validar" in sys.argv:
        args = [a for a in sys.argv[1:] if a != "--validar"]
        alvo = args[0] if args else os.path.join(MAT_DIR, "MUC_H2_ALT_STC002_R2M001.mat")
        validar(alvo if os.path.isabs(alvo) else os.path.join(MAT_DIR, os.path.basename(alvo)))
    else:
        main()
