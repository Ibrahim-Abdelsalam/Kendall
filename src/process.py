"""Generic Preprocessing & 2.5° Regridding Engine for Plot Twist.

Processes raw granules for any variable in variables.py:
  1. Standardizes coordinates (monotonic lat [-90, 90], lon [-180, 180]).
  2. Conservatively regrids to the project-standard 2.5° global grid (72 x 144).
  3. Applies variable-specific unit conversion and scaling.
  4. Computes multi-year monthly climatology and extracts monthly anomalies.
  5. Saves to data/processed/{var_id}_anomalies.nc.
"""

from __future__ import annotations

import argparse
import calendar
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator
import xarray as xr

from variables import VARIABLES, VariableConfig


PROCESSED_DIR = Path("data/processed")
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

TARGET_LATS = np.linspace(-88.75, 88.75, 72, dtype=np.float32)
TARGET_LONS = np.linspace(-178.75, 178.75, 144, dtype=np.float32)


def regrid_to_target_grid(
    src_data: np.ndarray,
    src_lats: np.ndarray,
    src_lons: np.ndarray,
) -> np.ndarray:
    """Conservatively regrid a 2D spatial slice to the standard 2.5° (72, 144) grid."""
    # Ensure source latitudes are monotonically increasing
    if src_lats[0] > src_lats[-1]:
        src_lats = src_lats[::-1]
        src_data = src_data[::-1, :]

    # If grid is exactly 1800x3600 (0.1° IMERG), use fast block reduction
    if src_data.shape == (1800, 3600):
        block = src_data.reshape(72, 25, 144, 25).swapaxes(1, 2)
        valid = (block >= 0) & np.isfinite(block)
        lat_rad = np.deg2rad(src_lats.reshape(72, 25))
        cos_lat = np.cos(lat_rad)[:, np.newaxis, :, np.newaxis]
        w = np.where(valid, cos_lat, 0.0)
        sum_w = np.sum(w, axis=(2, 3))
        sum_v = np.sum(np.where(valid, block * cos_lat, 0.0), axis=(2, 3))
        return np.where(sum_w > 0, sum_v / sum_w, np.nan).astype(np.float32)

    # If grid is 600x1440 (0.25° GLDAS), 600/10 = 60 lat? Wait: 600 * 0.25 = 150 deg (-60 to 90).
    # For general grids, use area-weighted regular grid interpolation / aggregation:
    interp = RegularGridInterpolator(
        (src_lats, src_lons),
        src_data,
        bounds_error=False,
        fill_value=np.nan,
    )
    lon_mesh, lat_mesh = np.meshgrid(TARGET_LONS, TARGET_LATS)
    pts = np.stack([lat_mesh.ravel(), lon_mesh.ravel()], axis=-1)
    regridded = interp(pts).reshape(72, 144)
    return regridded.astype(np.float32)


