"""Quantifica o bug da hora do INMET (chuva_fontes.py: str(hora)[:2]) no registro inteiro e nas 33 janelas.

1. Confere que inmet.ler(bug=True) == chuva_fontes.inmet() original (importado de D:\\PREVINE\\hec_calibracao_20261005,
   sem gravar nada lá).
2. Para cada leitura com chuva: ficou na hora certa, foi deslocada (quanto) ou se perdeu (sobrescrita por outra hora).
3. Para cada hora da grade corrigida: valor certo, lacuna ou valor errado no lido com bug.
4. Totais diários (dia BRT) com e sem bug: correlação e diferença.
5. Por janela: postos INMET, horas com valor diferente, chuva deslocada/perdida.
Saída: bug_inmet.json
"""
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
AQUI = Path(__file__).resolve().parent
ORIG = Path(r"D:\PREVINE\hec_calibracao_20261005")
os.environ.setdefault("HEC_CATALOGO", "catalogo_ampliado.json")
sys.path.insert(0, str(ORIG))
import chuva_fontes as CF  # noqa: E402
import forcamento as F1  # noqa: E402
from comum import SIMULACOES  # noqa: E402

import inmet as I  # noqa: E402

TESTE = "X20260918"
JANELAS = [s for s in SIMULACOES if s != TESTE]


def linhas_estacao(f):
    """Leituras válidas (mesmo filtro do original) com hora certa, hora com bug e se sobreviveram ao dict do original."""
    d = I.bruto(f)
    data = pd.to_datetime(d.data, format="%d/%m/%Y", errors="coerce")
    hb = pd.to_numeric(d.hora.astype(str).str[:2], errors="coerce")
    hc = pd.to_numeric(d.hora, errors="coerce") // 100
    mm = pd.to_numeric(d.mm, errors="coerce")
    x = pd.DataFrame({"utc_h": hc, "tb": data + pd.to_timedelta(hb, unit="h") - timedelta(hours=3),
                      "tc": data + pd.to_timedelta(hc, unit="h") - timedelta(hours=3), "mm": mm})
    x = x[x.mm.notna() & x.tb.notna() & (x.mm >= 0) & (x.mm < 200)].reset_index(drop=True)
    x["sobrevive"] = ~x.duplicated("tb", keep="last")
    return x


