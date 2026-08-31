#!/usr/bin/env python3
"""Regression tests for the Santa Tereza prospective weather feed."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .build_santa_weather_feed import build_feed, parse_forecast_hour, parse_hour, read_live
except ImportError:
    from build_santa_weather_feed import build_feed, parse_forecast_hour, parse_hour, read_live


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def payload(grid_lat: float, grid_lon: float, rain: float) -> dict:
    times = [(NOW + timedelta(hours=index)).isoformat().replace("+00:00", "Z") for index in range(1, 193)]
    return {
        "latitude": grid_lat,
        "longitude": grid_lon,
        "hourly": {
            "time": times,
            "precipitation": [rain] * len(times),
            "soil_moisture_0_to_7cm": [0.42] * len(times),
            "temperature_2m": [18.0] * len(times),
        },
    }


class SantaWeatherFeedTests(unittest.TestCase):
    def test_naive_live_timestamp_is_brt(self) -> None:
        self.assertEqual(
            parse_hour("2026-08-30T09:00:00"),
            datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        )

    def test_naive_open_meteo_hour_is_utc(self) -> None:
        self.assertEqual(
            parse_forecast_hour("2026-08-30T09:00:00"),
            datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc),
        )

    def test_live_reading_keeps_source_time_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live.json"
            path.write_text(
                json.dumps({"telemetria_ultima_em": "2026-08-30T08:45:00", "telemetria_ultima_nivel_cm": 444}),
                encoding="utf-8",
            )
            result = read_live(path, NOW)
        self.assertEqual(result["state"], "fresh")
        self.assertEqual(result["observed_at_utc"], "2026-08-30T11:45:00Z")
        self.assertEqual(result["age_minutes"], 15.0)

    def test_spatial_proxy_deduplicates_returned_grid_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "points.json"
            catalog.write_text(
                json.dumps(
                    {
                        "points": [
                            {"name": "A", "role": "upstream_monitoring_point", "latitude": -28.5, "longitude": -51.3},
                            {"name": "A duplicada", "role": "upstream_monitoring_point", "latitude": -28.6, "longitude": -51.4},
                            {"name": "B", "role": "upstream_monitoring_point", "latitude": -29.0, "longitude": -51.8},
                            {"name": "Santa Tereza", "role": "target_santa_tereza", "latitude": -29.1781, "longitude": -51.7322},
                            {"name": "Muçum", "role": "target_mucum", "latitude": -29.1672, "longitude": -51.8686},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            live = root / "live.json"
            live.write_text(
                json.dumps({"telemetria_ultima_em_utc": "2026-08-30T11:45:00Z", "telemetria_ultima_nivel_cm": 444}),
                encoding="utf-8",
            )
            missing_previous = root / "previous-does-not-exist.json"
            feed = build_feed(
                [
                    payload(-28.5, -51.25, 2.0),
                    payload(-28.5, -51.25, 9.0),
                    payload(-29.0, -51.75, 4.0),
                    payload(-29.25, -51.75, 1.0),
                    payload(-29.25, -51.75, 8.0),
                ],
                "https://example.test/ecmwf",
                live,
                catalog,
                now=NOW,
                direct={"status": "unavailable", "horizons": []},
                previous_path=missing_previous,
            )

        row24 = next(item for item in feed["horizons"] if item["hours"] == 24)
        self.assertEqual(row24["rain_point_mm"], 24.0)
        # (2 mm/h + 4 mm/h) / 2 unique cells * 24 h = 72 mm.
        self.assertEqual(row24["basin_mean_mm"], 72.0)
        self.assertEqual(row24["basin_max_mm"], 96.0)
        self.assertEqual(feed["basin_aggregation"]["unique_upstream_grid_cells"], 2)
        self.assertTrue(feed["basin_aggregation"]["deduplication_applied"])
        self.assertFalse(feed["basin_aggregation"]["hydrologic_mask"])
        self.assertEqual(feed["basin_aggregation"]["status"], "upstream_monitoring_grid_proxy")
        self.assertFalse(feed["official_alert"])
        self.assertFalse(feed["risk_model"]["probabilities_available"])


if __name__ == "__main__":
    unittest.main()
