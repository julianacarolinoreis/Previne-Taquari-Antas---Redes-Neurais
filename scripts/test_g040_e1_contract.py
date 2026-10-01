#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
MOD=ROOT/"scripts/run_hec_hms_g040_e1_hindcast.py"
spec=importlib.util.spec_from_file_location("g040e1",MOD)
m=importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(m)

class E1ContractTests(unittest.TestCase):
    def test_hec_subbasin_names_fit_limit(self):
        ids=[
            "BRANCH_86595000","BRANCH_86746000",
            "CORE_INC_86472000_86510000","CORE_INC_86510000_86720000",
            "CORE_INC_86720000_86743000","CORE_INC_86743000_86879000",
            "CORE_INC_86879000_86879300","CORE_INC_86879300_86895000",
        ]
        names=[m.hec_subbasin_name(x) for x in ids]
        self.assertEqual(len(names),len(set(names)))
        self.assertTrue(all(len(x)<=28 for x in names))

    def test_generated_project_contains_primary_flow_gage(self):
        start=m.utc("2026-09-28T00:00:00Z")
        end=m.utc("2026-09-29T00:00:00Z")
        used=["CORE_INC_86472000_86510000","BRANCH_86595000"]
        active=["86500000"]
        g=m.build_gage(start,end,active,used)
        self.assertIn("Gage: Q_86472000",g)
        self.assertIn("Gage: Q_86500000",g)
        self.assertIn("/G040/86472000/FLOW/01Sep2026/1Hour/FORECAST/",g)
        self.assertNotIn("/G040/86472000/FLOW/01Sep2026/1Hour/OBS/",g)

    def test_preflight_rejects_missing_primary_gage(self):
        start=m.utc("2026-09-28T00:00:00Z")
        end=m.utc("2026-09-29T00:00:00Z")
        used=["CORE_INC_86472000_86510000"]
        active=["86500000"]
        g=m.build_gage(start,end,active,used).replace("Gage: Q_86472000","Gage: Q_MISSING")
        met=m.build_met(used)
        basin="\n".join([
            "Flow Gage: Q_86472000",
            "Flow Gage: Q_86500000",
        ])
        with self.assertRaises(RuntimeError):
            m.validate_project_contract(g,met,basin,active,used)

    def test_jython_writer_has_exact_dss_readback_preflight(self):
        src=MOD.read_text(encoding="utf-8")
        self.assertIn("DSS_PREFLIGHT|%s|%d",src)
        self.assertIn('1Hour/FORECAST/',src)
        self.assertIn('raise RuntimeError("DSS preflight failed',src)

if __name__=="__main__":
    unittest.main()
