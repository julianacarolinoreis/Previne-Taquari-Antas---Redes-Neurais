#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Análises adicionais da validação de campo do HAND de Santa Tereza.

Complementa `analise_erros_campo.py` e `estatisticas_manuscrito.py` com:

1. concordância da profundidade: regressão observada × estimada, NSE, KGE e
   classes de perigo (<0,5; 0,5–1; 1–2; >2 m) com kappa ponderado;
2. cota da cheia observada (RTK) × cota do trecho de drenagem a que o HAND
   refere cada ponto: testa a premissa de linha d'água paralela ao rio no LiDAR
   e compara HAND e plano horizontal por validação cruzada leave-one-out;
3. erro horizontal da borda da mancha nos limites (distância assinada ao
   contorno HAND do evento) e sua relação com a declividade do terreno;
4. altitude do terreno nos vértices RTK segundo LiDAR 10 m, MDT de drone 1 m
   e ANADEM 30 m;
5. orçamento de erros por Monte Carlo (incertezas de medição assumidas);
6. sensibilidade aos pontos excluídos e ao HAND web de 5 m.

As coordenadas ficam só em memória; os arquivos gravados não as contêm.

Uso:
  python pesquisas/validacao-campo-hand-santa-tereza/analises_adicionais.py \
      caminho/para/sumario_erros_hand.xlsx
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy import stats

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analise_erros_campo as A  # noqa: E402

DATA = A.DATA
OUT = HERE / "analises_adicionais.json"
FIG = A.FIG_DIR / "fig_adicional_cheia_vs_drenagem.png"
RNG = np.random.default_rng(42)
B = 20_000
CLASSES = [0.5, 1.0, 2.0]  # limites das classes de profundidade (m)


def r3(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 3)


def boot_ci(a, fn):
    a = np.asarray(a, float)
    idx = RNG.integers(0, a.size, size=(B, a.size))
    v = fn(a[idx])
    return [r3(np.percentile(v, 2.5)), r3(np.percentile(v, 97.5))]


# ----------------------------------------------------------------- 1. concordância
def concordancia(obs, sim):
    obs, sim = np.asarray(obs, float), np.asarray(sim, float)
    lr = stats.linregress(obs, sim)
    e = sim - obs
    nse = 1 - np.sum(e ** 2) / np.sum((obs - obs.mean()) ** 2)
    r = np.corrcoef(obs, sim)[0, 1]
    kge = 1 - math.sqrt((r - 1) ** 2 + (sim.std() / obs.std() - 1) ** 2 + (sim.mean() / obs.mean() - 1) ** 2)
    rho_e = stats.spearmanr(obs, e)
    return {"n": int(obs.size), "inclinacao": r3(lr.slope), "intercepto": r3(lr.intercept),
            "r2": r3(lr.rvalue ** 2), "nse": r3(nse), "kge": r3(kge),
            "spearman_erro_vs_obs": r3(rho_e.statistic), "p_spearman": r3(rho_e.pvalue)}


def classe(d):
    d = np.asarray(d, float)
    return np.digitize(np.where(d < 0, 0, d), CLASSES, right=True)


def kappa_ponderado(a, b, k=4):
    m = np.zeros((k, k))
    for i, j in zip(a, b):
        m[i, j] += 1
    w = 1 - np.abs(np.subtract.outer(np.arange(k), np.arange(k))) / (k - 1)
    po = (w * m).sum() / m.sum()
    pe = (w * np.outer(m.sum(1), m.sum(0))).sum() / m.sum() ** 2
    return (po - pe) / (1 - pe), m


def loo(y, X):
    """MAE leave-one-out de mínimos quadrados y ~ X (X já com as colunas desejadas)."""
    res = []
    for i in range(len(y)):
        k = np.arange(len(y)) != i
        beta, *_ = np.linalg.lstsq(X[k], y[k], rcond=None)
        res.append(y[i] - X[i] @ beta)
    return np.array(res)


