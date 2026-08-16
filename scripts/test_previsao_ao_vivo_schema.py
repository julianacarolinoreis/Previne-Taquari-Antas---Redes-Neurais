#!/usr/bin/env python3
"""Deterministic contract tests for the Santa Tereza live feed.

These tests only read the current feed and MAT hash. They never invoke a
robot and never write dynamic JSON, so they are safe to run in CI or locally.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

try:
    from .validar_previsao_ao_vivo import B_MAT, validate_data
except ImportError:  # execução direta: python scripts/test_...py
    from validar_previsao_ao_vivo import B_MAT, validate_data


ROOT = Path(__file__).resolve().parents[1]


class LiveFeedContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads((ROOT / "previsao_ao_vivo.json").read_text(encoding="utf-8"))

    def test_current_feed_schema_and_forward_metadata(self) -> None:
        validate_data(self.data, b_mat=B_MAT)

    def test_explicit_4h_fallback_without_prediction_is_valid(self) -> None:
        data = copy.deepcopy(self.data)
        four = data["horizontes"]["4h"]
        four["nivel_previsto_cm"] = None
        four["status"] = "inputs incompletos — sem previsão nesta hora"
        four["auditoria_inputs"] = {"status": "ATENCAO"}
        validate_data(data, b_mat=B_MAT)

    def test_legacy_cascata_is_rejected_from_public_feed(self) -> None:
        data = copy.deepcopy(self.data)
        data["horizontes"]["4h"]["modelo"] = "4h_cascata_legado"
        with self.assertRaises(SystemExit):
            validate_data(data, b_mat=B_MAT)

    def test_unexpected_horizon_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["horizontes"]["4h_cascata"] = copy.deepcopy(data["horizontes"]["4h"])
        with self.assertRaises(SystemExit):
            validate_data(data, b_mat=B_MAT)

    def test_non_exact_4h_timestamp_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["horizontes"]["4h"]["hora_modelo"] = "2026-08-16T08:30:00"
        with self.assertRaises(SystemExit):
            validate_data(data, b_mat=B_MAT)


if __name__ == "__main__":
    unittest.main()
