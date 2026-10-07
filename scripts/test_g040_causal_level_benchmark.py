#!/usr/bin/env python3
import py_compile
import unittest
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import evaluate_g040_causal_level_benchmark as m

class TestLevelBenchmark(unittest.TestCase):
    def test_compiles(self):
        py_compile.compile(str(ROOT/"scripts/evaluate_g040_causal_level_benchmark.py"),doraise=True)

    def test_spearman(self):
        self.assertAlmostEqual(m.spearman([1,2,3,4],[10,20,30,40]),1.0)
        self.assertAlmostEqual(m.spearman([1,2,3,4],[40,30,20,10]),-1.0)

    def test_shape(self):
        self.assertAlmostEqual(m.shape_rmse([1,2,3],[10,20,30]),0.0)
        self.assertAlmostEqual(m.sign_skill([1,2,1],[10,20,10]),1.0)

    def test_no_rating_curve_conversion(self):
        src=(ROOT/"scripts/evaluate_g040_causal_level_benchmark.py").read_text(encoding="utf-8")
        self.assertIn('"rating_curve_used":False',src)
        self.assertNotIn("q_to_stage",src)
        self.assertNotIn("rating_curve(",src)

if __name__=="__main__":
    unittest.main()
