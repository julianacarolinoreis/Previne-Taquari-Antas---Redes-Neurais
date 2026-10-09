"""PEDIDO.json de uma rodada 'in-': md-val2-c002 e lr-g8-c038 (lrdc, calha trapezoidal) nas 33 janelas (sem X20260918).
Uso: python gerar_pedido.py <rodada> <forcamento_v3|forcamento_v3b>"""
import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PED = AQUI.parent / "calibracao_hec_bacia145" / "rodadas" / "PEDIDO.json"
JANELAS = ("S2023_07,S2023_09,S2023_10,S2023_11,S2024_05,S2024_06,S2025_06,S2026_07,X20180721,X20180821,X20180828,"
           "X20180928,X20181028,X20190525,X20191027,X20200626,X20200809,X20210125,X20210525,X20210622,X20220428,X20220525,"
           "X20220614,X20230611,X20230913,X20231028,X20231124,X20241006,X20250918,X20251104,X20260629,X20260809,X20260827")
CANDS = {
    # md-val2-c002 sem ie/atc/ar/nob (neutros com rota mc: Clark padrão e sem seções) -> família lrdc
    "c002": {"qstar": 0.014135104216783987, "mr": 11.71172507393819, "v_alto": 0.7155014832239208, "v_resto": 0.7406691688401893,
             "mn": 0.9845534923619383, "mk": 0.7434900084529428, "v_grandes": 0.7757006298554873, "ks": 0.36870159130556196,
             "dmax": 48.24815269261765, "perc": 11.368382533421787, "imp": 0.037116405128044365, "k1": 27.835744047440855,
             "k2": 856.2654079108399, "fb": 0.5553170077914086, "p1": 0.8681809414083625, "s1": 0.2422491439892351},
    "c038": {"qstar": 0.013472066978957543, "mr": 10.904032937734716, "v_alto": 0.6487484797429014, "v_resto": 1.1469906221234796,
             "mn": 0.9703533779320117, "mk": 0.9865289855468546, "v_grandes": 0.7856423100527201, "ks": 0.3828115845159088,
             "dmax": 40.98735711666086, "perc": 7.249907095503727, "imp": 0.033927977647463144, "k1": 26.108503791822685,
             "k2": 1138.812451357461, "fb": 0.4774166731888625, "p1": 0.8881570572885835, "s1": 0.12515135262806845},
}


def main():
    rodada, forc = sys.argv[1], sys.argv[2]
    assert "X20260918" not in JANELAS and len(JANELAS.split(",")) == 33
    ped = {"rodada": rodada, "janelas": JANELAS, "shards": 20, "papeis": {"E18": "validacao", "E22": "validacao"},
           "forcamento": forc,
           "descricao": f"bug da hora INMET: md-val2-c002 (c000) e lr-g8-c038 (c001) nas 33 janelas com {forc}",
           "candidatos": [{"id": f"{rodada}-c{i:03d}", "rota": "mc", "p": p, "nota": k} for i, (k, p) in enumerate(CANDS.items())]}
    PED.write_text(json.dumps(ped, indent=1, ensure_ascii=False), encoding="utf-8")
    print(rodada, forc, len(ped["candidatos"]), "candidatos x 33 janelas")


if __name__ == "__main__":
    main()
