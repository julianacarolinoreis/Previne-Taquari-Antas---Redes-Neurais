"""Contrato do refinamento visual do MDT de Santa Tereza.

O teste verifica apenas a publicação e a rastreabilidade do produto de
pesquisa. Não certifica a exatidão hidrológica do relevo nem a mancha HAND.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MDT = ROOT / "assets" / "data" / "santa_tereza_inundacao" / "mdt"


class SantaTerezaMdtRefinementTests(unittest.TestCase):
    def test_refined_assets_are_published_without_overwriting_original(self) -> None:
        original = MDT / "altitude_terreno_10m.json"
        refined = MDT / "altitude_terreno_10m_refinado.json"
        visual = MDT / "mdt_santa_tereza_10m_refinado_visual.png"
        report = ROOT / "assets" / "data" / "santa_tereza_inundacao" / "mdt_refinamento_santa_tereza.json"
        for path in (original, refined, visual, report):
            self.assertTrue(path.exists(), path)

        original_meta = json.loads(original.read_text(encoding="utf-8"))
        refined_meta = json.loads(refined.read_text(encoding="utf-8"))
        audit = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(original_meta["png"], "altitude_terreno_10m.png")
        self.assertEqual(refined_meta["original_web_grade"], original.name)
        self.assertEqual(refined_meta["product_type"], "research_visual_refinement")
        self.assertEqual(refined_meta["hydrologic_use"], "visualization_only")
        self.assertEqual(refined_meta["validation_status"], "pending_independent_water_mask_and_footprint_validation")
        self.assertGreater(refined_meta["changed_cells_2m"], 0)
        self.assertEqual(audit["celulas_corrigidas_2m"], refined_meta["changed_cells_2m"])

        with Image.open(visual) as image:
            self.assertEqual(image.size, (refined_meta["cols"], refined_meta["rows"]))
            self.assertEqual(image.mode, "RGBA")

    def test_santa_tereza_pages_use_refined_grade_and_expose_visual_layer(self) -> None:
        for name in ("santa_tereza_inundacao.html", "santa_tereza_previsao_inundacao.html"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("altitude_terreno_10m_refinado.json", text)
            self.assertIn("mdt_santa_tereza_10m_refinado_visual.png", text)
            self.assertIn("MDT refinado", text)
            self.assertIn("MIN_VISUAL_HOLE_M2=5000", text)
            self.assertIn("visualFeature(feat)", text)
            self.assertIn("GeoJSON original não muda", text)


if __name__ == "__main__":
    unittest.main()
