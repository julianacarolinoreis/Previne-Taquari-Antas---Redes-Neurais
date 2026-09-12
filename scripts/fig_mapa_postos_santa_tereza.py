#!/usr/bin/env python3
"""Figura 1 — postos com coordenada conhecida na telemetria SGB/ANA do projeto.

Não desenha área de drenagem: o campo AreaDrenagem do HidroWeb/ANA não foi
recuperado nesta versão (HidroInventario HTTP 500; HidroWebService HTTP 401).
Distâncias no mapa são geodésicas (haversine), não tempo de viagem.
"""

from __future__ import annotations

from pathlib import Path

try:
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import FancyArrowPatch, Rectangle
except ImportError:  # pragma: no cover - ambiente sem matplotlib
    plt = None

ROOT = Path(__file__).resolve().parents[1]
OUTS = [
    ROOT / "pesquisas" / "figuras" / "figura1_postos_santa_tereza.png",
    Path("/opt/cursor/artifacts/figura1_postos_santa_tereza.png"),
]

# Coordenadas da telemetria publicada em previsao_ao_vivo.json (fonte SGB/ANA).
POSTOS = [
    {
        "code": "86472600",
        "name": "Santa Tereza",
        "lat": -29.1781,
        "lon": -51.7322,
        "kind": "alvo",
        "dx": 0.04,
        "dy": -0.06,
    },
    {
        "code": "86472000",
        "name": "Linha José Júlio\n(Antas montante)",
        "lat": -29.0978,
        "lon": -51.6997,
        "kind": "montante",
        "dx": 0.05,
        "dy": 0.04,
    },
    {
        "code": "86448000",
        "name": "Veranópolis",
        "lat": -29.0292,
        "lon": -51.5219,
        "kind": "montante",
        "dx": 0.04,
        "dy": 0.03,
    },
    {
        "code": "86125130",
        "name": "Ituim",
        "lat": -28.5919,
        "lon": -51.3247,
        "kind": "montante",
        "dx": 0.02,
        "dy": 0.04,
    },
]


def _km_per_deg(lat: float) -> tuple[float, float]:
    import math

    km_lat = 111.32
    km_lon = 111.32 * math.cos(math.radians(lat))
    return km_lat, km_lon


def build(dest: Path | None = None) -> Path:
    dest = dest or OUTS[0]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if plt is None:
        if dest.exists():
            return dest
        raise RuntimeError("matplotlib é necessário para gerar a Figura 1")

    fig, ax = plt.subplots(figsize=(7.2, 6.4), dpi=200)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f7f4ec")

    styles = {
        "alvo": dict(c="#7a1f1f", marker="*", s=220, z=5, lw=0.6, edge="#2b1810"),
        "montante": dict(c="#1f4e79", marker="o", s=70, z=4, lw=0.6, edge="#102030"),
    }
    for p in POSTOS:
        st = styles[p["kind"]]
        ax.scatter(
            p["lon"],
            p["lat"],
            s=st["s"],
            c=st["c"],
            marker=st["marker"],
            zorder=st["z"],
            edgecolors=st["edge"],
            linewidths=st["lw"],
        )
        ax.annotate(
            f"{p['name']}\n{p['code']}",
            xy=(p["lon"], p["lat"]),
            xytext=(p["lon"] + p["dx"], p["lat"] + p["dy"]),
            fontsize=7.5,
            color="#222",
            ha="left",
            va="center",
            arrowprops=dict(arrowstyle="-", color="#666", lw=0.5),
        )

    # Esquema de fluxo Antas → Taquari (apenas orientação, não hidrografia oficial).
    ax.annotate(
        "",
        xy=(-51.70, -29.16),
        xytext=(-51.36, -28.64),
        arrowprops=dict(arrowstyle="-|>", color="#6a8aaa", lw=1.4, connectionstyle="arc3,rad=0.12"),
    )
    ax.text(-51.46, -28.88, "Antas\n(sentido jusante)", fontsize=7, color="#3a5a72", ha="center")

    lats = [p["lat"] for p in POSTOS]
    lons = [p["lon"] for p in POSTOS]
    ax.set_xlim(min(lons) - 0.18, max(lons) + 0.22)
    ax.set_ylim(min(lats) - 0.16, max(lats) + 0.14)
    ax.set_xlabel("Longitude (°W)", fontsize=9)
    ax.set_ylabel("Latitude (°S)", fontsize=9)
    ax.tick_params(labelsize=8)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, ls=":", lw=0.4, color="#c8c4b8")

    mid_lat = sum(lats) / len(lats)
    km_lat, km_lon = _km_per_deg(mid_lat)
    x0, y0 = ax.get_xlim()[0] + 0.06, ax.get_ylim()[0] + 0.05
    bar_km = 20.0
    bar_deg = bar_km / km_lon
    ax.add_patch(Rectangle((x0, y0 - 0.012), bar_deg, 0.008, facecolor="#222", edgecolor="none"))
    ax.text(x0 + bar_deg / 2, y0 + 0.018, "20 km", ha="center", va="bottom", fontsize=7.5)

    north = FancyArrowPatch(
        (ax.get_xlim()[1] - 0.08, ax.get_ylim()[1] - 0.14),
        (ax.get_xlim()[1] - 0.08, ax.get_ylim()[1] - 0.04),
        arrowstyle="-|>",
        mutation_scale=12,
        color="#222",
        lw=1.2,
    )
    ax.add_patch(north)
    ax.text(ax.get_xlim()[1] - 0.08, ax.get_ylim()[1] - 0.02, "N", ha="center", fontsize=8, fontweight="bold")

    legend = [
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#7a1f1f", markersize=14, label="Estação-alvo"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#1f4e79", markersize=8, label="Posto de montante (com coordenada)"),
    ]
    ax.legend(handles=legend, loc="lower right", fontsize=7.5, frameon=True, fancybox=False, edgecolor="#ccc")
    ax.set_title(
        "Postos fluviométricos com coordenada na telemetria SGB/ANA\n"
        "usados nas combinações principais — Santa Tereza, RS",
        fontsize=10,
        pad=8,
    )
    fig.text(
        0.5,
        0.01,
        "Carreiro (86507000), 86298000 e 86430900 entram no Quadro 1, mas sem latitude/longitude na telemetria do projeto.\n"
        "A área afluente ao 86472600 não foi recuperada no HidroWeb nesta versão. Distâncias no mapa são geodésicas.",
        ha="center",
        va="bottom",
        fontsize=6.5,
        color="#444",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(dest, dpi=200)
    plt.close(fig)
    for extra in OUTS:
        if extra.resolve() != dest.resolve():
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_bytes(dest.read_bytes())
    return dest


if __name__ == "__main__":
    path = build()
    print(path)
