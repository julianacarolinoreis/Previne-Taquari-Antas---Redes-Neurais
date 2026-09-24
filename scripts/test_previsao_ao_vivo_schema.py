#!/usr/bin/env python3
"""Deterministic contract tests for the Santa Tereza live feed.

These tests read the current feed and MAT hash. The one network-path regression
test uses a mocked ANA response, never reaches the network, and never writes
dynamic JSON, so the suite is safe to run in CI or locally.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from .validar_previsao_ao_vivo import B_MAT, validate_data
except ImportError:  # execução direta: python scripts/test_...py
    from validar_previsao_ao_vivo import B_MAT, validate_data


ROOT = Path(__file__).resolve().parents[1]


class LiveFeedContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads((ROOT / "previsao_ao_vivo.json").read_text(encoding="utf-8"))

    def test_current_feed_schema_and_forward_metadata(self) -> None:
        validate_data(self.data, b_mat=B_MAT)

    def test_hand_zero_is_separate_from_official_flood_level(self) -> None:
        self.assertEqual(self.data["bankfull_cm"], 1500)
        self.assertEqual(self.data["hand_zero_cm"], 160)
        for horizon in ("2h", "4h", "8h"):
            self.assertEqual(self.data["horizontes"][horizon]["hand_zero_cm"], 160)

    def test_page_uses_field_zero_for_spatialization(self) -> None:
        page = (ROOT / "santa_tereza_previsao_inundacao.html").read_text(encoding="utf-8")
        self.assertIn("HAND_ZERO_DEFAULT_CM=160", page)
        self.assertIn("const COTA_INUND=1500", page)
        self.assertIn("function stageToSpatialHand(cm,zeroCm=HAND_ZERO_DEFAULT_CM)", page)
        self.assertIn("(Number(cm)-Number(zeroCm))/100", page)
        self.assertIn("contornos_mancha.json", page)
        self.assertNotIn("Number(cm)-COTA_INUND", page)

    def test_generated_hand_diagnostic_is_main_river_only(self) -> None:
        diagnostic = json.loads(
            (ROOT / "assets" / "data" / "santa_tereza_inundacao" / "hand_lidar_5m_diagnostic.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(diagnostic["hand_zero_cm"], 160)
        self.assertEqual(diagnostic["flowacc_threshold_fine_cells"], 50_000_000)
        self.assertEqual(diagnostic["componentes_mantidos"], 1)
        self.assertGreater(diagnostic["celulas_rio_principal"], 0)
        self.assertGreaterEqual(diagnostic["contornos_features"], 151)
        if "contour_max_m" in diagnostic:
            self.assertEqual(diagnostic["contour_max_m"], 25.0)

    def test_explicit_4h_fallback_without_prediction_is_valid(self) -> None:
        data = copy.deepcopy(self.data)
        four = data["horizontes"]["4h"]
        four["nivel_previsto_cm"] = None
        four["disponivel"] = False
        four["status"] = "inputs incompletos — sem previsão nesta hora"
        four["auditoria_inputs"] = {"status": "ATENCAO"}
        validate_data(data, b_mat=B_MAT)

    def test_legacy_cascata_is_rejected_from_public_feed(self) -> None:
        data = copy.deepcopy(self.data)
        data["horizontes"]["4h"]["modelo"] = "4h_cascata_legado"
        with self.assertRaises(SystemExit):
            validate_data(data, b_mat=B_MAT)

    def test_unexpected_horizon_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["horizontes"]["4h_cascata"] = copy.deepcopy(data["horizontes"]["4h"])
        with self.assertRaises(SystemExit):
            validate_data(data, b_mat=B_MAT)

    def test_non_exact_4h_timestamp_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["horizontes"]["4h"]["hora_modelo"] = "2026-08-16T08:30:00"
        with self.assertRaises(SystemExit):
            validate_data(data, b_mat=B_MAT)

    def test_missing_prediction_cannot_be_marked_available(self) -> None:
        data = copy.deepcopy(self.data)
        two = data["horizontes"]["2h"]
        two["nivel_previsto_cm"] = None
        two["disponivel"] = True
        two["auditoria_inputs"] = {"status": "ATENCAO"}
        with self.assertRaises(SystemExit):
            validate_data(data, b_mat=B_MAT)

    def test_implausible_prediction_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["horizontes"]["2h"]["nivel_previsto_cm"] = 99999
        with self.assertRaises(SystemExit):
            validate_data(data, b_mat=B_MAT)

    def test_robot_failure_does_not_fake_a_fresh_success_timestamp(self) -> None:
        source = (ROOT / "previne" / "robo" / "gerar_previsao_ao_vivo.py").read_text(encoding="utf-8")
        start = source.index("def preservar_saida_valida_em_falha")
        end = source.index("def algum_horizonte_com_previsao", start)
        block = source[start:end]
        self.assertNotIn('atual["consultado_em"] = agora', block)
        self.assertIn('atual["ultima_tentativa_em"] = agora', block)
        self.assertIn('audit = auditoria_inputs_8h(cfg, cand, x)', source)

    def test_operational_fallbacks_are_explicit_and_drop_86298000_dependency(self) -> None:
        from previne.robo import gerar_previsao_ao_vivo as live

        four = live.FALLBACKS_HORIZONTE["4h"]
        eight = live.FALLBACKS_HORIZONTE["8h"]
        self.assertEqual(four["inputs_total"], 14)
        self.assertEqual(eight["inputs_total"], 10)
        self.assertEqual(four["input_grade"], "hourly_exact")
        self.assertEqual(eight["input_grade"], "hourly_exact")
        self.assertNotIn("86298000", " ".join(four.get("input_labels") or []))
        self.assertNotIn("86298000", " ".join(eight.get("input_labels") or []))

    def test_expired_primary_requests_fallback(self) -> None:
        from previne.robo import gerar_previsao_ao_vivo as live

        expired = {
            "nivel_previsto_cm": 500,
            "hora_modelo": "2026-09-21T19:00:00",
            "hora_alvo": "2026-09-21T23:00:00",
        }
        self.assertTrue(live._precisa_fallback(expired))

    def test_ana_reuses_one_xml_for_level_and_rain(self) -> None:
        from previne.robo import gerar_previsao_ao_vivo as live

        xml = b"""
        <root><row>
          <DataHora>2026-09-21T07:00:00</DataHora>
          <Nivel>350</Nivel>
          <Chuva>1.2</Chuva>
        </row></root>
        """
        calls = []

        class Response:
            def read(self):
                return xml

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, timeout))
            return Response()

        live.ANA_XML_CACHE.clear()
        live.CHUVA_ANA_CACHE.clear()
        live.ULTIMA_RAW.clear()
        try:
            with patch.object(live.urllib.request, "urlopen", side_effect=fake_urlopen):
                level = live.buscar_ana("86472000", dias=5, tentativas_rede=1)
                rain = live.buscar_ana_chuva("86472000", dias=5, tentativas_rede=1)
        finally:
            live.ANA_XML_CACHE.clear()
            live.CHUVA_ANA_CACHE.clear()
            live.ULTIMA_RAW.clear()

        self.assertEqual(len(calls), 1)
        self.assertEqual(list(level.values()), [350.0])
        self.assertEqual(list(rain.values()), [1.2])


if __name__ == "__main__":
    unittest.main()
