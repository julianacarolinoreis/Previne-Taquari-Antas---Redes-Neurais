"""Efeito da correção do INMET na chuva por sub-bacia: forcamento_v3 (= forc_bug, provado idêntico) x forc_corrigido.

Por janela: total médio da bacia, razão do total por sub-bacia (p10/p50/p90), correlação horária da média da bacia,
pico horário da média da bacia, deslocamento do centro de massa do hietograma (h), fração de sub-bacia x hora alterada,
peso IDW médio dos postos INMET. Também a defasagem detectada pelo próprio forcamento_v3 (lag_suspeito) nos postos INMET.
Saída: efeito_chuva.json e efeito_chuva.md
"""
import json
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer

AQUI = Path(__file__).resolve().parent
GEO = json.loads(Path(r"D:\PREVINE\hec_calibracao_20261005\geometria_subbacias.json").read_text(encoding="utf-8"))
SUBS = [g["sub_id"] for g in GEO]
AREA = np.array([g["area_km2"] for g in GEO])
TR = Transformer.from_crs(4326, 31982, always_xy=True)


def carregar(pasta, sim):
    d = json.loads((AQUI / pasta / f"{sim}.json").read_text(encoding="utf-8"))
    return d, np.array([d["chuva_por_subbacia"][s] for s in SUBS], dtype=float).T


def peso_inmet(d, sim):
    """Fração média (horas x área) do peso IDW que vem de postos INMET."""
    led = {r["posto"]: r for r in json.loads((AQUI / "forc_corrigido" / f"{sim}_postos.json").read_text(encoding="utf-8"))}
    codes = d["postos_usados"]
    sx, sy = TR.transform([led[c]["lon"] for c in codes], [led[c]["lat"] for c in codes])
    px, py = TR.transform([g["lon"] for g in GEO], [g["lat"] for g in GEO])
    w = 1 / np.maximum(np.hypot(np.array(px)[:, None] - sx, np.array(py)[:, None] - sy), 1.0) ** 2
    ins = np.array([c.startswith("INMET_") for c in codes])
    f = w[:, ins].sum(1) / w.sum(1)
    return float(f @ AREA / AREA.sum()), float(f.max())


def centro(m):
    t = np.arange(len(m))
    return float((t * m).sum() / m.sum()) if m.sum() > 0 else float("nan")


def main():
    out = {}
    sims = sorted(p.stem for p in (AQUI / "forc_bug").glob("*.json") if not p.stem.endswith("_postos") and not p.stem.startswith("comp"))
    for sim in sims:
        d3, A = carregar("forc_bug", sim)
        db, B = carregar("forc_corrigido", sim)
        ma, mb = A @ AREA / AREA.sum(), B @ AREA / AREA.sum()
        ta, tb = A.sum(0), B.sum(0)
        rz = (tb + 0.5) / (ta + 0.5)
        led_b = {r["posto"]: r for r in json.loads((AQUI / "forc_bug" / f"{sim}_postos.json").read_text(encoding="utf-8"))}
        led_c = {r["posto"]: r for r in json.loads((AQUI / "forc_corrigido" / f"{sim}_postos.json").read_text(encoding="utf-8"))}
        lag = {c: (led_b[c].get("lag_suspeito"), led_c[c].get("lag_suspeito")) for c in led_c if c.startswith("INMET_")
               and (led_b[c].get("lag_suspeito") or led_c[c].get("lag_suspeito"))}
        pi = peso_inmet(db, sim)
        r = dict(total_bacia_v3=round(float(ma.sum()), 1), total_bacia_v3b=round(float(mb.sum()), 1),
                 dif_total_pct=round(float((mb.sum() / ma.sum() - 1) * 100), 1),
                 razao_total_subbacia_p10_p50_p90=[round(float(x), 3) for x in np.percentile(rz, [10, 50, 90])],
                 razao_total_subbacia_min_max=[round(float(rz.min()), 3), round(float(rz.max()), 3)],
                 corr_horaria_media_bacia=round(float(np.corrcoef(ma, mb)[0, 1]), 4) if ma.std() > 0 else None,
                 corr_horaria_subbacia_mediana=round(float(np.nanmedian([np.corrcoef(A[:, i], B[:, i])[0, 1] for i in range(len(SUBS))
                                                                          if A[:, i].std() > 0 and B[:, i].std() > 0])), 4),
                 pico_media_bacia_v3=round(float(ma.max()), 2), pico_media_bacia_v3b=round(float(mb.max()), 2),
                 hora_pico_dif_h=int(np.argmax(mb) - np.argmax(ma)),
                 centro_massa_dif_h=round(centro(mb) - centro(ma), 2),
                 frac_subbacia_hora_alterada=round(float((np.abs(A - B) > 0.05).mean()), 3),
                 max_abs_subbacia_hora_mm=round(float(np.abs(A - B).max()), 2),
                 rmse_horario_media_bacia_mm=round(float(np.sqrt(((ma - mb) ** 2).mean())), 3),
                 peso_inmet_medio=round(pi[0], 3), peso_inmet_max_subbacia=round(pi[1], 3),
                 postos_v3=len(d3["postos_usados"]), postos_v3b=len(db["postos_usados"]),
                 inmet_v3=sum(c.startswith("INMET_") for c in d3["postos_usados"]),
                 inmet_v3b=sum(c.startswith("INMET_") for c in db["postos_usados"]),
                 excl_qc_v3=d3["postos_excluidos_qc"], excl_qc_v3b=db["postos_excluidos_qc"],
                 lag_suspeito_inmet_v3_v3b=lag)
        out[sim] = r
        print(sim, {k: v for k, v in r.items() if k not in ("excl_qc_v3", "excl_qc_v3b", "lag_suspeito_inmet_v3_v3b")}, flush=True)
    (AQUI / "efeito_chuva.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    L = ["| janela | total v3 → v3b (mm) | Δ% | razão sub-bacia p10/p50/p90 | corr h (bacia) | pico h bacia v3 → v3b | Δ centro (h) | INMET usados v3 → v3b | peso INMET |",
         "|---|---|---|---|---|---|---|---|---|"]
    for s, r in out.items():
        p = r["razao_total_subbacia_p10_p50_p90"]
        L.append(f"| {s} | {r['total_bacia_v3']} → {r['total_bacia_v3b']} | {r['dif_total_pct']:+.1f} | {p[0]:.2f}/{p[1]:.2f}/{p[2]:.2f} | "
                 f"{r['corr_horaria_media_bacia']} | {r['pico_media_bacia_v3']} → {r['pico_media_bacia_v3b']} | {r['centro_massa_dif_h']:+.2f} | "
                 f"{r['inmet_v3']} → {r['inmet_v3b']} | {r['peso_inmet_medio']:.2f} |")
    (AQUI / "efeito_chuva.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
