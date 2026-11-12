"""Generic Trend Estimation Engine for Plot Twist.

Computes hardened statistical trends for any processed anomaly file:
  - Sen's slope (scaled to variable units per decade: per-month * 120)
  - Hamed-Rao autocorrelation-corrected Mann-Kendall p-value
  - Plain Mann-Kendall p-value
  - Benjamini-Hochberg False Discovery Rate (FDR) control at q < 0.05
  - Polar mask: cells poleward of 60° masked (valid=0, significance flags zeroed)
  - Parametric OLS regression cross-check and sign agreement
  - Sensor era split (2000-2013 vs 2014-2025) stability flag ('era_sign_flip')

Saves to: data/processed/{var_id}_trend.nc
"""

from __future__ import annotations

import argparse
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

from variables import VARIABLES, VariableConfig


PROCESSED_DIR = Path("data/processed")
MONTHS_PER_DECADE = 120.0
ERA_BREAK_DATE = "2013-12-31"


def compute_single_cell_metrics(
    series: np.ndarray,
    n_t1: int,
) -> Tuple[float, float, float, float, float, int]:
    """Compute trend metrics and era sign stability for a single grid cell."""
    valid_mask = np.isfinite(series)
    valid_vals = series[valid_mask]
    n_pts = len(valid_vals)

    if n_pts < 10:
        return np.nan, np.nan, np.nan, np.nan, np.nan, 0

    if np.all(valid_vals == valid_vals[0]):
        return 0.0, 1.0, 1.0, 0.0, 1.0, 0

    # 1. Plain MK & Sen's slope
    try:
        res_plain = mk.original_test(valid_vals)
        sens_slope = float(res_plain.slope * MONTHS_PER_DECADE)
        p_plain = float(res_plain.p)
    except Exception:
        sens_slope, p_plain = np.nan, np.nan

    # 2. Hamed-Rao modified MK
    try:
        res_hr = mk.hamed_rao_modification_test(valid_vals)
        p_hr = float(res_hr.p)
    except Exception:
        p_hr = p_plain

    # 3. OLS linear regression
    try:
        t_months = np.arange(n_pts, dtype=np.float64)
        lr = linregress(t_months, valid_vals)
        ols_slope = float(lr.slope * MONTHS_PER_DECADE)
        ols_p = float(lr.pvalue) if np.isfinite(lr.pvalue) else 1.0
    except Exception:
        ols_slope, ols_p = np.nan, np.nan

    # 4. Era sign flip check (2000-2013 vs 2014-2025)
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


def _worker_batch(args: Tuple[np.ndarray, int]) -> list[Tuple[float, float, float, float, float, int]]:
    batch_series, n_t1 = args
    out = []
    for i in range(batch_series.shape[0]):
        out.append(compute_single_cell_metrics(batch_series[i], n_t1))
    return out


