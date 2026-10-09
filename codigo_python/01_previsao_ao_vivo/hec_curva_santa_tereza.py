"""Curva empírica régua de Muçum (86510000) -> régua de Santa Tereza (86472600) para a mancha do HEC ao vivo.

PESQUISA — não é alerta oficial. O executor HEC-HMS ao vivo prevê o nível de Muçum, mas a mancha de Santa
Tereza (contornos HAND do mosaico 2 m) é indexada pela régua 86472600. Enquanto o HEC não tiver um ponto
próprio em Santa Tereza, o site pode converter Muçum -> Santa Tereza por esta curva, que fica atrás de uma
flag desligada (ver assets/data/hec_aovivo/README.md).

O script baixa a telemetria da ANA (15 min) dos dois postos nas cheias de nov/2023, mai/2024, jun/2024 e no
período recente, faz médias horárias, escolhe a defasagem pelo erro deixando um evento de fora e grava a curva
(mediana por faixa + acumulado máximo, monotônica) com as métricas por evento.

    python codigo_python/01_previsao_ao_vivo/hec_curva_santa_tereza.py [--cache pasta]
"""
import argparse
import json
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[2]
SAIDA = RAIZ / "assets" / "data" / "hec_aovivo" / "curva_mucum_santa_tereza.json"
BASES = ["https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos",
         "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/DadosHidrometeorologicos"]
POSTOS = {"ST": "86472600", "MUC": "86510000"}
EVENTOS = {
    "nov2023": ("2023-11-15", "2023-11-26"),
    "mai2024": ("2024-04-28", "2024-05-12"),
    "jun2024": ("2024-06-15", "2024-06-26"),
    "recente": ("2026-09-05", "2026-10-09"),
}
DEFASAGENS_H = range(-6, 7)
COTA_ALTA_CM = 800


def baixar(cod, ini, fim):
    """{hora: nível médio em cm} de (H-60 min, H], hora local da ANA."""
    a = (ini - timedelta(days=1)).strftime("%d/%m/%Y")
    b = (fim + timedelta(days=1)).strftime("%d/%m/%Y")
    for k in range(3):
        for base in BASES:
            try:
                req = urllib.request.Request(f"{base}?codEstacao={cod}&dataInicio={a}&dataFim={b}",
                                             headers={"User-Agent": "previne-site-hec/1.0"})
                txt = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")
                break
            except Exception:  # noqa: BLE001 — tenta o outro endereço
                txt = None
        if txt:
            break
        time.sleep(3 * (k + 1))
    if not txt:
        raise RuntimeError(f"ANA indisponível para {cod}")
    acc = {}
    for blk in re.findall(r"<DadosHidrometereologicos .*?</DadosHidrometereologicos>", txt, re.S):
        dh = re.search(r"<DataHora>(.*?)</DataHora>", blk, re.S)
        nv = re.search(r"<Nivel>(.*?)</Nivel>", blk, re.S)
        if not dh or not nv or not nv[1].strip():
            continue
        t = datetime.fromisoformat(dh[1].strip()[:19])
        if not ini <= t <= fim:
            continue
        H = t.replace(minute=0, second=0) + (timedelta(hours=1) if t.minute else timedelta(0))
        acc.setdefault(H, []).append(float(nv[1].replace(",", ".")))
    return {h: float(np.mean(v)) for h, v in acc.items()}


def series(cache):
    arq = cache / "series_st_muc.json" if cache else None
    if arq and arq.exists():
        raw = json.loads(arq.read_text())
        return {e: {p: {datetime.fromisoformat(k): v for k, v in s.items()} for p, s in d.items()} for e, d in raw.items()}
    out = {}
    for ev, (a, b) in EVENTOS.items():
        ini, fim = datetime.fromisoformat(a), datetime.fromisoformat(b)
        out[ev] = {p: baixar(c, ini, fim) for p, c in POSTOS.items()}
        print(ev, {p: len(s) for p, s in out[ev].items()})
    if arq:
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(json.dumps({e: {p: {k.isoformat(): v for k, v in s.items()} for p, s in d.items()}
                                   for e, d in out.items()}))
    return out


def pares(st, muc, lag_h):
    """ST(t) contra MUC(t - lag_h); lag negativo = Santa Tereza adiantada em relação a Muçum."""
    xs, ys = [], []
    for t, y in st.items():
        x = muc.get(t - timedelta(hours=lag_h))
        if x is not None:
            xs.append(x)
            ys.append(y)
    return np.array(xs), np.array(ys)


