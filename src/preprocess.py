"""Preprocess GPM IMERG V07 Monthly Precipitation Granules.

1. Ingests all 304 downloaded monthly HDF5 files from data/raw/.
2. Converts precipitation rate (mm/hr) to monthly accumulation (mm/month) based on hours per month.
3. Performs conservative area-weighted regridding from native 0.1° (1800x3600) to uniform 2.5° (72x144).
4. Handles uneven record period explicitly:
   - June to September: 26 years of observations (2000-2025)
   - October to December: 25 years of observations (2000-2024)
   - January to May: 25 years of observations (2001-2025)
5. Computes multi-year monthly climatology and derives monthly precipitation anomalies.
6. Saves CF-compliant NetCDF4 dataset to data/processed/precip_anomalies.nc.
"""

from __future__ import annotations

import calendar
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
import xarray as xr


RAW_DATA_DIR = Path("data/raw")
PROCESSED_DATA_DIR = Path("data/processed")
OUTPUT_ANOMALIES_FILE = PROCESSED_DATA_DIR / "precip_anomalies.nc"

TARGET_D_LAT = 2.5
TARGET_D_LON = 2.5
BLOCK_SIZE = 25  # 25 * 0.1 deg = 2.5 deg


def extract_year_month_from_filename(filename: str) -> Tuple[int, int]:
    """Parse Year and Month from standard GPM IMERG file naming.
    
    Example: 3B-MO.MS.MRG.3IMERG.20000601-S000000-E235959.06.V07B.HDF5 -> (2000, 6)
    """
    match = re.search(r"\.(\d{4})(\d{2})01-", filename)
    if not match:
        raise ValueError(f"Could not extract date from filename: {filename}")
    return int(match.group(1)), int(match.group(2))


def compute_conservative_block_weights(raw_lats: np.ndarray) -> np.ndarray:
    """Compute cosine-latitude area weights for each 25x25 cell block.
    
    lat shape: (1800,) -> (72, 25)
    Returns: cos_lat weights shaped (72, 1, 25, 1)
    """
    lat_rad = np.deg2rad(raw_lats.reshape(72, BLOCK_SIZE))
    cos_lat = np.cos(lat_rad)[:, np.newaxis, :, np.newaxis]
    return cos_lat


def regrid_single_month_conservative(
    raw_precip_rate: np.ndarray,
    cos_lat_weights: np.ndarray,
) -> np.ndarray:
    """Regrid native 0.1° precipitation rate (1800 lat, 3600 lon) to 2.5° (72, 144).
    
    Preserves spatial water flux using cosine-latitude area-weighted block integration.
    """
    # Raw precip shape: (1800, 3600)
    # Reshape to (72, 25, 144, 25) and swap to (72, 144, 25, 25)
    block = raw_precip_rate.reshape(72, BLOCK_SIZE, 144, BLOCK_SIZE).swapaxes(1, 2)

    # Missing/invalid values check (IMERG uses -9999.9 for fill/missing)
    valid_mask = (block >= 0.0) & np.isfinite(block)

    # Area-weighted reduction
    cell_weights = np.where(valid_mask, cos_lat_weights, 0.0)
    sum_weights = np.sum(cell_weights, axis=(2, 3))
    weighted_sum = np.sum(np.where(valid_mask, block * cos_lat_weights, 0.0), axis=(2, 3))

    regridded = np.where(sum_weights > 0, weighted_sum / sum_weights, np.nan)
    return regridded.astype(np.float32)


