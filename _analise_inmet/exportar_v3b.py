"""Grava calibracao_hec_bacia145/dados/forcamento_v3b/<janela>.json.gz (mesmo formato do forcamento_v3).

33 janelas = forc_corrigido/ (reconstruir_v3.py corrigido). X20260918 (teste, fechada) não é lida nem refeita: é copiada
byte a byte do forcamento_v3, porque o INMET termina em 25/11/2025 e o bug só mexe em leituras INMET (com deslocamento
máximo de +81 h), então essa janela (set-out/2026) é a mesma nas duas versões. O mesmo vale, conferido, para as outras
4 janelas de 2026 (equivalencia.json: corrigido == v3).
"""
import gzip
import json
import shutil
from pathlib import Path

AQUI = Path(__file__).resolve().parent
DADOS = AQUI.parent / "calibracao_hec_bacia145" / "dados"
V3, V3B = DADOS / "forcamento_v3", DADOS / "forcamento_v3b"


def main():
    V3B.mkdir(exist_ok=True)
    n = 0
    for f in sorted((AQUI / "forc_corrigido").glob("*.json")):
        if f.stem.endswith("_postos") or f.stem.startswith("comparativo"):
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        d["versao"] = "v3b: forcamento_v3 com a hora do INMET corrigida (int(hora)//100); _analise_inmet/reconstruir_v3.py"
        with gzip.open(V3B / f"{f.stem}.json.gz", "wt", encoding="utf-8", compresslevel=9) as h:
            json.dump(d, h)
        n += 1
    shutil.copyfile(V3 / "X20260918.json.gz", V3B / "X20260918.json.gz")
    print(n, "janelas corrigidas + X20260918 copiada do v3")


if __name__ == "__main__":
    main()
