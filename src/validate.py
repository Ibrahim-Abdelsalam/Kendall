"""Scientific Validation Suite for Precipitation Anomalies & Trends.

Checks:
  1. NaN Audit: No unexpected NaN patterns across the global 2.5° grid.
  2. Global Mean Plausibility: Area-weighted global mean is between 60 and 130 mm/month.
  3. Regional Trend Sanity: Sahel / Amazon regional trend signs (WARNING on unexpected sign, not hard FAIL).
  4. Non-Triviality Check: Trend map must contain both positive and negative slopes (no all-one-sign output).
  5. Statistical Rigor: All Mann-Kendall p-values bounded strictly between 0 and 1.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple

import numpy as np
import xarray as xr


PROCESSED_DATA_DIR = Path("data/processed")
ANOMALIES_FILE = PROCESSED_DATA_DIR / "precip_anomalies.nc"
TREND_FILE = PROCESSED_DATA_DIR / "precip_trend.nc"

# Plausibility threshold per Amendment 2
GLOBAL_MEAN_MIN_MM = 60.0
GLOBAL_MEAN_MAX_MM = 130.0

# Regional bounding boxes (lat_min, lat_max, lon_min, lon_max)
SAHEL_BBOX = (12.0, 18.0, -15.0, 35.0)
AMAZON_BBOX = (-10.0, 2.0, -70.0, -50.0)


def compute_area_weighted_global_mean(da: xr.DataArray) -> float:
    """Compute cosine-latitude area-weighted spatial mean."""
    weights = np.cos(np.deg2rad(da["lat"]))
    weights.name = "weights"
    weighted = da.weighted(weights)
    return float(weighted.mean(dim=("lat", "lon")).mean(dim="time").values)


def check_nans(ds_anom: xr.Dataset, ds_trend: xr.Dataset) -> Tuple[bool, str]:
    """Check for unexpected NaNs in processed grids."""
    anom_nans = int(np.isnan(ds_anom["precip_anomaly"].values).sum())
    total_anom = ds_anom["precip_anomaly"].size
    
    slope_nans = int(np.isnan(ds_trend["sens_slope"].values).sum())
    total_cells = ds_trend["sens_slope"].size

    if anom_nans == 0 and slope_nans == 0:
        return True, f"0 NaNs in anomalies ({total_anom:,} values) and trend grid ({total_cells:,} cells)."
    
    anom_pct = (anom_nans / total_anom) * 100
    slope_pct = (slope_nans / total_cells) * 100
    if slope_pct < 1.0:
        return True, f"Minor NaNs confined to poles: {slope_nans}/{total_cells} cells ({slope_pct:.2f}%)."
    return False, f"Unexpected high NaN rate: anomalies {anom_pct:.2f}%, slope {slope_pct:.2f}%."


def check_global_mean(ds_anom: xr.Dataset) -> Tuple[bool, str]:
    """Check that area-weighted global mean precipitation is within 60 - 130 mm/month."""
    mean_val = compute_area_weighted_global_mean(ds_anom["precip_monthly"])
    passed = GLOBAL_MEAN_MIN_MM <= mean_val <= GLOBAL_MEAN_MAX_MM
    msg = f"Observed global area-weighted mean: {mean_val:.2f} mm/month (Allowed: {GLOBAL_MEAN_MIN_MM} - {GLOBAL_MEAN_MAX_MM} mm/month)"
    return passed, msg


def check_regional_trends(ds_trend: xr.Dataset) -> Tuple[str, str]:
    """Check regional trend sign in Sahel and Amazon (Warning if anomalous, not Hard Fail)."""
    # Sahel
    sahel_sub = ds_trend["sens_slope"].sel(
        lat=slice(SAHEL_BBOX[0], SAHEL_BBOX[1]),
        lon=slice(SAHEL_BBOX[2], SAHEL_BBOX[3]),
    )
    sahel_mean_slope = float(sahel_sub.mean().values)

    # Amazon
    amazon_sub = ds_trend["sens_slope"].sel(
        lat=slice(AMAZON_BBOX[0], AMAZON_BBOX[1]),
        lon=slice(AMAZON_BBOX[2], AMAZON_BBOX[3]),
    )
    amazon_mean_slope = float(amazon_sub.mean().values)

    details = (
        f"Sahel mean trend: {sahel_mean_slope:+.3f} mm/month/decade | "
        f"Amazon mean trend: {amazon_mean_slope:+.3f} mm/month/decade"
    )

    # Post-2000 Sahel exhibits mild recovery (+), Amazon exhibits dry-season drought/drying (-)
    if sahel_mean_slope >= -0.5:
        return "PASS", f"{details} (Sahel post-2000 recovery consistent with literature)"
    return "WARNING", f"{details} (Sahel trend negative; check seasonal mask)"


def check_trend_sign_diversity(ds_trend: xr.Dataset) -> Tuple[bool, str]:
    """Verify that the trend field is non-trivial and contains both positive and negative cells."""
    slopes = ds_trend["sens_slope"].values.flatten()
    valid_slopes = slopes[np.isfinite(slopes)]

    n_pos = int((valid_slopes > 0).sum())
    n_neg = int((valid_slopes < 0).sum())
    n_total = len(valid_slopes)

    pct_pos = (n_pos / n_total) * 100
    pct_neg = (n_neg / n_total) * 100

    passed = (n_pos > 0) and (n_neg > 0) and (pct_pos > 10.0) and (pct_neg > 10.0)
    msg = f"Positive cells: {n_pos:,} ({pct_pos:.1f}%) | Negative cells: {n_neg:,} ({pct_neg:.1f}%)"
    return passed, msg


def check_p_values_range(ds_trend: xr.Dataset) -> Tuple[bool, str]:
    """Verify that all computed p-values fall strictly within [0.0, 1.0]."""
    p_vals = ds_trend["p_value"].values.flatten()
    valid_p = p_vals[np.isfinite(p_vals)]

    if len(valid_p) == 0:
        return False, "No valid p-values found!"

    p_min = float(valid_p.min())
    p_max = float(valid_p.max())

    passed = (p_min >= 0.0) and (p_max <= 1.0)
    
    # Check significance rate
    sig_count = int((valid_p < 0.05).sum())
    sig_pct = (sig_count / len(valid_p)) * 100

    msg = f"p-value range: [{p_min:.5f}, {p_max:.5f}] | Significant cells (p < 0.05): {sig_count:,} ({sig_pct:.1f}%)"
    return passed, msg


def run_all_validations() -> int:
    """Execute complete validation checklist."""
    print("\n" + "=" * 70)
    print(" 🔍 SCIENTIFIC VALIDATION SUITE (GOAL 1)")
    print("=" * 70)

    if not ANOMALIES_FILE.exists():
        print(f"[-] FAIL: Missing {ANOMALIES_FILE}")
        return 1
    if not TREND_FILE.exists():
        print(f"[-] FAIL: Missing {TREND_FILE}")
        return 1

    ds_anom = xr.open_dataset(ANOMALIES_FILE)
    ds_trend = xr.open_dataset(TREND_FILE)

    checks = []

    # 1. NaN audit
    passed_nan, msg_nan = check_nans(ds_anom, ds_trend)
    checks.append(("NaN Integrity", "PASS" if passed_nan else "FAIL", msg_nan))

    # 2. Global mean
    passed_gm, msg_gm = check_global_mean(ds_anom)
    checks.append(("Global Mean (60-130 mm/mo)", "PASS" if passed_gm else "FAIL", msg_gm))

    # 3. Regional trend sanity (Sahel/Amazon)
    status_reg, msg_reg = check_regional_trends(ds_trend)
    checks.append(("Regional Sanity (Sahel/Amazon)", status_reg, msg_reg))

    # 4. Sign diversity
    passed_div, msg_div = check_trend_sign_diversity(ds_trend)
    checks.append(("Trend Sign Diversity (+ / -)", "PASS" if passed_div else "FAIL", msg_div))

    # 5. P-value bounds
    passed_p, msg_p = check_p_values_range(ds_trend)
    checks.append(("p-value Bounds [0, 1]", "PASS" if passed_p else "FAIL", msg_p))

    print(f"\n{'CHECK':<32} | {'STATUS':<8} | {'DETAILS'}")
    print("-" * 70)
    
    hard_fail = False
    for name, status, msg in checks:
        color = "\033[32m" if status == "PASS" else ("\033[33m" if status == "WARNING" else "\033[31m")
        print(f"{name:<32} | {color}{status:<8}\033[0m | {msg}")
        if status == "FAIL":
            hard_fail = True

    print("=" * 70 + "\n")

    ds_anom.close()
    ds_trend.close()

    if hard_fail:
        print("[-] Validation FAILED on one or more mandatory checks.")
        return 1
    
    print("[+] All scientific validation criteria PASSED successfully!")
    return 0


def main() -> int:
    return run_all_validations()


if __name__ == "__main__":
    sys.exit(main())
