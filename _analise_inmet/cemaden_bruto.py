"""Extrai do estacoes_cemaden.zip (CSV mensais brutos do CEMADEN, RS) as leituras das estaÃ§Ãµes na regiÃ£o da bacia.

A planilha horÃ¡ria processada que o forcamento_v3 usou (estacoes_cemaden/chuvas_horarias_cemaden_bacia.csv) sumiu do
disco em 08/10/2026; sÃ³ sobrou o zip. Aqui guardamos as leituras brutas (codEstacao, datahora como vem, valor) em
cemaden_leituras.pkl e as coordenadas/nomes em cemaden_estacoes.json. A conversÃ£o para hora cheia fica em
estacoes.py (convenÃ§Ã£o conferida contra o forcamento_v3).
Uso: python cemaden_bruto.py
"""
import io
import json
import re
import zipfile
from pathlib import Path

import pandas as pd

AQUI = Path(__file__).resolve().parent
ZIP = Path(r"D:\PREVINE\estacoes_cemaden.zip")
BBOX = (-30.3, -27.9, -53.2, -49.6)    # lat mÃ­n, lat mÃ¡x, lon mÃ­n, lon mÃ¡x (bacia + 30 km)
MESES = [(a, m) for a in range(2022, 2027) for m in range(1, 13) if (2022, 12) <= (a, m) <= (2026, 7)]


def main():
    z = zipfile.ZipFile(ZIP)
    nomes = set(z.namelist())
    partes, est = [], {}
    for a, m in MESES:
        f = f"estacoes_cemaden/{a}/{m:02d}_{a}.csv"
        if f not in nomes:
            print("falta", f, flush=True)
            continue
        d = pd.read_csv(io.BytesIO(z.read(f)), sep=";", decimal=",", encoding="utf-8-sig", dtype={"codEstacao": str})
        d = d[(d.latitude >= BBOX[0]) & (d.latitude <= BBOX[1]) & (d.longitude >= BBOX[2]) & (d.longitude <= BBOX[3])]
        for r in d.drop_duplicates("codEstacao").itertuples():
            est[r.codEstacao] = dict(nome=r.nomeEstacao, municipio=r.municipio, lat=float(r.latitude), lon=float(r.longitude))
        partes.append(pd.DataFrame({"cod": d.codEstacao.values,
                                    "t": pd.to_datetime(d.datahora.str[:19], format="%Y-%m-%d %H:%M:%S"),
                                    "mm": pd.to_numeric(d.valorMedida, errors="coerce").values}))
        print(f, len(d), "leituras;", d.codEstacao.nunique(), "estaÃ§Ãµes", flush=True)
    t = pd.concat(partes, ignore_index=True).drop_duplicates(["cod", "t"])
    t.to_pickle(AQUI / "cemaden_leituras.pkl")
    (AQUI / "cemaden_estacoes.json").write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    print("total", len(t), "leituras;", len(est), "estaÃ§Ãµes")


if __name__ == "__main__":
    main()

