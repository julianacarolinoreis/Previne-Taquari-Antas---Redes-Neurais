"""Experimento retroativo do estado entre ciclos (chuva "perfeita" = observada arquivada do forcamento_v3; ciclos a cada
6 h; horizonte 48 h). Nunca usa janelas de teste (X20260918…).

  V0  partida a frio em cada ciclo, início adaptativo (ciclo.escolher_inicio: última hora com Q(Muçum) <= 1,25 x mínima,
      >= 5 dias antes de t0) — o que o ciclo ao vivo fazia até aqui
  V1  estado encadeado sem assimilação (= rodada contínua desde o início da janela; Save/Start State exatos)
  V2  estado encadeado + assimilação (razão incremental obs/sim por região de controle, estado.py) COM memória:
      o estado assimilado segue para o próximo ciclo
  V3  estado de V1 + assimilação só para a previsão (SEM memória: a cadeia guardada continua a do modelo puro)
Métricas em LJJ, Muçum e Encantado: razão sim/obs em t0, MAE bruto e corrigido (correção aditiva adit_h, τ do conjunto
de parâmetros) em +6/+24/+48 h; na janela inteira e só nos ciclos com t0 dentro dos eventos (comum.EVENTOS).
Uso: python experimento_estado.py [--janelas S2024_05,S2025_06] [--variantes V0,V1,V2,V3] [--saida DIR]
"""
import argparse
import gzip
import json
import math
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import ciclo                   # noqa: E402
import estado                  # noqa: E402
import executor                # noqa: E402
import posproc as pp           # noqa: E402
import telemetria_ana as ta    # noqa: E402
import vazao_observada as vo   # noqa: E402

H = timedelta(hours=1)
CAL = AQUI.parent
PONTOS = {"LJJ": ("86472000", "J_208", 1800), "MUCUM": ("86510000", "J_201", 1500),
          "ENCANTADO": ("86720000", "J_258", 1920)}
HZ = [6, 24, 48]


def args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--janelas", default="S2024_05,S2025_06")
    ap.add_argument("--variantes", default="V0,V1,V2,V3")
    ap.add_argument("--passo-h", type=int, default=6)
    ap.add_argument("--horizonte", type=int, default=48)
    ap.add_argument("--dias-antes", type=float, default=5)
    ap.add_argument("--parametros", default=str(AQUI / "parametros" / "md-val2-c002.json"))
    ap.add_argument("--trabalho", default=str(Path.home() / "hec_exp_estado"))
    ap.add_argument("--saida", default=str(CAL.parent / "_analise_sistema" / "estado"))
    ap.add_argument("--paralelo", type=int, default=4)
    ap.add_argument("--por-jvm", type=int, default=6)
    ap.add_argument("--max-ciclos", type=int, default=0, help="só para teste rápido")
    return ap.parse_args()


