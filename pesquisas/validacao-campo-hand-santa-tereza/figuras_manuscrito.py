#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Figuras do manuscrito (SBSR 2027) em padrão de publicação.

Figura 1: localização da área de estudo, mancha HAND de set/2023 e pontos de campo.
Figura 2: (a) lâmina observada × estimada; (b) erro vertical com celular × RTK.

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
plt.rcParams.update({
    "font.family": "Liberation Serif", "font.size": 8, "axes.linewidth": 0.6,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.major.size": 2.5,
    "ytick.major.size": 2.5, "legend.frameon": False, "savefig.dpi": 400,
})


def dms(v, eixo):
    s = "W" if eixo == "x" else "S"
    v = abs(v)
    g = int(v)
    m = (v - g) * 60
    return f"{g}°{m:05.2f}'{s}".replace(".", ",")


def polys(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    return geom["coordinates"]


def desenha_poligonos(ax, geom, **kw):
    verts, codes = [], []
    for p in polys(geom):
        for ring in p:
            r = np.asarray(ring)[:, :2]
            verts.extend(r.tolist())
            codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(r) - 2) + [MplPath.CLOSEPOLY])
    ax.add_patch(PathPatch(MplPath(verts, codes), **kw))


def figura_mapa(xlsx: Path, estados: Path):
    rtk, linhas = ler_planilha(xlsx)
    tipos = {p["id"]: ("limite" if p["altura"] == 0 else "marca") for p in linhas if not p["obs"]}
    to_geo = Transformer.from_crs("EPSG:31982", "EPSG:4674", always_xy=True)
    pts = []
    for pid, tipo in tipos.items():
        v = rtk.get(RTK_ALIAS.get(pid, pid))
        if v is None:
            continue
        lon, lat = to_geo.transform(v["E"], v["N"])
        pts.append((pid, tipo, lon, lat))
    lons = [p[2] for p in pts] + [GAUGE_LONLAT[0]]
    lats = [p[3] for p in pts] + [GAUGE_LONLAT[1]]
    pad = 0.0035
    W, E = min(lons) - pad, max(lons) + pad
    S, N = min(lats) - pad, max(lats) + pad
    lat0 = (S + N) / 2
    asp = 1 / math.cos(math.radians(lat0))

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

    fig = plt.figure(figsize=(16 * CM, 10.2 * CM))
    ax = fig.add_axes([0.06, 0.08, 0.50, 0.88])
    ax.imshow(hs, extent=ext, cmap="gray", vmin=0.15, vmax=1.0, origin="upper", interpolation="bilinear")
    desenha_poligonos(ax, geo[22.0], facecolor="#6aa6d9", edgecolor="#2f6fa8", linewidth=0.4, alpha=0.55)
    desenha_poligonos(ax, geo[0.0], facecolor="#1f4e85", edgecolor="none", alpha=0.9)
    for pid, tipo, lon, lat in pts:
        if tipo == "marca":
            ax.plot(lon, lat, marker="^", ms=4.6, mfc="black", mec="white", mew=0.5, ls="none", zorder=5)
        else:
            ax.plot(lon, lat, marker="o", ms=4.2, mfc="white", mec="black", mew=0.8, ls="none", zorder=5)
        if pid in {"V010", "V011", "H003", "H004", "H007"}:
            ax.annotate(pid, (lon, lat), xytext=(4, 2), textcoords="offset points", fontsize=6.5,
                        zorder=6, bbox=dict(boxstyle="square,pad=0.1", fc="white", ec="none", alpha=0.7))
    ax.plot(*GAUGE_LONLAT, marker="*", ms=8, mfc="#d62728", mec="black", mew=0.5, ls="none", zorder=6)
    ax.set_xlim(W, E)
    ax.set_ylim(S, N)
    ax.set_aspect(asp)
    passo = 0.25 / 60
    xt = np.arange(math.ceil(W / passo) * passo, E, passo)
    yt = np.arange(math.ceil(S / passo) * passo, N, passo)
    ax.set_xticks(xt)
    ax.set_yticks(yt)
    ax.set_xticklabels([dms(v, "x") for v in xt])
    ax.set_yticklabels([dms(v, "y") for v in yt], rotation=90, va="center")
    ax.tick_params(direction="in", top=True, right=True)
    # barra de escala (500 m) e norte
    m_por_grau = 111320 * math.cos(math.radians(lat0))
    L = 500 / m_por_grau
    x0, y0 = W + 0.06 * (E - W), S + 0.04 * (N - S)
    ax.add_patch(plt.Rectangle((x0, y0), L / 2, 0.006 * (N - S), fc="black", ec="black", lw=0.5, zorder=7))
    ax.add_patch(plt.Rectangle((x0 + L / 2, y0), L / 2, 0.006 * (N - S), fc="white", ec="black", lw=0.5, zorder=7))
    for frac, txt in ((0, "0"), (0.5, "250"), (1, "500 m")):
        ax.text(x0 + frac * L, y0 + 0.016 * (N - S), txt, ha="center", fontsize=6.5, zorder=7)
    xn, yn = E - 0.08 * (E - W), N - 0.10 * (N - S)
    ax.annotate("", xy=(xn, yn + 0.05 * (N - S)), xytext=(xn, yn), zorder=7,
                arrowprops=dict(arrowstyle="-|>", color="black", lw=0.8, mutation_scale=8))
    ax.text(xn, yn + 0.058 * (N - S), "N", ha="center", fontsize=8, fontweight="bold", zorder=7)
    ax.text(0.015, 0.985, "(b)", transform=ax.transAxes, va="top", fontsize=9, fontweight="bold",
            bbox=dict(fc="white", ec="none", pad=1.0))

    # inset: Brasil e RS
    ai = fig.add_axes([0.60, 0.50, 0.38, 0.46])
    br = json.loads(Path(estados).read_text())
    for f in br["features"]:
        nome = (f["properties"].get("name") or f["properties"].get("sigla") or "")
        rs = "Rio Grande do Sul" in nome
        for p in polys(f["geometry"]):
            ai.add_patch(MplPolygon(np.array(p[0]), closed=True, fc="#9e9e9e" if rs else "#efefef",
                                    ec="#6b6b6b", lw=0.25))
    ai.plot(*GAUGE_LONLAT, marker="s", ms=3.5, mfc="#d62728", mec="black", mew=0.4)
    ai.set_xlim(-74.5, -34.0)
    ai.set_ylim(-34.5, 5.8)
    ai.set_aspect(1.0)
    ai.set_xticks([])
    ai.set_yticks([])
    ai.text(0.03, 0.97, "(a)", transform=ai.transAxes, va="top", fontsize=9, fontweight="bold")
    ai.text(-55.6, -30.2, "RS", fontsize=6.5, ha="right")

    leg = [
        Line2D([], [], marker="^", ms=5, mfc="black", mec="white", ls="none", label="Marca de profundidade"),
        Line2D([], [], marker="o", ms=4.5, mfc="white", mec="black", ls="none", label="Limite de inundação"),
        Line2D([], [], marker="*", ms=8, mfc="#d62728", mec="black", ls="none", label="Estação 86472600"),
        Patch(fc="#6aa6d9", ec="#2f6fa8", alpha=0.55, label="Mancha HAND (set/2023)"),
        Patch(fc="#1f4e85", label="Rio Taquari-Antas (HAND = 0)"),
    ]
    fig.legend(handles=leg, loc="upper left", bbox_to_anchor=(0.60, 0.44), fontsize=7.5,
               handlelength=1.4, labelspacing=0.7)
    fig.text(0.60, 0.07, "Relevo sombreado: LiDAR 10 m\nSIRGAS 2000, coordenadas geográficas",
             fontsize=6.5, color="#444444")
    out = FIG_DIR / "fig_manuscrito_1_mapa.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def figura_erros():
    d = pd.read_csv(FIG_DIR.parent / "erros_campo_santa_tereza.csv")
    fig, (a, b) = plt.subplots(1, 2, figsize=(16 * CM, 7.2 * CM), gridspec_kw={"width_ratios": [1, 1.05]})

    marcas = d[d.tipo == "marca"]
    lim = 5.0
    a.fill_between([0, lim], [-0.5, lim - 0.5], [0.5, lim + 0.5], color="#e6e6e6", lw=0)
    a.plot([0, lim], [0, lim], color="black", lw=0.7)
    estilos = {"2023-09": dict(marker="o", mfc="black", mec="black", label="set/2023 (calibração)"),
               "2023-11": dict(marker="s", mfc="white", mec="black", label="nov/2023 (validação)"),
               "2024-05": dict(marker="^", mfc="white", mec="black", label="mai/2024 (validação)")}
    for ev, st in estilos.items():
        s = marcas[marcas.evento == ev]
        a.plot(s.lamina_obs_m, s.lamina_hand_m, ls="none", ms=4.5, mew=0.8, **st)
    for _, r in marcas.iterrows():
        if abs(r.erro_lamina_m) > 1:
            a.annotate(r.id, (r.lamina_obs_m, r.lamina_hand_m), xytext=(5, -3) if r.erro_lamina_m > 0 else (-24, -2),
                       textcoords="offset points", fontsize=7)
    a.set_xlim(0, lim)
    a.set_ylim(0, lim)
    a.set_aspect("equal")
    a.set_xlabel("Lâmina observada (m)")
    a.set_ylabel("Lâmina estimada pelo HAND (m)")
    a.legend(loc="upper left", fontsize=7, handletextpad=0.3)
    a.text(lim - 0.08, 0.15, "1:1 ± 0,5 m", ha="right", fontsize=7)
    a.text(-0.2, 1.06, "(a)", transform=a.transAxes, fontsize=9, fontweight="bold")

    v = d[d.rtk_valido == True].copy()  # noqa: E712
    v = v.sort_values("erro_lamina_m").reset_index(drop=True)
    y = np.arange(len(v))
    for i, r in v.iterrows():
        b.plot([r.erro_lamina_m, r.erro_cota_rtk_m], [i, i], color="#9e9e9e", lw=0.8, zorder=1)
    b.plot(v.erro_lamina_m, y, ls="none", marker="o", ms=4, mfc="white", mec="black", mew=0.8, zorder=2,
           label="Celular + LiDAR (lâmina)")
    b.plot(v.erro_cota_rtk_m, y, ls="none", marker="o", ms=4, mfc="black", mec="black", zorder=3,
           label="RTK (cota da cheia)")
    b.axvline(0, color="black", lw=0.6)
    b.axvspan(-0.5, 0.5, color="#e6e6e6", lw=0, zorder=0)
    b.set_yticks(y)
    b.set_yticklabels([f"{r.id} ({r.evento[5:]}/{r.evento[2:4]})" for _, r in v.iterrows()], fontsize=6.5)
    b.set_xlabel("Erro vertical (m)")
    b.set_xlim(-3.8, 3.4)
    b.set_ylim(-0.8, len(v) - 0.2)
    b.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=2, fontsize=7, handletextpad=0.2, columnspacing=1.0, borderaxespad=0.2)
    b.text(-0.28, 1.06, "(b)", transform=b.transAxes, fontsize=9, fontweight="bold")
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.15, top=0.90, wspace=0.42)
    out = FIG_DIR / "fig_manuscrito_2_erros.png"
    fig.savefig(out)
    plt.close(fig)
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    print(figura_mapa(Path(sys.argv[1]), Path(sys.argv[2])))
    print(figura_erros())
