import json
import hashlib
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
            self.assertEqual(result["source_feed_sha256"], hashlib.sha256(feed.read_bytes()).hexdigest())

    def test_same_minute_different_snapshots_never_overwrite_even_sparse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feed = root / "feed.json"
            archive = root / "archive"
            archive.mkdir()
            legacy = archive / "20261002T1800Z.json"
            legacy.write_bytes(b'{"legacy":"preserve exactly"}\r\n')
            first_input = {"generated_at_utc": "2026-10-02T18:00:01Z", "stations": [], "observation": 0}
            feed.write_text(json.dumps(first_input), encoding="utf-8")
            first = archive_snapshot(feed, archive)
            original = first.read_bytes()
            # Same timestamp, distinct full source, including information not
            # retained in the compact rain-only skill product.
            first_input["observation"] = 1
            feed.write_text(json.dumps(first_input), encoding="utf-8")
            second = archive_snapshot(feed, archive)
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), original)
            self.assertEqual(legacy.read_bytes(), b'{"legacy":"preserve exactly"}\r\n')
            self.assertEqual(archive_snapshot(feed, archive), second)
            self.assertEqual(len(list(archive.glob('*.json'))), 3)
            # A sparse checkout sees no history: it still chooses the same
            # content-addressed name without colliding with the legacy path.
            sparse = archive_snapshot(feed, root / "sparse")
            self.assertEqual(sparse.name, second.name)
            self.assertEqual(sparse.read_bytes(), second.read_bytes())

    def test_archive_requires_timezone_and_names_in_utc(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feed = root / "feed.json"
            feed.write_text(json.dumps({"generated_at_utc": "2026-10-02T15:00:00-03:00", "stations": []}), encoding="utf-8")
            target = archive_snapshot(feed, root / "archive")
            self.assertTrue(target.name.startswith("20261002T1800Z-"))
            feed.write_text(json.dumps({"generated_at_utc": "2026-10-02T15:00:00", "stations": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                archive_snapshot(feed, root / "archive")


if __name__ == "__main__":
    unittest.main()
