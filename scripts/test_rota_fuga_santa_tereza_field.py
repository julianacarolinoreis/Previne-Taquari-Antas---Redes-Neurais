"""Regressões da rota de exercício de Santa Tereza, sem gerar produtos.

Execute no repositório:
    python -B scripts/test_rota_fuga_santa_tereza_field.py -v

Usa unittest, numpy e Pillow (as dependências do gerador). Forecasts e PNGs
são sintéticos, com relógio fixo; o contrato raster real é chamado. Testes
do main interceptam os destinos de escrita e conferem os bytes dos produtos
existentes antes/depois. Não certifica segurança de rota nem aprovação final.
"""
from __future__ import annotations

import base64
import copy
import datetime as dt
import hashlib
import importlib.util
import io
import json
import re
import shlex
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "codigo_python/09_rota_fuga/gerar_rota_fuga_santa_tereza.py"
WORKFLOW = ROOT / ".github/workflows/rota-fuga-santa-tereza.yml"
SPEC = importlib.util.spec_from_file_location("stz_route_under_test", GENERATOR)
route = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(route)
import santa_tereza_hand_field_contract as contract

NOW = "2026-09-28T09:13:18"
LIVE_FILES = ("santa_tereza_rota_fuga.html", "assets/data/rota_fuga_santa_tereza.json")
HISTORICAL_FILES = (
    "santa_tereza_rota_fuga_cenario.html",
    "assets/data/rota_fuga_santa_tereza_cenario.json",
)
SYNTHETIC_FILES = (
    "santa_tereza_rota_fuga_cenario_sintetico.html",
    "assets/data/rota_fuga_santa_tereza_cenario_sintetico.json",
)


def forecast_fixture() -> dict:
    horizons = {}
    # 8h: base própria 06:00; não integra a curva 2h/4h de base 08:00.
    for key, base, target, predicted in (
        ("2h", "08:00", "10:00", 406),
        ("4h", "08:00", "12:00", 409),
        ("8h", "06:00", "14:00", 344),
    ):
        horizons[key] = {
            "hora_modelo": f"2026-09-28T{base}:00",
            "hora_alvo": f"2026-09-28T{target}:00",
            "nivel_previsto_cm": predicted,
            "disponivel": True,
            "status": "ok",
            "ativo_ao_vivo": True,
            "shadow_only": False,
            "input_grade": "hourly_exact",
            "input_contract_version": "hourly_exact_v1",
            "inputs_faltantes_n": 0,
            "auditoria_inputs": {
                "status": "NORMAL",
                "formula_conferida_com_montador": True,
                "n_inputs_nao_exatos": 0,
            },
        }
    return {
        "telemetria_ultima_em": "2026-09-28T08:45:00",
        "telemetria_ultima_nivel_cm": 407,
        "horizontes": horizons,
    }


def raster_fixture(values, image_format="PNG") -> dict:
    image = Image.fromarray(np.array(values, dtype=np.uint8))
    encoded = io.BytesIO()
    image.save(encoded, format=image_format)
    png = encoded.getvalue()
    return {
        "source_id": "santa_tereza_lidar_campo_rio_principal_zero160_v1",
        "cidade": "santa_tereza",
        "rio": "somente rio principal",
        "superficie_inundacao": "CLIP_MOSAICO_LIDAR_RS.tif (LiDAR bruto)",
        "superficie_roteamento": "FILL_CLIP_MOSAICO_LIDAR_RS.tif",
        "hand_zero_cm": 160,
        "max_hand_m": 25.0,
        "nodata": 255,
        "saturated_value": 250,
        "crs": "EPSG:4326",
        "georeferencing": "reprojected_nearest_from_source_utm",
        "cols": image.width,
        "rows": image.height,
        "S": -29.1751, "N": -29.1749, "W": -51.7306, "E": -51.7304,
        "hand_png_b64": base64.b64encode(png).decode("ascii"),
        "hand_png_sha256": hashlib.sha256(png).hexdigest(),
        "station": {"lat": -29.1781, "lon": -51.7322, "code": "86472600"},
    }


