"""Executa UM PEDAÇO (shard) de uma rodada de avaliação: para cada (candidato, janela) roda o HEC-HMS e guarda vazao.csv.

Funciona no PC (Windows) e no GitHub Actions (Linux, com HEC_HMS_CMD apontando para o hec-hms.sh).
Uso:
  python nuvem_lote.py --candidatos cands.json --janelas cal --shard 0 --shards 20 --saida saida [--paralelo 4]
cands.json: lista de {"id": "c000", "rota": "mc", "p": {parâmetros de estrutura_v3.PARAMS}}.
--janelas: 'cal' (janelas com eventos de calibração), 'todas' ou lista separada por vírgulas (ex.: S2023_09,X20180721).
Saída: <saida>/<id>/<janela>/vazao.csv (+ erro.txt se a rodada falhar).
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import bacia_inteira as bi
import buscar_v3 as bs
import estrutura_v3 as e3
import hec
from comum import RUNS, SIMULACOES, janela


def janelas(arg):
    if arg == "cal":
        return list(bs.SIMS_CAL)
    if arg == "todas":
        return list(SIMULACOES)
    return [janela(s) for s in arg.split(",") if s]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidatos", required=True)
    ap.add_argument("--janelas", default="cal")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--saida", required=True)
    ap.add_argument("--paralelo", type=int, default=4)
    ap.add_argument("--por-jvm", type=int, default=2)
    a = ap.parse_args()
    cands = json.loads(Path(a.candidatos).read_text(encoding="utf-8"))
    sims = janelas(a.janelas)
    todos = [(c, s) for c in cands for s in sims]
    meus = todos[a.shard::a.shards]
    print(f"shard {a.shard}/{a.shards}: {len(meus)} simulações de {len(todos)} ({len(cands)} candidatos x {len(sims)} janelas)", flush=True)
    hec.NOS_EXTRA = sorted({c[1] for c in bi.CONTROLES.values()})
    jobs = [(RUNS / c["id"] / s, s, e3.bacia_v3(c["p"], s, c.get("rota", "mc")), e3.tabelas_v3(c["p"], c.get("rota", "mc")))
            for c, s in meus]
    res = hec.rodar_lote(jobs, paralelo=a.paralelo, por_jvm=a.por_jvm)
    saida = Path(a.saida)
    falhas = 0
    for (c, s), (d, *_) in zip(meus, jobs):
        alvo = saida / c["id"] / s
        alvo.mkdir(parents=True, exist_ok=True)
        r = res[d]
        if isinstance(r, Exception):
            falhas += 1
            (alvo / "erro.txt").write_text(str(r)[:2000], encoding="utf-8")
        else:
            shutil.copy2(d / "vazao.csv", alvo / "vazao.csv")
    print(f"concluído: {len(meus) - falhas} ok, {falhas} falhas", flush=True)
    return 1 if falhas == len(meus) and meus else 0


if __name__ == "__main__":
    sys.exit(main())
