"""Substituto de chuva_fontes.cemaden() a partir das leituras brutas do zip (cemaden_bruto.py -> cemaden_leituras.pkl).

A planilha horária processada (D:\\PREVINE\\estacoes_cemaden\\chuvas_horarias_cemaden_bacia.csv) e a legenda sumiram.
Hora: leituras em UTC -> BRT, rótulo = floor(hora) + 1 h (DESLOC_CEMADEN_H = 1 do original), soma das leituras.
Conjunto de estações, ordem, nomes e coordenadas = os da legenda original, recuperados dos registros por posto que o
forcamento_v3 gravou (hec_calibracao_20261005/forcamento_v3/<janela>_postos.json, só leitura).
"""
import json
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

AQUI = Path(__file__).resolve().parent
LEDGER = Path(r"D:\PREVINE\hec_calibracao_20261005\forcamento_v3")


def legenda():
    """{chave CEM_: (nome, lat, lon)} na ordem em que o forcamento_v3 percorreu os postos."""
    leg = {}
    for f in sorted(LEDGER.glob("*_postos.json")):
        if f.name.startswith("X20260918"):
            continue
        for r in json.loads(f.read_text(encoding="utf-8")):
            if r["fonte"] == "CEMADEN" and r["posto"] not in leg:
                leg[r["posto"]] = (r["nome"], r["lat"], r["lon"])
    return leg


@lru_cache(maxsize=1)
def ler():
    d = pd.read_pickle(AQUI / "cemaden_leituras.pkl")
    d = d[d.mm.notna() & (d.mm >= 0)]
    rot = (d.t - timedelta(hours=3)).dt.floor("h") + timedelta(hours=1)
    h = d.assign(rot=rot).groupby(["cod", "rot"]).mm.sum()
    series = {"CEM_" + cod: s.droplevel(0) for cod, s in h.groupby(level=0)}
    out, meta = {}, {}
    for key, m in legenda().items():
        s = series.get(key)
        if s is None or len(s) < 100:
            print("CEMADEN sem série no zip:", key, m[0], flush=True)
            continue
        out[key] = {k.to_pydatetime(): float(v) for k, v in s.items()}
        meta[key] = m
    return out, meta
