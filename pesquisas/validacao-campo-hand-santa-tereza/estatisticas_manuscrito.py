#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Estatísticas do manuscrito revisado (resposta à banca do SBSR 2027).

Lê `erros_campo_santa_tereza.csv` (gerado por analise_erros_campo.py) e calcula:
- IC 95% por bootstrap (B = 20 000) do viés e do MAE; IC t quando n < 10;
- fração de |e| <= 0,5 m com IC de Wilson;
- z0 calibrado, IC 95% e z0 que anula o viés por evento e por tipo;
- sensibilidade à fonte do pico da régua (telemetria x cota nivelada pelo SGB);
- desnível de terreno celular x RTK (Δz = e_s − e_d) e mudanças de classificação;
- modelo nulo: plano d'água horizontal com um parâmetro (set/2023);
- estrutura espacial da cota modelada (patamares herdados da drenagem).

Uso:
  python pesquisas/validacao-campo-hand-santa-tereza/estatisticas_manuscrito.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
CSV = HERE / "erros_campo_santa_tereza.csv"
OUT = HERE / "estatisticas_manuscrito.json"
B = 20_000
RNG = np.random.default_rng(42)
Z0 = 1.60
# Pico na régua 86472600: telemetria (usada na planilha) e cota nivelada pelo SGB
# (assets/data/estudo_caso_territorio/casos_acoplados.json). Nov/2023 sem cota SGB.
PICO_TELEMETRIA = {"2023-09": 23.65, "2023-11": 21.61, "2024-05": 22.33}
PICO_SGB = {"2023-09": 24.04, "2023-11": 21.61, "2024-05": 22.42}


def r3(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 3)


def boot_ci(a, fn):
    a = np.asarray(a, float)
    idx = RNG.integers(0, a.size, size=(B, a.size))
    v = fn(a[idx])
    return [r3(np.percentile(v, 2.5)), r3(np.percentile(v, 97.5))]


def t_ci(a):
    a = np.asarray(a, float)
    m, s = a.mean(), a.std(ddof=1)
    h = stats.t.ppf(0.975, a.size - 1) * s / math.sqrt(a.size)
    return [r3(m - h), r3(m + h)]


def wilson(k, n):
    z = 1.959964
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [r3(c - h), r3(c + h)]


def resumo(e):
    e = np.asarray(e, float)
    k = int((np.abs(e) <= 0.5).sum())
    out = {
        "n": int(e.size),
        "vies": r3(e.mean()),
        "mae": r3(np.abs(e).mean()),
        "rmse": r3(np.sqrt((e ** 2).mean())),
        "mediana_abs": r3(np.median(np.abs(e))),
        "frac_abs_le_0_5": r3(k / e.size),
        "frac_abs_le_0_5_ic_wilson": wilson(k, e.size),
    }
    if e.size >= 10:
        out["vies_ic_boot"] = boot_ci(e, lambda x: x.mean(axis=1))
        out["mae_ic_boot"] = boot_ci(e, lambda x: np.abs(x).mean(axis=1))
    if e.size >= 3:
        out["vies_ic_t"] = t_ci(e)
    return out


