"""Geometria: sub-bacias (centróide, área, pontos), projeção UTM 22S e pesos de grade dos modelos de previsão."""
import gzip
import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

DADOS = Path(__file__).resolve().parent / "dados"


@lru_cache(maxsize=1)
def subbacias():
    """{sub_id: {lat, lon, area_km2, pontos[[lon, lat], ...]}} (ordem do arquivo = ordem alfabética)."""
    return json.loads(gzip.decompress((DADOS / "subbacias.json.gz").read_bytes()))


def nomes():
    return sorted(subbacias())


def areas():
    s = subbacias()
    return np.array([s[n]["area_km2"] for n in nomes()])


def utm22s(lon, lat):
    """SIRGAS 2000 / UTM 22S (EPSG:31982), série de Snyder; erro < 1 mm na faixa da bacia. Evita depender do pyproj."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    a, f, k0, lon0 = 6378137.0, 1 / 298.257222101, 0.9996, math.radians(-51.0)
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    p, lam = np.radians(lat), np.radians(lon)
    N = a / np.sqrt(1 - e2 * np.sin(p) ** 2)
    T, C, A = np.tan(p) ** 2, ep2 * np.cos(p) ** 2, (lam - lon0) * np.cos(p)
    e4, e6 = e2 * e2, e2 ** 3
    M = a * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * p - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * np.sin(2 * p)
             + (15 * e4 / 256 + 45 * e6 / 1024) * np.sin(4 * p) - (35 * e6 / 3072) * np.sin(6 * p))
    x = k0 * N * (A + (1 - T + C) * A ** 3 / 6 + (5 - 18 * T + T * T + 72 * C - 58 * ep2) * A ** 5 / 120) + 500000.0
    y = k0 * (M + N * np.tan(p) * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * A ** 4 / 24
                                   + (61 - 58 * T + T * T + 600 * C - 330 * ep2) * A ** 6 / 720)) + 10000000.0
    return x, y


def pesos_grade(lat0, lon0, dlat, dlon, ni, nj):
    """Grade regular (lat = lat0 + i·dlat, lon = lon0 + j·dlon, índice i·ni + j): média na área de cada sub-bacia
    (pontos a 0,01° → célula mais próxima) e célula do centróide. Mesma regra de chuva_prevista/grade.py."""
    def idx(lon, lat):
        i = np.rint((np.asarray(lat) - lat0) / dlat).astype(int)
        j = np.rint(((np.asarray(lon) - lon0) % 360) / dlon).astype(int) % ni
        assert (i >= 0).all() and (i < nj).all()
        return i * ni + j
    area, cent = {}, {}
    for s, v in subbacias().items():
        pts = np.array(v["pontos"])
        k, n = np.unique(idx(pts[:, 0], pts[:, 1]), return_counts=True)
        area[s] = (k, n / n.sum())
        cent[s] = int(idx(v["lon"], v["lat"]))
    return area, cent
