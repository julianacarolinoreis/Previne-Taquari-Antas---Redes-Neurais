"""Sombra da regra por porte (frente `cursor/hec-bacia145-porte`): em cada ciclo,
  S = chuva das 24 h até t0 + chuva prevista das 48 h seguintes, média na bacia de Muçum (mm), no cenário ECMWF
      (GFS se o ECMWF falhar); a chuva "até t0" é a do forçamento do ciclo (observada até a última hora com dado);
  S ≥ limiar (83,4 mm) → roda também o HEC com o conjunto G robusto (po-r4-c008) e aplica o d_piv reajustado na
  calibração sobre a saída da regra; S < limiar → nada extra. Nunca muda o que é publicado.
Parâmetros em parametros/porte_<conjunto>.json.
"""
import json
from pathlib import Path

import geo

PADRAO = geo.DADOS.parent / "parametros" / "porte_po-r4-c008.json"


def carregar(opcao, pos):
    """opcao: auto (liga só com --pos hibrido), sempre (roda o G mesmo abaixo do limiar: teste de custo), nao, ou arquivo."""
    if opcao == "nao":
        return None, "desligado (--porte nao)"
    if opcao == "auto" and pos != "hibrido":
        return None, "desligado (só com --pos hibrido)"
    arq = PADRAO if opcao in ("auto", "sempre") else Path(opcao)
    if not arq.exists():
        return None, f"sem {arq.name}"
    cfg = json.loads(arq.read_text(encoding="utf-8"))
    cfg["arquivo"], cfg["forcar"] = arq.name, opcao == "sempre"
    return cfg, "ligado"


def indice_s(forc, horas, t0, cfg):
    """(S, chuva das 24 h até t0, chuva prevista das 48 h depois), mm na média da bacia de Muçum."""
    nomes, areas = geo.nomes(), geo.areas()
    a = {n: float(x) for n, x in zip(nomes, areas)}
    subs = cfg["regra"]["subbacias_mucum"]
    tot = sum(a[s] for s in subs)
    j0 = horas.index(t0)
    ch = forc["chuva_por_subbacia"]

    def soma(i, j):
        return sum(a[s] * sum(ch[s][i:j]) for s in subs) / tot
    p24, p48 = soma(max(0, j0 - 23), j0 + 1), soma(j0 + 1, j0 + 49)
    return round(p24 + p48, 1), round(p24, 1), round(p48, 1)
