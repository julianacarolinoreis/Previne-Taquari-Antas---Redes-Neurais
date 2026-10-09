"""Prova de equivalência: o forcamento refeito com o bug (forc_bug/) é igual ao forcamento_v3 commitado?
Compara chuva por sub-bacia (4 casas), média da bacia, postos usados, excluídos no QC, razões, estações por hora e o
registro por posto (horas válidas, total, usado, excluído, defasagem suspeita) com o original do PC.
Também compara forc_corrigido/ com o mesmo para listar o que mudou de postos/QC.
Saída: equivalencia.json
"""
import gzip
import json
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
REPO_V3 = AQUI.parent / "calibracao_hec_bacia145" / "dados" / "forcamento_v3"
PC_V3 = Path(r"D:\PREVINE\hec_calibracao_20261005\forcamento_v3")
CAMPOS_POSTO = ("posto", "fonte", "horas_validas", "horas_esperadas", "total_mm", "usado", "excluido_qc",
                "razao_total_vizinhos", "lag_suspeito", "cadencia_min")


def comparar(a, b):
    subs = list(b["chuva_por_subbacia"])
    A = np.array([a["chuva_por_subbacia"][s] for s in subs], dtype=float)
    B = np.array([b["chuva_por_subbacia"][s] for s in subs], dtype=float)
    return dict(horas_iguais=a["horas"] == b["horas"],
                max_abs_subbacia=float(np.nanmax(np.abs(A - B))) if A.shape == B.shape else None,
                n_valores_diferentes=int((A != B).sum()) if A.shape == B.shape else None,
                media_bacia_igual=a["chuva_media_bacia_mm"] == b["chuva_media_bacia_mm"],
                postos_usados_iguais=a["postos_usados"] == b["postos_usados"],
                excluidos_iguais=a["postos_excluidos_qc"] == b["postos_excluidos_qc"],
                razoes_iguais=a["razao_total_vizinhos"] == b["razao_total_vizinhos"],
                n_disp_iguais=a["estacoes_disponiveis_por_hora"] == b["estacoes_disponiveis_por_hora"])


def main():
    out = {}
    for f in sorted((AQUI / "forc_bug").glob("*.json")):
        if f.name.endswith("_postos.json") or f.name.startswith("comparativo"):
            continue
        sim = f.stem
        bug = json.loads(f.read_text(encoding="utf-8"))
        repo = json.load(gzip.open(REPO_V3 / f"{sim}.json.gz", "rt", encoding="utf-8"))
        pc = json.loads((PC_V3 / f"{sim}.json").read_text(encoding="utf-8"))
        r = {"bug_vs_repo": comparar(bug, repo), "repo_vs_pc": comparar(repo, pc)}
        lb = {x["posto"]: x for x in json.loads((AQUI / "forc_bug" / f"{sim}_postos.json").read_text(encoding="utf-8"))}
        lp = {x["posto"]: x for x in json.loads((PC_V3 / f"{sim}_postos.json").read_text(encoding="utf-8"))}
        dif = [(p, k, lb.get(p, {}).get(k), lp.get(p, {}).get(k)) for p in sorted(set(lb) | set(lp)) for k in CAMPOS_POSTO
               if lb.get(p, {}).get(k) != lp.get(p, {}).get(k)]
        r["registro_postos_bug_vs_pc"] = {"n_postos": len(lp), "mesma_ordem": list(lb) == list(lp), "diferencas": dif[:20],
                                          "n_diferencas": len(dif)}
        cor = json.loads((AQUI / "forc_corrigido" / f"{sim}.json").read_text(encoding="utf-8"))
        r["corrigido_vs_repo"] = comparar(cor, repo)
        r["corrigido_mudancas_postos"] = dict(
            entram=sorted(set(cor["postos_usados"]) - set(repo["postos_usados"])),
            saem=sorted(set(repo["postos_usados"]) - set(cor["postos_usados"])),
            excluidos_v3=repo["postos_excluidos_qc"], excluidos_corrigido=cor["postos_excluidos_qc"])
        out[sim] = r
        e = r["bug_vs_repo"]
        ok = (e["max_abs_subbacia"] == 0 and e["media_bacia_igual"] and e["postos_usados_iguais"] and e["excluidos_iguais"]
              and e["razoes_iguais"] and e["n_disp_iguais"] and e["horas_iguais"] and r["registro_postos_bug_vs_pc"]["n_diferencas"] == 0)
        r["identico"] = ok
        print(sim, "IDÊNTICO" if ok else "DIFERENTE", e, r["registro_postos_bug_vs_pc"]["n_diferencas"],
              "| corrigido:", r["corrigido_vs_repo"]["max_abs_subbacia"], r["corrigido_mudancas_postos"], flush=True)
    out["_resumo"] = dict(janelas=len(out), identicas=sum(1 for v in out.values() if v["identico"]))
    print(out["_resumo"])
    (AQUI / "equivalencia.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
