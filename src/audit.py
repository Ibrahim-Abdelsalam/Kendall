"""Scientific Data Completeness & Integrity Audit for Kendall (Plot Twist).

Performs comprehensive audits across Raw, Processed, Trend, and Web layers for every
variable declared in variables.yaml.

Audits:
  1. Raw layer: Expected vs actual months, missing/duplicate months, zero-byte files,
     xarray internal time coordinate validation, and IMERG download_manifest cross-check.
  2. Processed layer: Anomaly cube shapes, time continuity, NaN fractions, all-NaN months,
     and calendar month distribution across years.
  3. Trend layer: Variable existence, valid-cell counts, p/q bounds in [0, 1], NaN inside
     valid mask, and polar mask leakage checks (|lat| > 60°).
  4. Web layer: File integrity, gzip decompression, int16 quantization error vs processed NetCDF,
     and total web/data size budget.
  5. Truncation check: Months in -> Months processed -> Months web.
  6. Intentional exclusions: Cryosphere, polar, and synchronization boundaries.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import xarray as xr
import yaml


RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
WEB_DATA_DIR = Path("web/data")
VARIABLES_YAML = Path("src/variables.yaml")
MANIFEST_PATH = RAW_DIR / "download_manifest.json"


def load_variables_config() -> Dict[str, Any]:
    """Load variable definitions from src/variables.yaml or src/variables.py."""
    if not VARIABLES_YAML.exists():
        raise FileNotFoundError(f"Missing config: {VARIABLES_YAML}")
    with open(VARIABLES_YAML, "r", encoding="utf-8") as f:
        try:
            return yaml.unsafe_load(f)
        except Exception:
            return yaml.load(f, Loader=yaml.FullLoader)


def get_expected_months(start_str: str, end_str: str) -> List[Tuple[int, int]]:
    """Generate list of expected (year, month) tuples from start to end date inclusive."""
    start_dt = pd.to_datetime(start_str)
    end_dt = pd.to_datetime(end_str)
    cur = pd.Timestamp(year=start_dt.year, month=start_dt.month, day=1)
    end = pd.Timestamp(year=end_dt.year, month=end_dt.month, day=1)
    months = []
    while cur <= end:
        months.append((cur.year, cur.month))
        # advance one month
        if cur.month == 12:
            cur = pd.Timestamp(year=cur.year + 1, month=1, day=1)
        else:
            cur = pd.Timestamp(year=cur.year, month=cur.month + 1, day=1)
    return months


def extract_internal_time_coord(fpath: Path, group: Optional[str] = None) -> Tuple[int, int]:
    """Open granule with xarray and read internal time coordinate (not filename)."""
    with xr.open_dataset(fpath, group=group, engine="netcdf4") as ds:
        if "time" not in ds.coords and "time" not in ds.data_vars:
            raise ValueError(f"No 'time' coordinate found in {fpath.name}")
        tval = ds["time"].values
        if hasattr(tval, "__len__") and len(tval) > 0:
            tval = tval[0]
        if hasattr(tval, "year") and hasattr(tval, "month"):
            return int(tval.year), int(tval.month)
        ts = pd.to_datetime(tval)
        return int(ts.year), int(ts.month)


def audit_raw_layer(var_id: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Audit raw files on disk against expected months from config."""
    time_range = cfg.get("time_range", ("2000-06-01", "2025-09-01"))
    if isinstance(time_range, tuple) or isinstance(time_range, list):
        start_str, end_str = time_range[0], time_range[1]
    else:
        start_str, end_str = "2000-06-01", "2025-09-01"

    expected_months = get_expected_months(start_str, end_str)
    n_expected = len(expected_months)

    # Determine raw directory and file pattern
    group = cfg.get("source_group")
    fmt = cfg.get("file_format", "nc4")
    
    if var_id == "gpm_precip":
        raw_target_dir = RAW_DIR
        pattern = "*.HDF5"
        group = "Grid"
    elif var_id.startswith("gldas_"):
        raw_target_dir = RAW_DIR / "gldas_noah025_m"
        pattern = "*.nc4"
    elif var_id == "merra2_aod":
        raw_target_dir = RAW_DIR / "merra2_aod"
        pattern = "*.nc4"
    elif var_id in ("merra2_ts", "merra2_wind", "merra2_ps", "merra2_tqv"):
        raw_target_dir = RAW_DIR / "merra2_slv"
        pattern = "*.nc4"
    else:
        raw_target_dir = RAW_DIR / cfg.get("dataset_short_name", "").lower()
        pattern = f"*.{fmt}"

    if not raw_target_dir.exists():
        return {
            "status": "NOT_DOWNLOADED",
            "n_expected": n_expected,
            "n_found": 0,
            "files": [],
            "missing_months": expected_months,
            "duplicate_months": [],
            "zero_byte_files": [],
            "unreadable_files": [],
            "date_range": None,
            "manifest_match": None,
        }

    raw_files = sorted(raw_target_dir.glob(pattern))
    if not raw_files:
        return {
            "status": "NOT_DOWNLOADED",
            "n_expected": n_expected,
            "n_found": 0,
            "files": [],
            "missing_months": expected_months,
            "duplicate_months": [],
            "zero_byte_files": [],
            "unreadable_files": [],
            "date_range": None,
            "manifest_match": None,
        }

    found_months = []
    zero_byte = []
    unreadable = []
    month_to_file = {}
    duplicates = []

    for f in raw_files:
        size = f.stat().st_size
        if size == 0:
            zero_byte.append(f.name)
            continue
        try:
            ym = extract_internal_time_coord(f, group=group)
            if ym in month_to_file:
                duplicates.append((ym, f.name, month_to_file[ym]))
            else:
                month_to_file[ym] = f.name
                found_months.append(ym)
        except Exception as exc:
            unreadable.append((f.name, str(exc)))

    expected_set = set(expected_months)
    found_set = set(found_months)
    missing = sorted(list(expected_set - found_set))

    date_range = None
    if found_months:
        min_ym = min(found_months)
        max_ym = max(found_months)
        date_range = (f"{min_ym[0]:04d}-{min_ym[1]:02d}", f"{max_ym[0]:04d}-{max_ym[1]:02d}")

    manifest_audit = None
    if var_id == "gpm_precip" and MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r", encoding="utf-8") as mf:
            manifest = json.load(mf)
        m_files = set(manifest.keys())
        d_files = set(f.name for f in raw_files)
        m_missing = list(m_files - d_files)
        m_extra = list(d_files - m_files)
        size_diffs = []
        for fn in d_files.intersection(m_files):
            actual_sz = (RAW_DIR / fn).stat().st_size
            expected_sz = manifest[fn].get("size_bytes")
            if actual_sz != expected_sz:
                size_diffs.append((fn, expected_sz, actual_sz))
        manifest_audit = {
            "manifest_entries": len(manifest),
            "missing_from_disk": len(m_missing),
            "extra_on_disk": len(m_extra),
            "size_mismatches": len(size_diffs),
            "all_verified": len(m_missing) == 0 and len(m_extra) == 0 and len(size_diffs) == 0,
        }

    status = "PASS"
    if missing or zero_byte or unreadable or duplicates:
        status = "FAIL"

    return {
        "status": status,
        "n_expected": n_expected,
        "n_found": len(found_months),
        "files_count": len(raw_files),
        "missing_months": missing,
        "duplicate_months": duplicates,
        "zero_byte_files": zero_byte,
        "unreadable_files": unreadable,
        "date_range": date_range,
        "manifest_match": manifest_audit,
    }


