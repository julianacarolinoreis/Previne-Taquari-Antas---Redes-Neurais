"""Séries horárias por posto (ANA, CEMADEN, INMET) e coordenadas, reproduzindo o leitor do forcamento_v3
(D:\\PREVINE\\hec_calibracao_20261005\\forcamento_v3.py + forcamento.py + chuva_fontes.py).

Convenção: hora H = soma de (H-60 min, H], horário de Brasília. Lacuna nunca vira zero.
  ANA     : telemetria bruta (dados_ana/csv/<cod>_<janela>.csv), hora só existe com todos os registros da cadência;
            > 90 mm/h = suspeita (descartada). Relógio de Muçum corrigido (comum.corrige_relogio).
  CEMADEN : leituras brutas do zip (cemaden_bruto.py). Rótulo = floor(hora local) + 1 h (DESLOC_CEMADEN_H = 1 do v3);
            o fuso das leituras é conferido em conferir_v3.py (UTC -> BRT reproduz o v3).
  INMET   : SERIE_HISTORICA (BDMEP), UTC -> BRT, rótulo igual (já acumula a hora anterior).
"""
import csv
import glob
import json
import math
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
CAL = AQUI.parent / "calibracao_hec_bacia145"
CODEX = Path(r"D:\PREVINE\hec_calibracao_20261005")
DADOS_ANA = CODEX / "dados_ana" / "csv"
INMET_DIR = Path(r"D:\PREVINE\estacoes_inmet\SERIE_HISTORICA")
SHP = r"D:\PREVINE\inventario_estacoes_taquariantas_3\inventario_ana_inmet_cemaden_ta.shp"
MAX_MM_H = 90.0
CEM_UTC = os.environ.get("CEM_UTC", "1") == "1"     # leituras CEMADEN em UTC (conferido em conferir_v3.py)

os.environ.setdefault("HEC_CATALOGO", "../dados/catalogo_ampliado.json")
sys.path.insert(0, str(CAL / "codigo"))
from comum import POSTOS, SIMULACOES, corrige_relogio  # noqa: E402

TESTE = "X20260918"   # janela dos eventos de teste: nunca é lida
JANELAS = [s for s in SIMULACOES if s != TESTE and "__" not in s]


def grade(ini, fim):
    out, t = [], ini
    while t <= fim:
        out.append(t)
        t += timedelta(hours=1)
    return out


