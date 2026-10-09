"""Métricas por evento/controle comparando vazão instantânea observada (HH:00) com a simulada.

Critérios de aceite (definidos antes de calibrar):
  NSE >= 0,70 ; |erro de pico| <= 15% ; |defasagem do pico| <= 3 h ; |viés de volume| <= 10%
"""
import math
from datetime import timedelta

from comum import CONTROLES, EVENTOS, MUCUM, SIMULACOES
from hec import nivel, observado

ALVO = dict(nse=0.70, pico=0.15, lag=3.0, vol=0.10)
# Controles que não valem para pico (estação parou / sem dado no pico)
SEM_PICO = {("E5", "MUCUM"), ("E18", "LJJ")}
# Muçum: curva-chave sem suporte acima de ~18–20 m (SGB 2014 vai só até 20 m; balanço LJJ×Muçum
# indica subestimativa da curva da telemetria acima de ~18 m). Vazão de Muçum só é usada nas horas
# com nível <= LIMITE_CURVA_CM; o horário do pico vem do NÍVEL (independe da curva).
LIMITE_CURVA_CM = 1800


def horas(ini, fim):
    t = ini
    while t <= fim:
        yield t
        t += timedelta(hours=1)


def avaliar(evento: str, controle: str, sim_series: dict) -> dict | None:
    ev = EVENTOS[evento]
    node, cod = CONTROLES[controle]
    obs = observado(ev["sim"], cod)
    simq = sim_series.get(node, {})
    hs = list(horas(ev["ini"], ev["fim"]))
    if controle == "MUCUM":
        return avaliar_mucum(evento, ev, obs, simq, hs)
    pares = [(t, obs[t], simq[t]) for t in hs if t in obs and t in simq]
    if len(pares) < 0.3 * len(hs) or len(pares) < 12:
        return None
    o = [p[1] for p in pares]
    s = [p[2] for p in pares]
    mo = sum(o) / len(o)
    sst = sum((x - mo) ** 2 for x in o)
    nse = 1 - sum((a - b) ** 2 for a, b in zip(s, o)) / sst if sst > 0 else None
    vol = sum(s) / sum(o) - 1
    out = dict(evento=evento, controle=controle, papel=ev["papel"], pares=len(pares), horas=len(hs),
               nse=nse, vol=vol, rmse=math.sqrt(sum((a - b) ** 2 for a, b in zip(s, o)) / len(o)))
    # Pico: só se o observado está completo em torno do máximo (±6 h) e não está na borda
    tpo, qpo = max(pares, key=lambda p: p[1])[0], max(o)
    viz = [tpo + timedelta(hours=k) for k in range(-6, 7)]
    completo = all(t in obs for t in viz) and (evento, controle) not in SEM_PICO
    completo = completo and ev["ini"] < tpo < ev["fim"]
    # pico simulado: máximo na janela do evento (série simulada completa)
    sim_ev = {t: simq[t] for t in hs if t in simq}
    tps, qps = max(sim_ev.items(), key=lambda kv: kv[1])
    out.update(pico_obs=qpo, t_pico_obs=str(tpo), pico_sim=qps, t_pico_sim=str(tps), pico_completo=completo,
               erro_pico=(qps / qpo - 1) if completo else None,
               lag_h=((tps - tpo).total_seconds() / 3600) if completo else None)
    out["passa"] = passa(out)
    return out


