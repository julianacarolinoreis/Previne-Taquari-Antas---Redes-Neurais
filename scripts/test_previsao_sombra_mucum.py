#!/usr/bin/env python3
"""Testes do robô em sombra de Muçum (RNAs v2): contrato de chuva, QC ao vivo e hierarquia."""
from __future__ import annotations

import datetime as dt
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "codigo_python" / "01_previsao_ao_vivo" / "gerar_previsao_sombra_mucum.py"
SPEC = importlib.util.spec_from_file_location("sombra_mucum", SCRIPT)
S = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(S)

T0 = dt.datetime(2026, 9, 22, 10, 0)


def horas(n, inicio=T0):
    return [inicio - dt.timedelta(hours=i) for i in range(n)]


class SombraMucumTests(unittest.TestCase):
    def test_rain_hour_label_is_past_only(self) -> None:
        xml = b"""<?xml version="1.0"?><root>
        <r><DataHora>2026-09-22 09:15:00</DataHora><Nivel>500</Nivel><Chuva>1</Chuva></r>
        <r><DataHora>2026-09-22 10:00:00</DataHora><Nivel>510</Nivel><Chuva>2</Chuva></r>
        <r><DataHora>2026-09-22 10:15:00</DataHora><Nivel>515</Nivel><Chuva>4</Chuva></r>
        <r><DataHora>2026-09-22 10:30:00</DataHora><Nivel>520</Nivel><Chuva>-1</Chuva></r>
        </root>"""
        niveis, chuva = S.series_da_resposta(xml)
        self.assertEqual(niveis, {T0: 510.0})                  # só hora cheia exata
        self.assertEqual(chuva[T0], 3.0)                      # (09:00, 10:00] = 09:15 + 10:00
        self.assertEqual(chuva[T0 + dt.timedelta(hours=1)], 4.0)  # 10:15 vai para 11:00; negativo ignorado

    def test_mean_of_station_accumulations(self) -> None:
        chuva = {"A": {h: 1.0 for h in horas(6)}, "B": {h: 2.0 for h in horas(5)}, "C": {}}
        inp = {"tipo": "chuva_acum", "janela_h": 6, "estacoes": ["A", "B", "C"], "nome": "c"}
        x, faltam = S.montar_entradas([inp], {}, chuva, T0)
        self.assertEqual(x, [6.0])          # B incompleto e C vazio ficam fora (COUNT/AVERAGE)
        x, faltam = S.montar_entradas([dict(inp, estacoes=["C"])], {}, chuva, T0)
        self.assertEqual(faltam, ["c"])     # nenhum posto com valor -> ausente, nunca zero

    def test_rain_difference_is_mean_of_station_differences(self) -> None:
        chuva = {"A": {h: (2.0 if i < 24 else 1.0) for i, h in enumerate(horas(48))}}
        inp = {"tipo": "chuva_diferenca", "janela_h": 24, "janela_anterior_h": 24, "estacoes": ["A"], "nome": "d"}
        x, _ = S.montar_entradas([inp], {}, chuva, T0)
        self.assertEqual(x, [24.0])

    def test_level_formulas_match_training(self) -> None:
        n = {"X": {h: float(100 + 10 * (20 - i) + (i % 3)) for i, h in enumerate(horas(21))}}
        inputs = [{"tipo": "nivel", "estacao": "X", "defasagem_h": 0, "nome": "n"},
                  {"tipo": "vel_nivel", "estacao": "X", "defasagem_h": 4, "nome": "d4"},
                  {"tipo": "acel_nivel", "estacao": "X", "defasagem_h": 12, "nome": "a12"}]
        x, faltam = S.montar_entradas(inputs, n, {}, T0)
        N = lambda k: n["X"][T0 - dt.timedelta(hours=k)]
        self.assertEqual(faltam, [])
        self.assertEqual(x, [N(0), N(0) - N(4), (N(0) - N(1)) - (N(12) - N(13))])

    def test_live_qc_drops_zero_bitflip_and_stuck_sensor(self) -> None:
        alvo = {h: 500.0 + 10 * i for i, h in enumerate(horas(10))}   # Muçum variando 90 cm
        serie = {h: 42500.0 for h in horas(8)}                         # barragem travada 8 h
        serie[T0 - dt.timedelta(hours=9)] = 0.0
        limpa = S.qc_niveis("86489000", serie, {"86489000": {"min": 40000, "max": 50000}}, alvo)
        self.assertEqual(limpa, {})
        regua = {T0: 16438.0, T0 - dt.timedelta(hours=1): 120.0}
        self.assertEqual(S.qc_niveis("86099000", regua, {}, alvo), {T0 - dt.timedelta(hours=1): 120.0})

    def test_live_qc_drops_impossible_jump_until_level_returns(self) -> None:
        # 86298000 em 06/10/2026: 171 -> 1475 -> 1892 cm em 2 h sem cheia; volta a 180
        t0 = dt.datetime(2026, 10, 6, 6, 0)
        valores = [172, 171, 254, 1475, 1870, 1802, 1860, 1892, 180]
        serie = {t0 + dt.timedelta(hours=i): float(v) for i, v in enumerate(valores)}
        limpa = S.qc_niveis(S.ALVO, serie, {S.ALVO: {"min": 1, "max": 3260, "salto_max_1h": 696}})
        self.assertEqual(sorted(limpa.values()), [171.0, 172.0, 180.0, 254.0])
        # interrupção real (> 3 h sem leitura) refaz a âncora
        serie2 = {t0: 200.0, t0 + dt.timedelta(hours=5): 1200.0, t0 + dt.timedelta(hours=6): 1210.0}
        self.assertEqual(len(S.qc_niveis(S.ALVO, serie2, {S.ALVO: {"salto_max_1h": 696}})), 3)

    def test_hierarchy_skips_control_and_falls_back_when_inputs_missing(self) -> None:
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            mat = str(Path(d) / "m.mat")
            Path(mat).write_bytes(b"x")
            niveis = {S.ALVO: {h: 500.0 for h in horas(3)}}
            nivel = lambda est: [{"tipo": "nivel", "estacao": est, "defasagem_h": 0, "nome": f"n{est}"}]
            cfg = {"horizonte_h": 4, "modelos": [
                {"modelo_id": "ctrl", "nivel_hierarquia": 0, "mat": mat, "inputs": nivel(S.ALVO)},
                {"modelo_id": "n1", "nivel_hierarquia": 1, "mat": mat, "inputs": nivel("86472000")},
                {"modelo_id": "n2", "nivel_hierarquia": 2, "mat": mat, "inputs": nivel(S.ALVO),
                 "faixa_e95_cm": {"geral": 40.0}},
            ]}
            with mock.patch.object(S.R, "prever", return_value=12.0), \
                 mock.patch.object(S.R, "antecedencia_efetiva", return_value=(3.5, True)):
                escolhido, todos = S.prever_horizonte(cfg, niveis, {}, sorted(niveis[S.ALVO]), T0)
        self.assertEqual(escolhido["modelo"], "n2")              # n1 sem LJJ; controle nunca é escolhido
        self.assertEqual([t["status"] for t in todos], ["ok", "entradas incompletas (1)", "ok"])
        self.assertEqual(escolhido["nivel_previsto_cm"], 512.0)
        self.assertEqual(escolhido["faixa_incerteza"]["min_cm"], 472)


if __name__ == "__main__":
    unittest.main()
