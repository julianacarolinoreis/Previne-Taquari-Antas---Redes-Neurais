#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "assets/data/hec_hms_g040_full_basin/original_145_meteorologic_assignment_latest.csv"
AUDIT_PATH = ROOT / "assets/data/hec_hms_g040_full_basin/original_145_meteorologic_assignment_audit_latest.json"


class LegacyMeteorologicAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
        self.audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

    def test_recovered_source_integrity(self):
        ids = [int(r["bacia"]) for r in self.rows]
        self.assertEqual(len(self.rows), 144)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([i for i in range(1, 146) if i not in set(ids)], [99])

    def test_station_fields_preserved(self):
        cols = ["station_sep_2023", "station_nov_2023", "station_may_2024"]
        for row in self.rows:
            for col in cols:
                self.assertTrue(row[col].strip())
        self.assertEqual(len({r["station_sep_2023"] for r in self.rows}), 27)
        self.assertEqual(len({r["station_nov_2023"] for r in self.rows}), 19)
        self.assertEqual(len({r["station_may_2024"] for r in self.rows}), 43)

    def test_audit_forbids_silent_fill(self):
        integrity = self.audit["integrity"]
        self.assertEqual(integrity["missing_bacia_ids"], [99])
        self.assertFalse(integrity["silent_fill_permitted"])
        self.assertEqual(integrity["status"], "INCOMPLETE_BY_SOURCE_PRESERVED")


if __name__ == "__main__":
    unittest.main()
