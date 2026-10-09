"""Termo de vazão de base nas janelas longas e contínuas (base-contínua, 09/10/2026).

As janelas de evento começam no q0 observado, então o J de eventos não vê a base que o modelo sustenta por conta
própria: numa rodada contínua o c008/c002 chegam ao fim das recessões com ~0,3 do observado. As janelas longas
(catálogo, campo "longa" = papel) rodam meses seguidos; descartados os AQUEC_DIAS iniciais, por controle:
  recessões = trechos de >= MIN_SEG dias em que a média diária OBSERVADA não sobe (tolerância TOL), sem os
              DESCARTA primeiros dias (escoamento rápido);
  termos (cada um vale 1 no limite, como em metricas.penalidade):
    vol  |ln(soma sim / soma obs)| nos dias de recessão          / ln 1,2
    dia  média de |ln(sim/obs)| diário nos dias de recessão       / ln 1,3
    fim  média, por recessão, de |ln(sim/obs)| nos 2 últimos dias / ln 1,2   (base no fim de cada recessão)
  pen = média dos três termos, limitada a PEN_MAX.
Médias diárias também apagam a oscilação diária das UHEs (Muçum).
J_base = média de pen nos controles do objetivo e nas janelas longas do papel pedido."""
import math
import statistics
from datetime import timedelta

import bacia_inteira as bi
from comum import SIMULACOES

AQUEC_DIAS = 20
MIN_SEG, DESCARTA, TOL = 6, 2, 1.02
LIM = {"vol": math.log(1.2), "dia": math.log(1.3), "fim": math.log(1.2)}
PEN_MAX = 20.0


def longas(papel=None):
    return [s for s, v in SIMULACOES.items() if v.get("longa") and (papel is None or v["longa"] == papel)]


def diarias(serie, ini, fim, min_horas):
    """Média diária com pelo menos min_horas horas distintas com dado."""
    soma, horas = {}, {}
    for t, q in serie.items():
        if ini <= t < fim:
            d = t.date()
            soma.setdefault(d, []).append(q)
            horas.setdefault(d, set()).add(t.hour)
    return {d: sum(v) / len(v) for d, v in soma.items() if len(horas[d]) >= min_horas}


def recessoes(od):
    dias = sorted(od)
    segs, atual = [], []
    for a, b in zip(dias, dias[1:]):
        if (b - a).days == 1 and od[b] <= TOL * od[a]:
            atual = atual or [a]
            atual.append(b)
        else:
            if len(atual) >= MIN_SEG:
                segs.append(atual)
            atual = []
    if len(atual) >= MIN_SEG:
        segs.append(atual)
    return [s[DESCARTA:] for s in segs]


def avaliar_longa(sim, simq):
    cfg = SIMULACOES[sim]
    ini, fim = cfg["ini"] + timedelta(days=AQUEC_DIAS), cfg["fim"]
    out = []
    for nome, (cod, node, _lim, no_obj) in bi.CONTROLES.items():
        od = {d: q for d, q in diarias(bi.obs_limpo(sim, cod), ini, fim, 18).items() if q > 0}
        sd = diarias(simq.get(node, {}), ini, fim, 20)
        if len(od) < 30 or not sd:
            continue
        segs = [[d for d in s if d in sd and sd[d] > 0] for s in recessoes(od)]
        segs = [s for s in segs if len(s) >= 2]
        dias = [d for s in segs for d in s]
        if len(dias) < 10:
            continue
        r_vol = sum(sd[d] for d in dias) / sum(od[d] for d in dias)
        e_dia = sum(abs(math.log(sd[d] / od[d])) for d in dias) / len(dias)
        r_fim = [sum(sd[d] for d in s[-2:]) / sum(od[d] for d in s[-2:]) for s in segs]
        e_fim = sum(abs(math.log(r)) for r in r_fim) / len(r_fim)
        comum = [d for d in od if d in sd]
        pen = (abs(math.log(r_vol)) / LIM["vol"] + e_dia / LIM["dia"] + e_fim / LIM["fim"]) / 3
        out.append(dict(janela=sim, papel=cfg["longa"], controle=nome, objetivo=no_obj, n_rec=len(segs),
                        dias_rec=len(dias), razao_vol_rec=r_vol, erro_log_dia=e_dia,
                        razao_fim_mediana=statistics.median(r_fim), razao_fim=[round(r, 3) for r in r_fim],
                        razao_media_janela=sum(sd[d] for d in comum) / sum(od[d] for d in comum),
                        pen=min(pen, PEN_MAX)))
    return out


def J_base(mets, papel="calibracao"):
    ms = [m for m in mets if m["papel"] == papel and m["objetivo"]]
    return sum(m["pen"] for m in ms) / len(ms) if ms else float("inf")
