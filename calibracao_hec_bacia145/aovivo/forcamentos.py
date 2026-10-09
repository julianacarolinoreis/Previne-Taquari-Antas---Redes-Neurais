"""Versões "ao vivo" do forçamento histórico das 33 janelas de calibração/validação (X20260918 = teste, fechada).

Mesmo leitor (estacoes.py, reproduz o v3 com diferença 0) e mesma interpolação (idw.py: IDW p=2 no centróide).
Universo de candidatos = os postos que entram em algum forcamento_v3 (105 ANA, 71 CEMADEN, 15 INMET), cada fonte só
no período em que o v3 a tinha (CEMADEN dez/2022–jul/2026, INMET até 25/11/2025).

  avrob   (a)  só os 10 postos ANA que o robô de Santa Tereza já lê; sem controle de qualidade; usa toda hora com dado.
  avtelq3      postos vivos hoje (teste das APIs em 09/10/2026) com as regras do v3 (cobertura >= 50 % da janela,
               controle iterativo por vizinhos com o TOTAL da janela = olha o futuro). Isola a perda de postos.
  avtel   (b)  postos vivos hoje (ANA + CEMADEN + INMET), toda hora com dado, controle CAUSAL por vizinhos.
  avtel0       idem sem controle de qualidade (só o teto de 90 mm/h).
  avana        só ANA viva hoje (sem cadastro em CEMADEN/INMET), controle causal.
Controle causal: na hora h, total das últimas 72 h (até h) do posto x média dos 3 vizinhos mais próximos, nas horas em
que todos têm dado; vizinhos > 30 mm e posto < 0,4x (sub-registro) ou > 2,5x (excesso) -> posto fora naquela hora.
Hora sem nenhum posto: chuva 0 (contada em horas_sem_posto).
Saída: forc/<versao>/<janela>.json (detalhe) e, com --exportar, calibracao_hec_bacia145/dados/forcamento_prevista/
<janela>__<versao>.json.gz no formato das janelas derivadas (emissão t0 = 1 h antes do início: a chuva da janela
inteira vem da versão; estado inicial e observados são os da mãe).
Uso: python forcamentos.py [--exportar] [versao ...]
"""
import gzip
import json
import math
import sys
from datetime import timedelta

import numpy as np

import estacoes as E
import idw

ROBO = ["2851044", "2851072", "86488000", "86490500", "86497000", "86505500", "86507000", "86472600", "86472000", "86500000"]
VERSOES = ["avrob", "avtelq3", "avtel", "avtel0", "avana"]
FORC3 = E.CAL / "dados" / "forcamento_v3"
SAIDA = E.AQUI / "forc"
PREV = E.CAL / "dados" / "forcamento_prevista"
LIM_SUB, LIM_EXC, MIN_VIZ, JAN_QC = 0.4, 2.5, 30.0, 72


def v3(sim):
    return json.load(gzip.open(FORC3 / f"{sim}.json.gz", "rt", encoding="utf-8"))


def universo():
    u = set()
    for s in E.JANELAS:
        u |= set(v3(s)["postos_usados"])
    return u


def vivos():
    viv = json.loads((E.AQUI / "postos_ao_vivo.json").read_text(encoding="utf-8"))
    cem = json.loads((E.AQUI / "cemaden_ao_vivo.json").read_text(encoding="utf-8"))
    out = set(viv["ana_vivos"]) | {c for c, r in cem.items() if r["vivo"]}
    out |= {c for c, r in viv["inmet"].items() if r and r[1] == "Operante"}
    return out


def qc_v3(series, horas, P):
    """forcamento_v2.qc_iterativo (regra do v3, total da janela)."""
    excl, razoes = {}, {}
    xy = {c: idw.TR.transform(P[c][2], P[c][1]) for c in series}
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
            if tv > MIN_VIZ and tc < LIM_SUB * tv:
                novos[c] = "subregistro"
            elif tv > MIN_VIZ and tc > LIM_EXC * tv:
                novos[c] = "excesso"
        if not novos:
            return excl
        pior = max(novos, key=lambda c: abs(math.log(max(razoes[c] or 1e-3, 1e-3))))
        excl[pior] = novos[pior]
        series.pop(pior)


