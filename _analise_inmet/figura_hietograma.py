"""Hietograma da média da bacia, v3 x v3b, em duas janelas (maior deslocamento do centro de massa e maior evento)."""
import json
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

AQUI = Path(__file__).resolve().parent


def serie(pasta, sim):
    d = json.loads((AQUI / pasta / f"{sim}.json").read_text(encoding="utf-8"))
    return [datetime.fromisoformat(h) for h in d["horas"]], d["chuva_media_bacia_mm"]


def main():
    fig, axs = plt.subplots(2, 1, figsize=(11, 6.5))
    for ax, (sim, ini, fim) in zip(axs, (("X20181028", "2018-10-28 12:00", "2018-11-02 00:00"),
                                          ("S2024_05", "2024-04-29 00:00", "2024-05-03 12:00"))):
        t, a = serie("forc_bug", sim)
        _, b = serie("forc_corrigido", sim)
        i0, i1 = t.index(datetime.fromisoformat(ini)), t.index(datetime.fromisoformat(fim))
        ax.step(t[i0:i1], a[i0:i1], where="post", color="tab:red", lw=1.2, label="v3 (hora INMET com bug)")
        ax.step(t[i0:i1], b[i0:i1], where="post", color="tab:blue", lw=1.2, label="v3b (corrigido)")
        ax.set_title(f"{sim}: chuva média da bacia (mm/h, hora de Brasília)", fontsize=10)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(AQUI / "hietograma_v3_v3b.png", dpi=110)


if __name__ == "__main__":
    main()
