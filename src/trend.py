"""Compute pixel-wise linear precipitation trends using Mann-Kendall with Sen's slope.

Reads: data/processed/precip_anomalies.nc
Computes per grid cell:
  - Sen's slope scaled to mm / month / decade (per-month slope * 120)
  - Mann-Kendall two-sided p-value
  - Significance flag (p < 0.05)
Parallelized across all CPU cores for fast execution on ~10,000 cells.
Saves: data/processed/precip_trend.nc
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Tuple

import numpy as np
import pymannkendall as mk
import xarray as xr


PROCESSED_DATA_DIR = Path("data/processed")
ANOMALIES_FILE = PROCESSED_DATA_DIR / "precip_anomalies.nc"
TREND_FILE = PROCESSED_DATA_DIR / "precip_trend.nc"

# Conversion factor: each time step is 1 month.
# 1 decade = 120 months.
# Thus: per-month Sen's slope * 120 = mm / month / decade.
MONTHS_PER_DECADE = 120.0


def compute_cell_trend(series: np.ndarray) -> Tuple[float, float, int]:
    """Compute Sen's slope and Mann-Kendall p-value for a single 1D time series.
    
    Returns:
      (slope_per_decade, p_value, is_significant)
    """
    # Filter out NaNs if present
    valid_mask = np.isfinite(series)
    valid_vals = series[valid_mask]

    # Need at least 10 valid points to compute meaningful MK test
    if len(valid_vals) < 10:
        return np.nan, np.nan, 0

    # Constant series check (zero variance)
    if np.all(valid_vals == valid_vals[0]):
        return 0.0, 1.0, 0

    try:
        res = mk.original_test(valid_vals)
        # Sen's slope conversion:
        # res.slope is in units of [variable] per time-step (mm / month / month).
        # Multiplied by 120 months/decade yields mm / month / decade.
        slope_decade = float(res.slope * MONTHS_PER_DECADE)
        p_val = float(res.p)
        sig = 1 if p_val < 0.05 else 0
        return slope_decade, p_val, sig
    except Exception:
        return np.nan, np.nan, 0


def _worker_chunk(chunk_data: np.ndarray) -> list[Tuple[float, float, int]]:
    """Worker function to process a batch of 1D series."""
    # chunk_data shape: (N_cells, N_time)
    results = []
    for i in range(chunk_data.shape[0]):
        results.append(compute_cell_trend(chunk_data[i]))
    return results


def run_trend_analysis() -> None:
    """Run parallelized trend estimation across the global 2.5° grid."""
    if not ANOMALIES_FILE.exists():
        raise FileNotFoundError(f"Missing input anomalies file: {ANOMALIES_FILE}")

    print(f"[*] Opening {ANOMALIES_FILE}...")
    ds = xr.open_dataset(ANOMALIES_FILE)
    anom_da = ds["precip_anomaly"]  # (time, lat, lon)

    n_time, n_lat, n_lon = anom_da.shape
    total_cells = n_lat * n_lon
    print(f"[*] Grid size: {n_lat} lats x {n_lon} lons = {total_cells} grid cells across {n_time} months.")

    # Reshape to (total_cells, n_time) for batch distribution
    # Transpose to (lat, lon, time) then flatten spatial dims
    spatial_time = anom_da.values.transpose(1, 2, 0).reshape(total_cells, n_time)

    num_workers = min(os.cpu_count() or 4, 16)
    chunk_size = int(np.ceil(total_cells / (num_workers * 4)))
    chunks = [
        spatial_time[i : i + chunk_size]
        for i in range(0, total_cells, chunk_size)
    ]

    print(f"[*] Parallelizing trend calculation over {num_workers} worker processes ({len(chunks)} chunks)...")
    start_time = time.time()

    all_results = []
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        for chunk_res in executor.map(_worker_chunk, chunks):
            all_results.extend(chunk_res)

    elapsed = time.time() - start_time
    print(f"[+] Completed Mann-Kendall + Sen's slope on {total_cells} cells in {elapsed:.2f}s ({(total_cells/elapsed):.1f} cells/s).")

    # Unpack results into 2D arrays (72, 144)
    slopes = np.array([r[0] for r in all_results], dtype=np.float32).reshape(n_lat, n_lon)
    p_values = np.array([r[1] for r in all_results], dtype=np.float32).reshape(n_lat, n_lon)
    significance = np.array([r[2] for r in all_results], dtype=np.int8).reshape(n_lat, n_lon)

    # Construct output Dataset
    ds_trend = xr.Dataset(
        data_vars={
            "sens_slope": (
                ("lat", "lon"),
                slopes,
                {
                    "units": "mm/month/decade",
                    "long_name": "Sen's Slope Trend in Monthly Precipitation",
                    "description": "Linear trend in monthly precipitation anomalies derived from Sen's slope estimator (per-month slope * 120).",
                },
            ),
            "p_value": (
                ("lat", "lon"),
                p_values,
                {
                    "units": "1",
                    "long_name": "Mann-Kendall Two-Sided p-value",
                    "description": "Two-sided p-value from non-parametric Mann-Kendall trend test.",
                    "valid_range": [0.0, 1.0],
                },
            ),
            "significant": (
                ("lat", "lon"),
                significance,
                {
                    "units": "1",
                    "long_name": "Trend Significance Flag (p < 0.05)",
                    "description": "Binary significance indicator: 1 where p < 0.05, 0 elsewhere.",
                    "flag_values": [0, 1],
                    "flag_meanings": "not_significant significant",
                },
            ),
        },
        coords={
            "lat": ds["lat"],
            "lon": ds["lon"],
        },
        attrs={
            "title": "GPM IMERG V07 Precipitation Trend & Mann-Kendall Significance (2000-2025)",
            "source": "NASA GPM IMERG Final Monthly V07",
            "methodology": "Mann-Kendall non-parametric trend test and Sen's slope estimator",
            "slope_conversion": "per-month Sen's slope * 120 = mm/month per decade",
            "period": f"{str(ds['time'].values[0])[:10]} to {str(ds['time'].values[-1])[:10]}",
            "created_at": datetime.utcnow().isoformat(),
            "conventions": "CF-1.8",
        },
    )

    print(f"[*] Saving trend dataset to {TREND_FILE}...")
    encoding = {
        "sens_slope": {"zlib": True, "complevel": 4, "dtype": "float32"},
        "p_value": {"zlib": True, "complevel": 4, "dtype": "float32"},
        "significant": {"zlib": True, "complevel": 4, "dtype": "int8"},
    }
    ds_trend.to_netcdf(TREND_FILE, encoding=encoding)
    ds.close()

    file_size_kb = TREND_FILE.stat().st_size / 1024
    print(f"[+] Successfully generated {TREND_FILE} ({file_size_kb:.1f} KB)")


def main() -> int:
    try:
        run_trend_analysis()
        return 0
    except Exception as exc:
        print(f"[-] Trend calculation FAILED: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
