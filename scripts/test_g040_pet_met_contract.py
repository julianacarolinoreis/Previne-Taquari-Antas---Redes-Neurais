#!/usr/bin/env python3
from __future__ import annotations
import json, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class PetMetContractTests(unittest.TestCase):
    def test_pet_matrix_is_fail_closed(self):
        j=json.loads((ROOT/"config/g040_pet_strategy_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(j["status"],"EXPERIMENT_MATRIX_READY_NO_METHOD_PROMOTED")
        self.assertFalse(j["promotion_allowed"])
        self.assertTrue(j["hec_hms"]["zero_pet_forbidden_as_default"])
        self.assertEqual(j["mgb"]["preferred_historical_source"],"ERA5-Land official CDS")
        self.assertEqual(j["mgb"]["independent_audit_source"],"NASA POWER hourly")

    def test_met_audit_does_not_promote_source(self):
        src=(ROOT/"scripts/audit_g040_nasa_power_met.py").read_text(encoding="utf-8")
        for p in ["T2M","RH2M","WS10M","ALLSKY_SFC_SW_DWN","PS"]:
            self.assertIn(p,src)
        self.assertIn('"canonical_mgb_forcing_ready":False',src)
        self.assertIn('"pet_method_selected":False',src)

if __name__=="__main__":
    unittest.main()
