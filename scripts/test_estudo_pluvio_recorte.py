#!/usr/bin/env python3
"""Offline checks for pluviometry inventory + model-scope decision brief."""

import json
import unittest
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "data" / "estudo_bacia_taquari_antas"


class PluvioRecorteTests(unittest.TestCase):
    def test_rain_inventory_covers_upgs(self) -> None:
        data = json.loads((OUT / "pluviometria_g040_latest.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(data["counts"]["rain_stations_inside_g040"], 50)
        self.assertGreaterEqual(data["counts"]["by_rede"].get("ANA", 0), 50)
        self.assertIn("INMET", data["counts"]["by_rede"])
        for upg in ("Prata", "Carreiro", "Guaporé", "Forqueta", "Médio Taquari-Antas"):
            self.assertGreater(data["coverage"]["by_upg_counts"].get(upg, 0), 0)

    def test_previne_rain_gap_documented(self) -> None:
        data = json.loads((OUT / "pluviometria_g040_latest.json").read_text(encoding="utf-8"))
        without = set(data["coverage"]["upgs_without_previne_rain_seed"])
        self.assertTrue({"Guaporé", "Forqueta"} & without or {"Guaporé", "Forqueta", "Alto Taquari-Antas", "Baixo Taquari-Antas"} & without)
        self.assertIn("PREVINE", data["reading"]["previne_rain_cluster"])

    def test_decision_awaits_human(self) -> None:
        data = json.loads((OUT / "recorte_modelo_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "aguardando_decisao")
        ids = [o["id"] for o in data["options"]]
        self.assertEqual(ids, ["A_corredor_mucum", "B_g040_completa", "C_hibrido_explicito"])
        self.assertIn("NAO escolhe", data["recommendation_engine_not_human"])
        html = (OUT / "recorte_modelo.html").read_text(encoding="utf-8")
        self.assertIn("Antes do HEC", html)
        self.assertIn("A_corredor_mucum", html)
        index = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("recorte_modelo.html", index)


if __name__ == "__main__":
    unittest.main()
