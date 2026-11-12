"""Unit tests for spatial regridding, area conservation, and land-masking."""

import pytest
import numpy as np
import sys
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from process import regrid_imerg_block, regrid_gldas_block, TARGET_LATS, TARGET_LONS


class TestRegridding:
    def test_constant_field_imerg(self):
        """A constant field on native 0.1° grid must remain constant on 2.5° grid."""
        raw_lats = np.linspace(-89.95, 89.95, 1800, dtype=np.float32)
        const_val = 42.5
        raw_data = np.full((1800, 3600), const_val, dtype=np.float32)
        
        regridded = regrid_imerg_block(raw_data, raw_lats)
        assert regridded.shape == (72, 144)
        valid = np.isfinite(regridded)
        assert np.all(valid)
        assert np.allclose(regridded, const_val, atol=1e-5)

    def test_constant_field_gldas(self):
        """A constant field on native 0.25° GLDAS grid must stay constant in GLDAS domain."""
        raw_lats = np.linspace(-59.875, 89.875, 600, dtype=np.float32)
        const_val = 18.0
        raw_data = np.full((600, 1440), const_val, dtype=np.float32)

        regridded = regrid_gldas_block(raw_data, raw_lats, min_land_fraction=0.50)
        assert regridded.shape == (72, 144)
        # Rows 0..11 are Antarctica / outside GLDAS -> NaN
        assert np.all(np.isnan(regridded[:12, :]))
        # Rows 12..71 are inside GLDAS domain -> constant 18.0
        assert np.allclose(regridded[12:, :], const_val, atol=1e-5)

    def test_global_mean_preservation_imerg(self):
        """Area-weighted global mean on native 0.1° grid must match 2.5° grid within 0.5%."""
        np.random.seed(42)
        raw_lats = np.linspace(-89.95, 89.95, 1800, dtype=np.float32)
        
        # Synthetic field with smooth latitudinal gradient and noise
        lat_grad = np.cos(np.deg2rad(raw_lats))[:, np.newaxis]
        raw_data = (lat_grad * 50.0 + np.random.uniform(5.0, 20.0, size=(1800, 3600))).astype(np.float32)

        # Native cosine-latitude weighted global mean
        cos_lats_native = np.cos(np.deg2rad(raw_lats))[:, np.newaxis]
        native_mean = float(np.sum(raw_data * cos_lats_native) / (np.sum(cos_lats_native) * 3600))

        # Regrid to 2.5°
        regridded = regrid_imerg_block(raw_data, raw_lats)

        # 2.5° cosine-latitude weighted global mean
        cos_lats_target = np.cos(np.deg2rad(TARGET_LATS))[:, np.newaxis]
        target_mean = float(np.sum(regridded * cos_lats_target) / (np.sum(cos_lats_target) * 144))

        rel_diff = abs(target_mean - native_mean) / native_mean
        print(f"Native mean: {native_mean:.4f}, Regridded mean: {target_mean:.4f}, Rel diff: {rel_diff * 100:.3f}%")
        assert rel_diff < 0.005  # Within 0.5%

    def test_land_mask_threshold_gldas(self):
        """Blocks with < 50% valid land data must be masked as NaN, >= 50% kept."""
        raw_lats = np.linspace(-59.875, 89.875, 600, dtype=np.float32)
        raw_data = np.full((600, 1440), 10.0, dtype=np.float32)

        # In block (row=0, col=0) of GLDAS (corresponding to target row 12, col 0):
        # Set 60 of 100 cells to NaN (40% valid -> should be masked to NaN)
        raw_data[0:6, 0:10] = np.nan

        # In block (row=0, col=1) of GLDAS (target row 12, col 1):
        # Set 40 of 100 cells to NaN (60% valid -> should remain valid)
        raw_data[0:4, 10:20] = np.nan

        regridded = regrid_gldas_block(raw_data, raw_lats, min_land_fraction=0.50)

        # Block (12, 0) should be NaN (40% < 50%)
        assert np.isnan(regridded[12, 0])

        # Block (12, 1) should be valid (60% >= 50%)
        assert np.isfinite(regridded[12, 1])
        assert np.isclose(regridded[12, 1], 10.0)