def trajectory(forecast=None, now=NOW, cenario="ao_vivo"):
    return route.trajetoria_nivel(
        forecast_fixture() if forecast is None else forecast, now=now, cenario=cenario,
    )


def grid(values, temporal=None):
    hand, geo = route.decodifica_hand(raster_fixture(values))
    return route.monta_quadras(hand, geo, trajectory() if temporal is None else temporal)


def rendered_html(temporal=None):
    temporal = trajectory() if temporal is None else temporal
    cells, dy, dx = grid([[30]], temporal)
    meta = {
        "temporal": temporal,
        "estacao": raster_fixture([[30]])["station"],
        "ponte": None,
        "nivel_txt": "4.07 m",
        "cenario_rotulo": temporal["rotulo"],
        "gerado_em": NOW,
    }
    counts = {name: sum(cell["classe"] == name for cell in cells) for name in route.CORES}
    return route.render_html(cells, dy, dx, meta, counts)


def product_hashes():
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if (ROOT / name).exists() else None
        for name in (*LIVE_FILES, *HISTORICAL_FILES, *SYNTHETIC_FILES)
    }


class TemporalTests(unittest.TestCase):
    def test_absolute_targets_and_separate_8h(self):
        result = trajectory()
        self.assertEqual([point[0] for point in result["pontos"]], [0, 75, 195])
        self.assertEqual(result["horizontes_separados"], ["8h"])
        self.assertEqual(result["grupos"][1]["pontos"][-1][0], 315)
        self.assertFalse(result["grupos"][1]["usado_na_classificacao"])
        # Só a extensão antiga até 6h cruzaria 4,10 m neste exemplo.
        self.assertIsNone(route.tempo_ate(4.10, result["pontos"]))

    def test_same_base_8h_uses_real_target(self):
        forecast = forecast_fixture()
        forecast["horizontes"]["8h"].update(
            hora_modelo="2026-09-28T08:00:00", hora_alvo="2026-09-28T16:00:00",
        )
        result = trajectory(forecast)
        self.assertEqual([point[0] for point in result["pontos"]], [0, 75, 195, 435])
        self.assertEqual(result["horizontes_separados"], [])

    def test_distinct_2h_4h_bases_are_not_merged(self):
        forecast = forecast_fixture()
        forecast["horizontes"]["4h"].update(
            hora_modelo="2026-09-28T07:00:00", hora_alvo="2026-09-28T11:00:00",
        )
        result = trajectory(forecast)
        self.assertEqual(result["horizontes_principais"], ["2h"])
        self.assertEqual(result["horizontes_separados"], ["4h", "8h"])

    def test_telemetry_time_priority_and_utc(self):
        forecast = forecast_fixture()
        forecast["telemetria_ultima_hora"] = "2026-09-28T11:45:00Z"
        now = dt.datetime(2026, 9, 28, 12, 13, 18, tzinfo=dt.timezone.utc)
        result = trajectory(forecast, now)
        self.assertEqual(result["campo_origem"], "telemetria_ultima_hora")
        self.assertEqual(result["origem_em"], "2026-09-28T08:45:00-03:00")
        self.assertEqual([point[0] for point in result["pontos"]], [0, 75, 195])

    def test_missing_telemetry_never_becomes_zero(self):
        forecast = forecast_fixture()
        forecast["telemetria_ultima_nivel_cm"] = None
        result = trajectory(forecast)
        self.assertEqual(result["pontos"], [])
        self.assertIsNone(result["nivel_atual_cm"])
        self.assertEqual(len(result["horizontes_rejeitados"]), 3)
        self.assertTrue(result["motivos_indisponibilidade"])

    def test_zero_telemetry_is_valid(self):
        forecast = forecast_fixture()
        forecast["telemetria_ultima_nivel_cm"] = 0
        self.assertEqual(trajectory(forecast)["pontos"][0], (0, 0))

    def test_stale_future_and_invalid_telemetry_time(self):
        self.assertEqual(trajectory(now="2026-10-02T09:00:00")["pontos"], [])
        self.assertEqual(trajectory(now="2026-09-28T08:00:00")["pontos"], [])
        forecast = forecast_fixture()
        forecast["telemetria_ultima_em"] = "invalid"
        self.assertEqual(trajectory(forecast)["pontos"], [])

    def test_freshness_boundary_is_explicit(self):
        accepted = trajectory(now="2026-09-28T10:45:00")
        self.assertEqual(accepted["idade_telemetria_min"], 120)
        self.assertNotEqual(accepted["status"], "telemetria_indisponivel")
        rejected = trajectory(now="2026-09-28T10:45:01")
        self.assertIn("telemetria_vencida", rejected["motivos_indisponibilidade"])
        self.assertEqual(rejected["criterios_validade"]["max_idade_telemetria_min"], 120)

    def test_expired_targets_are_rejected_independently(self):
        result = trajectory(now="2026-09-28T10:00:00")
        self.assertNotIn("2h", result["horizontes_aceitos"])
        self.assertIn("4h", result["horizontes_aceitos"])
        self.assertIn("8h", result["horizontes_separados"])

    def test_unavailable_shadow_and_invalid_contract_rejected(self):
        for field, value in (
            ("disponivel", False), ("shadow_only", True), ("ativo_ao_vivo", False),
            ("status", "INVALIDO"), ("input_contract_version", "wrong"),
            ("input_grade", "nearest"), ("inputs_faltantes_n", 1),
        ):
            with self.subTest(field=field):
                forecast = forecast_fixture()
                forecast["horizontes"]["2h"][field] = value
                result = trajectory(forecast)
                self.assertNotIn("2h", result["horizontes_aceitos"])
                self.assertTrue(result["horizontes_rejeitados"][0]["motivos"])

    def test_invalid_input_audit_rejected(self):
        for field, value in (
            ("status", "ATENCAO"), ("formula_conferida_com_montador", False),
            ("n_inputs_nao_exatos", 1), ("n_interpolados", 1),
            ("n_vizinhos_mais_proximos", 1), ("n_inputs_ausentes", 1),
            ("n_inputs_atrasados", 1), ("n_inputs_fora_faixa", 1),
        ):
            with self.subTest(field=field):
                forecast = forecast_fixture()
                forecast["horizontes"]["2h"]["auditoria_inputs"][field] = value
                self.assertNotIn("2h", trajectory(forecast)["horizontes_aceitos"])

    def test_nonfinite_missing_or_implausible_levels_rejected(self):
        for value in (None, True, "406", float("nan"), float("inf"), -501, 5001):
            with self.subTest(value=value):
                forecast = forecast_fixture()
                forecast["horizontes"]["2h"]["nivel_previsto_cm"] = value
                self.assertNotIn("2h", trajectory(forecast)["horizontes_aceitos"])
                forecast["telemetria_ultima_nivel_cm"] = value
                self.assertEqual(trajectory(forecast)["pontos"], [])

    def test_inconsistent_or_nonhourly_target_rejected(self):
        for base, target in (
            ("08:00", "11:00"), ("08:30", "10:30"), ("09:00", "11:00"),
        ):
            with self.subTest(base=base, target=target):
                forecast = forecast_fixture()
                forecast["horizontes"]["2h"].update(
                    hora_modelo=f"2026-09-28T{base}:00", hora_alvo=f"2026-09-28T{target}:00",
                )
                self.assertNotIn("2h", trajectory(forecast)["horizontes_aceitos"])

    def test_feed_quality_warning_preserved(self):
        forecast = forecast_fixture()
        forecast["horizontes"]["4h"]["status"] = "ok - atencao: erro recente acima do guardrail"
        result = trajectory(forecast)
        self.assertIn("4h", result["horizontes_aceitos"])
        self.assertTrue(result["alvos"]["4h"]["ressalvas"])
        self.assertIn("ressalva de qualidade/base", rendered_html(result))

    def test_no_forecast_keeps_reference_only(self):
        forecast = forecast_fixture()
        forecast["horizontes"] = {}
        result = trajectory(forecast)
        self.assertEqual(result["status"], "sem_previsao_admissivel")
        self.assertEqual(result["pontos"], [(0, 4.07)])
        self.assertIsNone(route.tempo_ate(4.10, result["pontos"]))

    def test_crossing_only_between_existing_points(self):
        self.assertAlmostEqual(route.tempo_ate(2.0, [(0, 1.0), (75, 3.0)]), 37.5)
        self.assertIsNone(route.tempo_ate(4.0, [(0, 1.0), (75, 3.0)]))
        self.assertIsNone(route.tempo_ate(2.0, []))
        self.assertEqual(route.tempo_ate(1.0, [(0, 1.0)]), 0)

    def test_forecast_argument_is_not_mutated(self):
        forecast = forecast_fixture()
        before = copy.deepcopy(forecast)
        trajectory(forecast)
        self.assertEqual(forecast, before)


