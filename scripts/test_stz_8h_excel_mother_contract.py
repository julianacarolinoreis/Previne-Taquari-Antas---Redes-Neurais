#!/usr/bin/env python3
"""Regressoes do contrato de chuva dos modelos Santa Tereza 8h."""
from __future__ import annotations

import datetime as dt
import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

from previne.robo import fontes_chuva_8h as fontes
from previne.robo import gerar_previsao_ao_vivo as robo

_DOWNLOADER_PATH = Path(__file__).resolve().parents[1] / "codigo_python/10_chuvas/baixar_chuvas_horarias.py"
_SPEC = importlib.util.spec_from_file_location("chuvas_horarias_downloader", _DOWNLOADER_PATH)
downloader = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(downloader)


class FontesOficiaisTest(unittest.TestCase):
    def test_cemaden_utc_para_brt_sem_interpolar(self):
        payload = {
            "estacao": {"codEstacao": "432040401A"},
            "horarios": ["22h", "23h", "0h", "1h"],
            "datas": ["30/08/2026", "31/08/2026"],
            "acumulados": [
                [1.0, 2.0, None, None],
                [None, None, 3.0, 4.0],
            ],
        }
        serie = fontes.parse_cemaden_chuva(payload)
        self.assertEqual(
            serie,
            {
                dt.datetime(2026, 8, 30, 19): 1.0,
                dt.datetime(2026, 8, 30, 20): 2.0,
                dt.datetime(2026, 8, 30, 21): 3.0,
                dt.datetime(2026, 8, 30, 22): 4.0,
            },
        )

    def test_cemaden_rejeita_estacao_trocada(self):
        with self.assertRaises(ValueError):
            fontes.parse_cemaden_chuva(
                {"estacao": {"codEstacao": "OUTRA"}, "horarios": [], "datas": [], "acumulados": []}
            )

    def test_inmet_utc_para_brt_e_ausencia_nao_vira_zero(self):
        serie = fontes.parse_inmet_chuva(
            [
                {"DT_MEDICAO": "2026-08-31", "HR_MEDICAO": "0000", "CHUVA": "1.2"},
                {"DT_MEDICAO": "2026-08-31", "HR_MEDICAO": "0100", "CHUVA": None},
            ]
        )
        self.assertEqual(serie, {dt.datetime(2026, 8, 30, 20): 1.2})

    def test_downloader_preserva_csv_e_mescla_observacao_real(self):
        colunas = ["chuva_02851072", "chuva_cemaden_4320404010A"]
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "chuvas.csv"
            with caminho.open("w", newline="", encoding="utf-8") as arquivo:
                writer = csv.writer(arquivo)
                writer.writerow(["COD_SEQUENCIAL", *colunas])
                writer.writerow(["202608300200", "1.5", ""])
            anterior = downloader.SAIDA
            try:
                downloader.SAIDA = str(caminho)
                series, _, _ = downloader.carregar_existente(colunas)
                downloader.mesclar_observacoes(
                    series["chuva_cemaden_4320404010A"],
                    {dt.datetime(2026, 8, 30, 2): None, dt.datetime(2026, 8, 30, 3): 0.0},
                )
            finally:
                downloader.SAIDA = anterior
        self.assertEqual(series["chuva_02851072"][dt.datetime(2026, 8, 30, 2)], 1.5)
        self.assertEqual(series["chuva_cemaden_4320404010A"][dt.datetime(2026, 8, 30, 3)], 0.0)
        self.assertNotIn(dt.datetime(2026, 8, 30, 2), series["chuva_cemaden_4320404010A"])


class ExcelMaeFormulaTest(unittest.TestCase):
    HORA = dt.datetime(2026, 8, 30, 20)
    NIVEL_POSTOS = (
        "86472600", "86472000", "86125500", "86298000", "86306000",
        "86430900", "86448000", "86447000", "86505500",
    )

    def montar_series(self, *, incluir_a894=True, incluir_cemaden=True):
        series = {}
        for indice, codigo in enumerate(self.NIVEL_POSTOS):
            series[codigo] = {
                self.HORA - dt.timedelta(hours=h): 100.0 + indice * 10 + h
                for h in range(40)
            }

        def chuva(atual, anterior):
            return {
                self.HORA - dt.timedelta(hours=h): atual if h < 24 else anterior
                for h in range(48)
            }

        postos = {
            "86472600": chuva(1.0, 0.5),
            "86472000": chuva(3.0, 1.0),
            "2851072": chuva(1.0, 0.5),
            "A894": chuva(2.0, 1.0) if incluir_a894 else {},
            "432040401A": chuva(5.0, 2.0) if incluir_cemaden else {},
        }
        series["__chuva8h_postos__"] = postos
        return series

    def test_v001_e_v002_reproduzem_as_seis_formulas_de_chuva(self):
        series = self.montar_series()
        v001, _ = robo.montar_inputs_8h_alt_v001(series, self.HORA)
        v002, _ = robo.montar_inputs_8h_alt_v002(series, self.HORA)
        esperado = [36.0, 30.0, 48.0, 36.0, 6.0, 21.0]
        self.assertEqual(v001[-6:], esperado)
        self.assertEqual(v002[-6:], esperado)
        self.assertEqual(len(v001), 31)
        self.assertEqual(len(v002), 28)

    def test_average_do_excel_usa_somente_estacoes_disponiveis(self):
        series = self.montar_series(incluir_a894=False)
        v001, _ = robo.montar_inputs_8h_alt_v001(series, self.HORA)
        # 02851072 + CEMADEN, sem A894: (18 + 90) / 2; CEMADEN 6h = 30.
        self.assertEqual(v001[-4], 54.0)
        self.assertEqual(v001[-1], 30.0)

    def test_sem_a894_e_cemaden_input_6h_fica_ausente(self):
        series = self.montar_series(incluir_a894=False, incluir_cemaden=False)
        v001, _ = robo.montar_inputs_8h_alt_v001(series, self.HORA)
        self.assertIsNone(v001[-1])
        self.assertNotEqual(v001[-1], 0.0)

    def test_lacuna_interna_nao_e_inventada_como_zero(self):
        series = self.montar_series()
        del series["__chuva8h_postos__"]["432040401A"][
            self.HORA - dt.timedelta(hours=2)
        ]
        self.assertIsNone(robo._chuva_acum_8h(series, "432040401A", self.HORA, 6))
        # A media ainda pode usar o A894, cuja janela esta completa.
        v001, _ = robo.montar_inputs_8h_alt_v001(series, self.HORA)
        self.assertEqual(v001[-1], 12.0)

    def test_linha_real_do_excel_mae_row_3685(self):
        self.assertAlmostEqual(robo._media_disponiveis(16.6, 2.0, 2.0), 6.866666666666667)
        self.assertAlmostEqual(robo._media_disponiveis(43.4, 17.4, 14.6), 25.133333333333333)
        self.assertAlmostEqual(robo._media_disponiveis(0.2, 0.0), 0.1)

    def test_hashes_das_planilhas_mae_auditadas_ficam_fixos(self):
        self.assertEqual(
            robo.MODELO_8H_V001_FORMULA_SHA256,
            "E675E77B671DBB6AC20E4A46230B851CA33B3A789AE6DBAA2A1C6409EB2BA9F6",
        )
        self.assertEqual(
            robo.MODELO_8H_V002_FORMULA_SHA256,
            "9D036026B8DEDB7DA90F285CA39F1B13C53F194266D18DDFD46D106874044EDC",
        )


if __name__ == "__main__":
    unittest.main()
