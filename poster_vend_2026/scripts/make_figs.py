"""Recalcula métricas dos modelos ALT ao vivo (Santa Tereza) e gera figuras do pôster."""
import json
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import scipy.io as sio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parents[1] / "fig"  # mapa.png vem da Figura 1 do resumo
OUT.mkdir(exist_ok=True)

NAVY, ORANGE, BLUE, GRAY, INK, MUTED = "#2A378D", "#D9661F", "#2E86C1", "#B8C2CC", "#1F2633", "#5B6573"
plt.rcParams.update({
    "font.family": "Liberation Sans", "font.size": 15, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#E3E7EC", "grid.linewidth": 0.8, "axes.titleweight": "bold",
    "axes.titlesize": 17, "axes.titlecolor": INK, "legend.frameon": False,
})


def prctile(x, p):
    """Percentil no mesmo critério do prctile do MATLAB."""
    x = np.sort(np.asarray(x, float))
    pos = 100 * (np.arange(1, len(x) + 1) - 0.5) / len(x)
    return float(np.interp(p, pos, x))


def metricas(obs, pred, cur):
    obs, pred, cur = (np.asarray(a, float).ravel() for a in (obs, pred, cur))
    e = pred - obs
    return {
        "n": int(len(obs)),
        "NSE": float(1 - np.sum(e ** 2) / np.sum((obs - obs.mean()) ** 2)),
        "PME": float(1 - np.sum(e ** 2) / np.sum((obs - cur) ** 2)),
        "EAM": float(np.mean(np.abs(e))),
        "E95": prctile(np.abs(e), 95),
        "EAM_persistencia": float(np.mean(np.abs(obs - cur))),
        "pico_obs": float(obs.max()),
    }


def carregar_v7(path):
    m = sio.loadmat(path, squeeze_me=True)
    X = np.asarray(m["X"]).ravel()
    return {
        "X": X, "obs": m["Ttot1"], "pred": m["Tctot1"], "cur": m["ATUAL_TOT"],
        "n_inputs": int(m["input"]), "nh": int(m["nh"]), "nit": int(m["nit"]), "cic": int(m["Cic"]),
    }


def carregar_v73(path):
    h = h5py.File(path)
    cur = h["Ptot"][()][:, 0]
    return {
        "X": h["X"][()].ravel(), "obs": cur + h["Ttot"][()].ravel(), "pred": cur + h["Tctot"][()].ravel(), "cur": cur,
        "n_inputs": int(h["input"][()].ravel()[0]), "nh": int(h["nh"][()].ravel()[0]),
        "nit": int(h["nit"][()].ravel()[0]), "cic": int(h["Cic"][()].ravel()[0]),
    }


MODELOS = {
    "2h": ("009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21", carregar_v7(REPO / "previne/assets/mat/009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21.mat")),
    "4h": ("4H_ALT__V01_R00_BASELINE_nh52_nit10_cic100000", carregar_v7(REPO / "assets/mat/4H_ALT__V01_R00_BASELINE_nh52_nit10_cic100000.mat")),
    "8h": ("STZ_H8_ALT_V001_31IN_63NH", carregar_v73(REPO / "previne/assets/mat/RNAPREV__SANTA_TEREZA__08h__ALT__V001__31inputs_63hiddens_20260821.mat")),
}
PART = {1: "treino", 2: "validacao", 3: "teste"}

resumo = {}
for hz, (mid, d) in MODELOS.items():
    r = {"modelo": mid, "n_inputs": d["n_inputs"], "neuronios": d["nh"], "inicializacoes": d["nit"], "ciclos": d["cic"]}
    for code, nome in PART.items():
        s = d["X"] == code
        r[nome] = metricas(d["obs"][s], d["pred"][s], d["cur"][s])
    r["geral"] = metricas(d["obs"], d["pred"], d["cur"])
    resumo[hz] = r

# Operação ao vivo (previsões auditadas contra a telemetria)
hist = json.load(open(REPO / "historico_previsoes_ao_vivo.json"))["registros"]
ao_vivo = {}
for hz, (mid, _) in MODELOS.items():
    recs = [x for x in hist if x["modelo"] == mid and x.get("status_auditoria") == "conferido" and x.get("observado_cm") is not None]
    recs.sort(key=lambda x: x["hora_alvo"])
    o = np.array([x["observado_cm"] for x in recs], float)
    p = np.array([x["nivel_previsto_cm"] for x in recs], float)
    c = np.array([x["nivel_modelo_cm"] for x in recs], float)
    m = metricas(o, p, c)
    m.update(inicio=recs[0]["hora_modelo"], fim=recs[-1]["hora_modelo"])
    ao_vivo[hz] = (m, recs)
resumo["ao_vivo"] = {hz: v[0] for hz, v in ao_vivo.items()}
json.dump(resumo, open(OUT / "metricas.json", "w"), indent=1, ensure_ascii=False)
for hz in ("2h", "4h", "8h"):
    t = resumo[hz]["teste"]
    print(hz, resumo[hz]["n_inputs"], resumo[hz]["neuronios"], {k: round(v, 3) for k, v in t.items()})
print("ao vivo", {hz: {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()} for hz, m in resumo["ao_vivo"].items()})

