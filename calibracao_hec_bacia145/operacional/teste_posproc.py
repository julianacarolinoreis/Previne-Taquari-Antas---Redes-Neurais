"""Testes do híbrido em sombra (posproc.f_piv, d_piv, carregar_sombra). Uso: python -B teste_posproc.py (ou pytest)."""
import json
import math
import sys
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import posproc as pp  # noqa: E402

Q0, B, QMAX = 2000.0, 1.5, 8000.0


def test_identidade_ate_q0():
    for s in (0.5, 10.0, 1999.9, Q0):
        assert pp.f_piv(s, Q0, B, QMAX) == s


def test_potencia_entre_q0_e_qmax():
    s = 4000.0
    assert math.isclose(pp.f_piv(s, Q0, B, QMAX), s * (s / Q0) ** (B - 1))


def test_fator_congelado_acima_de_qmax():
    fmax = (QMAX / Q0) ** (B - 1)
    for s in (QMAX, 12000.0, 50000.0):
        assert math.isclose(pp.f_piv(s, Q0, B, QMAX) / s, fmax)


def test_fator_limitado_a_rmax():
    assert math.isclose(pp.f_piv(1e5, 100.0, 3.0, 1e6, rmax=3.0), 3e5)


def test_d_piv_continuidade_e_decaimento():
    horas = [datetime(2026, 10, 9, h) for h in range(10, 16)]
    t0 = horas[2]
    S = [3000.0, 3000.0, 3000.0, 5000.0, 5000.0, None]
    O_tv, tau = 2500.0, 24.0
    Q, e = pp.d_piv(S, horas, 1, O_tv, Q0, B, QMAX, tau, t0)
    assert Q[:3] == [None, None, None] and Q[5] is None
    assert math.isclose(e, O_tv - pp.f_piv(3000.0, Q0, B, QMAX))
    assert math.isclose(Q[3], pp.f_piv(5000.0, Q0, B, QMAX) + e * math.exp(-2 / tau))
    assert math.isclose(Q[4], pp.f_piv(5000.0, Q0, B, QMAX) + e * math.exp(-3 / tau))


def test_d_piv_abaixo_de_q0_e_obs_igual_ao_sim_e_identidade():
    horas = [datetime(2026, 10, 9, h) for h in range(6)]
    S = [800.0, 900.0, 1000.0, 1200.0, 1500.0, 1900.0]
    Q, e = pp.d_piv(S, horas, 2, 1000.0, Q0, B, QMAX, 12.0, horas[2])
    assert e == 0.0 and Q[3:] == S[3:]


def test_d_piv_sem_observado_valido_fica_so_F():
    horas = [datetime(2026, 10, 9, h) for h in range(3)]
    Q, e = pp.d_piv([5000.0] * 3, horas, None, None, Q0, B, QMAX, 24.0, horas[0])
    assert e == 0.0 and math.isclose(Q[1], pp.f_piv(5000.0, Q0, B, QMAX))


def test_carregar_sombra_ligado_so_ao_seu_modelo():
    par = json.loads((AQUI / "parametros" / "vo-val-c008.json").read_text(encoding="utf-8"))
    cfg, motivo = pp.carregar_sombra(par)
    assert cfg is not None and motivo == "ligado"
    assert set(cfg["variantes"]) == {"todos_picos", "so_curva"}
    for v in cfg["variantes"].values():
        assert set(v["pontos"]) == {"MUCUM", "ENCANTADO", "LJJ"}
    assert pp.carregar_sombra(par, "nao")[0] is None
    assert pp.carregar_sombra(dict(par, sha256_p="outro"))[0] is None
    c002 = json.loads((AQUI / "parametros" / "md-val2-c002.json").read_text(encoding="utf-8"))
    assert pp.carregar_sombra(c002)[0] is None


if __name__ == "__main__":
    n = 0
    for nome, f in list(globals().items()):
        if nome.startswith("test_"):
            f()
            n += 1
            print("ok", nome)
    print(f"{n} testes ok")
