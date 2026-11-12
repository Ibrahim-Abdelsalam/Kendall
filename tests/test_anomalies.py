"""Unit tests for monthly climatology and anomaly derivation."""

import pytest
import numpy as np
import pandas as pd


class TestAnomalies:
    def test_anomalies_zero_climatology(self):
        """The multi-year mean of anomalies for each calendar month must equal zero."""
        np.random.seed(42)
        n_years = 25
        n_months = n_years * 12
        dates = pd.date_range("2000-01-01", periods=n_months, freq="MS")

        # Seasonal cycle + random interannual noise
        seasonal_cycle = np.array([20, 25, 40, 70, 95, 120, 110, 90, 60, 45, 30, 22])
        raw_series = np.zeros(n_months)
        for i, dt in enumerate(dates):
            raw_series[i] = seasonal_cycle[dt.month - 1] + np.random.normal(0, 10.0)

        # Compute climatology per calendar month (1..12)
        df = pd.DataFrame({"val": raw_series, "month": dates.month})
        climatology = df.groupby("month")["val"].transform("mean")
        anomalies = df["val"] - climatology

        # Verify that for each calendar month, mean anomaly is ~ 0.0
        month_mean_anomalies = anomalies.groupby(dates.month).mean()
        for m in range(1, 13):
            assert abs(month_mean_anomalies[m]) < 1e-12

    def test_anomalies_uneven_record(self):
        """Handles uneven record length (e.g. 26 years of Jun-Sep, 25 years of other months)."""
        # Exact record structure of Kendall: 2000-06 to 2025-09 (304 months)
        dates = pd.date_range("2000-06-01", "2025-09-01", freq="MS")
        assert len(dates) == 304

        np.random.seed(123)
        raw_vals = np.random.uniform(50, 150, size=304)

        df = pd.DataFrame({"val": raw_vals, "month": dates.month})
        climatology = df.groupby("month")["val"].transform("mean")
        anomalies = df["val"] - climatology

        month_mean_anoms = anomalies.groupby(dates.month).mean()
        for m in range(1, 13):
            assert abs(month_mean_anoms[m]) < 1e-12
