"""CEMADEN ao vivo: JSON público do mapa interativo (getJson2.php?uf=RS), sem credencial.

O JSON só traz, por estação, o instante do último dado (UTC) e os acumulados de 1, 3, 6, 12, 24, 48, 72 e 96 h até ele
("-" = sem chuva no período); não tem histórico nem código da estação (casamento por município + nome público,
dados/postos_rede.json). Por isso há um COLETOR (a cada 10 min) que guarda as leituras em
<pasta>/AAAA-MM-DD.jsonl (dia UTC; uma linha por coleta) e a série horária é montada assim (hora H = (H − 1 h, H], BRT):
  hora    — leitura cujo último dado é H:00 (exata) ou a mais próxima de H:00 (até ±30 min; com o coletor a cada
            10 min, em geral ±10 min) → acc1hr; a leitura vale para a hora cheia H (deslocamento registrado);
  bloco   — horas sem leitura própria: a leitura mais próxima depois de H dá o total do menor bloco que contém H
            ((t−3, t−1] ou (t−6, t−3]; blocos maiores apagariam o horário dos picos); o total menos as horas já
            conhecidas no bloco é dividido por igual entre as que faltam (isentas da regra de valor travado do QC).
            Com o coletor contínuo quase toda hora tem leitura própria; o rateio só cobre lacunas curtas. Sem
            histórico, o posto entra só nas últimas ~6 h.
Uso do coletor: python cemaden.py coletar --pasta <dir> [--loop-min 10 --vezes N]
"""
import argparse
import json
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import geo

URL = "https://resources.cemaden.gov.br/graficos/interativo/getJson2.php?uf=RS"
BLOCOS = [("acc1hr", 1), ("acc3hr", 3), ("acc6hr", 6), ("acc12hr", 12), ("acc24hr", 24), ("acc48hr", 48),
          ("acc72hr", 72), ("acc96hr", 96)]
H = timedelta(hours=1)
BRT = timedelta(hours=-3)


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    return " ".join(s.replace("-", " ").replace(".", " ").split())


def mapa_publico(postos=None):
    """{(município, nome público) normalizados: código CEM_…} dos postos CEMADEN da rede."""
    postos = postos or json.loads((geo.DADOS / "postos_rede.json").read_text(encoding="utf-8"))["postos"]
    return {(norm(p["municipio"]), norm(p["nome_publico"])): c for c, p in postos.items() if p["fonte"] == "CEMADEN"}


def _num(x):
    if x in ("-", "", None):
        return 0.0
    try:
        return float(str(x).replace(",", "."))
    except ValueError:
        return None


def coletar(timeout=60, tentativas=3):
    """(instante da coleta UTC, {cod: [t_dado_utc 'AAAA-MM-DDTHH:MM', acc1, acc3, …, acc96]}, n_publicas, erro)."""
    erro = None
    for k in range(tentativas):
        try:
            r = requests.get(URL, timeout=timeout, headers={"User-Agent": "previne-hec-aovivo/1.0 (pesquisa)"})
            r.raise_for_status()
            linhas = r.json()
            break
        except Exception as exc:  # noqa: BLE001
            erro = repr(exc)[:200]
            time.sleep(5 * (k + 1))
    else:
        return datetime.now(timezone.utc).replace(tzinfo=None), {}, 0, erro
    agora = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    mp = mapa_publico()
    est = {}
    for ln in linhas:
        c = mp.get((norm(ln.get("cidade")), norm(ln.get("nomeestacao"))))
        if not c:
            continue
        try:
            t = datetime.strptime(ln["datahoraUltimovalor"], "%d/%m/%y %H:%M")
        except (KeyError, ValueError):
            continue
        est[c] = [t.strftime("%Y-%m-%dT%H:%M")] + [_num(ln.get(k)) for k, _ in BLOCOS]
    return agora, est, len(linhas), None


