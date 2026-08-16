#!/usr/bin/env python3
"""Regression tests for the Muçum live-feed contract."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

try:
    from .validar_previsao_ao_vivo_mucum import validate_data
except ImportError:
    from validar_previsao_ao_vivo_mucum import validate_data


ROOT = Path(__file__).resolve().parents[1]


class MucumFeedContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads((ROOT / "previsao_ao_vivo_mucum.json").read_text(encoding="utf-8"))

    def test_current_feed_schema(self) -> None:
        validate_data(self.data)

    def test_explicit_missing_prediction_is_valid(self) -> None:
        data = copy.deepcopy(self.data)
        data["horizontes"]["4h"]["nivel_previsto_cm"] = None
        data["horizontes"]["4h"]["status"] = "inputs incompletos — sem previsão nesta hora"
        validate_data(data)

    def test_legacy_cascata_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["horizontes"]["4h"]["modelo"] = "4h_cascata_legado"
        with self.assertRaises(SystemExit):
            validate_data(data)


if __name__ == "__main__":
    unittest.main()
