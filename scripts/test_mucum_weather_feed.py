#!/usr/bin/env python3
"""Regression tests for Muçum weather-feed timestamp handling."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

try:
    from .build_mucum_weather_feed import parse_forecast_hour, parse_hour, read_live
except ImportError:
    from build_mucum_weather_feed import parse_forecast_hour, parse_hour, read_live


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


if __name__ == "__main__":
    unittest.main()