def main():
    orig, _ = CF.inmet()
    bug, meta = I.ler(True)
    cor, _ = I.ler(False)
    igual = set(orig) == set(bug) and all(orig[k] == bug[k] for k in orig)
    print("inmet.ler(bug=True) == chuva_fontes.inmet() original:", igual, flush=True)
    assert igual

    import glob
    res = {"reproduz_original": igual, "estacoes": {}, "janelas": {}}
    desloc = Counter()
    tot = Counter()
    linhas = {}
    for f in sorted(glob.glob(str(I.INMET / "dados_*_H_*.csv"))):
        key = "INMET_" + I.cabecalho(f)["Codigo Estacao"]
        if key not in bug:
            continue
        x = linhas_estacao(f)
        linhas[key] = x
        chuva = x[x.mm > 0]
        certo = chuva.sobrevive & (chuva.tb == chuva.tc)
        mov = chuva.sobrevive & (chuva.tb != chuva.tc)
        perd = ~chuva.sobrevive
        for dh, mmv in zip(((chuva.tb - chuva.tc)[mov].dt.total_seconds() // 3600).astype(int), chuva.mm[mov]):
            desloc[int(dh)] += 1
        b, c = bug[key], cor[key]
        grade = sorted(c)
        n_ok = sum(1 for h in grade if h in b and b[h] == c[h])
        n_lac = sum(1 for h in grade if h not in b)
        n_err = sum(1 for h in grade if h in b and b[h] != c[h])
        dia_b = pd.Series(b).groupby(lambda t: t.date()).sum()
        dia_c = pd.Series(c).groupby(lambda t: t.date()).sum()
        dd = pd.concat([dia_b, dia_c], axis=1).fillna(0.0)
        dd = dd[(dd[0] > 0) | (dd[1] > 0)]
        r = dict(nome=meta[key][0], leituras_validas=int(len(x)), leituras_01_09utc=int(x.utc_h.between(1, 9).sum()),
                 leituras_com_chuva=int(len(chuva)), chuva_total_mm=round(float(chuva.mm.sum()), 1),
                 chuva_hora_certa_mm=round(float(chuva.mm[certo].sum()), 1),
                 chuva_deslocada_mm=round(float(chuva.mm[mov].sum()), 1), chuva_perdida_mm=round(float(chuva.mm[perd].sum()), 1),
                 leituras_chuva_deslocadas=int(mov.sum()), leituras_chuva_perdidas=int(perd.sum()),
                 horas_grade=len(grade), horas_certas=n_ok, horas_lacuna=n_lac, horas_valor_errado=n_err,
                 corr_total_diario=round(float(np.corrcoef(dd[0], dd[1])[0, 1]), 3),
                 razao_total_diario_bug_sobre_certo=round(float(dd[0].sum() / dd[1].sum()), 3))
        res["estacoes"][key] = r
        for k in ("leituras_validas", "leituras_01_09utc", "leituras_com_chuva", "leituras_chuva_deslocadas",
                  "leituras_chuva_perdidas", "horas_grade", "horas_certas", "horas_lacuna", "horas_valor_errado"):
            tot[k] += r[k]
        for k in ("chuva_total_mm", "chuva_hora_certa_mm", "chuva_deslocada_mm", "chuva_perdida_mm"):
            tot[k] += r[k]
        print(key, r, flush=True)
    res["total"] = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in tot.items()}
    res["deslocamento_h_das_leituras_com_chuva_que_sobrevivem"] = dict(sorted(desloc.items()))

    for sim in JANELAS:
        cfg = SIMULACOES[sim]
        horas = F1.grade(cfg["ini"], cfg["fim"])
        hs = set(horas)
        jr = {"postos_com_dado": 0, "horas_posto_dif": 0, "horas_posto_lacuna_bug": 0, "horas_posto_valor_errado": 0,
              "chuva_certa_mm": 0.0, "chuva_bug_mm": 0.0, "chuva_hora_errada_mm": 0.0, "por_posto": {}}
        for key in bug:
            b = {h: v for h, v in bug[key].items() if h in hs}
            c = {h: v for h, v in cor[key].items() if h in hs}
            if not b and not c:
                continue
            jr["postos_com_dado"] += 1
            lac = sum(1 for h in c if h not in b)
            err = sum(1 for h in c if h in b and b[h] != c[h]) + sum(1 for h in b if h not in c)
            # chuva certa que não está na hora certa no lido com bug (perdida ou trocada)
            fora = sum(v for h, v in c.items() if b.get(h) != v)
            jr["horas_posto_lacuna_bug"] += lac
            jr["horas_posto_valor_errado"] += err
            jr["horas_posto_dif"] += lac + err
            jr["chuva_certa_mm"] += sum(c.values())
            jr["chuva_bug_mm"] += sum(b.values())
            jr["chuva_hora_errada_mm"] += fora
            jr["por_posto"][key] = dict(horas=len(c), lacuna=lac, errada=err, total_certo=round(sum(c.values()), 1),
                                        total_bug=round(sum(b.values()), 1), chuva_fora_do_lugar=round(fora, 1))
        for k in ("chuva_certa_mm", "chuva_bug_mm", "chuva_hora_errada_mm"):
            jr[k] = round(jr[k], 1)
        jr["afetada"] = jr["horas_posto_dif"] > 0
        res["janelas"][sim] = jr
        print(sim, {k: v for k, v in jr.items() if k != "por_posto"}, flush=True)
    afet = [s for s, j in res["janelas"].items() if j["afetada"]]
    res["janelas_afetadas"] = afet
    res["resumo_janelas"] = dict(
        n_afetadas=len(afet), n_total=len(JANELAS),
        horas_posto_dif=sum(res["janelas"][s]["horas_posto_dif"] for s in afet),
        chuva_certa_mm=round(sum(res["janelas"][s]["chuva_certa_mm"] for s in afet), 1),
        chuva_hora_errada_mm=round(sum(res["janelas"][s]["chuva_hora_errada_mm"] for s in afet), 1))
    print("RESUMO", res["total"], res["deslocamento_h_das_leituras_com_chuva_que_sobrevivem"], res["resumo_janelas"], flush=True)
    (AQUI / "bug_inmet.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