def qc_causal(series, horas, P):
    """Tira o posto nas horas em que o total das 72 h anteriores destoa dos 3 vizinhos. Devolve horas excluídas/posto."""
    cs = sorted(series)
    if len(cs) < 4:
        return {}
    xy = {c: idw.TR.transform(P[c][2], P[c][1]) for c in cs}
    V = np.array([[series[c].get(h, np.nan) for c in cs] for h in horas])
    fora = {}
    novo = {c: dict(series[c]) for c in cs}
    for j, c in enumerate(cs):
        viz = [cs.index(x) for x in sorted((x for x in cs if x != c), key=lambda x: math.dist(xy[c], xy[x]))[:3]]
        ok = np.isfinite(V[:, j]) & np.isfinite(V[:, viz]).all(1)
        a = np.where(ok, V[:, j], 0.0).cumsum()
        b = np.where(ok, np.nanmean(np.where(ok[:, None], V[:, viz], 0.0), 1), 0.0).cumsum()
        A = a - np.r_[np.zeros(JAN_QC), a[:-JAN_QC]] if len(a) > JAN_QC else a
        B = b - np.r_[np.zeros(JAN_QC), b[:-JAN_QC]] if len(b) > JAN_QC else b
        ruim = (B > MIN_VIZ) & ((A < LIM_SUB * B) | (A > LIM_EXC * B))
        for i in np.where(ruim & np.isfinite(V[:, j]))[0]:
            novo[c].pop(horas[i], None)
        if ruim.any():
            fora[c] = int((ruim & np.isfinite(V[:, j])).sum())
    series.clear()
    series.update(novo)
    return fora


TRAVA_H, TRAVA_MIN, TRAVA_AMP = 6, 2.0, 1.0
ISOL_MIN, ISOL_VIZ = 10.0, 1.0


def qc_hora(series, horas, P):
    """Regras horárias causais: valor travado (últimas TRAVA_H h todas >= TRAVA_MIN e amplitude <= TRAVA_AMP)
    e chuva isolada (>= ISOL_MIN com os 3 vizinhos com dado todos < ISOL_VIZ). Devolve horas excluídas/posto."""
    cs = sorted(series)
    xy = {c: idw.TR.transform(P[c][2], P[c][1]) for c in cs}
    viz = {c: sorted((x for x in cs if x != c), key=lambda x: math.dist(xy[c], xy[x]))[:3] for c in cs}
    fora, novo = {}, {}
    for c in cs:
        s, ruins = series[c], set()
        for i, h in enumerate(horas):
            v = s.get(h)
            if v is None:
                continue
            ult = [s.get(x) for x in horas[max(0, i - TRAVA_H + 1):i + 1]]
            if len(ult) == TRAVA_H and all(x is not None and x >= TRAVA_MIN for x in ult) and max(ult) - min(ult) <= TRAVA_AMP:
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


