"""Executor enxuto do HEC-HMS 4.13 para calibração em lote.

- Um DSS de chuva por janela de simulação (escrito uma vez).
- Um projeto pequeno por (janela, candidato); vários projetos calculados numa única JVM.
- Saída: vazão em J_201 (Muçum) e J_208 (Linha José Júlio), passo de 10 min.
"""
import csv
import json
import math
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from comum import (AREA_MUCUM_KM2, BASIN_BASE, CONTROLES, DADOS, FORC, FORC_PREV, HEC_CMD, MUCUM, SIMULACOES,
                   corrige_relogio, mae)

MES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MES_L = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
         "October", "November", "December"]
PASSO_MIN = 10
NOS_EXTRA = []  # nós adicionais a extrair (diagnóstico)
SAIDA = "Save Minimum"  # "Save All" grava ~55 MB/rodada
BASIN_NAME = "Taquari-Antas 145 SB 105 R"
# ET de referência mensal (mm/mês, jan..dez) aproximada para a Serra Gaúcha; só entra com a perda Deficit Constant,
# que precisa secar o solo entre as chuvas das janelas de 2-3 semanas.
ET_MENSAL_MM = [130, 105, 95, 65, 45, 35, 40, 55, 70, 100, 120, 135]


def lbl(t):
    return f"{t.day:02d}{MES[t.month - 1]}{t.year}"


def data_longa(t):
    return f"{t.day:02d} {MES_L[t.month - 1]} {t.year}"


