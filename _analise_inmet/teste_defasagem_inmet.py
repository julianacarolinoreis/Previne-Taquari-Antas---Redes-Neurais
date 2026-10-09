"""Repete o teste_defasagem.py original (INMET x média dos 3 ANA do Codex a até 40 km, defasagem -3..+3 h) com o INMET
lido com bug e corrigido, nas 33 janelas (sem o teste). Além do histograma do melhor lag por posto x janela (como o
original), calcula a correlação AGRUPADA por defasagem (todos os pares posto x janela juntos), no dia inteiro e só nas
horas que o bug estragava (01-09 UTC = 22-06 h BRT).
L < 0: o INMET marca a chuva L h ANTES dos ANA vizinhos.
Saída: defasagem_inmet.json
"""
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from pyproj import Transformer

sys.dont_write_bytecode = True
AQUI = Path(__file__).resolve().parent
os.environ["HEC_CATALOGO"] = "catalogo_ampliado.json"
sys.path.insert(0, r"D:\PREVINE\hec_calibracao_20261005")
import forcamento as F1  # noqa: E402
from comum import POSTOS, SIMULACOES  # noqa: E402

import inmet as I  # noqa: E402

TR = Transformer.from_crs(4326, 31982, always_xy=True)
LAGS = range(-3, 4)


def main():
    out = {}
    pares = {m: {L: ([], [], []) for L in LAGS} for m in ("bug", "corrigido")}
    hist = {m: Counter() for m in pares}
    det = []
    for sim, cfg in SIMULACOES.items():
        if sim == "X20260918":
            continue
        horas = F1.grade(cfg["ini"], cfg["fim"])
        ana = {}
        for c in POSTOS:
            s, _, _ = F1.chuva_horaria(c, sim, horas)
            if len(s) > 0.5 * len(horas):
                ana[c] = s
        axy = {c: TR.transform(POSTOS[c][2], POSTOS[c][1]) for c in ana}
        for modo in pares:
            inm, meta = I.ler(modo == "bug")
            for k, s_all in inm.items():
                s = {h: s_all[h] for h in horas if h in s_all}
                if len(s) < 0.5 * len(horas) or sum(s.values()) < 30:
                    continue
                xy = TR.transform(meta[k][2], meta[k][1])
                viz = [c for c in sorted(ana, key=lambda c: math.dist(xy, axy[c])) if math.dist(xy, axy[c]) < 40000][:3]
                if len(viz) < 2:
                    continue
                a = np.array([s.get(h, np.nan) for h in horas])
                b = np.array([np.nanmean([ana[v].get(h, np.nan) for v in viz]) if any(h in ana[v] for v in viz) else np.nan
                              for h in horas])
                utc = np.array([(h.hour + 3) % 24 for h in horas])
                best = None
                for L in LAGS:
                    x, y = a[max(0, L):len(a) + min(0, L)], b[max(0, -L):len(b) + min(0, -L)]
                    u = utc[max(0, L):len(a) + min(0, L)]
                    ok = np.isfinite(x) & np.isfinite(y)
                    pares[modo][L][0].extend(x[ok])
                    pares[modo][L][1].extend(y[ok])
                    pares[modo][L][2].extend(u[ok])
                    if ok.sum() < 24 or x[ok].std() == 0 or y[ok].std() == 0:
                        continue
                    r = float(np.corrcoef(x[ok], y[ok])[0, 1])
                    if best is None or r > best[1]:
                        best = (L, r)
                if best and best[1] > 0.5:
                    hist[modo][best[0]] += 1
                    det.append((modo, sim, k, best[0], round(best[1], 2)))
        print(sim, flush=True)
    for modo in pares:
        tot = sum(hist[modo].values())
        agr, noite = {}, {}
        for L in LAGS:
            x, y, u = (np.array(v) for v in pares[modo][L])
            agr[L] = round(float(np.corrcoef(x, y)[0, 1]), 3)
            n = (u >= 1) & (u <= 9)
            noite[L] = round(float(np.corrcoef(x[n], y[n])[0, 1]), 3)
        out[modo] = dict(n_posto_janela=tot, melhor_lag_hist={L: hist[modo][L] for L in LAGS},
                         melhor_lag_pct={L: round(hist[modo][L] / tot * 100) for L in LAGS},
                         corr_agrupada_por_lag=agr, corr_agrupada_01_09utc=noite)
        print(modo, out[modo], flush=True)
    out["detalhe"] = det
    (AQUI / "defasagem_inmet.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
