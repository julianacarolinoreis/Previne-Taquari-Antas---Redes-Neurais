"""Calibração HEC-HMS da bacia Taquari-Antas inteira, com biblioteca de modelos.

- Controles: todos os postos com vazão utilizável (SGB e UHEs CERAN). Em Muçum e Encantado a
  vazão só é usada abaixo do limite da curva-chave e o horário do pico vem do NÍVEL.
- Parâmetros: velocidade de resposta por região (Tc, R e K juntos) + globais (perdas, forma, base).
- Biblioteca: o melhor conjunto para CADA evento de calibração + o melhor compromisso.
  Na previsão, escolhe-se o membro que melhor reproduz as últimas horas observadas (testado à parte).
"""
import json
import math
import random
import re
import sys
import time
from datetime import timedelta

from comum import AQUI, EVENTOS, RESULT, RUNS, SIMULACOES
import hec
from metricas import ALVO, horas

# nome: (código ANA, nó do modelo, limite da curva em cm ou None, usa no objetivo?)
CONTROLES = {
    "TAINHAS":        ("86160000", "J_106", None, True),
    "CASTRO_ALVES":   ("86305000", "J_211", None, True),
    "MONTE_CLARO":    ("86448000", "J_236", None, True),
    # 14 de Julho fora do objetivo: a curva de LJJ é derivada da defluente da 14J (mesma informação)
    # e em jun/2024 a série da 14J é cópia de Monte Claro deslocada 1 h (revisão 06/10/2026).
    "QUATORZE_JULHO": ("86470800", "J_213", None, False),
    "LJJ":            ("86472000", "J_208", 1800, True),   # curva SGB de LJJ vale até 18 m
    "MUCUM":          ("86510000", "J_201", 1500, True),   # razões ENC/MUC e MUC/LJJ mudam acima de ~15 m
    "ENCANTADO":      ("86720000", "J_258", 1920, True),
    "ESTRELA":        ("86879300", "J_189", None, False),
    "PASSO_CARREIRO": ("86500000", "J_254", None, False),
    "LINHA_COLOMBO":  ("86560000", "J_220", None, False),
}
NOS_REGIAO = {"J_106": "tainhas", "J_211": "alto", "J_236": "medio", "J_201": "carreiro", "J_258": "guapore"}
REGIOES = ["tainhas", "alto", "medio", "carreiro", "guapore", "baixo"]

PARAMS = {
    "ia": (0.0, 60.0, "lin"), "f": (0.5, 6.0, "log"),
    "mr": (0.4, 2.5, "log"),    # R relativo ao Tc (forma do hidrograma das sub-bacias)
    "mk": (0.4, 2.5, "log"),    # K relativo à velocidade da região (calha x encosta)
    "rec": (0.70, 0.97, "lin"), "thr": (0.05, 0.40, "lin"),
    **{f"v_{r}": (0.25, 2.0, "log") for r in REGIOES},  # multiplicador de tempo por região (menor = mais rápido)
}
CAL_EVENTOS = ["E4", "E5", "E12", "E18", "E22"]
SIMS_CAL = sorted({EVENTOS[e]["sim"] for e in CAL_EVENTOS})
LOG = RESULT / "bacia_inteira_avaliacoes.jsonl"


def _regioes():
    txt = hec.base_text()
    down = {}
    for m in re.finditer(r"(?ms)^(Subbasin|Reach|Junction|Sink): ([^\n]+)\n(.*?)^End:", txt):
        d = re.search(r"(?m)^\s*Downstream:\s*([^\n]+)", m[3])
        down[m[2].strip()] = d[1].strip() if d else None
    reg = {}
    for n0 in down:
        if n0.startswith("J_"):
            continue
        n, r = n0, "baixo"
        while n:
            if n in NOS_REGIAO:
                r = NOS_REGIAO[n]
                break
            n = down.get(n)
        reg[n0] = r
    return reg


REG = _regioes()


def bacia_bi(p, init_ratio):
    def sub(m):
        nome, corpo = m[1].strip(), m[2]
        v = p["v_" + REG[nome]]

        def rep(label, val):
            nonlocal corpo
            corpo, n = re.subn(r"(?m)^(\s*" + re.escape(label) + r": )[^\n]+", lambda mm: mm[1] + val, corpo)
            assert n == 1, (nome, label)
        tc = float(re.search(r"(?m)^\s*Time of Concentration: ([^\n]+)", corpo)[1])
        r = float(re.search(r"(?m)^\s*Storage Coefficient: ([^\n]+)", corpo)[1])
        rep("Initial Loss", f"{p['ia']:.4f}")
        rep("Constant Loss Rate", f"{p['f']:.4f}")
        rep("Percent Impervious Area", f"{100 * p.get('imp', 0.0):.3f}")   # fração impermeável (escoamento direto); 0 = como antes
        rep("Time of Concentration", f"{tc * v:.5f}")
        rep("Storage Coefficient", f"{r * v * p['mr']:.5f}")
        rep("Recession Factor", f"{p['rec']:.4f}")
        rep("Initial Flow/Area Ratio", f"{init_ratio:.6f}")
        rep("Threshold Flow to Peak Ratio", f"{p['thr']:.4f}")
        return f"Subbasin: {m[1]}\n{corpo}End:"

    def rea(m):
        nome, corpo = m[1].strip(), m[2]
        k = float(re.search(r"(?m)^\s*Muskingum K: ([^\n]+)", corpo)[1]) * p["v_" + REG[nome]] * p["mk"]
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


