#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "data" / "estudo_bacia_taquari_antas"


class ContratoRnaMascaraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads((OUT / "contrato_rna_mascara_stz_mucum_latest.json").read_text(encoding="utf-8"))
        cls.html = (OUT / "contrato_rna_mascara_stz_mucum.html").read_text(encoding="utf-8")

    def test_status_and_path(self) -> None:
        self.assertIn(
            self.data["status"],
            {"contrato_rna_mascara_v1", "contrato_com_mascara_chuva_gerada"},
        )
        self.assertEqual(self.data["path_chosen_by_study_gate"], "RNA_com_mascara")
        self.assertIn("bloqueado", self.data["hec_status"])
        self.assertIn("treino", " ".join(self.data["explicitly_not_done"]))

    def test_stz_core(self) -> None:
        stz = self.data["models"]["santa_tereza"]
        self.assertEqual(stz["predictand"]["code"], "86472600")
        levels = [f["code"] for f in stz["core_level_features"]]
        rains = [f["code"] for f in stz["core_rain_features"]]
        self.assertEqual(levels, ["86472000", "86507000", "86125500"])
        self.assertEqual(rains, ["86472000", "86472600", "2851072"])
        excluded = {f["code"] for f in stz["excluded_from_v1"]}
        self.assertIn("A894", excluded)
        self.assertIn("86510000", excluded)

    def test_mucum_uses_stz_as_feature(self) -> None:
        muc = self.data["models"]["mucum"]
        self.assertEqual(muc["predictand"]["code"], "86510000")
        levels = [f["code"] for f in muc["core_level_features"]]
        self.assertEqual(levels[0], "86472600")
        self.assertIn("86472000", levels)

    def test_mask_rules(self) -> None:
        ids = {r["id"] for r in self.data["mask_rules"]}
        self.assertIn("R1_buraco_nao_e_zero", ids)
        self.assertIn("R3_linha_incompleta_no_nucleo", ids)
        self.assertIn("ainda sem treino", self.html.lower())
        idx = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("contrato_rna_mascara_stz_mucum.html", idx)


if __name__ == "__main__":
    unittest.main()
