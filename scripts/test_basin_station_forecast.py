import csv
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import build_basin_station_forecast as feed


class BasinStationForecastTests(unittest.TestCase):
    def write_provenance(self, path, captured_at):
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        cells = {}
        for row in rows:
            for column, value in row.items():
                if column.startswith('chuva_') and value not in (None, ''):
                    cells.setdefault(column, {})[row['COD_SEQUENCIAL']] = captured_at.isoformat()
        Path(str(path) + '.provenance.json').write_text(json.dumps({
            'schema_version': 1, 'csv_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'cells': cells,
        }), encoding='utf-8')

    def observed_samples(self, samples, now):
        """Exercise the public CSV loader using local interval-start labels."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rain.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["COD_SEQUENCIAL", "chuva_86472600"])
                writer.writeheader()
                for local_time, value in samples:
                    writer.writerow({"COD_SEQUENCIAL": local_time, "chuva_86472600": value})
            self.write_provenance(path, now)
            return feed.load_observed_rain(path, now=now)["86472600"]

    def test_retained_partial_cell_does_not_close_without_a_new_source_consultation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rain.csv'
            path.write_text('COD_SEQUENCIAL,chuva_86472600\n202609301200,2.5\n202609301300,0\n', encoding='utf-8')
            self.write_provenance(path, datetime(2026, 9, 30, 16, 30, tzinfo=timezone.utc))
            original = path.read_bytes()
            for now in (datetime(2026, 9, 30, 16, 59, tzinfo=timezone.utc), datetime(2026, 9, 30, 17, 10, tzinfo=timezone.utc)):
                result = feed.load_observed_rain(path, now=now)['86472600']
                self.assertTrue(result['rows'][-1]['partial'])
                self.assertEqual(result['windows']['1h']['mm'], 2.5)
                self.assertEqual(result['last_closed_interval_end_utc'], '2026-09-30T16:00Z')
                self.assertEqual(result['rows'][-1]['confirmation'], 'captured_during_interval')
            self.assertEqual(path.read_bytes(), original)
            self.write_provenance(path, datetime(2026, 9, 30, 17, 5, tzinfo=timezone.utc))
            result = feed.load_observed_rain(path, now=datetime(2026, 9, 30, 17, 10, tzinfo=timezone.utc))['86472600']
            self.assertFalse(result['rows'][-1]['partial'])
            self.assertEqual(result['windows']['1h']['mm'], 0)
            self.assertTrue(result['windows']['1h']['complete'])

    def test_legacy_or_mismatched_provenance_cannot_claim_confirmed_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rain.csv'
            path.write_text('COD_SEQUENCIAL,chuva_86472600\n202609301200,2.5\n', encoding='utf-8')
            now = datetime(2026, 9, 30, 17, 10, tzinfo=timezone.utc)
            result = feed.load_observed_rain(path, now=now)['86472600']
            self.assertEqual(result['windows']['1h']['mm'], 2.5)
            self.assertFalse(result['windows']['1h']['complete'])
            self.assertEqual(result['windows']['1h']['unconfirmed_points'], 1)
            self.write_provenance(path, now)
            path.write_text(path.read_text() + '202609301300,1\n', encoding='utf-8')
            result = feed.load_observed_rain(path, now=now)['86472600']
            self.assertFalse(result['windows']['1h']['complete'])
            self.assertEqual(result['rows'][-1]['confirmation'], 'unknown')

    def test_current_hour_zero_is_partial_and_excluded_until_exact_close(self):
        samples = [("202609301200", 2.5), ("202609301300", 0)]
        before = self.observed_samples(samples, datetime(2026, 9, 30, 16, 59, 59, tzinfo=timezone.utc))
        closed = self.observed_samples(samples, datetime(2026, 9, 30, 17, 0, tzinfo=timezone.utc))
        self.assertEqual(before["timestamp_role"], "interval_start")
        self.assertEqual(before["last_observed_at_utc"], "2026-09-30T16:00Z")
        self.assertEqual(before["last_closed_interval_end_utc"], "2026-09-30T16:00Z")
        self.assertEqual(before["windows"]["1h"]["mm"], 2.5)
        self.assertEqual(before["windows"]["1h"]["start_utc"], "2026-09-30T15:00Z")
        self.assertTrue(before["rows"][-1]["partial"])
        self.assertEqual(before["rows"][-1]["interval_end_utc"], "2026-09-30T17:00Z")
        self.assertEqual(closed["windows"]["1h"]["mm"], 0)
        self.assertTrue(closed["windows"]["1h"]["complete"])
        self.assertEqual(closed["last_closed_interval_end_utc"], "2026-09-30T17:00Z")
        self.assertEqual(closed["closed_interval_age_minutes"], 0)
        self.assertFalse(closed["rows"][-1]["partial"])

    def test_only_open_hour_does_not_create_a_complete_observed_window(self):
        result = self.observed_samples([("202610010000", 0)], datetime(2026, 10, 1, 3, 30, tzinfo=timezone.utc))
        self.assertEqual(result["state"], "available")
        self.assertIsNone(result["last_closed_interval_end_utc"])
        self.assertIsNone(result["closed_interval_age_minutes"])
        for window in result["windows"].values():
            self.assertIsNone(window["mm"])
            self.assertIsNone(window["start_utc"])
            self.assertIsNone(window["end_utc"])
            self.assertFalse(window["complete"])

    def test_closed_rain_interval_preserves_brt_day_rollover_and_internal_gap(self):
        result = self.observed_samples(
            [("202609302200", 1), ("202609302300", ""), ("202610010000", 3), ("202610010100", 90)],
            datetime(2026, 10, 1, 4, 30, tzinfo=timezone.utc),
        )
        window = result["windows"]["3h"]
        self.assertEqual(window["mm"], 4)
        self.assertEqual(window["start_utc"], "2026-10-01T01:00Z")
        self.assertEqual(window["end_utc"], "2026-10-01T04:00Z")
        self.assertEqual(window["valid_points"], 2)
        self.assertFalse(window["complete"])
        self.assertEqual(result["closed_interval_age_minutes"], 30)
        self.assertEqual(result["last_observed_at_utc"], "2026-10-01T04:00Z")
        self.assertEqual(result["rows"][-1]["mm"], 90)
        self.assertTrue(result["rows"][-1]["partial"])

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
        self.assertEqual(result["86472600"]["observed_age_minutes"], 0)
        self.assertEqual(
            result["86472600"]["source"],
            "ANA · telemetria horária · assets/data/chuvas_horarias.csv",
        )
        self.assertTrue(any(row["mm"] is None for row in rows))
        self.assertIn(4.5, [row["mm"] for row in rows])

    def test_observed_rain_source_names_network_and_marks_legacy_column(self):
        self.assertIn("ANA · telemetria horária", feed.observed_rain_source("86472600"))
        self.assertIn("INMET · estação A894", feed.observed_rain_source("A894"))
        self.assertIn("CEMADEN · estação 432040401A", feed.observed_rain_source("432040401A"))
        self.assertIn("coluna legada", feed.observed_rain_source("02851044"))
        self.assertIn("rede não identificada", feed.observed_rain_source("unknown"))

    def test_legacy_72h_window_discloses_age_and_unconfirmed_coverage_with_newer_gaps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rain.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["COD_SEQUENCIAL", "chuva_86472600"],
                )
                writer.writeheader()
                local_start = datetime(2026, 9, 20, 0)
                for hour in range(78):
                    local_time = local_start + timedelta(hours=hour)
                    writer.writerow({
                        "COD_SEQUENCIAL": local_time.strftime("%Y%m%d%H%M"),
                        "chuva_86472600": 1.0 if hour <= 72 else "",
                    })

            result = feed.load_observed_rain(
                path,
                now=datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc),
                hours=72,
            )["86472600"]

        window = result["windows"]["72h"]
        self.assertFalse(window["complete"])
        self.assertEqual(window["unconfirmed_points"], 72)
        self.assertEqual(window["valid_points"], 72)
        self.assertEqual(window["start_utc"], "2026-09-20T04:00Z")
        self.assertEqual(window["end_utc"], "2026-09-23T04:00Z")
        self.assertEqual(result["observed_age_minutes"], 300)
        self.assertEqual(result["closed_interval_age_minutes"], 240)
        self.assertEqual([{key: row[key] for key in ("time", "mm")} for row in result["rows"][-5:]], [
            {"time": "2026-09-23T04:00Z", "mm": None},
            {"time": "2026-09-23T05:00Z", "mm": None},
            {"time": "2026-09-23T06:00Z", "mm": None},
            {"time": "2026-09-23T07:00Z", "mm": None},
            {"time": "2026-09-23T08:00Z", "mm": None},
        ])

    def test_cemaden_24h_observation_is_not_an_hourly_series(self):
        station = {"source_observations": [{
            "source": "CEMADEN",
            "metric": "chuva_acumulada_24h_mm",
            "source_status": 0,
            "value": 0,
        }]}
        self.assertTrue(feed.has_cemaden_rain_24h(station))
        station["source_observations"][0]["value"] = None
        self.assertFalse(feed.has_cemaden_rain_24h(station))
        station["source_observations"][0]["value"] = -1
        self.assertFalse(feed.has_cemaden_rain_24h(station))
        station["source_observations"][0]["value"] = 2.5
        station["source_observations"][0]["source_status"] = 1
        self.assertFalse(feed.has_cemaden_rain_24h(station))

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
        self.assertEqual(windows["2h"]["start_utc"], "2026-09-20T01:00Z")
        self.assertEqual(windows["2h"]["end_utc"], "2026-09-20T03:00Z")

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
        self.assertEqual(windows["24h"]["start_utc"], "2026-09-20T00:00Z")
        self.assertEqual(windows["24h"]["end_utc"], "2026-09-21T00:00Z")

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
                "8h_indisponivel": {
                    "horizonte_h": 8,
                    "hora_alvo": "2026-09-20T19:00:00",
                    "nivel_previsto_cm": 999,
                    "status": "indisponivel: base atrasada; aguardando inputs completos",
                    "modelo": "RNA-8H-STALE",
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

    def test_implausible_vertical_value_is_not_river_stage(self):
        result = feed.normalize_level_measurement(
            {
                "state": "available",
                "current_cm": 24907,
                "observed_at_utc": "2026-10-01T13:00Z",
                "quality": "NORMAL",
            }
        )
        self.assertEqual(result["state"], "suspect_scale")
        self.assertIsNone(result["current_cm"])
        self.assertEqual(result["raw_current_cm"], 24907.0)
        self.assertEqual(result["measurement_classification"], "cota_or_incompatible_scale")
        self.assertEqual(result["quality"], "SUSPECT_SCALE")

        negative = feed.normalize_level_measurement(
            {"state": "available", "current_cm": -332}
        )
        self.assertIsNone(negative["current_cm"])
        self.assertEqual(negative["raw_current_cm"], -332.0)

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

    def test_compact_status_preserves_observed_interval_and_confirmation(self):
        now = datetime(2026, 9, 30, 17, 10, tzinfo=timezone.utc)
        observed = self.observed_samples([('202609301300', 0)], now)
        compact = feed._compact_station_status({'observed_rain': observed}, generated_at=now)['observed_rain']
        self.assertEqual(compact['timestamp_role'], 'interval_start')
        self.assertEqual(compact['last_closed_interval_end_utc'], '2026-09-30T17:00Z')
        self.assertEqual(compact['closed_interval_age_minutes'], 10)
        self.assertEqual(compact['windows']['1h']['start_utc'], '2026-09-30T16:00Z')
        self.assertEqual(compact['windows']['1h']['end_utc'], '2026-09-30T17:00Z')
        self.assertEqual(compact['windows']['1h']['unconfirmed_points'], 0)


    def test_status_snapshot_keeps_compact_station_contract(self):
        generated = datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc)
        models = {}
        for spec in feed.MODEL_SPECS:
            models[spec["id"]] = {
                "precipitation_windows": {
                    f"{hours}h": [float(hours), float(hours) + 1.0]
                    for hours in feed.PRECIPITATION_WINDOW_HOURS
                }
            }
        station = {
            "id": "ANA:86125500",
            "code": "86125500",
            "name": "PCH JARARACA BARRAMENTO",
            "network": "ANA",
            "latitude": -28.9381,
            "longitude": -51.4656,
            "source_networks": ["ANA/HidroWeb", "SGB/SACE"],
            "source_roles": ["inventário ANA/HidroWeb", "hidrotelemetria SGB/SACE"],
            "source_observations": [],
            "observed_rain": {
                "state": "unavailable",
                "source": "ANA/INMET/CEMADEN · chuvas_horarias.csv",
                "unit": "mm",
                "windows": {},
            },
            "level": feed.normalize_level_measurement({
                "state": "available",
                "current_cm": 24907,
                "observed_at_utc": "2026-10-01T12:55Z",
                "forecast_applicable": False,
                "forecast_status": "not_applicable",
                "forecasts": [],
            }),
            "forecast": {
                "state": "available",
                "times": ["2026-10-01T12:00Z", "2026-10-01T15:00Z"],
                "fetched_at_utc": "2026-10-01T13:00Z",
                "models": models,
            },
        }
        status = feed._status_snapshot({
            "generated_at_utc": "2026-10-01T13:00Z",
            "scope": {"station_count": 1, "forecast_station_count": 1},
            "stations": [station],
        })
        self.assertEqual(status["schema_version"], 2)
        self.assertEqual(len(status["stations"]), 1)
        compact = status["stations"][0]
        self.assertIsNone(compact["level"]["current_cm"])
        self.assertEqual(compact["level"]["raw_current_cm"], 24907.0)
        self.assertEqual(
            compact["level"]["measurement_classification"],
            "cota_or_incompatible_scale",
        )
        self.assertTrue(compact["forecast"]["models"]["ecmwf_ifs025"]["available"])
        self.assertEqual(
            compact["forecast"]["models"]["ecmwf_ifs025"]["precipitation_state"],
            "complete",
        )
        self.assertEqual(
            compact["forecast"]["models"]["ecmwf_ifs025"]["precipitation_valid_window_count"],
            len(feed.PRECIPITATION_WINDOW_HOURS),
        )
        self.assertEqual(
            compact["forecast"]["models"]["ecmwf_ifs025"]["precipitation_windows_mm"]["24h"],
            25.0,
        )
        station['forecast']['times'] = ['2026-09-30T12:00Z', '2026-09-30T15:00Z']
        expired = feed._compact_station_status(station, generated_at=generated)['forecast']['models']['ecmwf_ifs025']
        self.assertEqual(expired['precipitation_state'], 'unavailable')
        self.assertTrue(all(value is None for value in expired['precipitation_windows_mm'].values()))

    def test_dashboard_contract_includes_g040_health_and_no_current_filter(self):
        html = (feed.ROOT / "dashboard_bacia.html").read_text(encoding="utf-8")
        js = (feed.ROOT / "assets/js/bacia_dashboard.js").read_text(encoding="utf-8")
        self.assertIn('id="basin-network-summary"', html)
        self.assertIn('data-network-filter="no-current"', html)
        self.assertIn('data-network-filter="no-time"', html)
        self.assertIn('id="basin-upg-filter"', html)
        self.assertIn('id="basin-upg-health"', html)
        self.assertIn('id="basin-gap-diagnostics"', html)
        self.assertIn('id="basin-station-search"', html)
        self.assertIn('id="basin-clear-filters"', html)
        self.assertIn("basin_station_status_latest.json", js)
        self.assertIn("state.networkFilter === 'no-current'", js)
        self.assertIn("state.networkFilter === 'no-time'", js)
        self.assertIn("state.networkUpg", js)
        self.assertIn("function renderUpgHealth()", js)
        self.assertIn("function renderGapDiagnostics()", js)
        self.assertIn("function networkVariableCoverage()", js)
        self.assertIn("variable === 'flow'", js)
        self.assertIn("MAIORES ATRASOS COM HORÁRIO", js)
        self.assertIn("Previsão meteorológica multi-modelo", js)
        self.assertIn("valor vertical bruto bloqueado como nível", js)
        self.assertIn("function findNetworkStation(query)", js)
        self.assertIn("function clearNetworkFilters()", js)
        self.assertIn("function networkForecastCoverageSummary(status)", js)
        self.assertIn("precipitation_state", js)
        self.assertIn("RASTREABILIDADE DA ESTAÇÃO", js)
        self.assertIn("measurement_classification", js)


if __name__ == "__main__":
    unittest.main()
