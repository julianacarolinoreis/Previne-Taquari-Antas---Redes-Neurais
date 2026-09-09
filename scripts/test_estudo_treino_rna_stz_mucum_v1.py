#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "data" / "estudo_bacia_taquari_antas"


class TreinoRnaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads((OUT / "treino_rna_stz_mucum_v1_latest.json").read_text(encoding="utf-8"))

    def test_status_and_models(self) -> None:
        self.assertEqual(self.data["status"], "treino_rna_v1_concluido_nao_operacional")
        self.assertIn("nao_operacional", self.data["status"])
        self.assertTrue((OUT / "treino_rna_stz_mucum_v1" / "modelo_stz.joblib").exists())
        self.assertTrue((OUT / "treino_rna_stz_mucum_v1" / "modelo_mucum.joblib").exists())

    def test_teste_beats_or_near_persistence_skill(self) -> None:
        for key in ("santa_tereza", "mucum"):
            teste = self.data["models"][key]["metrics"]["Teste"]
            self.assertGreater(teste["n"], 50)
            self.assertLess(teste["rmse_cm"], teste["persistencia_rmse_cm"])
            self.assertGreater(teste["skill_rmse_vs_pers"], 0.0)

    def test_html(self) -> None:
        html = (OUT / "treino_rna_stz_mucum_v1.html").read_text(encoding="utf-8")
        self.assertIn("ainda pesquisa", html.lower())
        self.assertIn("86472600", html)
        self.assertIn("86510000", html)


if __name__ == "__main__":
    unittest.main()
