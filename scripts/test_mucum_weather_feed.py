#!/usr/bin/env python3
"""Regression tests for the Muçum prospective weather feed."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .build_mucum_weather_feed import build_feed, parse_forecast_hour, parse_hour, read_live
except ImportError:
    from build_mucum_weather_feed import build_feed, parse_forecast_hour, parse_hour, read_live


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


class MucumWeatherTimestampTests(unittest.TestCase):
    def test_naive_robot_time_is_interpreted_as_brt(self) -> None:
        self.assertEqual(
            parse_hour("2026-08-27T09:45:00"),
            datetime(2026, 8, 27, 12, 45, tzinfo=timezone.utc),
        )

    def test_naive_open_meteo_time_is_interpreted_as_utc(self) -> None:
        self.assertEqual(
            parse_forecast_hour("2026-08-27T09:45:00"),
            datetime(2026, 8, 27, 9, 45, tzinfo=timezone.utc),
        )

    def test_live_feed_prefers_explicit_utc_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "previsao_ao_vivo_mucum.json"
            path.write_text(
                json.dumps(
                    {
                        "telemetria_ultima_em": "2026-08-27T09:45:00",
                        "telemetria_ultima_em_utc": "2026-08-27T12:45:00Z",
                        "telemetria_ultima_nivel_cm": 320,
                    }
                ),
                encoding="utf-8",
            )
            result = read_live(path, datetime(2026, 8, 27, 13, 20, tzinfo=timezone.utc))

        self.assertEqual(result["state"], "fresh")
        self.assertEqual(result["age_minutes"], 35.0)
        self.assertEqual(result["observed_at_utc"], "2026-08-27T12:45:00Z")


class MucumIndependentProxyTests(unittest.TestCase):
    def test_spatial_proxy_includes_santa_excludes_mucum_and_deduplicates(self) -> None:
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
                json.dumps({"telemetria_ultima_em_utc": "2026-08-30T11:45:00Z", "telemetria_ultima_nivel_cm": 320}),
                encoding="utf-8",
            )
            missing_previous = root / "previous-does-not-exist.json"
            feed = build_feed(
                [
                    payload(-28.5, -51.25, 2.0),   # A
                    payload(-28.5, -51.25, 9.0),   # A duplicada → mesma célula
                    payload(-29.0, -51.75, 4.0),   # B
                    payload(-29.25, -51.75, 3.0),  # Santa (montante de Muçum)
                    payload(-29.25, -51.875, 8.0), # Muçum alvo — excluído do proxy
                ],
                "https://example.test/ecmwf",
                live,
                catalog,
                now=NOW,
                direct={"status": "unavailable", "horizons": []},
                previous_path=missing_previous,
            )

        row24 = next(item for item in feed["horizons"] if item["hours"] == 24)
        self.assertEqual(row24["rain_point_mm"], 192.0)  # 8 mm/h * 24 h no ponto Muçum
        # Unique upstream cells: A(2), B(4), Santa(3) → mean 3 mm/h * 24 = 72; max 4*24 = 96
        self.assertEqual(row24["basin_mean_mm"], 72.0)
        self.assertEqual(row24["basin_max_mm"], 96.0)
        self.assertEqual(feed["basin_aggregation"]["unique_upstream_grid_cells"], 3)
        self.assertTrue(feed["basin_aggregation"]["independent_for_station"])
        self.assertTrue(feed["basin_aggregation"]["includes_santa_tereza_as_upstream"])
        self.assertTrue(feed["basin_aggregation"]["target_station_excluded"])
        self.assertFalse(feed["basin_aggregation"]["hydrologic_mask"])
        self.assertFalse(feed["basin_aggregation"]["area_weighted"])
        self.assertEqual(
            feed["basin_aggregation"]["status"],
            "mucum_independent_upstream_monitoring_grid_proxy",
        )
        self.assertTrue(feed["basin_aggregation"]["catchment_mask"]["exists"])
        self.assertAlmostEqual(feed["basin_aggregation"]["catchment_mask"]["srtm_to_ana_area_ratio"], 0.98067)
        self.assertFalse(feed["official_alert"])


if __name__ == "__main__":
    unittest.main()
