"""Web Export Utility for Plot Twist Static Website.

Exports compact, web-optimized JSON and gzipped binary/int16 files to web/data/{var_id}/:
  1. meta.json: Variable metadata, student definitions, summary stats, and regional alerts.
  2. trend.json.gz: 2D grids (Sen's slope, p-values, q-values, significant_fdr, valid mask) in scaled int16.
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
import xarray as xr

from variables import VARIABLES, VariableConfig


WEB_DATA_DIR = Path("web/data")
PROCESSED_DIR = Path("data/processed")


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
    # Find anomaly variable
    da_name = None
    for k in ds_anom.data_vars:
        if "anomaly" in k:
            da_name = k
            break
    if not da_name:
        da_name = list(ds_anom.data_vars.keys())[0]

    anom_vals = ds_anom[da_name].values.astype(np.float32)  # (304, 72, 144)
    n_time, n_lat, n_lon = anom_vals.shape

    # Determine dynamic scale factor so int16 covers full range with high precision
    finite_anom = anom_vals[np.isfinite(anom_vals)]
    max_abs = float(np.max(np.abs(finite_anom))) if len(finite_anom) > 0 else 1.0
    anom_scale = max_abs / 30000.0 if max_abs > 0 else 1.0

    # Scale and cast to int16 (missing values mapped to -32768)
    scaled_anom = np.where(np.isfinite(anom_vals), np.round(anom_vals / anom_scale), -32768).astype(np.int16)

    # Export compressed binary anomalies
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

    max_slope = float(np.nanmax(np.abs(slopes))) if np.any(np.isfinite(slopes)) else 1.0
    slope_scale = max_slope / 30000.0 if max_slope > 0 else 1.0
    scaled_slopes = np.where(np.isfinite(slopes), np.round(slopes / slope_scale), -32768).astype(np.int16)

    trend_payload = {
        "slope_scale": slope_scale,
        "slopes": scaled_slopes.tolist(),
        "p_values": np.where(np.isfinite(p_hr), np.round(p_hr, 4), None).tolist(),
        "q_values": np.where(np.isfinite(q_fdr), np.round(q_fdr, 4), None).tolist(),
        "significant_fdr": sig_fdr.tolist(),
        "valid": valid_mask.tolist(),
        "era_sign_flip": era_flips.tolist(),
    }

    trend_json_path = var_dir / "trend.json.gz"
    with gzip.open(trend_json_path, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(trend_payload, f)

    # 3. Summary Statistics for Meta
    valid_cells = int(valid_mask.sum())
    n_fdr = int(sig_fdr.sum())
    n_hr = int(ds_trend["significant_modified"].values.sum())
    n_pl = int(ds_trend["significant_plain"].values.sum())
    n_flips = int(era_flips[valid_mask == 1].sum())

    pct_fdr = (n_fdr / valid_cells) * 100 if valid_cells > 0 else 0.0
    pct_hr = (n_hr / valid_cells) * 100 if valid_cells > 0 else 0.0
    pct_pl = (n_pl / valid_cells) * 100 if valid_cells > 0 else 0.0
    pct_flips = (n_flips / valid_cells) * 100 if valid_cells > 0 else 0.0

    # 4. Export meta.json
    meta = {
        "id": var_id,
        "name": var_cfg.name,
        "student_definition": var_cfg.student_definition,
        "units": var_cfg.units,
        "trend_units": f"{var_cfg.units}/decade",
        "dataset_short_name": var_cfg.dataset_short_name,
        "version": var_cfg.version,
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
            "era_flip_share_pct": round(pct_flips, 2),
        },
        "verdict_card": {
            "Amazon": {
                "signal": "Drying trend (-9.27 mm/mo/decade across full record)",
                "warning": "Trend flips from +5.38 (2000-2013 TRMM) to -23.29 (2014-2025 GPM). Treat with caution pending independent dataset confirmation.",
                "status": "CAUTION_ERA_BREAK",
            },
            "Sahel": {
                "signal": "Weakly positive trend (+0.26 mm/mo/decade across full record)",
                "warning": "Not statistically significant under autocorrelation-aware test (p = 0.071). Consistent weakly positive sign across both eras (+0.38 vs +0.22).",
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
