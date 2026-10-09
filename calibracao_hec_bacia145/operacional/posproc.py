"""Pós-processamento: correção aditiva hora a hora pelo último observado válido, vazão → nível pelos pares da telemetria,
cotas de Muçum e resumo de conjunto (ensemble). Mesmas regras de _analise_bacia145/correcao/horaria/correcao_horaria.py:

  Q(t) = S(t) + e(tv)·exp(−(t − tv)/τ(h)),  h = t − t0 (1…48 h; depois, τ(48)),  saída ≥ 1 m³/s
  tv = último observado válido até t0 (vazão > 0 e nível ≤ limite da curva-chave), procurado até 72 h para trás;
  sem observado válido → série bruta.
  Curva: pares (nível, vazão) da própria janela; fora da faixa, a curva agregada das janelas do catálogo (sem a de
  teste) deslocada para encostar na ponta.

Encaixe: ciclo.py chama ponto() → cotas_mucum() → resumo_conjunto(); outra correção (ex.: assimilação, outra curva)
entra substituindo ponto() com as mesmas chaves de saída (observado, simulado, corrigido, nivel_previsto_cm).

Híbrido em SOMBRA (d_piv; não muda nada do que é publicado, só acrescenta `hibrido_sombra` ao ponto), quando o conjunto
de parâmetros tem parametros/hibrido_<id>.json:
  F(S) = S·(min(S, qmax)/q0)^(b−1) se S > q0, senão S; F/S limitado a [1/rmax, rmax]
  Q(t) = F(S(t)) + (O(tv) − F(S(tv)))·exp(−(t − tv)/τd),  saída ≥ 1 m³/s  (mesmo tv da correção aditiva)
"""
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

import geo

H = timedelta(hours=1)
PONTOS = {   # nome: (código ANA, nó do modelo, limite da curva em cm ou None, corrigir?)
    "LJJ": ("86472000", "J_208", 1800, True),
    "MUCUM": ("86510000", "J_201", 1500, True),
    "ENCANTADO": ("86720000", "J_258", 1920, True),
    "ESTRELA": ("86879300", "J_189", None, False),   # sem estudo de correção nem curva: só simulado e observado
}
COTAS_MUCUM_CM = {"atencao_5m": 500, "alerta_10m": 1000, "limite_curva_15m": 1500, "inundacao_18m": 1800}


def carregar_config(parametros=None):
    """τ(h) da correção: o do conjunto de parâmetros (chave 'correcao'), senão o de dados/correcao.json (lr-g8-c038)."""
    corr = (parametros or {}).get("correcao") or json.loads((geo.DADOS / "correcao.json").read_text(encoding="utf-8"))
    curvas = json.loads((geo.DADOS / "curvas_telemetria.json").read_text(encoding="utf-8"))
    return corr, curvas


class Curva:
    """Porta de correcao_horaria.Curva: (h, q) da janela e (hp, qp) agregada."""

    def __init__(self, pares, pool):
        if pares:
            a = np.array(sorted(pares))
            h, q = a[:, 0], np.maximum.accumulate(a[:, 1])
            _, i = np.unique(h, return_index=True)
            self.h, self.q = h[i], q[i]
        else:
            self.h, self.q = np.array([]), np.array([])
        self.hp, self.qp = np.array(pool["nivel_cm"]), np.array(pool["vazao_m3s"])

    def h2q(self, x):
        if len(self.h) and self.h[0] <= x <= self.h[-1]:
            return float(np.interp(x, self.h, self.q))
        if not len(self.h):
            return float(np.interp(x, self.hp, self.qp))
        acima = x > self.h[-1]
        d = (self.h[-1] - np.interp(self.q[-1], self.qp, self.hp)) if acima else (
            self.h[0] - np.interp(self.q[0], self.qp, self.hp))
        return float(np.interp(x - d, self.hp, self.qp))

    def q2h(self, y):
        if len(self.q) and self.q[0] <= y <= self.q[-1]:
            return float(np.interp(y, self.q, self.h))
        if not len(self.q):
            return float(np.interp(y, self.qp, self.hp))
        ref = self.q[-1] if y > self.q[-1] else self.q[0]
        d = (self.h[-1] if y > self.q[-1] else self.h[0]) - np.interp(ref, self.qp, self.hp)
        return float(np.interp(y, self.qp, self.hp) + d)


def _r(x, n=1):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), n)


def curva_ponto(nome, t0, obs_q, obs_n, curvas):
    if nome not in curvas:
        return None
    pares = [(obs_n[t], obs_q[t]) for t in obs_q if t <= t0 and t in obs_n and obs_q[t] and obs_q[t] > 0
             and obs_n[t] is not None]
    return Curva(pares, curvas[nome])


