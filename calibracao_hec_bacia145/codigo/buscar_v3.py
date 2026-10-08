"""Busca de parâmetros da estrutura v3 SÓ com eventos de calibração (catálogo ampliado, papéis congelados).

Rodada 0: amostragem em hipercubo latino, as mesmas amostras nas duas rotas (musk = Muskingum K, mc = Muskingum-Cunge).
Rodadas seguintes: estratégia evolutiva (mu, lambda) na rota que tiver o melhor J.
Uso: HEC_CATALOGO=catalogo_ampliado.json HEC_FORC=forcamento_v3 python buscar_v3.py [n_lhs] [rodadas] [lambda] [mu]
"""
import json
import math
import random
import sys
import time

import numpy as np
from scipy.stats import qmc

from comum import AQUI, EVENTOS, RUNS
import bacia_inteira as bi
import estrutura_v3 as e3
import hec

LOG = AQUI / "resultados_v3" / "busca_v3.jsonl"
CAL = sorted(e for e, v in EVENTOS.items() if v["papel"] == "calibracao")
SIMS_CAL = sorted({EVENTOS[e]["sim"] for e in CAL})


def to_unit(p):
    q = {**e3.NEUTRO, **p}
    return {k: (math.log(q[k] / a) / math.log(b / a)) if s == "log" else (q[k] - a) / (b - a)
            for k, (a, b, s) in e3.PARAMS.items()}


def from_unit(u):
    out = {}
    for k, (a, b, s) in e3.PARAMS.items():
        x = min(1.0, max(0.0, u[k]))
        out[k] = a * (b / a) ** x if s == "log" else a + x * (b - a)
    return out


def avaliar(cands, rota, paralelo=20, por_jvm=2):
    hec.NOS_EXTRA = sorted({c[1] for c in bi.CONTROLES.values()})
    jobs = [(RUNS / e3.cid3(p, rota) / s, s, e3.bacia_v3(p, s, rota)) for p in cands for s in SIMS_CAL]
    res = hec.rodar_lote(jobs, paralelo=paralelo, por_jvm=por_jvm)
    out = []
    for p in cands:
        mets, erros = [], []
        for s in SIMS_CAL:
            r = res[RUNS / e3.cid3(p, rota) / s]
            if isinstance(r, Exception):
                erros.append(f"{s}: {str(r)[:100]}")
            else:
                mets += bi.avaliar_sim(s, r)
        J_ev = {e: bi.J_evento(mets, e) for e in CAL}
        fin = [v for v in J_ev.values() if math.isfinite(v)]
        J = sum(fin) / len(fin) if fin and not erros else float("inf")
        reg = {"cid": e3.cid3(p, rota), "rota": rota, "p": p, "J": J, "J_ev": {k: (v if math.isfinite(v) else None) for k, v in J_ev.items()},
               "erros": erros, "n_ev": len(fin),
               "metricas": [{k: m[k] for k in ("evento", "controle", "nse", "vol", "erro_pico", "lag_h")} for m in mets if m["papel"] == "calibracao"]}
        out.append(reg)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as h:
        for r in out:
            h.write(json.dumps(r, default=str) + "\n")
    return out


def carregar():
    return [json.loads(x) for x in LOG.open(encoding="utf-8")] if LOG.exists() else []


def main(n_lhs=48, rodadas=5, lam=24, mu=6, semente=3):
    print(f"eventos de calibração: {len(CAL)}; janelas: {len(SIMS_CAL)}", flush=True)
    todos = carregar()
    feitos = {(r["cid"]) for r in todos}
    if not todos:
        amostras = qmc.LatinHypercube(d=len(e3.PARAMS), seed=semente).random(n_lhs)
        chaves = list(e3.PARAMS)
        cands = [from_unit(dict(zip(chaves, a))) for a in amostras]
        for rota in ("musk", "mc"):
            t0 = time.time()
            novos = avaliar(cands, rota)
            todos += novos
            js = sorted(r["J"] for r in novos)
            print(f"R0 {rota}: {time.time() - t0:.0f}s melhor J={js[0]:.2f} mediana top-6={np.median(js[:6]):.2f} "
                  f"mediana geral={np.median(js):.2f}", flush=True)
    rota = min(("musk", "mc"), key=lambda r: np.median(sorted(x["J"] for x in todos if x["rota"] == r)[:6]))
    print(f"rota escolhida para refinar: {rota}", flush=True)
    rnd = random.Random(semente)
    sig = 0.15
    for k in range(1, rodadas + 1):
        pool = sorted((x for x in todos if x["rota"] == rota), key=lambda x: x["J"])
        elite = pool[:mu]
        w = [math.log(mu + 0.5) - math.log(i + 1) for i in range(mu)]
        us = [to_unit(e["p"]) for e in elite]
        med = {c: sum(wi * u[c] for wi, u in zip(w, us)) / sum(w) for c in e3.PARAMS}
        filhos = [from_unit({c: med[c] + rnd.gauss(0, sig) for c in e3.PARAMS}) for _ in range(lam)]
        antes = pool[0]["J"]
        t0 = time.time()
        novos = avaliar(filhos, rota)
        todos += novos
        melhor = min(todos, key=lambda x: x["J"] if x["rota"] == rota else 1e9)
        if melhor["J"] >= antes:
            sig = max(0.04, sig * 0.8)
        print(f"R{k} {time.time() - t0:.0f}s melhor J={melhor['J']:.2f} sigma={sig:.3f} "
              + " ".join(f"{c}={v:.3g}" for c, v in melhor["p"].items()), flush=True)
    print("FIM_BUSCA_V3", flush=True)


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:]))
