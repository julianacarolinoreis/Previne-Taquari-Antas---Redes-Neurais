#!/usr/bin/env python3
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "codigo_python/11_experimento_mimo"))

from mimo_core import align_horizons, load_horizon_dataset, load_mat_weights, predict_direct_batch


class TestMimoCore(unittest.TestCase):
    def test_load_horizons(self):
        d2 = load_horizon_dataset("2h")
        d4 = load_horizon_dataset("4h")
        d8 = load_horizon_dataset("8h")
        self.assertEqual(d2.n_inputs, 15)
        self.assertEqual(d4.n_inputs, 26)
        self.assertEqual(d8.n_inputs, 31)
        self.assertEqual(set(d2.split), {1, 2, 3})

    def test_direct_repro_2h(self):
        ds = load_horizon_dataset("2h")
        w = load_mat_weights(ds.mat_path)
        pred = predict_direct_batch(w, ds.inputs, ds.atual)
        rmse = float(((pred - ds.target_abs) ** 2).mean() ** 0.5)
        self.assertLess(rmse, 1e-3)

    def test_alignment_non_empty(self):
        a = align_horizons(["2h", "4h"])
        self.assertGreater(len(a["rows"]), 100)
        a3 = align_horizons(["2h", "4h", "8h"])
        self.assertGreater(len(a3["rows"]), 30)


class TestExperimentArtifact(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        json_path = ROOT / "assets/data/research_mimo_multihorizon_latest.json"
        if not json_path.exists():
            subprocess.check_call(
                [sys.executable, str(ROOT / "codigo_python/11_experimento_mimo/run_experiment.py")],
                cwd=str(ROOT / "codigo_python/11_experimento_mimo"),
            )
        cls.data = json.loads(json_path.read_text(encoding="utf-8"))

    def test_schema(self):
        self.assertIn("experiments", self.data)
        self.assertIn("exp1_2h4h_15in", self.data["experiments"])
        exp = self.data["experiments"]["exp1_2h4h_15in"]
        self.assertIn("summary_scratch_vs_mimo", exp)
        self.assertIn("direct_mat", exp)
        self.assertIn("mimo", exp)

    def test_test_split_present(self):
        exp = self.data["experiments"]["exp1_2h4h_15in"]
        self.assertIn("2h", exp["direct_mat"]["splits"]["teste"])
        self.assertIn("4h", exp["mimo"]["splits"]["teste"])


if __name__ == "__main__":
    unittest.main()
