"""Leitor INMET (BDMEP, SERIE_HISTORICA) igual ao chuva_fontes.inmet() do forcamento_v3, com a hora corrigida.

A coluna "Hora Medicao" vem como inteiro HHMM em UTC (0, 100, ..., 2300). O original fazia str(hora)[:2]:
100 -> 10 h, 300 -> 30 h, 800 -> 80 h ... (bug). Correção: int(hora) // 100.
bug=True reproduz o original byte a byte (conferido em quantificar_bug.py contra o chuva_fontes.inmet importado).
"""
import glob
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

INMET = Path(r"D:\PREVINE\estacoes_inmet\SERIE_HISTORICA")
DESLOC_INMET_H = 0


def cabecalho(f):
    cab = {}
    with open(f, encoding="latin-1") as h:
        for i, linha in enumerate(h):
            if i >= 8:
                break
            k, _, v = linha.partition(":")
            cab[k.strip()] = v.strip().strip(";")
    return cab


def bruto(f):
    d = pd.read_csv(f, sep=";", skiprows=10, encoding="latin-1", decimal=",", usecols=[0, 1, 2])
    d.columns = ["data", "hora", "mm"]
    return d


@lru_cache(maxsize=2)
def ler(bug):
    out, meta = {}, {}
    for f in sorted(glob.glob(str(INMET / "dados_*_H_*.csv"))):
        cab = cabecalho(f)
        cod = cab["Codigo Estacao"]
        d = bruto(f)
        if bug:
            hora = pd.to_numeric(d.hora.astype(str).str[:2], errors="coerce")
        else:
            hora = pd.to_numeric(d.hora, errors="coerce") // 100
        t = pd.to_datetime(d.data, format="%d/%m/%Y", errors="coerce") + pd.to_timedelta(hora, unit="h") \
            - timedelta(hours=3 - DESLOC_INMET_H)
        s = pd.Series(pd.to_numeric(d.mm, errors="coerce").values, index=t).dropna()
        s = s[(s >= 0) & (s < 200)]
        if len(s) < 100:
            continue
        key = "INMET_" + cod
        out[key] = {k.to_pydatetime(): float(v) for k, v in s.items()}
        meta[key] = (f"INMET {cab.get('Nome', cod)}", float(cab["Latitude"].replace(",", ".")),
                     float(cab["Longitude"].replace(",", ".")))
    return out, meta
