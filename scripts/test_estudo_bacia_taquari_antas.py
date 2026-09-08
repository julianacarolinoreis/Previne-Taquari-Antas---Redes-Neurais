#!/usr/bin/env python3
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_estudo_bacia_taquari_antas.py"
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"


class EstudoBaciaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run([sys.executable, str(SCRIPT)], check=True, cwd=ROOT)

    def test_study_states_full_basin_not_mucum(self) -> None:
        data = json.loads((OUT / "estudo_bacia_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["official_basin"]["area_km2_sema"], 26430)
        self.assertEqual(data["official_units_of_management"]["count_ug"], 7)
        self.assertEqual(data["official_units_of_management"]["count_subbasins"], 32)
        self.assertFalse(
            data["critical_distinction"]["evidence_local"]["guapore_forqueta_in_mucum_upstream_clip"]
        )
        self.assertIn("16 mil", data["critical_distinction"]["finding"])

    def test_html_is_study_not_hec(self) -> None:
        html = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("antes do HEC", html)
        self.assertIn("26.430", html)
        self.assertIn("32", html)


if __name__ == "__main__":
    unittest.main()
