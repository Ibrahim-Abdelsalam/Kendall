"""Plot global precipitation trends and regional time series.

Outputs:
  data/processed/trend_map.png
    - Panel 1: Global map of Sen's slope with FDR-significant cells stippled.
    - Panel 2: Time-series of Amazon basin precipitation anomalies with trend line and TRMM/GPM transition marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pymannkendall as mk
from scipy.stats import linregress
import xarray as xr


PROCESSED_DATA_DIR = Path("data/processed")
ANOMALIES_FILE = PROCESSED_DATA_DIR / "precip_anomalies.nc"
TREND_FILE = PROCESSED_DATA_DIR / "precip_trend.nc"
OUTPUT_PNG = PROCESSED_DATA_DIR / "trend_map.png"

AMAZON_BBOX = (-10.0, 2.0, -70.0, -50.0)
SAHEL_BBOX = (12.0, 18.0, -15.0, 35.0)


def generate_diagnostic_figure() -> Path:
    """Generate the two-panel trend map and time-series diagnostic plot."""
    if not ANOMALIES_FILE.exists() or not TREND_FILE.exists():
        raise FileNotFoundError("Anomalies or trend files are missing from data/processed/")

    print(f"[*] Reading datasets from {PROCESSED_DATA_DIR}...")
    ds_anom = xr.open_dataset(ANOMALIES_FILE)
    ds_trend = xr.open_dataset(TREND_FILE)

    lats = ds_trend["lat"].values
    lons = ds_trend["lon"].values
    slope_grid = ds_trend["sens_slope"].values
    fdr_sig = ds_trend["significant_fdr"].values

    # Setup publication-style 2-panel figure
    fig = plt.figure(figsize=(13, 11), dpi=300)
    gs = fig.add_gridspec(2, 1, height_ratios=[1.2, 0.9], hspace=0.32)

    # ==========================================
    # Panel 1: Global Sen's Slope with Stippling
    # ==========================================
    ax1 = fig.add_subplot(gs[0])
    
    # 2D coordinates for pcolormesh
    lon_mesh, lat_mesh = np.meshgrid(lons, lats)
    
    # Diverging colormap: Brown (drying) to Blue/Green (wetting)
    cmap = plt.get_cmap("BrBG")
    vmin, vmax = -25.0, 25.0

    mesh = ax1.pcolormesh(
        lon_mesh,
        lat_mesh,
        slope_grid,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        shading="auto",
    )

    # Stippling where significant under FDR control (q < 0.05)
    stipple_mask = (fdr_sig == 1)
    stipple_lons = lon_mesh[stipple_mask]
    stipple_lats = lat_mesh[stipple_mask]
    ax1.scatter(
        stipple_lons,
        stipple_lats,
        color="black",
        s=1.8,
        alpha=0.65,
        marker="o",
        label=r"Significant ($q_{\mathrm{FDR}} < 0.05$)",
    )

    # Outline Amazon and Sahel regional boxes
    rect_amazon = patches.Rectangle(
        (AMAZON_BBOX[2], AMAZON_BBOX[0]),
        AMAZON_BBOX[3] - AMAZON_BBOX[2],
        AMAZON_BBOX[1] - AMAZON_BBOX[0],
        linewidth=1.8,
        edgecolor="#d97706",
        facecolor="none",
        linestyle="-",
        label="Amazon Box",
    )
    rect_sahel = patches.Rectangle(
        (SAHEL_BBOX[2], SAHEL_BBOX[0]),
        SAHEL_BBOX[3] - SAHEL_BBOX[2],
        SAHEL_BBOX[1] - SAHEL_BBOX[0],
        linewidth=1.8,
        edgecolor="#0284c7",
        facecolor="none",
        linestyle="--",
        label="Sahel Box",
    )
    ax1.add_patch(rect_amazon)
    ax1.add_patch(rect_sahel)

    ax1.set_xlim(-180, 180)
    ax1.set_ylim(-90, 90)
    ax1.set_xticks(np.arange(-180, 181, 60))
    ax1.set_yticks(np.arange(-90, 91, 30))
    ax1.set_xticklabels([f"{x}°" for x in np.arange(-180, 181, 60)], fontsize=9)
    ax1.set_yticklabels([f"{y}°" for y in np.arange(-90, 91, 30)], fontsize=9)
    ax1.set_xlabel("Longitude", fontsize=10, fontweight="medium")
    ax1.set_ylabel("Latitude", fontsize=10, fontweight="medium")
    ax1.grid(True, linestyle=":", alpha=0.4, color="gray")
    ax1.set_title(
        r"$\bf{Global\ Precipitation\ Trend\ (2000–2025)}$"
        + "\nSen’s Slope (mm / month / decade) with Benjamini-Hochberg FDR Stippling ($q < 0.05$)",
        fontsize=12,
        pad=10,
    )
    ax1.legend(loc="lower left", fontsize=8.5, framealpha=0.9)

    # Colorbar
    cbar = fig.colorbar(mesh, ax=ax1, orientation="horizontal", pad=0.12, fraction=0.045, shrink=0.7)
    cbar.set_label("Precipitation Anomaly Trend (mm / month / decade)", fontsize=9.5)
    cbar.ax.tick_params(labelsize=8.5)

    # ==========================================
    # Panel 2: Amazon Basin Regional Time-Series
    # ==========================================
    ax2 = fig.add_subplot(gs[1])

    # Extract Amazon regional average anomaly time series
    amazon_anom = (
        ds_anom["precip_anomaly"]
        .sel(lat=slice(AMAZON_BBOX[0], AMAZON_BBOX[1]), lon=slice(AMAZON_BBOX[2], AMAZON_BBOX[3]))
        .mean(dim=("lat", "lon"))
    )
    
    dates = pd.to_datetime(amazon_anom["time"].values)
    values = amazon_anom.values
    t_idx = np.arange(len(values))

    # Calculate regional stats
    mk_res = mk.hamed_rao_modification_test(values)
    lr = linregress(t_idx, values)
    sen_slope_dec = mk_res.slope * 120.0
    ols_slope_dec = lr.slope * 120.0

    # Trend line points
    trend_line = mk_res.intercept + mk_res.slope * t_idx
    ols_line = lr.intercept + lr.slope * t_idx

    # Plot monthly anomaly bars / line
    ax2.bar(
        dates,
        values,
        width=25,
        color=np.where(values >= 0, "#0284c7", "#b45309"),
        alpha=0.35,
        label="Monthly Anomaly",
    )
    
    # 12-month rolling mean
    s_series = pd.Series(values, index=dates)
    rolling_12 = s_series.rolling(12, center=True).mean()
    ax2.plot(dates, rolling_12, color="#0f172a", linewidth=1.8, label="12-Month Moving Average")

    # Plot Sen's slope trend line
    ax2.plot(
        dates,
        trend_line,
        color="#dc2626",
        linewidth=2.2,
        label=f"Sen’s Slope: {sen_slope_dec:+.2f} mm/mo/dec ($p = {mk_res.p:.4f}$)",
    )
    # Plot OLS line
    ax2.plot(
        dates,
        ols_line,
        color="#7c3aed",
        linewidth=1.4,
        linestyle="--",
        label=f"OLS Trend: {ols_slope_dec:+.2f} mm/mo/dec ($p = {lr.pvalue:.4f}$)",
    )

    # Vertical line at TRMM to GPM transition (2014-01-01)
    break_date = pd.Timestamp("2014-01-01")
    ax2.axvline(break_date, color="#475569", linestyle=":", linewidth=1.5, alpha=0.9)
    ax2.text(
        break_date,
        ax2.get_ylim()[1] if ax2.get_ylim()[1] != 0 else 80,
        " TRMM ➔ GPM Transition (2014)",
        fontsize=8.5,
        color="#334155",
        fontweight="semibold",
        va="top",
    )

    ax2.set_xlim(dates[0], dates[-1])
    ax2.xaxis.set_major_locator(mdates.YearLocator(3))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax2.axhline(0, color="gray", linewidth=0.8, linestyle="-")
    ax2.grid(True, linestyle=":", alpha=0.5)
    ax2.set_xlabel("Year", fontsize=10, fontweight="medium")
    ax2.set_ylabel("Precipitation Anomaly (mm / month)", fontsize=10, fontweight="medium")
    ax2.set_title(
        r"$\bf{Amazon\ Basin\ Monthly\ Precipitation\ Anomalies\ (10°S–2°N,\ 70°W–50°W)}$"
        + f"\nClear Drying Signal: {sen_slope_dec:+.2f} mm/month/decade (Hamed-Rao p = {mk_res.p:.4f})",
        fontsize=11.5,
        pad=8,
    )
    ax2.legend(loc="lower left", fontsize=8.5, framealpha=0.9)

    # Save to disk
    plt.savefig(OUTPUT_PNG, dpi=300, bbox_inches="tight")
    plt.close(fig)

    ds_anom.close()
    ds_trend.close()

    print(f"[+] Diagnostic figure generated successfully: {OUTPUT_PNG} ({OUTPUT_PNG.stat().st_size / 1024:.1f} KB)")
    return OUTPUT_PNG


def main() -> int:
    try:
        generate_diagnostic_figure()
        return 0
    except Exception as exc:
        print(f"[-] Plotting failed: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