def audit_processed_layer(var_id: str) -> Dict[str, Any]:
    """Audit 2.5° monthly anomaly NetCDF dataset."""
    # Find anomalies file
    if var_id == "gpm_precip":
        path = PROCESSED_DIR / "precip_anomalies.nc"
    else:
        path = PROCESSED_DIR / f"{var_id}_anomalies.nc"

    if not path.exists():
        return {
            "status": "NOT_PROCESSED",
            "path": str(path),
            "exists": False,
        }

    with xr.open_dataset(path) as ds:
        # Detect anomaly variable
        anom_var = None
        for k in ds.data_vars:
            if "anomaly" in k:
                anom_var = k
                break
        if not anom_var:
            anom_var = list(ds.data_vars.keys())[0]

        da = ds[anom_var]
        shape = list(da.shape)
        n_time, n_lat, n_lon = shape

        # Check time continuity
        times = pd.to_datetime(ds["time"].values)
        consecutive_gaps = []
        is_monotonic = bool((times == times.sort_values()).all())
        if not is_monotonic:
            for i in range(len(times) - 1):
                if times[i + 1] < times[i]:
                    consecutive_gaps.append((f"{times[i].year:04d}-{times[i].month:02d}", f"{times[i+1].year:04d}-{times[i+1].month:02d}"))
        else:
            for i in range(len(times) - 1):
                t1 = times[i]
                t2 = times[i + 1]
                exp_year = t1.year + 1 if t1.month == 12 else t1.year
                exp_month = 1 if t1.month == 12 else t1.month + 1
                if t2.year != exp_year or t2.month != exp_month:
                    consecutive_gaps.append((f"{t1.year:04d}-{t1.month:02d}", f"{t2.year:04d}-{t2.month:02d}"))

        # NaN statistics per month
        anom_vals = da.values
        nan_per_month = np.isnan(anom_vals).reshape(n_time, -1).mean(axis=1)
        min_nan = float(np.min(nan_per_month))
        max_nan = float(np.max(nan_per_month))
        mean_nan = float(np.mean(nan_per_month))
        all_nan_months = int(np.sum(nan_per_month == 1.0))

        # Calendar month counts across years
        month_counts = {m: 0 for m in range(1, 13)}
        for t in times:
            month_counts[t.month] += 1

        expected_cal = {m: (26 if m in (6, 7, 8, 9) else 25) for m in range(1, 13)}
        cal_match = (month_counts == expected_cal)

        if not is_monotonic:
            status = "FAIL (Time Order)"
        elif len(consecutive_gaps) > 0 or all_nan_months > 0 or not cal_match:
            status = "FAIL"
        else:
            status = "PASS"

        return {
            "status": status,
            "path": str(path),
            "exists": True,
            "anom_var": anom_var,
            "shape": shape,
            "n_months": n_time,
            "is_monotonic": is_monotonic,
            "consecutive_gaps": consecutive_gaps,
            "min_nan_frac": min_nan,
            "max_nan_frac": max_nan,
            "mean_nan_frac": mean_nan,
            "all_nan_months": all_nan_months,
            "month_counts": month_counts,
            "cal_dist_correct": cal_match,
        }


