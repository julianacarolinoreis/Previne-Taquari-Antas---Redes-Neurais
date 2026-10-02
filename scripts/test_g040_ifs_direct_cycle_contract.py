#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MOD=ROOT/"scripts/build_g040_ifs_direct_cycle.py"
spec=importlib.util.spec_from_file_location("g040_direct_cycle",MOD)
m=importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(m)

class DirectCycleContractTests(unittest.TestCase):
    def test_static_contract(self):
        src=MOD.read_text(encoding="utf-8")
        self.assertIn('"EXACT_CYCLE_FULLGRID_READY"',src)
        self.assertIn('"exact_cycle_id_available":True',src)
        self.assertIn('"fallback_used":False',src)
        self.assertIn('"native_model_resolution_deg":0.25',src)
        self.assertIn('"sampling_grid_resolution_deg":0.1',src)
        self.assertIn("GRID_CELL_COUNT",src)
        self.assertIn("build_component_weights",src)
        self.assertIn("build_cell_weights",src)

    def test_cycle_parser_rejects_non_synoptic_hour(self):
        old=m.CYCLE_RAW
        try:
            m.CYCLE_RAW="2026-10-01T05:00:00Z"
            with self.assertRaises(RuntimeError):
                m.select_cycle()
        finally:
            m.CYCLE_RAW=old

if __name__=="__main__":
    unittest.main()