def montar(versao, sim, P, U, VIV):
    d = v3(sim)
    horas = [E.datetime.fromisoformat(h) for h in d["horas"]]
    if versao == "avrob":
        cand = list(ROBO)
    else:
        cand = [c for c in U if c in VIV]
        if versao == "avana":
            cand = [c for c in cand if E.fonte(c) == "ANA"]
        if versao in ("avtelbl", "avtelbl0", "avtelqc2"):
            negra = set(json.loads((E.AQUI / "lista_negra.json").read_text(encoding="utf-8"))["lista"])
            cand = [c for c in cand if c not in negra]
    series = {}
    for c in sorted(cand):
        s = E.serie(c, sim, horas)
        s = {h: v for h, v in s.items() if v <= E.MAX_MM_H}
        if s:
            series[c] = s
    info = {}
    if versao == "avtelq3":
        series = {c: s for c, s in series.items() if len(s) >= 0.5 * len(horas) and sum(s.values()) > 0}
        info["excluidos_qc"] = qc_v3(series, horas, P)
    elif versao in ("avtel", "avana", "avtelbl"):
        info["horas_excluidas_qc"] = qc_causal(series, horas, P)
    elif versao == "avtelqc2":
        info["horas_excluidas_qc_hora"] = qc_hora(series, horas, P)
        info["horas_excluidas_qc"] = qc_causal(series, horas, P)
    codes = sorted(series)
    ch, n = idw.idw(codes, series, horas, P, vazio="zero")
    _, _, area, subs = idw.xy_sub()
    ref = np.array([d["chuva_por_subbacia"][s] for s in subs]).T
    media, media3 = ch @ area / area.sum(), ref @ area / area.sum()
    tot, tot3 = ch.sum(0), ref.sum(0)
    out = dict(sim=sim, versao=versao, horas=d["horas"], convencao=d["convencao"], postos_usados=codes,
               por_fonte={f: sum(E.fonte(c) == f for c in codes) for f in ("ANA", "CEMADEN", "INMET")},
               postos_v3=len(d["postos_usados"]), estacoes_disponiveis_por_hora=n.tolist(),
               horas_sem_posto=int((n == 0).sum()), **info,
               chuva_por_subbacia={s: [round(float(v), 4) for v in ch[:, i]] for i, s in enumerate(subs)},
               chuva_media_bacia_mm=[round(float(v), 4) for v in media],
               resumo=dict(total_bacia_mm=round(float(media.sum()), 1), total_bacia_v3_mm=round(float(media3.sum()), 1),
                           razao_total_subbacias_p10_p50_p90=[round(float(x), 2) for x in np.percentile(
                               (tot + 0.5) / (tot3 + 0.5), [10, 50, 90])],
                           corr_horaria_media_bacia=round(float(np.corrcoef(media, media3)[0, 1]), 3)
                           if media.std() > 0 and media3.std() > 0 else None,
                           corr_horaria_subbacia_mediana=round(float(np.nanmedian([
                               np.corrcoef(ch[:, i], ref[:, i])[0, 1] for i in range(len(subs))
                               if ch[:, i].std() > 0 and ref[:, i].std() > 0])), 3)))
    return out


def merge_carregar():
    """merge_sub.npz (merge_subbacias.py) -> ({hora UTC do arquivo: vetor por sub-bacia na ordem de idw.xy_sub}, subs)."""
    z = np.load(E.AQUI / "merge_sub.npz")
    _, _, _, subs = idw.xy_sub()
    ordem = [list(z["subs"]).index(s) for s in subs]
    return {E.datetime.strptime(str(t), "%Y%m%d%H"): z["P"][i, ordem] for i, t in enumerate(z["t_utc"])}


def merge_janela(M, horas, desloc):
    """Chuva da hora local H = arquivo MERGE da hora UTC H + 3 h + desloc. Arquivo ausente/NaN -> 0 (contado)."""
    ch, falt = [], 0
    for h in horas:
        v = M.get(h + timedelta(hours=3 + desloc))
        if v is None or not np.isfinite(v).all():
            falt += 1
            v = np.nan_to_num(v, nan=0.0) if v is not None else np.zeros(len(next(iter(M.values()))))
        ch.append(v)
    return np.array(ch), falt


def merge_desloc(M):
    """Deslocamento (h) que maximiza a correlação horária da média da bacia com o v3, somando as 33 janelas."""
    _, _, area, subs = idw.xy_sub()
    melhor = {}
    for d in range(-3, 4):
        a, b = [], []
        for sim in E.JANELAS:
            x = v3(sim)
            horas = [E.datetime.fromisoformat(h) for h in x["horas"]]
            ref = np.array([x["chuva_por_subbacia"][s] for s in subs]).T
            m, _ = merge_janela(M, horas, d)
            a += list(m @ area / area.sum())
            b += list(ref @ area / area.sum())
        melhor[d] = float(np.corrcoef(a, b)[0, 1])
    print("MERGE: correlação com o v3 por deslocamento (h):", {k: round(v, 3) for k, v in melhor.items()}, flush=True)
    return max(melhor, key=melhor.get), melhor


