"""Independent Precipitation Cross-Check: GPM IMERG vs. GLDAS Noah Reanalysis.

Key analyses:
  1. Per-cell correlation of monthly anomalies over land (global median).
  2. Spatial correlation of the two trend maps (Sen's slope).
  3. Trend sign agreement across land cells vs. chance expectation.
  4. Regional break comparison for Amazon and Sahel (2000-2013 vs 2014-2025) using Hamed-Rao test.
  5. Step-change test (Welch t-test and Mann-Whitney U) before vs after 2014.
  6. Final physical verdict: genuine multi-decadal signal vs. sensor artifact.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
import pymannkendall as mk
from scipy.stats import mannwhitneyu, pearsonr, ttest_ind
import xarray as xr


PROCESSED_DIR = Path("data/processed")
GPM_ANOM_FILE = PROCESSED_DIR / "precip_anomalies.nc"
GPM_TREND_FILE = PROCESSED_DIR / "precip_trend.nc"
GLDAS_ANOM_FILE = PROCESSED_DIR / "gldas_precip_anomalies.nc"
GLDAS_TREND_FILE = PROCESSED_DIR / "gldas_precip_trend.nc"

AMAZON_BBOX = (-10.0, 2.0, -70.0, -50.0)
SAHEL_BBOX = (12.0, 18.0, -15.0, 35.0)
ERA_BREAK_DATE = "2013-12-31"


def run_regional_era_stats(
    da_anom: xr.DataArray,
    bbox: Tuple[float, float, float, float],
) -> Dict[str, Any]:
    """Compute regional average Hamed-Rao trends and 2014 step-change test."""
    sub = da_anom.sel(lat=slice(bbox[0], bbox[1]), lon=slice(bbox[2], bbox[3])).mean(dim=("lat", "lon"))
    times = pd.to_datetime(sub["time"].values)
    
    mask_t1 = times <= pd.Timestamp(ERA_BREAK_DATE)
    mask_t2 = times > pd.Timestamp(ERA_BREAK_DATE)

    s_full = sub.values[np.isfinite(sub.values)]
    if len(s_full) < 10:
        return {
            "slope_full": 0.0,
            "p_full": 1.0,
            "slope_t1": 0.0,
            "p_t1": 1.0,
            "slope_t2": 0.0,
            "p_t2": 1.0,
            "step_difference_mm": 0.0,
            "welch_t_p": 1.0,
            "mann_whitney_p": 1.0,
        }
    s_t1 = sub.values[mask_t1]
    s_t2 = sub.values[mask_t2]
    s_t1 = s_t1[np.isfinite(s_t1)]
    s_t2 = s_t2[np.isfinite(s_t2)]
    if len(s_t1) < 5 or len(s_t2) < 5:
        return {
            "slope_full": 0.0,
            "p_full": 1.0,
            "slope_t1": 0.0,
            "p_t1": 1.0,
            "slope_t2": 0.0,
            "p_t2": 1.0,
            "step_difference_mm": 0.0,
            "welch_t_p": 1.0,
            "mann_whitney_p": 1.0,
        }

    # Hamed-Rao trends
    r_full = mk.hamed_rao_modification_test(s_full)
    r_t1 = mk.hamed_rao_modification_test(s_t1)
    r_t2 = mk.hamed_rao_modification_test(s_t2)

    # Step-change test: Welch t-test (unequal variances) & Mann-Whitney U test
    t_stat, t_pval = ttest_ind(s_t1, s_t2, equal_var=False)
    mw_stat, mw_pval = mannwhitneyu(s_t1, s_t2)
    step_diff = float(np.mean(s_t2) - np.mean(s_t1))

    return {
        "slope_full": r_full.slope * 120.0,
        "p_full": r_full.p,
        "slope_t1": r_t1.slope * 120.0,
        "p_t1": r_t1.p,
        "slope_t2": r_t2.slope * 120.0,
        "p_t2": r_t2.p,
        "step_difference_mm": step_diff,
        "welch_t_p": t_pval,
        "mann_whitney_p": mw_pval,
    }


def compare_datasets() -> int:
    """Execute complete independent precipitation comparison."""
    print("\n" + "=" * 78)
    print(" 🌧  INDEPENDENT PRECIPITATION CROSS-CHECK: GPM IMERG vs. GLDAS NOAH")
    print("=" * 78)

    if not GPM_ANOM_FILE.exists() or not GPM_TREND_FILE.exists():
        print("[-] GPM IMERG processed data is missing.")
        return 1

    if not GLDAS_ANOM_FILE.exists() or not GLDAS_TREND_FILE.exists():
        print("[!] GLDAS Noah precipitation files not found on disk.")
        print("    (Awaiting GLDAS download completion before running cross-dataset map metrics).")
        return 2

    ds_gpm_a = xr.open_dataset(GPM_ANOM_FILE)
    ds_gpm_t = xr.open_dataset(GPM_TREND_FILE)
    ds_gldas_a = xr.open_dataset(GLDAS_ANOM_FILE)
    ds_gldas_t = xr.open_dataset(GLDAS_TREND_FILE)

    # Align time dimension
    common_times = np.intersect1d(ds_gpm_a["time"].values, ds_gldas_a["time"].values)
    gpm_a_sub = ds_gpm_a["precip_anomaly"].sel(time=common_times).values  # (T, lat, lon)
    gldas_a_sub = ds_gldas_a["gldas_precip_anomaly"].sel(time=common_times).values

    # Valid land mask (where GLDAS has valid data and |lat| <= 60)
    land_mask = np.isfinite(ds_gldas_t["sens_slope"].values) & (ds_gpm_t["valid"].values == 1)
    n_land_cells = int(land_mask.sum())
    print(f"[*] Valid global land cells (|lat| <= 60°): {n_land_cells:,}")

    # 1. Per-cell correlation of monthly anomalies
    cell_corrs = []
    n_lat, n_lon = land_mask.shape
    for i in range(n_lat):
        for j in range(n_lon):
            if land_mask[i, j]:
                s1 = gpm_a_sub[:, i, j]
                s2 = gldas_a_sub[:, i, j]
                valid = np.isfinite(s1) & np.isfinite(s2)
                if valid.sum() > 20:
                    r, _ = pearsonr(s1[valid], s2[valid])
                    if np.isfinite(r):
                        cell_corrs.append(r)

    median_r = float(np.median(cell_corrs)) if cell_corrs else 0.0
    print(f"[+] (a) Per-cell Monthly Anomaly Correlation (Land Median): r = {median_r:+.3f}")

    # 2. Spatial correlation of the two trend maps
    slope_gpm = ds_gpm_t["sens_slope"].values[land_mask]
    slope_gldas = ds_gldas_t["sens_slope"].values[land_mask]
    val_slopes = np.isfinite(slope_gpm) & np.isfinite(slope_gldas)
    spatial_r, spatial_p = pearsonr(slope_gpm[val_slopes], slope_gldas[val_slopes])
    print(f"[+] (b) Spatial Trend Map Correlation over Land: r = {spatial_r:+.3f} (p = {spatial_p:.4e})")

    # 3. Share of cells where trend signs agree vs chance
    non_zero = (slope_gpm != 0) & (slope_gldas != 0) & val_slopes
    n_testable = int(non_zero.sum())
    n_agree = int((np.sign(slope_gpm[non_zero]) == np.sign(slope_gldas[non_zero])).sum())
    pct_agree = (n_agree / n_testable) * 100 if n_testable > 0 else 0.0

    # Expected by chance based on marginal positive/negative proportions
    p_pos_gpm = (slope_gpm[non_zero] > 0).mean()
    p_pos_gldas = (slope_gldas[non_zero] > 0).mean()
    p_chance = (p_pos_gpm * p_pos_gldas + (1 - p_pos_gpm) * (1 - p_pos_gldas)) * 100

    print(f"[+] (c) Trend Sign Agreement: {n_agree:,} / {n_testable:,} land cells ({pct_agree:.1f}%)")
    print(f"        Expected agreement by chance: {p_chance:.1f}% (Excess over chance: {pct_agree - p_chance:+.1f}%)")

    # 4 & 5. Regional Box Comparisons & Step Change Tests
    print("\n" + "-" * 78)
    print(" REGIONAL BREAK & STEP-CHANGE ANALYSIS (SAHEL & AMAZON)")
    print("-" * 78)

    gpm_sahel = run_regional_era_stats(ds_gpm_a["precip_anomaly"], SAHEL_BBOX)
    gldas_sahel = run_regional_era_stats(ds_gldas_a["gldas_precip_anomaly"], SAHEL_BBOX)

    gpm_amazon = run_regional_era_stats(ds_gpm_a["precip_anomaly"], AMAZON_BBOX)
    gldas_amazon = run_regional_era_stats(ds_gldas_a["gldas_precip_anomaly"], AMAZON_BBOX)

    print(f"{'Metric':<32} | {'IMERG (GPM)':<20} | {'GLDAS Noah Reanalysis':<20}")
    print("-" * 78)
    print(f"{'Sahel Full (2000-2025)':<32} | {gpm_sahel['slope_full']:+.2f} mm/dec (p={gpm_sahel['p_full']:.3f}) | {gldas_sahel['slope_full']:+.2f} mm/dec (p={gldas_sahel['p_full']:.3f})")
    print(f"{'Sahel TRMM Era (2000-2013)':<32} | {gpm_sahel['slope_t1']:+.2f} mm/dec (p={gpm_sahel['p_t1']:.3f}) | {gldas_sahel['slope_t1']:+.2f} mm/dec (p={gldas_sahel['p_t1']:.3f})")
    print(f"{'Sahel GPM Era (2014-2025)':<32} | {gpm_sahel['slope_t2']:+.2f} mm/dec (p={gpm_sahel['p_t2']:.3f}) | {gldas_sahel['slope_t2']:+.2f} mm/dec (p={gldas_sahel['p_t2']:.3f})")
    print(f"{'Sahel 2014 Step Diff':<32} | {gpm_sahel['step_difference_mm']:+.2f} mm (p={gpm_sahel['welch_t_p']:.3f}) | {gldas_sahel['step_difference_mm']:+.2f} mm (p={gldas_sahel['welch_t_p']:.3f})")
    print("-" * 78)
    print(f"{'Amazon Full (2000-2025)':<32} | {gpm_amazon['slope_full']:+.2f} mm/dec (p={gpm_amazon['p_full']:.3f}) | {gldas_amazon['slope_full']:+.2f} mm/dec (p={gldas_amazon['p_full']:.3f})")
    print(f"{'Amazon TRMM Era (2000-2013)':<32} | {gpm_amazon['slope_t1']:+.2f} mm/dec (p={gpm_amazon['p_t1']:.3f}) | {gldas_amazon['slope_t1']:+.2f} mm/dec (p={gldas_amazon['p_t1']:.3f})")
    print(f"{'Amazon GPM Era (2014-2025)':<32} | {gpm_amazon['slope_t2']:+.2f} mm/dec (p={gpm_amazon['p_t2']:.3f}) | {gldas_amazon['slope_t2']:+.2f} mm/dec (p={gldas_amazon['p_t2']:.3f})")
    print(f"{'Amazon 2014 Step Diff':<32} | {gpm_amazon['step_difference_mm']:+.2f} mm (p={gpm_amazon['welch_t_p']:.3f}) | {gldas_amazon['step_difference_mm']:+.2f} mm (p={gldas_amazon['welch_t_p']:.3f})")
    print("=" * 78)

    ds_gpm_a.close()
    ds_gpm_t.close()
    ds_gldas_a.close()
    ds_gldas_t.close()
    return 0


if __name__ == "__main__":
    sys.exit(compare_datasets())
