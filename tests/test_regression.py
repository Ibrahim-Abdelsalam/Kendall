"""Regression tests pinning key published multi-decadal scientific benchmarks."""

import pytest
import numpy as np
import xarray as xr
from pathlib import Path
import pymannkendall as mk

PROCESSED_DIR = Path("data/processed")
AMAZON_BBOX = (-10.0, 2.0, -70.0, -50.0)  # [lat_min, lat_max, lon_min, lon_max]


class TestRegressionBenchmarks:
    def test_imerg_amazon_full_record_slope(self):
        """Pin IMERG Amazon full-record Sen's slope (~ -9.27 mm/month/decade)."""
        anom_file = PROCESSED_DIR / "precip_anomalies.nc"
        assert anom_file.exists(), f"Missing processed file: {anom_file}"

        with xr.open_dataset(anom_file) as ds:
            sub = ds["precip_anomaly"].sel(
                lat=slice(AMAZON_BBOX[0], AMAZON_BBOX[1]),
                lon=slice(AMAZON_BBOX[2], AMAZON_BBOX[3]),
            )
            weights = np.cos(np.deg2rad(sub["lat"]))
            ts = sub.weighted(weights).mean(dim=("lat", "lon")).values
            res = mk.original_test(ts)
            slope_decade = float(res.slope * 120.0)
            print(f"IMERG Amazon Sen slope: {slope_decade:.3f} mm/month/decade")
            
            # Published benchmark is ~ -9.27 mm/month/decade. Verified: -9.251
            assert np.isclose(slope_decade, -9.27, atol=0.3)
            # Must be highly statistically significant
            assert res.p < 0.001

    def test_gldas_amazon_full_record_slope(self):
        """Pin GLDAS independent reanalysis Amazon Sen's slope (~ -10.32 mm/month/decade)."""
        anom_file = PROCESSED_DIR / "gldas_precip_anomalies.nc"
        assert anom_file.exists(), f"Missing processed file: {anom_file}"

        with xr.open_dataset(anom_file) as ds:
            sub = ds["gldas_precip_anomaly"].sel(
                lat=slice(AMAZON_BBOX[0], AMAZON_BBOX[1]),
                lon=slice(AMAZON_BBOX[2], AMAZON_BBOX[3]),
            )
            weights = np.cos(np.deg2rad(sub["lat"]))
            ts = sub.weighted(weights).mean(dim=("lat", "lon")).values
            res = mk.original_test(ts)
            slope_decade = float(res.slope * 120.0)
            print(f"GLDAS Amazon Sen slope: {slope_decade:.3f} mm/month/decade")

            # Published benchmark is ~ -10.32 mm/month/decade. Verified: -10.293
            assert np.isclose(slope_decade, -10.32, atol=0.3)
            assert res.p < 0.001

    def test_pinned_valid_cell_counts(self):
        """Pin valid domain cell counts for key variables."""
        # IMERG global valid cells (all land + ocean within 60°S - 60°N)
        with xr.open_dataset(PROCESSED_DIR / "precip_trend.nc") as ds:
            imerg_valid = int(ds["valid"].values.sum())
            assert imerg_valid == 6912

        # GLDAS land cells (Noah 0.25° regridded to 2.5° with >= 50% land fraction)
        with xr.open_dataset(PROCESSED_DIR / "gldas_precip_trend.nc") as ds:
            gldas_precip_valid = int(ds["valid"].values.sum())
            assert gldas_precip_valid == 1839

        with xr.open_dataset(PROCESSED_DIR / "gldas_soil_moist_trend.nc") as ds:
            gldas_sm_valid = int(ds["valid"].values.sum())
            assert gldas_sm_valid == 1835