def ana(cod, sim, horas):
    """Cópia de forcamento.chuva_horaria (modo histórico): {hora: mm}, cadência, horas suspeitas."""
    assert sim != TESTE
    path = DADOS_ANA / f"{cod}_{sim}.csv"
    if not path.exists():
        return {}, None, []
    reg = {}
    for r in csv.DictReader(path.open(encoding="utf-8")):
        if r["chuva_mm"] == "":
            continue
        reg[corrige_relogio(cod, datetime.fromisoformat(r["data_hora"].strip()).replace(second=0))] = float(r["chuva_mm"])
    if len(reg) < 10:
        return {}, None, []
    ts = sorted(reg)
    cad = Counter(int((b - a).total_seconds() // 60) for a, b in zip(ts, ts[1:])).most_common(1)[0][0]
    if cad not in (5, 10, 15, 30, 60):
        return {}, cad, []
    n = 60 // cad
    out, susp = {}, []
    for h in horas:
        slots = [h - timedelta(minutes=cad * k) for k in range(n)]
        if any(s not in reg for s in slots):
            continue
        v = sum(reg[s] for s in slots)
        if v < 0 or not math.isfinite(v):
            continue
        if v > MAX_MM_H:
            susp.append((str(h), v))
            continue
        out[h] = v
    return out, cad, susp


@lru_cache(maxsize=1)
def _cem():
    d = pd.read_pickle(AQUI / "cemaden_leituras.pkl")
    d = d[d.mm.notna() & (d.mm >= 0)]
    t = d.t - (timedelta(hours=3) if CEM_UTC else timedelta(0))
    rot = t.dt.floor("h") + timedelta(hours=1)
    h = d.assign(rot=rot).groupby(["cod", "rot"]).mm.sum()
    out = {}
    for cod, s in h.groupby(level=0):
        s = s.droplevel(0)
        if len(s) >= 100:
            out["CEM_" + cod] = {k.to_pydatetime(): float(v) for k, v in s.items()}
    meta = {"CEM_" + c: (f"CEMADEN {v['nome']} ({v['municipio']})", v["lat"], v["lon"])
            for c, v in json.loads((AQUI / "cemaden_estacoes.json").read_text(encoding="utf-8")).items()}
    return out, meta


@lru_cache(maxsize=1)
def _inmet():
    out, meta = {}, {}
    for f in sorted(glob.glob(str(INMET_DIR / "dados_*_H_*.csv"))):
        cab = {}
        with open(f, encoding="latin-1") as h:
            for i, linha in enumerate(h):
                if i >= 8:
                    break
                k, _, v = linha.partition(":")
                cab[k.strip()] = v.strip().strip(";")
        cod = cab["Codigo Estacao"]
        d = pd.read_csv(f, sep=";", skiprows=10, encoding="latin-1", decimal=",", usecols=[0, 1, 2])
        d.columns = ["data", "hora", "mm"]
        # a hora vem como HHMM (inteiro 100 ou texto "0100 UTC"): sem o zfill, 100 vira 10 h
        d["hora"] = pd.to_numeric(d.hora.astype(str).str.extract(r"(\d+)")[0].str.zfill(4).str[:2], errors="coerce")
        t = pd.to_datetime(d.data, format="%d/%m/%Y", errors="coerce") + pd.to_timedelta(d.hora, unit="h") - timedelta(hours=3)
        s = pd.Series(pd.to_numeric(d.mm, errors="coerce").values, index=t).dropna()
        s = s[(s >= 0) & (s < 200)]
        if len(s) < 100:
            continue
        out["INMET_" + cod] = {k.to_pydatetime(): float(v) for k, v in s.items()}
        meta["INMET_" + cod] = (f"INMET {cab.get('Nome', cod)}", float(cab["Latitude"].replace(",", ".")),
                                float(cab["Longitude"].replace(",", ".")))
    return out, meta


def serie(cod, sim, horas):
    """Série do posto na janela (só horas que existem), qualquer fonte."""
    assert sim != TESTE
    if cod.startswith("CEM_"):
        s = _cem()[0].get(cod, {})
        return {h: s[h] for h in horas if h in s}
    if cod.startswith("INMET_"):
        s = _inmet()[0].get(cod, {})
        return {h: s[h] for h in horas if h in s}
    return ana(cod, sim, horas)[0]


def fonte(c):
    return "CEMADEN" if c.startswith("CEM_") else "INMET" if c.startswith("INMET_") else "ANA"


@lru_cache(maxsize=1)
def postos():
    """Coordenadas como em forcamento_v3.todos_postos (CEMADEN: coordenadas do CSV bruto, 3 casas)."""
    import geopandas as gpd
    P = dict(POSTOS)
    g = gpd.read_file(SHP)
    for _, r in g[g.TIPO == "chuva"].iterrows():
        c = str(r.COD)
        if c not in P:
            P[c] = (f"ANA {c}", float(r.LAT), float(r.LONG))
    for r in json.loads((CODEX / "dados_ana" / "inventario_fluviometricas_86.json").read_text(encoding="utf-8")):
        if r.get("lat") and r["cod"] not in P:
            P[r["cod"]] = (f"ANA {r['nome'][:30]}", float(r["lat"]), float(r["lon"]))
    P.update(_cem()[1])
    P.update(_inmet()[1])
    return P


def ana_disponiveis(sim):
    """Códigos ANA com arquivo de telemetria baixado para a janela."""
    return sorted({p.name.rsplit("_", 2)[0] for p in DADOS_ANA.glob(f"*_{sim}.csv")})


@lru_cache(maxsize=1)
def geometria():
    geo = json.loads((CODEX / "geometria_subbacias.json").read_text(encoding="utf-8"))
    return geo
