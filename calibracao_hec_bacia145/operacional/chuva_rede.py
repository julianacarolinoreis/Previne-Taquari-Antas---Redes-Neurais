"""Chuva observada ao vivo pela REDE recomendada pela frente de chuva ao vivo (versão 'avtelqc2', branch
cursor/hec-bacia145-aovivo): ANA telemetria (72) + CEMADEN público (66) + INMET (13, só com INMET_TOKEN), sem a
lista negra (dados/postos_rede.json, gerado por preparar_dados.py rede).

  hora H = (H − 1 h, H], BRT (convenção do forcamento_v3)
  ANA      HidroTelemetria em série (429 em paralelo) com backoff; hora só com todos os registros da cadência; relógio
           de Muçum corrigido; > 90 mm/h fora
  CEMADEN  histórico do coletor (cemaden.py, uma leitura a cada 10 min) + uma coleta na hora; hora exata (acc1hr com
           último dado em H:00) ou rateio do menor bloco acumulado (3/6/12… h) — ver cemaden.horarias
  INMET    apitempo com token (variável de ambiente INMET_TOKEN); sem token a fonte é pulada e registrada
  QC causal (avtelqc2): por hora, valor travado (6 h seguidas >= 2 mm com amplitude <= 1 mm) e chuva isolada
           (>= 10 mm com os 3 vizinhos com dado < 1 mm); depois, total das 72 h anteriores vs média dos 3 vizinhos
           (vizinhos > 30 mm e posto < 0,4x ou > 2,5x → posto fora naquela hora)
  IDW p = 2 no centróide (UTM 22S); hora sem nenhum posto (até a última hora observada) = 0, contada em
  horas_sem_estacao; última hora observada = a mais recente com >= max(5, 0,5 x mediana) postos.
"""
import json
import math
import time
from datetime import datetime, timedelta

import numpy as np

import cemaden
import chuva_observada as co
import geo
import inmet
import telemetria_ana as ta

H = timedelta(hours=1)
BRT = timedelta(hours=-3)
TRAVA_H, TRAVA_MIN, TRAVA_AMP = 6, 2.0, 1.0
ISOL_MIN, ISOL_VIZ = 10.0, 1.0
LIM_SUB, LIM_EXC, MIN_VIZ, JAN_QC = 0.4, 2.5, 30.0, 72


def _vizinhos(cs, xy, k=3):
    return {c: sorted((x for x in cs if x != c), key=lambda x: math.dist(xy[c], xy[x]))[:k] for c in cs}


def qc_hora(series, horas, xy, isentas_trava=None):
    """Porta de aovivo/forcamentos.qc_hora (valor travado; chuva isolada). Altera series; devolve {posto: horas fora}.
    isentas_trava: {posto: horas} rateadas por igual (CEMADEN em bloco), que não são valor travado do sensor."""
    cs = sorted(series)
    viz = _vizinhos(cs, xy)
    isentas_trava = isentas_trava or {}
    fora, novo = {}, {}
    for c in cs:
        s, ruins = series[c], set()
        ise = isentas_trava.get(c, set())
        for i, h in enumerate(horas):
            v = s.get(h)
            if v is None:
                continue
            ult = [s.get(x) for x in horas[max(0, i - TRAVA_H + 1):i + 1]]
            if h not in ise and len(ult) == TRAVA_H and all(x is not None and x >= TRAVA_MIN for x in ult) and max(ult) - min(ult) <= TRAVA_AMP:
                ruins.add(h)
                continue
            vv = [series[x].get(h) for x in viz[c]]
            if v >= ISOL_MIN and len(vv) == 3 and all(x is not None and x < ISOL_VIZ for x in vv):
                ruins.add(h)
        novo[c] = {h: v for h, v in s.items() if h not in ruins}
        if ruins:
            fora[c] = len(ruins)
    series.clear()
    series.update({c: s for c, s in novo.items() if s})
    return fora


