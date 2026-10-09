"""Monta o PEDIDO.json das rodadas das famílias novas da estrutura v3 para o lote na nuvem (--familia, padrão dc):
  dc   Deficit and Constant + base Recession          (estrutura_v3.PARAMS_DC)
  lric Initial+Constant    + base em reservatório linear (PARAMS_LRIC)
  lrdc Deficit and Constant + base em reservatório linear (PARAMS_LRDC)

Mesmas janelas e papéis das famílias g1/g2/g4/g6 (todos os eventos de calibração), para o J ser comparável com
lib-A (Initial+Constant) e scs-A (SCS).
Uso:
  python rodada_dc.py lhs  --familia lric,lrdc --rodada lr-g0 --n 32 --semente 11 --saida ../rodadas/PEDIDO.json
  (várias famílias num pedido só: os candidatos vêm em sequência e "familias" no pedido diz a faixa de cada uma)
  python rodada_dc.py es   --rodada dc-g1 --resultados pasta [pasta ...] --lam 24 --mu 6 --sigma 0.15 --saida ...
  python rodada_dc.py top  --rodada dc-av --resultados pasta [pasta ...] --n 3 --janelas todas --saida ...
  python rodada_dc.py teste --rodada dc-teste --semente 1 --saida ...   (2 candidatos x 2 janelas: confere a sintaxe)
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

import numpy as np
from scipy.stats import qmc

import estrutura_v3 as e3

JANELAS_CAL = ("S2023_07,S2023_09,S2023_11,S2024_05,S2024_06,X20180721,X20180821,X20180828,X20180928,X20181028,"
               "X20190525,X20191027,X20200626,X20200809,X20210125,X20210525,X20210622")
PAPEIS = {"E18": "validacao", "E22": "validacao"}
P = e3.PARAMS_DC   # trocado em main() conforme --familia


def to_unit(p):
    return {k: (math.log(p[k] / a) / math.log(b / a)) if s == "log" else (p[k] - a) / (b - a)
            for k, (a, b, s) in P.items()}


def from_unit(u):
    out = {}
    for k, (a, b, s) in P.items():
        x = min(1.0, max(0.0, u[k]))
        out[k] = a * (b / a) ** x if s == "log" else a + x * (b - a)
    return out


def ler_resultados(pastas):
    vistos, out = set(), []
    for pasta in pastas:
        for f in Path(pasta).rglob("resultado.json"):
            for c in json.loads(f.read_text(encoding="utf-8")):
                if c["id"] in vistos or set(c["p"]) != set(P):
                    continue
                vistos.add(c["id"])
                out.append(c)
    return [c for c in out if c["J"] is not None and math.isfinite(c["J"])]


def pedido(rodada, cands, janelas=JANELAS_CAL, **extra):
    return {"rodada": rodada, "janelas": janelas, "shards": 20, "papeis": PAPEIS,
            "candidatos": [{"id": f"{rodada}-c{i:03d}", "rota": "mc", "p": p} for i, p in enumerate(cands)], **extra}


def gerar(a, fam, semente):
    """Candidatos de uma família; devolve (lista de parâmetros, informação para o pedido)."""
    global P
    P = e3.FAMILIAS[fam]
    chaves = list(P)
    if a.modo in ("lhs", "teste"):
        n = 2 if a.modo == "teste" else a.n
        amostras = qmc.LatinHypercube(d=len(chaves), seed=semente).random(n)
        return [from_unit(dict(zip(chaves, x))) for x in amostras], {}
    todos = sorted(ler_resultados(a.resultados), key=lambda c: c["J"])
    if not todos:
        sys.exit(f"{fam}: nenhum resultado com J finito nas pastas indicadas")
    if a.modo == "top":
        return [c["p"] for c in todos[:a.n]], {"origem": [{"id": c["id"], "J": c["J"]} for c in todos[:a.n]]}
    elite = todos[:a.mu]
    w = [math.log(a.mu + 0.5) - math.log(i + 1) for i in range(len(elite))]
    us = [to_unit(c["p"]) for c in elite]
    med = {k: sum(wi * u[k] for wi, u in zip(w, us)) / sum(w) for k in chaves}
    rnd = random.Random(semente)
    filhos = [from_unit({k: med[k] + rnd.gauss(0, a.sigma) for k in chaves}) for _ in range(a.lam)]
    return filhos, {"melhor_ate_aqui": {"id": elite[0]["id"], "J": elite[0]["J"]}, "sigma": a.sigma,
                    "n_avaliados": len(todos)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=("lhs", "es", "top", "teste"))
    ap.add_argument("--familia", default="dc", help="uma ou mais de " + ",".join(e3.FAMILIAS) + ", separadas por vírgula")
    ap.add_argument("--rodada", required=True)
    ap.add_argument("--n", type=int, default=32)
    ap.add_argument("--semente", type=int, default=7)
    ap.add_argument("--resultados", nargs="*", default=[])
    ap.add_argument("--lam", type=int, default=24)
    ap.add_argument("--mu", type=int, default=6)
    ap.add_argument("--sigma", type=float, default=0.15)
    ap.add_argument("--janelas", default=JANELAS_CAL)
    ap.add_argument("--saida", default="")
    a = ap.parse_args()
    janelas = "S2023_09,S2023_11" if a.modo == "teste" else a.janelas
    cands, extra = [], {"familias": {}}
    for i, fam in enumerate(a.familia.split(",")):
        c, x = gerar(a, fam, a.semente + i)
        extra["familias"][fam] = {"de": len(cands), "ate": len(cands) + len(c) - 1, **x}
        cands += c
    out = pedido(a.rodada, cands, janelas, **extra)
    txt = json.dumps(out, indent=1, default=float)
    if a.saida:
        Path(a.saida).write_text(txt, encoding="utf-8")
        print(f"{a.saida}: {len(out['candidatos'])} candidatos, janelas={out['janelas'][:60]}")
    else:
        print(txt)


if __name__ == "__main__":
    main()
