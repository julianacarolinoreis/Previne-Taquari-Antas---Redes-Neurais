"""Fontes de chuva OBSERVADA por sub-bacia (hora H = soma de (H − 1 h, H], hora local).

Interface (para plugar a chuva ao vivo da outra frente sem mexer no resto):
    fonte.obter(ini, ate, contexto) -> ChuvaObservada
`ate` é a última hora que pode ser observada (t0); a fonte devolve até onde de fato tem dado (`ChuvaObservada.ate`).
Lacuna nunca vira zero aqui: hora sem estação fica None e o montador do forçamento decide (e registra).

Implementações:
  TelemetriaANA     — postos ANA da rede do forcamento_v3 (130 com coordenada), leitura e QC do forcamento_v3:
                      hora completa pela cadência do posto, MAX 90 mm/h, QC iterativo contra 3 vizinhos, IDW p = 2
                      no centróide (UTM 22S). Única fonte ao vivo acessível hoje sem credencial.
  ArquivoForcamento — forcamento_v3/<janela>.json.gz do git (ANA + CEMADEN + INMET com QC), para execução retroativa.
"""
import gzip
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

import geo
import telemetria_ana as ta

H = timedelta(hours=1)
MAX_MM_H = 90.0
LIMITE_SUB, LIMITE_EXC, MIN_VIZ_MM = 0.4, 2.5, 30.0


@dataclass
class ChuvaObservada:
    horas: list                      # datetimes locais, de ini até ate (inclusive)
    chuva: dict                      # {sub_id: [mm ou None]}
    ate: datetime                    # última hora com chuva observada utilizável
    fonte: str
    cobertura: dict = field(default_factory=dict)   # postos, estações por hora, excluídos, falhas…
    registros: dict = field(default_factory=dict)   # {cod: {t: (nivel, vazao, chuva)}} (reaproveitados pela vazão)


def grade(ini, fim):
    out, t = [], ini
    while t <= fim:
        out.append(t)
        t += H
    return out


