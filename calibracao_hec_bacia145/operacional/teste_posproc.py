"""Testes do pós-processamento (posproc: f_piv, d_piv, carregar_sombra, aplicar_titular, sombra_ponto) e da sombra
de porte (porte.carregar, indice_s). Uso: python -B teste_posproc.py (ou pytest)."""
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import geo  # noqa: E402
import porte  # noqa: E402
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


def test_pc_f8_tem_hibrido_e_tau():
    par = json.loads((AQUI / "parametros" / "pc-f8-c025.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(json.dumps(par["p"], sort_keys=True).encode()).hexdigest()[:16] == par["sha256_p"]
    assert all(len(par["correcao"]["tau_h"][c]) == 48 for c in ("MUCUM", "ENCANTADO", "LJJ"))
    cfg, motivo = pp.carregar_sombra(par)
    assert motivo == "ligado" and cfg["modelo"] == "pc-f8-c025"
    assert set(cfg["variantes"]) == {"todos_picos", "so_curva"}


def _ponto_sintetico(nome="MUCUM"):
    horas = [datetime(2026, 10, 9) + timedelta(hours=i) for i in range(30)]
    t0 = horas[10]
    obs_q = {t: 3500.0 for t in horas[:11]}
    obs_n = {t: 900.0 for t in horas[:11]}
    sims = {"ecmwf": {t: 2500.0 + 150.0 * i for i, t in enumerate(horas)}}
    corr = dict(tau_h={nome: [24] * 48})
    p = pp.ponto(nome, horas, t0, sims, obs_q, obs_n, corr, {}, 19)
    return p, horas, t0, sims, obs_q, obs_n


def test_aplicar_titular_publica_d_piv_e_guarda_aditiva():
    p, horas, t0, sims, obs_q, obs_n = _ponto_sintetico()
    adit = json.loads(json.dumps(p["corrigido"]))
    cfg = dict(metodo="d_piv", modelo="x", arquivo="x.json", rmax=3.0,
               variantes={"so_curva": {"pontos": {"MUCUM": dict(q0=Q0, b=B, qmax=QMAX, tau_h=12)}}})
    assert pp.aplicar_titular(p, "MUCUM", horas, t0, sims, obs_q, obs_n, {}, cfg, "so_curva")
    assert p["aditiva"]["corrigido"] == adit
    S = [sims["ecmwf"][t] for t in horas]
    Q, e = pp.d_piv(S, horas, 10, 3500.0, Q0, B, QMAX, 12, t0)
    assert p["corrigido"]["ecmwf"] == [pp._r(x) for x in Q] and p["erro_em_tv_m3s"]["ecmwf"] == pp._r(e)
    assert p["pos_processamento"]["variante"] == "so_curva" and "corrigido" not in p["pos_processamento"]
    sem = dict(cfg, variantes={"so_curva": {"pontos": {}}})
    p2 = _ponto_sintetico()[0]
    assert not pp.aplicar_titular(p2, "MUCUM", horas, t0, sims, obs_q, obs_n, {}, sem, "so_curva")
    assert "aditiva" not in p2


def test_sombra_exclui_a_variante_publicada():
    p, horas, t0, sims, obs_q, obs_n = _ponto_sintetico()
    v = {"pontos": {"MUCUM": dict(q0=Q0, b=B, qmax=QMAX, tau_h=12)}}
    cfg = dict(metodo="d_piv", modelo="x", arquivo="x.json", variantes={"so_curva": v, "todos_picos": v})
    hs = pp.sombra_ponto(p, "MUCUM", horas, t0, sims, obs_q, obs_n, {}, cfg, "so_curva")
    assert set(hs["variantes"]) == {"todos_picos"}
    assert pp.sombra_ponto(p, "MUCUM", horas, t0, sims, obs_q, obs_n, {}, dict(cfg, variantes={"so_curva": v}),
                           "so_curva") is None


def test_porte_carregar_e_indice_s():
    assert porte.carregar("nao", "hibrido")[0] is None
    assert porte.carregar("auto", "aditiva")[0] is None
    cfg, motivo = porte.carregar("auto", "hibrido")
    assert motivo == "ligado" and not cfg["forcar"] and cfg["regra"]["limiar_mm"] == 83.4
    assert porte.carregar("sempre", "aditiva")[0]["forcar"]
    g = cfg["parametros"]
    assert hashlib.sha256(json.dumps(g["p"], sort_keys=True).encode()).hexdigest()[:16] == g["sha256_p"]
    horas = [datetime(2026, 10, 9) + timedelta(hours=i) for i in range(100)]
    t0 = horas[30]
    subs = set(cfg["regra"]["subbacias_mucum"])
    # 1 mm/h em todas as sub-bacias de Muçum: 24 h até t0 + 48 h depois = 72 mm; fora de Muçum não conta
    ch = {n: [1.0 if n in subs else 50.0] * len(horas) for n in geo.nomes()}
    S, s24, s48 = porte.indice_s(dict(chuva_por_subbacia=ch), horas, t0, cfg)
    assert (S, s24, s48) == (72.0, 24.0, 48.0)


if __name__ == "__main__":
    n = 0
    for nome, f in list(globals().items()):
        if nome.startswith("test_"):
            f()
            n += 1
            print("ok", nome)
    print(f"{n} testes ok")
