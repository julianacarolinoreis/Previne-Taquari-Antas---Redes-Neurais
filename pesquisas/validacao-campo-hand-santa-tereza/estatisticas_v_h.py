#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Estatísticas do manuscrito com avaliação vertical só nas marcas (V) e horizontal só nos limites (H).

Lê erros_campo_santa_tereza.csv (gerado por analise_erros_campo.py, sem coordenadas) e grava
estatisticas_v_h.json. Reproduz os números da versão do manuscrito que separa V e H:
Tabela 1, classes de perigo, diagnóstico da referência de drenagem (V de set/2023 com RTK)
e distâncias dos limites à borda da mancha nas posições do celular e RTK.

Uso:
  python pesquisas/validacao-campo-hand-santa-tereza/estatisticas_v_h.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from analise_erros_campo import LIMIAR_HAND, PICO_REGUA_M, ZERO_REGUA_M  # noqa: E402
from analises_adicionais import classe, concordancia, kappa_ponderado, loo  # noqa: E402

PICO_SGB = {"2023-09": 24.04, "2023-11": 21.61, "2024-05": 22.42}  # cotas niveladas pelo SGB [1]


def r3(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 3)


def resumo(e):
    e = np.asarray(e, float)
    return {"n": int(e.size), "vies_m": r3(e.mean()), "mae_m": r3(np.abs(e).mean()),
            "mediana_abs_m": r3(np.median(np.abs(e)))}


def ic_t(e):
    e = np.asarray(e, float)
    t = stats.t.ppf(0.975, e.size - 1) * e.std(ddof=1) / np.sqrt(e.size)
    return [r3(e.mean() - t), r3(e.mean() + t)]


def main():
    d = pd.read_csv(AQUI / "erros_campo_santa_tereza.csv")
    v = d[d.tipo == "marca"]
    h = d[d.tipo == "limite"]
    outros = v[v.evento != "2023-09"]
    vr = v[v.rtk_valido == True]  # noqa: E712
    out = {"fonte": "erros_campo_santa_tereza.csv"}

    # Sensibilidade à fonte do pico (como em estatisticas_manuscrito.py): z0 recalibrado em
    # set/2023 (17 registros V e H) com as cotas niveladas pelo SGB; nov/2023 sem cota SGB.
    cal = d[d.calibracao == True]  # noqa: E712
    z0_sgb = ZERO_REGUA_M + cal.erro_lamina_m.mean() + (PICO_SGB["2023-09"] - PICO_REGUA_M["2023-09"])
    desloc_sgb = {ev: (PICO_SGB[ev] - z0_sgb) - (PICO_REGUA_M[ev] - ZERO_REGUA_M) for ev in PICO_SGB}
    out["z0_m"] = ZERO_REGUA_M
    out["z0_picos_sgb_m"] = r3(z0_sgb)

    out["tabela1"] = {
        "todos_V_ed": resumo(v.erro_lamina_m),
        "set2023_V_ed": resumo(v[v.evento == "2023-09"].erro_lamina_m),
        "outros_eventos_V_ed": {**resumo(outros.erro_lamina_m), "ic95_t_vies_m": ic_t(outros.erro_lamina_m)},
        "outros_eventos_V_ed_picos_sgb": resumo(outros.erro_lamina_m + outros.evento.map(desloc_sgb)),
        "V_com_rtk_ed": resumo(vr.erro_lamina_m),
        "V_com_rtk_es": resumo(vr.erro_cota_rtk_m),
        "V_com_rtk_dz": resumo(vr.dz_lidar_rtk_m),
        "sem_V010_ed": resumo(v[v.id != "V010"].erro_lamina_m),
    }
    out["outros_eventos_sem_V011_vies_m"] = r3(outros[outros.id != "V011"].erro_lamina_m.mean())
    out["V_dentro_05m"] = int((v.erro_lamina_m.abs() <= 0.5).sum())
    out["concordancia_V"] = concordancia(v.lamina_obs_m, v.lamina_hand_m)
    a, b = classe(v.lamina_obs_m), classe(v.lamina_hand_m)
    out["classes_V"] = {"acertos": int((a == b).sum()), "n": int(a.size),
                        "kappa_ponderado_linear": r3(kappa_ponderado(a, b)[0])}

    ed, es = vr.erro_lamina_m.to_numpy(), vr.erro_cota_rtk_m.to_numpy()
    out["V_com_rtk"] = {
        "abs_dz_maior_1m": int((vr.dz_lidar_rtk_m.abs() > 1).sum()),
        "muda_enquadramento_05m": int(((np.abs(ed) <= 0.5) != (np.abs(es) <= 0.5)).sum()),
        "erro_abs_aumentou_com_rtk": int((np.abs(es) > np.abs(ed)).sum()),
    }

    # Diagnóstico da premissa do HAND: cota observada × cota do trecho de drenagem de referência
    s = vr[vr.evento == "2023-09"]
    wse_obs = (s.z_rtk_m + s.lamina_obs_m).to_numpy()
    wse_mod = (s.z_lidar_m + s.lamina_hand_m).to_numpy()
    z_dren = wse_mod - LIMIAR_HAND["2023-09"]
    lr = stats.linregress(z_dren, wse_obs)
    n = len(s)
    t = stats.t.ppf(0.975, n - 2)
    um = np.ones(n)[:, None]
    out["diagnostico_drenagem_V_set2023_rtk"] = {
        "n": n, "ids": s.id.tolist(), "inclinacao": r3(lr.slope),
        "ic95": [r3(lr.slope - t * lr.stderr), r3(lr.slope + t * lr.stderr)],
        "p_inclinacao_1": r3(2 * stats.t.sf(abs((lr.slope - 1) / lr.stderr), n - 2)),
        "loocv_mae_plano_horizontal_m": r3(np.abs(loo(wse_obs, um)).mean()),
        "loocv_mae_hand_m": r3(np.abs(loo(wse_obs - wse_mod, um)).mean()),
    }

    out["horizontal_H"] = {
        pos: {"n": int(h[col].notna().sum()), "min_m": r3(h[col].min()), "max_m": r3(h[col].max()),
              "media_m": r3(h[col].mean()), "desvio_m": r3(h[col].std(ddof=1)),
              "mediana_m": r3(h[col].median())}
        for pos, col in (("celular", "erro_h_cel_m"), ("rtk", "erro_h_rtk_m"))
    }
    out["horizontal_H"]["wilcoxon_rtk_vs_celular_p"] = r3(stats.wilcoxon(h.erro_h_rtk_m, h.erro_h_cel_m).pvalue)

    dest = AQUI / "estatisticas_v_h.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return dest


if __name__ == "__main__":
    print(main())