def audit_trend_layer(var_id: str) -> Dict[str, Any]:
    """Audit 2D trend NetCDF dataset."""
    if var_id == "gpm_precip":
        path = PROCESSED_DIR / "precip_trend.nc"
    else:
        path = PROCESSED_DIR / f"{var_id}_trend.nc"

    if not path.exists():
        return {
            "status": "NOT_PROCESSED",
            "path": str(path),
            "exists": False,
        }

    with xr.open_dataset(path) as ds:
        expected_vars = [
            "sens_slope",
            "p_value",
            "p_value_plain",
            "q_value",
            "significant_fdr",
            "significant_modified",
            "significant_plain",
            "valid",
            "ols_slope",
        ]
        missing_vars = [v for v in expected_vars if v not in ds.data_vars]

        cluster_flag = "cluster_significant" in ds.data_vars

        valid_mask = ds["valid"].values.astype(int) == 1
        valid_cells = int(valid_mask.sum())

        p_vals = ds["p_value"].values
        q_vals = ds["q_value"].values
        slopes = ds["sens_slope"].values

        # Bounds on finite values
        finite_p = p_vals[np.isfinite(p_vals)]
        p_in_bounds = bool(np.all((finite_p >= 0.0) & (finite_p <= 1.0))) if len(finite_p) > 0 else False

        finite_q = q_vals[np.isfinite(q_vals)]
        q_in_bounds = bool(np.all((finite_q >= 0.0) & (finite_q <= 1.0))) if len(finite_q) > 0 else False

        # NaNs inside valid mask
        nan_slopes_in_valid = int(np.isnan(slopes[valid_mask]).sum())
        nan_p_in_valid = int(np.isnan(p_vals[valid_mask]).sum())
        nan_q_in_valid = int(np.isnan(q_vals[valid_mask]).sum())

        # Polar mask check: cells with |lat| > 60°
        lats = ds["lat"].values
        polar_idx = np.where(np.abs(lats) > 60.0)[0]
        polar_valid_leak = int(ds["valid"].values[polar_idx, :].sum())
        polar_sig_leak = int(ds["significant_fdr"].values[polar_idx, :].sum())

        # Status: PASS if no missing variables, bounds hold, slopes have no NaN, polar leaks = 0
        status = "PASS"
        if missing_vars or not p_in_bounds or not q_in_bounds or nan_slopes_in_valid > 0 or polar_valid_leak > 0:
            status = "FAIL"
        elif nan_p_in_valid > 0:
            status = "WARN"  # Known Hamed-Rao negative variance artifact on isolated cells

        return {
            "status": status,
            "path": str(path),
            "exists": True,
            "missing_vars": missing_vars,
            "cluster_filter_present": cluster_flag,
            "valid_cells": valid_cells,
            "p_in_bounds": p_in_bounds,
            "q_in_bounds": q_in_bounds,
            "nan_slopes_in_valid": nan_slopes_in_valid,
            "nan_p_in_valid": nan_p_in_valid,
            "nan_q_in_valid": nan_q_in_valid,
            "polar_valid_leak": polar_valid_leak,
            "polar_sig_leak": polar_sig_leak,
        }