class Lab:
    def __init__(self, a):
        self.a = a
        self.T = Path(a.trabalho)
        m = executor.preparar(self.T)
        self.comum, self.hec, self.bi, self.e3 = m["comum"], m["hec"], m["bacia_inteira"], m["estrutura_v3"]
        self.w = m["w"]
        self.par = json.loads(Path(a.parametros).read_text(encoding="utf-8"))
        self.hec.NOS_EXTRA = sorted({c[1] for c in self.bi.CONTROLES.values()})
        self.cfg = {}
        original = self.hec.escrever_projeto

        def escrever(d, nome, texto):
            original(d, nome, texto)
            c = self.cfg.get(Path(d))
            if c:
                estado.configurar(Path(d), self.hec, c.get("salvar"), c.get("inicial"))

        self.hec.escrever_projeto = escrever

    def janela(self, W):
        self.W = W
        self.ini_w, self.fim_w = self.comum.SIMULACOES[W]["ini"], self.comum.SIMULACOES[W]["fim"]
        f = json.loads(gzip.decompress((CAL / "dados" / "forcamento_v3" / f"{W}.json.gz").read_bytes()))
        self.horas_doc = [datetime.fromisoformat(h) for h in f["horas"]]
        self.chuva_doc = f["chuva_por_subbacia"]
        cods = sorted({c[0] for c in self.bi.CONTROLES.values()})
        self.regs, _ = vo.ArquivoObservados(W, CAL / "dados" / "observados").obter(cods, self.ini_w - 6 * H, self.fim_w)
        self.mae = f"EX_{W}"
        for cod, reg in self.regs.items():
            ta.gravar_csv(reg, self.w / "dados_ana" / "csv" / f"{cod}_{self.mae}.csv")
        self.comum.SIMULACOES[self.mae] = dict(ini=self.ini_w, fim=self.fim_w)
        self.obs = {n: self.hec.observado(self.mae, cod) for n, (cod, _, _) in PONTOS.items()}
        self.niv = {n: self.hec.nivel(self.mae, cod) for n, (cod, _, _) in PONTOS.items()}
        self.obs_ctrl = {nome: self.bi.obs_limpo(self.mae, self.bi.CONTROLES[nome][0]) for nome, _ in self.e3.CTRL_NOS}

    def job(self, nome, a, b, salvar=None, inicial=None):
        self.comum.SIMULACOES[nome] = dict(ini=a, fim=b, mae=self.mae)
        i0, i1 = self.horas_doc.index(a), self.horas_doc.index(b)
        forc = dict(horas=[str(h) for h in self.horas_doc[i0:i1 + 1]], sim=nome,
                    convencao="hora H = soma (H-60min, H]",
                    chuva_por_subbacia={k: v[i0:i1 + 1] for k, v in self.chuva_doc.items()})
        (self.comum.FORC / f"{nome}.json").write_text(json.dumps(forc), encoding="utf-8")
        d = self.comum.RUNS / self.W / nome
        self.cfg[d] = dict(salvar=salvar, inicial=inicial)
        return d, nome, self.e3.bacia_v3(self.par["p"], nome, self.par.get("rota", "mc"))

    def rodar(self, jobs, paralelo=None):
        res = self.hec.rodar_lote(jobs, paralelo=paralelo or self.a.paralelo, por_jvm=self.a.por_jvm)
        for d, r in res.items():
            if isinstance(r, Exception):
                raise RuntimeError(f"{d}: {r}")
        return res


def sim_ctrl(res_d, e3):
    return {nome: {t: q for t, q in res_d.get(no, {}).items() if t.minute == 0} for nome, no in e3.CTRL_NOS}


