#!/usr/bin/env python3
"""Proveniencia de chuva: rede simulada e arquivos somente em TemporaryDirectory.

O oraculo de confirmacao e independente do builder: exige hash dos bytes e
captura >= fim fisico da hora BRT. Rodar com:
python -B -m unittest scripts.test_rain_observation_provenance -v
"""
import contextlib
import csv
import datetime as dt
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "rain_provenance_downloader", ROOT / "codigo_python/10_chuvas/baixar_chuvas_horarias.py"
)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)
UTC = dt.timezone.utc
CEMA = "chuva_cemaden_4320404010A"
ANA = "chuva_86472600"
INMET = "chuva_inmet_A894"
LABEL = dt.datetime(2026, 9, 30, 13)  # inicio BRT; fim = 17:00 UTC
CODE = "202609301300"


def iso(instant):
    return instant.astimezone(UTC).isoformat().replace("+00:00", "Z")


class Response(io.BytesIO):
    headers = {}


def confirmed(csv_path, column, code):
    """Oraculo independente; o simples avanco do relogio nao participa."""
    try:
        metadata = json.loads(Path(str(csv_path) + ".provenance.json").read_text(encoding="utf-8"))
        if metadata["schema_version"] != 1:
            return False
        if metadata["csv_sha256"] != hashlib.sha256(csv_path.read_bytes()).hexdigest():
            return False
        captured = dt.datetime.fromisoformat(metadata["cells"][column][code].replace("Z", "+00:00"))
        start = dt.datetime.strptime(code, "%Y%m%d%H%M").replace(tzinfo=collector.BRT)
        return captured >= start + dt.timedelta(hours=1)
    except (OSError, ValueError, TypeError, KeyError):
        return False


class RainProvenanceTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "rain.csv"
        self.meta = Path(str(self.path) + ".provenance.json")
        self.now = dt.datetime(2026, 9, 30, 16, 30, tzinfo=UTC)
        self.addCleanup(patch.stopall)
        patch.object(collector, "SAIDA", str(self.path)).start()
        patch.object(collector, "_agora_utc", side_effect=lambda: self.now).start()
        patch.object(collector.time, "sleep").start()
        patch.dict(collector.os.environ, {"CEMADEN_TOKEN": ""}).start()

    def seed(self, values=None, cells=None):
        values = values if values is not None else {CEMA: 0.0}
        with self.path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["COD_SEQUENCIAL", *collector.COLUNAS])
            writer.writerow([CODE, *(values.get(column, "") for column in collector.COLUNAS)])
        if cells is not None:
            self.write_metadata(cells)

    def write_metadata(self, cells, **extra):
        metadata = {
            "schema_version": 1,
            "csv_sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
            "cells": cells,
            **extra,
        }
        self.meta.write_text(json.dumps(metadata), encoding="utf-8")

    def payload_cema(self, value=0.0, hour=16, date="30/09/2026"):
        return {
            "estacao": {"codEstacao": "432040401A"},
            "horarios": [f"{hour}h"], "datas": [date], "acumulados": [[value]],
        }

    def run_main(self, *, cema=None, ana=b"<root/>", inmet=None, failure=False):
        def network(request, **kwargs):
            if failure:
                raise OSError("fonte indisponivel")
            url = request.full_url
            if "ServiceANA" in url:
                body = ana
            elif "apitempo" in url:
                body = json.dumps(inmet or []).encode()
            else:
                body = json.dumps(cema if cema is not None else self.payload_cema()).encode()
            return Response(body)
        with patch.object(collector.urllib.request, "urlopen", side_effect=network) as mock_network:
            with patch.object(collector.sys, "argv", ["collect", "--inicio", "2026-09-30", "--fim", "2026-09-30"]):
                with contextlib.redirect_stdout(io.StringIO()):
                    collector.main()
        return mock_network

    def row(self, code=CODE):
        with self.path.open(encoding="utf-8", newline="") as handle:
            return next(row for row in csv.DictReader(handle) if row["COD_SEQUENCIAL"] == code)

    def test_same_csv_clock_advance_keeps_open_hour_locked(self):
        self.seed()
        self.run_main()
        before_csv, before_meta = self.path.read_bytes(), self.meta.read_bytes()
        before_mtime = self.path.stat().st_mtime_ns, self.meta.stat().st_mtime_ns
        self.assertFalse(confirmed(self.path, CEMA, CODE))
        self.now = dt.datetime(2026, 9, 30, 20, tzinfo=UTC)
        self.run_main(failure=True)
        self.assertEqual(self.path.read_bytes(), before_csv)
        self.assertEqual(self.meta.read_bytes(), before_meta)
        self.assertEqual((self.path.stat().st_mtime_ns, self.meta.stat().st_mtime_ns), before_mtime)
        self.assertEqual(collector.carregar_proveniencia()[CEMA][CODE], "2026-09-30T16:30:00Z")
        self.assertFalse(confirmed(self.path, CEMA, CODE))

    def test_new_zero_after_interval_end_reconfirms_identical_csv(self):
        self.seed()
        self.run_main()
        before_csv = self.path.read_bytes()
        self.now = dt.datetime(2026, 9, 30, 17, 0, 0, 1, tzinfo=UTC)
        self.run_main()
        self.assertEqual(self.path.read_bytes(), before_csv)
        self.assertEqual(collector.carregar_proveniencia()[CEMA][CODE], iso(self.now))
        self.assertTrue(confirmed(self.path, CEMA, CODE))

    def test_capture_at_exact_end_confirms_but_microsecond_before_does_not(self):
        self.seed()
        end = dt.datetime(2026, 9, 30, 17, tzinfo=UTC)
        self.now = end - dt.timedelta(microseconds=1)
        self.run_main()
        self.assertFalse(confirmed(self.path, CEMA, CODE))
        self.now = end
        self.run_main()
        self.assertTrue(confirmed(self.path, CEMA, CODE))

    def test_capture_before_network_not_after_response_crosses_end(self):
        self.now = dt.datetime(2026, 9, 30, 16, 59, 59, tzinfo=UTC)
        start = self.now
        captures = {}
        def network(request, **kwargs):
            self.now = dt.datetime(2026, 9, 30, 17, 1, tzinfo=UTC)
            return Response(json.dumps(self.payload_cema()).encode())
        with patch.object(collector.urllib.request, "urlopen", side_effect=network):
            values = collector.cemaden_chuva_horaria("432040401A", LABEL, LABEL, capturas=captures)
        self.assertEqual(values, {LABEL: 0.0})
        self.assertEqual(captures, {LABEL: iso(start)})

    def test_each_retry_records_its_own_start_before_network(self):
        captures = {}
        first = self.now
        second = first + dt.timedelta(hours=1)
        def network(request, **kwargs):
            if self.now == first:
                self.assertEqual(captures["captured_at_utc"], iso(first))
                self.now = second
                raise OSError("primeira tentativa")
            self.assertEqual(captures["captured_at_utc"], iso(second))
            self.now += dt.timedelta(minutes=3)
            return Response(b"valid")
        with patch.object(collector.urllib.request, "urlopen", side_effect=network) as call:
            self.assertEqual(collector.http_get("https://example.invalid", tentativas=2, captura=captures), b"valid")
        self.assertEqual(call.call_count, 2)
        self.assertEqual(captures["captured_at_utc"], iso(second))

    def test_failure_preserves_both_files_byte_for_byte(self):
        self.seed(cells={CEMA: {CODE: iso(self.now)}})
        before = self.path.read_bytes(), self.meta.read_bytes()
        before_mtime = self.path.stat().st_mtime_ns, self.meta.stat().st_mtime_ns
        self.run_main(failure=True)
        self.assertEqual((self.path.read_bytes(), self.meta.read_bytes()), before)
        self.assertEqual((self.path.stat().st_mtime_ns, self.meta.stat().st_mtime_ns), before_mtime)

    def test_empty_or_invalid_response_does_not_create_provenance_or_zero(self):
        for value in (None, "", -1, "nan", "inf", "-inf"):
            with self.subTest(value=value):
                self.seed(values={CEMA: 2.5})
                self.meta.unlink(missing_ok=True)
                before = self.path.read_bytes()
                self.run_main(cema=self.payload_cema(value))
                self.assertEqual(self.path.read_bytes(), before)
                self.assertFalse(self.meta.exists())
                self.assertEqual(self.row()[CEMA], "2.5")

    def test_failed_column_keeps_capture_when_other_source_updates(self):
        self.seed(values={CEMA: 0, ANA: 4.2}, cells={ANA: {CODE: "2026-09-30T16:20:00Z"}})
        self.now = dt.datetime(2026, 9, 30, 17, 1, tzinfo=UTC)
        self.run_main()  # ANA sem novos dados; CEMADEN respondeu zero valido
        self.assertEqual(self.row()[ANA], "4.2")
        self.assertEqual(collector.carregar_proveniencia()[ANA][CODE], "2026-09-30T16:20:00Z")
        self.assertFalse(confirmed(self.path, ANA, CODE))
        self.assertTrue(confirmed(self.path, CEMA, CODE))

    def test_legacy_csv_is_usable_without_confirmation(self):
        self.seed(values={ANA: 3.4})
        series, _, _ = collector.carregar_existente(collector.COLUNAS)
        self.assertEqual(series[ANA][LABEL], 3.4)
        self.assertEqual(collector.carregar_proveniencia(), {})
        self.assertFalse(confirmed(self.path, ANA, CODE))

    def test_mismatched_hash_cannot_carry_old_confirmation_into_new_csv(self):
        self.seed(values={ANA: 3.4, CEMA: 0}, cells={ANA: {CODE: "2026-09-30T18:00:00Z"}})
        self.write_metadata({ANA: {CODE: "2026-09-30T18:00:00Z"}}, csv_sha256="0" * 64)
        self.assertEqual(collector.carregar_proveniencia(), {})
        self.assertFalse(confirmed(self.path, ANA, CODE))
        self.run_main()
        self.assertEqual(self.row()[ANA], "3.4")
        self.assertNotIn(ANA, collector.carregar_proveniencia())
        self.assertFalse(confirmed(self.path, ANA, CODE))

    def test_invalid_json_or_schema_is_unknown(self):
        self.seed()
        for body in ("{broken", "null", "[]", '{"schema_version": 2}', '{"schema_version": true}'):
            with self.subTest(body=body):
                self.meta.write_text(body, encoding="utf-8")
                self.assertEqual(collector.carregar_proveniencia(), {})
        self.write_metadata({CEMA: []})
        self.assertEqual(collector.carregar_proveniencia(), {})

    def test_invalid_capture_or_nonhour_code_cannot_confirm(self):
        self.seed()
        for capture in ("2026-09-30T18:00:00", "2026-09-30T18:00:00-03:00", None, "invalid"):
            with self.subTest(capture=capture):
                self.write_metadata({CEMA: {CODE: capture}})
                self.assertEqual(collector.carregar_proveniencia(), {})
        self.write_metadata({CEMA: {"202609301330": iso(self.now)}})
        self.assertEqual(collector.carregar_proveniencia(), {})

    def test_prune_eight_day_boundary_and_keep_recent_old_capture_lock(self):
        cutoff = LABEL - dt.timedelta(days=8)
        old = cutoff - dt.timedelta(hours=1)
        series = {CEMA: {LABEL: 0, cutoff: 2, old: 3}}
        cells = {CEMA: {
            CODE: "2026-09-30T16:20:00Z",
            collector.cod_seq(cutoff): "2026-09-22T16:10:00Z",
            collector.cod_seq(old): "2026-09-22T15:10:00Z",
            "202609301400": iso(self.now),
            "202609301200": iso(self.now),  # sem valor correspondente no CSV
        }}
        result = collector.podar_proveniencia(cells, series, self.now)
        self.assertEqual(result, {CEMA: {
            CODE: "2026-09-30T16:20:00Z",
            collector.cod_seq(cutoff): "2026-09-22T16:10:00Z",
        }})

    def test_merge_invalid_values_preserves_previous_values_and_captures(self):
        captures = {CODE: "2026-09-30T16:10:00Z"}
        for value in (None, -1, float("nan"), float("inf"), "bad"):
            with self.subTest(value=value):
                dest = {LABEL: 1.2}
                count = collector.mesclar_observacoes(dest, {LABEL: value}, captures, {LABEL: iso(self.now)})
                self.assertEqual(count, 0)
                self.assertEqual(dest, {LABEL: 1.2})
                self.assertEqual(captures[CODE], "2026-09-30T16:10:00Z")
        self.assertEqual(collector.mesclar_observacoes({}, {LABEL: 0}, {}, {LABEL: iso(self.now)}), 1)

    def test_csv_read_rejects_nonfinite_observations(self):
        self.seed(values={ANA: "inf", INMET: "nan", CEMA: "0"})
        series, _, _ = collector.carregar_existente(collector.COLUNAS)
        self.assertEqual(series[ANA], {})
        self.assertEqual(series[INMET], {})
        self.assertEqual(series[CEMA], {LABEL: 0.0})

    def test_source_ana_sums_valid_subhours_and_records_query_start(self):
        xml = b"""<root><r><DataHora>2026-09-30 13:05:00</DataHora><Chuva>1.2</Chuva></r>
          <r><DataHora>2026-09-30 13:25:00</DataHora><Chuva>0.3</Chuva></r>
          <r><DataHora>2026-09-30 13:35:00</DataHora><Chuva>-5</Chuva></r>
          <r><DataHora>2026-09-30 12:00:00</DataHora><Chuva>nan</Chuva></r>
          <r><DataHora>2026-09-30 11:00:00</DataHora><Chuva>inf</Chuva></r></root>"""
        captures = {}
        with patch.object(collector.urllib.request, "urlopen", return_value=Response(xml)):
            values = collector.ana_chuva_horaria("86472600", LABEL, LABEL, capturas=captures)
        self.assertEqual(values, {LABEL: 1.5})
        self.assertEqual(captures, {LABEL: iso(self.now)})

    def test_source_inmet_startlabel_brt_day_rollover_and_invalid_missing(self):
        payload = [
            {"DT_MEDICAO": "2026-10-01", "HR_MEDICAO": "0000", "CHUVA": "1.2"},
            {"DT_MEDICAO": "2026-10-01", "HR_MEDICAO": "0100", "CHUVA": None},
            {"DT_MEDICAO": "2026-10-01", "HR_MEDICAO": "0200", "CHUVA": "inf"},
            {"DT_MEDICAO": "2026-10-01", "HR_MEDICAO": "0300", "CHUVA": -1},
        ]
        captures = {}
        with patch.object(collector.urllib.request, "urlopen", return_value=Response(json.dumps(payload).encode())):
            values = collector.inmet_chuva_horaria("A894", LABEL, LABEL, capturas=captures)
        expected_label = dt.datetime(2026, 9, 30, 20)
        self.assertEqual(values, {expected_label: 1.2})
        self.assertEqual(captures, {expected_label: iso(self.now)})

    def test_source_cema_ped_public_override_uses_public_capture(self):
        patch.dict(collector.os.environ, {"CEMADEN_TOKEN": "fixture"}).start()
        ped_start, public_start = self.now, self.now + dt.timedelta(minutes=2)
        def network(request, **kwargs):
            if "dados_pcd" in request.full_url:
                self.now = public_start
                payload = [{"datahora": "2026-09-30 16:20:00", "valor": 1.2},
                           {"datahora": "2026-09-30 16:40:00", "valor": "inf"}]
            else:
                self.now += dt.timedelta(minutes=2)
                payload = self.payload_cema(1.8)
            return Response(json.dumps(payload).encode())
        captures = {}
        with patch.object(collector.urllib.request, "urlopen", side_effect=network):
            values = collector.cemaden_chuva_horaria("432040401A", LABEL, LABEL, capturas=captures)
        self.assertEqual(values, {LABEL: 1.8})
        self.assertNotEqual(iso(ped_start), iso(public_start))
        self.assertEqual(captures, {LABEL: iso(public_start)})

    def test_monthly_queries_have_separate_capture_timestamps(self):
        first, second = self.now, self.now + dt.timedelta(minutes=2)
        def network(request, **kwargs):
            if "30/09/2026" in request.full_url:
                stamp = "2026-09-30 13:00:00"
                self.now = second
            else:
                stamp = "2026-10-01 00:00:00"
            return Response(f"<root><r><DataHora>{stamp}</DataHora><Chuva>0</Chuva></r></root>".encode())
        captures = {}
        with patch.object(collector.urllib.request, "urlopen", side_effect=network):
            values = collector.ana_chuva_horaria("86472600", LABEL, dt.datetime(2026, 10, 1, 23), capturas=captures)
        self.assertEqual(values, {LABEL: 0.0, dt.datetime(2026, 10, 1): 0.0})
        self.assertEqual(captures, {LABEL: iso(first), dt.datetime(2026, 10, 1): iso(second)})

    def test_metadata_hash_matches_final_csv_bytes_and_missing_stays_blank(self):
        self.seed(values={ANA: 1.234})
        self.run_main()
        metadata = json.loads(self.meta.read_text(encoding="utf-8"))
        self.assertEqual(set(metadata), {"schema_version", "csv_sha256", "cells"})
        self.assertEqual(metadata["schema_version"], 1)
        self.assertEqual(metadata["csv_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(self.row()[INMET], "")
        self.assertEqual(self.row()[ANA], "1.23")
        self.assertEqual(metadata["cells"], {CEMA: {CODE: iso(self.now)}})

    def test_sidecar_contains_only_valid_cells_actually_written_to_csv(self):
        series = {column: {} for column in collector.COLUNAS}
        series[CEMA] = {LABEL: 0, LABEL - dt.timedelta(hours=1): 4}
        cells = {CEMA: {CODE: iso(self.now), "202609301200": iso(self.now)},
                 INMET: {CODE: iso(self.now)}}
        collector.gravar_csv_e_proveniencia(series, LABEL, LABEL, cells)
        self.assertEqual(collector.carregar_proveniencia(), {CEMA: {CODE: iso(self.now)}})
        self.assertEqual(self.row()[INMET], "")

    def test_failed_ana_query_keeps_value_and_lock_when_cema_updates(self):
        self.seed(values={ANA: 4.2, CEMA: 0}, cells={ANA: {CODE: "2026-09-30T16:20:00Z"}})
        self.now = dt.datetime(2026, 9, 30, 17, 1, tzinfo=UTC)
        real_get = collector.http_get
        def fail_ana(url, **kwargs):
            if "ServiceANA" in url:
                raise OSError("ANA indisponivel")
            return real_get(url, **kwargs)
        with patch.object(collector, "http_get", side_effect=fail_ana):
            self.run_main()
        self.assertEqual(self.row()[ANA], "4.2")
        self.assertEqual(collector.carregar_proveniencia()[ANA][CODE], "2026-09-30T16:20:00Z")
        self.assertFalse(confirmed(self.path, ANA, CODE))
        self.assertTrue(confirmed(self.path, CEMA, CODE))

    def test_recent_qa_failure_preserves_both_files(self):
        self.seed(values={ANA: 2}, cells={ANA: {CODE: iso(self.now)}})
        before = self.path.read_bytes(), self.meta.read_bytes()
        xml = b"<root><r><DataHora>2026-09-30 13:00:00</DataHora><Chuva>0</Chuva></r></root>"
        with self.assertRaises(SystemExit):
            self.run_main(ana=xml, cema=self.payload_cema(None))
        self.assertEqual((self.path.read_bytes(), self.meta.read_bytes()), before)

    def test_staging_failure_leaves_both_previous_files_unchanged(self):
        self.seed(cells={CEMA: {CODE: iso(self.now)}})
        before = self.path.read_bytes(), self.meta.read_bytes()
        with patch.object(collector.json, "dump", side_effect=OSError("disco")):
            with self.assertRaises(OSError):
                self.run_main()
        self.assertEqual((self.path.read_bytes(), self.meta.read_bytes()), before)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_both_files_staged_before_csv_replace_and_interruption_fails_closed(self):
        self.seed(values={CEMA: 2.5}, cells={CEMA: {CODE: "2026-09-30T18:00:00Z"}})
        old_meta = self.meta.read_bytes()
        real_replace = collector.os.replace
        def replace(source, target):
            if str(target) == str(self.path):
                staged = list(self.path.parent.glob("rain-*.json.tmp"))
                self.assertEqual(len(staged), 1)
                data = json.loads(staged[0].read_text(encoding="utf-8"))
                self.assertEqual(data["csv_sha256"], hashlib.sha256(Path(source).read_bytes()).hexdigest())
                return real_replace(source, target)
            raise OSError("interrupcao entre replaces")
        with patch.object(collector.os, "replace", side_effect=replace):
            with self.assertRaises(OSError):
                self.run_main()
        self.assertEqual(self.meta.read_bytes(), old_meta)
        self.assertEqual(collector.carregar_proveniencia(), {})
        self.assertFalse(confirmed(self.path, CEMA, CODE))
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
