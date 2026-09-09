#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "data" / "estudo_bacia_taquari_antas"


class DoisModelosTests(unittest.TestCase):
    def test_decision_locked(self) -> None:
        data = json.loads((OUT / "dois_modelos_stz_mucum_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["decision"]["chosen"], "dois_modelos_alvo_STZ_e_Mucum")
        self.assertIn("Muçum", data["decision"]["statement"])
        self.assertIn("Santa Tereza", data["decision"]["statement"])

    def test_targets_and_exclusions(self) -> None:
        data = json.loads((OUT / "dois_modelos_stz_mucum_latest.json").read_text(encoding="utf-8"))
        stz = data["models"]["santa_tereza"]
        muc = data["models"]["mucum"]
        self.assertEqual(stz["target_station"], "86472600")
        self.assertEqual(muc["target_station"], "86510000")
        excluded = set(data["shared_truths"]["excluded_from_both"]["upgs"])
        self.assertTrue({"Guaporé", "Forqueta", "Baixo Taquari-Antas"} <= excluded)
        foz = {f["family"]: f for f in data["shared_truths"]["fozes"]}
        self.assertTrue(foz["7866"]["in_stz_model"])
        self.assertTrue(foz["7868"]["in_stz_model"])
        self.assertFalse(foz["7864"]["in_mucum_model"])
        self.assertFalse(foz["7862"]["in_stz_model"])

    def test_target_stations_present_in_seeds(self) -> None:
        data = json.loads((OUT / "dois_modelos_stz_mucum_latest.json").read_text(encoding="utf-8"))
        stz_codes = {s["codigo"] for s in data["models"]["santa_tereza"]["stations_flu"]}
        muc_codes = {s["codigo"] for s in data["models"]["mucum"]["stations_flu"]}
        self.assertIn("86472600", stz_codes)
        self.assertIn("86472000", stz_codes)
        self.assertIn("86510000", muc_codes)
        self.assertIn("86472600", muc_codes)
        html = (OUT / "dois_modelos_stz_mucum.html").read_text(encoding="utf-8")
        self.assertIn("Um modelo para Santa Tereza", html)
        self.assertIn("nunca 'modelo da bacia", html)


if __name__ == "__main__":
    unittest.main()
