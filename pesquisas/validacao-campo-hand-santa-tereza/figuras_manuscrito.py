#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Figuras do manuscrito (SBSR 2027), versão revisada após a banca.

Figura 1: área de estudo (mapa único com inserto de localização), mancha HAND de
set/2023 e posições RTK dos pontos de campo, por tipo e por evento.
Figura 2: (a) profundidade observada × estimada; (b) erro por ponto com o terreno
LiDAR na posição do celular (e_d) e com o terreno RTK (e_s), marcas e limites
separados.
Figura 1 da versão atual (fig_manuscrito_1_mapa_erros.png): as duas anteriores
juntas, com o mapa em (a) e os painéis de erro em (b) e (c), cores por evento.

Uso:
  python pesquisas/validacao-campo-hand-santa-tereza/figuras_manuscrito.py \
      caminho/sumario_erros_hand.xlsx caminho/brazil-states.geojson
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LightSource
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, PathPatch, Polygon as MplPolygon
from matplotlib.path import Path as MplPath
from PIL import Image
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analise_erros_campo import DATA, FIG_DIR, RTK_ALIAS, ler_planilha  # noqa: E402

CM = 1 / 2.54
GAUGE_LONLAT = (-51.7322, -29.1781)  # estação 86472600
COR_EVENTO = {"2023-09": "#1a1a1a", "2023-11": "#d9531e", "2024-05": "#1b9e77"}
ROT_EVENTO = {"2023-09": "set/2023", "2023-11": "nov/2023", "2024-05": "mai/2024"}
plt.rcParams.update({
    "font.family": "Liberation Serif", "font.size": 8, "axes.linewidth": 0.6,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.major.size": 2.5,
    "ytick.major.size": 2.5, "legend.frameon": False, "savefig.dpi": 400,
    "mathtext.fontset": "stix",
})


def dms(v, eixo):
    s = "W" if eixo == "x" else "S"
    v = abs(v) + 1e-9
    g = int(v)
    mm = (v - g) * 60
    m = int(mm)
    sec = round((mm - m) * 60)
    if sec == 60:
        m, sec = m + 1, 0
    return f"{g}°{m:02d}'{sec:02d}\"{s}"


def polys(geom):
    return [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]


def desenha_poligonos(ax, geom, **kw):
    verts, codes = [], []
    for p in polys(geom):
        for ring in p:
            r = np.asarray(ring)[:, :2]
            verts.extend(r.tolist())
            codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(r) - 2) + [MplPath.CLOSEPOLY])
    ax.add_patch(PathPatch(MplPath(verts, codes), **kw))