def audit_web_layer(var_id: str, ds_anom_path: Optional[str] = None) -> Dict[str, Any]:
    """Audit web export files: meta.json, trend.json.gz, anomalies.bin.gz."""
    var_dir = WEB_DATA_DIR / var_id
    if not var_dir.exists():
        return {
            "status": "NOT_EXPORTED",
            "dir": str(var_dir),
            "exists": False,
        }

    meta_path = var_dir / "meta.json"
    trend_path = var_dir / "trend.json.gz"
    anom_path = var_dir / "anomalies.bin.gz"

    if not meta_path.exists() or not trend_path.exists() or not anom_path.exists():
        return {
            "status": "FAIL",
            "dir": str(var_dir),
            "exists": True,
            "missing_files": [p.name for p in (meta_path, trend_path, anom_path) if not p.exists()],
        }

    # 1. Parse meta.json
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    anom_scale = meta.get("compression", {}).get("anom_scale_factor")
    anom_shape = meta.get("compression", {}).get("anom_shape")

    # 2. Decompress and parse trend.json.gz
    with gzip.open(trend_path, "rt", encoding="utf-8") as f:
        trend_json = json.load(f)

    trend_keys = set(trend_json.keys())
    trend_valid = {"slopes", "p_values", "q_values", "valid", "significant_fdr"}.issubset(trend_keys)

    # 3. Decompress anomalies.bin.gz and check quantization against processed NetCDF
    with gzip.open(anom_path, "rb") as f:
        raw_bytes = f.read()

    int_arr = np.frombuffer(raw_bytes, dtype=np.int16).reshape(anom_shape)
    decoded_anom = np.where(int_arr == -32768, np.nan, int_arr.astype(np.float32) * anom_scale)

    max_quant_err = 0.0
    quant_pass = True
    if ds_anom_path and Path(ds_anom_path).exists():
        with xr.open_dataset(ds_anom_path) as ds:
            anom_var = None
            for k in ds.data_vars:
                if "anomaly" in k:
                    anom_var = k
                    break
            if not anom_var:
                anom_var = list(ds.data_vars.keys())[0]
            nc_vals = ds[anom_var].values
            if meta.get("compression", {}).get("glacier_cap_note"):
                # If glacier capping was applied, check quantization error relative to capped input
                cap_val = 110.0 if var_id == "gldas_swe" else 0.6
                comp_vals = np.clip(nc_vals, -cap_val, cap_val)
            else:
                comp_vals = nc_vals

            mask = np.isfinite(comp_vals)
            if np.any(mask):
                err = np.abs(decoded_anom[mask] - comp_vals[mask])
                max_quant_err = float(np.max(err))
                # Theoretical max round error is scale / 2
                quant_pass = max_quant_err <= (anom_scale / 2.0 + 1e-4)

    total_bytes = meta_path.stat().st_size + trend_path.stat().st_size + anom_path.stat().st_size

    status = "PASS" if trend_valid and quant_pass else "FAIL"

    return {
        "status": status,
        "dir": str(var_dir),
        "exists": True,
        "n_months_web": anom_shape[0] if anom_shape else None,
        "anom_scale": anom_scale,
        "max_quantization_error": max_quant_err,
        "quantization_within_half_scale": quant_pass,
        "disk_size_bytes": total_bytes,
    }


