"""Harden precipitation trend statistics with autocorrelation, FDR, and polar masking.

Features:
  1. Autocorrelation-aware trend: Hamed-Rao modified Mann-Kendall test.
  2. Plain Mann-Kendall p-value retained in 'p_value_plain' for direct comparison.
  3. Multiple Testing Correction: Benjamini-Hochberg FDR applied across all cells ('significant_fdr' at q < 0.05).
  4. Cross-check: Ordinary Least Squares (OLS) slope and t-test p-value per cell; sign agreement metric.
  5. State slope conversion: per-month Sen's slope * 120 = mm / month / decade.
  6. Polar Masking (Honesty Guard): Cells poleward of 60° (|lat| > 60°) are marked valid=0 and their
     significance flags forced to 0 due to unreliable satellite retrievals over polar ice sheets.
  7. Era Split Stability: Computes trend sign for 2000-2013 (TRMM) vs 2014-2025 (GPM) and records 'era_sign_flip'.

Saves: data/processed/precip_trend.nc
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
import pymannkendall as mk
from scipy.stats import false_discovery_control, linregress
import xarray as xr


PROCESSED_DATA_DIR = Path("data/processed")
ANOMALIES_FILE = PROCESSED_DATA_DIR / "precip_anomalies.nc"
TREND_FILE = PROCESSED_DATA_DIR / "precip_trend.nc"

MONTHS_PER_DECADE = 120.0
ERA_BREAK_DATE = "2013-12-31"


def compute_single_cell_metrics(
    series: np.ndarray,
    n_t1: int,
) -> Tuple[float, float, float, float, float, int]:
    """Compute trend metrics and era sign stability for a single grid cell.
    
    Returns:
      (sens_slope_decade, p_val_hr, p_val_plain, ols_slope_decade, ols_p_val, era_sign_flip)
    """
    valid_mask = np.isfinite(series)
    valid_vals = series[valid_mask]
    n_pts = len(valid_vals)

    if n_pts < 10:
        return np.nan, np.nan, np.nan, np.nan, np.nan, 0

    # Zero-variance check (constant series)
    if np.all(valid_vals == valid_vals[0]):
        return 0.0, 1.0, 1.0, 0.0, 1.0, 0

    # 1. Plain Mann-Kendall & Sen's slope
    try:
        res_plain = mk.original_test(valid_vals)
        sens_slope = float(res_plain.slope * MONTHS_PER_DECADE)
        p_plain = float(res_plain.p)
    except Exception:
        sens_slope, p_plain = np.nan, np.nan

    # 2. Autocorrelation-aware Hamed-Rao modified Mann-Kendall
    try:
        res_hr = mk.hamed_rao_modification_test(valid_vals)
        p_hr = float(res_hr.p)
    except Exception:
        p_hr = p_plain

    # 3. OLS linear regression cross-check
    try:
        t_months = np.arange(n_pts, dtype=np.float64)
        lr = linregress(t_months, valid_vals)
        ols_slope = float(lr.slope * MONTHS_PER_DECADE)
        ols_p = float(lr.pvalue) if np.isfinite(lr.pvalue) else 1.0
    except Exception:
        ols_slope, ols_p = np.nan, np.nan

    # 4. Era break sign flip check (2000-2013 vs 2014-2025)
    era_flip = 0
    try:
        s_t1 = series[:n_t1]
        s_t2 = series[n_t1:]
        if not np.all(s_t1 == s_t1[0]) and not np.all(s_t2 == s_t2[0]):
            sl_t1 = mk.original_test(s_t1).slope
            sl_t2 = mk.original_test(s_t2).slope
            if sl_t1 != 0 and sl_t2 != 0:
                if np.sign(sl_t1) != np.sign(sl_t2):
                    era_flip = 1
    except Exception:
        pass

    return sens_slope, p_hr, p_plain, ols_slope, ols_p, era_flip


def _worker_batch(
    args: Tuple[np.ndarray, int],
) -> list[Tuple[float, float, float, float, float, int]]:
    """Worker function to process a batch of grid cells."""
    batch_series, n_t1 = args
    out = []
    for i in range(batch_series.shape[0]):
        out.append(compute_single_cell_metrics(batch_series[i], n_t1))
    return out


def run_hardened_trend_analysis() -> None:
    """Execute complete hardened trend estimation with 60° polar masking."""
    if not ANOMALIES_FILE.exists():
        raise FileNotFoundError(f"Missing input anomalies file: {ANOMALIES_FILE}")

    print(f"[*] Loading anomalies dataset from {ANOMALIES_FILE}...")
    ds = xr.open_dataset(ANOMALIES_FILE)
    anom_da = ds["precip_anomaly"]  # (time: 304, lat: 72, lon: 144)

    n_time, n_lat, n_lon = anom_da.shape
    total_cells = n_lat * n_lon
    lats = ds["lat"].values
    lons = ds["lon"].values

    # Determine index separating TRMM and GPM eras
    times = pd.to_datetime(ds["time"].values)
    n_t1 = int((times <= pd.Timestamp(ERA_BREAK_DATE)).sum())
    n_t2 = n_time - n_t1
    print(f"[*] Era partition: TRMM era (2000-2013) = {n_t1} months | GPM era (2014-2025) = {n_t2} months.")

    # Reshape spatial matrix to (total_cells, n_time)
    spatial_data = anom_da.values.transpose(1, 2, 0).reshape(total_cells, n_time)

    num_workers = min(os.cpu_count() or 4, 16)
    chunk_size = int(np.ceil(total_cells / (num_workers * 4)))
    chunks = [
        (spatial_data[i : i + chunk_size], n_t1)
        for i in range(0, total_cells, chunk_size)
    ]

    print(f"[*] Calculating Sen's slope, Hamed-Rao, plain MK, OLS, and era stability over {num_workers} processes...")
    t0 = time.time()

    raw_results = []
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        for batch_res in executor.map(_worker_batch, chunks):
            raw_results.extend(batch_res)

    elapsed = time.time() - t0
    print(f"[+] Finished cell-wise calculations in {elapsed:.2f}s ({(total_cells/elapsed):.1f} cells/s).")

    # Unpack 1D results
    sens_slope_1d = np.array([r[0] for r in raw_results], dtype=np.float32)
    p_val_hr_1d = np.array([r[1] for r in raw_results], dtype=np.float32)
    p_val_plain_1d = np.array([r[2] for r in raw_results], dtype=np.float32)
    ols_slope_1d = np.array([r[3] for r in raw_results], dtype=np.float32)
    ols_p_val_1d = np.array([r[4] for r in raw_results], dtype=np.float32)
    era_flip_1d = np.array([r[5] for r in raw_results], dtype=np.int8)

    # 4. Construct 60° Polar Mask (|lat| <= 60 is valid)
    lat_2d = np.repeat(lats[:, np.newaxis], n_lon, axis=1).flatten()
    valid_mask_1d = np.where(np.abs(lat_2d) <= 60.0, 1, 0).astype(np.int8)
    n_valid = int(valid_mask_1d.sum())
    n_masked = total_cells - n_valid
    print(f"[*] Polar mask: {n_valid:,} cells valid (|lat| <= 60°) | {n_masked:,} cells masked (|lat| > 60° ice sheets).")

    # 5. Multiple testing (Benjamini-Hochberg FDR)
    print("[*] Applying Benjamini-Hochberg FDR control across valid cells...")
    q_vals_1d = np.full_like(p_val_hr_1d, np.nan)
    valid_cells_idx = (valid_mask_1d == 1) & np.isfinite(p_val_hr_1d)
    
    q_vals_1d[valid_cells_idx] = false_discovery_control(p_val_hr_1d[valid_cells_idx], method="bh")

    # Significance masks (strictly zeroed poleward of 60°)
    sig_plain_1d = np.where((p_val_plain_1d < 0.05) & (valid_mask_1d == 1), 1, 0).astype(np.int8)
    sig_hr_1d = np.where((p_val_hr_1d < 0.05) & (valid_mask_1d == 1), 1, 0).astype(np.int8)
    sig_fdr_1d = np.where((q_vals_1d < 0.05) & (valid_mask_1d == 1), 1, 0).astype(np.int8)

    # 6. OLS vs Sen's slope sign agreement check
    non_zero = (sens_slope_1d != 0) & (ols_slope_1d != 0) & np.isfinite(sens_slope_1d) & np.isfinite(ols_slope_1d) & (valid_mask_1d == 1)
    sign_agree_1d = np.zeros(total_cells, dtype=np.int8)
    sign_agree_1d[non_zero] = np.where(np.sign(sens_slope_1d[non_zero]) == np.sign(ols_slope_1d[non_zero]), 1, 0)
    
    n_agree = int(sign_agree_1d[non_zero].sum())
    n_testable = int(non_zero.sum())
    pct_agree = (n_agree / n_testable) * 100 if n_testable > 0 else 0.0
    print(f"[+] OLS vs Sen's slope sign agreement: {n_agree:,} / {n_testable:,} valid cells ({pct_agree:.2f}%)")

    # Era sign flip share in valid domain
    valid_flips = int(era_flip_1d[valid_mask_1d == 1].sum())
    pct_flips = (valid_flips / n_valid) * 100 if n_valid > 0 else 0.0
    print(f"[+] Global era sign flips (2000-2013 vs 2014-2025): {valid_flips:,} / {n_valid:,} valid cells ({pct_flips:.1f}%)")

    # Reshape arrays to 2D (72, 144)
    sens_slope_2d = sens_slope_1d.reshape(n_lat, n_lon)
    p_val_hr_2d = p_val_hr_1d.reshape(n_lat, n_lon)
    p_val_plain_2d = p_val_plain_1d.reshape(n_lat, n_lon)
    q_vals_2d = q_vals_1d.reshape(n_lat, n_lon)
    sig_fdr_2d = sig_fdr_1d.reshape(n_lat, n_lon)
    sig_hr_2d = sig_hr_1d.reshape(n_lat, n_lon)
    sig_plain_2d = sig_plain_1d.reshape(n_lat, n_lon)
    valid_mask_2d = valid_mask_1d.reshape(n_lat, n_lon)
    era_flip_2d = era_flip_1d.reshape(n_lat, n_lon)
    ols_slope_2d = ols_slope_1d.reshape(n_lat, n_lon)
    ols_p_val_2d = ols_p_val_1d.reshape(n_lat, n_lon)
    sign_agree_2d = sign_agree_1d.reshape(n_lat, n_lon)

    # Construct hardened dataset
    ds_trend = xr.Dataset(
        data_vars={
            "sens_slope": (
                ("lat", "lon"),
                sens_slope_2d,
                {
                    "units": "mm/month/decade",
                    "long_name": "Sen's Slope Trend in Monthly Precipitation",
                    "description": "Linear trend from Sen's slope estimator (per-month slope * 120).",
                },
            ),
            "p_value": (
                ("lat", "lon"),
                p_val_hr_2d,
                {
                    "units": "1",
                    "long_name": "Hamed-Rao Modified Mann-Kendall p-value",
                    "description": "Autocorrelation-corrected two-sided p-value accounting for lag autocorrelation.",
                    "valid_range": [0.0, 1.0],
                },
            ),
            "p_value_plain": (
                ("lat", "lon"),
                p_val_plain_2d,
                {
                    "units": "1",
                    "long_name": "Plain Mann-Kendall p-value (uncorrected)",
                    "description": "Standard two-sided Mann-Kendall p-value without autocorrelation correction.",
                    "valid_range": [0.0, 1.0],
                },
            ),
            "q_value": (
                ("lat", "lon"),
                q_vals_2d,
                {
                    "units": "1",
                    "long_name": "Benjamini-Hochberg False Discovery Rate q-value",
                    "description": "FDR adjusted p-value derived from Hamed-Rao modified p-values across valid cells.",
                    "valid_range": [0.0, 1.0],
                },
            ),
            "valid": (
                ("lat", "lon"),
                valid_mask_2d,
                {
                    "units": "1",
                    "long_name": "Valid Retrieval Mask",
                    "description": "1 = valid low-and-mid latitudes (|lat| <= 60 deg); 0 = masked poleward of 60 deg due to unreliable retrievals over ice.",
                    "flag_values": [0, 1],
                },
            ),
            "significant_fdr": (
                ("lat", "lon"),
                sig_fdr_2d,
                {
                    "units": "1",
                    "long_name": "FDR Significance Flag (q < 0.05)",
                    "description": "1 if significant under Benjamini-Hochberg FDR control at q < 0.05 and within valid mask; 0 otherwise.",
                    "flag_values": [0, 1],
                },
            ),
            "significant_modified": (
                ("lat", "lon"),
                sig_hr_2d,
                {
                    "units": "1",
                    "long_name": "Autocorrelation-Aware Significance Flag (p < 0.05)",
                    "description": "1 if significant under Hamed-Rao test at p < 0.05 and within valid mask; 0 otherwise.",
                    "flag_values": [0, 1],
                },
            ),
            "significant_plain": (
                ("lat", "lon"),
                sig_plain_2d,
                {
                    "units": "1",
                    "long_name": "Plain Mann-Kendall Significance Flag (p < 0.05)",
                    "description": "1 if significant under standard plain MK test at p < 0.05 and within valid mask; 0 otherwise.",
                    "flag_values": [0, 1],
                },
            ),
            "era_sign_flip": (
                ("lat", "lon"),
                era_flip_2d,
                {
                    "units": "1",
                    "long_name": "TRMM-GPM Era Sign Flip Indicator",
                    "description": "1 if trend sign differs between 2000-2013 and 2014-2025; 0 if consistent sign.",
                    "flag_values": [0, 1],
                },
            ),
            "ols_slope": (
                ("lat", "lon"),
                ols_slope_2d,
                {
                    "units": "mm/month/decade",
                    "long_name": "Ordinary Least Squares Linear Trend",
                    "description": "Parametric OLS regression slope (per-month slope * 120).",
                },
            ),
            "ols_p_value": (
                ("lat", "lon"),
                ols_p_val_2d,
                {
                    "units": "1",
                    "long_name": "OLS Linear Regression p-value",
                    "description": "Two-sided t-test p-value for OLS slope parameter.",
                    "valid_range": [0.0, 1.0],
                },
            ),
            "slope_sign_agreement": (
                ("lat", "lon"),
                sign_agree_2d,
                {
                    "units": "1",
                    "long_name": "Sign Agreement between OLS and Sen's Slope",
                    "description": "1 if OLS and Sen's slope share the same sign (+ or -), 0 otherwise.",
                    "flag_values": [0, 1],
                },
            ),
        },
        coords={
            "lat": ds["lat"],
            "lon": ds["lon"],
        },
        attrs={
            "title": "GPM IMERG V07 Precipitation Trends (2000-2025)",
            "source": "NASA GPM IMERG Final Monthly V07",
            "statistical_hardening": "Hamed-Rao autocorrelation correction, Benjamini-Hochberg FDR control, OLS cross-validation, 60° polar mask",
            "slope_conversion": "per-month Sen's slope * 120 = mm/month per decade",
            "period": f"{str(ds['time'].values[0])[:10]} to {str(ds['time'].values[-1])[:10]}",
            "created_at": datetime.utcnow().isoformat(),
            "conventions": "CF-1.8",
        },
    )

    print(f"[*] Writing updated trend dataset to {TREND_FILE}...")
    encoding = {var: {"zlib": True, "complevel": 4} for var in ds_trend.data_vars}
    ds_trend.to_netcdf(TREND_FILE, encoding=encoding)
    ds.close()

    print(f"[+] Successfully wrote {TREND_FILE} ({TREND_FILE.stat().st_size / 1024:.1f} KB)")


def main() -> int:
    try:
        run_hardened_trend_analysis()
        return 0
    except Exception as exc:
        print(f"[-] Trend calculation failed: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
