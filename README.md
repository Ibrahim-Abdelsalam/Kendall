# Kendall: Planetary Multi-Decadal Trend & Era Shift Detector (2000–2025)

> **"Find the trends that are real."**  
> *Named after the Mann-Kendall non-parametric trend test.*  
> NASA Space Apps Challenge / Earth Science Variable Trend Detection & Open Science.

[![Audit Status](https://img.shields.io/badge/Scientific%20Audit-10%2F10%20PASS-34D399?style=flat-square)](docs/AUDIT.md)
[![Python Tests](https://img.shields.io/badge/Pytest%20Suite-44%20PASS-22D3EE?style=flat-square)](tests/)
[![Browser E2E](https://img.shields.io/badge/Playwright%20E2E-11%20PASS-A78BFA?style=flat-square)](tests/test_browser_smoke.py)
[![Audio Tour](https://img.shields.io/badge/Narrated%20Tour-39%20Steps%20%7C%20Kokoro--82M-FF6B35?style=flat-square)](web/tour/)
[![License](https://img.shields.io/badge/License-Apache%202.0-F59E0B?style=flat-square)](models/kokoro/LICENSE)

---

## Executive Overview

Humanity faces accelerating climate volatility, yet identifying true long-term environmental shifts remains hindered by natural cyclical noise, seasonal distortion, sensor discontinuities between satellite generations, and temporal autocorrelation. 

**Kendall** is an open-science, zero-backend planetary trend analytics platform that ingests **25.33 years (304 consecutive months: June 2000 – September 2025)** of continuous NASA satellite and reanalysis observations across **10,368 global grid cells**. 

By applying robust non-parametric mathematics—monthly climatology anomaly extraction, pixel-wise Sen’s slope magnitude estimation, Hamed-Rao modified Mann-Kendall variance correction, and Benjamini-Hochberg False Discovery Rate (FDR) control—Kendall eliminates subjective guessing and separates authentic climate signals ($p < 0.05$) from sensor discontinuities and random weather noise.

---

## Project Goals & Completion Matrix

All core and extended goals for Project Kendall have been fully implemented, numerically audited, and verified:

| # | Project Goal | Implementation Scope | Verification & Status |
| :-: | :--- | :--- | :---: |
| **1** | **Multi-Decadal NASA Data Ingestion** | 304 contiguous months (2000–2025) across 12 active planetary variables from GPM IMERG, GLDAS Noah, and MERRA-2. Conservative 2.5° area-weighted regridding with polar masking at $\|lat\| > 60^\circ$. | **COMPLETED**<br>*(100% manifest match, 0 polar leaks)* |
| **2** | **Statistical Rigor & Autocorrelation Correction** | Pairwise Sen's slope rate estimation ($\text{units/decade}$), Hamed-Rao variance inflation for lag-1 autocorrelation ($\rho_1$), planetary FDR $q$-value control, and empirical Detectability Clocks. | **COMPLETED**<br>*(44 pytest unit tests pass)* |
| **3** | **2014 Satellite Sensor Transition Diagnostic** | Domain-wide detrended step test across the 2014 TRMM-to-GPM sensor transition. Automatic cautionary regime-shift flags on verdict cards when era slopes flip without sub-period significance. | **COMPLETED**<br>*(Verified against Amazon & Sahel)* |
| **4** | **Zero-Backend Spatial Database (<39 MB)** | Domain-aware int16 binary typed array buffers and gzip compression reducing multi-terabyte raw NASA NetCDF/HDF5 feeds to **38.93 MB** with sub-millimeter quantization error ($<0.6\%$). | **COMPLETED**<br>*(Passes strict 60 MB payload budget)* |
| **5** | **Mission Control Interactive Web Application** | 3D orthographic WebGL globe and 2D Mercator flat map with smooth projection morphing, custom area-weighted bounding box region drawing, monthly scrubber, and Planetary Lineup. | **COMPLETED**<br>*(All 12 variables interactive in browser)* |
| **6** | **Multiple Testing Safeguards ("Looks" Counter)** | Real-time counter tracking exploratory combinations tested. Calculates family-wise false positive risk ($1 - (1-0.05)^m$) with milestone toasts (5, 10, 20 looks) and auto-resets on case start or 3-min inactivity. | **COMPLETED**<br>*(Tested across desktop and mobile)* |
| **7** | **Voice-Narrated Guided Tour System** | 90-second interactive Site Tour (14 steps) and 4 deep-dive Case File narrations (39 steps total). Local Kokoro-82M speech synthesis normalized to -16 LUFS (<3.6 MB bundle) with dynamic SVG mask tracking. | **COMPLETED**<br>*(Zero API keys, Apache 2.0 license)* |
| **8** | **Exhaustive Multi-Layer Audit & Automated Test Suite** | 10-point data completeness audit ([`src/audit.py`](src/audit.py)), 44 Python scientific tests ([`tests/`](tests/)), Node.js client-vs-python parity engine ([`validate_js_stats.js`](tests/validate_js_stats.js)), and 11 Playwright browser E2E tests. | **COMPLETED**<br>*(10/10 Audit sections unconditionally pass)* |

---

## The 12 Active Planetary Datasets

Kendall operates on a unified global 2.5° × 2.5° grid (72 latitudes × 144 longitudes = 10,368 cells; 6,912 non-polar cells) across 304 contiguous months:

| Variable ID | Descriptive Name | Source Instrument / Model | Canonical Units | Trend Rate Units |
| :--- | :--- | :--- | :---: | :---: |
| `gpm_precip` | Precipitation Rate | GPM IMERG Final Monthly V07B | $\text{mm/month}$ | $\text{mm/month/decade}$ |
| `gldas_precip` | Reanalysis Precipitation Flux | GLDAS Noah Land Surface Model 2.1 | $\text{mm/month}$ | $\text{mm/month/decade}$ |
| `gldas_soil_moist`| Soil Moisture (0–10 cm depth) | GLDAS Noah Land Surface Model 2.1 | $\text{kg/m}^2$ | $\text{kg/m}^2\text{/decade}$ |
| `gldas_temp` | 2m Air Temperature | GLDAS Noah Land Surface Model 2.1 | $^\circ\text{C}$ | $^\circ\text{C/decade}$ |
| `gldas_evap` | Total Evapotranspiration | GLDAS Noah Land Surface Model 2.1 | $\text{mm/month}$ | $\text{mm/month/decade}$ |
| `merra2_aod` | Aerosol Optical Depth (550 nm) | MERRA-2 2D Atmospheric Reanalysis | $\text{dimensionless}$ | $1\text{/decade}$ |
| `gldas_swe` | Snow Water Equivalent (SWE) | GLDAS Noah Land Surface Model 2.1 | $\text{kg/m}^2$ | $\text{kg/m}^2\text{/decade}$ |
| `gldas_snow_depth`| Snow Depth | GLDAS Noah Land Surface Model 2.1 | $\text{m}$ | $\text{m/decade}$ |
| `merra2_ts` | Surface / Ocean Skin Temperature | MERRA-2 2D Atmospheric Reanalysis | $^\circ\text{C}$ | $^\circ\text{C/decade}$ |
| `merra2_wind` | 10m Surface Wind Speed | MERRA-2 2D Atmospheric Reanalysis | $\text{m/s}$ | $\text{m/s/decade}$ |
| `merra2_ps` | Surface Atmospheric Pressure | MERRA-2 2D Atmospheric Reanalysis | $\text{hPa}$ | $\text{hPa/decade}$ |
| `merra2_tqv` | Total Precipitable Water Vapor | MERRA-2 2D Atmospheric Reanalysis | $\text{kg/m}^2$ | $\text{kg/m}^2\text{/decade}$ |

*(Note: `modis_ndvi` is explicitly documented as not included in this submission to preserve data purity).*

---

## Repository Architecture

```
.
├── README.md                          # Primary project documentation, goals & architecture
├── Makefile                           # Unified developer shortcuts (test, audit, serve)
├── requirements.txt                   # Scientific Python environment dependencies
├── data/
│   ├── download_manifest.json         # SHA-256 verified download ledger for 304 raw months
│   ├── raw/                           # Raw downloaded HDF5 / NetCDF4 granules
│   └── processed/                     # Gridded anomaly cubes & precomputed trend NetCDFs
├── src/
│   ├── audit.py                       # 10-point multi-layer scientific audit engine
│   ├── variables.yaml                 # Master configuration for all 12 planetary variables
│   ├── variables.py                   # Variable catalog schemas and unit conversion specs
│   ├── process.py                     # Chronological granule reader, regridder & anomaly extractor
│   ├── trend_all.py                   # Parallelized Sen's slope & Hamed-Rao Mann-Kendall calculator
│   ├── export_web.py                  # Domain-aware int16 typed array compressor (<39 MB)
│   ├── cross_check.py                 # Multi-dataset agreement & 2014 era-break diagnostics
│   ├── download.py                    # Resilient NASA Earthdata bulk downloader
│   └── auth.py                        # NASA Earthdata authentication & token manager
├── web/
│   ├── index.html                     # Kendall Mission Control single-page web application
│   ├── style.css                      # Design tokens, CRT phosphor themes, mobile sheet & HUD
│   ├── app.js                         # WebGL MapLibre globe/flat morph, Web Worker stats, HUD
│   ├── icons/                         # SVG master icon, favicons, web manifest & social preview
│   ├── tour/
│   │   ├── tours.json                 # Data-driven tour steps with computed telemetry
│   │   └── audio/
│   │       ├── manifest.json          # Step ID to MP3 mapping, real durations & SHA256 hashes
│   │       └── en/*.mp3               # 39 loudness-normalized speech clips (-16 LUFS, 3.53 MB)
│   └── data/                          # Web assets for 12 variables (meta.json, trend, anomalies)
├── scripts/
│   ├── run_all_checks.sh              # Single-command unified audit runner (Python + Node + E2E)
│   ├── build_tours.py                 # Telemetry-backed script generating web/tour/tours.json
│   └── build_audio.py                 # Local Kokoro/Edge/Piper speech synthesis engine
├── tests/
│   ├── test_units.py                  # Unit conversions (mm/hr, kg/m2/s, Kelvin to Celsius)
│   ├── test_regridding.py             # Conservative area-weighted averaging & global mean checks
│   ├── test_anomalies.py              # Zero-climatology verification & uneven record handling
│   ├── test_statistics.py             # Sen's slope recovery, Hamed-Rao variance, FDR control
│   ├── test_regression.py             # Fixed benchmark checkpoints (Amazon, Sahel, pinned cells)
│   ├── test_time_order.py             # Invariant strictly-increasing monthly time axis validation
│   ├── test_tour_text.py              # Statistical definition presence & forbidden word scanner
│   ├── validate_js_stats.js           # Client JS vs Python numerical parity across 360 cells
│   ├── test_browser_smoke.py          # Playwright headless browser E2E smoke tests (7 tests)
│   └── test_tour_browser.py           # Playwright headless browser tour E2E tests (4 tests)
├── models/kokoro/                     # Local open-source Kokoro-82M ONNX model weights & Apache 2.0 license
└── docs/
    ├── AUDIT.md                       # Comprehensive 10-section independent audit report (PASS)
    ├── SPACE_APPS_SUBMISSION.md       # Official NASA Space Apps Challenge submission dossier
    └── screens/                       # High-resolution UI screenshots & tour step captures
```

---

## Verification & Testing Suite

The repository contains a multi-layer test suite enforcing numerical precision, mathematical equivalence, and browser stability.

### Unified Single-Command Runner

Execute the entire four-stage audit across Python, Node.js, and Playwright in a single command:

```bash
bash scripts/run_all_checks.sh
# or
make audit
```

### Verification Pipeline Stages

1. **Stage 1: Data Completeness & Integrity Audit (`src/audit.py`)**:
   - Inspects raw files, processed NetCDFs, and web payloads.
   - Confirms 304/304 contiguous months with 0 gaps, 0 duplicates, 0 polar mask leaks, and max quantization error $\le 0.04\text{ mm/mo}$.
2. **Stage 2: Numerical, Scientific & Regression Tests (`pytest tests/`)**:
   - 44 automated tests verifying unit conversions, global mean preservation within 0.5%, Theil-Sen slope recovery within 2%, Hamed-Rao variance inflation, and chronological time ordering.
   - Validates that tour narrations match computed numbers and contain zero forbidden phrases (*"proves"*, *"confirms"*, *"real physical signal"*).
3. **Stage 3: JavaScript vs. Python Statistical Parity (`node tests/validate_js_stats.js`)**:
   - Evaluates 360 random cells across all 12 variables plus regional composites.
   - Proves client-side browser math matches Python SciPy within $\le 2.0\%$ relative difference (typical error $<0.5\%$).
4. **Stage 4: Playwright Headless Browser Smoke & Tour Tests (`tests/test_browser_smoke.py`, `tests/test_tour_browser.py`)**:
   - 11 end-to-end browser tests verifying clean boot (0 console errors, 0 API-key requests), projection morphing, regional drawing, multiple-testing counters, and full guided tour playback.

---

## Local Development & Quickstart

### 1. Environment Setup (Conda)

Following the project environment policy, activate the preconfigured Anaconda environment:

```bash
# Scientific environment (Python 3.11 with GDAL, xarray, pymannkendall)
conda activate plot-twist

# Install any additional development dependencies
pip install -r requirements.txt
```

### 2. Launch Local Web Server

```bash
cd web
python -m http.server 8000
```
Open **`http://localhost:8000`** in any modern web browser.

### 3. Regenerating Tours and Audio

The guided tours and audio narration are 100% locally generated without external APIs:

```bash
# Generate tours.json from real computed NetCDF statistics
/opt/anaconda3/envs/plot-twist/bin/python scripts/build_tours.py

# Generate natural speech audio using local Kokoro-82M ONNX model
PATH="/opt/anaconda3/envs/plot-twist/bin:$PATH" /opt/anaconda3/envs/plot-twist/bin/python scripts/build_audio.py --backend kokoro --voice af_heart --lang en
```

---

## Voice Narration & Audio Pipeline Credits

Kendall features a fully local, narrated guided tour powered by high-fidelity open-source speech synthesis without external API keys or remote server calls.

### Voice Model & License
- **Model**: **Kokoro-82M** (v0.19 ONNX runtime, voices v1.0, default voice: `af_heart`) developed by Hexgrad.
- **License**: **Apache License, Version 2.0 (January 2004)** (verified directly from the model's license file at [`models/kokoro/LICENSE`](models/kokoro/LICENSE)).
  - *Terms*: Licensed under the Apache License, Version 2.0; you may not use this file except in compliance with the License. You may obtain a copy of the License at `http://www.apache.org/licenses/LICENSE-2.0`.
- **Audio Processing**:
  - Sentence-by-sentence synthesis joined by 300 ms silence intervals.
  - Loudness normalization via FFmpeg `loudnorm` filter targeted to **-16 LUFS** (`I=-16:TP=-1.5:LRA=11`).
  - Monophonic 64 kbps MP3 encoding for fast web streaming with total bundle size under **3.6 MB** (well below the 15 MB constraint).
- **Secondary Backends**:
  - `edge-tts` for Arabic (`ar-EG-SalmaNeural`, `ar-EG-ShakirNeural`) and English (`en-US-AriaNeural`).
  - `piper-tts` local fallback.