def ponto(nome, horas, t0, sims, obs_q, obs_n, corr, curvas, horizonte_h, busca_h=72, aditiva=True):
    """sims: {cenario: {t: q}} (10 min); obs_q/obs_n: {t: valor} (só até t0 para a correção).
    aditiva=False: 'corrigido' = simulado (estado já assimilado; a correção aditiva dobraria o ajuste)."""
    cod, no, lim, corrigir = PONTOS[nome]
    O = [obs_q.get(t) for t in horas]
    N = [obs_n.get(t) for t in horas]

    def valido(i):
        return (O[i] is not None and O[i] > 0 and horas[i] <= t0
                and (lim is None or (N[i] is not None and N[i] <= lim)))
    j0 = horas.index(t0)
    tv = next((i for i in range(j0, -1, -1) if valido(i) and (t0 - horas[i]) <= busca_h * H), None)
    out = dict(codigo=cod, no_modelo=no, limite_curva_cm=lim,
               observado=dict(vazao_m3s=[_r(x) for x in O], nivel_cm=[_r(x) for x in N]),
               simulado={c: [_r(s.get(t)) for t in horas] for c, s in sims.items()})
    if not corrigir:
        out["correcao"] = "não aplicada (sem estudo de correção neste posto)"
        return out
    tau_h = corr["tau_h"][nome]
    curva = curva_ponto(nome, t0, obs_q, obs_n, curvas)
    out["ultimo_observado_valido"] = None if tv is None else dict(
        t=str(horas[tv]), vazao_m3s=_r(O[tv]), nivel_cm=_r(N[tv]), idade_h=(t0 - horas[tv]) / H)
    out["corrigido"], out["nivel_previsto_cm"], out["erro_em_tv_m3s"] = {}, {}, {}
    for c, s in sims.items():
        S = [s.get(t) for t in horas]
        e = (O[tv] - S[tv]) if (aditiva and tv is not None and S[tv] is not None) else 0.0
        out["erro_em_tv_m3s"][c] = _r(e)
        F = []
        for i, t in enumerate(horas):
            if t <= t0 or S[i] is None:
                F.append(None)
                continue
            h = round((t - t0) / H)
            tau = tau_h[min(h, len(tau_h)) - 1]
            k = (t - horas[tv]) / H if tv is not None else 0.0
            F.append(max(S[i] + e * math.exp(-k / tau), 1.0))
        out["corrigido"][c] = [_r(x) for x in F]
        if curva is not None:
            out["nivel_previsto_cm"][c] = [None if x is None else _r(curva.q2h(x), 0) for x in F]
    out["tau_h_usado"] = {"1h": tau_h[0], "6h": tau_h[5], "24h": tau_h[23], "48h+": tau_h[-1]}
    if not aditiva:
        out["correcao"] = "estado assimilado no fim do observado; sem correção aditiva"
    if curva is not None:
        out["curva"] = dict(pares_da_janela=len(curva.h), faixa_janela_cm=[_r(curva.h[0], 0), _r(curva.h[-1], 0)]
                            if len(curva.h) else None, agregada_janelas=len(curvas[nome]["janelas"]))
    return out


def cotas_mucum(p, horas, t0):
    """Primeiro cruzamento de cada cota (pela vazão da cota na curva) e pico previsto, por cenário."""
    res = {}
    for c, niv in p.get("nivel_previsto_cm", {}).items():
        F = p["corrigido"][c]
        fut = [(t, q, n) for t, q, n in zip(horas, F, niv) if t > t0 and q is not None]
        if not fut:
            continue
        tm, qm, nm = max(fut, key=lambda x: x[1])
        r = dict(pico_vazao_m3s=_r(qm), pico_nivel_cm=_r(nm, 0), t_pico=str(tm),
                 pico_acima_validade=bool(nm is not None and nm > 1500), cotas={})
        for nome, cm in COTAS_MUCUM_CM.items():
            x = next(((t, n) for t, q, n in fut if n is not None and n >= cm), None)
            r["cotas"][nome] = dict(cota_cm=cm, cruza=x is not None, primeiro_cruzamento=str(x[0]) if x else None,
                                    antecedencia_h=((x[0] - t0) / H) if x else None,
                                    indicativo=cm > 1500)
        res[c] = r
    return res


def resumo_conjunto(p, cenarios, horas, t0):
    """Para cenários com o mesmo `grupo` (ensemble): quantis ponderados da vazão corrigida e probabilidade de cada cota."""
    grupos = {}
    for c in cenarios:
        if c.grupo:
            grupos.setdefault(c.grupo, []).append(c)
    out = {}
    for g, cs in grupos.items():
        if len(cs) < 2 or not all(c.id in p.get("corrigido", {}) for c in cs):
            continue
        w = np.array([c.peso for c in cs], float)
        w /= w.sum()
        M = np.array([[np.nan if x is None else x for x in p["corrigido"][c.id]] for c in cs])
        q = {}
        for nome, a in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9)):
            col = []
            for j in range(M.shape[1]):
                v = M[:, j]
                ok = np.isfinite(v)
                if not ok.any():
                    col.append(None)
                    continue
                o = np.argsort(v[ok])
                cw = np.cumsum(w[ok][o]) / w[ok].sum()
                col.append(_r(v[ok][o][np.searchsorted(cw, a)]))
            q[nome] = col
        out[g] = dict(membros=len(cs), quantis_vazao_corrigida=q)
        if "nivel_previsto_cm" in p:
            prob = {}
            for nome, cm in COTAS_MUCUM_CM.items():
                cruza = [any(n is not None and n >= cm for t, n in zip(horas, p["nivel_previsto_cm"][c.id]) if t > t0)
                         for c in cs]
                prob[nome] = _r(float(np.dot(w, cruza)), 3)
            out[g]["probabilidade_cota"] = prob
    return out


