"""Um ciclo do HEC-HMS ao vivo (bacia 145, lr-g8-c038). PESQUISA — não é alerta oficial.

  janela: t0 − dias_antes … t0 + horizonte, passo de 10 min; estado inicial pelo q0 observado no início (estrutura_v3)
  chuva:  observada (fonte trocável) até a última hora com dado; depois, um cenário de chuva prevista por HEC
  saída:  vazão em LJJ, Muçum, Encantado e Estrela; correção aditiva; nível; cotas de Muçum; JSON com metadados

Uso:
  ao vivo:      python ciclo.py --modo aovivo [--horizonte 120] [--cenarios ecmwf,gfs,zero]
  retroativo:   python ciclo.py --modo retro --t0 2024-05-10T14:00 [--fonte-obs ana|arquivo --janela-arquivo S2024_05]
                              [--fonte-prev aberto|arquivo] [--janela-mae S2024_05]   (janela-mae: período da calibração)
"""
import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import chuva_observada as co   # noqa: E402
import chuva_prevista as cp    # noqa: E402
import executor                # noqa: E402
import geo                     # noqa: E402
import posproc as pp           # noqa: E402
import vazao_observada as vo   # noqa: E402

H = timedelta(hours=1)
BRT = timezone(-3 * H)
CAL = AQUI.parent
JANELAS_TESTE = {"X20260918": (datetime(2026, 9, 18, 6), datetime(2026, 10, 4, 11))}   # catálogo: papel "teste"
AVISO = ("PESQUISA — não é alerta oficial. Previsão do modelo HEC-HMS da bacia Taquari-Antas (145 sub-bacias, "
         "lr-g8-c038) com chuva prevista determinística; acima de 15 m em Muçum o nível é só indicativo.")


def args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["aovivo", "retro"], default="aovivo")
    ap.add_argument("--t0", help="retro: hora de emissão local (AAAA-MM-DDTHH:MM)")
    ap.add_argument("--horizonte", type=int, default=120)
    ap.add_argument("--dias-antes", type=float, default=5, help="mínimo de dias antes de t0 (aquecimento)")
    ap.add_argument("--dias-max", type=float, default=30, help="máximo de dias antes de t0 na busca do início")
    ap.add_argument("--fator-inicio", type=float, default=1.25)
    ap.add_argument("--inicio-fixo", action="store_true", help="começa exatamente em t0 − dias-antes")
    ap.add_argument("--cenarios", default="ecmwf,gfs,zero")
    ap.add_argument("--pos-chuva", default="", help="pós-processadores da chuva prevista, ex.: fator:1.2 "
                                                    "(registrados em chuva_prevista.POS_CHUVA)")
    ap.add_argument("--fonte-obs", choices=["ana", "arquivo"], default="ana")
    ap.add_argument("--fonte-prev", choices=["aberto", "arquivo"], default="aberto")
    ap.add_argument("--janela-arquivo", help="janela do catálogo para --fonte-obs arquivo / observados arquivados")
    ap.add_argument("--janela-mae", help="usa o período (ini/fim) desta janela da calibração em vez de t0 − dias")
    ap.add_argument("--parametros", default=str(AQUI / "parametros" / "lr-g8-c038.json"))
    ap.add_argument("--trabalho", default=str(Path.home() / "hec_aovivo_trabalho"))
    ap.add_argument("--cache-prev", default=None, help="cache das rodadas (padrão: <trabalho>/cache_prev)")
    ap.add_argument("--saida", default=str(AQUI / "saida"))
    ap.add_argument("--hec-cmd", default=None)
    ap.add_argument("--rotulo", default=None)
    return ap.parse_args()


def sobrepoe_teste(a, b):
    return [k for k, (i, f) in JANELAS_TESTE.items() if a <= f and b >= i]


def escolher_inicio(reg_muc, corrige, t0, lim_ini, min_dias, fator):
    """Início da janela: a hora mais recente em [lim_ini, t0 − min_dias] com vazão de Muçum ≤ fator × a mínima do
    período. O estado inicial (q0 → déficit do solo e reservatórios lineares) foi calibrado em janelas que começam em
    vazão baixa; começar numa recessão alta deixa o reservatório lento (GW-2, k2 ≈ 1100 h) cheio por semanas."""
    teto = t0 - timedelta(days=min_dias)
    q = {}
    for t, v in reg_muc.items():
        tc = corrige("86510000", t)
        if tc.minute == 0 and lim_ini <= tc <= teto and v[1] is not None and v[1] > 0:
            q[tc] = v[1]
    if not q:
        return teto, dict(regra="sem vazão de Muçum no período: t0 − dias mínimos", q_muc_inicio=None)
    qmin = min(q.values())
    ini = max(t for t, v in q.items() if v <= fator * qmin)
    return ini, dict(regra=f"última hora em [{lim_ini}, {teto}] com Q(Muçum) <= {fator} x mínima do período",
                     q_muc_minima=qmin, q_muc_inicio=q[ini], q_muc_em_t0_menos_min_dias=q.get(teto))