def qc_causal(series, horas, xy):
    """Porta de aovivo/forcamentos.qc_causal (72 h anteriores vs 3 vizinhos). Altera series; devolve {posto: horas fora}."""
    cs = sorted(series)
    if len(cs) < 4:
        return {}
    viz = _vizinhos(cs, xy)
    V = np.array([[series[c].get(h, np.nan) for c in cs] for h in horas])
    fora = {}
    novo = {c: dict(series[c]) for c in cs}
    for j, c in enumerate(cs):
        iv = [cs.index(x) for x in viz[c]]
        ok = np.isfinite(V[:, j]) & np.isfinite(V[:, iv]).all(1)
        a = np.where(ok, V[:, j], 0.0).cumsum()
        b = np.where(ok, np.nanmean(np.where(ok[:, None], V[:, iv], 0.0), 1), 0.0).cumsum()
        A = a - np.r_[np.zeros(JAN_QC), a[:-JAN_QC]] if len(a) > JAN_QC else a
        B = b - np.r_[np.zeros(JAN_QC), b[:-JAN_QC]] if len(b) > JAN_QC else b
        ruim = (B > MIN_VIZ) & ((A < LIM_SUB * B) | (A > LIM_EXC * B)) & np.isfinite(V[:, j])
        for i in np.where(ruim)[0]:
            novo[c].pop(horas[i], None)
        if ruim.any():
            fora[c] = int(ruim.sum())
    series.clear()
    series.update({c: s for c, s in novo.items() if s})
    return fora


