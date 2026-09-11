#!/usr/bin/env python3
"""Tests for Muçum HEC twin leave-one-out hindcast skill (quanto sobe)."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
SCRIPTS = ROOT / "scripts"


class HindcastSkill5dTests(unittest.TestCase):
    def test_loo_excludes_target_and_scores(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import run_hec_twin_mucum_hindcast_skill_5d as skill
        import run_hec_twin_mucum_forward_5d as fwd

        modelo = json.loads((OUT / "modelo_mucum_eventwise_v1_fechado_latest.json").read_text(encoding="utf-8"))
        hec = json.loads((OUT / "hec_twin_stz_mucum_v1_latest.json").read_text(encoding="utf-8"))
        library = list(modelo["params_library_eventwise"])
        hec_events = list(hec["models"]["mucum"]["events"])
        hec_by_id = {e["event_id"]: e for e in hec_events}
        areas = fwd.load_areas()
        segments = fwd.mucum_curve_segments()

        target = "E23"
        analog = skill.pick_loo_analog(target, 120.0, library, hec_events)
        self.assertIsNotNone(analog)
        assert analog is not None
        self.assertNotEqual(analog["event_id"], target)

        row = skill.score_event(
            target,
            library=library,
            hec_by_id=hec_by_id,
            hec_events=hec_events,
            areas=areas,
            segments=segments,
        )
        self.assertEqual(row["status"], "scored")
        self.assertNotEqual(row["analog_event_id"], target)
        self.assertIsNotNone(row["obs_rise_n_cm"])
        self.assertIsNotNone(row["sim_rise_n_cm"])
        self.assertGreater(row["pairs"], 6)

        summary = skill.summarize([row])
        verdict = skill.build_verdict(summary)
        self.assertIn(verdict["level"], {"usable_research", "caution", "weak"})
        self.assertIn("Hindcast", verdict["plain_pt"])

    def test_cli_writes_artifacts(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "run_hec_twin_mucum_hindcast_skill_5d.py"),
                    "--events",
                    "E23",
                    "E28",
                    "--out-dir",
                    str(out),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("wrote", proc.stdout)
            data = json.loads((out / "hec_twin_mucum_hindcast_skill_5d_latest.json").read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], "hec_twin_mucum_hindcast_skill_5d_v1")
            self.assertGreaterEqual(data["summary"]["n_scored"], 1)
            self.assertIn("plain_pt", data["verdict"])
            html = (out / "hec_twin_mucum_hindcast_skill_5d.html").read_text(encoding="utf-8")
            self.assertIn("Veredito", html)
            self.assertIn("rna", data["method"]["not"])
            self.assertIn("stz_n", data["method"]["not"])


if __name__ == "__main__":
    unittest.main()
