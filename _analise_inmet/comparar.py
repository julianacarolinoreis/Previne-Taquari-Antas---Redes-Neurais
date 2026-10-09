"""Compara rodadas (resultado.json do lote) por candidato: J cal (= J do lote), J_pico, J val, e por controle a mediana
de NSE, vol, erro de pico e lag (cal e val) — mesma conta do _analise_modelo/resumo.py.
Uso: python comparar.py <rodada_ref>:<id> <rodada>:<id> [...] [--md saida.md] [--rotulos a,b,...]
Ex.: python comparar.py in-v3:in-v3-c000 in-v3b:in-v3b-c000
"""
import json
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

AQUI = Path(__file__).resolve().parent
OBJ = ("TAINHAS", "CASTRO_ALVES", "MONTE_CLARO", "LJJ", "MUCUM", "ENCANTADO")


def cand(arg):
    rod, cid = arg.split(":")
    return next(c for c in json.loads((AQUI / "res" / rod / "resultado.json").read_text(encoding="utf-8")) if c["id"] == cid)


def j_papel(c, papel):
    ev = defaultdict(list)
    for m in c["metricas"]:
        if m["papel"] == papel and m["controle"] in OBJ and m["pen"] is not None:
            ev[m["evento"]].append(min(m["pen"], 60.0))
    js = {e: sum(v) / len(v) for e, v in ev.items()}
    return (st.mean(js.values()) if js else float("nan")), js


def por_controle(c, papel):
    g = defaultdict(list)
    for m in c["metricas"]:
        if m["papel"] == papel and m["nse"] is not None and m["controle"] in OBJ:
            g[m["controle"]].append(m)
    out = {}
    for k in OBJ:
        v = g.get(k, [])
        if not v:
            continue
        pk = [m["erro_pico"] for m in v if m["erro_pico"] is not None]
        lg = [m["lag_h"] for m in v if m["lag_h"] is not None]
        out[k] = dict(n=len(v), nse=st.median(m["nse"] for m in v), vol=st.median(m["vol"] for m in v),
                      pico=st.median(pk) if pk else float("nan"), lag=st.median(lg) if lg else float("nan"),
                      passa=sum(1 for m in v if m["passa"]))
    return out


def resumo(c):
    jc, evc = j_papel(c, "calibracao")
    jv, evv = j_papel(c, "validacao")
    return dict(J=c["J"], J_pico=c.get("J_pico"), J_cal=jc, J_val=jv, ev_cal=evc, ev_val=evv,
                cal=por_controle(c, "calibracao"), val=por_controle(c, "validacao"))


def main():
    argv, opc = sys.argv[1:], {}
    for k in ("--md", "--rotulos"):
        if k in argv:
            i = argv.index(k)
            opc[k] = argv[i + 1]
            del argv[i:i + 2]
    args, md = argv, opc.get("--md")
    rot = opc["--rotulos"].split(",") if "--rotulos" in opc else args
    R = [resumo(cand(a)) for a in args]
    L = ["| versão | J cal | J_pico cal | J val | passa cal | passa val |", "|---|---|---|---|---|---|"]
    for r, n in zip(R, rot):
        L.append(f"| {n} | {r['J']:.3f} | {r['J_pico']:.3f} | {r['J_val']:.3f} | "
                 f"{sum(v['passa'] for v in r['cal'].values())} | {sum(v['passa'] for v in r['val'].values())} |")
    for papel in ("cal", "val"):
        L += ["", f"Por controle ({papel}; mediana nos eventos): NSE / vol / pico / lag (h)", "",
              "| controle | " + " | ".join(rot) + " |", "|---|" + "---|" * len(rot)]
        for k in OBJ:
            cel = []
            for r in R:
                v = r[papel].get(k)
                cel.append("–" if v is None else f"{v['nse']:.2f} / {v['vol']:+.2f} / {v['pico']:+.2f} / {v['lag']:+.1f}")
            L.append(f"| {k} | " + " | ".join(cel) + " |")
    L += ["", "J por evento (" + " → ".join(rot) + ")", "", "| evento | papel | " + " | ".join(rot) + " |", "|---|---|" + "---|" * len(rot)]
    for papel, chave in (("cal", "ev_cal"), ("val", "ev_val")):
        for e in sorted(R[0][chave], key=lambda x: (len(x), x)):
            L.append(f"| {e} | {papel} | " + " | ".join(f"{r[chave].get(e, float('nan')):.2f}" for r in R) + " |")
    txt = "\n".join(L) + "\n"
    print(txt)
    if md:
        (AQUI / md).write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
