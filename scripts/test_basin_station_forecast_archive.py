import json
import tempfile
import unittest
from pathlib import Path

from scripts.archive_basin_station_forecast import archive_snapshot


class BasinStationForecastArchiveTests(unittest.TestCase):
    def test_archive_is_compact_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feed = root / "feed.json"
            archive = root / "archive"
            feed.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-09-20T20:58Z",
                        "stations": [
                            {
                                "id": "ANA:1",
                                "code": "1",
                                "name": "Teste",
                                "latitude": -29.1,
                                "longitude": -51.7,
                                "observed_rain": {"state": "available", "source": "test", "available_points": 3},
                                "forecast": {
                                    "state": "available",
                                    "times": ["2026-09-21T00:00Z"],
                                    "models": {
                                        "gfs": {
                                            "precipitation": [1.0],
                                            "precipitation_windows": {"3h": [2.0]},
                                            "temperature_2m": [20.0],
                                        }
                                    },
                                },
                            },
                            {
                                "id": "ANA:2",
                                "forecast": {"state": "unavailable"},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            first = archive_snapshot(feed, archive)
            first_bytes = first.read_bytes()
            second = archive_snapshot(feed, archive)

            self.assertEqual(first, second)
            self.assertEqual(first_bytes, first.read_bytes())
            result = json.loads(first.read_text(encoding="utf-8"))
            self.assertEqual(len(result["stations"]), 1)
            self.assertEqual(
                result["stations"][0]["models"]["gfs"]["precipitation"], [1.0]
            )
            self.assertNotIn("temperature_2m", result["stations"][0]["models"]["gfs"])


if __name__ == "__main__":
    unittest.main()
