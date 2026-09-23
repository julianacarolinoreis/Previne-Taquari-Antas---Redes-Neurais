#!/usr/bin/env python3
"""Regression tests for CEMADEN public endpoint fallback behavior."""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "codigo_python"
    / "10_chuvas"
    / "baixar_chuvas_horarias.py"
)
SPEC = importlib.util.spec_from_file_location("baixar_chuvas_horarias", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MOD)


class CEMADENFallbackTests(unittest.TestCase):
    def test_cemaden_public_fetch_failure_marks_status_as_unavailable(self) -> None:
        inicio = dt.datetime(2026, 9, 15, 0, 0)
        fim = dt.datetime(2026, 9, 16, 23, 0)
        with patch.dict(os.environ, {"CEMADEN_TOKEN": ""}):
            with patch.object(
                MOD,
                "baixar_cemaden_chuva_recente",
                side_effect=RuntimeError("falha temporaria"),
            ):
                serie, publico_ok = MOD.cemaden_chuva_horaria("432040401A", inicio, fim)

        self.assertEqual(serie, {})
        self.assertFalse(publico_ok)

    def test_cemaden_public_fetch_success_marks_status_as_available(self) -> None:
        inicio = dt.datetime(2026, 9, 15, 0, 0)
        fim = dt.datetime(2026, 9, 16, 23, 0)
        observacoes = {dt.datetime(2026, 9, 16, 10, 0): 1.2}
        with patch.dict(os.environ, {"CEMADEN_TOKEN": ""}):
            with patch.object(MOD, "baixar_cemaden_chuva_recente", return_value=observacoes):
                serie, publico_ok = MOD.cemaden_chuva_horaria("432040401A", inicio, fim)

        self.assertEqual(serie, observacoes)
        self.assertTrue(publico_ok)


if __name__ == "__main__":
    unittest.main()