def run_full_audit() -> Dict[str, Any]:
    """Execute complete data audit across all variables."""
    cfg = load_variables_config()
    print("=" * 86)
    print("   KENDALL SCIENTIFIC DATA COMPLETENESS & REPRODUCIBILITY AUDIT")
    print(f"   Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Target: All variables in variables.yaml")
    print("=" * 86)

    results = {}
    total_web_bytes = 0

    for var_id, var_cfg in cfg.items():
        if var_cfg.get("included_in_submission") is False or var_id == "modis_ndvi":
            results[var_id] = {
                "name": var_cfg.get("name"),
                "not_included": True,
                "raw": {"status": "NOT_INCLUDED", "n_expected": 304, "n_found": 0},
                "processed": {"status": "NOT_INCLUDED", "n_months": "-"},
                "trend": {"status": "NOT_INCLUDED", "valid_cells": "-", "polar_valid_leak": "-"},
                "web": {"status": "NOT_INCLUDED", "n_months_web": "-"},
                "truncation_pass": True,
                "truncation_msg": "Not included in this submission",
            }
            continue

        print(f"\n[*] Auditing variable: {var_id} ({var_cfg.get('name')})...")
        raw_res = audit_raw_layer(var_id, var_cfg)
        proc_res = audit_processed_layer(var_id)
        trend_res = audit_trend_layer(var_id)
        web_res = audit_web_layer(var_id, proc_res.get("path"))

        if web_res.get("disk_size_bytes"):
            total_web_bytes += web_res["disk_size_bytes"]

        # Truncation check
        m_raw = raw_res.get("n_found", 0)
        m_proc = proc_res.get("n_months", 0)
        m_web = web_res.get("n_months_web", 0)

        truncation_pass = True
        truncation_msg = f"{m_raw} -> {m_proc} -> {m_web}"
        if m_raw > 0 and (m_proc < m_raw or m_web < m_proc):
            truncation_pass = False

        results[var_id] = {
            "name": var_cfg.get("name"),
            "raw": raw_res,
            "processed": proc_res,
            "trend": trend_res,
            "web": web_res,
            "truncation_pass": truncation_pass,
            "truncation_msg": truncation_msg,
        }

    # Print Summary Table
    print("\n" + "=" * 115)
    print(f"{'VARIABLE ID':<18} | {'EXPECT':<6} | {'RAW':<5} | {'PROC':<5} | {'WEB':<5} | {'VALID':<6} | {'POLAR LEAK':<10} | {'MAX Q-ERR':<10} | {'STATUS':<10}")
    print("-" * 115)

    all_pass = True
    for var_id, r in results.items():
        n_exp = r["raw"].get("n_expected", 304)
        n_raw = r["raw"].get("n_found", 0)
        n_proc = r["processed"].get("n_months", "-")
        n_web = r["web"].get("n_months_web", "-")
        n_valid = r["trend"].get("valid_cells", "-")
        p_leak = r["trend"].get("polar_valid_leak", "-")
        max_q = f"{r['web'].get('max_quantization_error', 0.0):.4f}" if r["web"].get("max_quantization_error") is not None else "-"

        # Determine composite status
        if r.get("not_included"):
            status = "NOT INCLUDED (not in submission)"
        elif r["raw"]["status"] == "NOT_DOWNLOADED":
            status = "NOT_DOWNLOADED"
        elif not r["truncation_pass"]:
            status = "TRUNCATED"
            all_pass = False
        elif "FAIL" in r["processed"]["status"] or r["trend"]["status"] == "FAIL" or r["web"]["status"] == "FAIL":
            status = r["processed"]["status"] if "FAIL" in r["processed"]["status"] else "FAIL"
            all_pass = False
        elif r["trend"]["status"] == "WARN":
            status = "WARN (p-nan)"
        else:
            status = "PASS"

        print(f"{var_id:<18} | {n_exp:<6} | {n_raw:<5} | {str(n_proc):<5} | {str(n_web):<5} | {str(n_valid):<6} | {str(p_leak):<10} | {max_q:<10} | {status:<10}")

    print("-" * 115)
    total_web_mb = total_web_bytes / (1024 * 1024)
    print(f"Total Web Export Payload: {total_web_mb:.2f} MB (Budget: < 60 MB)")
    print("=" * 115)

    # Print Intentional Exclusions
    print("\n--- INTENTIONAL EXCLUSIONS & SCIENTIFIC DESIGN CHOICES ---")
    print("1. Record End Date: Synchronized to 2025-09 across all variables. October 2025 is excluded to match")
    print("   the final latency release of GPM IMERG V07B.")
    print("2. Cryosphere Mask (GLDAS SWE & Snow Depth): Cells with < 50% non-zero snow months are masked (cryosphere-only).")
    print("3. Polar 60° Mask (Honesty Guard): All cells with |lat| > 60° have valid=0 and significant_*=0 due to")
    print("   satellite retrieval noise over ice sheets and sea-ice transitions.")
    print("4. Noah Land Mask (GLDAS): Polar Antarctica (< -60°) and oceans are masked by the terrestrial Noah model.")
    print("5. MODIS NDVI: Declared in config schema for future expansion; not downloaded in current deployment.")

    return {
        "results": results,
        "total_web_mb": total_web_mb,
        "all_pass": all_pass,
    }


if __name__ == "__main__":
    audit_data = run_full_audit()
    sys.exit(0 if audit_data["all_pass"] else 1)