class RasterAndGridTests(unittest.TestCase):
    def test_authoritative_raster_page_is_forecast_page(self):
        self.assertEqual(Path(route.PAGINA_HAND), ROOT / "santa_tereza_previsao_inundacao.html")

    def test_nodata_saturation_and_valid_zero(self):
        hand, geo = route.decodifica_hand(raster_fixture([[0, 255, 250, 10]]))
        self.assertEqual(hand[0, 0], 0)
        self.assertTrue(np.isnan(hand[0, 1]))
        self.assertTrue(np.isnan(hand[0, 2]))
        self.assertEqual(hand[0, 3], 1)
        self.assertEqual(geo["raster_contract"]["scope"], "somente rio principal")

    def test_hash_source_calibration_and_encoding_guards(self):
        for field, value in (
            ("hand_png_sha256", "0" * 64), ("source_id", "wrong"),
            ("hand_zero_cm", 400), ("nodata", 0), ("saturated_value", 255),
            ("superficie_inundacao", "FILL_CLIP_MOSAICO_LIDAR_RS.tif"),
            ("rio", "todos os afluentes"), ("georeferencing", "bilinear"),
        ):
            with self.subTest(field=field):
                payload = raster_fixture([[0, 10]])
                payload[field] = value
                with self.assertRaises((ValueError, RuntimeError)):
                    route.decodifica_hand(payload)

    def test_missing_hash_and_reserved_codes_rejected(self):
        payload = raster_fixture([[0, 10]])
        del payload["hand_png_sha256"]
        with self.assertRaises(RuntimeError):
            route.decodifica_hand(payload)
        for value in range(251, 255):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                route.decodifica_hand(raster_fixture([[value]]))

    def test_non_png_and_wrong_dimensions_rejected(self):
        with self.assertRaises(RuntimeError):
            route.decodifica_hand(raster_fixture([[0, 10]], image_format="JPEG"))
        payload = raster_fixture([[0, 10]])
        payload["rows"] = 2
        with self.assertRaises(RuntimeError):
            route.decodifica_hand(payload)

    def test_validation_precedes_decode(self):
        with mock.patch.object(contract, "validate_raster_payload", side_effect=RuntimeError("gate")) as gate:
            with mock.patch.object(route.base64, "b64decode") as decoder:
                with self.assertRaisesRegex(RuntimeError, "gate"):
                    route.decodifica_hand({"hand_png_b64": "invalid"})
                gate.assert_called_once()
                decoder.assert_not_called()

    def test_no_crossing_cells_are_kept_with_null_time(self):
        cells, _, _ = grid([[30]])
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0]["status"], "sem_cruzamento_no_intervalo")
        self.assertIsNone(cells[0]["min_ate_limiar"])
        self.assertIsNone(cells[0]["margem_min"])
        json.dumps(cells, allow_nan=False)

    def test_missing_forecast_nodata_and_saturation_are_visible(self):
        forecast = forecast_fixture()
        forecast["telemetria_ultima_nivel_cm"] = None
        for values, status in (
            ([[30]], "previsao_indisponivel"),
            ([[255]], "sem_dado_terreno"),
            ([[250]], "terreno_saturado"),
        ):
            with self.subTest(status=status):
                cells, _, _ = grid(values, trajectory(forecast))
                self.assertEqual(len(cells), 1)
                self.assertEqual(cells[0]["status"], status)
                self.assertIsNone(cells[0]["min_ate_limiar"])
                self.assertIsNone(cells[0]["margem_min"])
                if status != "previsao_indisponivel":
                    self.assertIsNone(cells[0]["hand_m"])
                json.dumps(cells, allow_nan=False)

    def test_partial_nodata_preserves_zero_with_partial_coverage(self):
        cells, _, _ = grid([[0, 255]])
        self.assertEqual(cells[0]["hand_m"], 0)
        self.assertTrue(cells[0]["terreno_parcial"])
        self.assertEqual(cells[0]["fracao_raster_valida"], 0.5)
        self.assertEqual(cells[0]["classe"], "limiar_na_origem")

    def test_classification_boundaries_are_numerical_not_instructions(self):
        for margin, crossing, expected in (
            (-5, 0, "limiar_na_origem"), (-1, 10, "margem_negativa"),
            (0, 10, "margem_ate_15"), (14.9, 20, "margem_ate_15"),
            (15, 20, "margem_15_60"), (59.9, 70, "margem_15_60"),
            (60, 70, "margem_acima_60"), (None, None, "sem_cruzamento"),
        ):
            with self.subTest(margin=margin, crossing=crossing):
                self.assertEqual(route.classe(margin, crossing), expected)


