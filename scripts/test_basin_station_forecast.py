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
        self.assertEqual(
            result["models"]["gfs_seamless"]["precipitation_windows"]["3h"],
            [9.0, None],
        )
        self.assertEqual(
            result["models"]["gfs_seamless"]["precipitation_windows"]["24h"],
            [None, None],
        )

    def test_forward_window_keeps_missing_hours_unavailable(self):
        values = [1, None, 3, 4, 5]
        self.assertEqual(
            feed._forward_window_sums(values, [0, 1], 3),
            [None, 12.0],
        )

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

    def test_observed_windows_keep_coverage_and_missingness(self):
        rows = [
            (datetime(2026, 9, 20, 0, tzinfo=timezone.utc), 1.0),
            (datetime(2026, 9, 20, 1, tzinfo=timezone.utc), None),
            (datetime(2026, 9, 20, 2, tzinfo=timezone.utc), 3.0),
        ]
        windows = feed._observed_window_stats(
            rows,
            latest_observed=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
            windows=(2,),
        )
        self.assertEqual(windows["2h"]["mm"], 3.0)
        self.assertEqual(windows["2h"]["valid_points"], 1)
        self.assertEqual(windows["2h"]["expected_points"], 2)
        self.assertFalse(windows["2h"]["complete"])
        self.assertAlmostEqual(windows["2h"]["coverage_ratio"], 0.5, places=3)

    def test_observed_windows_use_exact_hour_count(self):
        latest = datetime(2026, 9, 20, 23, tzinfo=timezone.utc)
        rows = [
            (latest.replace(hour=hour), 1.0)
            for hour in range(24)
        ]
        windows = feed._observed_window_stats(
            rows,
            latest_observed=latest,
            windows=(24,),
        )
        self.assertEqual(windows["24h"]["mm"], 24.0)
        self.assertEqual(windows["24h"]["valid_points"], 24)
        self.assertEqual(windows["24h"]["expected_points"], 24)
        self.assertTrue(windows["24h"]["complete"])

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

    def test_forecast_requests_deduplicate_station_coordinates(self):
        stations = [
            {"latitude": -29.1781, "longitude": -51.7322},
            {"latitude": -29.1781, "longitude": -51.7322},
            {"latitude": -29.2, "longitude": -51.8},
        ]
        locations = feed._unique_forecast_locations(stations)
        self.assertEqual(
            locations,
            [
                {"latitude": -29.1781, "longitude": -51.7322},
                {"latitude": -29.2, "longitude": -51.8},
            ],
        )

    def test_cycle_is_next_five_minute_boundary(self):
        now = datetime(2026, 9, 20, 2, 15, tzinfo=timezone.utc)
        self.assertEqual(feed.iso_utc(feed._next_cycle(now)), "2026-09-20T02:20Z")

    def test_forecast_request_keeps_six_day_buffer_for_72h_window(self):
        url = feed.build_open_meteo_url(
            [{"latitude": -29.1781, "longitude": -51.7322}]
        )
        self.assertIn("forecast_days=6", url)
        self.assertEqual(len(feed.MODEL_SPECS), 5)
        self.assertIn(72, feed.PRECIPITATION_WINDOW_HOURS)

    def test_level_metric_keeps_observed_series_and_rna_forecasts(self):
        raw = {
            "telemetria_ultima_em": "2026-09-20T09:00:00",
            "telemetria_ultima_nivel_cm": 350,
            "nivel_previsto_cm": 348,
            "hora_alvo": "2026-09-20T11:00:00",
            "bankfull_cm": 1500,
            "status_dados": "telemetria recente",
            "serie_observada_ana": [
                {"hora": "2026-09-17T09:00:00", "nivel_cm": 300},
                {"hora": "2026-09-19T09:00:00", "nivel_cm": 340},
                {"hora": "2026-09-20T09:00:00", "nivel_cm": 350},
            ],
            "horizontes": {
                "2h": {
                    "horizonte_h": 2,
                    "hora_alvo": "2026-09-20T11:00:00",
                    "nivel_previsto_cm": 348,
                    "modelo": "RNA-2H",
                },
                "4h_vencida": {
                    "horizonte_h": 4,
                    "hora_alvo": "2026-09-20T08:00:00",
                    "nivel_previsto_cm": 420,
                    "modelo": "RNA-4H-ANTIGA",
                },
                "8h": {
                    "horizonte_h": 8,
                    "hora_alvo": "2026-09-20T17:00:00",
                    "nivel_previsto_cm": 310,
                    "modelo": "RNA-8H",
                },
            },
        }

        result = feed._level_record(raw, "86472600")

        self.assertIsNotNone(result)
        self.assertEqual(result["state"], "available")
        self.assertEqual(result["current_cm"], 350.0)
        self.assertEqual(result["series"][-1], {"time": "2026-09-20T12:00Z", "cm": 350.0})
        self.assertEqual([item["label"] for item in result["forecasts"]], ["RNA 2h", "RNA 8h"])
        self.assertEqual(result["forecasts"][1]["cm"], 310.0)
        self.assertTrue(result["forecast_applicable"])
        self.assertEqual(result["forecast_status"], "available")

    def test_level_station_without_rna_is_explicitly_not_applicable(self):
        raw = {
            "telemetria_ultima_em": "2026-09-20T09:00:00",
            "telemetria_ultima_nivel_cm": 1766,
            "status_dados": "NORMAL",
        }
        result = feed._level_record(raw, "86472000")
        self.assertIsNotNone(result)
        self.assertFalse(result["forecast_applicable"])
        self.assertEqual(result["forecast_status"], "not_applicable")
        self.assertIsNone(result["forecast_cm"])

    def test_rna_target_without_current_forecast_is_explicitly_unavailable(self):
        raw = {
            "telemetria_ultima_em": "2026-09-20T09:00:00",
            "telemetria_ultima_nivel_cm": 1375,
            "status_dados": "NORMAL",
        }
        result = feed._level_record(raw, "86472600")
        self.assertIsNotNone(result)
        self.assertTrue(result["forecast_applicable"])
        self.assertEqual(result["forecast_status"], "unavailable")

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

    def test_complete_feed_contract_rejects_missing_model_or_required_series(self):
        station = {
            "id": "ANA:1",
            "forecast": {
                "state": "available",
                "times": ["2026-09-20T00:00Z"],
                "models": {
                    spec["id"]: {
                        variable: [1.0]
                        for variable in feed.REQUIRED_FORECAST_VARIABLES
                    }
                    for spec in feed.MODEL_SPECS[:-1]
                },
            },
        }
        with self.assertRaisesRegex(RuntimeError, "Modelos ausentes"):
            feed.validate_complete_feed(
                {"scope": {"station_count": 1, "forecast_station_count": 1}, "stations": [station]}
            )

        station["forecast"]["models"] = {
            spec["id"]: {
                variable: [1.0]
                for variable in feed.REQUIRED_FORECAST_VARIABLES
            }
            for spec in feed.MODEL_SPECS
        }
        station["forecast"]["models"][feed.MODEL_SPECS[0]["id"]]["precipitation"] = []
        with self.assertRaisesRegex(RuntimeError, "Série inválida"):
            feed.validate_complete_feed(
                {"scope": {"station_count": 1, "forecast_station_count": 1}, "stations": [station]}
            )

    def test_complete_feed_contract_requires_72h_window_from_three_models(self):
        times = ["2026-09-20T03:00Z"]
        models = {}
        for spec in feed.MODEL_SPECS:
            model = {
                variable: [1.0]
                for variable in feed.REQUIRED_FORECAST_VARIABLES
            }
            model["precipitation_windows"] = {
                f"{hours}h": [1.0]
                for hours in feed.PRECIPITATION_WINDOW_HOURS
            }
            models[spec["id"]] = model
        for spec in feed.MODEL_SPECS[:3]:
            models[spec["id"]]["precipitation_windows"]["72h"] = [None]

        with self.assertRaisesRegex(RuntimeError, "Janela 72 h insuficiente"):
            feed.validate_complete_feed(
                {
                    "generated_at_utc": "2026-09-20T02:15Z",
                    "scope": {"station_count": 1, "forecast_station_count": 1},
                    "stations": [
                        {
                            "id": "ANA:86472000",
                            "forecast": {
                                "state": "available",
                                "times": times,
                                "models": models,
                            },
                        }
                    ],
                }
            )

    def test_level_snapshot_adds_age_and_trend(self):
        level = {
            "state": "available",
            "current_cm": 350.0,
            "observed_at_utc": "2026-09-20T01:00Z",
            "series": [
                {"time": "2026-09-20T00:00Z", "cm": 340.0},
                {"time": "2026-09-20T01:00Z", "cm": 350.0},
            ],
        }
        result = feed._decorate_level_snapshot(
            level, now=datetime(2026, 9, 20, 2, tzinfo=timezone.utc)
        )
        self.assertEqual(result["observed_age_minutes"], 60.0)
        self.assertEqual(result["trend_cm_per_hour"], 10.0)
        self.assertEqual(result["trend_label"], "subindo")

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
        self.assertTrue(level["forecast_applicable"])
        self.assertEqual(level["forecast_status"], "unavailable")
        self.assertEqual(result["scope"]["level_station_count"], 0)


if __name__ == "__main__":
    unittest.main()
