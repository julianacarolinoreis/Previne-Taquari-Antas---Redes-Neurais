#!/usr/bin/env python3
import py_compile
import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import build_g040_causal_upper_antas as m

class TestUpperAntas(unittest.TestCase):
    def test_compiles(self):
        py_compile.compile(str(ROOT/"scripts/build_g040_causal_upper_antas.py"),doraise=True)
    def test_fixed_split(self):
        self.assertEqual(m.CAL_EVENTS,("E22_SEP2023","E24_NOV2023"))
        src=(ROOT/"scripts/build_g040_causal_upper_antas.py").read_text(encoding="utf-8")
        self.assertNotIn('CAL_EVENTS=("E27',src)
        self.assertIn('"future_observed_flow_used":False',src)
        self.assertIn('"validation_event_used_for_selection":False',src)
        self.assertIn('"pre_t0_scored":False',src)
        self.assertIn('post_idx=[i for i,t in enumerate(axis) if t>=t0]',src)
    def test_simulate_nonnegative(self):
        a={m.Z_PRATA:1000.0,m.Z_ANTAS:2000.0}
        p=m.ZoneParams(1.0,0.5,10.0,20.0,0.9,0.001)
        q=m.simulate_upper([0,5,10,0],[0,5,10,0],p,a)
        self.assertEqual(len(q),4)
        self.assertTrue(all(x>=0 for x in q))

if __name__=="__main__":
    unittest.main()
