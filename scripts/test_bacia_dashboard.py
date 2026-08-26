"""Contract tests for the integrated Taquari–Antas dashboard page."""

from __future__ import annotations

import json
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class _Ids(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])


class BasinDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = ROOT / "dashboard_bacia.html"
        self.text = self.page.read_text(encoding="utf-8")

    def test_page_and_assets_are_wired(self) -> None:
        self.assertTrue(self.page.exists())
        self.assertTrue((ROOT / "assets/css/bacia_dashboard.css").exists())
        self.assertTrue((ROOT / "assets/js/bacia_dashboard.js").exists())
        for token in ("data-bacia-dashboard", "assets/css/bacia_dashboard.css", "assets/js/bacia_dashboard.js", "dashboard_bacia.html"):
            self.assertIn(token, self.text)

    def test_controls_cover_basin_stations_and_horizons(self) -> None:
        for token in ('data-station="basin"', 'data-station="santa"', 'data-station="mucum"', 'data-horizon="24"', 'data-horizon="72"', 'data-horizon="168"'):
            self.assertIn(token, self.text)
        parser = _Ids()
        parser.feed(self.text)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))

    def test_public_semantics_are_explicit(self) -> None:
        self.assertIn("não é a mesma coisa que probabilidade de inundação", self.text)
        self.assertIn("sem alerta automático", self.text)
        script = (ROOT / "assets/js/bacia_dashboard.js").read_text(encoding="utf-8")
        self.assertIn("Não há probabilidade conjunta publicada", script)
        self.assertIn("PROBABILIDADE · experimental", script)
        self.assertIn("PROXY · célula espacial", script)

    def test_compact_feeds_have_expected_horizons(self) -> None:
        for name in ("research_visual_patterns_santa_tereza_latest.json", "research_visual_patterns_mucum_latest.json"):
            feed = json.loads((ROOT / "assets/data" / name).read_text(encoding="utf-8"))
            self.assertEqual([row["hours"] for row in feed["horizons"]], [24, 48, 72, 120, 168])
            self.assertTrue(feed["events"])


if __name__ == "__main__":
    unittest.main()
