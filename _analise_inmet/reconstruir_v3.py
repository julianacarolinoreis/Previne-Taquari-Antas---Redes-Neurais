"""Refaz o forcamento_v3 inteiro com o código ORIGINAL (forcamento_v3.main: todos os postos, cobertura >= 50 %,
QC iterativo por vizinhos, teste de defasagem, IDW p=2 por hora), importado de D:\\PREVINE\\hec_calibracao_20261005
sem gravar nada lá. Só duas trocas:
  * chuva_fontes.cemaden -> cemaden.ler (zip bruto; a planilha processada sumiu);
  * modo 'corrigido': chuva_fontes.inmet -> inmet.ler(bug=False) (hora = int(hora)//100).
    No modo 'bug' o chuva_fontes.inmet original é usado como está.
Uso: python reconstruir_v3.py bug|corrigido  -> forc_<modo>/<janela>.json e <janela>_postos.json (33 janelas, sem o teste)
"""
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
AQUI = Path(__file__).resolve().parent
ORIG = Path(r"D:\PREVINE\hec_calibracao_20261005")
os.environ["HEC_CATALOGO"] = "catalogo_ampliado.json"
os.environ.pop("HEC_FORC", None)
sys.path.insert(0, str(ORIG))
sys.path.insert(1, str(AQUI))
import chuva_fontes as CF  # noqa: E402
import forcamento_v3 as V3  # noqa: E402
from comum import SIMULACOES  # noqa: E402

import cemaden  # noqa: E402
import inmet  # noqa: E402

TESTE = "X20260918"


def main():
    modo = sys.argv[1]
    assert modo in ("bug", "corrigido")
    CF.cemaden = cemaden.ler
    if modo == "corrigido":
        CF.inmet = lambda: inmet.ler(False)
    V3.FORC3 = AQUI / f"forc_{modo}"
    janelas = sys.argv[2:] or [s for s in SIMULACOES if s != TESTE]
    assert TESTE not in janelas
    sys.argv = [sys.argv[0], *janelas]
    V3.main()


if __name__ == "__main__":
    main()