# ------------------------------------------------------------------ métricas
UHES = {"86305000", "86448000", "86470800"}


def obs_limpo(sim, cod):
    """Vazão observada sem os defeitos das séries das UHEs: zeros (falhas de transmissão),
    pontos isolados sem vizinho válido em ±2 h e cópia da 14 de Julho = Monte Claro(t-1 h)."""
    obs = hec.observado(sim, cod)
    if cod not in UHES:
        return obs
    o = {t: q for t, q in obs.items() if q > 0}
    o = {t: q for t, q in o.items()
         if any(t + timedelta(hours=k) in o for k in (-2, -1, 1, 2))}
    if cod == "86470800":
        mc = hec.observado(sim, "86448000")
        iguais = sum(1 for t, q in o.items() if mc.get(t - timedelta(hours=1)) == q)
        if o and iguais > 0.5 * len(o):
            return {}
    return o


def avaliar_ctrl(evento, nome, simq):
    ev = EVENTOS[evento]
    cod, node, limite, no_obj = CONTROLES[nome]
    obs = obs_limpo(ev["sim"], cod)
    niv = hec.nivel(ev["sim"], cod)
    q = simq.get(node, {})
    hs = list(horas(ev["ini"], ev["fim"]))
    ok_q = (lambda t: niv.get(t, 1e9) <= limite) if limite else (lambda t: True)
    pares = [(t, obs[t], q[t]) for t in hs if t in obs and t in q and ok_q(t)]
    if len(pares) < max(12, 0.5 * len(hs)) and not (limite and len(pares) >= 12):
        return None
    o, s = [x[1] for x in pares], [x[2] for x in pares]
    mo = sum(o) / len(o)
    sst = sum((a - mo) ** 2 for a in o)
    if sst <= 0:
        return None
    nse = 1 - sum((a - b) ** 2 for a, b in zip(s, o)) / sst
    vol = sum(s) / sum(o) - 1
    # pico: por nível quando há limite de curva (Muçum/Encantado), senão pela vazão
    serie_pico = niv if limite else obs
    hs_p = [t for t in hs if t in serie_pico]
    tpo = max(hs_p, key=lambda t: serie_pico[t]) if hs_p else None
    completo = (tpo is not None and all(tpo + timedelta(hours=k) in serie_pico for k in range(-6, 7))
                and ev["ini"] < tpo < ev["fim"] and nome not in ev.get("sem_pico", set()))
    # pico simulado procurado na MESMA onda: ±24 h em torno do pico observado (evita "troca de pico")
    if tpo is not None:
        sim_ev = {t: q[t] for t in hs if t in q and abs((t - tpo).total_seconds()) <= 24 * 3600}
    else:
        sim_ev = {t: q[t] for t in hs if t in q}
    tps, qps = max(sim_ev.items(), key=lambda kv: kv[1])
    mag_ok = completo and tpo in obs and (not limite or niv[tpo] <= limite)
    m = dict(evento=evento, controle=nome, papel=ev["papel"], objetivo=no_obj, pares=len(pares), horas=len(hs),
             nse=nse, vol=vol, pico_obs=obs.get(tpo) if tpo else None, t_pico_obs=str(tpo), pico_sim=qps,
             t_pico_sim=str(tps), pico_completo=mag_ok,
             erro_pico=(qps / obs[tpo] - 1) if mag_ok else None,
             lag_h=((tps - tpo).total_seconds() / 3600) if completo else None)
    j = (1 - nse) / (1 - ALVO["nse"]) + abs(vol) / ALVO["vol"]
    if m["erro_pico"] is not None:
        j += abs(m["erro_pico"]) / ALVO["pico"]
    if m["lag_h"] is not None:
        j += abs(m["lag_h"]) / ALVO["lag"]
    m["pen"] = min(j, 60.0)  # limita o peso de um único controle muito ruim
    m["passa"] = (nse >= ALVO["nse"] and abs(vol) <= ALVO["vol"]
                  and (m["erro_pico"] is None or abs(m["erro_pico"]) <= ALVO["pico"])
                  and (m["lag_h"] is None or abs(m["lag_h"]) <= ALVO["lag"]))
    return m


def avaliar_sim(sim, simq):
    out = []
    for e, v in EVENTOS.items():
        if v["sim"] != sim:
            continue
        for nome in CONTROLES:
            m = avaliar_ctrl(e, nome, simq)
            if m:
                out.append(m)
    return out