# ---------- Figura: dispersão previsto x observado (3 painéis) ----------
fig, axs = plt.subplots(1, 3, figsize=(15.6, 5.9), constrained_layout=True)
estilos = [(1, "Treino", GRAY, 10), (2, "Validação", BLUE, 14), (3, "Teste", ORANGE, 18)]
for ax, hz in zip(axs, ("2h", "4h", "8h")):
    d = MODELOS[hz][1]
    lim = max(d["obs"].max(), d["pred"].max()) * 1.04 / 100
    ax.plot([0, lim], [0, lim], color=MUTED, lw=1.4, ls="--", zorder=1)
    for code, nome, cor, sz in estilos:
        s = d["X"] == code
        ax.scatter(d["obs"][s] / 100, d["pred"][s] / 100, s=sz, color=cor, edgecolor="white", linewidth=0.4, label=nome, zorder=2 + code)
    t = resumo[hz]["teste"]
    ax.set_title(f"ALT {hz}\nNSE {t['NSE']:.3f} · PME {t['PME']:.3f} · EAM {t['EAM']:.1f} cm".replace(".", ","), loc="left", fontsize=17, linespacing=1.3)
    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.set_xlabel("Nível observado (m)")
axs[0].set_ylabel("Nível previsto (m)")
axs[0].legend(loc="upper left", markerscale=1.6, handletextpad=0.2)
fig.savefig(OUT / "dispersao.png", dpi=300)
plt.close(fig)

# ---------- Figura: série do conjunto de teste do 8h (cheia de jul/2023) ----------
d = MODELOS["8h"][1]
s = np.where(d["X"] == 3)[0]
horas = np.arange(len(s))
fig, ax = plt.subplots(figsize=(8.6, 4.15), constrained_layout=True)
ax.plot(horas, d["obs"][s] / 100, color=NAVY, lw=2.6, label="Observado")
ax.plot(horas, d["pred"][s] / 100, color=ORANGE, lw=2.2, label="RNA ALT 8h")
ax.plot(horas, d["cur"][s] / 100, color=MUTED, lw=1.6, ls=(0, (4, 3)), label="Persistência")
ax.set_xlabel("Horas desde o início do evento de teste")
ax.set_ylabel("Nível (m)")
ax.legend(loc="upper right")
ax.set_xlim(0, horas[-1])
ax.set_ylim(0, None)
fig.savefig(OUT / "teste_8h.png", dpi=300)
plt.close(fig)

# ---------- Figura: operação em tempo real (2h) ----------
m2, recs = ao_vivo["2h"]
ta = [datetime.fromisoformat(x["hora_alvo"]) for x in recs]
o = np.array([x["observado_cm"] for x in recs]) / 100
p = np.array([x["nivel_previsto_cm"] for x in recs]) / 100
fig, ax = plt.subplots(figsize=(8.6, 4.15), constrained_layout=True)
ax.plot(ta, o, color=NAVY, lw=2.6, label="Observado (telemetria)")
ax.plot(ta, p, color=ORANGE, lw=0, marker="o", ms=4.2, mec="white", mew=0.4, label="Previsão ao vivo 2h")
ax.set_ylabel("Nível (m)")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
ax.set_xlabel("Data (2026)")
ax.legend(loc="upper right")
ax.set_ylim(0, None)
fig.savefig(OUT / "ao_vivo_2h.png", dpi=300)
plt.close(fig)
print("figuras ok")

# ---------- Figura: dispersão empilhada (3 linhas) com PME, EAM e E95 no gráfico ----------
fig, axs = plt.subplots(3, 1, figsize=(260 / 25.4, 300 / 25.4), constrained_layout=True)
for i, (ax, hz) in enumerate(zip(axs, ("2h", "4h", "8h"))):
    d = MODELOS[hz][1]
    lim = max(d["obs"].max(), d["pred"].max()) * 1.04 / 100
    ax.plot([0, lim], [0, lim], color=MUTED, lw=1.4, ls="--", zorder=1)
    for code, nome, cor, sz in estilos:
        s = d["X"] == code
        ax.scatter(d["obs"][s] / 100, d["pred"][s] / 100, s=sz, color=cor, edgecolor="white", linewidth=0.4, label=nome, zorder=2 + code)
    t = resumo[hz]["teste"]
    ax.set_title(f"ALT {hz}", loc="left")
    txt = (f"NSE* = {t['NSE']:.3f}\nPME* = {t['PME']:.3f}\nEAM* = {t['EAM']:.1f} cm\nE95* = {t['E95']:.0f} cm").replace(".", ",")
    ax.text(0.03, 0.95, txt, transform=ax.transAxes, va="top", ha="left", fontsize=15, color=INK, linespacing=1.35,
            bbox=dict(boxstyle="round,pad=0.5", fc="white", ec=GRAY, lw=1))
    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.set_ylabel("Previsto (m)")
    if i == 2:
        ax.set_xlabel("Nível observado (m)")
axs[0].legend(loc="lower right", markerscale=1.6, handletextpad=0.2)
fig.savefig(OUT / "dispersao_vertical.png", dpi=300)
plt.close(fig)
print("dispersao vertical ok")
