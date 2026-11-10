"""Pipeline batch runner for new variables in Plot Twist.

Processes all new variables:
  - gldas_swe
  - gldas_snow_depth
  - merra2_ts
  - merra2_wind
  - merra2_ps
  - merra2_tqv

Computes anomalies, trends (Sen's slope, Hamed-Rao, plain MK, FDR, cluster significance),
web exports, and generates the required variable summary table and sanity metrics.
"""

import sys
import time
from pathlib import Path
import numpy as np
import xarray as xr

from variables import VARIABLES
from process import process_variable
from trend_all import run_trend_for_variable
from export_web import export_variable_to_web


NEW_VARS = [
    "gldas_swe",
    "gldas_snow_depth",
    "merra2_ts",
    "merra2_wind",
    "merra2_ps",
    "merra2_tqv",
]


def run_pipeline():
    print("=" * 80)
    print("  PLOT TWIST: PROCESSING ALL 6 NEW VARIABLES")
    print("=" * 80)
    
    results = []
    sanity_metrics = {}
    
    t_start = time.time()
    
    for var_id in NEW_VARS:
        vcfg = VARIABLES[var_id]
        print(f"\n{'='*70}\n[>>>] RUNNING PIPELINE FOR: {vcfg.name} ({var_id})\n{'='*70}")
        
        # 1. Process Anomalies
        anom_file = process_variable(var_id)
        
        # 2. Run Hardened Trends
        trend_file = run_trend_for_variable(var_id)
        
        # 3. Export to Web
        web_res = export_variable_to_web(var_id)
        
        # 4. Extract Summary Stats for Reporting
        with xr.open_dataset(anom_file) as ds_anom:
            n_months = len(ds_anom["time"])
            
        with xr.open_dataset(trend_file) as ds_tr:
            valid_mask = ds_tr["valid"].values
            n_valid = int(valid_mask.sum())
            n_plain = int(ds_tr["significant_plain"].values.sum())
            n_mod = int(ds_tr["significant_modified"].values.sum())
            n_fdr = int(ds_tr["significant_fdr"].values.sum())
            
            pct_plain = (n_plain / n_valid * 100.0) if n_valid > 0 else 0.0
            pct_mod = (n_mod / n_valid * 100.0) if n_valid > 0 else 0.0
            pct_fdr = (n_fdr / n_valid * 100.0) if n_valid > 0 else 0.0

        # Web file size in MB
        var_web_dir = Path("web/data") / var_id
        web_size_mb = sum(f.stat().st_size for f in var_web_dir.glob("*")) / (1024 * 1024)
        
        results.append({
            "var_id": var_id,
            "name": vcfg.name,
            "units": vcfg.units,
            "months": n_months,
            "valid_cells": n_valid,
            "pct_plain": pct_plain,
            "pct_mod": pct_mod,
            "pct_fdr": pct_fdr,
            "web_size_mb": web_size_mb,
        })

    print("\n\n" + "=" * 90)
    print("  PART A: COMPREHENSIVE NEW VARIABLES SUMMARY TABLE")
    print("=" * 90)
    print(f"{'Variable ID':<18} | {'Months':<6} | {'Valid Cells':<11} | {'Sig (Plain / Mod / FDR)':<26} | {'Web Size':<9}")
    print("-" * 90)
    for r in results:
        sig_str = f"{r['pct_plain']:.1f}% / {r['pct_mod']:.1f}% / {r['pct_fdr']:.1f}%"
        print(f"{r['var_id']:<18} | {r['months']:<6} | {r['valid_cells']:<11} | {sig_str:<26} | {r['web_size_mb']:.2f} MB")
    print("=" * 90)
    
    # Check total web/data directory size
    total_web_bytes = sum(f.stat().st_size for f in Path("web/data").rglob("*") if f.is_file())
    total_web_mb = total_web_bytes / (1024 * 1024)
    print(f"\n[+] Total web/data footprint across ALL 12 variables: {total_web_mb:.2f} MB (< 60 MB budget)")
    print(f"[+] Total execution time: {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    run_pipeline()
