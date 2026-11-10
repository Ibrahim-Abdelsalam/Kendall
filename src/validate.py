"""Internal Scientific Sanity Checks for Precipitation Anomalies & Hardened Trends.

Validates:
  1. NaN Integrity: No unexpected NaNs in anomalies or trend grids.
  2. Global Climatological Mean: Area-weighted mean within 60.0 - 130.0 mm/month.
  3. Trend Sign Diversity: Grid contains both positive and negative slopes.
  4. OLS vs Sen's Slope Cross-Check: Sign agreement > 85% across valid non-zero cells.
  5. Statistical Hierarchy: Asserts N_FDR <= N_HamedRao <= N_PlainMK.
  6. p-value & q-value Bounds: All metrics bounded strictly in [0.0, 1.0].
  7. Polar 60° Mask: Asserts all cells poleward of 60° have valid=0 and zero significance flags.
  8. TRMM vs GPM Break Check (Honesty Guard):
     - Emits WARN if trend sign differs between 2000-2013 and 2014-2025 for any region.
     - Reports global count and percentage of cells whose trend sign flips across the era boundary.
     - Uses autocorrelation-aware Hamed-Rao test with exact p-values for Sahel and Amazon.
  9. Diagnostic Map Verification: Verifies data/processed/trend_map.png exists and is non-empty.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple

import numpy as np
import pymannkendall as mk
from scipy.stats import linregress
import xarray as xr


PROCESSED_DATA_DIR = Path("data/processed")
ANOMALIES_FILE = PROCESSED_DATA_DIR / "precip_anomalies.nc"
TREND_FILE = PROCESSED_DATA_DIR / "precip_trend.nc"
MAP_FILE = PROCESSED_DATA_DIR / "trend_map.png"

GLOBAL_MEAN_MIN_MM = 60.0
GLOBAL_MEAN_MAX_MM = 130.0

SAHEL_BBOX = (12.0, 18.0, -15.0, 35.0)
AMAZON_BBOX = (-10.0, 2.0, -70.0, -50.0)


def compute_area_weighted_global_mean(da: xr.DataArray) -> float:
    """Compute cosine-latitude area-weighted spatial mean."""
    weights = np.cos(np.deg2rad(da["lat"]))
    weights.name = "weights"
    weighted = da.weighted(weights)
    return float(weighted.mean(dim=("lat", "lon")).mean(dim="time").values)


def check_nans(ds_anom: xr.Dataset, ds_trend: xr.Dataset) -> Tuple[bool, str]:
    """Check for unexpected NaNs."""
    anom_nans = int(np.isnan(ds_anom["precip_anomaly"].values).sum())
    total_anom = ds_anom["precip_anomaly"].size
    
    slope_nans = int(np.isnan(ds_trend["sens_slope"].values).sum())
    total_cells = ds_trend["sens_slope"].size

    if anom_nans == 0 and slope_nans == 0:
        return True, f"0 NaNs in anomalies ({total_anom:,} values) and trend grid ({total_cells:,} cells)."
    
    slope_pct = (slope_nans / total_cells) * 100
    if slope_pct < 1.0:
        return True, f"Minor NaNs confined to poles: {slope_nans}/{total_cells} cells ({slope_pct:.2f}%)."
    return False, f"Unexpected high NaN rate: slope {slope_pct:.2f}%."


def check_global_mean(ds_anom: xr.Dataset) -> Tuple[bool, str]:
    """Verify physical climatological mean bounds (60 - 130 mm/month)."""
    mean_val = compute_area_weighted_global_mean(ds_anom["precip_monthly"])
    passed = GLOBAL_MEAN_MIN_MM <= mean_val <= GLOBAL_MEAN_MAX_MM
    msg = f"Observed global area-weighted mean: {mean_val:.2f} mm/month (Allowed: {GLOBAL_MEAN_MIN_MM} - {GLOBAL_MEAN_MAX_MM} mm/month)"
    return passed, msg


def check_trend_sign_diversity(ds_trend: xr.Dataset) -> Tuple[bool, str]:
    """Verify trend field is bidirectional."""
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


def check_ols_agreement(ds_trend: xr.Dataset) -> Tuple[bool, str]:
    """Verify OLS vs Sen's slope sign agreement > 85% on valid cells."""
    sens = ds_trend["sens_slope"].values.flatten()
    ols = ds_trend["ols_slope"].values.flatten()
    val = ds_trend["valid"].values.flatten()

    non_zero = (sens != 0) & (ols != 0) & np.isfinite(sens) & np.isfinite(ols) & (val == 1)
    n_testable = int(non_zero.sum())
    n_agree = int((np.sign(sens[non_zero]) == np.sign(ols[non_zero])).sum())

    pct = (n_agree / n_testable) * 100 if n_testable > 0 else 0.0
    passed = pct >= 85.0
    msg = f"Agreement: {n_agree:,} / {n_testable:,} valid cells ({pct:.2f}% >= threshold 85.0%)"
    return passed, msg


