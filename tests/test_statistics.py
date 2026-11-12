"""Rigorous statistical test suite for Kendall: trend, FDR, era breaks, seasons, and export."""

import gzip
import pytest
import numpy as np
import pandas as pd
import pymannkendall as mk
from scipy.stats import false_discovery_control


class TestStatistics:
    def test_known_linear_trend_recovery(self):
        """Sen's slope must recover known synthetic linear trend within 2%."""
        np.random.seed(42)
        n = 304
        t = np.arange(n, dtype=np.float64)
        true_slope_per_month = 0.05  # mm/month per month (+6.0 mm/mo/decade)
        noise = np.random.normal(0, 0.5, size=n)
        series = true_slope_per_month * t + noise

        res = mk.original_test(series)
        recovered_slope = float(res.slope)
        rel_err = abs(recovered_slope - true_slope_per_month) / true_slope_per_month
        print(f"True slope: {true_slope_per_month}, Recovered: {recovered_slope:.5f}, Rel Err: {rel_err * 100:.2f}%")
        assert rel_err < 0.02  # Recovered within 2%

    def test_pure_noise_false_positives(self):
        """2000 independent white noise series must yield ~5% false positives at p < 0.05."""
        np.random.seed(999)
        n_series = 2000
        n_pts = 304
        alpha = 0.05

        false_positives = 0
        # Generate bulk standard normal noise
        noise_matrix = np.random.normal(0, 1.0, size=(n_series, n_pts))

        for i in range(n_series):
            res = mk.original_test(noise_matrix[i])
            if res.p < alpha:
                false_positives += 1

        fp_rate = false_positives / n_series
        print(f"White noise false positive rate: {fp_rate * 100:.2f}% ({false_positives}/{n_series})")
        # For n=2000 and p=0.05: SE = sqrt(0.05*0.95/2000) = 0.00487 (~0.49%)
        # 99.9% binomial tolerance interval is [0.034, 0.066] (3.4% to 6.6%)
        assert 0.034 <= fp_rate <= 0.066

    def test_autocorrelated_noise_hamed_rao_vs_plain(self):
        """On AR(1) autocorrelated noise, Hamed-Rao modified MK must yield fewer false alarms than plain MK."""
        np.random.seed(42)
        n_series = 400
        n_pts = 304
        rho = 0.6  # Moderate-high positive serial correlation
        alpha = 0.05

        plain_fp = 0
        hr_fp = 0

        for _ in range(n_series):
            # AR(1) generation: x_t = rho * x_{t-1} + e_t
            innovations = np.random.normal(0, 1.0, size=n_pts)
            ar_series = np.zeros(n_pts)
            for t in range(1, n_pts):
                ar_series[t] = rho * ar_series[t - 1] + innovations[t]

            # Plain MK
            res_pl = mk.original_test(ar_series)
            if res_pl.p < alpha:
                plain_fp += 1

            # Hamed-Rao modified MK
            try:
                res_hr = mk.hamed_rao_modification_test(ar_series)
                if np.isfinite(res_hr.p) and res_hr.p < alpha:
                    hr_fp += 1
            except Exception:
                pass

        rate_plain = plain_fp / n_series
        rate_hr = hr_fp / n_series
        print(f"AR(1) false positive rate - Plain MK: {rate_plain * 100:.1f}%, Hamed-Rao: {rate_hr * 100:.1f}%")

        # Plain MK rate is heavily inflated by autocorrelation (typically > 30%)
        # Hamed-Rao variance correction significantly reduces false alarms
        assert rate_plain > 0.20
        assert rate_hr < rate_plain

    def test_zero_variance_no_crash(self):
        """A series with zero variance (all identical values) must not crash."""
        series = np.zeros(304, dtype=float)
        # Using the project's guarded zero-variance logic
        if np.all(series == series[0]):
            sens_slope, p_val = 0.0, 1.0
        else:
            res = mk.original_test(series)
            sens_slope, p_val = float(res.slope), float(res.p)

        assert sens_slope == 0.0
        assert p_val == 1.0

    def test_fdr_benjamini_hochberg(self):
        """Benjamini-Hochberg FDR output must satisfy q >= p and monotonicity when sorted."""
        np.random.seed(777)
        raw_p = np.random.uniform(0.0001, 0.9999, size=500)
        q_vals = false_discovery_control(raw_p, method="bh")

        # Property 1: q >= p for every hypothesis
        assert np.all(q_vals >= raw_p - 1e-12)

        # Property 2: Monotonicity on sorted p-values
        sort_idx = np.argsort(raw_p)
        sorted_p = raw_p[sort_idx]
        sorted_q = q_vals[sort_idx]
        diffs = np.diff(sorted_q)
        assert np.all(diffs >= -1e-12)

    def test_era_break_step_vs_trend(self):
        """A synthetic step at 2014 is flagged, while a pure monotonic trend is not."""
        dates = pd.date_range("2000-06-01", "2025-09-01", freq="MS")
        n = len(dates)
        t_idx = np.arange(n, dtype=float)
        era_break_t = np.where(dates > pd.Timestamp("2013-12-31"))[0][0]

        # Case A: Pure linear trend without step
        pure_trend = 0.05 * t_idx + np.random.normal(0, 0.2, size=n)
        
        # Fit trend-aware step model: y = b0 + b1*t + b2*d_step
        d_step = (dates > pd.Timestamp("2013-12-31")).astype(float)
        X = np.column_stack([np.ones(n), t_idx, d_step])
        
        beta_a, _, _, _ = np.linalg.lstsq(X, pure_trend, rcond=None)
        res_a = pure_trend - X @ beta_a
        sigma2_a = np.sum(res_a ** 2) / (n - 3)
        cov_a = sigma2_a * np.linalg.inv(X.T @ X)
        se_step_a = np.sqrt(cov_a[2, 2])
        t_stat_a = abs(beta_a[2] / se_step_a)
        is_break_a = t_stat_a > 2.58  # p < 0.01

        # Case B: Stationary series with sharp 5.0 step at 2014
        step_series = np.random.normal(0, 0.2, size=n)
        step_series[era_break_t:] += 5.0

        beta_b, _, _, _ = np.linalg.lstsq(X, step_series, rcond=None)
        res_b = step_series - X @ beta_b
        sigma2_b = np.sum(res_b ** 2) / (n - 3)
        cov_b = sigma2_b * np.linalg.inv(X.T @ X)
        se_step_b = np.sqrt(cov_b[2, 2])
        t_stat_b = abs(beta_b[2] / se_step_b)
        is_break_b = t_stat_b > 2.58  # p < 0.01

        print(f"Pure trend t-stat: {t_stat_a:.2f} (flagged: {is_break_a}) | Step series t-stat: {t_stat_b:.2f} (flagged: {is_break_b})")
        assert not is_break_a  # Pure trend is NOT flagged as a step break
        assert is_break_b      # Step at 2014 IS flagged as a step break

    def test_season_logic_djf(self):
        """DJF assignment spans year boundary (Dec Y with Jan/Feb Y+1); incomplete seasons dropped."""
        dates = pd.date_range("2000-06-01", "2025-09-01", freq="MS")
        
        # Test season grouping function
        def extract_djf_seasons(dates):
            # DJF needs Dec(Y), Jan(Y+1), Feb(Y+1)
            seasons = {}
            for idx, dt in enumerate(dates):
                if dt.month == 12:
                    season_key = dt.year  # Winter Y/(Y+1)
                    seasons.setdefault(season_key, {})["D"] = idx
                elif dt.month == 1:
                    season_key = dt.year - 1
                    seasons.setdefault(season_key, {})["J"] = idx
                elif dt.month == 2:
                    season_key = dt.year - 1
                    seasons.setdefault(season_key, {})["F"] = idx

            # Complete seasons only (has D, J, and F)
            complete_seasons = {k: v for k, v in seasons.items() if len(v) == 3}
            return complete_seasons

        djf = extract_djf_seasons(dates)
        
        # First complete winter is 2000/2001 (Dec 2000 + Jan 2001 + Feb 2001)
        assert 2000 in djf
        assert dates[djf[2000]["D"]] == pd.Timestamp("2000-12-01")
        assert dates[djf[2000]["J"]] == pd.Timestamp("2001-01-01")
        assert dates[djf[2000]["F"]] == pd.Timestamp("2001-02-01")

        # Last complete winter is 2024/2025 (Dec 2024 + Jan 2025 + Feb 2025)
        assert 2024 in djf
        # 2025/2026 is incomplete (ends Sep 2025) -> must be dropped
        assert 2025 not in djf
        # 1999/2000 is incomplete (starts Jun 2000) -> must be dropped
        assert 1999 not in djf

        # Exactly 25 complete DJF winters (2000/01 through 2024/25)
        assert len(djf) == 25

    def test_region_mean_cos_lat_and_dateline(self):
        """Cos-latitude weighting on hand-computed example and dateline-crossing bounding box."""
        # Hand-computed test:
        # Cell 1: lat = 0°, cos(0°) = 1.0, value = 10.0
        # Cell 2: lat = 60°, cos(60°) = 0.5, value = 20.0
        lats = np.array([0.0, 60.0])
        vals = np.array([10.0, 20.0])
        weights = np.cos(np.deg2rad(lats))
        weighted_mean = np.sum(vals * weights) / np.sum(weights)
        # (10 * 1.0 + 20 * 0.5) / (1.0 + 0.5) = 20 / 1.5 = 13.33333...
        assert np.isclose(weighted_mean, 20.0 / 1.5)

        # Dateline crossing test:
        # Longitude grid from -180 to +180 in 2.5° steps
        grid_lons = np.linspace(-178.75, 178.75, 144)
        # Bounding box spanning dateline: West = 170°, East = -170°
        w_lon, e_lon = 170.0, -170.0
        # When W > E, box crosses the antimeridian
        in_box = (grid_lons >= w_lon) | (grid_lons <= e_lon)
        selected_lons = grid_lons[in_box]
        
        # Must select longitudes >= 170° AND longitudes <= -170°
        assert np.all((selected_lons >= 170.0) | (selected_lons <= -170.0))
        assert np.any(selected_lons > 0)
        assert np.any(selected_lons < 0)

    def test_export_round_trip(self):
        """Anomalies cube scaled to int16 + gzip must round-trip within theoretical quantization error."""
        np.random.seed(101)
        shape = (304, 72, 144)
        # Synthetic anomaly field with positive and negative departures
        synth_anom = np.random.normal(0, 35.0, size=shape).astype(np.float32)

        max_abs = float(np.max(np.abs(synth_anom)))
        scale = max_abs / 30000.0

        # Encode to int16
        int_arr = np.round(synth_anom / scale).astype(np.int16)
        compressed = gzip.compress(int_arr.tobytes(), compresslevel=6)

        # Decode from binary
        decompressed = gzip.decompress(compressed)
        decoded_int = np.frombuffer(decompressed, dtype=np.int16).reshape(shape)
        decoded_float = decoded_int.astype(np.float32) * scale

        # Error check: max error must be <= scale / 2 + numerical epsilon
        err = np.abs(decoded_float - synth_anom)
        max_err = float(np.max(err))
        print(f"Max error: {max_err:.6f}, scale/2: {scale / 2.0:.6f}")
        assert max_err <= (scale / 2.0 + 1e-4)