class RedeAoVivo(co.FonteChuvaObservada):
    nome = "rede ao vivo ANA + CEMADEN + INMET (QC causal avtelqc2, IDW p=2)"

    def __init__(self, pasta_cemaden=None, coletar_agora=True, paralelo_ana=1, min_estacoes_hora=5,
                 frac_ultima_hora=0.5, rede=None, fontes=("ANA", "CEMADEN", "INMET")):
        r = rede or json.loads((geo.DADOS / "postos_rede.json").read_text(encoding="utf-8"))
        self.negra = set(r.get("lista_negra", []))
        self.postos = {c: p for c, p in r["postos"].items() if c not in self.negra and p["fonte"] in fontes}
        self.pasta_cem, self.coletar_agora = pasta_cemaden, coletar_agora
        self.paralelo, self.min_est, self.frac = paralelo_ana, min_estacoes_hora, frac_ultima_hora
        self.fontes = fontes

    def _fonte(self, c):
        return self.postos[c]["fonte"]

    def obter(self, ini, ate, contexto=None):
        contexto = contexto or {}
        corrige = contexto.get("corrige_relogio", lambda c, t: t)
        horas = co.grade(ini, ate)
        series, info, tempos = {}, {}, {}

        # ANA
        t = time.time()
        ana = sorted(c for c in self.postos if self._fonte(c) == "ANA")
        extra = sorted(set(contexto.get("postos_extra", [])) - set(ana))
        n429 = ta.N_429[0]
        regs, falhas = ta.baixar_varios(ana + extra, ini - H, ate, self.paralelo) if ana or extra else ({}, {})
        susp, cad = {}, {}
        for c in ana:
            s, k, sp = co.chuva_horaria(regs.get(c, {}), horas, corrige=lambda t_, c=c: corrige(c, t_), tolerar=False)
            cad[c] = k
            if sp:
                susp[c] = sp
            if s:
                series[c] = s
        info["ANA"] = dict(consultados=len(ana), com_registro=sum(1 for c in ana if regs.get(c)),
                           com_chuva_horaria=sum(1 for c in ana if c in series), falhas_rede=falhas,
                           respostas_429=ta.N_429[0] - n429, horas_acima_90mm=susp,
                           cadencia_min={c: k for c, k in cad.items() if k})
        tempos["ANA"] = round(time.time() - t, 1)

        # CEMADEN
        t = time.time()
        cem = sorted(c for c in self.postos if self._fonte(c) == "CEMADEN")
        rateio = {}
        if cem:
            ini_u, ate_u = ini - BRT, ate - BRT
            coletas = cemaden.ler(self.pasta_cem, ini_u, ate_u) if self.pasta_cem else []
            n_hist = len(coletas)
            erro = None
            if self.coletar_agora:
                inst, est, n_pub, erro = cemaden.coletar()
                if est:
                    coletas.append((inst, est))
                    if self.pasta_cem:
                        cemaden.gravar(self.pasta_cem, inst, est, dict(n_publicas=n_pub, origem="ciclo"))
            sc, ic, rateio = cemaden.horarias(coletas, horas)
            for c in cem:
                s = {h: v for h, v in sc.get(c, {}).items() if 0 <= v <= co.MAX_MM_H}
                if s:
                    series[c] = s
            soma = {k: sum(v[k] for c, v in ic.items() if c in cem) for k in ("exatas", "aproximadas", "bloco")}
            info["CEMADEN"] = dict(consultados=len(cem), com_dado=sum(1 for c in cem if c in ic),
                                   com_chuva_horaria=sum(1 for c in cem if c in series), coletas_historico=n_hist,
                                   pasta_historico=str(self.pasta_cem) if self.pasta_cem else None,
                                   coleta_agora=self.coletar_agora, erro_coleta=erro,
                                   horas_exatas=soma["exatas"], horas_leitura_ate_30min=soma["aproximadas"],
                                   horas_por_bloco=soma["bloco"],
                                   ultima_coleta_utc=str(max(c[0] for c in coletas)) if coletas else None)
        tempos["CEMADEN"] = round(time.time() - t, 1)

        # INMET
        t = time.time()
        inm = sorted(c for c in self.postos if self._fonte(c) == "INMET")
        if inm:
            tk = inmet.token()
            if not tk:
                info["INMET"] = dict(consultados=0, pulado="sem INMET_TOKEN no ambiente")
            else:
                fal = {}
                for c in inm:
                    s, e = inmet.baixar(c.split("_", 1)[1], ini, ate, tk)
                    if e:
                        fal[c] = e
                    s = {h: v for h, v in s.items() if h in set(horas) and v <= co.MAX_MM_H}
                    if s:
                        series[c] = s
                info["INMET"] = dict(consultados=len(inm), com_chuva_horaria=sum(1 for c in inm if c in series),
                                     falhas_rede=fal)
        tempos["INMET"] = round(time.time() - t, 1)

        # QC causal + IDW
        cs = sorted(self.postos)
        xs, ys = geo.utm22s([self.postos[c]["lon"] for c in cs], [self.postos[c]["lat"] for c in cs])
        xy = {c: (x, y) for c, x, y in zip(cs, xs, ys)}
        fora_h = qc_hora(series, horas, xy, rateio)
        fora_c = qc_causal(series, horas, xy)
        codes = sorted(series)
        n_est = [sum(1 for c in codes if h in series[c]) for h in horas]
        ref = float(np.median(n_est)) if n_est else 0.0
        ok_h = [i for i, n in enumerate(n_est) if n >= max(self.min_est, self.frac * ref)]
        ate_obs = horas[ok_h[-1]] if ok_h else ini - H
        sub = geo.subbacias()
        nomes = geo.nomes()
        px, py = geo.utm22s([sub[n]["lon"] for n in nomes], [sub[n]["lat"] for n in nomes])
        chuva = {n: [] for n in nomes}
        sem = []
        if codes:
            sx = np.array([xy[c][0] for c in codes])
            sy = np.array([xy[c][1] for c in codes])
            w = 1 / np.maximum(np.hypot(px[:, None] - sx, py[:, None] - sy), 1.0) ** 2
        for i, h in enumerate(horas):
            if h > ate_obs:
                for n in nomes:
                    chuva[n].append(None)
                continue
            vals = np.array([series[c].get(h, np.nan) for c in codes]) if codes else np.array([])
            ok = np.isfinite(vals)
            if ok.sum() < 1:
                sem.append(str(h))
                for n in nomes:
                    chuva[n].append(0.0)
                continue
            v = (w[:, ok] @ vals[ok]) / w[:, ok].sum(axis=1)
            for j, n in enumerate(nomes):
                chuva[n].append(round(float(v[j]), 4))
        por_fonte_h = {f: [sum(1 for c in codes if self._fonte(c) == f and h in series[c]) for h in horas]
                       for f in self.fontes}
        degradado = [str(h) for h, n in zip(horas, n_est) if h <= ate_obs and n < 10]
        cob = dict(rede="dados/postos_rede.json", lista_negra=sorted(self.negra), por_fonte=info,
                   postos_usados=codes, postos_usados_por_fonte={f: sum(1 for c in codes if self._fonte(c) == f)
                                                                 for f in self.fontes},
                   qc_horas_fora_trava_ou_isolada=fora_h, qc_horas_fora_72h_vizinhos=fora_c,
                   estacoes_por_hora=n_est, estacoes_por_hora_por_fonte=por_fonte_h,
                   horas_sem_estacao=sem, horas_degradadas_menos_10_postos=degradado,
                   ultima_hora_pedida=str(ate), ultima_hora_observada=str(ate_obs),
                   regra_ultima_hora=f">= max({self.min_est}, {self.frac} x mediana de estacoes/hora)",
                   tempos_s=tempos)
        return co.ChuvaObservada(horas=horas, chuva=chuva, ate=ate_obs, fonte=self.nome, cobertura=cob, registros=regs)