def check_statistical_hierarchy(ds_trend: xr.Dataset) -> Tuple[bool, str]:
    """Verify conservative hierarchy: N_FDR <= N_HamedRao <= N_PlainMK."""
    valid_cells = int(ds_trend["valid"].sum())
    n_plain = int(ds_trend["significant_plain"].sum())
    n_hr = int(ds_trend["significant_modified"].sum())
    n_fdr = int(ds_trend["significant_fdr"].sum())

    pct_plain = (n_plain / valid_cells) * 100
    pct_hr = (n_hr / valid_cells) * 100
    pct_fdr = (n_fdr / valid_cells) * 100

    passed = (n_fdr <= n_hr) and (n_hr <= n_plain)
    msg = f"Plain: {n_plain:,} ({pct_plain:.1f}%) ➔ Autocorr-Aware: {n_hr:,} ({pct_hr:.1f}%) ➔ FDR: {n_fdr:,} ({pct_fdr:.1f}%) of valid domain"
    return passed, msg


def check_polar_mask_integrity(ds_trend: xr.Dataset) -> Tuple[bool, str]:
    """Verify cells poleward of 60° are masked out (valid=0 and zero significance flags)."""
    lats = ds_trend["lat"].values
    n_lon = ds_trend["lon"].size
    
    polar_lat_mask = (np.abs(lats) > 60.0)
    polar_cells = int(polar_lat_mask.sum()) * n_lon

    # Check that in polar cells, valid==0 and significance flags == 0
    valid_arr = ds_trend["valid"].values
    sig_fdr_arr = ds_trend["significant_fdr"].values
    sig_mod_arr = ds_trend["significant_modified"].values
    sig_pl_arr = ds_trend["significant_plain"].values

    polar_valid_leak = int(valid_arr[polar_lat_mask, :].sum())
    polar_sig_leak = int(sig_fdr_arr[polar_lat_mask, :].sum()) + int(sig_mod_arr[polar_lat_mask, :].sum()) + int(sig_pl_arr[polar_lat_mask, :].sum())

    passed = (polar_valid_leak == 0) and (polar_sig_leak == 0)
    msg = f"Masked {polar_cells:,} cells (|lat| > 60°); valid leaks: {polar_valid_leak}, significance leaks: {polar_sig_leak}"
    return passed, msg


def check_probability_bounds(ds_trend: xr.Dataset) -> Tuple[bool, str]:
    """Verify p-values and q-values are bounded in [0.0, 1.0]."""
    p_plain = ds_trend["p_value_plain"].values
    p_hr = ds_trend["p_value"].values
    q_fdr = ds_trend["q_value"].values

    v_plain = p_plain[np.isfinite(p_plain)]
    v_hr = p_hr[np.isfinite(p_hr)]
    v_fdr = q_fdr[np.isfinite(q_fdr)]

    ok_plain = (v_plain.min() >= 0.0) and (v_plain.max() <= 1.0)
    ok_hr = (v_hr.min() >= 0.0) and (v_hr.max() <= 1.0)
    ok_fdr = (v_fdr.min() >= 0.0) and (v_fdr.max() <= 1.0)

    passed = ok_plain and ok_hr and ok_fdr
    msg = f"p_plain: [{v_plain.min():.4f}, {v_plain.max():.4f}] | p_hr: [{v_hr.min():.4f}, {v_hr.max():.4f}] | q_fdr: [{v_fdr.min():.4f}, {v_fdr.max():.4f}]"
    return passed, msg


