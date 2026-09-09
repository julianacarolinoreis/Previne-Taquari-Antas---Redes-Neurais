#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "data" / "estudo_bacia_taquari_antas"


class EstruturaStzMucumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads((OUT / "estrutura_stz_mucum_latest.json").read_text(encoding="utf-8"))
        cls.html = (OUT / "estrutura_stz_mucum.html").read_text(encoding="utf-8")

    def test_status(self) -> None:
        self.assertEqual(self.data["status"], "estrutura_proposta_nao_calibrada")
        self.assertIn("nao e calibracao", self.data["purpose"])

    def test_stz_topology_and_closure(self) -> None:
        stz = self.data["models"]["santa_tereza"]
        self.assertEqual(stz["target"], "86472600")
        ids = stz["area_check"]["subbasin_ids"]
        self.assertEqual(
            ids,
            ["SB_PRATA_7868", "SB_ANTAS_RESIDUAL", "SB_CARREIRO_7866", "SB_STZ_RESIDUAL"],
        )
        self.assertTrue(stz["area_check"]["closure_ok"])
        self.assertAlmostEqual(stz["area_check"]["sum_subbasin_km2"], 15775.186, places=2)
        self.assertNotIn("SB_INC_MUCUM", ids)
        self.assertNotIn("J_MUCUM_86510000", [e["id"] for e in stz["elements"]])

    def test_mucum_adds_increment(self) -> None:
        muc = self.data["models"]["mucum"]
        self.assertEqual(muc["target"], "86510000")
        ids = muc["area_check"]["subbasin_ids"]
        self.assertIn("SB_INC_MUCUM", ids)
        self.assertTrue(muc["area_check"]["closure_ok"])
        self.assertAlmostEqual(muc["area_check"]["sum_subbasin_km2"], 15965.207, places=2)
        stz_j = next(e for e in muc["elements"] if e["id"] == "J_STZ_86472600")
        self.assertIn("forcante", stz_j["role"])

    def test_exclusions(self) -> None:
        excl = self.data["excluded_from_both"]
        self.assertTrue({"Guaporé", "Forqueta", "Baixo Taquari-Antas"} <= set(excl["upgs"]))
        self.assertTrue({"7864", "7862"} <= set(excl["families"]))

    def test_html_and_index(self) -> None:
        self.assertIn("ainda sem calibração", self.html.lower())
        self.assertIn("SB_PRATA_7868", self.html)
        self.assertIn("86472600", self.html)
        self.assertIn("86510000", self.html)
        idx = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("estrutura_stz_mucum.html", idx)
        domains = json.loads((OUT / "dois_modelos_stz_mucum_latest.json").read_text(encoding="utf-8"))
        self.assertTrue(
            "estrutura" in domains["status"] or "series" in domains["status"]
        )


if __name__ == "__main__":
    unittest.main()
