"""PEDIDO.json de uma rodada 'av-': lr-g8-c038 nas 33 janelas (mães = forcamento_v3) e nas derivadas das versões ao vivo.
Uso: python gerar_pedido.py <rodada> <versao,...> [--sem-maes]"""
import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PED = AQUI.parent / "calibracao_hec_bacia145" / "rodadas" / "PEDIDO.json"
CAND = {"id": "lr-g8-c038", "rota": "mc", "origem": "mt-b1-c000", "p": {
    "qstar": 0.013472066978957543, "mr": 10.904032937734716, "v_alto": 0.6487484797429014, "v_resto": 1.1469906221234796,
    "mn": 0.9703533779320117, "mk": 0.9865289855468546, "v_grandes": 0.7856423100527201, "ks": 0.3828115845159088,
    "dmax": 40.98735711666086, "perc": 7.249907095503727, "imp": 0.033927977647463144, "k1": 26.108503791822685,
    "k2": 1138.812451357461, "fb": 0.4774166731888625, "p1": 0.8881570572885835, "s1": 0.12515135262806845}}


def main():
    rodada, versoes = sys.argv[1], sys.argv[2].split(",")
    sys.path.insert(0, str(AQUI))
    import estacoes as E
    der = [j for j in (AQUI / "forc" / "janelas_derivadas.txt").read_text(encoding="utf-8").split(",")
           if j.split("__")[2] in versoes]
    for v in versoes:
        f = AQUI / "forc" / f"janelas_derivadas_{v}.txt"
        if f.exists():
            der += [j for j in f.read_text(encoding="utf-8").split(",") if j not in der]
    maes = [] if "--sem-maes" in sys.argv else list(E.JANELAS)
    assert not any("X20260918" in j for j in maes + der)
    ped = {"rodada": rodada, "janelas": ",".join(maes + der), "shards": 20,
           "papeis": {"E18": "validacao", "E22": "validacao"},
           "descricao": f"chuva ao vivo: lr-g8-c038 com forçamentos só de postos realistas ao vivo ({', '.join(versoes)}); "
                        "derivada <mãe>__<t0 = início-1h>__<versão> = janela inteira com a chuva da versão; mães = forcamento_v3",
           "candidatos": [CAND]}
    PED.write_text(json.dumps(ped, indent=1, ensure_ascii=False), encoding="utf-8")
    print(rodada, len(maes), "mães +", len(der), "derivadas")


if __name__ == "__main__":
    main()
