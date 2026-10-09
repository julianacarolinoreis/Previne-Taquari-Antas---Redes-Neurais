"""Leitura da HidroTelemetria ANA (DadosHidrometeorologicos): nível, vazão e chuva brutos de 15 min por posto.

Mesmo endpoint e leitura dos robôs do site (repo_site/codigo_python/01_previsao_ao_vivo) e de baixar_ana.py da
calibração. Nada é preenchido; o que falhar fica registrado em `falhas`.
"""
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

BASES = ["https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos",
         "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/DadosHidrometeorologicos"]
_BLOCO = re.compile(r"<DadosHidrometereologicos .*?</DadosHidrometereologicos>", re.S)


def _campo(blk, k):
    m = re.search(f"<{k}>(.*?)</{k}>", blk, re.S)
    return m[1].strip() if m else ""


def _num(x):
    try:
        return float(x.replace(",", "."))
    except ValueError:
        return None


def ler_xml(txt):
    """{datetime: (nivel_cm, vazao_m3s, chuva_mm)} com None onde o campo veio vazio."""
    out = {}
    for blk in _BLOCO.findall(txt):
        dh = _campo(blk, "DataHora")
        try:
            t = datetime.fromisoformat(dh.strip()[:19]).replace(second=0)
        except ValueError:
            continue
        out[t] = (_num(_campo(blk, "Nivel")), _num(_campo(blk, "Vazao")), _num(_campo(blk, "Chuva")))
    return out


N_429 = [0]   # respostas "Too Many Requests" no processo (a frente de chuva viu 429 com muitas consultas em paralelo)


def baixar(cod, ini, fim, tentativas=4, timeout=60):
    """Registros do posto entre ini e fim (hora local). Devolve (registros, erro ou None).
    HTTP 429: espera 10, 20, 30 s antes de tentar de novo (backoff)."""
    a = (ini - timedelta(days=1)).strftime("%d/%m/%Y")
    b = (fim + timedelta(days=1)).strftime("%d/%m/%Y")
    erro = None
    for k in range(tentativas):
        espera = 3 * (k + 1)
        for base in BASES:
            try:
                req = urllib.request.Request(f"{base}?codEstacao={cod}&dataInicio={a}&dataFim={b}",
                                             headers={"User-Agent": "previne-hec-aovivo/1.0"})
                txt = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
                reg = {t: v for t, v in ler_xml(txt).items() if ini <= t <= fim}
                return reg, None
            except urllib.error.HTTPError as exc:
                erro = f"HTTP {exc.code}"
                if exc.code == 429:
                    N_429[0] += 1
                    espera = 10 * (k + 1)
                    break
            except Exception as exc:  # noqa: BLE001 — falha de rede é registrada, não interrompe o ciclo
                erro = repr(exc)[:160]
        time.sleep(espera)
    return {}, erro


def baixar_varios(codigos, ini, fim, paralelo=8):
    """{cod: registros}, {cod: erro}. paralelo=1 = em série (o recomendado se aparecer 429)."""
    with ThreadPoolExecutor(max(1, paralelo)) as ex:
        res = list(ex.map(lambda c: (c, *baixar(c, ini, fim)), codigos))
    return {c: r for c, r, _ in res}, {c: e for c, _, e in res if e}


def gravar_csv(reg, caminho):
    """Formato de dados/observados (o que hec.observado/hec.nivel leem)."""
    def f(x):
        return "" if x is None else f"{x:.2f}"
    linhas = ["data_hora,nivel_cm,vazao_m3s,chuva_mm"]
    linhas += [f"{t:%Y-%m-%d %H:%M:%S},{f(n)},{f(q)},{f(c)}" for t, (n, q, c) in sorted(reg.items())]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def ler_csv_texto(txt):
    out = {}
    for ln in txt.splitlines()[1:]:
        p = (ln.split(",") + ["", "", "", ""])[:4]
        try:
            t = datetime.fromisoformat(p[0].strip())
        except ValueError:
            continue
        out[t] = tuple(float(x) if x.strip() else None for x in p[1:4])
    return out