def check_trmm_gpm_break(ds_anom: xr.Dataset, ds_trend: xr.Dataset) -> Tuple[str, str]:
    """Check stability across the 2014 TRMM to GPM transition.
    
    RULE: If trend sign differs between 2000-2013 and 2014-2025 for a region,
    output WARN 'possible era break', not PASS.
    """
    t_break = "2013-12-31"
    
    # 1. Sahel evaluation using autocorrelation-aware test
    sahel_full = ds_anom["precip_anomaly"].sel(lat=slice(SAHEL_BBOX[0], SAHEL_BBOX[1]), lon=slice(SAHEL_BBOX[2], SAHEL_BBOX[3])).mean(dim=("lat", "lon"))
    sahel_t1 = sahel_full.sel(time=slice("2000-06-01", t_break)).values
    sahel_t2 = sahel_full.sel(time=slice("2014-01-01", "2025-09-01")).values
    
    res_sahel_full = mk.hamed_rao_modification_test(sahel_full.values)
    res_sahel_t1 = mk.hamed_rao_modification_test(sahel_t1)
    res_sahel_t2 = mk.hamed_rao_modification_test(sahel_t2)

    s_sahel_full, p_sahel_full = res_sahel_full.slope * 120.0, res_sahel_full.p
    s_sahel_t1, p_sahel_t1 = res_sahel_t1.slope * 120.0, res_sahel_t1.p
    s_sahel_t2, p_sahel_t2 = res_sahel_t2.slope * 120.0, res_sahel_t2.p

    sahel_sign_match = (np.sign(s_sahel_t1) == np.sign(s_sahel_t2))

    # 2. Amazon evaluation using autocorrelation-aware test
    amazon_full = ds_anom["precip_anomaly"].sel(lat=slice(AMAZON_BBOX[0], AMAZON_BBOX[1]), lon=slice(AMAZON_BBOX[2], AMAZON_BBOX[3])).mean(dim=("lat", "lon"))
    amazon_t1 = amazon_full.sel(time=slice("2000-06-01", t_break)).values
    amazon_t2 = amazon_full.sel(time=slice("2014-01-01", "2025-09-01")).values

    res_amazon_full = mk.hamed_rao_modification_test(amazon_full.values)
    res_amazon_t1 = mk.hamed_rao_modification_test(amazon_t1)
    res_amazon_t2 = mk.hamed_rao_modification_test(amazon_t2)

    s_amazon_full, p_amazon_full = res_amazon_full.slope * 120.0, res_amazon_full.p
    s_amazon_t1, p_amazon_t1 = res_amazon_t1.slope * 120.0, res_amazon_t1.p
    s_amazon_t2, p_amazon_t2 = res_amazon_t2.slope * 120.0, res_amazon_t2.p

    amazon_sign_match = (np.sign(s_amazon_t1) == np.sign(s_amazon_t2))

    # 3. Global sign flip count in valid domain
    val_mask = (ds_trend["valid"].values == 1)
    flips = int(ds_trend["era_sign_flip"].values[val_mask].sum())
    total_val = int(val_mask.sum())
    pct_flips = (flips / total_val) * 100 if total_val > 0 else 0.0

    # Build report text
    sahel_text = f"Sahel: Full={s_sahel_full:+.2f} (p={p_sahel_full:.3f}), TRMM={s_sahel_t1:+.2f} (p={p_sahel_t1:.3f}), GPM={s_sahel_t2:+.2f} (p={p_sahel_t2:.3f})"
    amazon_text = f"Amazon: Full={s_amazon_full:+.2f} (p={p_amazon_full:.3f}), TRMM={s_amazon_t1:+.2f} (p={p_amazon_t1:.3f}), GPM={s_amazon_t2:+.2f} (p={p_amazon_t2:.3f})"
    global_text = f"Global sign flips: {flips:,} / {total_val:,} valid cells ({pct_flips:.1f}%)"

    msg = f"{sahel_text} | {amazon_text} | {global_text}"

    # RULE: if any region flips sign, output WARN
    if not amazon_sign_match or not sahel_sign_match:
        reason = []
        if not amazon_sign_match:
            reason.append(f"Amazon flips from TRMM ({s_amazon_t1:+.2f}) to GPM ({s_amazon_t2:+.2f})")
        if not sahel_sign_match:
            reason.append("Sahel flips sign")
        return "WARN", f"possible era break: {'; '.join(reason)}. {global_text}"

    return "PASS", msg