class PresentationTests(unittest.TestCase):
    def test_html_shows_field_reference_and_research_scope(self):
        html = rendered_html()
        for text in (
            "Estimativa de cruzamento de limiar", "comparação separada",
            "não é alerta oficial", "régua 1,60 m = HAND 0", "somente rio principal",
            "régua prevista 3.44 m", "sem cruzamento no intervalo disponível",
        ):
            self.assertIn(text, html)
        for prohibited in ("sair agora", "já alagada", "Água chega em", "min_ate_agua"):
            self.assertNotIn(prohibited, html)
        self.assertNotRegex(html, r"__(DADOS|BANNER|NIVEL|CENARIO|GERADO|TEMPORAL|RESUMO)__")

    def test_embedded_payload_is_json_and_null_time_stays_null(self):
        html = rendered_html()
        match = re.search(r"const D=(.*), RES=", html)
        payload = json.loads(match.group(1))
        self.assertIsNone(payload["quadras"][0]["min_ate_limiar"])
        self.assertIsNone(payload["quadras"][0]["margem_min"])
        self.assertIn("Number.isFinite(q.min_ate_limiar)", html)
        self.assertIn("Number.isFinite(q.margem_min)", html)

    def test_stale_telemetry_reason_is_visible(self):
        result = trajectory(now="2026-10-02T09:00:00")
        html = rendered_html(result)
        self.assertIn("telemetria vencida", html)
        self.assertIn("estimativa temporal indisponível", html)
        self.assertIn("2026-09-28T08:45:00-03:00", html)