def montar_merge(sim, M, desloc):
    d = v3(sim)
    horas = [E.datetime.fromisoformat(h) for h in d["horas"]]
    ch, falt = merge_janela(M, horas, desloc)
    _, _, area, subs = idw.xy_sub()
    ref = np.array([d["chuva_por_subbacia"][s] for s in subs]).T
    media, media3 = ch @ area / area.sum(), ref @ area / area.sum()
    tot, tot3 = ch.sum(0), ref.sum(0)
    return dict(sim=sim, versao="avmerge", horas=d["horas"], convencao=d["convencao"] + f"; MERGE hora UTC = local + 3 h + {desloc}",
                postos_usados=[], por_fonte={}, postos_v3=len(d["postos_usados"]), estacoes_disponiveis_por_hora=[],
                horas_sem_posto=falt,
                chuva_por_subbacia={s: [round(float(v), 4) for v in ch[:, i]] for i, s in enumerate(subs)},
                chuva_media_bacia_mm=[round(float(v), 4) for v in media],
                resumo=dict(total_bacia_mm=round(float(media.sum()), 1), total_bacia_v3_mm=round(float(media3.sum()), 1),
                            razao_total_subbacias_p10_p50_p90=[round(float(x), 2) for x in np.percentile(
                                (tot + 0.5) / (tot3 + 0.5), [10, 50, 90])],
                            corr_horaria_media_bacia=round(float(np.corrcoef(media, media3)[0, 1]), 3),
                            corr_horaria_subbacia_mediana=round(float(np.nanmedian([
                                np.corrcoef(ch[:, i], ref[:, i])[0, 1] for i in range(len(subs))
                                if ch[:, i].std() > 0 and ref[:, i].std() > 0])), 3)))


def exportar(versao, sim, out):
    t0 = E.datetime.fromisoformat(out["horas"][0]) - timedelta(hours=1)
    js = {"mae": sim, "modelo": versao, "fonte": f"pluviômetros ao vivo ({versao}), _analise_aovivo/forcamentos.py",
          "convencao": out["convencao"] + "; emissão t0 = 1 h antes do início: a janela inteira usa esta chuva",
          "emissoes": {f"{t0:%Y%m%d%H}": {"chuva": out["chuva_por_subbacia"], "postos": out["postos_usados"]}}}
    PREV.mkdir(parents=True, exist_ok=True)
    with gzip.open(PREV / f"{sim}__{versao}.json.gz", "wt", encoding="utf-8", compresslevel=9) as h:
        json.dump(js, h, separators=(",", ":"))
    return f"{sim}__{t0:%Y%m%d%H}__{versao}"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    exp = "--exportar" in sys.argv
    versoes = args or VERSOES
    P, U, VIV = E.postos(), universo(), vivos()
    print(f"universo {len(U)} postos; vivos hoje no universo {len(U & VIV)}", flush=True)
    rf = SAIDA / "resumo.json"
    resumo, janelas = (json.loads(rf.read_text(encoding="utf-8")) if rf.exists() else {}), []
    if "avmerge" in versoes:
        M = merge_carregar()
        desloc, corr = merge_desloc(M)
        (SAIDA / "merge_desloc.json").write_text(json.dumps(dict(escolhido=desloc, corr=corr), indent=1), encoding="utf-8")
    for v in versoes:
        (SAIDA / v).mkdir(parents=True, exist_ok=True)
        for sim in E.JANELAS:
            out = montar_merge(sim, M, desloc) if v == "avmerge" else montar(v, sim, P, U, VIV)
            (SAIDA / v / f"{sim}.json").write_text(json.dumps(out), encoding="utf-8")
            resumo[f"{v}|{sim}"] = dict(postos=len(out["postos_usados"]), postos_v3=out["postos_v3"], por_fonte=out["por_fonte"],
                                        horas_sem_posto=out["horas_sem_posto"], **out["resumo"])
            print(v, sim, resumo[f"{v}|{sim}"], flush=True)
            if exp:
                janelas.append(exportar(v, sim, out))
    (SAIDA / "resumo.json").write_text(json.dumps(resumo, indent=1), encoding="utf-8")
    if exp:
        nome = "janelas_derivadas.txt" if not args else f"janelas_derivadas_{'_'.join(versoes)}.txt"
        (SAIDA / nome).write_text(",".join(janelas), encoding="utf-8")


if __name__ == "__main__":
    main()
