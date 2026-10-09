"""Re-otimização curta a partir do md-val2-c002 no forcamento_v3b (lrdc, rota mc, ordenação por J_pico como o c002):
  in-g0  viz: LHS de 48 com raio 0,05 em torno do c002 (candidato 0 = o próprio c002)
  in-g1..g3  ES (lam 48, mu 8, sigma 0,03 / 0,025 / 0,02) lendo SÓ resultados v3b (in-v3b, in-g*)
  in-val  top 4 por J_pico nas 33 janelas (validação; teste fechado)
Uso: python geracoes.py [primeira_etapa]"""
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
COD = AQUI.parent / "calibracao_hec_bacia145" / "codigo"
PED = AQUI.parent / "calibracao_hec_bacia145" / "rodadas" / "PEDIDO.json"
from gerar_pedido import JANELAS  # noqa: E402


def rodar(args):
    r = subprocess.run([sys.executable, "-B", "rodada_dc.py", *args, "--familia", "lrdc", "--forcamento", "forcamento_v3b",
                        "--objetivo", "J_pico", "--saida", str(PED)], cwd=COD, capture_output=True, text=True, encoding="utf-8")
    print(r.stdout, r.stderr, flush=True)
    if r.returncode:
        sys.exit(1)


def ciclo(rodada, msg):
    r = subprocess.run([sys.executable, "-B", "ciclo.py", "enviar", rodada, msg], cwd=AQUI)
    if r.returncode:
        sys.exit(f"{rodada} falhou")


def res_v3b(ate):
    return [str(AQUI / "res" / r) for r in ["in-v3b"] + [f"in-g{i}" for i in range(ate)]]


def main():
    etapas = ["in-g0", "in-g1", "in-g2", "in-g3", "in-val"]
    ini = etapas.index(sys.argv[1]) if len(sys.argv) > 1 else 0
    sig = {"in-g1": "0.03", "in-g2": "0.025", "in-g3": "0.02"}
    for i, rod in enumerate(etapas[ini:], ini):
        if rod == "in-g0":
            rodar(["viz", "--rodada", rod, "--centro", str(AQUI / "res" / "in-v3b" / "resultado.json") + ":in-v3b-c000",
                   "--raio", "0.05", "--n", "48", "--semente", "21"])
            ciclo(rod, "rodada in-g0: LHS raio 0,05 em torno do md-val2-c002, lrdc, forcamento_v3b")
        elif rod == "in-val":
            rodar(["top", "--rodada", rod, "--n", "4", "--janelas", JANELAS, "--resultados", *res_v3b(4)])
            ciclo(rod, "rodada in-val: top 4 (J_pico) da re-otimização no forcamento_v3b, 33 janelas")
        else:
            rodar(["es", "--rodada", rod, "--lam", "48", "--mu", "8", "--sigma", sig[rod], "--semente", str(21 + i),
                   "--resultados", *res_v3b(i)])
            ciclo(rod, f"rodada {rod}: ES lrdc no forcamento_v3b (J_pico, sigma {sig[rod]})")


if __name__ == "__main__":
    main()
