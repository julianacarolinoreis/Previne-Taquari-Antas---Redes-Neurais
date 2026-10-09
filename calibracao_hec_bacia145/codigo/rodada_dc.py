"""Monta o PEDIDO.json das rodadas das famílias novas da estrutura v3 para o lote na nuvem (--familia, padrão dc):
  dc    Deficit and Constant + base Recession          (estrutura_v3.PARAMS_DC)
  lric  Initial+Constant    + base em reservatório linear (PARAMS_LRIC)
  lrdc  Deficit and Constant + base em reservatório linear (PARAMS_LRDC)
  lrdcv lrdc + Clark variável (Tc e R pela intensidade do excesso; PARAMS_LRDCV)
  lrdc8 lrdc + n das encostas da seção de 8 pontos (nob; usar com --rota mc8 ou mc8st)
  lrdcv8 lrdcv + nob (Clark variável e seções de 8 pontos juntos)
  lrdcr lrdc + multiplicadores regionais de dmax, perc e fb (grupos T = Tainhas e B = Carreiro/Guaporé/baixo; PARAMS_LRDCR)

Mesmas janelas e papéis das famílias g1/g2/g4/g6 (todos os eventos de calibração), para o J ser comparável com
lib-A (Initial+Constant) e scs-A (SCS).
Uso:
  python rodada_dc.py lhs  --familia lric,lrdc --rodada lr-g0 --n 32 --semente 11 --saida ../rodadas/PEDIDO.json
  (várias famílias num pedido só: os candidatos vêm em sequência e "familias" no pedido diz a faixa de cada uma)
  python rodada_dc.py viz  --familia lrdcv --rodada md-v0 --centro res.json:lr-g8-c038 --raio 0.15 --n 48 --saida ...
  (LHS na vizinhança de um candidato: ±raio no espaço unitário dos parâmetros que ele tem; os parâmetros novos da
   família varrem a faixa toda; o candidato 0 é o próprio centro, com os parâmetros novos neutros)
  python rodada_dc.py es   --rodada dc-g1 --resultados pasta [pasta ...] --lam 24 --mu 6 --sigma 0.15 --saida ...
  python rodada_dc.py top  --rodada dc-av --resultados pasta [pasta ...] --n 3 --janelas todas --saida ...
  python rodada_dc.py teste --rodada dc-teste --semente 1 --saida ...   (2 candidatos x 2 janelas: confere a sintaxe)
--rota mc|mc8st|mc8 (calha trapezoidal ou seções de 8 pontos); es/top só leem resultados da mesma rota.
--objetivo J|J_pico: chave de ordenação de es/top (J_pico = J ponderado pelo tamanho da cheia observada; o J padrão
continua no resultado para comparar).
--eventos E4,E5,...: o objetivo passa a ser a média de J_ev só nesses eventos de calibração (parâmetros por porte de
cheia); candidato sem J_ev finito em algum deles fica fora.
--livres k1,k2,...: só esses parâmetros variam (viz e es); os outros ficam no valor do centro (viz) ou do melhor (es).
--forcamento forcamento_v3b: pasta de chuva do lote (campo "forcamento" do PEDIDO).
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
NEUTROS = {"ie": 5.0, "atc": 0.0, "ar": 0.0, "nob": 1.0, **{k: 1.0 for k in e3.PARAMS_LRDCR if k.startswith("x")}}


def to_unit(p):
    return {k: (math.log(p[k] / a) / math.log(b / a)) if s == "log" else (p[k] - a) / (b - a)
            for k, (a, b, s) in P.items()}


def from_unit(u):
    out = {}
    for k, (a, b, s) in P.items():
        x = min(1.0, max(0.0, u[k]))
        out[k] = a * (b / a) ** x if s == "log" else a + x * (b - a)
    return out


def j_eventos(c, eventos):
    v = [c.get("J_ev", {}).get(e) for e in eventos]
    return sum(v) / len(v) if v and all(x is not None and math.isfinite(x) for x in v) else None


def ler_resultados(pastas, rota="mc", objetivo="J", eventos=None):
    vistos, out = set(), []
    for pasta in pastas:
        for f in Path(pasta).rglob("resultado.json"):
            for c in json.loads(f.read_text(encoding="utf-8")):
                if c["id"] in vistos or set(c["p"]) != set(P) or c.get("rota", "mc") != rota:
                    continue
                vistos.add(c["id"])
                if eventos:
                    c["J_porte"] = j_eventos(c, eventos)
                out.append(c)
    return [c for c in out if c.get(objetivo) is not None and math.isfinite(c[objetivo])]


def ler_centro(arg):
    arq, cid = arg.rsplit(":", 1)
    return next(c for c in json.loads(Path(arq).read_text(encoding="utf-8")) if c["id"] == cid)


def pedido(rodada, cands, janelas=JANELAS_CAL, rota="mc", **extra):
    return {"rodada": rodada, "janelas": janelas, "shards": 20, "papeis": PAPEIS,
            "candidatos": [{"id": f"{rodada}-c{i:03d}", "rota": rota, "p": p} for i, p in enumerate(cands)], **extra}


def gerar(a, fam, semente):
    """Candidatos de uma família; devolve (lista de parâmetros, informação para o pedido)."""
    global P
    P = e3.FAMILIAS[fam]
    chaves = list(P)
    if a.modo in ("lhs", "teste"):
        n = 2 if a.modo == "teste" else a.n
        amostras = qmc.LatinHypercube(d=len(chaves), seed=semente).random(n)
        return [from_unit(dict(zip(chaves, x))) for x in amostras], {}
    livres = set(a.livres.split(",")) if a.livres else set(chaves)
    if a.modo == "viz":
        c0 = ler_centro(a.centro)
        p0 = {k: c0["p"].get(k, NEUTROS.get(k)) for k in chaves}
        u0 = to_unit(p0)
        amostras = qmc.LatinHypercube(d=len(chaves), seed=semente).random(a.n - 1)
        cands = [p0]
        for x in amostras:
            u = {k: u0[k] if k not in livres else (u0[k] + a.raio * (2 * xi - 1)) if k in c0["p"] else
                 (u0[k] + a.raio_novos * (2 * xi - 1)) if a.raio_novos > 0 else xi for k, xi in zip(chaves, x)}
            cands.append(from_unit(u))
        return cands, {"centro": c0["id"], "raio": a.raio, "raio_novos": a.raio_novos, "livres": sorted(livres)}
    obj = "J_porte" if a.eventos else a.objetivo
    eventos = a.eventos.split(",") if a.eventos else None
    todos = sorted(ler_resultados(a.resultados, a.rota, a.objetivo, eventos), key=lambda c: c[obj])
    if not todos:
        sys.exit(f"{fam}: nenhum resultado com {obj} finito nas pastas indicadas")
    if a.modo == "top":
        return [c["p"] for c in todos[:a.n]], {"origem": [{"id": c["id"], "J": c["J"], obj: c[obj]}
                                                          for c in todos[:a.n]]}
    elite = todos[:a.mu]
    w = [math.log(a.mu + 0.5) - math.log(i + 1) for i in range(len(elite))]
    us = [to_unit(c["p"]) for c in elite]
    med = {k: sum(wi * u[k] for wi, u in zip(w, us)) / sum(w) for k in chaves}
    rnd = random.Random(semente)
    filhos = [from_unit({k: (med[k] + rnd.gauss(0, a.sigma)) if k in livres else us[0][k] for k in chaves})
              for _ in range(a.lam)]
    return filhos, {"melhor_ate_aqui": {"id": elite[0]["id"], "J": elite[0]["J"], obj: elite[0][obj]},
                    "sigma": a.sigma, "n_avaliados": len(todos), "objetivo": obj, "eventos": eventos,
                    "livres": sorted(livres)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=("lhs", "viz", "es", "top", "teste"))
    ap.add_argument("--familia", default="dc", help="uma ou mais de " + ",".join(e3.FAMILIAS) + ", separadas por vírgula")
    ap.add_argument("--rodada", required=True)
    ap.add_argument("--n", type=int, default=32)
    ap.add_argument("--semente", type=int, default=7)
    ap.add_argument("--resultados", nargs="*", default=[])
    ap.add_argument("--lam", type=int, default=24)
    ap.add_argument("--mu", type=int, default=6)
    ap.add_argument("--sigma", type=float, default=0.15)
    ap.add_argument("--janelas", default=JANELAS_CAL)
    ap.add_argument("--rota", default="mc", choices=("mc", *e3.ROTAS_8PT))
    ap.add_argument("--objetivo", default="J", choices=("J", "J_pico"))
    ap.add_argument("--centro", default="", help="resultado.json:id (modo viz)")
    ap.add_argument("--raio", type=float, default=0.15)
    ap.add_argument("--raio-novos", type=float, default=0.0,
                    help="viz: parâmetros novos amostrados a ±raio-novos do valor neutro (0 = faixa toda)")
    ap.add_argument("--eventos", default="", help="objetivo = média de J_ev nesses eventos (J_porte)")
    ap.add_argument("--livres", default="", help="parâmetros que variam (padrão: todos da família)")
    ap.add_argument("--forcamento", default="", help="pasta de chuva do lote (ex.: forcamento_v3b)")
    ap.add_argument("--saida", default="")
    a = ap.parse_args()
    janelas = "S2023_09,S2023_11" if a.modo == "teste" else a.janelas
    cands, extra = [], {"familias": {}}
    for i, fam in enumerate(a.familia.split(",")):
        c, x = gerar(a, fam, a.semente + i)
        extra["familias"][fam] = {"de": len(cands), "ate": len(cands) + len(c) - 1, **x}
        cands += c
    if a.forcamento:
        extra["forcamento"] = a.forcamento
    out = pedido(a.rodada, cands, janelas, a.rota, **extra)
    txt = json.dumps(out, indent=1, default=float)
    if a.saida:
        Path(a.saida).write_text(txt, encoding="utf-8")
        print(f"{a.saida}: {len(out['candidatos'])} candidatos, rota={a.rota}, janelas={out['janelas'][:60]}")
    else:
        print(txt)


if __name__ == "__main__":
    main()
