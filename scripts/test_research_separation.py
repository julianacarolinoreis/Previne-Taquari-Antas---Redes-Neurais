"""Guardrails for keeping short live forecasts separate from long research."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ResearchSeparationTests(unittest.TestCase):
    def test_operational_panorama_links_to_research_without_embedding_long_panel(self):
        pages = {
            "santa_tereza_previsao_inundacao.html": "pesquisa_status.html",
            "mucum_previsao_inundacao.html": "pesquisa_status_mucum.html",
        }
        for name, research_page in pages.items():
            html = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn('class="research-panel', html, msg=name)
            self.assertIn('class="research-separate-link"', html, msg=name)
            self.assertIn(research_page, html, msg=name)
            self.assertNotIn("researchRiskUrl:", html, msg=name)


if __name__ == "__main__":
    unittest.main()
