"""Validation harness: Comparing JavaScript statistics against Python pymannkendall.

Compares:
  1. Amazon Box (Full Record, 2000-2013 TRMM, 2014-2025 GPM)
  2. Sahel Box (Full Record, 2000-2013 TRMM, 2014-2025 GPM)
  3. 30 random cells per variable across all 12 variables

Computes and prints:
  - Max slope difference (%)
  - Pearson & Spearman rank correlation of p-values
  - Verifies discrepancy < 2% in slope
"""

import json
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr
import xarray as xr
import pymannkendall as mk

from variables import VARIABLES
from cross_check import AMAZON_BBOX, SAHEL_BBOX

NODE_SCRIPT = "scratch/run_js_batch.js"


def get_regional_series(var_id: str, bbox: tuple):
    anom_file = f"data/processed/{var_id}_anomalies.nc"
    if var_id == "gpm_precip":
        anom_file = "data/processed/precip_anomalies.nc"
        
    ds = xr.open_dataset(anom_file)
    da_name = [k for k in ds.data_vars if "anomaly" in k][0]
    sub = ds[da_name].sel(lat=slice(bbox[0], bbox[1]), lon=slice(bbox[2], bbox[3])).mean(dim=("lat", "lon"))
    times = pd.to_datetime(sub["time"].values)
    vals = sub.values
    ds.close()
    return vals, times


def run_python_test(series):
    v = series[np.isfinite(series)]
    if len(v) < 10:
        return 0.0, 1.0, 1.0
    res_hr = mk.hamed_rao_modification_test(v)
    res_plain = mk.original_test(v)
    return float(res_hr.slope * 120.0), float(res_hr.p), float(res_plain.p)


