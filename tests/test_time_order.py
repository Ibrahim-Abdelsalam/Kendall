"""Permanent Time Order & Chronological Continuity Test Suite for Kendall.

Validates that:
  1. Every processed anomaly NetCDF cube (data/processed/*_anomalies.nc) has a strictly
     monotonic, monthly time axis with no gaps and no duplicate months.
  2. Every cube starts at 2000-06 and terminates at 2025-09 (304 contiguous months).
  3. For all MERRA-2 collections (merra2_aod, merra2_ts, merra2_wind, merra2_ps, merra2_tqv),
     the five instrument-anomaly recovery months (2020-09, 2021-06, 2021-07, 2021-08, 2021-09)
     sit at their true chronological positions in the time coordinate rather than being sorted
     to the end of the array due to stream name lexicography (MERRA2_401 vs MERRA2_400).
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import xarray as xr


PROCESSED_DIR = Path("data/processed")

MERRA2_VARIABLES = [
    "merra2_aod",
    "merra2_ts",
    "merra2_wind",
    "merra2_ps",
    "merra2_tqv",
]

ALL_VARIABLES = [
    "gpm_precip",
    "gldas_precip",
    "gldas_soil_moist",
    "gldas_temp",
    "gldas_evap",
    "merra2_aod",
    "gldas_swe",
    "gldas_snow_depth",
    "merra2_ts",
    "merra2_wind",
    "merra2_ps",
    "merra2_tqv",
]


def test_processed_cubes_exist():
    """Verify that all processed anomaly files exist."""
    for var_id in ALL_VARIABLES:
        anom_file = PROCESSED_DIR / f"{var_id}_anomalies.nc"
        assert anom_file.exists(), f"Missing processed anomaly file: {anom_file}"


@pytest.mark.parametrize("var_id", ALL_VARIABLES)
def test_time_axis_strictly_increasing_contiguous(var_id: str):
    """Test that time axis is strictly increasing by exactly 1 calendar month with no gaps."""
    anom_file = PROCESSED_DIR / f"{var_id}_anomalies.nc"
    with xr.open_dataset(anom_file) as ds:
        times = pd.to_datetime(ds["time"].values)

        assert len(times) == 304, f"{var_id}: Expected 304 months, found {len(times)}"
        assert times[0] == pd.Timestamp("2000-06-01"), f"{var_id}: Expected start 2000-06-01, got {times[0]}"
        assert times[-1] == pd.Timestamp("2025-09-01"), f"{var_id}: Expected end 2025-09-01, got {times[-1]}"

        # Check no duplicates
        unique_times = np.unique(times)
        assert len(unique_times) == len(times), f"{var_id}: Duplicate timestamps detected"

        # Check strictly increasing by 1 month
        for i in range(len(times) - 1):
            t_curr = times[i]
            t_next = times[i + 1]
            month_diff = (t_next.year - t_curr.year) * 12 + (t_next.month - t_curr.month)
            assert month_diff == 1, (
                f"{var_id}: Non-contiguous time jump from {t_curr.strftime('%Y-%m')} to "
                f"{t_next.strftime('%Y-%m')} at index {i}"
            )


@pytest.mark.parametrize("var_id", MERRA2_VARIABLES)
def test_merra2_stream_401_months_at_true_chronological_positions(var_id: str):
    """Verify that the 5 MERRA2_401 months sit at their true chronological indices.

    Chronological Index Formulas relative to 2000-06 (index 0):
      2020-09: (2020 - 2000)*12 + (9 - 6) = 240 + 3 = index 243
      2021-06: (2021 - 2000)*12 + (6 - 6) = 252 + 0 = index 252
      2021-07: index 253
      2021-08: index 254
      2021-09: index 255
      2025-09: index 303 (final month)
    """
    anom_file = PROCESSED_DIR / f"{var_id}_anomalies.nc"
    with xr.open_dataset(anom_file) as ds:
        times = pd.to_datetime(ds["time"].values)

        # 1. 2020-09 must be at index 243
        assert times[243] == pd.Timestamp("2020-09-01"), (
            f"{var_id}: 2020-09 is not at true chronological index 243, found {times[243]}"
        )
        assert times[242] == pd.Timestamp("2020-08-01"), f"{var_id}: Preceding month mismatch at 242"
        assert times[244] == pd.Timestamp("2020-10-01"), f"{var_id}: Following month mismatch at 244"

        # 2. 2021-06 through 2021-09 must be at indices 252 to 255
        expected_2021 = [
            (252, pd.Timestamp("2021-06-01")),
            (253, pd.Timestamp("2021-07-01")),
            (254, pd.Timestamp("2021-08-01")),
            (255, pd.Timestamp("2021-09-01")),
        ]
        for idx, expected_dt in expected_2021:
            assert times[idx] == expected_dt, (
                f"{var_id}: Month {expected_dt.strftime('%Y-%m')} not at index {idx}, found {times[idx]}"
            )
        assert times[251] == pd.Timestamp("2021-05-01"), f"{var_id}: Preceding month mismatch at 251"
        assert times[256] == pd.Timestamp("2021-10-01"), f"{var_id}: Following month mismatch at 256"

        # 3. Last month must be 2025-09 at index 303
        assert times[303] == pd.Timestamp("2025-09-01"), (
            f"{var_id}: Last month (index 303) should be 2025-09-01, found {times[303]}"
        )
