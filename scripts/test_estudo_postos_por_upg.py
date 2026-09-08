#!/usr/bin/env python3
"""Offline checks for station inventory by UPG / BHO6 family."""

import json
import unittest
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "data" / "estudo_bacia_taquari_antas"


class PostosPorUpgTests(unittest.TestCase):
    def test_all_seven_upgs_have_stations(self) -> None:
        data = json.loads((OUT / "postos_por_upg_latest.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(data["counts"]["inside_g040"], 100)
        self.assertEqual(data["coverage_gaps"]["upg_without_stations"], [])
        for upg in [
            "Alto Taquari-Antas",
            "Médio Taquari-Antas",
            "Baixo Taquari-Antas",
            "Prata",
            "Carreiro",
            "Guaporé",
            "Forqueta",
        ]:
            self.assertIn(upg, data["by_upg"])
            self.assertGreater(len(data["by_upg"][upg]), 0)

    def test_major_bho6_families_present(self) -> None:
        data = json.loads((OUT / "postos_por_upg_latest.json").read_text(encoding="utf-8"))
        fams = data["by_bho6_family"]
        for fam in ("786", "7868", "7866", "7864", "7862"):
            self.assertIn(fam, fams)
            self.assertGreater(len(fams[fam]), 0)

    def test_previne_gap_documented(self) -> None:
        data = json.loads((OUT / "postos_por_upg_latest.json").read_text(encoding="utf-8"))
        without = set(data["coverage_gaps"]["upgs_without_previne_seed"])
        self.assertTrue({"Guaporé", "Forqueta"} <= without)
        self.assertIn("Guapore e Forqueta", data["reading"]["previne_gap"])

    def test_geojson_and_map(self) -> None:
        fc = json.loads((OUT / "postos_g040.geojson").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(fc["features"]), 100)
        html = (OUT / "mapa_postos_upg.html").read_text(encoding="utf-8")
        self.assertIn("postos por UPG", html.lower())
        index = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("mapa_postos_upg.html", index)


if __name__ == "__main__":
    unittest.main()
