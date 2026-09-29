#!/usr/bin/env python3
"""Blind hold-out E31 using the already frozen P2 benchmark algorithm.

This file intentionally does not change scoring, parameter search, state
initialization, rainfall analog distance, metrics, or online recalibration.
It only adds the E31 event window and points TARGETS to E31.
"""
from pathlib import Path
import benchmark_mucum_pseudo_operational_p2 as b

b.EVENTS["E31"]=("2025-06-28 19:00:00","2025-07-04 02:00:00")
b.TARGETS=("E31",)
b.OUT=b.BASE/"scientific_benchmark_v1/holdout_e31_p2"
b.OUT.mkdir(parents=True,exist_ok=True)

if __name__=="__main__":
    b.main()
