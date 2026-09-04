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
        self.assertIn("exp5_leave_one_event_out_2h4h", self.data["experiments"])
        loo = self.data["experiments"]["exp5_leave_one_event_out_2h4h"]
        self.assertEqual(loo.get("status"), "ok")
        self.assertGreaterEqual(loo.get("n_events_evaluated", 0), 5)

    def test_test_split_present(self):
        exp = self.data["experiments"]["exp1_2h4h_15in"]
        self.assertIn("2h", exp["direct_mat"]["splits"]["teste"])
        self.assertIn("4h", exp["mimo"]["splits"]["teste"])
        mimo4 = exp["mimo"]["splits"]["teste"]["4h"]
        self.assertGreater(mimo4["nash"], 0.7)

    def test_mat_ceiling_uses_reference_not_aligned_replay(self):
        ref = self.data["mat_reference_metrics_teste"]
        exp = self.data["experiments"]["exp1_2h4h_15in"]
        summary = exp["summary_mat_vs_mimo"]
        rows = summary.get("ganhos", []) + summary.get("empates", []) + summary.get("perdas", [])
        self.assertTrue(rows, "summary_mat_vs_mimo vazio")
        self.assertEqual(summary.get("baseline"), "mat_reference_metrics_teste")
        for row in rows:
            hz = row["horizonte"]
            base_nash = row["direct"]["nash"]
            self.assertNotAlmostEqual(base_nash, 1.0, places=3, msg=f"{hz}: teto não pode ser replay NASH=1")
            self.assertAlmostEqual(base_nash, ref[hz]["nash"], places=4)
        # Replay alinhado permanece documentado à parte.
        replay = exp.get("summary_mat_aligned_replay_vs_mimo") or {}
        replay_rows = replay.get("ganhos", []) + replay.get("empates", []) + replay.get("perdas", [])
        if replay_rows:
            self.assertAlmostEqual(replay_rows[0]["direct"]["nash"], 1.0, places=3)
        self.assertIn("note_mat_aligned_replay", self.data["method"])

    def test_report_html_avoids_fake_ceiling(self):
        html_path = ROOT / "pesquisas/rna-multi-horizonte-relatorio.html"
        if not html_path.exists():
            subprocess.check_call([sys.executable, str(ROOT / "scripts/build_mimo_research_report.py")], cwd=str(ROOT))
        html = html_path.read_text(encoding="utf-8")
        self.assertIn("mat_reference_metrics_teste", html)
        self.assertIn("teste completo", html)
        # A tabela de teto operacional não deve listar 1,0000 como NASH base.
        self.assertNotIn("<h3>.mat auditado vs MIMO (teto)</h3>", html)
        self.assertIn("teto operacional", html.lower())
        # Ainda pode documentar o replay, mas o bloco de teto usa 0,9962 / 0,9926.
        self.assertIn("0,9962", html)
        self.assertIn("0,9926", html)


    def test_matlab_handoff_package(self):
        import sys
        sys.path.insert(0, str(ROOT / "codigo_python/11_experimento_mimo"))
        import export_matlab_mimo_package as exp
        manifest = exp.export_package()
        out = ROOT / "assets/data/research_mimo_matlab_handoff"
        self.assertGreaterEqual(manifest["n_rows"], 100)
        self.assertTrue((out / "mimo_aligned_2h4h_15in.csv").is_file())
        self.assertTrue((out / "manifest.json").is_file())
        self.assertTrue((ROOT / "codigo_python/11_experimento_mimo/matlab/train_mimo_2h4h_stz.m").is_file())
        # CSV header must expose dual targets
        header = (out / "mimo_aligned_2h4h_15in.csv").read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("delta_2h_cm", header)
        self.assertIn("delta_4h_cm", header)


if __name__ == "__main__":
    unittest.main()