def run_trend_for_variable(var_id: str) -> Path:
    """Execute complete trend calculation for a specified variable."""
    var_cfg = VARIABLES.get(var_id)
    var_name = var_cfg.name if var_cfg else var_id
    unit = var_cfg.units if var_cfg else "units"

    anom_file = PROCESSED_DIR / f"{var_id}_anomalies.nc"
    if not anom_file.exists() and var_id == "gpm_precip":
        anom_file = PROCESSED_DIR / "precip_anomalies.nc"

    if not anom_file.exists():
        raise FileNotFoundError(f"Missing anomalies file for {var_id}: {anom_file}")

    print(f"\n[*] Calculating trends for '{var_name}' ({var_id})...")
    ds = xr.open_dataset(anom_file)

    # Find the anomaly variable in dataset
    da_name = None
    for k in ds.data_vars:
        if "anomaly" in k:
            da_name = k
            break
    if not da_name:
        da_name = list(ds.data_vars.keys())[0]

    anom_da = ds[da_name]
    n_time, n_lat, n_lon = anom_da.shape
    total_cells = n_lat * n_lon
    lats = ds["lat"].values
    lons = ds["lon"].values

    times = pd.to_datetime(ds["time"].values)
    n_t1 = int((times <= pd.Timestamp(ERA_BREAK_DATE)).sum())
    n_t2 = n_time - n_t1

    spatial_data = anom_da.values.transpose(1, 2, 0).reshape(total_cells, n_time)
    num_workers = min(os.cpu_count() or 4, 16)
    chunk_size = int(np.ceil(total_cells / (num_workers * 4)))
    chunks = [
        (spatial_data[i : i + chunk_size], n_t1)
        for i in range(0, total_cells, chunk_size)
    ]

    t0 = time.time()
    raw_results = []
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        for batch_res in executor.map(_worker_batch, chunks):
            raw_results.extend(batch_res)

    sens_slope_1d = np.array([r[0] for r in raw_results], dtype=np.float32)
    p_val_hr_1d = np.array([r[1] for r in raw_results], dtype=np.float32)
    p_val_plain_1d = np.array([r[2] for r in raw_results], dtype=np.float32)
    ols_slope_1d = np.array([r[3] for r in raw_results], dtype=np.float32)
    ols_p_val_1d = np.array([r[4] for r in raw_results], dtype=np.float32)
    era_flip_1d = np.array([r[5] for r in raw_results], dtype=np.int8)

    # Valid domain: Polar mask (|lat| <= 60) AND finite data (land-mask for GLDAS)
    lat_2d = np.repeat(lats[:, np.newaxis], n_lon, axis=1).flatten()
    valid_mask_1d = np.where((np.abs(lat_2d) <= 60.0) & np.isfinite(sens_slope_1d), 1, 0).astype(np.int8)
    n_valid = int(valid_mask_1d.sum())

    # FDR Control
    q_vals_1d = np.full_like(p_val_hr_1d, np.nan)
    valid_cells_idx = (valid_mask_1d == 1) & np.isfinite(p_val_hr_1d)
    q_vals_1d[valid_cells_idx] = false_discovery_control(p_val_hr_1d[valid_cells_idx], method="bh")

    sig_plain_1d = np.where((p_val_plain_1d < 0.05) & (valid_mask_1d == 1), 1, 0).astype(np.int8)
    sig_hr_1d = np.where((p_val_hr_1d < 0.05) & (valid_mask_1d == 1), 1, 0).astype(np.int8)
    sig_fdr_1d = np.where((q_vals_1d < 0.05) & (valid_mask_1d == 1), 1, 0).astype(np.int8)
    hr_nan_1d = np.where((valid_mask_1d == 1) & np.isnan(p_val_hr_1d), 1, 0).astype(np.int8)

    # Spatial cluster significance: FDR-significant and >= 3 of 8 neighbors have same sign
    cluster_sig_2d = np.zeros((n_lat, n_lon), dtype=np.int8)
    slopes_2d = sens_slope_1d.reshape(n_lat, n_lon)
    valid_2d = valid_mask_1d.reshape(n_lat, n_lon)
    sig_fdr_2d = sig_fdr_1d.reshape(n_lat, n_lon)

    for i in range(n_lat):
        for j in range(n_lon):
            if valid_2d[i, j] == 1 and sig_fdr_2d[i, j] == 1:
                cell_sign = np.sign(slopes_2d[i, j])
                if cell_sign == 0 or np.isnan(cell_sign):
                    continue
                same_sign_count = 0
                for di in [-1, 0, 1]:
                    for dj in [-1, 0, 1]:
                        if di == 0 and dj == 0:
                            continue
                        ni = i + di
                        nj = (j + dj) % n_lon
                        if 0 <= ni < n_lat:
                            if valid_2d[ni, nj] == 1 and np.isfinite(slopes_2d[ni, nj]):
                                if np.sign(slopes_2d[ni, nj]) == cell_sign:
                                    same_sign_count += 1
                if same_sign_count >= 3:
                    cluster_sig_2d[i, j] = 1

    cluster_sig_1d = cluster_sig_2d.flatten()
    n_cluster = int(cluster_sig_1d[valid_mask_1d == 1].sum())
    pct_cluster = (n_cluster / n_valid) * 100 if n_valid > 0 else 0.0

    # Sign agreement
    non_zero = (sens_slope_1d != 0) & (ols_slope_1d != 0) & np.isfinite(sens_slope_1d) & np.isfinite(ols_slope_1d) & (valid_mask_1d == 1)
    sign_agree_1d = np.zeros(total_cells, dtype=np.int8)
    sign_agree_1d[non_zero] = np.where(np.sign(sens_slope_1d[non_zero]) == np.sign(ols_slope_1d[non_zero]), 1, 0)

    # Reporting
    n_agree = int(sign_agree_1d[non_zero].sum())
    n_testable = int(non_zero.sum())
    pct_agree = (n_agree / n_testable) * 100 if n_testable > 0 else 0.0
    valid_flips = int(era_flip_1d[valid_mask_1d == 1].sum())
    pct_flips = (valid_flips / n_valid) * 100 if n_valid > 0 else 0.0

    n_fdr = int(sig_fdr_1d.sum())
    n_hr = int(sig_hr_1d.sum())
    n_pl = int(sig_plain_1d.sum())

    print(f"[+] Completed {var_name} trend in {time.time() - t0:.2f}s:")
    print(f"    - Plain MK Significant        : {n_pl:,} / {n_valid:,} ({n_pl/n_valid*100:.1f}%)")
    print(f"    - Autocorrelation-Aware (HR)  : {n_hr:,} / {n_valid:,} ({n_hr/n_valid*100:.1f}%)")
    print(f"    - FDR-Corrected (q < 0.05)    : {n_fdr:,} / {n_valid:,} ({n_fdr/n_valid*100:.1f}%)")
    print(f"    - Cluster-Significant (>=3)   : {n_cluster:,} / {n_valid:,} ({pct_cluster:.1f}%)")
    print(f"    - OLS vs Sen Sign Agreement   : {pct_agree:.1f}%")
    print(f"    - Era Sign Flip (2000-13/14-25): {valid_flips:,} ({pct_flips:.1f}%)")

    # Reshape and save
    out_trend_file = PROCESSED_DIR / f"{var_id}_trend.nc"
    ds_trend = xr.Dataset(
        data_vars={
            "sens_slope": (("lat", "lon"), sens_slope_1d.reshape(n_lat, n_lon), {"units": f"{unit}/decade"}),
            "p_value": (("lat", "lon"), p_val_hr_1d.reshape(n_lat, n_lon), {"units": "1"}),
            "p_value_plain": (("lat", "lon"), p_val_plain_1d.reshape(n_lat, n_lon), {"units": "1"}),
            "q_value": (("lat", "lon"), q_vals_1d.reshape(n_lat, n_lon), {"units": "1"}),
            "valid": (("lat", "lon"), valid_mask_1d.reshape(n_lat, n_lon), {"units": "1"}),
            "significant_fdr": (("lat", "lon"), sig_fdr_1d.reshape(n_lat, n_lon), {"units": "1"}),
            "cluster_significant": (("lat", "lon"), cluster_sig_2d, {"units": "1", "description": "FDR significant with >=3 neighbors same sign"}),
            "significant_modified": (("lat", "lon"), sig_hr_1d.reshape(n_lat, n_lon), {"units": "1"}),
            "significant_plain": (("lat", "lon"), sig_plain_1d.reshape(n_lat, n_lon), {"units": "1"}),
            "hr_nan": (("lat", "lon"), hr_nan_1d.reshape(n_lat, n_lon), {"units": "1", "description": "1 if Hamed-Rao p-value underflowed to NaN"}),
            "era_sign_flip": (("lat", "lon"), era_flip_1d.reshape(n_lat, n_lon), {"units": "1"}),
            "ols_slope": (("lat", "lon"), ols_slope_1d.reshape(n_lat, n_lon), {"units": f"{unit}/decade"}),
            "ols_p_value": (("lat", "lon"), ols_p_val_1d.reshape(n_lat, n_lon), {"units": "1"}),
            "slope_sign_agreement": (("lat", "lon"), sign_agree_1d.reshape(n_lat, n_lon), {"units": "1"}),
        },
        coords={"lat": lats, "lon": lons},
        attrs={
            "variable_id": var_id,
            "variable_name": var_name,
            "units": f"{unit}/decade",
            "created_at": datetime.utcnow().isoformat(),
        },
    )

    encoding = {v: {"zlib": True, "complevel": 4} for v in ds_trend.data_vars}
    ds_trend.to_netcdf(out_trend_file, encoding=encoding)
    ds.close()

    # Backwards compatibility symlink/copy for precip_trend.nc
    if var_id == "gpm_precip":
        compat_file = PROCESSED_DIR / "precip_trend.nc"
        import shutil
        shutil.copy(out_trend_file, compat_file)

    print(f"[+] Successfully wrote {out_trend_file} ({out_trend_file.stat().st_size / 1024:.1f} KB)")
    return out_trend_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Generic trend estimator for Plot Twist.")
    parser.add_argument("var_id", default="gpm_precip", nargs="?", help="Variable ID (default: gpm_precip)")
    args = parser.parse_args()

    run_trend_for_variable(args.var_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