def chuva_horaria(reg, horas, corrige=lambda t: t, tolerar=True, max_falta=2):
    """Porta de forcamento.chuva_horaria (calibração). tolerar=True (só ao vivo): hora com até max_falta registros
    ausentes é aceita quando o registro anterior e o posterior mais próximos são 0 (o ausente entra como 0)."""
    r = {corrige(t): v[2] for t, v in reg.items() if v[2] is not None}
    if len(r) < 10:
        return {}, None, []
    ts = sorted(r)
    cad = Counter(int((b - a).total_seconds() // 60) for a, b in zip(ts, ts[1:])).most_common(1)[0][0]
    if cad not in (5, 10, 15, 30, 60):
        return {}, cad, []
    n = 60 // cad
    out, susp = {}, []
    passo = timedelta(minutes=cad)
    for h in horas:
        slots = [h - passo * k for k in range(n)]
        falt = [s for s in slots if s not in r]
        if falt and tolerar and len(falt) <= max_falta and len(falt) < n:
            ok = True
            for s_ in falt:
                ant = next((r[s_ - passo * j] for j in range(1, 4) if s_ - passo * j in r), None)
                pos = next((r[s_ + passo * j] for j in range(1, 4) if s_ + passo * j in r), None)
                if ant != 0 or pos != 0:
                    ok = False
                    break
            if ok:
                falt = []
        if falt:
            continue
        v = sum(r.get(s, 0.0) for s in slots)
        if v < 0 or not math.isfinite(v):
            continue
        if v > MAX_MM_H:
            susp.append((str(h), v))
            continue
        out[h] = v
    return out, cad, susp


def qc_iterativo(series, horas, xy):
    """Porta de forcamento_v2.qc_iterativo: remove, um por rodada, o posto com sub-registro (< 0,4×) ou excesso
    (> 2,5×) em relação à média dos 3 vizinhos mais próximos, quando os vizinhos somam > 30 mm."""
    excl, razoes = {}, {}
    while True:
        cs = list(series)
        novos = {}
        for c in cs:
            viz = sorted((x for x in cs if x != c), key=lambda x: math.dist(xy[c], xy[x]))[:3]
            hs = [h for h in horas if h in series[c] and all(h in series[v] for v in viz)]
            if len(hs) < 24:
                continue
            tc = sum(series[c][h] for h in hs)
            tv = sum(sum(series[v][h] for h in hs) for v in viz) / len(viz)
            razoes[c] = round(tc / tv, 2) if tv > 0 else None
            if tv > MIN_VIZ_MM and tc < LIMITE_SUB * tv:
                novos[c] = "subregistro"
            elif tv > MIN_VIZ_MM and tc > LIMITE_EXC * tv:
                novos[c] = "excesso"
        if not novos:
            return excl, razoes
        pior = max(novos, key=lambda c: abs(math.log(max(razoes[c] or 1e-3, 1e-3))))
        excl[pior] = novos[pior]
        series.pop(pior)


class FonteChuvaObservada:
    nome = "base"

    def obter(self, ini, ate, contexto=None) -> ChuvaObservada:
        raise NotImplementedError


class TelemetriaANA(FonteChuvaObservada):
    nome = "telemetria ANA (HidroTelemetria, 15 min)"

    def __init__(self, postos=None, min_cobertura=0.5, min_estacoes_hora=5, frac_ultima_hora=0.5, paralelo=8):
        self.postos = postos or json.loads((geo.DADOS / "postos_ana.json").read_text(encoding="utf-8"))
        self.min_cobertura, self.min_est, self.frac = min_cobertura, min_estacoes_hora, frac_ultima_hora
        self.paralelo = paralelo

    def obter(self, ini, ate, contexto=None):
        contexto = contexto or {}
        corrige = contexto.get("corrige_relogio", lambda c, t: t)
        extra = sorted(set(contexto.get("postos_extra", [])) - set(self.postos))
        regs, falhas = ta.baixar_varios(sorted(self.postos) + extra, ini - H, ate, self.paralelo)
        horas = grade(ini, ate)
        series, cad, susp = {}, {}, {}
        for c in self.postos:
            s, k, sp = chuva_horaria(regs.get(c, {}), horas, corrige=lambda t, c=c: corrige(c, t))
            cad[c] = k
            if sp:
                susp[c] = sp
            if len(s) >= self.min_cobertura * len(horas) and sum(s.values()) >= 0 and s:
                series[c] = s
        xs, ys = geo.utm22s([self.postos[c]["lon"] for c in self.postos], [self.postos[c]["lat"] for c in self.postos])
        xy = {c: (x, y) for c, x, y in zip(self.postos, xs, ys)}
        excl, razoes = qc_iterativo(series, horas, xy)
        codes = sorted(series)
        n_est = [sum(1 for c in codes if h in series[c]) for h in horas]
        # última hora observada: a mais recente com pelo menos frac × (mediana de estações por hora) e min_est estações
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
            vals = np.array([series[c].get(h, np.nan) for c in codes]) if codes else np.array([])
            ok = np.isfinite(vals)
            if h > ate_obs or ok.sum() < 1:
                if h <= ate_obs:
                    sem.append(str(h))
                for n in nomes:
                    chuva[n].append(None)
                continue
            v = (w[:, ok] @ vals[ok]) / w[:, ok].sum(axis=1)
            for j, n in enumerate(nomes):
                chuva[n].append(round(float(v[j]), 4))
        com_chuva = [c for c in self.postos if any(v[2] is not None for v in regs.get(c, {}).values())]
        cob = dict(postos_consultados=len(self.postos), postos_com_registro=sum(1 for c in self.postos if regs.get(c)),
                   postos_com_chuva=len(com_chuva), postos_usados=codes, excluidos_qc=excl,
                   razao_total_vizinhos=razoes, horas_suspeitas=susp, falhas_rede=falhas,
                   cadencia_min={c: k for c, k in cad.items() if k}, estacoes_por_hora=n_est,
                   horas_sem_estacao=sem, ultima_hora_pedida=str(ate), ultima_hora_observada=str(ate_obs),
                   regra_ultima_hora=f">= max({self.min_est}, {self.frac} x mediana de estacoes/hora)",
                   tolerancia="hora com ate 2 registros de 15 min ausentes aceita se vizinhos = 0 (so ao vivo)")
        return ChuvaObservada(horas=horas, chuva=chuva, ate=ate_obs, fonte=self.nome, cobertura=cob, registros=regs)


class ArquivoForcamento(FonteChuvaObservada):
    """Chuva observada arquivada da calibração (forcamento_v3/<janela>.json.gz), cortada em `ate`."""
    nome = "arquivo forcamento_v3 (ANA + CEMADEN + INMET, QC por vizinhos)"

    def __init__(self, janela, pasta):
        self.janela, self.pasta = janela, Path(pasta)

    def obter(self, ini, ate, contexto=None):
        f = json.loads(gzip.decompress((self.pasta / f"{self.janela}.json.gz").read_bytes()))
        hs = [datetime.fromisoformat(h) for h in f["horas"]]
        pos = {h: i for i, h in enumerate(hs)}
        horas = grade(ini, ate)
        chuva = {n: [(f["chuva_por_subbacia"][n][pos[h]] if h in pos else None) for h in horas]
                 for n in f["chuva_por_subbacia"]}
        sem = [str(h) for h in horas if h not in pos]
        cob = dict(janela=self.janela, postos_usados=f.get("postos_usados"), excluidos_qc=f.get("postos_excluidos_qc"),
                   estacoes_por_hora=[f["estacoes_disponiveis_por_hora"][pos[h]] if h in pos else 0 for h in horas],
                   horas_sem_estacao=sem, ultima_hora_observada=str(ate))
        return ChuvaObservada(horas=horas, chuva=chuva, ate=ate, fonte=self.nome, cobertura=cob)