def avaliar_mucum(evento, ev, obs, simq, hs):
    niv = nivel(ev["sim"], MUCUM)
    pares = [(t, obs[t], simq[t]) for t in hs if t in obs and t in simq and niv.get(t, 1e9) <= LIMITE_CURVA_CM]
    hs_niv = [t for t in hs if t in niv]
    if len(hs_niv) < 0.3 * len(hs) or len(pares) < 12:
        return None
    o = [p[1] for p in pares]
    s = [p[2] for p in pares]
    mo = sum(o) / len(o)
    sst = sum((x - mo) ** 2 for x in o)
    nse = 1 - sum((a - b) ** 2 for a, b in zip(s, o)) / sst if sst > 0 else None
    vol = sum(s) / sum(o) - 1
    out = dict(evento=evento, controle="MUCUM", papel=ev["papel"], pares=len(pares), horas=len(hs),
               nse=nse, vol=vol, rmse=math.sqrt(sum((a - b) ** 2 for a, b in zip(s, o)) / len(o)))
    # horário do pico pelo nível
    tpo = max(hs_niv, key=lambda t: niv[t])
    nmax = niv[tpo]
    viz = [tpo + timedelta(hours=k) for k in range(-6, 7)]
    completo = all(t in niv for t in viz) and ("MUCUM" not in ev.get("sem_pico", set())) and ev["ini"] < tpo < ev["fim"]
    sim_ev = {t: simq[t] for t in hs if t in simq}
    tps, qps = max(sim_ev.items(), key=lambda kv: kv[1])
    magnitude_ok = completo and nmax <= LIMITE_CURVA_CM and tpo in obs
    out.update(pico_obs=obs.get(tpo), nivel_pico_cm=nmax, t_pico_obs=str(tpo), pico_sim=qps, t_pico_sim=str(tps),
               pico_completo=magnitude_ok, tempo_completo=completo,
               erro_pico=(qps / obs[tpo] - 1) if magnitude_ok else None,
               lag_h=((tps - tpo).total_seconds() / 3600) if completo else None)
    out["passa"] = passa(out)
    return out


def passa(m):
    ok = m["nse"] is not None and m["nse"] >= ALVO["nse"] and abs(m["vol"]) <= ALVO["vol"]
    if m["pico_completo"]:
        ok = ok and abs(m["erro_pico"]) <= ALVO["pico"]
    if m["lag_h"] is not None:
        ok = ok and abs(m["lag_h"]) <= ALVO["lag"]
    return ok


def penalidade(m):
    """Cada termo vale 1 exatamente no limite do critério."""
    j = (1 - (m["nse"] if m["nse"] is not None else -1)) / (1 - ALVO["nse"]) + abs(m["vol"]) / ALVO["vol"]
    if m["pico_completo"]:
        j += abs(m["erro_pico"]) / ALVO["pico"]
    if m["lag_h"] is not None:
        j += abs(m["lag_h"]) / ALVO["lag"]
    return j


def pesos_por_pico(mets, eventos, expoente=1.0):
    """Opção (09/10): peso de cada evento pelo tamanho da cheia OBSERVADA, para um J com mais peso nas cheias grandes.
    Para cada controle, pico_obs / mediana do pico_obs do controle nos eventos dados (só picos com magnitude válida,
    erro_pico definido); o tamanho do evento é a média dessas razões, elevada ao expoente; normalizado para média 1.
    Evento sem pico válido fica com peso 1. Só usa observados: o peso é o mesmo para qualquer candidato."""
    por_ctrl = {}
    for m in mets:
        if m["evento"] in eventos and m.get("pico_obs") and m.get("erro_pico") is not None:
            por_ctrl.setdefault(m["controle"], {})[m["evento"]] = float(m["pico_obs"])
    med = {c: sorted(v.values())[len(v) // 2] for c, v in por_ctrl.items()}
    tam = {}
    for e in eventos:
        r = [v[e] / med[c] for c, v in por_ctrl.items() if e in v]
        tam[e] = (sum(r) / len(r)) ** expoente if r else None
    ok = [t for t in tam.values() if t is not None]
    media = sum(ok) / len(ok) if ok else 1.0
    return {e: (t / media if t is not None else 1.0) for e, t in tam.items()}


def J_ponderado(J_ev, pesos):
    """Média dos J_evento finitos ponderada por pesos (pesos_por_pico). Não substitui o J padrão (média simples)."""
    par = [(pesos.get(e, 1.0), j) for e, j in J_ev.items() if j is not None and math.isfinite(j)]
    return sum(w * j for w, j in par) / sum(w for w, _ in par) if par else float("inf")


def eventos_da_sim(sim):
    return [e for e, v in EVENTOS.items() if v["sim"] == sim]


def avaliar_sim(sim, series):
    out = []
    for e in eventos_da_sim(sim):
        for c in CONTROLES:
            m = avaliar(e, c, series)
            if m:
                out.append(m)
    return out