def main():
    d = pd.read_csv(CSV)
    cal = d[d.calibracao]
    ind = d[~d.calibracao]
    rtk = d[d.rtk_valido]
    m = {"fonte": CSV.name, "B_bootstrap": B, "semente": 42}

    m["profundidade"] = {
        "todas": resumo(d.erro_lamina_m),
        "set2023_calibracao": resumo(cal.erro_lamina_m),
        "set2023_marcas": resumo(cal[cal.tipo == "marca"].erro_lamina_m),
        "set2023_limites": resumo(cal[cal.tipo == "limite"].erro_lamina_m),
        "nao_calibracao": resumo(ind.erro_lamina_m),
        "nao_calibracao_sem_V011": resumo(ind[ind.id != "V011"].erro_lamina_m),
        "todas_sem_V010": resumo(d[d.id != "V010"].erro_lamina_m),
    }

    # z0: d_HAND diminui 1:1 com z0; o z0 que anula o viés é Z0 + média(e)
    ec = cal.erro_lamina_m.to_numpy()
    lo, hi = t_ci(ec)
    m["z0"] = {
        "calibrado": r3(Z0 + ec.mean()),
        "ic95_t": [r3(Z0 + lo), r3(Z0 + hi)],
        "ic95_boot": [r3(Z0 + v) for v in boot_ci(ec, lambda x: x.mean(axis=1))],
        "sem_V010": r3(Z0 + cal[cal.id != "V010"].erro_lamina_m.mean()),
        "so_marcas": r3(Z0 + cal[cal.tipo == "marca"].erro_lamina_m.mean()),
        "so_limites": r3(Z0 + cal[cal.tipo == "limite"].erro_lamina_m.mean()),
        "mediana": r3(Z0 + np.median(ec)),
        "por_evento": {ev: {"z0": r3(Z0 + g.erro_lamina_m.mean()), "n": int(len(g))}
                       for ev, g in d.groupby("evento")},
    }
    # LOO com um parâmetro aditivo = resíduo × n/(n−1): registrado só para auditoria
    m["loo_identidade_fator"] = r3(len(ec) / (len(ec) - 1))

    # sensibilidade à fonte do pico: recalibra z0 em set/2023 com o pico SGB
    dz0 = PICO_SGB["2023-09"] - PICO_TELEMETRIA["2023-09"]
    z0_sgb = Z0 + ec.mean() + dz0
    e_sgb = []
    for _, r in ind.iterrows():
        desloc = (PICO_SGB[r.evento] - z0_sgb) - (PICO_TELEMETRIA[r.evento] - Z0)
        e_sgb.append(r.erro_lamina_m + desloc)
    ind_sgb = ind.assign(erro_sgb=e_sgb)
    m["sensibilidade_pico_sgb"] = {
        "picos_telemetria": PICO_TELEMETRIA,
        "picos_sgb": PICO_SGB,
        "z0_calibrado_com_pico_sgb": r3(z0_sgb),
        "nao_calibracao": resumo(ind_sgb.erro_sgb),
        "nao_calibracao_sem_V011": resumo(ind_sgb[ind_sgb.id != "V011"].erro_sgb),
        "por_ponto": {r.id: r3(r.erro_sgb) for _, r in ind_sgb.iterrows()},
    }
    v1 = d.set_index("id")
    m["par_V001"] = {
        "delta_lamina_obs": r3(v1.loc["V001", "lamina_obs_m"] - v1.loc["V001b", "lamina_obs_m"]),
        "delta_pico_telemetria": r3(PICO_TELEMETRIA["2023-09"] - PICO_TELEMETRIA["2023-11"]),
        "delta_pico_sgb_set_tele_nov": r3(PICO_SGB["2023-09"] - PICO_TELEMETRIA["2023-11"]),
    }

    # celular x RTK
    dz = (rtk.erro_cota_rtk_m - rtk.erro_lamina_m).to_numpy()
    ed, es = rtk.erro_lamina_m.to_numpy(), rtk.erro_cota_rtk_m.to_numpy()
    dentro_ed, dentro_es = np.abs(ed) <= 0.5, np.abs(es) <= 0.5
    diff = np.abs(ed) - np.abs(es)
    peq = np.abs(dz) < 0.55
    m["celular_x_rtk"] = {
        "e_d": resumo(ed),
        "e_s": resumo(es),
        "delta_z": {
            "n": int(dz.size),
            "media": r3(dz.mean()),
            "mediana_abs": r3(np.median(np.abs(dz))),
            "nmad": r3(1.4826 * np.median(np.abs(dz - np.median(dz)))),
            "n_abs_gt_1m": int((np.abs(dz) > 1).sum()),
            "ids_abs_gt_1m": rtk.id[np.abs(dz) > 1].tolist(),
            "max_abs": r3(np.abs(dz).max()),
            "subconjunto_abs_lt_0_55": {
                "n": int(peq.sum()), "positivos": int((dz[peq] > 0).sum()),
                "mediana": r3(np.median(dz[peq])),
                "p_sinais": r3(stats.binomtest(int((dz[peq] > 0).sum()), int(peq.sum())).pvalue),
            },
        },
        "mudam_classe_0_5m": int((dentro_ed != dentro_es).sum()),
        "dif_mae_ed_menos_es": r3(diff.mean()),
        "dif_mae_ic_boot": boot_ci(diff, lambda x: x.mean(axis=1)),
    }
    lim = rtk[rtk.tipo == "limite"]
    m["limites_horizontal"] = {
        "celular": {"media": r3(d.erro_h_cel_m.mean()), "mediana": r3(d.erro_h_cel_m.median())},
        "rtk": {"media": r3(d.erro_h_rtk_m.mean()), "mediana": r3(d.erro_h_rtk_m.median())},
        "rtk_fora_da_mancha_ids": lim.id[lim.erro_cota_rtk_m < -0.5].tolist(),
    }

    # estrutura espacial e modelo nulo (set/2023)
    s = cal.assign(cota_mod=cal.z_lidar_m + cal.lamina_hand_m,
                   cota_obs_rtk=cal.z_rtk_m + cal.lamina_obs_m,
                   cota_obs_cel=cal.z_lidar_m + cal.lamina_obs_m)
    s = s.assign(patamar=np.where(s.cota_mod > 75.3, "superior", "inferior"))
    sr = s[s.rtk_valido]
    pat = {}
    for p, g in s.groupby("patamar"):
        gr = g[g.rtk_valido]
        pat[p] = {"n": int(len(g)), "cota_mod_media": r3(g.cota_mod.mean()),
                  "n_rtk": int(len(gr)), "cota_obs_rtk_media": r3(gr.cota_obs_rtk.mean()),
                  "e_s_media": r3(gr.erro_cota_rtk_m.mean())}
    e_hand_rtk = sr.erro_cota_rtk_m - sr.erro_cota_rtk_m.mean()
    e_plano_rtk = sr.cota_obs_rtk - sr.cota_obs_rtk.mean()
    e_hand_cel = s.erro_lamina_m - s.erro_lamina_m.mean()
    e_plano_cel = s.cota_obs_cel - s.cota_obs_cel.mean()
    m["set2023_estrutura"] = {
        "patamares": pat,
        "plano_horizontal": {
            "rtk": {"n": int(len(sr)), "mae_plano": r3(e_plano_rtk.abs().mean()),
                    "mae_hand_vies_zerado": r3(e_hand_rtk.abs().mean())},
            "celular": {"n": int(len(s)), "mae_plano": r3(e_plano_cel.abs().mean()),
                        "mae_hand_vies_zerado": r3(e_hand_cel.abs().mean())},
        },
    }
    obs_v = (d.z_rtk_m + d.lamina_obs_m)
    m["V011_consistencia"] = {
        "cota_obs_rtk_V011": r3(obs_v[d.id == "V011"].iloc[0]),
        "cota_obs_rtk_V005": r3(obs_v[d.id == "V005"].iloc[0]),
    }
    OUT.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(m, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
