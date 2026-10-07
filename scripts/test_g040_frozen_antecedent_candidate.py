#!/usr/bin/env python3
import py_compile, unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import select_g040_frozen_antecedent_candidate as m

class TestFrozenAntecedentSelector(unittest.TestCase):
    def test_compiles(self):
        py_compile.compile(str(ROOT/"scripts/select_g040_frozen_antecedent_candidate.py"),doraise=True)

    def test_frozen_split(self):
        self.assertEqual(m.DONORS,("E22_SEP2023","E24_NOV2023"))
        self.assertEqual(m.TARGETS,("E27_MAY2024","E28_JUN2024","E2026_JUL"))
        self.assertTrue(set(m.DONORS).isdisjoint(m.TARGETS))

    def test_distance_uses_antecedent_only(self):
        a={k:10.0 for k in m.FEATURES}
        b={k:20.0 for k in m.FEATURES}
        d,parts=m.distance(a,b)
        self.assertGreater(d,0)
        self.assertEqual(set(parts),set(m.FEATURES))
        src=(ROOT/"scripts/select_g040_frozen_antecedent_candidate.py").read_text(encoding="utf-8")
        self.assertNotIn("future_flow",src)
        self.assertIn('"selection_uses_target_fit_metrics":False',src)
        self.assertIn('"selection_uses_future_event_rain":False',src)

if __name__=="__main__":
    unittest.main()
