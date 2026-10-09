"""Baixa o MERGE-CPTEC horário (GPM IMERG + pluviômetros, 0,1°, HTTP aberto) para as horas das 33 janelas
(teste fechado). Cache em cache_merge/AAAA/MM/DD/MERGE_CPTEC_AAAAMMDDHH.grib2 (nome = hora UTC).
Uso: python baixar_merge.py [n_threads]"""
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import estacoes as E

AQUI = Path(__file__).resolve().parent
CACHE = AQUI / "cache_merge"
URL = "https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/HOURLY/{t:%Y/%m/%d}/MERGE_CPTEC_{t:%Y%m%d%H}.grib2"


def horas_utc():
    hs = set()
    for s in E.JANELAS:
        c = E.SIMULACOES[s]
        t = c["ini"] + timedelta(hours=3 - 3)      # BRT -> UTC (+3 h), com 3 h de folga antes
        while t <= c["fim"] + timedelta(hours=3 + 3):
            hs.add(t)
            t += timedelta(hours=1)
    return sorted(hs)


def baixar(t):
    f = CACHE / f"{t:%Y/%m/%d}" / f"MERGE_CPTEC_{t:%Y%m%d%H}.grib2"
    if f.exists() and f.stat().st_size > 1000:
        return "cache"
    f.parent.mkdir(parents=True, exist_ok=True)
    for k in range(4):
        try:
            d = urllib.request.urlopen(urllib.request.Request(URL.format(t=t), headers={"User-Agent": "previne-pesquisa/1.0"}),
                                       timeout=60).read()
            f.write_bytes(d)
            return "ok"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "404"
            time.sleep(3 * (k + 1))
        except Exception:  # noqa: BLE001
            time.sleep(3 * (k + 1))
    return "falha"


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    hs = horas_utc()
    print(len(hs), "horas", flush=True)
    st = {}
    with ThreadPoolExecutor(n) as ex:
        for i, r in enumerate(ex.map(baixar, hs)):
            st[r] = st.get(r, 0) + 1
            if i % 500 == 0:
                print(i, st, flush=True)
    print("fim", st, flush=True)
    falt = [str(t) for t, r in zip(hs, [None] * len(hs))]
    (AQUI / "log_baixar_merge.txt").write_text(str(st), encoding="utf-8")


if __name__ == "__main__":
    main()
