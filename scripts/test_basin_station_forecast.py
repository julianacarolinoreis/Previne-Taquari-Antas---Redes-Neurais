import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts import build_basin_station_forecast as feed


class BasinStationForecastTests(unittest.TestCase):
    def test_invalid_coordinate_values_are_skipped_without_crashing(self):
        self.assertIsNone(
            feed.valid_coordinates(
                {"lat": "NaN", "lon": "not-a-number"},
                {"type": "Point", "coordinates": [None, None]},
            )
        )
        self.assertEqual(
            feed.valid_coordinates(
                {},
                {"type": "Point", "coordinates": [-51.7, -29.1]},
            ),
            (-29.1, -51.7),
        )

    def test_extract_forecast_keeps_multiple_models_and_metrics(self):
        times = [
            "2026-09-20T00:00",
            "2026-09-20T01:00",
            "2026-09-20T02:00",
            "2026-09-20T03:00",
        ]
        payload = {"hourly": {"time": times}}
        for spec in feed.MODEL_SPECS:
            for variable in feed.FORECAST_VARIABLES:
                payload["hourly"][f"{variable}_{spec['id']}"] = [1, 2, 3, 4]

        result = feed.extract_forecast_payload(payload, step_hours=3)

        self.assertEqual(result["state"], "available")
        self.assertEqual(len(result["times"]), 2)
        self.assertEqual(set(result["models"]), {spec["id"] for spec in feed.MODEL_SPECS})
        self.assertEqual(result["models"]["gfs_seamless"]["precipitation"], [1.0, 4.0])

    def test_extract_forecast_marks_empty_response_unavailable(self):
        result = feed.extract_forecast_payload({"hourly": {"time": []}})
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(result["models"], {})

    def test_observed_missing_values_are_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rain.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["COD_SEQUENCIAL", "chuva_86472600"],
                )
                writer.writeheader()
                writer.writerow({"COD_SEQUENCIAL": "202609191900", "chuva_86472600": ""})
                writer.writerow({"COD_SEQUENCIAL": "202609192000", "chuva_86472600": "4.5"})

            result = feed.load_observed_rain(
                path,
                now=datetime(2026, 9, 19, 23, 0, tzinfo=timezone.utc),
                hours=72,
            )

        rows = result["86472600"]["rows"]
        self.assertEqual(result["86472600"]["state"], "available")
        self.assertTrue(any(row["mm"] is None for row in rows))
        self.assertIn(4.5, [row["mm"] for row in rows])

    def test_catalog_merges_flow_and_rain_records_by_network_and_code(self):
        with tempfile.TemporaryDirectory() as directory:
            flow_path = Path(directory) / "flow.json"
            rain_path = Path(directory) / "rain.json"
            feature = {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-51.7, -29.1]},
                "properties": {
                    "codigo": "86472600",
                    "nome": "SANTA TEREZA",
                    "tipo": "fluviometrica",
                    "upg": "Médio Taquari-Antas",
                },
            }
            rain_feature = {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-51.7, -29.1]},
                "properties": {
                    "codigo": "86472600",
                    "nome": "SANTA TEREZA",
                    "rede": "ANA",
                    "tipo": "fluviometrica_com_sensor_chuva",
                    "upg": "Médio Taquari-Antas",
                },
            }
            flow_path.write_text(json.dumps({"features": [feature]}), encoding="utf-8")
            rain_path.write_text(json.dumps({"features": [rain_feature]}), encoding="utf-8")

            stations = feed.load_station_catalog(flow_path, rain_path)

        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0]["id"], "ANA:86472600")
        self.assertEqual(
            set(stations[0]["types"]),
            {"fluviometrica", "fluviometrica_com_sensor_chuva"},
        )
        self.assertEqual(
            set(stations[0]["catalog_sources"]),
            {"flow.json", "rain.json"},
        )

    def test_default_catalog_sources_are_public_relative_paths(self):
        stations = feed.load_station_catalog()
        sources = {
            source
            for station in stations
            for source in station["catalog_sources"]
        }
        self.assertTrue(sources)
        self.assertTrue(all(source.startswith("assets/data/") for source in sources))
        self.assertTrue(all(":" not in source for source in sources))

    def test_cycle_is_next_six_hour_boundary(self):
        now = datetime(2026, 9, 20, 2, 15, tzinfo=timezone.utc)
        self.assertEqual(feed.iso_utc(feed._next_cycle(now)), "2026-09-20T06:17Z")

    def test_partial_forecast_run_cannot_replace_complete_snapshot(self):
        partial = {
            "scope": {
                "station_count": 420,
                "forecast_station_count": 419,
            }
        }

        with self.assertRaisesRegex(RuntimeError, "419/420"):
            feed.validate_complete_feed(partial)

        feed.validate_complete_feed(
            {
                "scope": {
                    "station_count": 420,
                    "forecast_station_count": 420,
                }
            }
        )

    def test_missing_level_is_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flow_path = root / "flow.json"
            rain_path = root / "rain.json"
            observed_path = root / "rain.csv"
            feature = {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-51.7, -29.1]},
                "properties": {
                    "codigo": "86472600",
                    "nome": "SANTA TEREZA",
                    "tipo": "fluviometrica",
                    "upg": "Médio Taquari-Antas",
                },
            }
            flow_path.write_text(json.dumps({"features": [feature]}), encoding="utf-8")
            rain_path.write_text(json.dumps({"features": []}), encoding="utf-8")
            observed_path.write_text(
                "COD_SEQUENCIAL,chuva_86472600\n202609192000,\n",
                encoding="utf-8",
            )

            result = feed.build_feed(
                now=datetime(2026, 9, 20, 2, 15, tzinfo=timezone.utc),
                flow_catalog=flow_path,
                rain_catalog=rain_path,
                observed_csv=observed_path,
                live_feeds=(),
                fetcher=lambda _url: [{"hourly": {"time": []}}],
            )

        level = result["stations"][0]["level"]
        self.assertEqual(level["state"], "unavailable")
        self.assertIsNone(level["current_cm"])
        self.assertEqual(result["scope"]["level_station_count"], 0)


if __name__ == "__main__":
    unittest.main()
