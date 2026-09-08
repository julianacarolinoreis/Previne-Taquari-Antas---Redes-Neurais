#!/usr/bin/env python3
"""Offline checks for the deep RS hierarchy study (no network)."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"


class HierarquiaRsTests(unittest.TestCase):
    def test_hierarchy_not_only_32(self) -> None:
        data = json.loads((OUT / "hierarquia_rs_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["hierarchy_levels"][1]["count"], 25)
        self.assertEqual(data["hierarchy_levels"][2]["count_rs"], 175)
        self.assertEqual(data["hierarchy_levels"][2]["count_g040"], 7)
        self.assertEqual(data["hierarchy_levels"][3]["count_g040_q040"], 32)
        self.assertGreater(data["hierarchy_levels"][4]["count_polygons_hsig_cocursodag_786"], 30000)
        self.assertIn("32 e o nivel de ENQUADRAMENTO", data["correction"]["right_reading"])

    def test_only_g040_contributes_runoff(self) -> None:
        data = json.loads((OUT / "hierarquia_rs_latest.json").read_text(encoding="utf-8"))
        runoff = data["what_influences_taquari_antas"]["runoff_contributors"]
        self.assertEqual([r["codigo"] for r in runoff], ["G040"])
        self.assertIn("So a chuva que cai DENTRO de G040", data["what_influences_taquari_antas"]["hard_rule"])

    def test_geojson_counts(self) -> None:
        bacias = json.loads((OUT / "bacias_rs_25.geojson").read_text(encoding="utf-8"))
        upgs = json.loads((OUT / "upgs_rs_175.geojson").read_text(encoding="utf-8"))
        self.assertEqual(len(bacias["features"]), 25)
        self.assertEqual(len(upgs["features"]), 175)
        g040_upgs = [f for f in upgs["features"] if f["properties"]["cod_bacia"] == "G040"]
        self.assertEqual(len(g040_upgs), 7)

    def test_pages_link_hierarchy(self) -> None:
        index = (OUT / "index.html").read_text(encoding="utf-8")
        mapa = (OUT / "mapa_hierarquia_rs.html").read_text(encoding="utf-8")
        self.assertIn("mapa_hierarquia_rs.html", index)
        self.assertIn("Nao sao so 32", mapa)
        self.assertIn("33133", mapa.replace(",", ""))


class SubbaciasFozesArtifactsTests(unittest.TestCase):
    def test_fozes_guapore_forqueta_downstream(self) -> None:
        data = json.loads((OUT / "subbacias_e_fozes_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["counts"]["subbacias_enquadramento"], 32)
        by = {j["family_code"]: j["position_vs_controls"] for j in data["fozes_principais"]}
        self.assertEqual(by["7864"], "downstream_of_mucum")
        self.assertEqual(by["7862"], "downstream_of_mucum")
        self.assertEqual(by["7866"], "between_antas_and_santa_tereza")


if __name__ == "__main__":
    unittest.main()