def process_all_granules() -> xr.Dataset:
    """Load, convert units, regrid, and aggregate all monthly files."""
    raw_files = list(RAW_DATA_DIR.glob("*.HDF5"))
    if not raw_files:
        raise FileNotFoundError(f"No HDF5 granules found in {RAW_DATA_DIR}.")

    month_to_file: dict[tuple[int, int], Path] = {}
    for fpath in raw_files:
        with xr.open_dataset(fpath, group="Grid", engine="netcdf4") as ds:
            tval = ds["time"].values[0]
            ym = (int(tval.year), int(tval.month))
        if ym in month_to_file:
            raise ValueError(f"DUPLICATE MONTH DETECTED: {month_to_file[ym].name} and {fpath.name}")
        month_to_file[ym] = fpath

    sorted_ym = sorted(month_to_file.keys())
    files = [month_to_file[ym] for ym in sorted_ym]

    print(f"[*] Found {len(files)} granules in {RAW_DATA_DIR}. Sorted by internal time coordinate...")

    # Open first file to extract coordinate arrays
    with xr.open_dataset(files[0], group="Grid", engine="netcdf4") as ds0:
        raw_lats = ds0["lat"].values
        raw_lons = ds0["lon"].values

    cos_lat_weights = compute_conservative_block_weights(raw_lats)

    # 2.5° target coordinates (cell centers)
    # 72 cells in lat: -88.75 to +88.75
    # 144 cells in lon: -178.75 to +178.75
    target_lats = raw_lats.reshape(72, BLOCK_SIZE).mean(axis=1).astype(np.float32)
    target_lons = raw_lons.reshape(144, BLOCK_SIZE).mean(axis=1).astype(np.float32)

    n_times = len(files)
    n_lats = len(target_lats)
    n_lons = len(target_lons)

    regridded_precip_monthly = np.empty((n_times, n_lats, n_lons), dtype=np.float32)
    time_coords = []

    print(f"[*] Regridding {n_times} monthly granules (0.1° -> 2.5° conservative area average)...")
    start_time = time.time()

    for idx, fpath in enumerate(files):
        year, month = extract_year_month_from_filename(fpath.name)
        time_coords.append(pd.Timestamp(year=year, month=month, day=1))

        # Calculate exact hours in this specific month
        days_in_month = calendar.monthrange(year, month)[1]
        hours_in_month = days_in_month * 24.0

        with xr.open_dataset(fpath, group="Grid", engine="netcdf4") as ds:
            # Raw shape is (1, lon: 3600, lat: 1800). Transpose to (lat: 1800, lon: 3600)
            raw_rate = ds["precipitation"].values[0].T

        # Regrid to (72, 144) in mm/hr
        regridded_rate = regrid_single_month_conservative(raw_rate, cos_lat_weights)

        # Convert mm/hr -> mm/month
        regridded_precip_monthly[idx] = regidded_month_accum = regridded_rate * hours_in_month

        if (idx + 1) % 50 == 0 or (idx + 1) == n_times:
            elapsed = time.time() - start_time
            print(f"    [{idx + 1}/{n_times}] Processed {year}-{month:02d} ({fpath.name[:28]}...) | Elapsed: {elapsed:.1f}s")

    # Construct xarray Dataset for monthly total precipitation
    ds_monthly = xr.Dataset(
        data_vars={
            "precip_monthly": (
                ("time", "lat", "lon"),
                regridded_precip_monthly,
                {
                    "units": "mm/month",
                    "long_name": "Total Monthly Precipitation",
                    "standard_name": "precipitation_amount",
                    "cell_methods": "time: sum area: mean",
                },
            )
        },
        coords={
            "time": ("time", pd.DatetimeIndex(time_coords)),
            "lat": (
                "lat",
                target_lats,
                {
                    "units": "degrees_north",
                    "long_name": "Latitude",
                    "standard_name": "latitude",
                    "axis": "Y",
                },
            ),
            "lon": (
                "lon",
                target_lons,
                {
                    "units": "degrees_east",
                    "long_name": "Longitude",
                    "standard_name": "longitude",
                    "axis": "X",
                },
            ),
        },
    )

    return ds_monthly


