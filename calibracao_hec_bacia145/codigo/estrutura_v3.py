"""Estrutura v3 do modelo (08/10/2026) — corrige os problemas M1, M5, M7 da revisão sem trocar o motor.

1. Perda: Initial+Constant com estado de umidade LOCAL: Ia = ia_max * exp(-q0/q*), onde q0 é a vazão específica
   observada no início da janela no menor controle que contém a sub-bacia (substitui o Ia fixo por membro).
2. Base: "Initial Flow/Area Ratio" = o mesmo q0 local (antes: o de Muçum para toda a bacia).
3. Calha principal de Linha José Júlio... Encantado em Muskingum-Cunge com a geometria do MDT (uma opção: rota='mc').
4. Parametrização enxuta: 2 grupos de velocidade (alto = montante de Monte Claro; resto), mr, mn/mk, imp, f, rec, thr.
"""
import csv
import json
import math
import os
import re
from datetime import timedelta

from comum import EVENTOS, MDT_SUBBACIAS, MDT_TRECHOS, SIMULACOES
import bacia_inteira as bi
import hec

MDT = MDT_TRECHOS
ATT = {r["reach_id"]: r for r in csv.DictReader(open(MDT, encoding="utf-8"))}
# declividade do caminho de escoamento de cada sub-bacia (MDT SRTM 30 m): relevo p90-p10 / comprimento de Hack (L = 1,4 A^0,6 km)
SUB_MDT = {}
for _r in csv.DictReader(open(MDT_SUBBACIAS, encoding="utf-8")):
    _A = float(_r["area_km2"])
    _rel = float(_r["elev_p90_m"]) - float(_r["elev_p10_m"])
    SUB_MDT[_r["sub_id"]] = dict(area=_A, S=min(0.15, max(0.003, _rel / (1.4 * _A ** 0.6 * 1000))))
