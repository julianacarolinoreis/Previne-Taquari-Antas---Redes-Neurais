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
import build_g040_observed_rain_forcing as obs


class G040RainContractTests(unittest.TestCase):
    def test_fixed_grid_contract(self):
        cells=grid.build_grid_cells()
        self.assertEqual(len(cells),600)
        self.assertEqual(grid.GRID_ROWS,20)
        self.assertEqual(grid.GRID_COLS,30)
        self.assertAlmostEqual(grid.GRID_STEP_DEG,0.1)
        self.assertAlmostEqual(cells[0]["latitude"],-29.95)
        self.assertAlmostEqual(cells[0]["longitude"],-52.75)
        self.assertAlmostEqual(cells[-1]["latitude"],-28.05)
        self.assertAlmostEqual(cells[-1]["longitude"],-49.85)
        self.assertEqual(grid.point_to_grid_index(-52.79,-29.99),0)
        self.assertEqual(grid.point_to_grid_index(-49.8,-28.0),599)

    def test_idw2_uses_every_valid_station(self):
        d2=np.array([[1.0,4.0,9.0,16.0,25.0,36.0,49.0]],dtype=float)
        vals=np.array([10.,20.,30.,40.,50.,60.,70.],dtype=float)
        got=float(obs.interpolate_all_valid_idw2(d2,vals)[0])
        weights=1.0/d2[0]
        expected=float(np.sum(weights*vals)/np.sum(weights))
        self.assertAlmostEqual(got,expected,places=10)

        # If the old nearest-six behavior returns, station 7 disappears and
        # this exact expectation changes.
        first6=float(np.sum(weights[:6]*vals[:6])/np.sum(weights[:6]))
        self.assertGreater(abs(got-first6),1e-6)

    def test_idw2_missing_is_excluded_not_zero(self):
        d2=np.array([[1.0,4.0,9.0]],dtype=float)
        vals=np.array([10.,np.nan,30.],dtype=float)
        got=float(obs.interpolate_all_valid_idw2(d2,vals)[0])
        expected=(10.0/1.0+30.0/9.0)/(1.0+1.0/9.0)
        self.assertAlmostEqual(got,expected,places=10)

    def test_exact_gauge_value_wins_at_gauge_location(self):
        d2=np.array([[4.0,0.0,9.0]],dtype=float)
        vals=np.array([10.,22.,30.],dtype=float)
        got=float(obs.interpolate_all_valid_idw2(d2,vals)[0])
        self.assertEqual(got,22.0)

    def test_sources_keep_native_and_sampling_resolution_distinct(self):
        src=(ROOT/"scripts/build_g040_ifs_interval_forcing.py").read_text(encoding="utf-8")
        self.assertIn('"native_model_resolution_deg":0.25',src)
        self.assertIn('"sampling_grid_resolution_deg":GRID_STEP_DEG',src)
        self.assertIn('"requested_cells":len(fetched)',src)
        self.assertIn('"full_600_cell_grid":len(fetched)==GRID_CELL_COUNT',src)
        self.assertIn('"exact_cycle_id_available":False',src)
        self.assertNotIn('grid_assignment":"nearest native 0.25-degree IFS cell center"',src)

    def test_observed_contract_has_no_nearest_k_limit(self):
        src=(ROOT/"scripts/build_g040_observed_rain_forcing.py").read_text(encoding="utf-8")
        self.assertNotIn("IDW_K",src)
        self.assertIn('"station_scope":"all_valid_stations_each_hour"',src)
        self.assertIn('"cross_station_sum":False',src)
        self.assertIn('"full_grid_preserved":True',src)

    def test_merge_requires_identical_grid_contract(self):
        src=(ROOT/"scripts/build_g040_merged_rain_forcing.py").read_text(encoding="utf-8")
        self.assertIn("observed/forecast grid contract mismatch",src)
        self.assertIn("IFS_FULLGRID_FORCING_READY_CYCLE_ID_UNVERIFIED",src)
        self.assertIn('"overlap_averaged":False',src)
        self.assertIn('"missing_zero_filled":False',src)


if __name__=="__main__":
    unittest.main()