class HistoricalProtectionTests(unittest.TestCase):
    def test_synthetic_and_22jul_use_separate_paths(self):
        expected = tuple(str(ROOT / name) for name in SYNTHETIC_FILES)
        for scenario in ("sintetico", "22jul"):
            self.assertEqual(route.caminhos_saida(scenario), expected)
        self.assertEqual(route.caminhos_saida("ao_vivo"), tuple(str(ROOT / name) for name in LIVE_FILES))
        self.assertTrue(set(expected).isdisjoint(str(ROOT / name) for name in HISTORICAL_FILES))

    def test_unknown_scenario_rejected_before_path_selection(self):
        with self.assertRaises(ValueError):
            route.caminhos_saida("historico")
        with self.assertRaises(ValueError):
            trajectory(cenario="historico")

    def test_synthetic_is_explicit_and_alias_equivalent(self):
        result = trajectory(cenario="sintetico")
        self.assertEqual(result, trajectory(cenario="22jul"))
        self.assertEqual(result["cenario"], "sintetico")
        self.assertEqual(result["status"], "cenario_sintetico")
        self.assertEqual(result["pontos"][-1][0], 360)
        self.assertAlmostEqual(result["pontos"][-1][1], 6.47)
        self.assertEqual(result["horizontes_aceitos"], [])
        self.assertIn("não é replay", result["caveat"])
        self.assertEqual(result["parametros_cenario"]["natureza"], "sintetico_nao_replay")

    def test_synthetic_missing_telemetry_does_not_invent_base(self):
        forecast = forecast_fixture()
        forecast["telemetria_ultima_nivel_cm"] = None
        result = trajectory(forecast, cenario="sintetico")
        self.assertEqual(result["pontos"], [])
        self.assertEqual(result["cenario"], "sintetico")
        self.assertIn("cenário sintético", result["rotulo"])
        self.assertIn("não é replay", result["caveat"])

    def test_main_paths_and_metadata_with_all_writes_intercepted(self):
        before = product_hashes()
        real_trajectory = route.trajetoria_nivel
        hand, geo = route.decodifica_hand(raster_fixture([[0, 30]]))
        for scenario in ("ao_vivo", "sintetico", "22jul"):
            with self.subTest(scenario=scenario):
                # Deixa o pipeline real montar quadras/meta. Apenas entrada de
                # arquivo/relógio e saída de arquivo são controlados.
                with mock.patch.object(route.sys, "argv", [str(GENERATOR), "--cenario", scenario]), \
                     mock.patch.object(route, "carrega_hand", return_value=(hand, geo)), \
                     mock.patch.object(route, "open", mock.mock_open(read_data=json.dumps(forecast_fixture())), create=True), \
                     mock.patch.object(route, "trajetoria_nivel", side_effect=lambda f, **kw: real_trajectory(f, now=NOW, **kw)), \
                     mock.patch.object(route, "escreve_json", return_value={}) as json_write, \
                     mock.patch.object(route, "escreve_html") as html_write, \
                     redirect_stdout(io.StringIO()):
                    route.main()
                normalized = "sintetico" if scenario == "22jul" else scenario
                html_path, json_path = route.caminhos_saida(normalized)
                self.assertEqual(json_write.call_count, 1)
                self.assertEqual(html_write.call_count, 1)
                self.assertEqual(json_write.call_args.args[2], json_path)
                self.assertEqual(html_write.call_args.args[-1], html_path)
                cells, meta, _ = json_write.call_args.args
                self.assertEqual(meta["cenario"], normalized)
                self.assertEqual(meta["argumento_cenario"], scenario)
                self.assertEqual(meta["schema_version"], "stz_route_research_v2")
                self.assertEqual(meta["raster_contract"]["source_id"], contract.FIELD_SOURCE_ID)
                self.assertEqual(meta["zero_regua_m"], 1.6)
                json.dumps({"cells": cells, "meta": meta}, allow_nan=False)
        self.assertEqual(product_hashes(), before, "os testes alteraram produtos do repositório")

    def test_main_invalid_raster_stops_before_any_output(self):
        with mock.patch.object(route.sys, "argv", [str(GENERATOR)]), \
             mock.patch.object(route, "carrega_hand", side_effect=RuntimeError("raster inválido")), \
             mock.patch.object(route, "escreve_json") as json_write, \
             mock.patch.object(route, "escreve_html") as html_write:
            with self.assertRaisesRegex(RuntimeError, "raster inválido"):
                route.main()
        json_write.assert_not_called()
        html_write.assert_not_called()

    def test_workflow_stages_only_live_and_optional_synthetic(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        # Confere a lista realmente usada pelo git add, sem executar Git.
        live = re.search(r"^\s+arquivos=\(([^\n]+)\)$", text, re.M)
        synthetic = re.search(r"^\s+arquivos\+=\(([^\n]+)\)$", text, re.M)
        self.assertEqual(shlex.split(live.group(1)), list(LIVE_FILES))
        self.assertEqual(shlex.split(synthetic.group(1)), list(SYNTHETIC_FILES))
        self.assertIn('git add -- "${arquivos[@]}"', text)
        self.assertIn("shell: bash", text)
        self.assertIn("--cenario sintetico", text)
        self.assertNotIn("--cenario 22jul", text)
        for name in HISTORICAL_FILES:
            self.assertNotIn(name, text)
        self.assertRegex(text, r"gerar_cenario:\s+description:[^\n]+\s+type: boolean\s+default: false")
        self.assertRegex(text, r'if \[ "\$\{\{ github.event.inputs.gerar_cenario \}\}" = "true" \]; then\s+python[^\n]+--cenario sintetico\s+arquivos\+=\([^\n]+\)\s+fi')


if __name__ == "__main__":
    unittest.main()