S_REF = sorted(v["S"] for v in SUB_MDT.values())[len(SUB_MDT) // 2]
A_GRANDE = 400.0   # km²: sub-bacias que tratamos à parte (uma UH só para > 400 km² é pouco crível)
NEUTRO = {"v_grandes": 1.0, "ks": 0.0}   # valores que reproduzem exatamente a estrutura anterior
CTRL_NOS = [("TAINHAS", "J_106"), ("CASTRO_ALVES", "J_211"), ("MONTE_CLARO", "J_236"), ("LJJ", "J_208"),
            ("MUCUM", "J_201"), ("ENCANTADO", "J_258")]
GRUPO_ALTO = {"tainhas", "alto", "medio"}
LARG = {"tainhas": 60, "alto": 100, "medio": 140, "carreiro": 170, "guapore": 250, "baixo": 280}
S_MIN = {"tainhas": 0.0015, "alto": 0.0010, "medio": 0.0008, "carreiro": 0.0005, "guapore": 0.0003, "baixo": 0.0003}
QIDX = {"tainhas": 400, "alto": 2500, "medio": 4000, "carreiro": 5000, "guapore": 6000, "baixo": 6000}
N_BASE = 0.045

PARAMS = {
    # limites ampliados em 08/10 (R5 da busca encostou em f=8, thr=0.05, mr=2.5, mn=0.6; imp perto de 0.35)
    "ia_max": (0.0, 90.0, "lin"), "qstar": (0.002, 0.05, "log"), "f": (0.5, 20.0, "log"), "imp": (0.0, 0.6, "lin"),
    "mr": (0.4, 5.0, "log"), "v_alto": (0.3, 2.5, "log"), "v_resto": (0.3, 2.5, "log"),
    "mn": (0.4, 1.8, "log"), "mk": (0.4, 2.5, "log"), "rec": (0.70, 0.98, "lin"), "thr": (0.01, 0.40, "lin"),
    # 08/10 noite: uso do MDT na resposta das sub-bacias
    "v_grandes": (0.25, 2.0, "log"),   # multiplicador extra de Tc e R das sub-bacias com mais de A_GRANDE km²
    "ks": (0.0, 0.8, "lin"),           # Tc e R proporcionais a (S/S_ref)^-ks, com S a declividade do caminho (MDT)
}
# Perda SCS (Curve Number), 08/10 noite: a fração de escoamento CRESCE com a chuva acumulada (perda que depende do tamanho da cheia).
# HEC_PERDA=scs troca (ia_max, f) por s0 (retenção máxima S em mm, estado seco); qstar passa a controlar a umidade:
#   S = s0 * exp(-q0/q*)  (q0 = vazão específica local no início da janela);  CN = 25400/(S+254);  Ia = 0,2 S (padrão do HEC-HMS).
# Só o lado local da busca lê esta variável: na nuvem, basta o candidato trazer "s0".
if os.environ.get("HEC_PERDA") == "scs":
    PARAMS.pop("ia_max")
    PARAMS.pop("f")
    PARAMS["qstar"] = (0.01, 0.30, "log")
    PARAMS["s0"] = (15.0, 500.0, "log")

# Perda Deficit and Constant (09/10): o candidato traz "dmax" em vez de (ia_max, f) ou s0.
# O solo tem capacidade dmax; a chuva só escoa quando o déficit zera (saturação) ou acima da taxa de percolação,
# e o déficit se recupera pela evapotranspiração mensal do dossel (o modelo meteorológico passa a ter ET).
# Déficit inicial = dmax * exp(-q0/q*), mesma leitura de umidade das outras perdas. Impermeável limitado a 5%:
# I+C e SCS só fechavam o volume com ~40% de área impermeável, o que não existe na bacia.
PARAMS_DC = {k: v for k, v in PARAMS.items() if k not in ("ia_max", "f", "s0", "imp")}
PARAMS_DC.update({
    "dmax": (20.0, 300.0, "log"), "perc": (0.2, 12.0, "log"), "imp": (0.0, 0.05, "lin"),
    "qstar": (0.002, 0.10, "log"), "mr": (0.4, 12.0, "log"),   # lr-g5 encostou em mr=7 com teto 8
})
CANOPY_MM, SUPERFICIE_MM = 3.0, 5.0

# Base em reservatório linear (09/10): o candidato traz "k1". É o único método de base do HEC-HMS que conserva massa:
# a perda (I+C: toda a perda; Deficit Constant: só a percolação) entra em dois reservatórios lineares em paralelo,
# GW-1 rápido (subsuperficial, k1 h) e GW-2 lento (k2 h). fb = fração da perda que volta ao rio (o resto vira recarga
# profunda); p1 = parcela de fb que vai para GW-1; s1 = parcela da vazão inicial q0 atribuída a GW-1.
# Com a Recession, a perda simplesmente some, e a busca compensava com ~40% de área impermeável e cheias atrasadas.
PARAMS_LR = {
    "k1": (3.0, 150.0, "log"), "k2": (150.0, 4000.0, "log"),
    "fb": (0.3, 1.0, "lin"), "p1": (0.02, 0.98, "lin"), "s1": (0.0, 0.6, "lin"),
}
PARAMS_LRIC = {k: v for k, v in PARAMS.items() if k not in ("rec", "thr", "s0")}
PARAMS_LRIC.update({"ia_max": (0.0, 90.0, "lin"), "f": (0.5, 20.0, "log"), "imp": (0.0, 0.15, "lin"), **PARAMS_LR})
PARAMS_LRDC = {k: v for k, v in PARAMS_DC.items() if k not in ("rec", "thr")}
PARAMS_LRDC.update(PARAMS_LR)

# Clark variável (09/10, família lrdcv): Tc e R de cada intervalo variam com a intensidade do excesso i (HEC-HMS
# "Clark Method: Variable"). Tc e R do candidato valem na intensidade-índice ie (mm/h); fora dela, por curvas
# percentuais iguais para todas as sub-bacias: Tc(i) = Tc * (i/ie)^-atc e R(i) = R * (i/ie)^-ar (onda cinemática:
# expoente ~0,4), limitadas a [VC_MIN, VC_MAX]%. atc = ar = 0 reproduz o Clark padrão.
PARAMS_LRDCV = dict(PARAMS_LRDC, ie=(0.5, 20.0, "log"), atc=(0.0, 0.6, "lin"), ar=(0.0, 0.6, "lin"))
VC_X = [0, 5, 10, 25, 50, 100, 200, 400, 800, 1600, 5000]   # % da intensidade-índice
VC_MIN, VC_MAX = 20.0, 400.0

# Seção de 8 pontos no Muskingum-Cunge (09/10, rotas mc8st / mc8): seções de dados/secoes_mc.json, extraídas do MDT de
# Santa Tereza (mosaico 2 m; R_208, R_256, R_201) e do SRTM 30 m (demais trechos da calha), com o leito abaixo da
# lâmina ajustado à curva-chave de LJJ (_analise_modelo/secoes). mc8st: só os 3 trechos do mosaico; mc8: os 17.
# n da calha entre os pontos 3 e 6 = N_BASE*mn; nas encostas = nob vezes isso (família lrdc8; sem nob, 1).
PARAMS_LRDC8 = dict(PARAMS_LRDC, nob=(0.7, 3.0, "log"))
PARAMS_LRDCV8 = dict(PARAMS_LRDCV, nob=PARAMS_LRDC8["nob"])
FAMILIAS = {"dc": PARAMS_DC, "lric": PARAMS_LRIC, "lrdc": PARAMS_LRDC, "lrdcv": PARAMS_LRDCV, "lrdc8": PARAMS_LRDC8,
            "lrdcv8": PARAMS_LRDCV8}
ROTAS_8PT = {"mc8st": ("R_208", "R_256", "R_201"), "mc8": None}
_SECOES = None


def secoes():
    global _SECOES
    if _SECOES is None:
        _SECOES = json.loads((MDT.parent / "secoes_mc.json").read_text(encoding="utf-8"))["trechos"]
    return _SECOES


def usa_8pt(r, rota):
    return rota in ROTAS_8PT and r in MC_REACHES and (ROTAS_8PT[rota] is None or r in ROTAS_8PT[rota])


def curva_vc(a):
    return [min(VC_MAX, max(VC_MIN, 100.0 * (max(x, VC_X[1]) / 100.0) ** (-a))) for x in VC_X]


def tabelas_v3(p, rota="mc"):
    """Tabelas (paired data) que a bacia do candidato usa: seções de 8 pontos e curvas do Clark variável."""
    tab = {}
    if rota in ROTAS_8PT:
        for r in MC_REACHES:
            if usa_8pt(r, rota):
                pts = secoes()[r]["pontos"]
                tab["XS_" + r] = dict(hec.TIPO_SECAO, x=[q[0] for q in pts], y=[q[1] for q in pts])
    if "ie" in p:
        tab["VC_TC"] = dict(hec.TIPO_PERCENTUAL, x=VC_X, y=curva_vc(p["atc"]))
        tab["VC_R"] = dict(hec.TIPO_PERCENTUAL, x=VC_X, y=curva_vc(p["ar"]))
    return tab


def bloco_lr(p, qloc):
    def piso(x):
        return math.floor(x * 1e4) / 1e4
    f1, f2 = piso(p["fb"] * p["p1"]), piso(p["fb"] * (1 - p["p1"]))
    linhas = ["     Baseflow: Linear Reservoir"]
    for i, (fr, k, q) in enumerate(((f1, p["k1"], qloc * p["s1"]), (f2, p["k2"], qloc * (1 - p["s1"]))), 1):
        linhas += [f"     Groundwater Layer: {i}", f"     GW-{i} Baseflow Fraction: {fr:.4f}",
                   f"     GW-{i} Number Reservoirs: 1", f"     GW-{i} Routing Coefficient: {k:.4f}",
                   f"     GW-{i} Initial Flow/Area Ratio: {q:.6f}"]
    return "\n".join(linhas) + "\n"


def bloco_dc(p, qloc, imp_pct):
    d0 = p["dmax"] * math.exp(-qloc / p["qstar"])
    return ("     Canopy: Simple\n     Allow Simultaneous Precip Et: No\n     Plant Uptake Method: Simple\n"
            f"     Initial Canopy Storage Percent: 0\n     Canopy Storage Capacity: {CANOPY_MM}\n"
            "     Crop Coefficient: 1.0\n     End Canopy:\n\n"
            f"     Surface: Simple\n     Initial Surface Storage Percent: 0\n     Surface Storage Capacity: {SUPERFICIE_MM}\n"
            "     Surface Albedo: 0.20\n     End Surface:\n\n"
            f"     LossRate: Deficit Constant\n     Percent Impervious Area: {imp_pct}\n"
            f"     Initial Deficit: {d0:.4f}\n     Maximum Deficit: {p['dmax']:.4f}\n"
            f"     Percolation Rate: {p['perc']:.4f}\n     Recovery Factor: 1.0\n")


def _topologia():
    txt = hec.base_text()
    down, area, tipo = {}, {}, {}
    for m in re.finditer(r"(?ms)^(Subbasin|Reach|Junction|Sink): ([^\n]+)\n(.*?)^End:", txt):
        n = m[2].strip()
        d = re.search(r"(?m)^\s*Downstream:\s*([^\n]+)", m[3])
        down[n] = d[1].strip() if d else None
        tipo[n] = m[1]
        a = re.search(r"(?m)^\s*Area:\s*([\d.]+)", m[3])
        if a:
            area[n] = float(a[1])
    return down, area, tipo


DOWN, AREA, TIPO = _topologia()


def _jusante(n):
    out = []
    while n:
        out.append(n)
        n = DOWN.get(n)
    return out


JUS = {n: _jusante(n) for n in DOWN}
AREA_UP = {no: sum(a for s, a in AREA.items() if no in JUS[s]) for _, no in CTRL_NOS}
# calha em Muskingum-Cunge: de J_106 até J_258 (Encantado)
MC_REACHES = [n for n in JUS["J_106"] if TIPO.get(n) == "Reach" and "J_258" in JUS[n] and n != "J_258"]
MC_REACHES = [r for r in MC_REACHES if JUS[r].index("J_258") >= 0]
# controle de cada sub-bacia = menor controle a jusante
CTRL_DE = {}
for s in AREA:
    for nome, no in sorted(CTRL_NOS, key=lambda c: AREA_UP[c[1]]):
        if no in JUS[s]:
            CTRL_DE[s] = nome
            break
    else:
        CTRL_DE[s] = "ENCANTADO"


def q0_controles(sim):
    """Vazão específica (m³/s/km²) no início da janela por controle, com fallback para o próximo controle maior."""
    ini = SIMULACOES[sim]["ini"]
    out = {}
    for nome, no in CTRL_NOS:
        cod, _, limite, _ = bi.CONTROLES[nome]
        obs = bi.obs_limpo(sim, cod)
        cand = [(abs((t - ini).total_seconds()), q) for t, q in obs.items() if abs((t - ini).total_seconds()) <= 6 * 3600]
        if cand:
            out[nome] = min(cand)[1] / AREA_UP[no]
    ordem = [n for n, _ in sorted(CTRL_NOS, key=lambda c: AREA_UP[c[1]])]
    for i, nome in enumerate(ordem):
        if nome not in out:
            for prox in ordem[i + 1:] + ordem[:i][::-1]:
                if prox in out:
                    out[nome] = out[prox]
                    break
    if not out:
        raise ValueError("sem vazão inicial em nenhum controle: " + sim)
    return out


def bloco_mc(r, mn):
    reg = bi.REG[r]
    L_m = float(ATT[r]["length_km"]) * 1000 / 1.10
    S = max(float(ATT[r]["slope_m_per_km"]) / 1000, S_MIN[reg])
    return ("     Route: Muskingum Cunge\n     Initial Variable: Combined Inflow\n     Channel: Trapezoid\n"
            f"     Length: {L_m:.1f}\n     Energy Slope: {S:.6f}\n     Mannings n: {N_BASE * mn:.4f}\n"
            f"     Bottom Width: {LARG[reg]}\n     Side Slope: 1\n     Index Parameter Type: Index Flow\n"
            f"     Index Flow: {QIDX[reg]}\n     Space-Time Method: Automatic DX and DT\n     Channel Loss: None\n")


def bloco_mc8(r, p):
    reg = bi.REG[r]
    L_m = float(ATT[r]["length_km"]) * 1000 / 1.10
    sec = secoes()[r]
    S = sec["decl_m_km"] / 1000 if sec.get("decl_m_km") else max(float(ATT[r]["slope_m_per_km"]) / 1000, S_MIN[reg])
    n = N_BASE * p["mn"]
    nob = n * p.get("nob", 1.0)
    return ("     Route: Muskingum Cunge\n     Initial Variable: Combined Inflow\n     Channel: 8-point\n"
            f"     Length: {L_m:.1f}\n     Energy Slope: {S:.6f}\n     Mannings n: {n:.4f}\n"
            f"     Left Mannings n: {nob:.4f}\n     Right Mannings n: {nob:.4f}\n     Cross Section Name: XS_{r}\n"
            "     Index Parameter Type: Index Flow\n"
            f"     Index Flow: {QIDX[reg]}\n     Space-Time Method: Automatic DX and DT\n     Channel Loss: None\n")


def bacia_v3(p, sim, rota="mc"):
    q0 = q0_controles(sim)

    def sub(m):
        nome, corpo = m[1].strip(), m[2]
        reg = bi.REG[nome]
        v = p["v_alto"] if reg in GRUPO_ALTO else p["v_resto"]
        md = SUB_MDT[nome]
        if md["area"] > A_GRANDE:
            v *= p.get("v_grandes", 1.0)
        v *= min(4.0, max(0.25, (md["S"] / S_REF) ** (-p.get("ks", 0.0))))
        qloc = q0[CTRL_DE[nome]]
        scs = "s0" in p
        dc = "dmax" in p
        ia = 0.0 if (scs or dc) else p["ia_max"] * math.exp(-qloc / p["qstar"])

        def rep(label, val):
            nonlocal corpo
            corpo, n = re.subn(r"(?m)^(\s*" + re.escape(label) + r": )[^\n]+", lambda mm: mm[1] + val, corpo)
            assert n == 1, (nome, label)
        tc = float(re.search(r"(?m)^\s*Time of Concentration: ([^\n]+)", corpo)[1])
        r = float(re.search(r"(?m)^\s*Storage Coefficient: ([^\n]+)", corpo)[1])
        if dc:
            corpo, n = re.subn(r"(?ms)^\s*Canopy: None\n.*?^\s*Constant Loss Rate: [^\n]+\n",
                               lambda mm: bloco_dc(p, qloc, f"{100 * p['imp']:.3f}"), corpo, count=1)
            assert n == 1, (nome, "bloco de perda")
        elif scs:
            S = max(5.3, p["s0"] * math.exp(-qloc / p["qstar"]))   # piso: o HEC-HMS recusa CN >= 99 (testado: todas as falhas tinham CN >= 99)
            CN = 25400.0 / (S + 254.0)
            corpo, n1 = re.subn(r"(?m)^(\s*)LossRate: Initial\+Constant\n", lambda mm: mm[1] + "LossRate: SCS\n", corpo)
            corpo, n2 = re.subn(r"(?m)^\s*Initial Loss: [^\n]+\n", "", corpo)
            corpo, n3 = re.subn(r"(?m)^(\s*)Constant Loss Rate: [^\n]+", lambda mm: mm[1] + f"Curve Number: {CN:.4f}", corpo)
            assert (n1, n2, n3) == (1, 1, 1), (nome, n1, n2, n3)
        else:
            rep("Initial Loss", f"{ia:.4f}")
            rep("Constant Loss Rate", f"{p['f']:.4f}")
        rep("Percent Impervious Area", f"{100 * p['imp']:.3f}")
        rep("Time of Concentration", f"{tc * v:.5f}")
        rep("Storage Coefficient", f"{r * v * p['mr']:.5f}")
        if "ie" in p:
            rep("Clark Method", "Variable")
            corpo, n = re.subn(r"(?m)^(\s*)(Time Area Method: [^\n]+\n)",
                               lambda mm: (f"{mm[1]}Index Excess: {p['ie']:.4f}\n{mm[1]}Excess-Tc Percentage Curve: VC_TC\n"
                                           f"{mm[1]}Excess-R Percentage Curve: VC_R\n{mm[1]}{mm[2]}"), corpo)
            assert n == 1, (nome, "Clark variável")
        if "k1" in p:
            corpo, n = re.subn(r"(?ms)^[ \t]*Baseflow: Recession\n.*?^[ \t]*Threshold Flow to Peak Ratio: [^\n]+\n",
                               lambda mm: bloco_lr(p, qloc), corpo, count=1)
            assert n == 1, (nome, "bloco de base")
        else:
            rep("Recession Factor", f"{p['rec']:.4f}")
            rep("Initial Flow/Area Ratio", f"{qloc:.6f}")
            rep("Threshold Flow to Peak Ratio", f"{p['thr']:.4f}")
        return f"Subbasin: {m[1]}\n{corpo}End:"

    def rea(m):
        nome, corpo = m[1].strip(), m[2]
        if rota in ("mc", *ROTAS_8PT) and nome in MC_REACHES:
            bloco = bloco_mc8(nome, p) if usa_8pt(nome, rota) else bloco_mc(nome, p["mn"])
            corpo = re.sub(r"(?ms)^\s*Route: Muskingum\n.*?^\s*Channel Loss: None\n", lambda mm: bloco, corpo)
            assert "Muskingum Cunge" in corpo, nome
            return f"Reach: {m[1]}\n{corpo}End:"
        reg = bi.REG[nome]
        v = p["v_alto"] if reg in GRUPO_ALTO else p["v_resto"]
        k = float(re.search(r"(?m)^\s*Muskingum K: ([^\n]+)", corpo)[1]) * v * p["mk"]
        x = float(re.search(r"(?m)^\s*Muskingum x: ([^\n]+)", corpo)[1])
        k = max(k, (hec.PASSO_MIN / 60) / (2 * (1 - x)) + 1e-6)
        corpo = re.sub(r"(?m)^(\s*Muskingum K: )[^\n]+", lambda mm: mm[1] + f"{k:.5f}", corpo)
        corpo = re.sub(r"(?m)^(\s*Muskingum Steps: )[^\n]+", lambda mm: mm[1] + str(hec.passos_muskingum(k, x)), corpo)
        return f"Reach: {m[1]}\n{corpo}End:"

    t = hec.base_text()
    t, ns = re.subn(r"(?ms)^Subbasin: ([^\n]+)\n(.*?)^End:", sub, t)
    t, nr = re.subn(r"(?ms)^Reach: ([^\n]+)\n(.*?)^End:", rea, t)
    assert ns == 145 and nr == 105
    return re.sub(r"(?m)^Basin: [^\n]+", "Basin: " + hec.BASIN_NAME, t, count=1)


def cid3(p, rota="mc"):
    return "v3" + rota + "_" + "_".join(f"{p[k]:.4g}" for k in PARAMS).replace(".", "p")


if __name__ == "__main__":
    print("MC:", len(MC_REACHES), MC_REACHES[:6], "...", MC_REACHES[-3:])
    print({n: round(a) for n, a in sorted(AREA_UP.items(), key=lambda kv: kv[1])})
    from collections import Counter
    print(Counter(CTRL_DE.values()))