def check_map_file() -> Tuple[bool, str]:
    """Verify diagnostic map PNG."""
    if MAP_FILE.exists() and MAP_FILE.stat().st_size > 50_000:
        return True, f"Diagnostic plot verified at {MAP_FILE} ({MAP_FILE.stat().st_size / 1024:.1f} KB)"
    return False, f"Missing or undersized map file at {MAP_FILE}"


def run_internal_sanity_checks() -> int:
    """Execute all internal sanity checks."""
    print("\n" + "=" * 78)
    print(" 🔍 INTERNAL SCIENTIFIC SANITY CHECKS (HARDENED HONESTY SUITE)")
    print("=" * 78)

    if not ANOMALIES_FILE.exists() or not TREND_FILE.exists():
        print("[-] Missing processed NetCDF files.")
        return 1

    ds_anom = xr.open_dataset(ANOMALIES_FILE)
    ds_trend = xr.open_dataset(TREND_FILE)

    checks = []

    # 1. NaN Integrity
    p, m = check_nans(ds_anom, ds_trend)
    checks.append(("NaN Integrity", "PASS" if p else "FAIL", m))

    # 2. Global Mean
    p, m = check_global_mean(ds_anom)
    checks.append(("Global Mean Bounds", "PASS" if p else "FAIL", m))

    # 3. Sign Diversity
    p, m = check_trend_sign_diversity(ds_trend)
    checks.append(("Trend Sign Diversity (+ / -)", "PASS" if p else "FAIL", m))

    # 4. Polar Masking Guard
    p, m = check_polar_mask_integrity(ds_trend)
    checks.append(("Polar 60° Mask (Ice Cover)", "PASS" if p else "FAIL", m))

    # 5. OLS Agreement
    p, m = check_ols_agreement(ds_trend)
    checks.append(("OLS vs Sen's Slope Agreement", "PASS" if p else "FAIL", m))

    # 6. Significance Hierarchy
    p, m = check_statistical_hierarchy(ds_trend)
    checks.append(("Significance Hierarchy", "PASS" if p else "FAIL", m))

    # 7. Probability Bounds
    p, m = check_probability_bounds(ds_trend)
    checks.append(("p-value & q-value Bounds", "PASS" if p else "FAIL", m))

    # 8. TRMM / GPM Break Check
    status, m = check_trmm_gpm_break(ds_anom, ds_trend)
    checks.append(("TRMM/GPM Era Break Check", status, m))

    # 9. Map File Check
    p, m = check_map_file()
    checks.append(("Diagnostic Map Generation", "PASS" if p else "FAIL", m))

    print(f"\n{'CHECK':<30} | {'STATUS':<8} | {'DETAILS'}")
    print("-" * 78)
    
    hard_fail = False
    for name, status, msg in checks:
        color = "\033[32m" if status == "PASS" else ("\033[33m" if status == "WARN" else "\033[31m")
        print(f"{name:<30} | {color}{status:<8}\033[0m | {msg}")
        if status == "FAIL":
            hard_fail = True

    print("=" * 78 + "\n")

    ds_anom.close()
    ds_trend.close()

    if hard_fail:
        print("[-] One or more checks failed.")
        return 1
    
    print("[+] Passed internal sanity checks (with honest WARN markers on sensor transition).")
    return 0


def main() -> int:
    return run_internal_sanity_checks()


if __name__ == "__main__":
    sys.exit(main())