def main(xlsx: Path):
    import rasterio
    from PIL import Image
    from pyproj import Transformer
    from shapely.geometry import Point, shape
    from shapely.ops import transform as shp_transform
    from shapely.prepared import prep

    rtk, linhas = A.ler_planilha(xlsx)
    regs, excluidos = A.montar_registros(rtk, linhas)
    to_utm = Transformer.from_crs("EPSG:4674", "EPSG:31982", always_xy=True)
    to_geo = Transformer.from_crs("EPSG:31982", "EPSG:4674", always_xy=True)
    out = {"fonte": "analises_adicionais.py", "B_bootstrap": B, "semente": 42}

    # ------------------------------------------------ 1. concordância e classes
    obs = np.array([r["lamina_obs_m"] for r in regs])
    sim = np.array([r["lamina_hand_m"] for r in regs])
    marcas = np.array([r["tipo"] == "marca" for r in regs])
    out["concordancia_profundidade"] = {
        "todas": concordancia(obs, sim),
        "marcas": concordancia(obs[marcas], sim[marcas]),
        "marcas_sem_V010": concordancia(obs[marcas & (np.array([r["id"] for r in regs]) != "V010")],
                                        sim[marcas & (np.array([r["id"] for r in regs]) != "V010")]),
    }
    co, cs = classe(obs), classe(sim)
    kw, m = kappa_ponderado(co, cs)
    out["classes_perigo"] = {
        "limites_m": CLASSES,
        "acerto_exato": r3(np.mean(co == cs)),
        "acerto_mais_menos_1_classe": r3(np.mean(np.abs(co - cs) <= 1)),
        "subestima_classe": int(np.sum(cs < co)),
        "superestima_classe": int(np.sum(cs > co)),
        "kappa_ponderado_linear": r3(kw),
        "matriz_obs_linhas_sim_colunas": m.astype(int).tolist(),
        "n": int(len(co)),
    }

    # ------------------------------------------------ 2. linha d'água × cota do trecho de drenagem (set/2023, RTK)
    # O HAND supõe a cheia paralela ao rio no LiDAR: cota da cheia = z_drenagem + (H_r − z0).
    # Se a cheia na cidade for um remanso plano, a cota observada não acompanha z_drenagem.
    contornos = json.loads((DATA / "santa_tereza_inundacao" / "contornos_mancha.json").read_text())
    pts = [r for r in regs if r["rtk_valido"] and r["evento"] == "2023-09"]
    lim = A.LIMIAR_HAND["2023-09"]
    wse_obs = np.array([r["z_rtk_m"] + r["lamina_obs_m"] for r in pts])
    wse_mod = np.array([r["z_lidar_m"] + r["lamina_hand_m"] for r in pts])
    z_dren = wse_mod - lim
    lr = stats.linregress(z_dren, wse_obs)
    tcrit = stats.t.ppf(0.975, len(pts) - 2)
    ic_b = [r3(lr.slope - tcrit * lr.stderr), r3(lr.slope + tcrit * lr.stderr)]
    t1 = (lr.slope - 1) / lr.stderr
    grupo_sup = z_dren > 53.2
    one = np.ones(len(pts))
    modelos = {"plano_horizontal_1p": loo(wse_obs, one[:, None]), "hand_1p": loo(wse_obs - wse_mod, one[:, None])}
    dif = np.abs(modelos["plano_horizontal_1p"]) - np.abs(modelos["hand_1p"])
    out["linha_dagua_vs_drenagem_set2023"] = {
        "n_pontos_rtk": int(len(pts)),
        "cota_drenagem_m": {"grupo_inferior_mediana": r3(np.median(z_dren[~grupo_sup])), "grupo_superior_mediana": r3(np.median(z_dren[grupo_sup])),
                            "n_inferior": int((~grupo_sup).sum()), "n_superior": int(grupo_sup.sum())},
        "cota_cheia_observada_m": {"grupo_inferior_media": r3(wse_obs[~grupo_sup].mean()), "grupo_superior_media": r3(wse_obs[grupo_sup].mean())},
        "inclinacao_obs_vs_drenagem": r3(lr.slope), "inclinacao_ic95": ic_b, "r2": r3(lr.rvalue ** 2),
        "p_inclinacao_igual_1": r3(2 * stats.t.sf(abs(t1), len(pts) - 2)),
        "p_inclinacao_igual_0": r3(lr.pvalue),
        "loocv": {k: {"mae_loo": r3(np.abs(v).mean()), "rmse_loo": r3(np.sqrt((v ** 2).mean()))} for k, v in modelos.items()},
        "dif_mae_loo_plano_menos_hand": r3(dif.mean()),
        "dif_mae_loo_ic_boot": boot_ci(dif, lambda x: x.mean(axis=1)),
        "p_wilcoxon_pareado": r3(stats.wilcoxon(np.abs(modelos["plano_horizontal_1p"]), np.abs(modelos["hand_1p"])).pvalue),
        "por_ponto": [{"id": r["id"], "tipo": r["tipo"], "cota_drenagem_m": r3(zd), "cota_obs_m": r3(o), "cota_hand_m": r3(mm)}
                      for r, zd, o, mm in zip(pts, z_dren, wse_obs, wse_mod)],
    }

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "Liberation Serif", "font.size": 9, "mathtext.fontset": "stix"})
    fig, ax = plt.subplots(figsize=(3.4, 3.0), dpi=300)
    xx = np.linspace(z_dren.min() - 0.15, z_dren.max() + 0.15, 10)
    vies = float(np.mean(wse_obs - wse_mod))
    ax.plot(xx, xx + lim + vies, color="#d9531e", lw=1.0, label="premissa do HAND (inclinação 1)")
    ax.plot(xx, lr.intercept + lr.slope * xx, color="#1a1a1a", lw=0.9, ls="--", label=f"ajuste às observações ({lr.slope:.2f})".replace(".", ",").replace("-", "−"))
    tip = np.array([r["tipo"] for r in pts])
    for t, mk, rot in (("marca", "^", "marcas"), ("limite", "o", "limites")):
        k = tip == t
        ax.scatter(z_dren[k], wse_obs[k], marker=mk, color="#1a1a1a", s=20, zorder=4, label=f"cota observada ({rot})")
    ax.set_xlim(52.3, 54.05)
    ax.set_xlabel("Cota do trecho de drenagem no LiDAR (m)")
    ax.set_ylabel("Cota da cheia de set/2023 (m)")
    ax.legend(fontsize=6.3, frameon=False, loc="upper center", bbox_to_anchor=(0.45, -0.2), ncol=2, columnspacing=0.8, handletextpad=0.4)
    ax.grid(alpha=0.25, lw=0.4)
    from matplotlib.ticker import FuncFormatter
    fmt = FuncFormatter(lambda v, _: f"{v:.1f}".replace(".", ","))
    ax.xaxis.set_major_formatter(fmt); ax.yaxis.set_major_formatter(fmt)
    fig.tight_layout()
    fig.savefig(FIG, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)

    # LiDAR 10 m (para declividade e comparação de MDTs)
    meta = json.loads((DATA / "santa_tereza_inundacao" / "mdt" / "altitude_terreno_lidar_10m.json").read_text())
    img = np.array(Image.open(DATA / "santa_tereza_inundacao" / "mdt" / meta["png"]))
    z10 = (img[..., 0].astype(float) * 256 + img[..., 1]) * meta["escala"]
    z10[img[..., 3] == 0] = np.nan

    def lidar10(lon, lat):
        c = int((lon - meta["W"]) / (meta["E"] - meta["W"]) * meta["cols"])
        r = int((meta["N"] - lat) / (meta["N"] - meta["S"]) * meta["rows"])
        return float(z10[r, c])

    # ------------------------------------------------ 3. erro horizontal nos limites
    niveis = {round(f["properties"]["nivel_m"], 1): shape(f["geometry"]) for f in contornos["features"]}
    lims = [r for r in regs if r["tipo"] == "limite"]
    ev_nivel = {ev: round(math.floor(A.LIMIAR_HAND[ev] * 10 + 1e-9) / 10, 1) for ev in A.LIMIAR_HAND}
    poli_utm = {}
    linhas_h = []
    for r in lims:
        if "_E" not in r:
            continue
        nv = ev_nivel[r["evento"]]
        if nv not in poli_utm:
            poli_utm[nv] = shp_transform(lambda x, y, z=None: to_utm.transform(x, y), niveis[nv])
        p = Point(r["_E"], r["_N"])
        g = poli_utm[nv]
        d = g.boundary.distance(p)
        dentro = g.contains(p)
        # declividade local no LiDAR 10 m (diferenças centradas de 10 m)
        lon, lat = to_geo.transform(r["_E"], r["_N"])
        def zat(dx, dy):
            return lidar10(*to_geo.transform(r["_E"] + dx, r["_N"] + dy))
        gxl = (zat(10, 0) - zat(-10, 0)) / 20
        gyl = (zat(0, 10) - zat(0, -10)) / 20
        decl = math.hypot(gxl, gyl)
        linhas_h.append({"id": r["id"], "evento": r["evento"], "nivel_contorno": nv,
                         "dist_assinada_m": r3(-d if dentro else d), "erro_h_rtk_planilha_m": r["erro_h_rtk_m"],
                         "erro_h_cel_planilha_m": r["erro_h_cel_m"], "e_s_m": r["erro_cota_rtk_m"],
                         "declividade_pct": r3(100 * decl),
                         "dist_implicita_m": r3(abs(r["erro_cota_rtk_m"]) / decl) if decl > 0 and r["erro_cota_rtk_m"] is not None else None})
    dh = np.array([abs(x["dist_assinada_m"]) for x in linhas_h])
    out["erro_horizontal_limites"] = {
        "n": len(linhas_h),
        "dist_absoluta_m": {"media": r3(dh.mean()), "mediana": r3(np.median(dh)), "max": r3(dh.max())},
        "dentro_da_mancha": int(sum(x["dist_assinada_m"] < 0 for x in linhas_h)),
        "fora_da_mancha": int(sum(x["dist_assinada_m"] > 0 for x in linhas_h)),
        "planilha_celular_m": {"media": r3(np.nanmean([x["erro_h_cel_planilha_m"] for x in linhas_h])),
                                "mediana": r3(np.nanmedian([x["erro_h_cel_planilha_m"] for x in linhas_h]))},
        "planilha_rtk_m": {"media": r3(np.nanmean([x["erro_h_rtk_planilha_m"] for x in linhas_h])),
                            "mediana": r3(np.nanmedian([x["erro_h_rtk_planilha_m"] for x in linhas_h]))},
        "declividade_pct_mediana": r3(np.median([x["declividade_pct"] for x in linhas_h])),
        "spearman_dist_vs_dist_implicita": r3(stats.spearmanr(dh, [x["dist_implicita_m"] for x in linhas_h]).statistic),
        "por_ponto": linhas_h,
    }

    # ------------------------------------------------ 4. MDTs nos vértices RTK
    vert = [(k, v) for k, v in rtk.items() if k != "BaseCerta"]
    def amostra(tif, lon, lat):
        with rasterio.open(tif) as ds:
            v = next(ds.sample([(lon, lat)]))[0]
            return None if v == ds.nodata or not np.isfinite(v) else float(v)
    comp = {"lidar_10m": [], "drone_1m": [], "anadem_30m": []}
    for k, v in vert:
        lon, lat = to_geo.transform(v["E"], v["N"])
        comp["lidar_10m"].append(lidar10(lon, lat) - v["H"])
        a = amostra(DATA / "santa_tereza_inundacao" / "mdt" / "mdt_santa_tereza_drone_1m.tif", lon, lat)
        if a is not None:
            comp["drone_1m"].append(a - v["H"])
        a = amostra(DATA / "santa_tereza_inundacao" / "mdt" / "mdt_santa_tereza_anadem_30m.tif", lon, lat)
        if a is not None:
            comp["anadem_30m"].append(a - v["H"])
    out["mdt_nos_vertices_rtk"] = {k: ({"n": len(v), "vies": r3(np.mean(v)), "mediana": r3(np.median(v)),
                                         "rmse": r3(np.sqrt(np.mean(np.square(v)))),
                                         "nmad": r3(1.4826 * np.median(np.abs(np.array(v) - np.median(v))))} if v else None)
                                   for k, v in comp.items()}
    out["mdt_nos_vertices_rtk"]["nota"] = "diferença MDT − RTK (altitude normal, h − 6,46 m); datum vertical do drone não documentado"

    # ------------------------------------------------ 5. orçamento de erros (Monte Carlo)
    sig = {"marca_ou_limite_em_campo": 0.10, "lidar_celula": 0.15, "lidar_drenagem": 0.15, "quantizacao_hand": 0.05 / math.sqrt(3)}
    nmc = 100_000
    e = sum(RNG.normal(0, s_, nmc) for s_ in sig.values())
    out["orcamento_erros_mc"] = {
        "sigmas_assumidos_m": {k: r3(v) for k, v in sig.items()},
        "mae_esperado_m": r3(np.abs(e).mean()),
        "mae_observado_set2023_m": r3(np.mean([abs(r["erro_lamina_m"]) for r in regs if r["calibracao"]])),
        "nota": "pico da régua omitido: o z0 calibrado absorve o erro comum a todos os pontos do evento",
    }

    # ------------------------------------------------ 6. sensibilidade
    exc = []
    for p in linhas:
        if p["obs"] and p["z_lidar"] is not None and p["lam_set23"] is not None:
            alt = p["altura"] or 0.0
            exc.append({"id": p["id"], "motivo": str(p["obs"]).strip(), "lamina_obs_m": alt,
                        "erro_lamina_set2023_m": r3(p["lam_set23"] - alt)})
    out["pontos_excluidos"] = exc
    todos = [r["erro_lamina_m"] for r in regs] + [x["erro_lamina_set2023_m"] for x in exc]
    out["todas_com_excluidos"] = {"n": len(todos), "vies": r3(np.mean(todos)), "mae": r3(np.mean(np.abs(todos)))}
    import csv
    with open(A.OUT_CSV, encoding="utf-8") as fh:
        hw = [float(x["erro_lamina_hand_web_rtk_m"]) for x in csv.DictReader(fh) if x["erro_lamina_hand_web_rtk_m"]]
    out["hand_web_5m_nos_vertices_rtk"] = {"n": len(hw), "vies": r3(np.mean(hw)), "mae": r3(np.mean(np.abs(hw)))}

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