def montar_forcamento(horas, obs, cen, avisos):
    """Chuva observada até obs.ate e a do cenário depois; lacunas viram 0 e são contadas (nunca em silêncio)."""
    pos_o = {h: i for i, h in enumerate(obs.horas)}
    pos_c = {h: i for i, h in enumerate(cen.horas)}
    lac_o = lac_c = 0
    ch = {}
    for n in geo.nomes():
        v = []
        for h in horas:
            x = None
            if h <= obs.ate:
                x = obs.chuva[n][pos_o[h]] if h in pos_o else None
                lac_o += x is None
            else:
                x = cen.chuva.get(n, [None] * len(cen.horas))[pos_c[h]] if h in pos_c else None
                lac_c += x is None
            v.append(0.0 if x is None else float(x))
        ch[n] = v
    n = len(geo.nomes())
    if lac_o:
        avisos.append(f"{cen.id}: {lac_o // n} h de chuva observada sem estação preenchidas com 0")
    if lac_c:
        avisos.append(f"{cen.id}: {lac_c // n} h sem chuva prevista (fora da rodada) preenchidas com 0")
    return {"horas": [str(h) for h in horas], "convencao": "hora H = soma (H-60min, H]", "chuva_por_subbacia": ch}


def media_bacia(ch, horas):
    a = geo.areas()
    M = np.array([ch[n] for n in geo.nomes()])
    return [round(float(x), 3) for x in (a @ M) / a.sum()]


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    a = args()
    T = {}
    t_tot = time.time()
    trab = Path(a.trabalho)
    agora = datetime.now(BRT).replace(tzinfo=None)
    if a.modo == "aovivo":
        t0 = agora.replace(minute=0, second=0, microsecond=0)
    else:
        t0 = datetime.fromisoformat(a.t0)
    stamp = f"{a.modo}_{t0:%Y%m%d%H}" + (f"_{a.rotulo}" if a.rotulo else "")
    trab = trab / f"{stamp}_{agora:%Y%m%d%H%M%S}"
    mods = executor.preparar(trab, a.hec_cmd)
    comum, hec, bi = mods["comum"], mods["hec"], mods["bacia_inteira"]
    info_ini = {}
    if a.janela_mae:
        for s in json.loads((CAL / "dados" / "catalogo_ampliado.json").read_text(encoding="utf-8"))["simulacoes"]:
            comum.SIMULACOES.setdefault(s["sim"], dict(ini=datetime.fromisoformat(s["ini"]),
                                                       fim=datetime.fromisoformat(s["fim"])))
        ini, fim = comum.SIMULACOES[a.janela_mae]["ini"], comum.SIMULACOES[a.janela_mae]["fim"]
        lim_ini = ini
        info_ini = dict(regra=f"período da janela de calibração {a.janela_mae}")
    else:
        fim = t0 + a.horizonte * H
        lim_ini = t0 - timedelta(days=max(a.dias_max, a.dias_antes))
        for _, (_i, f_teste) in JANELAS_TESTE.items():     # nunca começa dentro de uma janela de teste
            if lim_ini <= f_teste < t0:
                lim_ini = f_teste + H
    if a.modo == "retro" and sobrepoe_teste(lim_ini, fim):
        raise SystemExit(f"t0 {t0} cai em janela de teste {sobrepoe_teste(lim_ini, fim)}: retroativa recusada")
    avisos = []

    # ---------------- observados dos controles (estado inicial, início da janela e correção)
    t = time.time()
    cods_ctrl = sorted({c[0] for c in bi.CONTROLES.values()})
    if a.janela_arquivo and a.fonte_obs == "arquivo":
        fq = vo.ArquivoObservados(a.janela_arquivo, CAL / "dados" / "observados")
    else:
        fq = vo.TelemetriaANA()
    regs, falhas_q = fq.obter(cods_ctrl, lim_ini - 6 * H, t0 + 3 * H)
    # causal: nada depois de t0, no horário já corrigido (relógio de Muçum adiantado 105 min em 2023–2024)
    regs = {c: {t: v for t, v in r.items() if comum.corrige_relogio(c, t) <= t0} for c, r in regs.items()}
    T["observados_s"] = round(time.time() - t, 1)
    if not a.janela_mae:
        if a.inicio_fixo:
            ini = max(lim_ini, t0 - timedelta(days=a.dias_antes))
            info_ini = dict(regra=f"fixo: t0 − {a.dias_antes:g} dias")
        else:
            ini, info_ini = escolher_inicio(regs.get("86510000", {}), comum.corrige_relogio, t0, lim_ini,
                                            a.dias_antes, a.fator_inicio)
        regs = {c: {t: v for t, v in r.items() if comum.corrige_relogio(c, t) >= ini - 6 * H} for c, r in regs.items()}
    if (info_ini.get("q_muc_inicio") or 0) > 1500:
        avisos.append(f"janela começa com Muçum em {info_ini['q_muc_inicio']:.0f} m³/s (fora do regime de início da "
                      "calibração): o reservatório lento pode manter a vazão simulada alta por dias")
    print(f"[{stamp}] janela {ini} → {fim}; t0 {t0}; início: {info_ini}", flush=True)

    # ---------------- chuva observada
    t = time.time()
    ctx = dict(corrige_relogio=comum.corrige_relogio)
    if a.fonte_obs == "ana":
        fobs = co.TelemetriaANA()
    else:
        fobs = co.ArquivoForcamento(a.janela_arquivo, CAL / "dados" / "forcamento_v3")
    obs = fobs.obter(ini, t0, ctx)
    T["chuva_observada_s"] = round(time.time() - t, 1)
    print(f"chuva observada até {obs.ate} ({obs.fonte}); controles com dado: "
          f"{sum(1 for r in regs.values() if r)}/{len(cods_ctrl)} [{T['chuva_observada_s']} s]", flush=True)

    # ---------------- chuva prevista (cenários)
    t = time.time()
    inicio = obs.ate + H
    cache = Path(a.cache_prev) if a.cache_prev else Path(a.trabalho) / "cache_prev"
    cens = []
    for cid in [c for c in a.cenarios.split(",") if c]:
        papel = {"ecmwf": "principal", "gfs": "secundario"}.get(cid, "referencia")
        try:
            if cid == "zero":
                cens += cp.SemChuva().cenarios(t0, inicio, fim)
            elif a.fonte_prev == "arquivo":
                cens += cp.ArquivoPrevista(a.janela_mae or a.janela_arquivo, cid,
                                           CAL / "dados" / "forcamento_prevista", papel).cenarios(t0, inicio, fim)
            else:
                f = cp.ModeloAberto(cid, cache, papel)
                cens += f.cenarios(t0, inicio, fim, a.modo)
        except Exception as exc:  # noqa: BLE001 — um cenário que falha não derruba os outros
            cens.append(cp.Cenario(id=cid, modelo=cid, papel=papel, horas=[], chuva={}, status="falha",
                                   avisos=[repr(exc)[:300]]))
    cens = cp.aplicar_pos(cens, a.pos_chuva)
    T["chuva_prevista_s"] = round(time.time() - t, 1)
    for c in cens:
        print(f"cenário {c.id}: {c.status} rodada {c.rodada_utc} idade {c.idade_h} h; {'; '.join(c.avisos)}", flush=True)
    ok = [c for c in cens if c.status == "ok"]
    if not ok:
        raise SystemExit("nenhum cenário de chuva prevista disponível")

    # ---------------- HEC
    horas = co.grade(ini, fim)
    forc = {c.id: montar_forcamento(horas, obs, c, avisos) for c in ok}
    par = json.loads(Path(a.parametros).read_text(encoding="utf-8"))
    sim = f"AV{t0:%Y%m%d%H}"
    res, th, q0 = executor.rodar(sim, ini, fim, regs, forc, par)
    T.update(th)
    erros = {c: str(r)[:300] for c, r in res.items() if isinstance(r, Exception)}
    res = {c: r for c, r in res.items() if not isinstance(r, Exception)}
    if erros:
        avisos.append(f"HEC falhou em {sorted(erros)}: {erros}")
    if not res:
        raise SystemExit(f"HEC falhou em todos os cenários: {erros}")
    print(f"HEC: {sorted(res)} ok [{th['hec_s']} s]", flush=True)

    # ---------------- pós-processamento
    t = time.time()
    corr, curvas = pp.carregar_config()
    pontos = {}
    for nome, (cod, no, _, _) in pp.PONTOS.items():
        oq = {k: v for k, v in hec.observado(sim, cod).items() if k <= t0}
        on = {k: v for k, v in hec.nivel(sim, cod).items() if k <= t0}
        pontos[nome] = pp.ponto(nome, horas, t0, {c: r.get(no, {}) for c, r in res.items()}, oq, on, corr, curvas,
                                a.horizonte)
    pontos["MUCUM"]["cotas_previstas"] = pp.cotas_mucum(pontos["MUCUM"], horas, t0)
    for nome in pontos:
        rc = pp.resumo_conjunto(pontos[nome], ok, horas, t0)
        if rc:
            pontos[nome]["conjunto"] = rc
    if a.modo == "retro" and a.janela_arquivo:           # verificação: observado DEPOIS de t0 (só no retroativo)
        fv = vo.ArquivoObservados(a.janela_arquivo, CAL / "dados" / "observados")
        rv, _ = fv.obter([pp.PONTOS[n][0] for n in pp.PONTOS], ini, fim)
        for nome, (cod, *_r) in pp.PONTOS.items():
            q = {comum.corrige_relogio(cod, k): v for k, v in rv.get(cod, {}).items()}
            pontos[nome]["verificacao_apos_t0"] = dict(
                vazao_m3s=[pp._r(q[h][1]) if h in q and h > t0 else None for h in horas],
                nivel_cm=[pp._r(q[h][0]) if h in q and h > t0 else None for h in horas])
    T["pos_s"] = round(time.time() - t, 1)
    T["total_s"] = round(time.time() - t_tot, 1)

    mu = pontos["MUCUM"]
    acima = {c: any(n is not None and n > 1500 for n in v) for c, v in mu.get("nivel_previsto_cm", {}).items()}
    if any(acima.values()):
        avisos.append(f"nível previsto em Muçum passa de 15 m em {[c for c, v in acima.items() if v]}: "
                      "acima disso a curva está fora da validade (só indicativo)")
    if mu.get("ultimo_observado_valido") is None:
        avisos.append("Muçum sem observado válido nas últimas 72 h: série sem correção")
    elif mu["ultimo_observado_valido"]["idade_h"] > 3:
        avisos.append(f"último observado válido de Muçum tem {mu['ultimo_observado_valido']['idade_h']:.0f} h")
    saida = {
        "produto": "previne-hec-bacia145-aovivo", "versao_esquema": 1, "aviso": AVISO, "modo": a.modo,
        "emitido_em": agora.isoformat(timespec="seconds") + "-03:00", "t0": str(t0),
        "janela": dict(inicio=str(ini), fim=str(fim), passo_modelo_min=10, passo_saida_h=1, horizonte_h=a.horizonte,
                       dias_antes_min=a.dias_antes, dias_antes_max=a.dias_max, janela_mae=a.janela_mae,
                       inicio_escolhido=info_ini),
        "parametros": dict(id=par["id"], familia=par["familia"], gerador=par.get("gerador"), sha256_p=par.get("sha256_p"),
                           q0_especifica_m3s_km2={k: round(v, 6) for k, v in q0.items()}),
        "chuva_observada": dict(fonte=obs.fonte, ate=str(obs.ate),
                                **{k: v for k, v in obs.cobertura.items() if k not in ("razao_total_vizinhos",)}),
        "cenarios": [dict(id=c.id, modelo=c.modelo, papel=c.papel, status=c.status, fonte=c.fonte,
                          rodada_utc=c.rodada_utc, idade_rodada_h_em_t0=c.idade_h,
                          idade_rodada_h_na_emissao=(None if c.idade_h is None else
                                                     round(c.idade_h + (agora - t0) / H, 2) if a.modo == "aovivo" else c.idade_h),
                          cobre_ate=c.cobre_ate, grupo=c.grupo, membro=c.membro, peso=c.peso,
                          pos_processamento_chuva=c.pos_processamento, avisos=c.avisos,
                          chuva_bacia_prevista_mm=(round(sum(media_bacia(forc[c.id]["chuva_por_subbacia"], horas)
                                                             [horas.index(inicio):]), 1) if c.id in forc else None))
                     for c in cens],
        "horas": [str(h) for h in horas],
        "chuva_media_bacia_mm": {c: media_bacia(f["chuva_por_subbacia"], horas) for c, f in forc.items()},
        "pontos": pontos,
        "avisos": avisos,
        "tempos_s": T,
    }
    if a.modo == "retro":
        saida["observados_controles_falhas"] = falhas_q
    out = Path(a.saida)
    out.mkdir(parents=True, exist_ok=True)
    arq = out / f"hec_aovivo_{stamp}.json"
    arq.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if a.modo == "aovivo":
        (out / "hec_aovivo_latest.json").write_text(arq.read_text(encoding="utf-8"), encoding="utf-8")
    print("saída:", arq, f"({arq.stat().st_size / 1e3:.0f} kB)")
    print("tempos (s):", T)
    for c, r in mu.get("cotas_previstas", {}).items():
        print(f"  Muçum {c}: pico {r['pico_nivel_cm']} cm ({r['pico_vazao_m3s']} m³/s) em {r['t_pico']}; cotas "
              + ", ".join(f"{k}={'sim ' + v['primeiro_cruzamento'] if v['cruza'] else 'não'}" for k, v in r["cotas"].items()))
    print("avisos:", avisos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