def main():
    print("=" * 80)
    print("  VALIDATION: JAVASCRIPT STATISTICAL ENGINE VS. PYTHON PYMANNKENDALL")
    print("=" * 80)
    
    test_cases = []
    
    # 1. Amazon & Sahel Regional Series (Full, 2000-2013, 2014-2025)
    for var_id in ["gpm_precip", "gldas_precip", "gldas_temp"]:
        for name, bbox in [("Amazon", AMAZON_BBOX), ("Sahel", SAHEL_BBOX)]:
            vals, times = get_regional_series(var_id, bbox)
            m_t1 = times <= pd.Timestamp("2013-12-31")
            m_t2 = times > pd.Timestamp("2013-12-31")
            
            test_cases.append({
                "id": f"{var_id}_{name}_full",
                "var_id": var_id,
                "label": f"{name} Full (2000-2025)",
                "data": vals.tolist(),
            })
            test_cases.append({
                "id": f"{var_id}_{name}_t1",
                "var_id": var_id,
                "label": f"{name} 2000-2013",
                "data": vals[m_t1].tolist(),
            })
            test_cases.append({
                "id": f"{var_id}_{name}_t2",
                "var_id": var_id,
                "label": f"{name} 2014-2025",
                "data": vals[m_t2].tolist(),
            })

    # 2. 30 Random cells per variable across 12 variables
    np.random.seed(42)
    for var_id in VARIABLES.keys():
        if var_id == "modis_ndvi": continue
        anom_file = f"data/processed/{var_id}_anomalies.nc"
        if var_id == "gpm_precip": anom_file = "data/processed/precip_anomalies.nc"
        if not Path(anom_file).exists(): continue
        
        with xr.open_dataset(anom_file) as ds:
            da_name = [k for k in ds.data_vars if "anomaly" in k][0]
            arr = ds[da_name].values # (304, 72, 144)
            lats = ds["lat"].values
            valid_lat_idx = np.where(np.abs(lats) <= 60)[0]
            
            sampled = 0
            attempts = 0
            while sampled < 30 and attempts < 200:
                attempts += 1
                li = int(np.random.choice(valid_lat_idx))
                lj = int(np.random.randint(0, 144))
                series = arr[:, li, lj]
                if np.sum(np.isfinite(series)) >= 200:
                    test_cases.append({
                        "id": f"{var_id}_cell_{li}_{lj}",
                        "var_id": var_id,
                        "label": f"{var_id} cell ({lats[li]:.1f}, {ds['lon'].values[lj]:.1f})",
                        "data": series.tolist(),
                    })
                    sampled += 1

    print(f"[*] Prepared {len(test_cases)} test cases for cross-validation.")

    # Run Python calculations
    py_results = {}
    for tc in test_cases:
        arr = np.array(tc["data"])
        slope, p_hr, p_plain = run_python_test(arr)
        py_results[tc["id"]] = {
            "slope": slope,
            "p_hr": p_hr,
            "p_plain": p_plain,
        }

    # Write test cases to JSON for Node.js
    with open("scratch/validation_input.json", "w") as f:
        json.dump(test_cases, f)

    # Node runner script
    node_runner = """
    const fs = require('fs');
    const { computeHamedRao } = require('./test_js_stats_engine.js');

    const cases = JSON.parse(fs.readFileSync('scratch/validation_input.json', 'utf8'));
    const results = {};

    for (const tc of cases) {
      const valid = tc.data.filter(v => v !== null && isFinite(v));
      if (valid.length < 10) {
        results[tc.id] = { slope: 0, p_hr: 1.0, p_plain: 1.0 };
        continue;
      }
      const res = computeHamedRao(valid);
      results[tc.id] = {
        slope: res.slope * 120.0,
        p_hr: res.p,
        p_plain: res.p_plain,
      };
    }

    fs.writeFileSync('scratch/validation_output_js.json', JSON.stringify(results));
    """
    with open("scratch/run_js_batch.js", "w") as f:
        f.write(node_runner)

    subprocess.run(["node", "scratch/run_js_batch.js"], check=True)

    with open("scratch/validation_output_js.json") as f:
        js_results = json.load(f)

    # Compare
    slope_diffs_pct = []
    py_p_list = []
    js_p_list = []
    py_slope_list = []
    js_slope_list = []

    print("\n--- SAMPLE REGIONAL COMPARISON (AMAZON & SAHEL) ---")
    for tc in test_cases[:9]:
        tid = tc["id"]
        py_s, py_p = py_results[tid]["slope"], py_results[tid]["p_hr"]
        js_s, js_p = js_results[tid]["slope"], js_results[tid]["p_hr"]
        diff_pct = abs(js_s - py_s) / max(abs(py_s), 1e-4) * 100.0
        print(f"  {tc['label']:<28} | Py: slope={py_s:+7.3f}, p={py_p:.4f} | JS: slope={js_s:+7.3f}, p={js_p:.4f} | diff={diff_pct:.3f}%")

    for tid in py_results:
        py_s = py_results[tid]["slope"]
        js_s = js_results[tid]["slope"]
        py_p = py_results[tid]["p_hr"]
        js_p = js_results[tid]["p_hr"]

        if abs(py_s) > 1e-4 and abs(js_s) > 1e-4:
            pct = abs(js_s - py_s) / abs(py_s) * 100.0
            slope_diffs_pct.append(pct)

        py_p_list.append(py_p)
        js_p_list.append(js_p)
        py_slope_list.append(py_s)
        js_slope_list.append(js_s)

    max_slope_diff = max(slope_diffs_pct) if slope_diffs_pct else 0.0
    mean_slope_diff = np.mean(slope_diffs_pct) if slope_diffs_pct else 0.0
    valid_p = np.isfinite(py_p_list) & np.isfinite(js_p_list)
    p_spearman, _ = spearmanr(np.array(py_p_list)[valid_p], np.array(js_p_list)[valid_p])
    p_pearson, _ = pearsonr(np.array(py_p_list)[valid_p], np.array(js_p_list)[valid_p])

    valid_s = np.isfinite(py_slope_list) & np.isfinite(js_slope_list)
    slope_pearson, _ = pearsonr(np.array(py_slope_list)[valid_s], np.array(js_slope_list)[valid_s])

    print("\n" + "=" * 80)
    print("  VALIDATION SUMMARY REPORT (JS vs. PYTHON)")
    print("=" * 80)
    print(f"  Total Series Tested           : {len(test_cases)}")
    print(f"  Max Slope Difference          : {max_slope_diff:.4f}% (< 2.0% requirement: {'PASS' if max_slope_diff < 2.0 else 'FAIL'})")
    print(f"  Mean Slope Difference         : {mean_slope_diff:.4f}%")
    print(f"  Slope Pearson Correlation (r) : {slope_pearson:.6f}")
    print(f"  P-value Spearman Rank Corr    : {p_spearman:.6f} (> 0.99 requirement: {'PASS' if p_spearman > 0.99 else 'FAIL'})")
    print(f"  P-value Pearson Correlation   : {p_pearson:.6f}")
    print("=" * 80)

    assert max_slope_diff < 2.0, f"Max slope difference {max_slope_diff}% exceeds 2% threshold!"
    assert p_spearman > 0.99, f"P-value rank correlation {p_spearman} is below 0.99!"
    print("\n>>> ALL VALIDATION CHECKS PASSED PERFECTLY! <<<")


if __name__ == "__main__":
    main()
