"""Contract tests for the unified historical replay research room."""

from __future__ import annotations

import math
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_unified_event_spatial_dashboard as dashboard


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key == "id" and value:
                self.ids.append(value)


def coordinates(geometry: dict[str, object]):
    value = geometry["coordinates"]
    stack = [value]
    while stack:
        item = stack.pop()
        if (
            isinstance(item, list)
            and len(item) >= 2
            and isinstance(item[0], (int, float))
            and isinstance(item[1], (int, float))
        ):
            yield float(item[0]), float(item[1])
        elif isinstance(item, list):
            stack.extend(item)


class DashboardDataContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.events = dashboard.mucum_events() + dashboard.santa_events()
        cls.spatial = dashboard.spatial_data()

    def test_event_inventory_and_keys(self) -> None:
        self.assertEqual(27, len(self.events))
        self.assertEqual(6, sum(e["city_key"] == "mucum" for e in self.events))
        self.assertEqual(21, sum(e["city_key"] == "santa_tereza" for e in self.events))
        self.assertEqual(len(self.events), len({e["key"] for e in self.events}))

    def test_series_are_ordered_and_numbers_are_finite(self) -> None:
        from datetime import datetime

        for event in self.events:
            stamps = [datetime.fromisoformat(row[0]) for row in event["series"]]
            self.assertEqual(stamps, sorted(stamps), event["key"])
            self.assertEqual(len(stamps), len(set(stamps)), event["key"])
            for row in event["series"]:
                for value in row[1:]:
                    self.assertTrue(value is None or math.isfinite(value), event["key"])
            for value in event["metrics"].values():
                self.assertTrue(value is None or math.isfinite(value), event["key"])

    def test_linked_sources_exist_and_are_nonempty(self) -> None:
        for event in self.events:
            for field in ("metrics_source", "series_source"):
                source = dashboard.ROOT / event[field]
                self.assertTrue(source.is_file(), f"{event['key']}/{field}")
                self.assertGreater(source.stat().st_size, 0, f"{event['key']}/{field}")
        for city in self.spatial.values():
            for field in ("background", "grid_source", "contour_source"):
                relative = str(city[field]).removeprefix("../")
                source = dashboard.ROOT / relative
                self.assertTrue(source.is_file(), f"{city['label']}/{field}")
                self.assertGreater(source.stat().st_size, 0, f"{city['label']}/{field}")
            published = {float(level) for level in city["published"]}
            available = {item["level"] for item in city["contours"]}
            self.assertTrue(published <= available, city["label"])

    def test_spatial_coordinates_intersect_declared_bounds(self) -> None:
        for key, city in self.spatial.items():
            bounds = city["bounds"]
            for collection in ("contours", "grid"):
                for item in city[collection]:
                    points = list(coordinates(item["geometry"]))
                    self.assertTrue(points, f"{key}/{collection}")
                    self.assertTrue(
                        any(
                            bounds["west"] <= lon <= bounds["east"]
                            and bounds["south"] <= lat <= bounds["north"]
                            for lon, lat in points
                        ),
                        f"{key}/{collection} outside visual extent",
                    )
            self.assertTrue(all(city["level_min"] <= c["level"] <= city["level_max"] for c in city["contours"]))

    def test_generated_page_is_self_contained_and_ids_are_unique(self) -> None:
        dashboard.main()
        page = (dashboard.ROOT / "pesquisas" / "replay-hidrologico-espacial.html").read_text(encoding="utf-8")
        self.assertNotRegex(page, r"__(?:DATA|RUNTIME|EXTRA_CSS)__")
        self.assertNotIn("Rede completa · 3 zonas", page)
        self.assertNotIn("status = \"fechado\"", page)
        self.assertIn("generalização ainda não demonstrada", page)
        self.assertIn("somente diagnóstico", page)
        self.assertIn("não é uma superfície espacial de precipitação validada", page)
        self.assertIn('class="panel map-panel" aria-labelledby="mapTitle"', page)
        self.assertIn('role="region" aria-label="Catálogo completo de replays', page)
        self.assertIn('<th scope="col">Evento</th>', page)
        self.assertNotIn('class="grid-cell" aria-hidden="true"', page)
        parser = IdCollector()
        parser.feed(page)
        duplicates = sorted({item for item in parser.ids if parser.ids.count(item) > 1})
        self.assertEqual([], duplicates)
        self.assertEqual(1, len(re.findall(r"<script>const DATA=", page)))


if __name__ == "__main__":
    unittest.main()