def rodar_jython(script: Path, timeout=3600):
    r = subprocess.run([str(HEC_CMD), "-s", str(script)], cwd=HEC_CMD.parent, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r


# ---------------------------------------------------------------- chuva -> DSS
def forcamento_derivado(sim: str):
    """Chuva da janela derivada (comum.janela): a observada da mãe até a hora t0 inclusive; depois, a prevista pelo
    modelo na emissão t0 (FORC_PREV/<mãe>__<modelo>.json, lista horária a partir de t0+1 h); 'zero' = sem chuva
    depois de t0. Horas além do fim da previsão ficam sem chuva."""
    cfg = SIMULACOES[sim]
    f = json.loads((FORC / f"{cfg['mae']}.json").read_text(encoding="utf-8"))
    prev = {}
    if cfg["modelo"] != "zero":
        p = json.loads((FORC_PREV / f"{cfg['mae']}__{cfg['modelo']}.json").read_text(encoding="utf-8"))
        prev = p["emissoes"][f"{cfg['t0']:%Y%m%d%H}"]["chuva"]
        assert set(prev) == set(f["chuva_por_subbacia"]), sim
    for i, h in enumerate(f["horas"]):
        k = round((datetime.fromisoformat(h) - cfg["t0"]).total_seconds() / 3600) - 1
        if k >= 0:
            for s, v in f["chuva_por_subbacia"].items():
                serie = prev.get(s, [])
                v[i] = serie[k] if k < len(serie) else 0.0
    f["sim"] = sim
    f.pop("chuva_media_bacia_mm", None)
    (FORC / f"{sim}.json").write_text(json.dumps(f), encoding="utf-8")


def dss_chuva(sim: str) -> Path:
    dss = FORC / f"{sim}.dss"
    if dss.exists():
        return dss
    if "mae" in SIMULACOES[sim] and not (FORC / f"{sim}.json").exists():
        forcamento_derivado(sim)
    f = json.loads((FORC / f"{sim}.json").read_text(encoding="utf-8"))
    ini = datetime.fromisoformat(f["horas"][0])
    csvp = FORC / f"{sim}_chuva.csv"
    subs = list(f["chuva_por_subbacia"])
    with csvp.open("w", newline="") as h:
        w = csv.writer(h)
        w.writerow(subs)
        for i in range(len(f["horas"])):
            w.writerow([f"{f['chuva_por_subbacia'][s][i]:.4f}" for s in subs])
    tmp = FORC / f"{sim}_tmp.dss"
    script = FORC / f"{sim}_dss.py"
    script.write_text(f"""from hms.model.JythonHms import Exit
from hec.heclib.dss import HecDss
from hec.heclib.util import HecTime
from hec.io import TimeSeriesContainer
import csv
rows = list(csv.reader(open(r'{csvp.as_posix()}', 'rb')))
names = rows[0]; data = rows[1:]
t = HecTime('{lbl(ini)}', '{ini:%H%M}')
times = []
for _ in data:
    times.append(t.value()); t.add(60)
dss = HecDss.open(r'{tmp.as_posix()}')
for j, name in enumerate(names):
    c = TimeSeriesContainer()
    c.fullName = '/TAQUARI_ANTAS/%s/PRECIP-INC/{lbl(ini)}/1Hour/OBS/' % name
    c.interval = 60
    c.times = times
    c.values = [float(r[j]) for r in data]
    c.numberValues = len(times)
    c.units = 'MM'
    c.type = 'PER-CUM'
    dss.put(c)
dss.close()
open(r'{(FORC / (sim + "_dss.ok")).as_posix()}', 'w').write('OK')
Exit(1)
""", encoding="utf-8")
    r = rodar_jython(script, 600)
    if not (FORC / (sim + "_dss.ok")).exists():
        raise RuntimeError(f"Falha ao escrever DSS {sim}:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    tmp.rename(dss)
    return dss


# ---------------------------------------------------------------- bacia parametrizada
_BASE = None


def base_text():
    global _BASE
    if _BASE is None:
        _BASE = BASIN_BASE.read_text(encoding="utf-8")
    return _BASE


def passos_muskingum(k, x, dt_h=PASSO_MIN / 60):
    lo = max(1, math.ceil(2 * k * x / dt_h - 1e-10))
    hi = math.floor(2 * k * (1 - x) / dt_h + 1e-10)
    if lo > hi or lo > 100:
        raise ValueError("Muskingum sem discretização admissível")
    # HEC-HMS aceita no máximo 100 subtrechos (ERROR 41165)
    return min(hi, 100, max(lo, math.floor(k / dt_h + 0.5)))


def bacia(p: dict, init_ratio: float, grupos: dict | None = None) -> str:
    """p: ia, f, mtc, mr, mk, rec, thr (+ opcionais por grupo: mtc_<g>, mr_<g>, mk_<g>)."""
    grupos = grupos or {}

    def fator(nome, chave):
        g = grupos.get(nome)
        return p.get(f"{chave}_{g}", p[chave]) if g else p[chave]

    def sub(m):
        nome, corpo = m[1].strip(), m[2]
        def rep(label, val):
            nonlocal corpo
            corpo, n = re.subn(r"(?m)^(\s*" + re.escape(label) + r": )[^\n]+", lambda mm: mm[1] + val, corpo)
            assert n == 1, (nome, label)
        tc = float(re.search(r"(?m)^\s*Time of Concentration: ([^\n]+)", corpo)[1])
        r = float(re.search(r"(?m)^\s*Storage Coefficient: ([^\n]+)", corpo)[1])
        rep("Initial Loss", f"{p['ia']:.4f}")
        rep("Constant Loss Rate", f"{p['f']:.4f}")
        rep("Time of Concentration", f"{tc * fator(nome, 'mtc'):.5f}")
        rep("Storage Coefficient", f"{r * fator(nome, 'mr'):.5f}")
        rep("Recession Factor", f"{p['rec']:.4f}")
        rep("Initial Flow/Area Ratio", f"{init_ratio:.6f}")
        rep("Threshold Flow to Peak Ratio", f"{p['thr']:.4f}")
        return f"Subbasin: {m[1]}\n{corpo}End:"

    def rea(m):
        nome, corpo = m[1].strip(), m[2]
        k = float(re.search(r"(?m)^\s*Muskingum K: ([^\n]+)", corpo)[1]) * fator(nome, "mk")
        x = float(re.search(r"(?m)^\s*Muskingum x: ([^\n]+)", corpo)[1])
        # Trechos muito curtos: K mínimo admissível no passo de 10 min (1 subtrecho).
        k = max(k, (PASSO_MIN / 60) / (2 * (1 - x)) + 1e-6)
        corpo = re.sub(r"(?m)^(\s*Muskingum K: )[^\n]+", lambda mm: mm[1] + f"{k:.5f}", corpo)
        corpo = re.sub(r"(?m)^(\s*Muskingum Steps: )[^\n]+", lambda mm: mm[1] + str(passos_muskingum(k, x)), corpo)
        return f"Reach: {m[1]}\n{corpo}End:"

    t = base_text()
    t, ns = re.subn(r"(?ms)^Subbasin: ([^\n]+)\n(.*?)^End:", sub, t)
    t, nr = re.subn(r"(?ms)^Reach: ([^\n]+)\n(.*?)^End:", rea, t)
    assert ns == 145 and nr == 105
    t = re.sub(r"(?m)^Basin: [^\n]+", "Basin: " + BASIN_NAME, t, count=1)
    return t


# ---------------------------------------------------------------- observados
_OBS = {}


def observado(sim: str, cod: str) -> dict:
    """Vazão instantânea da telemetria (15 min) -> {datetime: m3/s}."""
    key = (sim, cod)
    if key not in _OBS:
        out = {}
        p = DADOS / "csv" / f"{cod}_{mae(sim)}.csv"
        if p.exists():
            for r in csv.DictReader(p.open(encoding="utf-8")):
                if r["vazao_m3s"]:
                    out[corrige_relogio(cod, datetime.fromisoformat(r["data_hora"].strip()))] = float(r["vazao_m3s"])
        _OBS[key] = out
    return _OBS[key]


_NIV = {}


def nivel(sim: str, cod: str) -> dict:
    """Nível instantâneo da telemetria (cm) -> {datetime: cm}."""
    key = (sim, cod)
    if key not in _NIV:
        out = {}
        p = DADOS / "csv" / f"{cod}_{mae(sim)}.csv"
        if p.exists():
            for r in csv.DictReader(p.open(encoding="utf-8")):
                if r["nivel_cm"]:
                    out[corrige_relogio(cod, datetime.fromisoformat(r["data_hora"].strip()))] = float(r["nivel_cm"])
        _NIV[key] = out
    return _NIV[key]


def razao_inicial(sim: str) -> float:
    ini = SIMULACOES[sim]["ini"]
    obs = observado(sim, MUCUM)
    cand = [obs[t] for t in sorted(obs) if abs((t - ini).total_seconds()) <= 3 * 3600]
    if not cand:
        raise ValueError("Sem vazão inicial em Muçum para " + sim)
    return cand[0] / AREA_MUCUM_KM2


# ---------------------------------------------------------------- tabelas (paired data)
# tabelas: {nome: {"tipo": rótulo do .pdata, "c": parte C do DSS, "xu", "yu": unidades, "x": [...], "y": [...]}}.
# O .pdata aponta para tabelas.dss, que a própria JVM do lote grava a partir de tabelas.txt antes de abrir o projeto.
TIPO_SECAO = dict(tipo="Distance-Elevation", c="DISTANCE-ELEVATION", xu="M", yu="M")
TIPO_PERCENTUAL = dict(tipo="Percent Graph", c="PERCENT GRAPH", xu="%", yu="%")


def caminho_tabela(nome, t):
    return f"/TAQUARI_ANTAS/{nome}/{t['c']}///TABLE/"


def escrever_tabelas(d: Path, tabelas: dict):
    p = ["Paired Data Manager: proj", "     Version: 4.13", "     Filepath Separator: \\", "End:", ""]
    linhas = []
    for nome, t in tabelas.items():
        p += [f"Table: {nome}", f"     Table Type: {t['tipo']}", f"     X-Units: {t['xu']}", f"     Y-Units: {t['yu']}",
              "     Use External DSS File: YES", "     DSS File: tabelas.dss",
              f"     Pathname: {caminho_tabela(nome, t)}", "End:", ""]
        linhas.append(";".join([caminho_tabela(nome, t), t["xu"], t["yu"], ",".join(f"{v:.6g}" for v in t["x"]),
                                ",".join(f"{v:.6g}" for v in t["y"])]))
    (d / "proj.pdata").write_text("\n".join(p), encoding="utf-8")
    (d / "tabelas.txt").write_text("\n".join(linhas) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- projeto e lote
def escrever_projeto(d: Path, sim: str, basin_text: str, tabelas: dict | None = None):
    d.mkdir(parents=True, exist_ok=True)
    cfg = SIMULACOES[sim]
    ini, fim = cfg["ini"], cfg["fim"]
    dss = dss_chuva(sim)
    shutil.copy2(dss, d / "chuva.dss")
    (d / "bacia.basin").write_text(basin_text, encoding="utf-8")
    if tabelas:
        escrever_tabelas(d, tabelas)
    subs = re.findall(r"(?m)^Subbasin: ([^\n]+)", basin_text)
    g = ["Gage Manager: chuva", "     Version: 4.13", "     Filepath Separator: \\", "End:", ""]
    for s in subs:
        g += [f"Gage: G_{s}", f"     Gage: G_{s}", "     Gage Type: Precipitation",
              "     Reference Height Units: Meters", "     Reference Height: 0.0",
              "     Data Source Type: External DSS", "     Filename: chuva.dss",
              f"     Pathname: /TAQUARI_ANTAS/{s}/PRECIP-INC/{lbl(ini)}/1Hour/OBS/",
              "     Variant: Variant-1", f"       Start Time: {data_longa(ini)}, {ini:%H:%M}",
              f"       End Time: {data_longa(fim)}, {fim:%H:%M}", "     End Variant: Variant-1", "End:", ""]
    (d / "proj.gage").write_text("\n".join(g), encoding="utf-8")
    com_et = "LossRate: Deficit Constant" in basin_text
    m = ["Meteorology: Chuva ANA", "     Version: 4.13", "     Unit System: Metric",
         "     Set Missing Data to Default: No", "     Precipitation Method: Specified Average",
         "     Air Temperature Method: None", "     Atmospheric Pressure Method: None",
         "     Dew Point Method: None", "     Wind Speed Method: None", "     Shortwave Radiation Method: None",
         "     Longwave Radiation Method: None", "     Snowmelt Method: None",
         "     Evapotranspiration Method: " + ("Monthly Evaporation" if com_et else "No Evapotranspiration"),
         f"     Use Basin Model: {BASIN_NAME}", "End:", "",
         "Precip Method Parameters: Specified Average", "     Allow Depth Override: Yes", "End:", ""]
    if com_et:
        m += ["Evapotranspiration Method Parameters: Monthly Evaporation", "End:", ""]
    et = (["", "     Begin Et: Monthly Evaporation"] + [f"     Pan Evaporation: {v}" for v in ET_MENSAL_MM]
          + ["     Evapotranspiration Coefficient: 1.0"] * 12 + ["     End Et:"]) if com_et else []
    for s in subs:
        m += [f"Subbasin: {s}", f"     Gage: G_{s}"] + et + ["End:", ""]
    (d / "chuva.met").write_text("\n".join(m), encoding="utf-8")
    (d / "controle.control").write_text(
        f"Control: Controle\n     Version: 4.13\n     Start Date: {data_longa(ini)}\n     Start Time: {ini:%H:%M}\n"
        f"     End Date: {data_longa(fim)}\n     End Time: {fim:%H:%M}\n     Time Interval: {PASSO_MIN}\nEnd:\n",
        encoding="utf-8")
    (d / "proj.hms").write_text(
        "Project: proj\n     Version: 4.13\n     Filepath Separator: \\\n     DSS File Name: proj.dss\n"
        "     Time Zone ID: America/Sao_Paulo\nEnd:\n\n"
        "Precipitation: Chuva ANA\n     Filename: chuva.met\nEnd:\n\n"
        f"Basin: {BASIN_NAME}\n     Filename: bacia.basin\nEnd:\n\n"
        "Control: Controle\n     FileName: controle.control\nEnd:\n", encoding="utf-8")
    (d / "proj.run").write_text(
        "Run: Rodada\n     Log File: Rodada.log\n     DSS File: output.dss\n     Is Save Spatial Results: No\n"
        f"     Basin: {BASIN_NAME}\n     Precip: Chuva ANA\n     Control: Controle\n"
        f"     Save State Type: None\n     Time-Series Output: {SAIDA}\nEnd:\n", encoding="utf-8")


def _lote_jvm(dirs: list[Path], script: Path):
    lst = repr([d.as_posix() for d in dirs])
    nodes = repr([n for n, _ in CONTROLES.values()] + list(NOS_EXTRA))
    script.write_text(f"""from hms.model.JythonHms import *
from hec.heclib.dss import HecDss
from hec.io import PairedDataContainer
import os
def gravar_tabelas(d):
    dss = HecDss.open(d + '/tabelas.dss')
    for linha in open(d + '/tabelas.txt').read().splitlines():
        if not linha.strip():
            continue
        cam, xu, yu, xs, ys = linha.split(';')
        x = [float(v) for v in xs.split(',')]
        y = [float(v) for v in ys.split(',')]
        c = PairedDataContainer()
        c.fullName = cam
        c.xOrdinates = x
        c.yOrdinates = [y]
        c.numberOrdinates = len(x)
        c.numberCurves = 1
        c.xunits = xu
        c.yunits = yu
        c.xtype = 'UNT'
        c.ytype = 'UNT'
        dss.put(c)
    dss.close()
for d in {lst}:
    try:
        if os.path.exists(d + '/tabelas.txt'):
            gravar_tabelas(d)
        OpenProject('proj', d)
        Compute('Rodada')
        dss = HecDss.open(d + '/output.dss')
        paths = list(dss.getCatalogedPathnames())
        f = open(d + '/vazao.csv', 'w')
        f.write('node,time_value,flow\\n')
        for node in {nodes}:
            for p in paths:
                if p.startswith('//' + node + '/FLOW/'):
                    ts = dss.get(p)
                    for i in range(ts.numberValues):
                        f.write('%s,%d,%.6f\\n' % (node, int(ts.times[i]), float(ts.values[i])))
        f.close()
        dss.close()
        open(d + '/ok.txt', 'w').write('OK')
    except Exception, e:
        open(d + '/erro.txt', 'w').write(str(e))
Exit(1)
""", encoding="utf-8")
    return rodar_jython(script, 7200)


def ler_vazao(d: Path) -> dict:
    out = {}
    with (d / "vazao.csv").open() as h:
        for r in csv.DictReader(h):
            t = datetime(1899, 12, 31) + timedelta(minutes=int(r["time_value"]))
            out.setdefault(r["node"], {})[t] = float(r["flow"])
    return out


def rodar_lote(jobs: list[tuple], paralelo=12, por_jvm=6) -> dict:
    """jobs: (dir, sim, basin_text[, tabelas]). Retorna {dir: {node: {t: q}}} (ou exceção registrada)."""
    pend = []
    for d, sim, txt, *tab in jobs:
        if (d / "ok.txt").exists():
            continue
        if d.exists():
            shutil.rmtree(d)
        escrever_projeto(d, sim, txt, tab[0] if tab else None)
        pend.append(d)
    grupos = [pend[i:i + por_jvm] for i in range(0, len(pend), por_jvm)]
    with ThreadPoolExecutor(paralelo) as ex:
        list(ex.map(lambda ig: _lote_jvm(ig[1], ig[1][0].parent / f"_lote_{ig[0]}_{ig[1][0].name}.py"), enumerate(grupos)))
    res = {}
    for d, *_ in jobs:
        if (d / "ok.txt").exists():
            res[d] = ler_vazao(d)
            for f in ("output.dss", "chuva.dss", "proj.dss", "tabelas.dss"):
                (d / f).unlink(missing_ok=True)  # economiza disco; CSV de vazão fica
        else:
            err = (d / "erro.txt").read_text() if (d / "erro.txt").exists() else "sem saída"
            res[d] = RuntimeError(err)
    return res