def curva(x, y, nbin=40):
    o = np.argsort(x)
    x, y = x[o], y[o]
    bordas = np.unique(np.quantile(x, np.linspace(0, 1, nbin + 1)))
    cx, cy = [], []
    for a, b in zip(bordas[:-1], bordas[1:]):
        m = (x >= a) & (x <= b)
        if m.sum() >= 3:
            cx.append(float(np.median(x[m])))
            cy.append(float(np.median(y[m])))
    return np.array(cx), np.maximum.accumulate(np.array(cy))


def avaliar(dados, lag):
    por_ev, todos = {}, []
    for fora in EVENTOS:
        xt, yt = zip(*(pares(dados[e]["ST"], dados[e]["MUC"], lag) for e in EVENTOS if e != fora))
        cx, cy = curva(np.concatenate(xt), np.concatenate(yt))
        xv, yv = pares(dados[fora]["ST"], dados[fora]["MUC"], lag)
        if not len(xv):
            continue
        e = np.interp(xv, cx, cy) - yv
        alto = yv >= COTA_ALTA_CM
        por_ev[fora] = dict(n=int(len(e)), st_max_cm=round(float(yv.max())),
                            mae_cm=round(float(np.mean(np.abs(e))), 1), vies_cm=round(float(np.mean(e)), 1),
                            p95_abs_cm=round(float(np.percentile(np.abs(e), 95)), 1),
                            mae_st_acima_8m_cm=round(float(np.mean(np.abs(e[alto]))), 1) if alto.any() else None)
        todos.append(e)
    e = np.concatenate(todos)
    return dict(mae_cm=round(float(np.mean(np.abs(e))), 1), p95_abs_cm=round(float(np.percentile(np.abs(e), 95)), 1),
                por_evento_deixado_fora=por_ev)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=None, help="pasta para guardar/reusar as séries baixadas")
    args = ap.parse_args()
    dados = series(args.cache)
    aval = {lag: avaliar(dados, lag) for lag in DEFASAGENS_H}
    lag = min(aval, key=lambda k: aval[k]["mae_cm"])
    xt, yt = zip(*(pares(dados[e]["ST"], dados[e]["MUC"], lag) for e in EVENTOS))
    x, y = np.concatenate(xt), np.concatenate(yt)
    cx, cy = curva(x, y)
    out = {
        "produto": "previne-curva-mucum-santa-tereza",
        "aviso": "PESQUISA — não é alerta oficial. Curva empírica régua de Muçum -> régua de Santa Tereza; "
                 "não resolve o datum entre a régua 86472600 e o MDT da mancha.",
        "gerado_em": datetime.now(timezone(timedelta(hours=-3))).isoformat(timespec="seconds"),
        "origem": {"x": "86510000 Muçum, nível horário (cm)", "y": "86472600 Santa Tereza, nível horário (cm)",
                   "fonte": "ANA HidroTelemetria, média de (H-60 min, H]", "eventos": EVENTOS},
        "defasagem_h": lag,
        "defasagem_leitura": f"Santa Tereza em t corresponde a Muçum em t{'+' if lag < 0 else '-'}{abs(lag)} h",
        "pares": int(len(x)),
        "faixa_muc_cm": [round(float(x.min())), round(float(x.max()))],
        "faixa_st_cm": [round(float(y.min())), round(float(y.max()))],
        "curva": {"muc_cm": [round(v, 1) for v in cx], "st_cm": [round(v, 1) for v in cy]},
        "validacao_deixando_um_evento_fora": aval[lag],
        "mae_por_defasagem_cm": {str(k): v["mae_cm"] for k, v in aval.items()},
        "confiavel_para_mancha": False,
        "motivos": [
            "erro de conversão grande nas cheias: p95 de "
            f"{aval[lag]['por_evento_deixado_fora'].get('mai2024', {}).get('p95_abs_cm', '?')} cm em mai/2024",
            "viés troca de sinal entre 2023-2024 e 2026 (possível mudança de régua/datum em Santa Tereza ou Muçum)",
            "o relógio de Muçum estava adiantado ~105 min em 2023-2024, o que mistura a defasagem",
            "datum entre a régua 86472600 e o MDT (HAND 0 = 400 cm) ainda não compatibilizado",
            "soma-se ao erro da própria previsão HEC em Muçum (acima de 15 m só indicativa)",
        ],
    }
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("defasagem_h", "pares", "faixa_muc_cm", "faixa_st_cm")}, ensure_ascii=False))
    print(json.dumps(aval[lag], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
