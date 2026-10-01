#!/usr/bin/env python3
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))

import g040_rain_grid as grid
import build_g040_observed_rain_forcing as g040_obs
import build_g040_ifs_interval_forcing as g040_fc
import build_mucum_observed_multistation as mucum_obs


class G040RainContractTests(unittest.TestCase):
    def test_forecast_helpers_exist(self):
        for name in ("load_support","parse_hour","start_hour"):
            self.assertTrue(callable(getattr(g040_fc,name,None)),name)

    def test_fixed_grid_contract(self):
        cells=grid.build_grid_cells()
        self.assertEqual(grid.GRID_ROWS,20)
        self.assertEqual(grid.GRID_COLS,30)
        self.assertEqual(len(cells),600)
        self.assertAlmostEqual(grid.GRID_STEP_DEG,0.1)
        self.assertAlmostEqual(cells[0]["latitude"],-29.95)
        self.assertAlmostEqual(cells[0]["longitude"],-52.75)
        self.assertAlmostEqual(cells[-1]["latitude"],-28.05)
        self.assertAlmostEqual(cells[-1]["longitude"],-49.85)
        self.assertEqual(grid.point_to_grid_index(-52.79,-29.99),0)
        self.assertEqual(grid.point_to_grid_index(-49.8,-28.0),599)

    def test_g040_idw2_uses_all_valid_stations(self):
        d2=np.array([[1.,4.,9.,16.,25.,36.,49.]],dtype=float)
        vals=np.array([10.,20.,30.,40.,50.,60.,70.],dtype=float)
        got=float(g040_obs.interpolate_points(d2,vals)[0])
        weights=1.0/d2[0]
        expected=float(np.sum(weights*vals)/np.sum(weights))
        self.assertAlmostEqual(got,expected,places=10)
        first6=float(np.sum(weights[:6]*vals[:6])/np.sum(weights[:6]))
        self.assertGreater(abs(got-first6),1e-6)

    def test_g040_idw2_missing_is_excluded_not_zero(self):
        d2=np.array([[1.,4.,9.]],dtype=float)
        vals=np.array([10.,np.nan,30.],dtype=float)
        got=float(g040_obs.interpolate_points(d2,vals)[0])
        expected=(10./1.+30./9.)/(1.+1./9.)
        self.assertAlmostEqual(got,expected,places=10)

    def test_exact_station_value_wins(self):
        d2=np.array([[4.,0.,9.]],dtype=float)
        vals=np.array([10.,22.,30.],dtype=float)
        self.assertEqual(float(g040_obs.interpolate_points(d2,vals)[0]),22.0)

    def test_mucum_idw2_uses_all_valid_stations(self):
        points=[(0.0,0.0,1.0)]
        stations=[
            {"code":str(i),"lon":math.sqrt(float(i)),"lat":0.0}
            for i in range(1,8)
        ]
        values={str(i):float(i*10) for i in range(1,8)}
        got=float(mucum_obs.idw_mean(points,stations,values))
        weights=np.array([1.0/i for i in range(1,8)],dtype=float)
        vals=np.array([i*10.0 for i in range(1,8)],dtype=float)
        expected=float(np.sum(weights*vals)/np.sum(weights))
        self.assertAlmostEqual(got,expected,places=10)

    def test_forecast_distinguishes_sampling_from_native_resolution(self):
        src=(ROOT/"scripts/build_g040_ifs_interval_forcing.py").read_text(encoding="utf-8")
        self.assertIn('"native_model_resolution_deg":0.25',src)
        self.assertIn('"sampling_grid_resolution_deg":GRID_STEP_DEG',src)
        self.assertIn('"full_600_cell_grid":len(fetched)==GRID_CELL_COUNT',src)
        self.assertIn('"exact_cycle_id_available":False',src)
        self.assertNotIn('nearest native 0.25-degree IFS cell center',src)

    def test_observed_contract_has_no_nearest_k_limit(self):
        src=(ROOT/"scripts/build_g040_observed_rain_forcing.py").read_text(encoding="utf-8")
        self.assertNotIn("IDW_K",src)
        self.assertIn('"station_scope":"all_valid_stations_each_hour"',src)
        self.assertIn('"cross_station_sum":False',src)
        self.assertIn('"full_grid_preserved":True',src)

    def test_merge_requires_same_grid_and_preserves_600_cells(self):
        src=(ROOT/"scripts/build_g040_merged_rain_forcing.py").read_text(encoding="utf-8")
        self.assertIn("observed/forecast grid contract mismatch",src)
        self.assertIn('len(obs_cells)!=600',src)
        self.assertIn('"overlap_averaged":False',src)
        self.assertIn('"missing_zero_filled":False',src)
        self.assertIn('"operational_promotion_allowed":bool(base_ready and exact_cycle)',src)


if __name__=="__main__":
    unittest.main()
