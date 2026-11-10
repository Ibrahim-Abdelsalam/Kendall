"""Generic Preprocessing & 2.5° Regridding Engine for Plot Twist.

Processes raw granules for any variable in variables.py:
  1. Standardizes coordinates (monotonic lat [-90, 90], lon [-180, 180]).
  2. For IMERG (0.1°): Conservative 25x25 block area-weighted reduction.
  3. For GLDAS (0.25°): 10x10 block area-weighted reduction with >= 50% land-fraction threshold.
     Cells with < 50% land data are masked out as water/polar.
  4. Applies variable-specific unit conversions:
     - Tair: Kelvin -> Celsius (K - 273.15)
     - Soil Moisture: kg/m^2
     - Rainfall & Evaporation: kg/m^2/s -> mm/month (flux * 86400 * days_in_month)
  5. Computes multi-year monthly climatology and extracts monthly anomalies.
  6. Saves to data/processed/{var_id}_anomalies.nc.
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


def regrid_imerg_block(raw_data: np.ndarray, raw_lats: np.ndarray) -> np.ndarray:
    """Regrid 0.1° IMERG (1800 x 3600) to 2.5° (72 x 144) using 25x25 block reduction."""
    block = raw_data.reshape(72, 25, 144, 25).swapaxes(1, 2)
    valid = (block >= 0) & np.isfinite(block)
    lat_rad = np.deg2rad(raw_lats.reshape(72, 25))
    cos_lat = np.cos(lat_rad)[:, np.newaxis, :, np.newaxis]
    w = np.where(valid, cos_lat, 0.0)
    sum_w = np.sum(w, axis=(2, 3))
    sum_v = np.sum(np.where(valid, block * cos_lat, 0.0), axis=(2, 3))
    return np.where(sum_w > 0, sum_v / sum_w, np.nan).astype(np.float32)


def regrid_gldas_block(
    raw_data: np.ndarray,
    raw_lats: np.ndarray,
    min_land_fraction: float = 0.50,
) -> np.ndarray:
    """Regrid 0.25° GLDAS (600 x 1440) to 2.5° (72 x 144).
    
    GLDAS covers latitudes -60° to +90° (600 rows).
    Target 2.5° grid has 72 rows total (-90° to +90°):
      - Rows 0 to 11 (-90° to -60°): Outside GLDAS coverage (Antarctica) -> NaN
      - Rows 12 to 71 (-60° to +90°): 60 rows corresponding exactly to 600 / 10 = 60 blocks.
    Masks any 2.5° cell with < 50% valid land data.
    """
    out = np.full((72, 144), np.nan, dtype=np.float32)
    
    # Check if raw_lats are decreasing, flip if necessary
    if raw_lats[0] > raw_lats[-1]:
        raw_data = raw_data[::-1, :]
        raw_lats = raw_lats[::-1]

    # Reshape GLDAS (600, 1440) into 60 x 10 x 144 x 10 -> (60, 144, 10, 10)
    block = raw_data.reshape(60, 10, 144, 10).swapaxes(1, 2)
    valid = np.isfinite(block)

    # Land fraction in each 10x10 block
    land_fraction = np.mean(valid, axis=(2, 3))  # (60, 144)

    # Cosine-latitude area weights
    lat_rad = np.deg2rad(raw_lats.reshape(60, 10))
    cos_lat = np.cos(lat_rad)[:, np.newaxis, :, np.newaxis]

    w = np.where(valid, cos_lat, 0.0)
    sum_w = np.sum(w, axis=(2, 3))
    sum_v = np.sum(np.where(valid, block * cos_lat, 0.0), axis=(2, 3))

    valid_cells = (land_fraction >= min_land_fraction) & (sum_w > 0)
    gldas_regridded = np.where(valid_cells, sum_v / np.where(sum_w > 0, sum_w, 1.0), np.nan)

    # Place into target grid rows 12..71 (-60 to +90)
    out[12:72, :] = gldas_regridded.astype(np.float32)
    return out


def regrid_merra2_interp(
    raw_data: np.ndarray,
    src_lats: np.ndarray,
    src_lons: np.ndarray,
) -> np.ndarray:
    """Regrid MERRA-2 (361 x 576) to 2.5° (72 x 144) using 2D linear interpolation."""
    mesh_lat, mesh_lon = np.meshgrid(TARGET_LATS, TARGET_LONS, indexing="ij")
    pts = np.stack([mesh_lat.ravel(), mesh_lon.ravel()], axis=-1)
    interp = RegularGridInterpolator((src_lats, src_lons), raw_data, method="linear", bounds_error=False, fill_value=np.nan)
    return interp(pts).reshape(72, 144).astype(np.float32)


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
    elif var_id == "merra2_aod":
        raw_dir = Path("data/raw/merra2_aod")
        pattern = "*.nc4"
    elif var_id.startswith("merra2_"):
        raw_dir = Path("data/raw/merra2_slv")
        pattern = "*.nc4"
    elif var_id.startswith("gldas_"):
        raw_dir = Path("data/raw/gldas_noah025_m")
        pattern = "*.nc4"
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
        match = re.search(r"[\.A](\d{4})(\d{2})", fpath.name)
        if not match:
            continue
        year, month = int(match.group(1)), int(match.group(2))
        time_coords.append(pd.Timestamp(year=year, month=month, day=1))

        group = var_cfg.source_group
        engine = "netcdf4" if var_cfg.file_format.lower() in ("hdf5", "nc4") else None
        
        with xr.open_dataset(fpath, group=group, engine=engine) as ds:
            src_var = var_cfg.source_variable
            if src_var not in ds and "TOTEXTTAU" in ds:
                src_var = "TOTEXTTAU"
            da = ds[src_var]
            lat_name = "lat" if "lat" in ds.coords else ("latitude" if "latitude" in ds.coords else None)
            lon_name = "lon" if "lon" in ds.coords else ("longitude" if "longitude" in ds.coords else None)
            
            src_lats = ds[lat_name].values
            src_lons = ds[lon_name].values
            
            raw_slice = da.values
            while raw_slice.ndim > 2:
                raw_slice = raw_slice[0]
            
            if raw_slice.shape == (len(src_lons), len(src_lats)):
                raw_slice = raw_slice.T

        # Regrid based on dataset geometry
        if raw_slice.shape == (1800, 3600):
            regridded = regrid_imerg_block(raw_slice, src_lats)
        elif raw_slice.shape == (600, 1440):
            regridded = regrid_gldas_block(raw_slice, src_lats, min_land_fraction=0.50)
        elif raw_slice.shape == (361, 576):
            regridded = regrid_merra2_interp(raw_slice, src_lats, src_lons)
        else:
            raise NotImplementedError(f"Unsupported grid shape: {raw_slice.shape}")

        # Variable-specific unit conversion
        days = calendar.monthrange(year, month)[1]
        if var_cfg.is_flux_rate:
            if var_cfg.aggregation == "hours_per_month_integral":
                regridded = regridded * (days * 24.0)
            elif var_cfg.aggregation in ("kg_m2_s_to_mm_month", "rate_flux_to_monthly"):
                # kg/m^2/s = mm/s * 86400 s/day * days = mm/month
                regridded = regridded * (days * 86400.0)

        if var_cfg.scale_factor != 1.0:
            regridded = regridded * var_cfg.scale_factor
        if var_cfg.add_offset != 0.0:
            regridded = regridded + var_cfg.add_offset

        regridded_all.append(regridded)

        if (idx + 1) % 50 == 0 or (idx + 1) == len(files):
            print(f"    [{idx + 1}/{len(files)}] Processed {year}-{month:02d} | Elapsed: {time.time() - t0:.1f}s")

    regridded_array = np.array(regridded_all, dtype=np.float32)

    # Snow domain thresholding: mask cells with < 50% nonzero snow months
    if var_id in ("gldas_swe", "gldas_snow_depth"):
        nonzero_snow_months = np.sum((regridded_array > 0.0) & np.isfinite(regridded_array), axis=0)
        valid_snow_cells = (nonzero_snow_months / len(files)) >= 0.50
        n_snow_remaining = int(valid_snow_cells.sum())
        regridded_array[:, ~valid_snow_cells] = np.nan
        print(f"[+] Snow Filtering: Masked cells with < 50% non-zero snow. Remaining valid snow cells: {n_snow_remaining} / {72*144} ({n_snow_remaining/(72*144)*100:.1f}%)")

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

    # Climatology & Anomalies
    climatology = ds_monthly["monthly_val"].groupby("time.month").mean(dim="time")
    anomalies = ds_monthly["monthly_val"].groupby("time.month") - climatology

    # Sanity metrics per prompt requirement #6
    weights = np.cos(np.deg2rad(TARGET_LATS))
    weights_da = xr.DataArray(weights, coords=[("lat", TARGET_LATS)])

    if var_id == "gldas_snow_depth":
        snow_mean = float(ds_monthly["monthly_val"].weighted(weights_da).mean(dim=("lat", "lon"), skipna=True).mean(dim="time").values)
        print(f"\n[+] Sanity Metric: Global mean snow depth over snow cells = {snow_mean:.3f} m")
        weighted_mean = snow_mean
    elif var_id == "gldas_swe":
        swe_mean = float(ds_monthly["monthly_val"].weighted(weights_da).mean(dim=("lat", "lon"), skipna=True).mean(dim="time").values)
        print(f"\n[+] Sanity Metric: Global mean SWE over snow cells = {swe_mean:.2f} kg/m^2")
        weighted_mean = swe_mean
    elif var_id == "merra2_ts":
        gldas_sample_file = next(Path("data/raw/gldas_noah025_m").glob("*.nc4"))
        with xr.open_dataset(gldas_sample_file) as ds_gldas:
            t_raw = ds_gldas["Tair_f_inst"].values[0]
            lats_gldas = ds_gldas["lat"].values
            gldas_land_grid = regrid_gldas_block(t_raw, lats_gldas)
            is_ocean = np.isnan(gldas_land_grid)
        
        ocean_da = ds_monthly["monthly_val"].where(xr.DataArray(is_ocean, coords=[("lat", TARGET_LATS), ("lon", TARGET_LONS)]))
        ocean_ts_mean = float(ocean_da.weighted(weights_da).mean(dim=("lat", "lon"), skipna=True).mean(dim="time").values)
        print(f"\n[+] Sanity Metric: Ocean mean TS = {ocean_ts_mean:.2f} °C")
        weighted_mean = ocean_ts_mean
    elif var_id == "merra2_wind":
        wind_mean = float(ds_monthly["monthly_val"].weighted(weights_da).mean(dim=("lat", "lon"), skipna=True).mean(dim="time").values)
        print(f"\n[+] Sanity Metric: Global mean wind speed = {wind_mean:.2f} m/s")
        weighted_mean = wind_mean
    elif var_id == "merra2_ps":
        ps_mean = float(ds_monthly["monthly_val"].weighted(weights_da).mean(dim=("lat", "lon"), skipna=True).mean(dim="time").values)
        print(f"\n[+] Sanity Metric: Global mean PS = {ps_mean:.2f} hPa")
        weighted_mean = ps_mean
    elif var_id == "merra2_tqv":
        tqv_mean = float(ds_monthly["monthly_val"].weighted(weights_da).mean(dim=("lat", "lon"), skipna=True).mean(dim="time").values)
        print(f"\n[+] Sanity Metric: Global mean total column water vapor = {tqv_mean:.2f} kg/m^2")
        weighted_mean = tqv_mean
    else:
        weighted_mean = float(ds_monthly["monthly_val"].weighted(weights_da).mean(dim=("lat", "lon"), skipna=True).mean(dim="time").values)
        print(f"\n[+] Sanity Metric: Global mean {var_cfg.name} = {weighted_mean:.2f} {var_cfg.units}")

    out_file = PROCESSED_DIR / f"{var_id}_anomalies.nc"
    ds_out = xr.Dataset(
        data_vars={
            f"{var_id}_anomaly": (
                ("time", "lat", "lon"),
                anomalies.values.astype(np.float32),
                {
                    "units": var_cfg.units,
                    "long_name": f"{var_cfg.name} Anomaly",
                    "description": "Deseasonalized monthly anomalies relative to 2000-2025 climatology.",
                },
            ),
            f"{var_id}_monthly": (
                ("time", "lat", "lon"),
                regridded_array,
                {"units": var_cfg.units, "long_name": f"{var_cfg.name} Total Monthly Value"},
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
            "regridding": "Conservative 2.5° area-weighted reduction with >= 50% land coverage mask",
            "global_mean": f"{weighted_mean:.2f} {var_cfg.units}",
            "created_at": datetime.utcnow().isoformat(),
        },
    )

    encoding = {v: {"zlib": True, "complevel": 4} for v in ds_out.data_vars}
    ds_out.to_netcdf(out_file, encoding=encoding)
    print(f"[+] Successfully wrote {out_file} ({out_file.stat().st_size / (1024*1024):.2f} MB)")

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