def metricas(L, prev, t0s, eventos, tau):
    """prev: {t0: {ponto: {t: q}}} (previsões da variante)."""
    out = {}
    for rotulo, sel in (("janela", t0s), ("eventos", [t for t in t0s if any(a <= t <= b for a, b in eventos)])):
        o = {}
        for n, (_cod, _no, lim) in PONTOS.items():
            O, N = L.obs[n], L.niv[n]
            razoes, ab = [], {h: [] for h in HZ}
            ac = {h: [] for h in HZ}
            for t0 in sel:
                S = prev[t0][n]
                if t0 in O and t0 in S and O[t0] > 0:
                    razoes.append(S[t0] / O[t0])
                tv = next((t0 - k * H for k in range(73) if (t0 - k * H) in O and O[t0 - k * H] > 0
                           and (t0 - k * H) in N and N[t0 - k * H] <= lim), None)
                e = (O[tv] - S[tv]) if tv is not None and tv in S else 0.0
                for h in HZ:
                    t = t0 + h * H
                    if t in O and t in S:
                        ab[h].append(abs(S[t] - O[t]))
                        k = (t - tv) / H if tv is not None else 0.0
                        ac[h].append(abs(max(S[t] + e * math.exp(-k / tau[n][min(h, len(tau[n])) - 1]), 1.0) - O[t]))
            lr = sorted(razoes)
            o[n] = dict(n_ciclos=len(sel),
                        razao_t0_mediana=round(lr[len(lr) // 2], 3) if lr else None,
                        razao_t0_p10_p90=[round(lr[int(0.1 * (len(lr) - 1))], 3), round(lr[int(0.9 * (len(lr) - 1))], 3)] if lr else None,
                        erro_log_t0_medio=round(sum(abs(math.log(r)) for r in lr) / len(lr), 3) if lr else None,
                        mae_bruto={f"+{h}h": round(sum(v) / len(v), 1) if v else None for h, v in ab.items()},
                        mae_corrigido={f"+{h}h": round(sum(v) / len(v), 1) if v else None for h, v in ac.items()})
        out[rotulo] = o
    return out


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    a = args()
    L = Lab(a)
    tau = pp.carregar_config(L.par)[0]["tau_h"]
    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    variantes = a.variantes.split(",")
    resumo = dict(parametros=L.par["id"], passo_h=a.passo_h, horizonte_h=a.horizonte, dias_antes=a.dias_antes,
                  janelas={})
    for W in a.janelas.split(","):
        assert not W.startswith("X"), "janela de teste fechada"
        T0 = time.time()
        L.janela(W)
        t = L.ini_w + timedelta(days=a.dias_antes)
        t = t.replace(minute=0) + ((-t.hour) % a.passo_h) * H
        t0s = []
        while t + a.horizonte * H <= L.fim_w:
            t0s.append(t)
            t += a.passo_h * H
        if a.max_ciclos:
            t0s = t0s[:a.max_ciclos]
        eventos = [(e["ini"], e["fim"]) for e in L.comum.EVENTOS.values() if e["sim"] == W]
        print(f"[{W}] {len(t0s)} ciclos {t0s[0]} … {t0s[-1]}; eventos {eventos}", flush=True)
        prev, tempos, info = {}, {}, {}

        # V1: rodada contínua (= estado encadeado) + estados em cada t0 (para V3 e verificação)
        t = time.time()
        jc = L.job(f"{W}_V1_cont", L.ini_w, L.fim_w)
        cont = L.rodar([jc], 1)[jc[0]]
        tempos["V1_continua_s"] = round(time.time() - t, 1)
        prev["V1"] = {t0: {n: cont[no] for n, (_, no, _) in PONTOS.items()} for t0 in t0s}
        cont_ctrl = sim_ctrl(cont, L.e3)

        precisa_estados = any(v in variantes for v in ("V2", "V3"))
        est = {}
        if precisa_estados:
            t = time.time()
            js = [L.job(f"{W}_E_{t0:%Y%m%d%H}", L.ini_w, t0, salvar=t0) for t0 in t0s]
            L.rodar(js)
            for (d, _, _), t0 in zip(js, t0s):
                est[t0] = estado.salvo(d)
                assert est[t0] and estado.instante(est[t0]) == t0, (d, t0)
            tempos["estados_s"] = round(time.time() - t, 1)
            # verificação: começar do estado salvo reproduz a contínua
            t0 = t0s[0]
            jv = L.job(f"{W}_V1_verif", t0, min(t0 + a.horizonte * H, L.fim_w), inicial=est[t0])
            rv = L.rodar([jv], 1)[jv[0]]
            info["verificacao_start_state_max_dif_m3s"] = {
                n: round(max(abs(rv[no][x] - cont[no][x]) for x in rv[no] if x in cont[no]), 4)
                for n, (_, no, _) in PONTOS.items()}
            print("verificação Start State:", info["verificacao_start_state_max_dif_m3s"], flush=True)

        if "V0" in variantes:
            t = time.time()
            js, ini0 = [], {}
            for t0 in t0s:
                i0, _ = ciclo.escolher_inicio(L.regs.get("86510000", {}), L.comum.corrige_relogio, t0, L.ini_w,
                                              a.dias_antes, 1.25)
                i0 = max(i0.replace(minute=0, second=0), L.ini_w)
                ini0[t0] = i0
                js.append(L.job(f"{W}_V0_{t0:%Y%m%d%H}", i0, min(t0 + a.horizonte * H, L.fim_w)))
            res = L.rodar(js)
            prev["V0"] = {t0: {n: res[d][no] for n, (_, no, _) in PONTOS.items()} for (d, _, _), t0 in zip(js, t0s)}
            info["V0_dias_antes_medio"] = round(sum((t0 - ini0[t0]) / H for t0 in t0s) / len(t0s) / 24, 2)
            tempos["V0_s"] = round(time.time() - t, 1)

        if "V3" in variantes:
            t = time.time()
            js, rz3 = [], {}
            for t0 in t0s:
                f = L.comum.RUNS / W / f"_assim_V3_{t0:%Y%m%d%H}.state"
                rz3[t0] = estado.assimilar(est[t0], f, cont_ctrl, L.obs_ctrl, t0, L.e3)
                js.append(L.job(f"{W}_V3_{t0:%Y%m%d%H}", t0, min(t0 + a.horizonte * H, L.fim_w), inicial=f))
            res = L.rodar(js)
            prev["V3"] = {t0: {n: res[d][no] for n, (_, no, _) in PONTOS.items()} for (d, _, _), t0 in zip(js, t0s)}
            info["V3_razoes_muc"] = {str(t0): rz3[t0]["MUCUM"]["razao"] for t0 in t0s}
            tempos["V3_s"] = round(time.time() - t, 1)

        if "V2" in variantes:
            t = time.time()
            prev["V2"], rz2 = {}, {}
            f = L.comum.RUNS / W / f"_assim_V2_{t0s[0]:%Y%m%d%H}.state"
            rz2[t0s[0]] = estado.assimilar(est[t0s[0]], f, cont_ctrl, L.obs_ctrl, t0s[0], L.e3)
            for k, t0 in enumerate(t0s):
                prox = t0s[k + 1] if k + 1 < len(t0s) else None
                j = L.job(f"{W}_V2_{t0:%Y%m%d%H}", t0, min(t0 + a.horizonte * H, L.fim_w), salvar=prox, inicial=f)
                r = L.rodar([j], 1)[j[0]]
                prev["V2"][t0] = {n: r[no] for n, (_, no, _) in PONTOS.items()}
                if prox:
                    s = estado.salvo(j[0])
                    f = L.comum.RUNS / W / f"_assim_V2_{prox:%Y%m%d%H}.state"
                    rz2[prox] = estado.assimilar(s, f, sim_ctrl(r, L.e3), L.obs_ctrl, prox, L.e3)
                if k % 10 == 0:
                    print(f"  V2 {k + 1}/{len(t0s)} [{time.time() - t:.0f} s]", flush=True)
            info["V2_razoes_muc"] = {str(t0): rz2[t0]["MUCUM"]["razao"] for t0 in rz2}
            tempos["V2_s"] = round(time.time() - t, 1)

        met = {v: metricas(L, prev[v], t0s, eventos, tau) for v in ("V0", "V1", "V2", "V3") if v in prev}
        resumo["janelas"][W] = dict(ciclos=len(t0s), primeiro=str(t0s[0]), ultimo=str(t0s[-1]),
                                    eventos=[[str(x), str(y)] for x, y in eventos], metricas=met, info=info,
                                    tempos_s=dict(tempos, total=round(time.time() - T0, 1)))
        (saida / "resultado.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
        for v, m in met.items():
            for rot in ("janela", "eventos"):
                print(f"  {W} {v} {rot}: " + " | ".join(
                    f"{n} t0x{x['razao_t0_mediana']} bruto {x['mae_bruto']} corr {x['mae_corrigido']}"
                    for n, x in m[rot].items()), flush=True)
        if not a.max_ciclos:
            shutil.rmtree(L.comum.RUNS / W, ignore_errors=True)
    print("resultado:", saida / "resultado.json")


if __name__ == "__main__":
    main()