def J_evento(mets, e):
    ms = [m for m in mets if m["evento"] == e and m["objetivo"]]
    return sum(m["pen"] for m in ms) / len(ms) if ms else float("inf")


# ------------------------------------------------------------------ busca
def to_unit(p):
    return {k: (math.log(p[k] / a) / math.log(b / a)) if s == "log" else (p[k] - a) / (b - a)
            for k, (a, b, s) in PARAMS.items()}


def from_unit(u):
    p = {}
    for k, (a, b, s) in PARAMS.items():
        x = min(1.0, max(0.0, u[k]))
        p[k] = a * (b / a) ** x if s == "log" else a + x * (b - a)
    return p


def cid_of(p):
    return "bi_" + "_".join(f"{p[k]:.4g}" for k in PARAMS).replace(".", "p") + (f"_imp{p['imp']:.4g}".replace(".", "p") if p.get("imp") else "")


def avaliar(cands, sims=SIMS_CAL, paralelo=20, por_jvm=4):
    hec.NOS_EXTRA = sorted({c[1] for c in CONTROLES.values()})
    jobs, idx = [], []
    for p in cands:
        for s in sims:
            jobs.append((RUNS / cid_of(p) / s, s, bacia_bi(p, hec.razao_inicial(s))))
            idx.append((cid_of(p), p))
    res = hec.rodar_lote(jobs, paralelo=paralelo, por_jvm=por_jvm)
    por = {}
    for (d, s, _), (cid, p) in zip(jobs, idx):
        e = por.setdefault(cid, {"cid": cid, "p": p, "metricas": [], "erros": []})
        r = res[d]
        if isinstance(r, Exception):
            e["erros"].append(f"{s}: {r}")
        else:
            e["metricas"] += avaliar_sim(s, r)
    out = []
    for e in por.values():
        e["J_ev"] = {ev: (J_evento(e["metricas"], ev) if not e["erros"] else float("inf")) for ev in CAL_EVENTOS}
        e["J"] = sum(e["J_ev"].values()) / len(CAL_EVENTOS)
        out.append(e)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as h:
        for e in out:
            h.write(json.dumps(e, default=str) + "\n")
    return out


def main(geracoes=10, por_alvo=4, mu=5, semente=11):
    rnd = random.Random(semente)
    alvos = CAL_EVENTOS + ["compromisso"]
    base = dict(ia=0, f=3, mr=1, mk=1, rec=0.8, thr=0.1, **{f"v_{r}": 1.0 for r in REGIOES})
    rapido = dict(base, ia=25, f=2.5, **{"v_alto": 0.5, "v_tainhas": 0.6, "v_medio": 0.6})
    todos = []
    if LOG.exists():  # retomada
        todos = [json.loads(x) for x in LOG.open(encoding="utf-8")]
    if not todos:
        ini = [base, rapido] + [from_unit({k: rnd.random() for k in PARAMS}) for _ in range(30)]
        t0 = time.time()
        todos += avaliar(ini)
        print(f"G0 {time.time() - t0:.0f}s", flush=True)
    sig = {a: 0.18 for a in alvos}
    chave = lambda a: (lambda e: e["J"]) if a == "compromisso" else (lambda e: e["J_ev"][a])
    for g in range(1, geracoes + 1):
        filhos = []
        for a in alvos:
            el = sorted(todos, key=chave(a))[:mu]
            w = [math.log(mu + 0.5) - math.log(i + 1) for i in range(mu)]
            us = [to_unit(e["p"]) for e in el]
            med = {k: sum(wi * u[k] for wi, u in zip(w, us)) / sum(w) for k in PARAMS}
            filhos += [from_unit({k: med[k] + rnd.gauss(0, sig[a]) for k in PARAMS}) for _ in range(por_alvo)]
        antes = {a: chave(a)(sorted(todos, key=chave(a))[0]) for a in alvos}
        t0 = time.time()
        novos = avaliar(filhos)
        todos += novos
        for a in alvos:
            if chave(a)(sorted(todos, key=chave(a))[0]) >= antes[a]:
                sig[a] = max(0.04, sig[a] * 0.8)
        linha = " ".join(f"{a}={chave(a)(sorted(todos, key=chave(a))[0]):.2f}" for a in alvos)
        print(f"G{g} {time.time() - t0:.0f}s | melhores: {linha}", flush=True)
    biblioteca = {a: sorted(todos, key=chave(a))[0] for a in alvos}
    (RESULT / "biblioteca_bacia_inteira.json").write_text(
        json.dumps({a: {"cid": e["cid"], "p": e["p"], "J": e["J"], "J_ev": e["J_ev"]} for a, e in biblioteca.items()},
                   indent=1, default=str), encoding="utf-8")
    print("FIM_BIBLIOTECA", flush=True)


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:]))