def _desenha_mapa(ax, xlsx: Path, estados: Path):
    """Desenha relevo, mancha, pontos, escala, norte e inserto em ax; devolve os itens da legenda."""
    rtk, linhas = ler_planilha(xlsx)
    d = pd.read_csv(FIG_DIR.parent / "erros_campo_santa_tereza.csv")
    d = d[d.rtk_valido == True]  # noqa: E712
    ev = d.groupby("id").evento.first().to_dict()
    tipos = d.groupby("id").tipo.first().to_dict()
    to_geo = Transformer.from_crs("EPSG:31982", "EPSG:4674", always_xy=True)
    pts = []
    for pid, tipo in tipos.items():
        v = rtk[RTK_ALIAS.get(pid, pid)]
        lon, lat = to_geo.transform(v["E"], v["N"])
        pts.append((pid, tipo, ev[pid], lon, lat))
    lons = [p[3] for p in pts] + [GAUGE_LONLAT[0]]
    lats = [p[4] for p in pts] + [GAUGE_LONLAT[1]]
    pad = 0.0032
    W, E = min(lons) - pad, max(lons) + pad
    S, N = min(lats) - pad, max(lats) + pad
    lat0 = (S + N) / 2

    meta = json.loads((DATA / "santa_tereza_inundacao" / "mdt" / "altitude_terreno_lidar_10m.json").read_text())
    img = np.array(Image.open(DATA / "santa_tereza_inundacao" / "mdt" / meta["png"]))
    z = (img[..., 0].astype(float) * 256 + img[..., 1]) * meta["escala"]
    z[img[..., 3] == 0] = np.nan
    dlon = (meta["E"] - meta["W"]) / meta["cols"]
    dlat = (meta["N"] - meta["S"]) / meta["rows"]
    c0, c1 = int((W - meta["W"]) / dlon), int((E - meta["W"]) / dlon) + 1
    r0, r1 = int((meta["N"] - N) / dlat), int((meta["N"] - S) / dlat) + 1
    zc = z[r0:r1, c0:c1]
    zc = np.where(np.isnan(zc), np.nanmin(zc), zc)
    dx = dlon * 111320 * math.cos(math.radians(lat0))
    dy = dlat * 110574
    hs = LightSource(azdeg=315, altdeg=45).hillshade(zc, vert_exag=1.5, dx=dx, dy=dy)
    ext = [meta["W"] + c0 * dlon, meta["W"] + c1 * dlon, meta["N"] - r1 * dlat, meta["N"] - r0 * dlat]
    cont = json.loads((DATA / "santa_tereza_inundacao" / "contornos_mancha.json").read_text())
    geo = {round(f["properties"]["nivel_m"], 1): f["geometry"] for f in cont["features"]}

    ax.imshow(hs, extent=ext, cmap="gray", vmin=0.15, vmax=1.0, origin="upper", interpolation="bilinear")
    desenha_poligonos(ax, geo[22.0], facecolor="#6aa6d9", edgecolor="#2f6fa8", linewidth=0.4, alpha=0.55)
    desenha_poligonos(ax, geo[0.0], facecolor="#1f4e85", edgecolor="none", alpha=0.9)
    for pid, tipo, e, lon, lat in pts:
        mk = "^" if tipo == "marca" else "o"
        fc = COR_EVENTO[e] if tipo == "marca" else "white"
        ax.plot(lon, lat, marker=mk, ms=4.8 if tipo == "marca" else 4.3, mfc=fc, mec=COR_EVENTO[e],
                mew=0.6 if tipo == "marca" else 1.1, ls="none", zorder=5)
        if pid in {"V010", "V011", "H003", "H004", "H007"}:
            ax.annotate(pid, (lon, lat), xytext=(4, 3), textcoords="offset points", fontsize=6.5, zorder=6,
                        bbox=dict(boxstyle="square,pad=0.1", fc="white", ec="none", alpha=0.75))
    ax.plot(*GAUGE_LONLAT, marker="*", ms=8.5, mfc="#ffd23f", mec="black", mew=0.6, ls="none", zorder=6)
    h3 = [p for p in pts if p[0] == "H004"][0]
    ax.annotate("vale do afluente", (h3[3] - 0.0010, h3[4] - 0.0017), fontsize=6.5, style="italic",
                ha="center", color="#222222", zorder=6)
    ax.set_xlim(W, E)
    ax.set_ylim(S, N)
    ax.set_aspect(1 / math.cos(math.radians(lat0)))
    passo = 15 / 3600
    xt = np.arange(math.ceil(W / passo) * passo, E, passo)
    yt = np.arange(math.ceil(S / passo) * passo, N, passo)
    ax.set_xticks(xt[::2])
    ax.set_yticks(yt[::2])
    ax.set_xticklabels([dms(v, "x") for v in xt[::2]])
    ax.set_yticklabels([dms(v, "y") for v in yt[::2]], rotation=90, va="center")
    ax.tick_params(direction="in", top=True, right=True, labelsize=7)

    m_por_grau = 111320 * math.cos(math.radians(lat0))
    L = 500 / m_por_grau
    x0, y0 = W + 0.06 * (E - W), S + 0.035 * (N - S)
    hbar = 0.007 * (N - S)
    ax.add_patch(plt.Rectangle((x0, y0), L / 2, hbar, fc="black", ec="black", lw=0.5, zorder=7))
    ax.add_patch(plt.Rectangle((x0 + L / 2, y0), L / 2, hbar, fc="white", ec="black", lw=0.5, zorder=7))
    for frac, txt in ((0, "0"), (0.5, "250"), (1, "500 m")):
        ax.text(x0 + frac * L, y0 + 0.018 * (N - S), txt, ha="center", fontsize=6.5, zorder=7)
    xn, yn = W + 0.08 * (E - W), N - 0.12 * (N - S)
    ax.annotate("", xy=(xn, yn + 0.05 * (N - S)), xytext=(xn, yn), zorder=7,
                arrowprops=dict(arrowstyle="-|>", color="black", lw=0.8, mutation_scale=8))
    ax.text(xn, yn + 0.058 * (N - S), "N", ha="center", fontsize=8, fontweight="bold", zorder=7)

    # inserto de localização no canto inferior direito do mapa
    ai = ax.inset_axes([0.615, 0.685, 0.375, 0.305])
    br = json.loads(Path(estados).read_text())
    for f in br["features"]:
        nome = f["properties"].get("name") or ""
        rs = "Rio Grande do Sul" in nome
        for p in polys(f["geometry"]):
            ai.add_patch(MplPolygon(np.array(p[0]), closed=True, fc="#9e9e9e" if rs else "#f2f2f2",
                                    ec="#6b6b6b", lw=0.25))
    ai.plot(*GAUGE_LONLAT, marker="s", ms=3, mfc="#d62728", mec="black", mew=0.4)
    ai.set_xlim(-74.5, -34.0)
    ai.set_ylim(-34.5, 5.8)
    ai.set_aspect(1.0)
    ai.set_xticks([])
    ai.set_yticks([])
    ai.set_facecolor("white")
    ai.text(-56.5, -30.0, "RS", fontsize=5.5, ha="right")

    return [
        Line2D([], [], marker="^", ms=5, mfc="#555555", mec="#555555", ls="none", label="Marca de profundidade"),
        Line2D([], [], marker="o", ms=4.5, mfc="white", mec="#555555", mew=1.1, ls="none",
               label="Limite de inundação"),
    ] + [Line2D([], [], marker="s", ms=5, mfc=c, mec=c, ls="none", label=f"Evento {ROT_EVENTO[e]}")
         for e, c in COR_EVENTO.items()] + [
        Line2D([], [], marker="*", ms=8, mfc="#ffd23f", mec="black", ls="none", label="Estação 86472600"),
        Patch(fc="#6aa6d9", ec="#2f6fa8", alpha=0.55, label="Mancha HAND, set/2023"),
        Patch(fc="#1f4e85", label="Leito (HAND = 0)"),
    ]


