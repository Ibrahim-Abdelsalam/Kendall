# Kendall: Planetary Climate Trend & Era Shift Detector (2000–2025)

> **"Find the trends that are real."**  
> *Named after the Mann-Kendall non-parametric trend test.*  
> Built for the **NASA Space Apps Challenge** · Earth Science & Open Science.

[![NASA Space Apps Challenge](https://img.shields.io/badge/NASA%20Space%20Apps-Challenge%20Submission-0B3D91?style=flat-square&logo=nasa)](https://www.spaceappschallenge.org)
[![Zero Backend Architecture](https://img.shields.io/badge/Architecture-100%25%20In--Browser%20Zero--Backend-10B981?style=flat-square)](web/)
[![Planetary Datasets](https://img.shields.io/badge/NASA%20Data-12%20Planetary%20Variables-22D3EE?style=flat-square)](src/variables.yaml)
[![Temporal Extent](https://img.shields.io/badge/Coverage-25.33%20Years%20(304%20Months)-F59E0B?style=flat-square)](web/data/)
[![License](https://img.shields.io/badge/License-Apache%202.0-34D399?style=flat-square)](LICENSE)

---

## Quick Start

Kendall runs **100% in your browser** with **zero backend servers**, **no database**, and **no API keys**. The entire 25.33-year global dataset (~38.9 MB) loads directly onto your client machine.

### 1. Clone & Enter the Repository

```bash
git clone https://github.com/Ibrahim-Abdelsalam/Kendall.git
cd Kendall
```

### 2. Start the Local Server

```bash
# Option A: Using Python (Simplest & Recommended)
python -m http.server 8000 --directory web

# Or with Make:
make serve
```

Then open your browser and navigate to:
**[http://localhost:8000](http://localhost:8000)**

*(Alternative with Node.js: `npx serve web -p 8000`).*

---

## What is Kendall?

When a farmer suffers three dry summers in a row, or a city faces repeated record rainfall, the critical question is: **"Is our regional climate permanently changing, or is this natural weather variability?"**

Raw climate maps often mislead because:
1. **Seasons dominate**: Comparing July to January measures seasonal cycles, not climate change.
2. **Weather memory**: Consecutive wet or dry months fool ordinary linear regressions into reporting false trends.
3. **Sensor transitions**: In 2014, NASA transitioned from TRMM to GPM satellites—a sensor change that can easily masquerade as an abrupt climate shift.

**Kendall** analyzes **25.33 continuous years (304 consecutive months: June 2000 – September 2025)** of NASA satellite observations and global reanalysis across **10,368 global grid cells**. By applying robust non-parametric mathematics, it separates true, statistically verified climate trends ($p < 0.05$) from short-term weather noise.

---

## Mission Control Features

- **Interactive 3D Globe & 2D Flat Map**: Smoothly morph between an orthographic 3D WebGL globe and an equirectangular flat map with MapLibre GL.
- **Point & Custom Region Analysis**: Click any coordinate on Earth or draw a custom bounding polygon to compute instant aggregate trends and area-weighted statistics.
- **Clear Statistical Verdicts**:
  - **Significant Trend**: Strong multi-decadal signal verified after Hamed-Rao autocorrelation correction and False Discovery Rate (FDR) control.
  - **Trending, Not Yet Significant**: A visible slope exists, but 25 years of data is not yet sufficient to mathematically rule out chance.
  - **No Trend**: Historical fluctuations remain within expected natural variance.
- **Detectability Clock**: Calculates the exact minimum years of continuous observation required before the regional trend becomes statistically detectable above background noise.
- **2014 Satellite Sensor Shift Guard**: Flags potential sensor transition artifacts in precipitation data around the 2014 TRMM-to-GPM constellation upgrade.
- **Multiple-Testing "Looks" Counter**: Tracks analytical exploratory queries and warns researchers when repeated testing elevates the risk of accidental false discoveries ($1 - (1 - 0.05)^m$).
- **Multi-Variable Cross-Check Lineup**: Compare multiple NASA planetary variables side-by-side to cross-validate physical consistency (e.g., rainfall decrease vs. soil moisture deficit vs. evapotranspiration).
- **304-Month Timeline Scrubber**: Animate monthly planetary anomalies from June 2000 through September 2025 with playback speed controls.

---

## The 12 NASA Planetary Datasets

Kendall harmonizes 12 planetary climate variables onto a unified 2.5° × 2.5° global grid (72 latitudes × 144 longitudes) over 304 contiguous months (June 2000 – September 2025):

| Variable ID | Dataset Name | Source Mission / Model | Canonical Units |
| :--- | :--- | :--- | :---: |
| `gpm_precip` | **Precipitation Rate** | NASA GPM IMERG Final Monthly V07B | $\text{mm/month}$ |
| `gldas_precip` | **Precipitation Flux** | NASA GLDAS Noah Land Surface Model 2.1 | $\text{mm/month}$ |
| `gldas_soil_moist`| **Soil Moisture (0–10 cm topsoil)** | NASA GLDAS Noah Land Surface Model 2.1 | $\text{kg/m}^2$ |
| `gldas_temp` | **2m Air Temperature** | NASA GLDAS Noah Land Surface Model 2.1 | $^\circ\text{C}$ |
| `gldas_evap` | **Total Evapotranspiration** | NASA GLDAS Noah Land Surface Model 2.1 | $\text{mm/month}$ |
| `merra2_aod` | **Aerosol Optical Depth (550 nm)** | NASA MERRA-2 Atmospheric Reanalysis | $\text{dimensionless}$ |
| `gldas_swe` | **Snow Water Equivalent (SWE)** | NASA GLDAS Noah Land Surface Model 2.1 | $\text{kg/m}^2$ |
| `gldas_snow_depth`| **Snow Depth** | NASA GLDAS Noah Land Surface Model 2.1 | $\text{m}$ |
| `merra2_ts` | **Skin / Surface Temperature** | NASA MERRA-2 Atmospheric Reanalysis | $^\circ\text{C}$ |
| `merra2_wind` | **10m Surface Wind Speed** | NASA MERRA-2 Atmospheric Reanalysis | $\text{m/s}$ |
| `merra2_ps` | **Surface Atmospheric Pressure** | NASA MERRA-2 Atmospheric Reanalysis | $\text{hPa}$ |
| `merra2_tqv` | **Precipitable Water Vapor** | NASA MERRA-2 Atmospheric Reanalysis | $\text{kg/m}^2$ |

---

## Scientific Methodology: 3-Filter Verification

1. **Filter 1: Deseasonalization (Historical Same-Month Baseline)**  
   Each month's value is compared strictly against the 25-year historical average for that calendar month (e.g., July 2024 vs. all Julys from 2000 to 2025). This strips away regular annual cycles.
2. **Filter 2: Theil-Sen Robust Median Estimator**  
   Ordinary least-squares regressions can be heavily distorted by a single anomalous drought or storm. The Theil-Sen estimator calculates the median slope across all pairwise observations, providing outlier-resistant trend quantification.
3. **Filter 3: Hamed-Rao Autocorrelation Correction + FDR Control**  
   Sequential climate observations exhibit temporal persistence (weather memory). Kendall calculates the effective sample size ($n^*$) using the Hamed-Rao variance inflation factor to avoid false positive significance alarms, paired with Benjamini-Hochberg False Discovery Rate (FDR) control across all 10,368 grid cells.

---

## Python Environment & Scientific Pipeline (Optional)

To run the scientific audit or reproduce the data processing pipeline, set up the **Conda** environment:

```bash
# 1. Create and activate the conda environment
conda create -n kendall python=3.11 -y
conda activate kendall

# 2. Install dependencies
pip install -r requirements.txt
```

### Run Scientific Data Audit

Verify the completeness, integrity, and quantization accuracy of all 12 datasets:

```bash
make audit-data
# or:
python src/audit.py
```

### Reproduce Data Ingest (Optional)

If downloading new granules or recomputing grids from NASA Earthdata:

```bash
export EARTHDATA_USERNAME="your_username"
export EARTHDATA_PASSWORD="your_password"

# Example: Process a variable through the pipeline
python src/download.py --var gpm_precip
python src/process.py --var gpm_precip
python src/trend_all.py --var gpm_precip
python src/export_web.py --var gpm_precip
```

---

## Repository Structure

The layout below mirrors the exact directory structure of the repository:

```
.
├── .gitignore                         # Git exclusion rules (ignores raw data, tracks web/data)
├── LICENSE                            # Open-source Apache License 2.0
├── Makefile                           # Command shortcuts (make serve, make audit-data)
├── README.md                          # Project documentation and setup guide
├── requirements.txt                   # Pipeline dependencies (xarray, netCDF4, pymannkendall)
├── src/                               # Scientific data processing & audit pipeline
│   ├── audit.py                       # 10-point completeness & integrity audit
│   ├── auth.py                        # NASA Earthdata authentication handler
│   ├── cross_check.py                 # Multi-variable physical consistency validator
│   ├── download.py                    # Bulk granule downloader for GES DISC & GMAO
│   ├── export_web.py                  # Domain-aware int16 typed array compressor
│   ├── fetch.py                       # Generic granule fetcher with retry logic
│   ├── fetch_aerosols.py              # MERRA-2 aerosol optical depth fetcher
│   ├── fetch_merra2_slv.py            # MERRA-2 single-level atmospheric variables fetcher
│   ├── loader.py                      # Local NetCDF/HDF5 granule reader
│   ├── plot_trends.py                 # Trend visualization & debug plotter
│   ├── preprocess.py                  # Spatial regridding and anomaly calculation
│   ├── process.py                     # Generic preprocessing and regridding engine
│   ├── trend.py                       # Mann-Kendall and Sen's slope algorithm
│   ├── trend_all.py                   # Parallelized batch trend estimator
│   ├── validate.py                    # Data sanity, bounds, and sign validator
│   ├── variables.py                   # Variable catalog schemas and dataclasses
│   └── variables.yaml                 # Formal registry of all 12 NASA variables
└── web/                               # Standalone client application (100% in-browser)
    ├── app.js                         # WebGL MapLibre globe, stats engine & UI controls
    ├── countries-110m.json            # Base world geography TopoJSON
    ├── favicon.ico                    # Browser favicon
    ├── icons/                         # Application icons & PWA assets
    │   ├── apple-touch-icon.png
    │   ├── favicon-16x16.png
    │   ├── favicon-32x32.png
    │   ├── favicon.svg
    │   ├── icon-192.png
    │   ├── icon-512.png
    │   ├── kendall.svg
    │   └── og-image.png
    ├── index.html                     # Mission Control UI layout
    ├── manifest.webmanifest           # Progressive Web App manifest
    ├── style.css                      # Design tokens, CRT theme & responsive HUD
    ├── topojson-client.min.js         # TopoJSON parser library
    └── data/                          # Compressed binary anomaly data (12 datasets, ~38.9 MB)
        ├── gldas_evap/                # Total Evapotranspiration
        ├── gldas_precip/              # Precipitation Flux (GLDAS)
        ├── gldas_snow_depth/          # Snow Depth
        ├── gldas_soil_moist/          # Topsoil Moisture (0-10 cm)
        ├── gldas_swe/                 # Snow Water Equivalent
        ├── gldas_temp/                # 2m Air Temperature
        ├── gpm_precip/                # Precipitation Rate (GPM IMERG V07B)
        ├── merra2_aod/                # Aerosol Optical Depth (550 nm)
        ├── merra2_ps/                 # Surface Atmospheric Pressure
        ├── merra2_tqv/                # Total Precipitable Water Vapor
        ├── merra2_ts/                 # Surface Skin Temperature
        └── merra2_wind/               # 10m Surface Wind Speed
```

---

## License & Credits

- **Application Code**: Open-source under the [Apache License 2.0](LICENSE).
- **NASA Data Sources**: Publicly provided by NASA Earth Science Data Systems (GES DISC, GMAO, GPM Science Team, GLDAS Science Team).
