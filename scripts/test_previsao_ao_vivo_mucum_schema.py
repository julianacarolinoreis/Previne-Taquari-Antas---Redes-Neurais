#!/usr/bin/env python3
"""Regression tests for the Muçum live-feed contract."""
from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
import unittest
from pathlib import Path

try:
    from .validar_previsao_ao_vivo_mucum import validate_data
except ImportError:
    from validar_previsao_ao_vivo_mucum import validate_data


ROOT = Path(__file__).resolve().parents[1]
LIVE_SCRIPT = ROOT / "codigo_python" / "01_previsao_ao_vivo" / "gerar_previsao_ao_vivo_mucum.py"
LIVE_SPEC = importlib.util.spec_from_file_location("mucum_live_generator", LIVE_SCRIPT)
LIVE = importlib.util.module_from_spec(LIVE_SPEC)
assert LIVE_SPEC.loader is not None
LIVE_SPEC.loader.exec_module(LIVE)


class MucumFeedContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = {
            "horizontes": {
                key: self._item(key, hours, inputs, role, rank)
                for key, hours, inputs, role, rank in (
                    ("2h", 2, 14, "principal", None),
                    ("4h", 4, 30, "principal", 1),
                    ("4h_versao_b", 4, 15, "comparativo", 2),
                    ("8h", 8, 26, "principal", 1),
                    ("8h_versao_b", 8, 28, "comparativo", 2),
                )
            }
        }

    @staticmethod
    def _item(key, hours, inputs, role, rank):
        item = {
            "horizonte": key,
            "horizonte_h": hours,
            "modelo": "fixture_" + key,
            "tipo": "ALT",
            "status": "ok",
            "modelo_papel": role,
            "selection_rank": rank,
            "disponivel": True,
            "hora_modelo": "2026-08-28T18:00:00",
            "input_grade": "hourly_exact",
            "input_contract_version": "hourly_exact_v1",
            "input_labels": [f"x{i}" for i in range(inputs)],
            "input_values_cm": [0.0] * inputs,
            "nivel_previsto_cm": 100.0,
            "auditoria_inputs": {
                "status": "NORMAL",
                "n_inputs_nao_exatos": 0,
                "usa_interpolacao_nivel": False,
                "usa_vizinho_nivel": False,
                "usa_interpolacao_chuva": False,
                "usa_preenchimento_chuva": False,
            },
        }
        return item

    def test_current_feed_schema(self) -> None:
        validate_data(self.data)

    def test_explicit_missing_prediction_is_valid(self) -> None:
        data = copy.deepcopy(self.data)
        data["horizontes"]["8h_versao_b"]["nivel_previsto_cm"] = None
        data["horizontes"]["8h_versao_b"]["disponivel"] = False
        data["horizontes"]["8h_versao_b"]["status"] = "inputs incompletos — sem previsão nesta hora"
        validate_data(data)

    def test_legacy_cascata_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["horizontes"]["4h"]["modelo"] = "4h_cascata_legado"
        with self.assertRaises(SystemExit):
            validate_data(data)

    def test_stale_guard_uses_nested_horizon_when_2h_is_missing(self) -> None:
        data = copy.deepcopy(self.data)
        data["horizontes"]["2h"]["nivel_previsto_cm"] = None
        data["horizontes"]["2h"]["disponivel"] = False
        data["horizontes"]["2h"]["status"] = "inputs incompletos — sem previsão nesta hora"
        self.assertEqual(
            LIVE._hora_previsao_mais_recente(data),
            dt.datetime(2026, 8, 28, 18, 0),
        )


if __name__ == "__main__":
    unittest.main()