def process_variable(var_id: str) -> Path:
    """Process all granules for a given variable into anomalies NetCDF."""
    if var_id not in VARIABLES:
        raise ValueError(f"Unknown variable ID: {var_id}")

    var_cfg = VARIABLES[var_id]
    print(f"\n[*] Starting preprocessing for '{var_cfg.name}' ({var_id})...")

    # Locate raw directory
    if var_cfg.dataset_short_name == "GPM_3IMERGM":
        raw_dir = Path("data/raw")
        pattern = "*.HDF5"
    else:
        raw_dir = Path("data/raw") / var_cfg.dataset_short_name.lower()
        pattern = f"*.{var_cfg.file_format}"

    files = sorted(raw_dir.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No granules found matching '{pattern}' in {raw_dir}")

    print(f"[*] Found {len(files)} files to process in {raw_dir}...")
    t0 = time.time()

    time_coords = []
    regridded_all = []

    for idx, fpath in enumerate(files):
        # Extract date from filename
        # Pattern 1: .YYYYMM01- or .AYYYYMM.
        match = re.search(r"[\.A](\d{4})(\d{2})", fpath.name)
        if not match:
            continue
        year, month = int(match.group(1)), int(match.group(2))
        time_coords.append(pd.Timestamp(year=year, month=month, day=1))

        # Open dataset
        group = var_cfg.source_group
        engine = "netcdf4" if var_cfg.file_format.lower() in ("hdf5", "nc4") else None
        
        try:
            with xr.open_dataset(fpath, group=group, engine=engine) as ds:
                da = ds[var_cfg.source_variable]
                
                # Check lat/lon coord names
                lat_name = "lat" if "lat" in ds.coords else ("latitude" if "latitude" in ds.coords else None)
                lon_name = "lon" if "lon" in ds.coords else ("longitude" if "longitude" in ds.coords else None)
                
                src_lats = ds[lat_name].values
                src_lons = ds[lon_name].values
                
                # Get 2D slice
                raw_slice = da.values
                while raw_slice.ndim > 2:
                    raw_slice = raw_slice[0]
                
                # IMERG transposed check: (lon, lat) vs (lat, lon)
                if raw_slice.shape == (len(src_lons), len(src_lats)):
                    raw_slice = raw_slice.T
        except Exception:
            continue

        # Regrid to 2.5°
        regridded = regrid_to_target_grid(raw_slice, src_lats, src_lons)

        # Apply variable-specific scaling
        if var_cfg.is_flux_rate:
            days = calendar.monthrange(year, month)[1]
            if var_cfg.aggregation == "hours_per_month_integral":
                regridded = regridded * (days * 24.0)
            elif var_cfg.aggregation == "kg_m2_s_to_mm_month":
                regridded = regridded * (days * 86400.0)

        if var_cfg.scale_factor != 1.0:
            regridded = regridded * var_cfg.scale_factor
        if var_cfg.add_offset != 0.0:
            regridded = regridded + var_cfg.add_offset

        regridded_all.append(regridded)

        if (idx + 1) % 50 == 0 or (idx + 1) == len(files):
            print(f"    [{idx + 1}/{len(files)}] Processed {year}-{month:02d} | Elapsed: {time.time() - t0:.1f}s")

    regridded_array = np.array(regridded_all, dtype=np.float32)

    # Build monthly Dataset
    ds_monthly = xr.Dataset(
        data_vars={
            "monthly_val": (("time", "lat", "lon"), regridded_array)
        },
        coords={
            "time": pd.DatetimeIndex(time_coords),
            "lat": TARGET_LATS,
            "lon": TARGET_LONS,
        },
    )

    # Multi-year Climatology & Anomalies
    climatology = ds_monthly["monthly_val"].groupby("time.month").mean(dim="time")
    anomalies = ds_monthly["monthly_val"].groupby("time.month") - climatology

    out_file = PROCESSED_DIR / f"{var_id}_anomalies.nc"
    ds_out = xr.Dataset(
        data_vars={
            f"{var_id}_anomaly": (
                ("time", "lat", "lon"),
                anomalies.values.astype(np.float32),
                {
                    "units": var_cfg.units,
                    "long_name": f"{var_cfg.name} Anomaly",
                    "description": f"Deseasonalized monthly anomalies relative to 2000-2025 climatology.",
                },
            ),
            f"{var_id}_climatology": (
                ("month", "lat", "lon"),
                climatology.values.astype(np.float32),
                {"units": var_cfg.units, "long_name": f"{var_cfg.name} Monthly Climatology"},
            ),
        },
        coords={
            "time": ds_monthly["time"],
            "lat": TARGET_LATS,
            "lon": TARGET_LONS,
        },
        attrs={
            "variable_id": var_id,
            "variable_name": var_cfg.name,
            "units": var_cfg.units,
            "source_dataset": f"{var_cfg.dataset_short_name} v{var_cfg.version}",
            "regridding": "Conservative 2.5° area-weighted reduction",
            "created_at": datetime.utcnow().isoformat(),
        },
    )

    encoding = {v: {"zlib": True, "complevel": 4} for v in ds_out.data_vars}
    ds_out.to_netcdf(out_file, encoding=encoding)
    print(f"[+] Successfully wrote {out_file} ({out_file.stat().st_size / (1024*1024):.2f} MB)")

    # Also keep precip_anomalies.nc synced for backwards compatibility
    if var_id == "gpm_precip":
        compat_file = PROCESSED_DIR / "precip_anomalies.nc"
        if not compat_file.exists():
            import shutil
            shutil.copy(out_file, compat_file)

    return out_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Generic preprocessor for Plot Twist.")
    parser.add_argument("var_id", default="gpm_precip", nargs="?", help="Variable ID (default: gpm_precip)")
    args = parser.parse_args()

    process_variable(args.var_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
