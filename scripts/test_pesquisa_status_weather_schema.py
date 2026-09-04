#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Garante que pesquisa_status.html lê o schema v3 do feed meteorológico IFS."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pesquisa_status.html"
FEED = ROOT / "assets" / "data" / "research_weather_santa_tereza_latest.json"


class PesquisaStatusWeatherSchemaTest(unittest.TestCase):
    def test_page_uses_schema_v3_fields(self) -> None:
        html = PAGE.read_text(encoding="utf-8")
        self.assertIn("risk_model", html)
        self.assertIn("rain_point_mm", html)
        self.assertIn("basin_mean_mm", html)
        # Campos do schema antigo não podem ser a fonte principal do painel.
        self.assertNotIn("d.answer_24h", html)
        self.assertNotIn("answer_24h.label", html)
        self.assertNotIn("rain_observed_", html)
        self.assertNotRegex(html, r"\bd\.rna\b")

    def test_live_feed_is_schema_v3(self) -> None:
        feed = json.loads(FEED.read_text(encoding="utf-8"))
        self.assertEqual(feed.get("schema_version"), 3)
        self.assertIn("risk_model", feed)
        self.assertTrue(feed.get("horizons") or (feed.get("forecast") or {}).get("horizons"))
        self.assertNotIn("answer_24h", feed)

    def test_weather_table_headers_match_renderer(self) -> None:
        html = PAGE.read_text(encoding="utf-8")
        for header in ("Chuva no ponto", "Proxy montante", "Máxima", "Estado do risco", "Triagem"):
            self.assertIn(header, html)
        self.assertIsNotNone(re.search(r'id="weather-horizons"', html))


if __name__ == "__main__":
    unittest.main()