def gravar(pasta, instante, est, extra=None):
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    linha = dict(c=instante.strftime("%Y-%m-%dT%H:%M:%S"), e=est, **(extra or {}))
    with (pasta / f"{instante:%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as h:
        h.write(json.dumps(linha, separators=(",", ":")) + "\n")


def ler(pasta, ini_utc, fim_utc):
    """Coletas (instante, est) com instante em [ini_utc − 4 dias, fim_utc + 4 dias] (os blocos alcançam 96 h)."""
    pasta = Path(pasta)
    out = []
    if not pasta.exists():
        return out
    d = (ini_utc - timedelta(days=4)).date()
    while d <= (fim_utc + timedelta(days=4)).date():
        f = pasta / f"{d:%Y-%m-%d}.jsonl"
        if f.exists():
            for ln in f.read_text(encoding="utf-8").splitlines():
                try:
                    x = json.loads(ln)
                    out.append((datetime.fromisoformat(x["c"]), x["e"]))
                except (ValueError, KeyError):
                    continue
        d += timedelta(days=1)
    return out


def horarias(coletas, horas, desvio_max_min=30, bloco_max_h=6):
    """Séries horárias BRT por posto a partir das coletas.
    Cada leitura vale para a hora cheia mais próxima do seu último dado (desvio <= desvio_max_min; fica a de menor
    desvio — a exata, se houver): o CEMADEN publica a cada 10 min e o coletor quase nunca vê exatamente H:00.
    Rateio só em blocos que terminam até bloco_max_h antes da leitura ((t−3, t−1] e (t−6, t−3]): blocos de 12–96 h
    apagariam o horário dos picos (o total de 48 h ficou certo, mas o pico horário da bacia caía à metade).
    Devolve ({cod: {h: mm}}, {cod: info}, {cod: {horas rateadas de bloco}})."""
    regs = {}
    for _, est in coletas:
        for c, v in est.items():
            t = datetime.fromisoformat(v[0]) + BRT
            tr = (t + timedelta(minutes=30)).replace(minute=0, second=0)
            desv = abs((t - tr).total_seconds()) / 60
            if desv > desvio_max_min:
                continue
            r = regs.setdefault(c, {})
            if tr not in r or desv < r[tr][0]:
                r[tr] = (desv, v[1:], t)
    hs = set(horas)
    out, info, rateio = {}, {}, {}
    for c, rr in regs.items():
        exatos = {t: x[1] for t, x in rr.items()}
        todas = {t: a[0] for t, a in exatos.items() if a[0] is not None}
        s = {t: v for t, v in todas.items() if t in hs}
        n_ex = len(s)
        n_zero = sum(1 for t in s if rr[t][0] == 0)
        ultimo = max(rr)
        faltam = [h for h in horas if h not in s and h <= ultimo]
        for h in faltam:
            melhor = None
            for t, a in exatos.items():
                if t < h or t - h >= bloco_max_h * H:
                    continue
                atras = (t - h) / H            # h está em (t − hi, t − lo]
                for i, (_, hi) in enumerate(BLOCOS):
                    lo = 0 if i == 0 else BLOCOS[i - 1][1]
                    if lo <= atras < hi:
                        if melhor is None or hi - lo < melhor[0]:
                            melhor = (hi - lo, t, lo, hi, a, i)
                        break
            if melhor is None:
                continue
            _, t, lo, hi, a, i = melhor
            if a[i] is None or (i and a[i - 1] is None):
                continue
            total = a[i] - (a[i - 1] if i else 0.0)
            bloco = [t - k * H for k in range(lo, hi)]
            conhecido = sum(todas[b] for b in bloco if b in todas)
            vazias = [b for b in bloco if b not in todas]
            s[h] = max(total - conhecido, 0.0) / max(len(vazias), 1)
        out[c] = s
        rateio[c] = set(s) - {t for t in s if t in todas}
        info[c] = dict(exatas=n_zero, aproximadas=n_ex - n_zero, bloco=len(s) - n_ex,
                       ultimo_dado_brt=str(rr[ultimo][2]))
    return out, info, rateio


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["coletar"])
    ap.add_argument("--pasta", required=True)
    ap.add_argument("--loop-min", type=float, default=0)
    ap.add_argument("--vezes", type=int, default=1)
    a = ap.parse_args()
    for k in range(a.vezes):
        t0 = time.time()
        inst, est, n, erro = coletar()
        gravar(a.pasta, inst, est, dict(n_publicas=n, erro=erro) if erro else dict(n_publicas=n))
        print(f"{inst:%Y-%m-%d %H:%M:%S} UTC: {len(est)} postos da rede de {n} públicas" + (f"; erro {erro}" if erro else ""),
              flush=True)
        if k + 1 < a.vezes and a.loop_min:
            time.sleep(max(0.0, a.loop_min * 60 - (time.time() - t0)))


if __name__ == "__main__":
    main()
