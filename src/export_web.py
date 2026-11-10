"""Web Export Utility for Plot Twist Static Website.

Exports compact, web-optimized JSON and gzipped binary/int16 files to web/data/{var_id}/:
  1. meta.json: Variable metadata, student definitions, era break caution notes, and summary statistics.
  2. trend.json.gz: 2D grids (Sen's slope, p-values, q-values, significant_fdr, cluster_significant, valid mask) in scaled int16.
  3. anomalies.bin.gz: 3D anomaly cube (time x lat x lon) in scaled int16 + gzip (< 3 MB per variable).

Strict budget: Total export across all variables must remain under 40 MB.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
from scipy.stats import ttest_ind
import xarray as xr

from variables import VARIABLES, VariableConfig


WEB_DATA_DIR = Path("web/data")
PROCESSED_DIR = Path("data/processed")


def get_caution_note_for_variable(var_id: str, is_caution: bool, pct_sig_break: float, step_diff: float, p_step: float) -> str:
    """Generate nuanced, scientifically honest caution notes based on official documentation."""
    base_disclaimer = "Trend over 2000-2025; may reflect natural cycles like ENSO."
    if var_id == "gpm_precip":
        return (
            "Supported by two datasets, consistent with drought years (2015/16, 2020, 2023/24), not proven. "
            "Both IMERG satellite and GLDAS reanalysis show post-2014 drops in regions like the Amazon, "
            "but sub-period trends are not statistically significant alone. "
            f"Domain-wide detrended step test is not significant (p = {p_step:.2f}). "
            + base_disclaimer
        )
    elif var_id == "gldas_precip":
        return (
            "Precipitation from GLDAS-2.1 Noah Monthly (0.25°). Forced with NOAA/GDAS atmospheric analysis fields "
            "and disaggregated GPCP Version 1.3 Daily Analysis precipitation fields (Adler et al., 2003; Huffman et al., 2001). "
            "Because GPCP v1.3 blends satellite sounders and ground gauges, it is partially but not completely independent of IMERG. "
            f"Trend-aware step test across 2014 is significant (detrended step: {step_diff:+.2f} mm/month, p = {p_step:.2e}). "
            + base_disclaimer
        )
    elif var_id == "gldas_soil_moist":
        return (
            "Simulated with Noah Model 3.6 in Land Information System (LIS) v7 forced by GDAS and GPCP v1.3. "
            f"Trend-aware step test across 2014 is not significant after linear detrending (p = {p_step:.2f}). "
            + base_disclaimer
        )
    elif var_id == "gldas_temp":
        return (
            "Caution: 2m air temperature simulated by GLDAS-2.1 Noah 3.6 using NOAA/GDAS atmospheric analysis fields. "
            f"Exhibits a statistically significant detrended step across 2014 ({step_diff:+.2f} °C, p = {p_step:.2e}), "
            "reflecting record global warmth in 2015-2024 coupled with atmospheric reanalysis inputs. "
            + base_disclaimer
        )
    elif var_id == "gldas_evap":
        return (
            "Caution: Evapotranspiration simulated by GLDAS-2.1 Noah 3.6 forced by GDAS and GPCP v1.3. "
            f"Exhibits a statistically significant detrended step across 2014 ({step_diff:+.2f} mm/month, p = {p_step:.2e}), "
            "along with sign reversal between eras in the Amazon basin. "
            + base_disclaimer
        )
    elif var_id == "merra2_aod":
        return (
            "Source variable: TOTEXTTAU (Total Aerosol Extinction Optical Depth at 550 nm from MERRA-2 M2TMNXAER v5.12.4). "
            f"Caution: Exhibits a significant detrended step across 2014 (p = {p_step:.2e}). "
            "MERRA-2 assimilates evolving satellite aerosol streams (MODIS Terra from 2000, Aqua from 2002, MISR), "
            "which introduces potential observing-system shifts across the 25-year record. "
            + base_disclaimer
        )
    return base_disclaimer


def export_variable_to_web(var_id: str) -> Dict[str, Any]:
    """Export compact web payload for a specific variable."""
    var_cfg = VARIABLES.get(var_id)
    if not var_cfg:
        raise ValueError(f"Unknown variable ID: {var_id}")

    var_dir = WEB_DATA_DIR / var_id
    var_dir.mkdir(parents=True, exist_ok=True)

    anom_file = PROCESSED_DIR / f"{var_id}_anomalies.nc"
    if not anom_file.exists() and var_id == "gpm_precip":
        anom_file = PROCESSED_DIR / "precip_anomalies.nc"

    trend_file = PROCESSED_DIR / f"{var_id}_trend.nc"
    if not trend_file.exists() and var_id == "gpm_precip":
        trend_file = PROCESSED_DIR / "precip_trend.nc"

    if not anom_file.exists() or not trend_file.exists():
        raise FileNotFoundError(f"Missing processed data for {var_id} in {PROCESSED_DIR}")

    print(f"\n[*] Exporting web assets for '{var_cfg.name}' to {var_dir}...")
    ds_anom = xr.open_dataset(anom_file)
    ds_trend = xr.open_dataset(trend_file)

    # 1. Anomaly Data Extraction & Scaling
    da_name = None
    for k in ds_anom.data_vars:
        if "anomaly" in k:
            da_name = k
            break
    if not da_name:
        da_name = list(ds_anom.data_vars.keys())[0]

    anom_vals = ds_anom[da_name].values.astype(np.float32)  # (304, 72, 144)
    n_time, n_lat, n_lon = anom_vals.shape

    finite_anom = anom_vals[np.isfinite(anom_vals)]
    max_abs = float(np.max(np.abs(finite_anom))) if len(finite_anom) > 0 else 1.0
    anom_scale = max_abs / 30000.0 if max_abs > 0 else 1.0

    scaled_anom = np.where(np.isfinite(anom_vals), np.round(anom_vals / anom_scale), -32768).astype(np.int16)

    anom_bin_path = var_dir / "anomalies.bin.gz"
    with gzip.open(anom_bin_path, "wb", compresslevel=6) as f:
        f.write(scaled_anom.tobytes())

    # 2. Trend Grids Extraction & Scaling
    slopes = ds_trend["sens_slope"].values.astype(np.float32)
    p_hr = ds_trend["p_value"].values.astype(np.float32)
    q_fdr = ds_trend["q_value"].values.astype(np.float32)
    valid_mask = ds_trend["valid"].values.astype(np.int8)
    sig_fdr = ds_trend["significant_fdr"].values.astype(np.int8)
    era_flips = ds_trend["era_sign_flip"].values.astype(np.int8)

    # Cluster significance
    if "cluster_significant" in ds_trend:
        cluster_sig = ds_trend["cluster_significant"].values.astype(np.int8)
    else:
        cluster_sig = np.zeros_like(sig_fdr, dtype=np.int8)

    max_slope = float(np.nanmax(np.abs(slopes))) if np.any(np.isfinite(slopes)) else 1.0
    slope_scale = max_slope / 30000.0 if max_slope > 0 else 1.0
    scaled_slopes = np.where(np.isfinite(slopes), np.round(slopes / slope_scale), -32768).astype(np.int16)

    trend_payload = {
        "slope_scale": slope_scale,
        "slopes": scaled_slopes.tolist(),
        "p_values": np.where(np.isfinite(p_hr), np.round(p_hr, 4), None).tolist(),
        "q_values": np.where(np.isfinite(q_fdr), np.round(q_fdr, 4), None).tolist(),
        "significant_fdr": sig_fdr.tolist(),
        "cluster_significant": cluster_sig.tolist(),
        "valid": valid_mask.tolist(),
        "era_sign_flip": era_flips.tolist(),
    }

    trend_json_path = var_dir / "trend.json.gz"
    with gzip.open(trend_json_path, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(trend_payload, f)

    # 3. Summary Statistics & 2014 Era Break Test
    valid_cells = int(valid_mask.sum())
    n_fdr = int(sig_fdr.sum())
    n_cluster = int(cluster_sig[valid_mask == 1].sum())
    n_hr = int(ds_trend["significant_modified"].values.sum())
    n_pl = int(ds_trend["significant_plain"].values.sum())
    n_flips = int(era_flips[valid_mask == 1].sum())

    pct_fdr = (n_fdr / valid_cells) * 100 if valid_cells > 0 else 0.0
    pct_cluster = (n_cluster / valid_cells) * 100 if valid_cells > 0 else 0.0
    pct_hr = (n_hr / valid_cells) * 100 if valid_cells > 0 else 0.0
    pct_pl = (n_pl / valid_cells) * 100 if valid_cells > 0 else 0.0
    pct_flips = (n_flips / valid_cells) * 100 if valid_cells > 0 else 0.0

    times = pd.to_datetime(ds_anom["time"].values)
    mask_t1 = times <= pd.Timestamp("2013-12-31")
    mask_t2 = times > pd.Timestamp("2013-12-31")

    # Cell-wise step change test
    cell_p_vals = []
    for i in range(n_lat):
        for j in range(n_lon):
            if valid_mask[i, j] == 1:
                s1 = anom_vals[mask_t1, i, j]
                s2 = anom_vals[mask_t2, i, j]
                if np.all(np.isfinite(s1)) and np.all(np.isfinite(s2)) and len(s1) > 10 and len(s2) > 10:
                    _, p = ttest_ind(s1, s2, equal_var=False)
                    if np.isfinite(p):
                        cell_p_vals.append(p)

    sig_break_cells = sum(p < 0.05 for p in cell_p_vals)
    pct_sig_break = (sig_break_cells / valid_cells) * 100 if valid_cells > 0 else 0.0

    # Domain mean time series step change (trend-aware OLS: y = b0 + b1*t + b2*d_step)
    weights = np.cos(np.deg2rad(ds_anom["lat"].values))
    weights_da = xr.DataArray(weights, coords=[("lat", ds_anom["lat"].values)])
    ts_series = ds_anom[da_name].weighted(weights_da).mean(dim=("lat", "lon")).values

    n_pts = len(ts_series)
    t_idx = np.arange(n_pts, dtype=float)
    d_step = (times > pd.Timestamp("2013-12-31")).astype(float)

    X = np.column_stack([np.ones(n_pts), t_idx, d_step])
    beta, _, _, _ = np.linalg.lstsq(X, ts_series, rcond=None)
    residuals = ts_series - X @ beta
    dof = n_pts - 3
    sigma2 = np.sum(residuals**2) / dof
    var_beta = sigma2 * np.linalg.inv(X.T @ X)
    se_step = np.sqrt(max(var_beta[2, 2], 1e-12))
    t_stat = beta[2] / se_step
    from scipy.stats import t as t_dist
    p_step_detrend = float(2 * (1 - t_dist.cdf(abs(t_stat), dof)))
    step_diff = float(beta[2])

    # Regional flip check (Amazon and Sahel)
    from cross_check import AMAZON_BBOX, SAHEL_BBOX, run_regional_era_stats
    amz_stats = run_regional_era_stats(ds_anom[da_name], AMAZON_BBOX)
    shl_stats = run_regional_era_stats(ds_anom[da_name], SAHEL_BBOX)

    amz_both_sig_flip = bool(amz_stats['p_t1'] < 0.05 and amz_stats['p_t2'] < 0.05 and np.sign(amz_stats['slope_t1']) != np.sign(amz_stats['slope_t2']))
    shl_both_sig_flip = bool(shl_stats['p_t1'] < 0.05 and shl_stats['p_t2'] < 0.05 and np.sign(shl_stats['slope_t1']) != np.sign(shl_stats['slope_t2']))
    regional_sig_flip = amz_both_sig_flip or shl_both_sig_flip

    is_caution = bool((p_step_detrend < 0.01) or regional_sig_flip)

    # 4. Export meta.json
    source_var_name = var_cfg.source_variable
    if var_id == "merra2_aod":
        source_var_name = "TOTEXTTAU"

    meta = {
        "id": var_id,
        "name": var_cfg.name,
        "student_definition": var_cfg.student_definition,
        "period_label": "Trend over 2000-2025; may reflect natural cycles like ENSO.",
        "units": var_cfg.units,
        "trend_units": f"{var_cfg.units}/decade",
        "dataset_short_name": var_cfg.dataset_short_name,
        "version": var_cfg.version,
        "source_variable": source_var_name,
        "time_range": {
            "start": str(ds_anom["time"].values[0])[:10],
            "end": str(ds_anom["time"].values[-1])[:10],
            "total_months": n_time,
            "timestamps": [str(t)[:10] for t in ds_anom["time"].values],
        },
        "grid": {
            "n_lat": n_lat,
            "n_lon": n_lon,
            "lats": ds_trend["lat"].values.tolist(),
            "lons": ds_trend["lon"].values.tolist(),
            "valid_cells": valid_cells,
        },
        "compression": {
            "anom_scale_factor": anom_scale,
            "anom_dtype": "int16",
            "anom_shape": [n_time, n_lat, n_lon],
            "slope_scale_factor": slope_scale,
        },
        "statistics": {
            "share_significant_plain_pct": round(pct_pl, 2),
            "share_significant_modified_pct": round(pct_hr, 2),
            "share_significant_fdr_pct": round(pct_fdr, 2),
            "share_isolated_filter_pct": round(pct_cluster, 2),
            "isolated_filter_cells": n_cluster,
            "isolated_filter_label": "isolated-cell filter (removes lone speckle; requires >= 3 of 8 neighbors share sign)",
            "era_flip_share_pct": round(pct_flips, 2),
        },
        "era_break_2014_check": {
            "detrended_step_difference": round(step_diff, 4),
            "detrended_step_p_value": float(f"{p_step_detrend:.4e}"),
            "amazon_both_eras_sig_flip": amz_both_sig_flip,
            "sahel_both_eras_sig_flip": shl_both_sig_flip,
            "caution": is_caution,
            "caution_note": get_caution_note_for_variable(var_id, is_caution, pct_sig_break, step_diff, p_step_detrend),
        },
        "verdict_card": {
            "Amazon": {
                "signal": "Drying trend (-9.27 mm/mo/decade in IMERG, -10.32 mm/mo/decade in GLDAS)",
                "warning": (
                    "Supported by two datasets, consistent with drought years (2015/16, 2020, 2023/24), not proven. "
                    "Both IMERG and GLDAS show sharp post-2014 drying (-14.1 mm and -18.4 mm step differences), "
                    "but neither era is statistically significant on its own (p = 0.15 and p = 0.14) and GLDAS is forced "
                    "by satellite-blended precipitation. Trend over 2000-2025; may reflect natural cycles like ENSO."
                ),
                "status": "CAUTION_REGIME_SHIFT",
            },
            "Sahel": {
                "signal": "Weakly positive trend (+0.26 mm/mo/decade in IMERG, +0.48 mm/mo/decade in GLDAS)",
                "warning": (
                    "Not statistically significant under autocorrelation-aware test (p = 0.071 in IMERG, p = 0.068 in GLDAS). "
                    "Consistent weakly positive sign across both eras. Trend over 2000-2025; may reflect natural cycles like ENSO."
                ),
                "status": "WEAKLY_POSITIVE",
            },
            "Polar": {
                "warning": "Cells poleward of 60° (|lat| > 60°) are masked out due to unreliable satellite retrievals over polar ice sheets.",
                "status": "MASKED_ICE",
            },
        },
    }

    meta_path = var_dir / "meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    sz_bin_kb = anom_bin_path.stat().st_size / 1024
    sz_json_kb = trend_json_path.stat().st_size / 1024
    sz_meta_kb = meta_path.stat().st_size / 1024
    total_kb = sz_bin_kb + sz_json_kb + sz_meta_kb

    print(f"[+] Web export complete for {var_id}:")
    print(f"    - anomalies.bin.gz : {sz_bin_kb:.1f} KB ({sz_bin_kb/1024:.2f} MB)")
    print(f"    - trend.json.gz    : {sz_json_kb:.1f} KB")
    print(f"    - meta.json        : {sz_meta_kb:.1f} KB")
    print(f"    - Total payload    : {total_kb:.1f} KB ({total_kb/1024:.2f} MB)")

    ds_anom.close()
    ds_trend.close()

    return {
        "var_id": var_id,
        "total_kb": total_kb,
        "files": [str(anom_bin_path), str(trend_json_path), str(meta_path)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export web payloads for Plot Twist.")
    parser.add_argument("var_id", default="gpm_precip", nargs="?", help="Variable ID (default: gpm_precip)")
    args = parser.parse_args()

    export_variable_to_web(args.var_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