def figura_mapa(xlsx: Path, estados: Path):
    fig = plt.figure(figsize=(16 * CM, 10.0 * CM))
    ax = fig.add_axes([0.075, 0.07, 0.52, 0.90])
    leg = _desenha_mapa(ax, xlsx, estados)
    fig.legend(handles=leg, loc="upper left", bbox_to_anchor=(0.635, 0.97), fontsize=7.5,
               handlelength=1.4, labelspacing=0.75)
    fig.text(0.637, 0.10, "Pontos nas posições RTK.\nRelevo sombreado: MDT LiDAR\nreamostrado a 10 m.\n"
             "Referencial: SIRGAS 2000.", fontsize=6.8, color="#333333", va="bottom")
    out = FIG_DIR / "fig_manuscrito_1_mapa.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def figura_erros():
    d = pd.read_csv(FIG_DIR.parent / "erros_campo_santa_tereza.csv")
    fig, (a, b) = plt.subplots(1, 2, figsize=(16 * CM, 7.4 * CM), gridspec_kw={"width_ratios": [1, 1.1]})

    marcas = d[d.tipo == "marca"]
    lim = 5.0
    a.fill_between([0, lim], [-0.5, lim - 0.5], [0.5, lim + 0.5], color="#e6e6e6", lw=0)
    a.plot([0, lim], [0, lim], color="black", lw=0.7)
    estilos = {"2023-09": dict(marker="o", mfc="black", mec="black"),
               "2023-11": dict(marker="s", mfc="white", mec="black"),
               "2024-05": dict(marker="^", mfc="white", mec="black")}
    rot = {"2023-09": "set/2023 (calibração)", "2023-11": "nov/2023", "2024-05": "mai/2024"}
    for ev, st in estilos.items():
        s = marcas[marcas.evento == ev]
        a.plot(s.lamina_obs_m, s.lamina_hand_m, ls="none", ms=4.5, mew=0.8, label=rot[ev], **st)
    for _, r in marcas.iterrows():
        if abs(r.erro_lamina_m) > 1:
            a.annotate(r.id, (r.lamina_obs_m, r.lamina_hand_m), textcoords="offset points",
                       xytext=(-6, 5) if r.erro_lamina_m > 0 else (-26, -3), fontsize=7)
    a.set_xlim(0, lim)
    a.set_ylim(0, lim)
    a.set_aspect("equal")
    a.set_xlabel("Profundidade observada (m)")
    a.set_ylabel("Profundidade estimada pelo HAND (m)")
    a.legend(loc="upper left", fontsize=7, handletextpad=0.3, borderaxespad=0.6)
    a.text(-0.2, 1.04, "(a)", transform=a.transAxes, fontsize=9, fontweight="bold")

    v = d[d.rtk_valido == True].copy()  # noqa: E712
    v["ord_tipo"] = (v.tipo == "limite").astype(int)
    v = v.sort_values(["ord_tipo", "erro_lamina_m"], ascending=[False, True]).reset_index(drop=True)
    y = np.arange(len(v))
    b.axvspan(-0.5, 0.5, color="#e6e6e6", lw=0, zorder=0)
    b.axvline(0, color="black", lw=0.6)
    for i, r in v.iterrows():
        mk = "^" if r.tipo == "marca" else "o"
        b.plot([r.erro_lamina_m, r.erro_cota_rtk_m], [i, i], color="#9e9e9e", lw=0.8, zorder=1)
        b.plot(r.erro_lamina_m, i, marker=mk, ms=4.3, mfc="white", mec="black", mew=0.8, zorder=2)
        b.plot(r.erro_cota_rtk_m, i, marker=mk, ms=4.3, mfc="black", mec="black", zorder=3)
    corte = int((v.tipo == "limite").sum()) - 0.5
    b.axhline(corte, color="black", lw=0.4, ls=(0, (3, 2)))
    b.text(3.3, corte - 0.6, "limites", ha="right", va="top", fontsize=7, style="italic")
    b.text(3.3, corte + 0.4, "marcas", ha="right", va="bottom", fontsize=7, style="italic")
    b.set_yticks(y)
    b.set_yticklabels([f"{r.id} ({r.evento[5:]}/{r.evento[2:4]})" for _, r in v.iterrows()], fontsize=6.5)
    b.set_xlabel("Erro (m); positivo = superestimativa")
    b.set_xlim(-3.8, 3.4)
    b.set_ylim(-0.8, len(v) - 0.2)
    leg = [Line2D([], [], marker="o", ms=4, mfc="white", mec="black", ls="none",
                  label="$e_d$ (celular + LiDAR)"),
           Line2D([], [], marker="o", ms=4, mfc="black", mec="black", ls="none",
                  label="$e_s$ (terreno RTK)")]
    b.legend(handles=leg, loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=2, fontsize=7,
             handletextpad=0.2, columnspacing=0.8, borderaxespad=0.2)
    b.text(-0.30, 1.04, "(b)", transform=b.transAxes, fontsize=9, fontweight="bold")
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.15, top=0.90, wspace=0.42)
    out = FIG_DIR / "fig_manuscrito_2_erros.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def figura_mapa_erros(xlsx: Path, estados: Path):
    """Figura composta: (a) mapa, (b) profundidade observada × estimada, (c) erro por ponto.

    As cores dos eventos são as mesmas nos três painéis, e a legenda do mapa vale para todos.
    """
    larg, alt = 17.0, 13.4
    fig = plt.figure(figsize=(larg * CM, alt * CM))

    def caixa(x0, y0, w, h):
        return [x0 / larg, y0 / alt, w / larg, h / alt]

    ax = fig.add_axes(caixa(0.95, 2.45, 7.6, 10.5))
    ax.set_anchor("NW")
    leg = _desenha_mapa(ax, xlsx, estados)
    leg[2].set_label("Evento set/2023 (calibração)")
    fig.canvas.draw()
    pos = ax.get_position()
    fig.legend(handles=leg, loc="upper left", bbox_to_anchor=(0.012, pos.y0 - 0.6 / alt),
               ncol=2, fontsize=6.8, handlelength=1.3, labelspacing=0.45, columnspacing=1.0,
               borderaxespad=0.0)
    ax.text(0.0, 1.012, "(a)", transform=ax.transAxes, fontsize=9, fontweight="bold", va="bottom")

    d = pd.read_csv(FIG_DIR.parent / "erros_campo_santa_tereza.csv")
    x_dir = pos.x1 * larg + 1.45  # borda esquerda dos rótulos de (c)
    larg_c = larg - x_dir - 1.0 - 0.15

    # (b) profundidade observada × estimada nas marcas, centrado sobre (c)
    a = fig.add_axes(caixa(x_dir + 1.0 + larg_c / 2 - 2.5, 7.95, 5.0, 5.0))
    marcas = d[d.tipo == "marca"]
    lim = 5.0
    a.fill_between([0, lim], [-0.5, lim - 0.5], [0.5, lim + 0.5], color="#e6e6e6", lw=0)
    a.plot([0, lim], [0, lim], color="black", lw=0.7)
    for ev, cor in COR_EVENTO.items():
        sub = marcas[marcas.evento == ev]
        a.plot(sub.lamina_obs_m, sub.lamina_hand_m, ls="none", marker="^", ms=4.8, mfc=cor, mec=cor, mew=0.6)
    for _, r in marcas.iterrows():
        if abs(r.erro_lamina_m) > 1:
            a.annotate(r.id, (r.lamina_obs_m, r.lamina_hand_m), textcoords="offset points",
                       xytext=(-25, -3), fontsize=6.8)
    a.set_xlim(0, lim)
    a.set_ylim(0, lim)
    a.set_aspect("equal")
    a.set_xlabel("Profundidade observada (m)")
    a.set_ylabel("Profundidade estimada (m)")
    a.tick_params(labelsize=7)
    a.text(-0.26, 1.012, "(b)", transform=a.transAxes, fontsize=9, fontweight="bold", va="bottom")

    # (c) erro por ponto: terreno do celular (e_d) e terreno RTK (e_s)
    b = fig.add_axes(caixa(x_dir + 1.0, 0.95, larg_c, 5.75))
    v = d[d.rtk_valido == True].copy()  # noqa: E712
    v["ord_tipo"] = (v.tipo == "limite").astype(int)
    v = v.sort_values(["ord_tipo", "erro_lamina_m"], ascending=[False, True]).reset_index(drop=True)
    b.axvspan(-0.5, 0.5, color="#e6e6e6", lw=0, zorder=0)
    b.axvline(0, color="black", lw=0.6)
    for i, r in v.iterrows():
        mk = "^" if r.tipo == "marca" else "o"
        cor = COR_EVENTO[r.evento]
        ms = 4.4 if r.tipo == "marca" else 3.9
        b.plot([r.erro_lamina_m, r.erro_cota_rtk_m], [i, i], color="#a6a6a6", lw=0.8, zorder=1)
        b.plot(r.erro_lamina_m, i, marker=mk, ms=ms, mfc="white", mec=cor, mew=0.9, zorder=2)
        b.plot(r.erro_cota_rtk_m, i, marker=mk, ms=ms, mfc=cor, mec=cor, mew=0.6, zorder=3)
    corte = int((v.tipo == "limite").sum()) - 0.5
    b.axhline(corte, color="black", lw=0.4, ls=(0, (3, 2)))
    b.text(3.3, corte - 0.45, "limites", ha="right", va="top", fontsize=6.8, style="italic")
    b.text(3.3, corte + 0.35, "marcas", ha="right", va="bottom", fontsize=6.8, style="italic")
    b.set_yticks(np.arange(len(v)))
    b.set_yticklabels(v.id, fontsize=6.3)
    b.tick_params(axis="x", labelsize=7)
    b.tick_params(axis="y", length=1.5, pad=1.5)
    b.set_xlabel("Erro vertical (m); positivo = superestimativa")
    b.set_xlim(-3.8, 3.4)
    b.set_ylim(-0.7, len(v) - 0.3)
    leg_c = [Line2D([], [], marker="o", ms=3.9, mfc="white", mec="black", mew=0.9, ls="none",
                    label="celular + LiDAR ($e_d$)"),
             Line2D([], [], marker="o", ms=3.9, mfc="black", mec="black", ls="none",
                    label="RTK ($e_s$)")]
    b.legend(handles=leg_c, loc="lower left", fontsize=6.6, handletextpad=0.2, borderaxespad=0.3,
             labelspacing=0.3)
    b.text(-0.215, 1.012, "(c)", transform=b.transAxes, fontsize=9, fontweight="bold", va="bottom")

    out = FIG_DIR / "fig_manuscrito_1_mapa_erros.png"
    fig.savefig(out)
    plt.close(fig)
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    print(figura_mapa(Path(sys.argv[1]), Path(sys.argv[2])))
    print(figura_erros())
    print(figura_mapa_erros(Path(sys.argv[1]), Path(sys.argv[2])))
