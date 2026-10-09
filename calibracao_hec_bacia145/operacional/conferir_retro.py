"""Confere uma execução retroativa do ciclo com o estudo _analise_bacia145/chuva_prevista (só no PC: lê artefatos fora do git).

1) Vazão simulada (LJJ, Muçum, Encantado; horária) x vazao.csv da rodada cp-r1/cp-r2 da janela derivada
   <mãe>__<t0>__<cenário>  → diferença máxima (deve ser ~0 na reprodução com a janela-mãe e as chuvas arquivadas).
2) Vazão corrigida (adit_h) em +3/+6/+12/+24/+48 h x linhas_vazao.json do estudo (mesma emissão).
3) Chuva prevista média da bacia de Muçum nas 72 h: ciclo x forcamento_prevista arquivado.
Uso: python conferir_retro.py <saida.json> <mãe> [--analise D:\\PREVINE\\repo_hec_calib\\_analise_bacia145]
"""
import argparse
import csv
import gzip
import json
from datetime import datetime, timedelta
from pathlib import Path

H = timedelta(hours=1)
NOS = {"LJJ": "J_208", "MUCUM": "J_201", "ENCANTADO": "J_258"}


def ler_vazao(p):
    out = {}
    with p.open() as h:
        for r in csv.DictReader(h):
            t = datetime(1899, 12, 31) + timedelta(minutes=int(r["time_value"]))
            out.setdefault(r["node"], {})[t] = float(r["flow"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("saida")
    ap.add_argument("mae")
    ap.add_argument("--analise", default=r"D:\PREVINE\repo_hec_calib\_analise_bacia145")
    a = ap.parse_args()
    d = json.loads(Path(a.saida).read_text(encoding="utf-8"))
    an = Path(a.analise) / "chuva_prevista"
    t0 = datetime.fromisoformat(d["t0"])
    horas = [datetime.fromisoformat(h) for h in d["horas"]]
    rel = {"t0": str(t0), "janela": d["janela"], "simulado_vs_nuvem": {}, "corrigido_vs_estudo": {}, "chuva_72h": {}}
    for cen in d["chuva_media_bacia_mm"]:
        nome = f"{a.mae}__{t0:%Y%m%d%H}__{cen}"
        arqs = list((an / "nuvem").glob(f"*/lote-*/*/{nome}/vazao.csv"))
        if not arqs:
            rel["simulado_vs_nuvem"][cen] = "sem vazao.csv da nuvem"
            continue
        v = ler_vazao(arqs[0])
        r = {}
        for p, no in NOS.items():
            s = d["pontos"][p]["simulado"][cen]
            difs = [abs(x - v[no][t]) for t, x in zip(horas, s) if x is not None and t in v[no]]
            dif_fut = [abs(x - v[no][t]) for t, x in zip(horas, s) if x is not None and t in v[no] and t > t0]
            r[p] = dict(horas=len(difs), max_abs_m3s=round(max(difs), 3), max_abs_depois_t0_m3s=round(max(dif_fut), 3),
                        pico_ciclo=round(max(x for x in s if x is not None), 1), pico_nuvem=round(max(v[no].values()), 1))
        rel["simulado_vs_nuvem"][cen] = dict(arquivo=str(arqs[0].relative_to(an)), **r)
    linhas = json.loads((an / "linhas_vazao.json").read_text(encoding="utf-8"))
    for ln in linhas:
        if ln["sim"] != a.mae or datetime.fromisoformat(ln["t0"]) != t0:
            continue
        p = d["pontos"][ln["alvo"]]
        r = {}
        for cen in d["chuva_media_bacia_mm"]:
            est = ln["prev"].get(f"{cen}|adit_h", {})
            for hz, ve in est.items():
                i = horas.index(t0 + int(hz) * H)
                vc = p["corrigido"][cen][i]
                r[f"{cen}+{hz}h"] = dict(ciclo=vc, estudo=round(ve, 1), obs=ln["obs"].get(hz),
                                         dif=None if vc is None else round(vc - ve, 2))
        rel["corrigido_vs_estudo"][ln["alvo"]] = r
    import numpy as np
    sub = json.loads(gzip.decompress((Path(__file__).parent / "dados" / "subbacias.json.gz").read_bytes()))
    for cen in ("ecmwf", "gfs"):
        f = Path(__file__).resolve().parents[1] / "dados" / "forcamento_prevista" / f"{a.mae}__{cen}.json.gz"
        if cen not in d["chuva_media_bacia_mm"] or not f.exists():
            continue
        e = json.loads(gzip.decompress(f.read_bytes()))["emissoes"].get(f"{t0:%Y%m%d%H}")
        if not e:
            continue
        nomes = sorted(e["chuva"])
        ar = np.array([sub[n]["area_km2"] for n in nomes])
        arq = float(sum((ar @ np.array([e["chuva"][n] for n in nomes])) / ar.sum()))
        i0 = horas.index(t0 + H)
        cic = float(sum(d["chuva_media_bacia_mm"][cen][i0:i0 + 72]))
        rel["chuva_72h"][cen] = dict(ciclo_mm=round(cic, 2), arquivo_mm=round(arq, 2), rodada_arquivo=e["rodada_utc"],
                                     rodada_ciclo=next(c["rodada_utc"] for c in d["cenarios"] if c["id"] == cen))
    print(json.dumps(rel, ensure_ascii=False, indent=1))
    Path(a.saida).with_suffix(".conferencia.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1),
                                                              encoding="utf-8")


if __name__ == "__main__":
    main()
