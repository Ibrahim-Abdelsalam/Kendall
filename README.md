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

## Running the Pipeline

1. **Test Access**:
   ```bash
   python src/test_access.py
   ```
2. **Download Historical Granules**:
   ```bash
   python src/download.py
   ```
3. **Preprocess & Compute Anomalies**:
   ```bash
   python src/preprocess.py
   ```
4. **Compute Trends & Significance**:
   ```bash
   python src/trend.py
   ```
5. **Validate Output**:
   ```bash
   python src/validate.py
   ```