def compute_anomalies_and_climatology(ds_monthly: xr.Dataset) -> xr.Dataset:
    """Compute multi-year monthly climatology and subtract it to obtain monthly anomalies.
    
    EXPLICIT UNEVEN CLIMATOLOGY HANDLING:
    - The record extends from 2000-06 through 2025-09 (304 months).
    - Months 1-5 (Jan-May) contain 25 years of data (2001-2025).
    - Months 6-9 (Jun-Sep) contain 26 years of data (2000-2025).
    - Months 10-12 (Oct-Dec) contain 25 years of data (2000-2024).
    Each calendar month's climatological mean is computed strictly over its own available sample count N_m.
    """
    print("\n[*] Computing multi-year monthly climatology and seasonal cycle removal...")
    
    # Audit sample distribution per calendar month
    month_counts = ds_monthly["time"].groupby("time.month").count(dim="time").values
    print("    Sample count N_m per calendar month:")
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for m_idx, (name, cnt) in enumerate(zip(month_names, month_counts), start=1):
        print(f"      Month {m_idx:02d} ({name}): N = {cnt} years")

    # Climatology per calendar month (12, 72, 144)
    climatology = ds_monthly["precip_monthly"].groupby("time.month").mean(dim="time")
    climatology.attrs = {
        "units": "mm/month",
        "long_name": "Monthly Precipitation Climatology (2000-2025)",
        "description": "Multi-year mean precipitation for each calendar month, accounting for uneven start in June 2000.",
    }

    # Anomalies = Monthly Total - Climatology of that calendar month
    anomalies = ds_monthly["precip_monthly"].groupby("time.month") - climatology
    anomalies.attrs = {
        "units": "mm/month",
        "long_name": "Monthly Precipitation Anomaly",
        "description": "Monthly precipitation with multi-year seasonal cycle removed (P_ym - P_clim_m).",
    }

    # Combined output dataset
    ds_out = xr.Dataset(
        data_vars={
            "precip_anomaly": anomalies,
            "precip_monthly": ds_monthly["precip_monthly"],
            "precip_climatology": climatology,
        },
        coords={
            "time": ds_monthly["time"],
            "lat": ds_monthly["lat"],
            "lon": ds_monthly["lon"],
        },
        attrs={
            "title": "GPM IMERG V07 Final Monthly Precipitation Anomalies (2000-2025)",
            "source": "NASA Global Precipitation Measurement (GPM) IMERG Final Monthly V07 (GPM_3IMERGM)",
            "regridding": "Conservative area-weighted block averaging (0.1° to 2.5°)",
            "temporal_range": f"{str(ds_monthly['time'].values[0])[:10]} to {str(ds_monthly['time'].values[-1])[:10]}",
            "total_months": len(ds_monthly["time"]),
            "conventions": "CF-1.8",
            "created_at": datetime.utcnow().isoformat(),
        },
    )

    return ds_out


def main() -> int:
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    try:
        ds_monthly = process_all_granules()
        ds_anomalies = compute_anomalies_and_climatology(ds_monthly)

        print(f"\n[*] Writing processed anomalies to {OUTPUT_ANOMALIES_FILE}...")
        encoding = {
            "precip_anomaly": {"zlib": True, "complevel": 4, "dtype": "float32"},
            "precip_monthly": {"zlib": True, "complevel": 4, "dtype": "float32"},
            "precip_climatology": {"zlib": True, "complevel": 4, "dtype": "float32"},
        }
        ds_anomalies.to_netcdf(OUTPUT_ANOMALIES_FILE, encoding=encoding)
        
        file_size_mb = OUTPUT_ANOMALIES_FILE.stat().st_size / (1024 * 1024)
        print(f"[+] Successfully generated {OUTPUT_ANOMALIES_FILE} ({file_size_mb:.2f} MB)")
        print(f"[+] Total preprocessing runtime: {time.time() - t_start:.2f}s")
        return 0
    except Exception as exc:
        print(f"[-] Preprocessing FAILED: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
