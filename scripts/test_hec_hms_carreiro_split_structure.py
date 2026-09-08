#!/usr/bin/env python3
"""Tests for the Carreiro-split HEC structure package."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_hec_hms_carreiro_split_structure.py"
OUT = ROOT / "assets" / "data" / "hec_hms_carreiro_split"


class CarreiroSplitStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run([sys.executable, str(SCRIPT)], check=True, cwd=ROOT)

    def test_artifacts(self) -> None:
        self.assertTrue((OUT / "carreiro_split_structure_latest.json").exists())
        self.assertTrue((OUT / "index.html").exists())
        self.assertTrue((OUT / "Taquari_Antas_CarreiroSplit.basin.txt").exists())

    def test_split_math_and_topology(self) -> None:
        data = json.loads((OUT / "carreiro_split_structure_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "structure_proposed_not_calibrated")
        self.assertTrue(data["area_check"]["area_closure_ok"])
        self.assertGreater(data["area_check"]["carreiro_fraction_of_stz_increment"], 0.85)
        ids = [e["id"] for e in data["elements"]]
        self.assertIn("SB_CARREIRO_7866", ids)
        self.assertIn("SB_STZ_RESIDUAL", ids)
        self.assertIn("J_CARREIRO_CONFLUENCE", ids)
        self.assertEqual(data["compared_to_previous_skeleton"]["proposed"]["subbasins"], 4)
        self.assertEqual(data["compared_to_previous_skeleton"]["proposed"]["reaches"], 3)
        self.assertIn("Nenhuma busca de parâmetros", data["explicitly_not_done"][0])

    def test_html_is_honest(self) -> None:
        html = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("não é calibração", html.lower())
        self.assertIn("SB_CARREIRO", html)
        self.assertIn("86507000", html)


if __name__ == "__main__":
    unittest.main()