# ------------------------------------------------------------------ híbrido em sombra (d_piv)
def carregar_sombra(parametros, opcao="auto"):
    """opcao: 'auto' = parametros/hibrido_<id>.json se existir; 'nao' = desligado; ou o caminho de um arquivo.
    Devolve (config ou None, motivo). O arquivo só vale para o conjunto (id + sha256_p) a que está ligado."""
    if opcao == "nao":
        return None, "desligado (--sombra nao)"
    arq = geo.DADOS.parent / "parametros" / f"hibrido_{parametros['id']}.json" if opcao == "auto" else Path(opcao)
    if not arq.exists():
        return None, f"sem parâmetros do híbrido para {parametros['id']}"
    cfg = json.loads(arq.read_text(encoding="utf-8"))
    if cfg["modelo"] != parametros["id"] or cfg.get("sha256_p") != parametros.get("sha256_p"):
        return None, (f"{arq.name} é de {cfg['modelo']} (sha256_p {cfg.get('sha256_p')}), não de "
                      f"{parametros['id']} ({parametros.get('sha256_p')})")
    cfg["arquivo"] = arq.name
    return cfg, "ligado"


def f_piv(s, q0, b, qmax, rmax=3.0):
    """Fator de porte: identidade até q0, S·(S/q0)^(b−1) acima, fator congelado acima de qmax."""
    if s <= q0:
        return s
    f = s * (min(s, qmax) / q0) ** (b - 1)
    return min(max(f, s / rmax), s * rmax)


def d_piv(S, horas, tv, O_tv, q0, b, qmax, tau_h, t0, rmax=3.0):
    """Série do híbrido (None até t0 e onde S falta); sem observado válido (tv None) fica só F(S)."""
    e = 0.0
    if tv is not None and S[tv] is not None:
        e = O_tv - f_piv(S[tv], q0, b, qmax, rmax)
    out = []
    for i, t in enumerate(horas):
        if t <= t0 or S[i] is None:
            out.append(None)
            continue
        k = (t - horas[tv]) / H if tv is not None else 0.0
        out.append(max(f_piv(S[i], q0, b, qmax, rmax) + e * math.exp(-k / tau_h), 1.0))
    return out, e


def sombra_ponto(p, nome, horas, t0, sims, obs_q, obs_n, curvas, cfg):
    """Bloco `hibrido_sombra` de um ponto (ou None se o ponto não está no arquivo). Não altera `p`."""
    lim = PONTOS[nome][2]
    uv = p.get("ultimo_observado_valido")
    tv = None if uv is None else horas.index(datetime.fromisoformat(uv["t"]))
    O_tv = None if tv is None else obs_q[horas[tv]]
    curva = curva_ponto(nome, t0, obs_q, obs_n, curvas)
    rmax = cfg.get("rmax", 3.0)
    res = {}
    for var, v in cfg["variantes"].items():
        pp_ = v["pontos"].get(nome)
        if pp_ is None:
            continue
        r = dict(q0=pp_["q0"], b=pp_["b"], qmax=pp_["qmax"], tau_h=pp_["tau_h"],
                 fator_maximo=_r((pp_["qmax"] / pp_["q0"]) ** (pp_["b"] - 1), 3),
                 erro_em_tv_m3s={}, corrigido={}, nivel_previsto_cm={}, pico={})
        for c, s in sims.items():
            S = [s.get(t) for t in horas]
            F, e = d_piv(S, horas, tv, O_tv, pp_["q0"], pp_["b"], pp_["qmax"], pp_["tau_h"], t0, rmax)
            r["erro_em_tv_m3s"][c] = _r(e)
            r["corrigido"][c] = [_r(x) for x in F]
            niv = [None if x is None or curva is None else _r(curva.q2h(x), 0) for x in F]
            if curva is not None:
                r["nivel_previsto_cm"][c] = niv
            fut = [(t, q, n, x) for t, q, n, x in zip(horas, F, niv, S) if q is not None]
            if fut:
                tm, qm, nm, _ = max(fut, key=lambda x: x[1])
                r["pico"][c] = dict(pico_vazao_m3s=_r(qm), pico_nivel_cm=_r(nm, 0), t_pico=str(tm),
                                    curva_extrapolada=bool(lim and nm is not None and nm > lim),
                                    fator_congelado=any(x > pp_["qmax"] for *_, x in fut))
        res[var] = r
    if not res:
        return None
    return dict(metodo=cfg["metodo"], modelo=cfg["modelo"], arquivo=cfg["arquivo"], limite_curva_cm=lim,
                horizonte_avaliado_h=cfg.get("horizonte_avaliado_h"),
                aviso="SOMBRA — não publicado; comparar com `corrigido` (correção aditiva)", variantes=res)
