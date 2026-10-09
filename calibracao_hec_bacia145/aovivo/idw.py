"""Interpolação do forcamento_v3: IDW potência 2 das estações para o CENTRÓIDE de cada sub-bacia (EPSG:31982,
distância mínima 1 m), refeita hora a hora só com as estações que têm dado naquela hora."""
import numpy as np
from pyproj import Transformer

import estacoes as E

TR = Transformer.from_crs(4326, 31982, always_xy=True)


def xy_sub():
    geo = E.geometria()
    px, py = TR.transform([g["lon"] for g in geo], [g["lat"] for g in geo])
    return np.array(px), np.array(py), np.array([g["area_km2"] for g in geo]), [g["sub_id"] for g in geo]


def idw(codes, series, horas, P, vazio="nan"):
    """chuva[h, sub] e n_estações[h]. vazio: 'nan' (hora sem estação fica NaN) ou 'zero'."""
    px, py, _, _ = xy_sub()
    if not codes:
        return np.full((len(horas), len(px)), np.nan if vazio == "nan" else 0.0), np.zeros(len(horas), int)
    sx, sy = TR.transform([P[c][2] for c in codes], [P[c][1] for c in codes])
    w = 1 / np.maximum(np.hypot(px[:, None] - sx, py[:, None] - sy), 1.0) ** 2
    V = np.array([[series[c].get(h, np.nan) for c in codes] for h in horas])
    chuva = np.full((len(horas), len(px)), np.nan)
    n = np.isfinite(V).sum(1)
    for i in range(len(horas)):
        ok = np.isfinite(V[i])
        if ok.any():
            chuva[i] = (w[:, ok] @ V[i, ok]) / w[:, ok].sum(1)
        elif vazio == "zero":
            chuva[i] = 0.0
    return chuva, n
