# -*- coding: utf-8 -*-
"""Casas do rota_fuga_ruas_*.json agregadas na grade IBGE.

Cada célula usa a MEDIANA das casas dentro dela (tempo a pé do idoso com
subidas, distância, abrigo), mais o p90 do tempo e a cota da casa mais baixa,
para não esconder as piores. Célula sem casa mapeada cai no nó de via com
rota mais próximo do centroide.
"""
from __future__ import annotations

import math
from collections import Counter

from shapely.geometry import Point
from shapely.strtree import STRtree

VEL_IDOSO = 0.9


def casas_com_rota(rf):
    campos = (rf.get("meta") or {}).get("casas_campos")
    if not campos or not rf.get("casas"):
        return []
    F = {k: i for i, k in enumerate(campos)}
    out = []
    for c in rf["casas"]:
        if c[F["no"]] is None or c[F["no"]] < 0:
            continue
        out.append({
            "lat": c[F["lat"]], "lon": c[F["lon"]], "no": c[F["no"]],
            "abrigo": c[F["abrigo"]], "dist_m": c[F["dist_m"]],
            "tempo_s": c[F["tempo_s"]] if "tempo_s" in F else c[F["dist_m"]] / VEL_IDOSO,
            "na_mancha": c[F["na_mancha"]],
            "cota": c[F["cota_alaga"]] if "cota_alaga" in F else None,
        })
    return out


def no_prox(nos, lat, lon, validos=None):
    best, bd = 0, 1e18
    clat = math.cos(math.radians(lat))
    for i, (la, lo) in enumerate(nos):
        if validos is not None and validos[i] is None:
            continue
        dy = la - lat
        dx = (lo - lon) * clat
        d = dy * dy + dx * dx
        if d < bd:
            bd, best = d, i
    return best


class GradeCasas:
    def __init__(self, rf):
        self.rf = rf
        self.casas = casas_com_rota(rf)
        self.tree = STRtree([Point(c["lon"], c["lat"]) for c in self.casas]) if self.casas else None
        self.tempo_no = rf.get("tempo_s")

    def celula(self, geom):
        """{n_casas, tempo_s, tempo_p90_s, dist_m, abrigo, no, cota_min} da célula.

        cota_min: menor cota de alagamento entre as casas (None = nenhuma alaga
        ou célula sem casa).
        """
        dentro = []
        if self.tree is not None:
            dentro = [self.casas[int(i)] for i in self.tree.query(geom, predicate="contains")]
        if dentro:
            dentro.sort(key=lambda c: c["tempo_s"])
            med = dentro[len(dentro) // 2]
            p90 = dentro[min(len(dentro) - 1, int(0.9 * len(dentro)))]
            cotas = [c["cota"] for c in dentro if c["cota"] is not None]
            return {"n_casas": len(dentro), "tempo_s": round(med["tempo_s"]),
                    "tempo_p90_s": round(p90["tempo_s"]),
                    "dist_m": round(med["dist_m"]), "no": med["no"],
                    "cota_min": min(cotas) if cotas else None,
                    "abrigo": Counter(c["abrigo"] for c in dentro).most_common(1)[0][0]}
        c = geom.centroid
        i = no_prox(self.rf["nos"], c.y, c.x, self.rf["dist_m"])
        dist = self.rf["dist_m"][i]
        t = self.tempo_no[i] if self.tempo_no else dist / VEL_IDOSO
        return {"n_casas": 0, "tempo_s": round(t), "tempo_p90_s": round(t), "dist_m": round(dist), "no": i,
                "cota_min": None, "abrigo": self.rf["dest"][i]}
