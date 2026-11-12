"""Unit tests for physical and temporal unit conversions."""

import calendar
import pytest
import numpy as np


def convert_mm_hr_to_mm_month(rate_mm_hr: float, year: int, month: int) -> float:
    """Convert mm/hr precipitation rate to monthly accumulation in mm/month."""
    days = calendar.monthrange(year, month)[1]
    hours = days * 24.0
    return rate_mm_hr * hours


def convert_kg_m2_s_to_mm_month(flux_kg_m2_s: float, year: int, month: int) -> float:
    """Convert water flux (kg/m^2/s = mm/s) to monthly accumulation in mm/month."""
    days = calendar.monthrange(year, month)[1]
    seconds = days * 86400.0
    return flux_kg_m2_s * seconds


def convert_kelvin_to_celsius(temp_k: float) -> float:
    """Convert absolute temperature Kelvin to degrees Celsius."""
    return temp_k - 273.15


class TestUnitConversions:
    def test_mm_hr_to_mm_month_leap_year(self):
        # 2024 is a leap year -> Feb has 29 days = 696 hours
        rate = 1.0  # mm/hr
        feb_2024 = convert_mm_hr_to_mm_month(rate, 2024, 2)
        assert feb_2024 == 29 * 24.0
        assert feb_2024 == 696.0

        # 2023 is non-leap year -> Feb has 28 days = 672 hours
        feb_2023 = convert_mm_hr_to_mm_month(rate, 2023, 2)
        assert feb_2023 == 28 * 24.0
        assert feb_2023 == 672.0

        # Difference between leap and non-leap February is exactly 24 hours
        assert feb_2024 - feb_2023 == 24.0

    def test_mm_hr_to_mm_month_standard_months(self):
        rate = 0.5  # mm/hr
        # January: 31 days = 744 hours -> 372 mm
        assert convert_mm_hr_to_mm_month(rate, 2021, 1) == 31 * 24 * 0.5
        # April: 30 days = 720 hours -> 360 mm
        assert convert_mm_hr_to_mm_month(rate, 2021, 4) == 30 * 24 * 0.5

    def test_kg_m2_s_to_mm_month(self):
        # 1 kg/m^2/s = 1 mm/s of water (density 1000 kg/m^3)
        flux = 1e-5  # kg/m^2/s
        # 30-day month (April): 30 * 86400 = 2,592,000 s -> 25.92 mm/month
        val_apr = convert_kg_m2_s_to_mm_month(flux, 2021, 4)
        assert np.isclose(val_apr, 25.92)

        # 31-day month (July): 31 * 86400 = 2,678,400 s -> 26.784 mm/month
        val_jul = convert_kg_m2_s_to_mm_month(flux, 2021, 7)
        assert np.isclose(val_jul, 26.784)

        # February leap vs non-leap
        val_feb_leap = convert_kg_m2_s_to_mm_month(flux, 2020, 2)
        val_feb_non_leap = convert_kg_m2_s_to_mm_month(flux, 2021, 2)
        assert np.isclose(val_feb_leap, 29 * 86400 * 1e-5)
        assert np.isclose(val_feb_non_leap, 28 * 86400 * 1e-5)
        assert val_feb_leap > val_feb_non_leap

    def test_kelvin_to_celsius(self):
        assert np.isclose(convert_kelvin_to_celsius(273.15), 0.0)
        assert np.isclose(convert_kelvin_to_celsius(373.15), 100.0)
        assert np.isclose(convert_kelvin_to_celsius(0.0), -273.15)
        assert np.isclose(convert_kelvin_to_celsius(293.15), 20.0)
