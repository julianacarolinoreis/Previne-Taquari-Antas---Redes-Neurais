#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/"scripts/run_hec_hms_g040_e1_hindcast.py"
spec=importlib.util.spec_from_file_location("g040e1",P)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class TestNumerics(unittest.TestCase):
    def test_interval_is_three_minutes(self):
        self.assertEqual(m.COMPUTE_INTERVAL_MIN,3)
        from datetime import datetime, timezone
        s=m.build_control(datetime(2023,9,1,tzinfo=timezone.utc),datetime(2023,9,2,tzinfo=timezone.utc))
        self.assertIn("Time Interval: 3",s)

    def test_scs_interval_gate_for_min_search_lag(self):
        self.assertLessEqual(m.COMPUTE_INTERVAL_MIN,0.29*15.847934)

    def test_muskingum_steps_make_coefficients_nonnegative(self):
        dt=m.COMPUTE_INTERVAL_MIN/60.0
        for k in (0.05,0.14,0.20,0.5,1.5,3.0,6.0,12.0):
            for x in (0.10,0.20,0.30):
                try:
                    n=m.muskingum_steps(k,x)
                except RuntimeError:
                    # Some broad search-edge combinations are intentionally
                    # rejected when no stable representation exists within
                    # the HEC-HMS accepted subreach range.
                    continue
                self.assertLessEqual(n,m.MAX_MUSKINGUM_SUBREACHES)
                ks=k/n
                self.assertLessEqual(2*ks*x-1e-12,dt)
                self.assertLessEqual(dt,2*ks*(1-x)+1e-12)

    def test_anchor_long_reach_is_stable_within_hec_limit(self):
        n=m.muskingum_steps(6.0,0.2)
        self.assertLessEqual(n,100)
        dt=m.COMPUTE_INTERVAL_MIN/60.0
        ks=6.0/n
        self.assertLessEqual(2*ks*0.2-1e-12,dt)
        self.assertLessEqual(dt,2*ks*(1-0.2)+1e-12)

    def test_hourly_sampling(self):
        vals=list(range(121))
        self.assertEqual(m.hourly_simulation_values(vals,3),[0,20,40])

if __name__=="__main__":
    unittest.main()
