# Kendall - Goal 1: Verified Precipitation Trend Pipeline

NASA Space Apps Challenge / Earth Science Variable Trend Detection.

## Overview
This pipeline ingests global monthly precipitation observations, performs conservative spatial regridding, computes monthly anomalies relative to multi-year climatology, and calculates pixel-wise linear trends using the non-parametric Mann-Kendall test with Sen's slope estimator.

- **Primary Dataset**: GPM IMERG Final Monthly V07 (`GPM_3IMERGM_07`) (2000–2025, 0.1° resolution).
- **Fallback Dataset**: GLDAS Noah Land Surface Model Monthly Rainfall (`GLDAS_NOAH025_M_2.1`).
- **Spatial Resolution**: Global 2.5° × 2.5° grid (conservative area-weighted averaging).
- **Statistical Metric**: Sen's slope ($\text{mm / month / decade}$) with Mann-Kendall test ($p < 0.05$).

## Folder Structure
```
.
├── .gitignore
├── README.md
├── requirements.txt
├── data/
│   ├── raw/                  # Downloaded raw HDF5/NetCDF granules
│   └── processed/            # Final pipeline outputs (precip_anomalies.nc, precip_trend.nc)
└── src/
    ├── test_access.py        # Single-month authentication & catalog test
    ├── download.py           # Bulk downloader with resuming & integrity checks
    ├── preprocess.py         # Regridding, unit conversion & anomaly derivation
    ├── trend.py              # Parallelized Mann-Kendall & Sen's slope trend estimation
    └── validate.py           # Verification suite (NaNs, global bounds, regional signs)
```

## Environment & Prerequisites

This pipeline requires Python 3.11 managed via Conda:

```bash
conda activate plot-twist
pip install -r requirements.txt
```

### Credentials
NASA Earthdata login credentials must be set in your environment:
```bash
export EARTHDATA_USERNAME="your_username"
export EARTHDATA_PASSWORD="your_password"
```
*(Never hardcode or commit credentials).*

## Verification & Testing Suite

The repository includes a comprehensive, automated multi-layer test and audit suite spanning data completeness, numerical physics, statistical equivalence, and headless browser interactions.

### Unified Single-Command Runner

Execute the entire four-stage audit in a single command:

```bash
bash scripts/run_all_checks.sh
# or
make audit
```

### Environment Architecture

The project utilizes Anaconda environments to separate heavy geospatial C-extensions from headless browser drivers:
1. **Scientific & Statistical Environment (`plot-twist`)**:
   - Location: `/opt/anaconda3/envs/plot-twist`
   - Python: 3.11 with `xarray`, `scipy`, `numpy`, `netCDF4`, `h5py`, `pymannkendall`, `pandas`, `pytest`.
   - Runs: Data integrity audits (`src/audit.py`) and numerical/regression test suites (`tests/`).
2. **Headless Browser Environment (`base`)**:
   - Location: `/opt/anaconda3`
   - Python: 3.13 with `playwright`, `pytest-playwright`, connected to Brave / Chromium.
   - Runs: Browser smoke test suite (`tests/test_browser_smoke.py`).
3. **Client JavaScript Engine (`node`)**:
   - Node.js v22.x runs `tests/validate_js_stats.js` to verify exact statistical parity between the client's in-browser math and backend Python calculations.

The orchestrator script `scripts/run_all_checks.sh` automatically routes each stage to its dedicated runtime.

