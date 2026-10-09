"""MERGE-CPTEC horário -> média na área de cada sub-bacia (roda no Python 3.12 com eccodes:
D:\\PREVINE\\repo_hec_calib\\_analise_bacia145\\chuva_prevista\\.venv312).

Pesos: grade.py da análise de chuva prevista (pontos a 0,01° dentro de cada polígono -> célula 0,1° mais próxima).
Saída: merge_sub.npz com t_utc (AAAAMMDDHH do nome do arquivo), subs, P[t, sub] (mm/h; NaN = arquivo ausente)."""
import sys
from pathlib import Path

import eccodes
import numpy as np

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, r"D:\PREVINE\repo_hec_calib\_analise_bacia145\chuva_prevista")
import grade  # noqa: E402

CACHE = AQUI / "cache_merge"


def ler(f):
    with open(f, "rb") as h:
        g = eccodes.codes_grib_new_from_file(h)
        try:
            meta = {k: eccodes.codes_get(g, k) for k in ("Ni", "Nj", "latitudeOfFirstGridPointInDegrees",
                                                         "longitudeOfFirstGridPointInDegrees", "shortName")}
            v = eccodes.codes_get_values(g)
        finally:
            eccodes.codes_release(g)
    v = np.where(v >= 9999, np.nan, v)
    return meta, v


def main():
    fs = sorted(CACHE.rglob("MERGE_CPTEC_*.grib2"))
    subs = grade.subbacias()
    meta, _ = ler(fs[0])
    assert meta["shortName"] == "rdp", meta
    area, _ = grade.pesos(meta["latitudeOfFirstGridPointInDegrees"], meta["longitudeOfFirstGridPointInDegrees"], 0.1, 0.1,
                          meta["Ni"], meta["Nj"], subs)
    nomes = list(subs)
    T, P = [], np.full((len(fs), len(nomes)), np.nan)
    for i, f in enumerate(fs):
        T.append(int(f.stem.split("_")[-1]))
        try:
            m, v = ler(f)
            assert (m["Ni"], m["Nj"]) == (meta["Ni"], meta["Nj"])
        except Exception as e:  # noqa: BLE001
            print("falha", f.name, e, flush=True)
            continue
        for k, s in enumerate(nomes):
            idx, w = area[s]
            x = v[idx]
            ok = np.isfinite(x)
            if ok.any():
                P[i, k] = float((x[ok] * w[ok]).sum() / w[ok].sum())
        if i % 1000 == 0:
            print(i, len(fs), flush=True)
    np.savez_compressed(AQUI / "merge_sub.npz", t_utc=np.array(T), subs=np.array(nomes), P=P)
    print("ok", P.shape, "NaN:", int(np.isnan(P).any(1).sum()), "horas com falha")


if __name__ == "__main__":
    main()
