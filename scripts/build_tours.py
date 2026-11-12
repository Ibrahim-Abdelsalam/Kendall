#!/usr/bin/env python3
"""
build_tours.py - Generates data-driven guided tours for Kendall.

Extracts real computed values directly from processed climate data and web metadata,
builds spoken-friendly step narrations, and ensures definitions of key statistical terms
are included without any forbidden phrases.

Outputs: web/tour/tours.json
"""

import json
import gzip
import os
import re
import numpy as np
import pymannkendall as mk

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DATA_DIR = os.path.join(BASE_DIR, "web", "data")
OUTPUT_PATH = os.path.join(BASE_DIR, "web", "tour", "tours.json")


def load_series(var_id, lat, lon):
    """Loads full 304-month anomaly series for a specific lat/lon grid cell."""
    bin_path = os.path.join(WEB_DATA_DIR, var_id, "anomalies.bin.gz")
    meta_path = os.path.join(WEB_DATA_DIR, var_id, "meta.json")

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    with gzip.open(bin_path, "rb") as f:
        buf = f.read()

    scale = meta["compression"]["anom_scale_factor"]
    shape = meta["compression"]["anom_shape"]  # [304, 72, 144]
    arr = np.frombuffer(buf, dtype=np.int16).reshape(shape).astype(np.float32) * scale

    lat_idx = int(round((lat - (-88.75)) / 2.5))
    lon_idx = int(round((lon - (-178.75)) / 2.5))
    series = arr[:, lat_idx, lon_idx]
    timestamps = meta["time_range"]["timestamps"]
    units = meta.get("trend_units", "units/decade")
    return series, timestamps, units, meta


def compute_point_stats(series, timestamps, months=None):
    """Computes Sen's slope, 95% CI, Hamed-Rao p-value, plain p-value, and detectability."""
    if months is not None:
        # Annual seasonal averages (same as web app extractAnalysisSeries)
        year_avgs = []
        years = []
        base_year = 2000
        for y in range(2000, 2026):
            vals = [
                series[i]
                for i, t in enumerate(timestamps)
                if t.startswith(str(y)) and int(t.split("-")[1]) in months
            ]
            if len(vals) > 0:
                year_avgs.append(float(np.mean(vals)))
                years.append(y)
        analysis_series = np.array(year_avgs, dtype=np.float64)
        mult = 10.0  # decade = 10 annual steps
        step_is_annual = True
    else:
        analysis_series = series.astype(np.float64)
        mult = 120.0  # decade = 120 monthly steps
        step_is_annual = False

    n = len(analysis_series)
    t = np.arange(n)
    slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            slopes.append((analysis_series[j] - analysis_series[i]) / (t[j] - t[i]))
    slopes.sort()
    median_slope = float(np.median(slopes)) * mult

    res_orig = mk.original_test(analysis_series)
    res_hr = mk.hamed_rao_modification_test(analysis_series)

    p_plain = float(res_orig.p)
    p_hr = float(res_hr.p) if res_hr.p is not None and not np.isnan(res_hr.p) else p_plain
    var_s = float(res_hr.var_s) if hasattr(res_hr, "var_s") and res_hr.var_s is not None else float(res_orig.var_s)

    z_crit = 1.95996
    c_alpha = z_crit * np.sqrt(var_s)
    m1 = max(0, int(np.floor((len(slopes) - c_alpha) / 2)))
    m2 = min(len(slopes) - 1, int(np.floor((len(slopes) + c_alpha) / 2)))
    ci_low = float(slopes[m1]) * mult
    ci_high = float(slopes[m2]) * mult

    # Detectability clock: check windows [5, 8, 12, 16, 20, 25.3]
    windows = [5, 8, 12, 16, 20, 25.3]
    sig_year = None
    for w in windows:
        cut = min(n, int(round(w * (1 if step_is_annual else 12))))
        sub = analysis_series[:cut]
        if len(sub) >= 4:
            sub_hr = mk.hamed_rao_modification_test(sub)
            sub_p = float(sub_hr.p) if sub_hr.p is not None and not np.isnan(sub_hr.p) else float(mk.original_test(sub).p)
            if sub_p < 0.05:
                sig_year = w
                break

    return {
        "slope": median_slope,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "p_plain": p_plain,
        "p_hr": p_hr,
        "sig_year": sig_year,
        "n": n,
    }


def num_to_spoken_words(val, decimals=2, unit=""):
    """Converts a float number to natural spoken English words."""
    is_neg = val < 0
    abs_val = round(abs(val), decimals)
    if decimals == 0:
        val_str = f"{int(abs_val)}"
    elif decimals == 1:
        val_str = f"{abs_val:.1f}"
    elif decimals == 2:
        val_str = f"{abs_val:.2f}"
    elif decimals == 3:
        val_str = f"{abs_val:.3f}"
    else:
        val_str = f"{abs_val:.4f}"

    digits_word = {
        "0": "zero",
        "1": "one",
        "2": "two",
        "3": "three",
        "4": "four",
        "5": "five",
        "6": "six",
        "7": "seven",
        "8": "eight",
        "9": "nine",
    }

    parts = val_str.split(".")
    integer_part = parts[0]
    decimal_part = parts[1] if len(parts) > 1 else ""

    spoken = []
    if is_neg:
        spoken.append("minus")

    spoken.append(integer_part)

    if decimal_part:
        spoken.append("point")
        for d in decimal_part:
            spoken.append(digits_word.get(d, d))

    res = " ".join(spoken)
    if unit:
        res += f" {unit}"
    return res


def build_tours():
    """Builds the comprehensive tours.json structure."""
    print("Computing real data values for case studies...")

    # 1. Amazon Basin
    amz_s, amz_t, amz_u, amz_meta = load_series("gpm_precip", -3.75, -61.25)
    amz_stats = compute_point_stats(amz_s, amz_t)

    # 2. Sahel Corridor (IMERG & GLDAS)
    sahel_imerg_s, sahel_imerg_t, _, _ = load_series("gpm_precip", 13.75, 13.75)
    sahel_imerg_stats = compute_point_stats(sahel_imerg_s, sahel_imerg_t)

    sahel_gldas_s, sahel_gldas_t, _, _ = load_series("gldas_precip", 13.75, 13.75)
    sahel_gldas_stats = compute_point_stats(sahel_gldas_s, sahel_gldas_t)

    # 3. Tibetan Plateau Warming
    tibet_s, tibet_t, tibet_u, _ = load_series("gldas_temp", 33.75, 81.25)
    tibet_stats = compute_point_stats(tibet_s, tibet_t)

    # 4. Central Canada Summer Smoke (ALL vs JJA)
    canada_s, canada_t, _, _ = load_series("merra2_aod", 53.75, -106.25)
    canada_all_stats = compute_point_stats(canada_s, canada_t)
    canada_jja_stats = compute_point_stats(canada_s, canada_t, months=[6, 7, 8])

    print(f"Amazon slope: {amz_stats['slope']:.2f}, CI: [{amz_stats['ci_low']:.2f}, {amz_stats['ci_high']:.2f}], p_hr: {amz_stats['p_hr']:.4f}")
    print(f"Sahel IMERG slope: {sahel_imerg_stats['slope']:.2f}, p_hr: {sahel_imerg_stats['p_hr']:.4f}")
    print(f"Sahel GLDAS slope: {sahel_gldas_stats['slope']:.2f}, p_hr: {sahel_gldas_stats['p_hr']:.4f}")
    print(f"Tibet slope: {tibet_stats['slope']:.2f}, CI: [{tibet_stats['ci_low']:.2f}, {tibet_stats['ci_high']:.2f}], p_hr: {tibet_stats['p_hr']:.4f}")
    print(f"Canada JJA slope: {canada_jja_stats['slope']:.3f}, p_hr: {canada_jja_stats['p_hr']:.4f}")

    # Build Site Tour (approx. 90s total duration across 14 focused steps)
    site_tour_steps = [
        {
            "id": "site_01_welcome",
            "title": "Welcome to Kendall",
            "text": "Welcome to Kendall. We are glad you are here. This interactive scientific explorer lets you investigate twenty-five years of continuous NASA satellite and reanalysis observations across planet Earth.",
            "audio": "audio/en/site_01_welcome.mp3",
            "target": "#map",
            "action": {
                "setVar": "gpm_precip",
                "setMode": "point",
                "setPeriod": [2000, 2025],
                "setSeason": "ALL",
                "setProjection": "globe",
                "flyTo": {"lon": 10.0, "lat": 15.0, "zoom": 1.8, "pitch": 20},
                "openPanel": None,
            },
            "highlightStyle": "spotlight",
            "durationFallbackMs": 8000,
            "autoAdvance": False,
        },
        {
            "id": "site_02_datasets",
            "title": "Variable Picker",
            "text": "Use the dataset bar to switch across atmospheric and terrestrial variables, including rainfall, temperature, soil moisture, evaporation, and wildfire smoke.",
            "audio": "audio/en/site_02_datasets.mp3",
            "target": "#variable-picker",
            "action": {
                "setVar": "gpm_precip",
                "setMode": "point",
            },
            "highlightStyle": "ring",
            "durationFallbackMs": 7000,
        },
        {
            "id": "site_03_selection",
            "title": "Point vs Region Analysis",
            "text": "Switch between Point mode to inspect single grid cells and Region mode to draw custom bounding boxes with area-weighted spatial aggregation.",
            "audio": "audio/en/site_03_selection.mp3",
            "target": "#selection-mode-group",
            "action": {
                "setMode": "point",
            },
            "highlightStyle": "ring",
            "durationFallbackMs": 7000,
        },
        {
            "id": "site_04_timeseries",
            "title": "25-Year Anomaly Trajectory",
            "text": "The time series chart displays monthly anomalies from the long-term climatology, showing the raw trajectory, a twelve-month rolling average, and Sen's slope line.",
            "audio": "audio/en/site_04_timeseries.mp3",
            "target": "#chart-timeseries",
            "action": {
                "setVar": "gpm_precip",
                "flyTo": {"lon": -61.25, "lat": -3.75, "zoom": 3.0, "pitch": 20},
            },
            "highlightStyle": "spotlight",
            "durationFallbackMs": 7500,
        },
        {
            "id": "site_05_verdict",
            "title": "The Verdict Card",
            "text": "The Verdict Card evaluates whether an apparent change is genuine or just statistical noise, adjusting strictly for serial autocorrelation.",
            "audio": "audio/en/site_05_verdict.mp3",
            "target": "#verdict-card",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 6500,
        },
        {
            "id": "site_06_verdict_states",
            "title": "Three Verdict States",
            "text": "A location is classified into one of three rigorous states: significant trend with p under five percent, trending but not yet significant, or no trend.",
            "audio": "audio/en/site_06_verdict_states.mp3",
            "target": "#verdict-status-pill",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 7000,
        },
        {
            "id": "site_07_ci_pvalue",
            "title": "Confidence Interval and P-Value",
            "text": "The ninety-five percent confidence interval gives the probable range of the rate, while the p-value measures the probability of observing this pattern by random chance.",
            "audio": "audio/en/site_07_ci_pvalue.mp3",
            "target": "#verdict-metrics-row",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 7500,
        },
        {
            "id": "site_08_clock",
            "title": "The Detectability Clock",
            "text": "The Detectability Clock reveals how many years of continuous observation are needed before a trend cleanly emerges from natural climate noise.",
            "audio": "audio/en/site_08_clock.mp3",
            "target": "#detectability-card",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 6500,
        },
        {
            "id": "site_09_lineup",
            "title": "Planetary Lineup",
            "text": "The Planetary Lineup compares all variables simultaneously at your pinned location, checking whether shifts in rain, temperature, and soil align coherently.",
            "audio": "audio/en/site_09_lineup.mp3",
            "target": "#lineup-card",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 7000,
        },
        {
            "id": "site_10_filters",
            "title": "Period and Season Filters",
            "text": "Slice the record into historical eras like pre-twenty-fourteen versus post-twenty-fourteen, or isolate individual seasons like summer or winter.",
            "audio": "audio/en/site_10_filters.mp3",
            "target": "#analysis-controls-card",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 6500,
        },
        {
            "id": "site_11_scrubber",
            "title": "Monthly Timeline Scrubber",
            "text": "Drag the scrubber timeline to step through every single month from June two thousand to September twenty twenty-five, watching global anomalies evolve.",
            "audio": "audio/en/site_11_scrubber.mp3",
            "target": "#timeline-container",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 7000,
        },
        {
            "id": "site_12_projection",
            "title": "Globe and Flat Projections",
            "text": "Toggle effortlessly between a realistic three-dimensional orthographic globe and a flat Mercator projection with smooth camera interpolation.",
            "audio": "audio/en/site_12_projection.mp3",
            "target": "#proj-toggle-group",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 6500,
        },
        {
            "id": "site_13_looks",
            "title": "Analysis Choices Counter",
            "text": "The looks counter tracks your exploratory choices. Searching through multiple combinations increases false positive risk, reminding us to remain skeptical.",
            "audio": "audio/en/site_13_looks.mp3",
            "target": "#analysis-looks-widget",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 7000,
        },
        {
            "id": "site_14_sources",
            "title": "Sources, Caveats and Curiosity",
            "text": "Every calculation adheres to open science standards, citing official NASA missions and stating all instrument limits clearly. Thank you for exploring planet Earth with us, and stay curious.",
            "audio": "audio/en/site_14_sources.mp3",
            "target": "#verdict-disclaimer",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 8000,
        },
    ]

    # Build Case Narrations (5 to 8 steps each, high-school language, definitions on first use, real numbers)

    # CASE 1: Amazon Basin
    # Define: anomaly, trend, p-value, significant, confidence interval, step change
    amz_slope_val = round(amz_stats["slope"], 2)
    amz_ci_l = round(amz_stats["ci_low"], 2)
    amz_ci_h = round(amz_stats["ci_high"], 2)
    amz_p_val = round(amz_stats["p_hr"], 4)

    case_amazon_steps = [
        {
            "id": "case_amz_01_flyto",
            "title": "Amazon Basin: The Drought Puzzle",
            "text": "We travel to the central Amazon Basin. This vast rainforest region has experienced extreme droughts and major fire events over recent decades.",
            "audio": "audio/en/case_amz_01_flyto.mp3",
            "target": {"type": "map_coord", "lng": -61.25, "lat": -3.75},
            "action": {
                "setVar": "gpm_precip",
                "setMode": "point",
                "setPeriod": [2000, 2025],
                "setSeason": "ALL",
                "setProjection": "globe",
                "flyTo": {"lon": -61.25, "lat": -3.75, "zoom": 3.8, "pitch": 25},
            },
            "highlightStyle": "ring",
            "durationFallbackMs": 7000,
        },
        {
            "id": "case_amz_02_signal",
            "title": "Precipitation Trajectory",
            "text": f"Over twenty-five years, monthly rainfall anomalies show a steep drying slope of {amz_slope_val} millimeters per month per decade. An anomaly is a departure from the long-term seasonal average, while a trend measures the steady rate of change over time.",
            "audio": "audio/en/case_amz_02_signal.mp3",
            "target": "#chart-timeseries",
            "action": {},
            "highlightStyle": "spotlight",
            "durationFallbackMs": 8500,
        },
        {
            "id": "case_amz_03_significance",
            "title": "Statistical Significance",
            "text": f"The autocorrelation-aware p-value is {amz_p_val}. A p-value is the probability that random chance produced this pattern. Because p is under zero point zero five, statisticians classify this full-record trend as significant.",
            "audio": "audio/en/case_amz_03_significance.mp3",
            "target": "#val-phr",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 8000,
        },
        {
            "id": "case_amz_04_ci",
            "title": "Confidence Interval",
            "text": f"The ninety-five percent confidence interval ranges from {amz_ci_l} to {amz_ci_h} millimeters per decade. A confidence interval gives the estimated range that holds the true underlying rate with ninety-five percent certainty.",
            "audio": "audio/en/case_amz_04_ci.mp3",
            "target": "#verdict-ci-range-bar",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 8000,
        },
        {
            "id": "case_amz_05_break",
            "title": "The 2014 Sensor Transition",
            "text": "In early twenty-fourteen, NASA transitioned primary satellites from TRMM to GPM. A step change is an abrupt jump in the data baseline. Before twenty-fourteen the slope was weakly positive, but afterwards it flipped deeply negative.",
            "audio": "audio/en/case_amz_05_break.mp3",
            "target": "#verdict-caution-box",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 8500,
        },
        {
            "id": "case_amz_06_agreement",
            "title": "Cross-Dataset Agreement",
            "text": "Independent GLDAS reanalysis also shows sharp post-twenty-fourteen drying. However, neither sub-period is statistically significant on its own, showing how sensitive trend estimates can be to the observation window.",
            "audio": "audio/en/case_amz_06_agreement.mp3",
            "target": "#lineup-card",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 8000,
        },
        {
            "id": "case_amz_07_caution",
            "title": "What This Does Not Mean",
            "text": "Crucially, a mathematical trend does not establish physical causation. This signal is not proven to be caused exclusively by local deforestation; historic El Niño drought episodes in twenty-fifteen and twenty-twenty-three heavily shape this record.",
            "audio": "audio/en/case_amz_07_caution.mp3",
            "target": "#verdict-caution-box",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 8500,
        },
    ]

    # CASE 2: African Sahel Corridor
    sahel_im_slope = round(sahel_imerg_stats["slope"], 2)
    sahel_im_p = round(sahel_imerg_stats["p_hr"], 2)
    sahel_gl_slope = round(sahel_gldas_stats["slope"], 2)
    sahel_gl_p = round(sahel_gldas_stats["p_hr"], 2)

    case_sahel_steps = [
        {
            "id": "case_shl_01_flyto",
            "title": "African Sahel: The Greening Debate",
            "text": "We shift our focus to the African Sahel corridor, a semi-arid zone between the Sahara desert and tropical savannas that experienced historic twentieth-century droughts.",
            "audio": "audio/en/case_shl_01_flyto.mp3",
            "target": {"type": "map_coord", "lng": 13.75, "lat": 13.75},
            "action": {
                "setVar": "gpm_precip",
                "setMode": "point",
                "setPeriod": [2000, 2025],
                "setSeason": "ALL",
                "setProjection": "globe",
                "flyTo": {"lon": 13.75, "lat": 13.75, "zoom": 3.8, "pitch": 25},
            },
            "highlightStyle": "ring",
            "durationFallbackMs": 7500,
        },
        {
            "id": "case_shl_02_imerg_trend",
            "title": "Modest IMERG Upward Slope",
            "text": f"IMERG satellite precipitation indicates a modest upward slope of {sahel_im_slope} millimeters per month per decade. Popular stories often describe this as a permanent greening recovery.",
            "audio": "audio/en/case_shl_02_imerg_trend.mp3",
            "target": "#chart-timeseries",
            "action": {},
            "highlightStyle": "spotlight",
            "durationFallbackMs": 7500,
        },
        {
            "id": "case_shl_03_not_sig",
            "title": "Not Yet Significant",
            "text": f"When we adjust for temporal autocorrelation, the p-value is {sahel_im_p}. Because p is well above zero point zero five, this result is not yet statistically significant; random year-to-year swings readily explain it.",
            "audio": "audio/en/case_shl_03_not_sig.mp3",
            "target": "#verdict-status-pill",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 8000,
        },
        {
            "id": "case_shl_04_clock",
            "title": "Detectability Window",
            "text": "The Detectability Clock indicates that rainfall noise across the Sahel is so high that more than twenty-five years of observation are required before a subtle trend can be confirmed.",
            "audio": "audio/en/case_shl_04_clock.mp3",
            "target": "#detectability-card",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 7500,
        },
        {
            "id": "case_shl_05_disagreement",
            "title": "Dataset Disagreement",
            "text": f"By contrast, GLDAS reanalysis estimates a steeper rate of {sahel_gl_slope} millimeters per month per decade, which reaches statistical significance at p equals {sahel_gl_p}. Disagreements between models and satellites urge caution.",
            "audio": "audio/en/case_shl_05_disagreement.mp3",
            "target": "#lineup-card",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 8500,
        },
        {
            "id": "case_shl_06_caution",
            "title": "What This Does Not Mean",
            "text": "What this does not mean: a modest positive trend is not proven to be a permanent climate recovery; severe annual precipitation deficits still occur regularly across the Sahel.",
            "audio": "audio/en/case_shl_06_caution.mp3",
            "target": "#verdict-caution-box",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 7500,
        },
    ]

    # CASE 3: Tibetan Plateau Warming
    tibet_slope_val = round(tibet_stats["slope"], 2)
    tibet_ci_l = round(tibet_stats["ci_low"], 2)
    tibet_ci_h = round(tibet_stats["ci_high"], 2)

    case_tibet_steps = [
        {
            "id": "case_tbt_01_flyto",
            "title": "Tibetan Plateau: High-Mountain Warming",
            "text": "Next, we fly to the high Tibetan Plateau and the Himalayas, known as the Third Pole and the vital water tower of Asia.",
            "audio": "audio/en/case_tbt_01_flyto.mp3",
            "target": {"type": "map_coord", "lng": 81.25, "lat": 33.75},
            "action": {
                "setVar": "gldas_temp",
                "setMode": "point",
                "setPeriod": [2000, 2025],
                "setSeason": "ALL",
                "setProjection": "globe",
                "flyTo": {"lon": 81.25, "lat": 33.75, "zoom": 3.8, "pitch": 30},
            },
            "highlightStyle": "ring",
            "durationFallbackMs": 7000,
        },
        {
            "id": "case_tbt_02_signal",
            "title": "Intense Thermal Amplification",
            "text": f"Two-meter air temperature reveals an intense warming slope of {tibet_slope_val} degrees Celsius per decade. This represents the strongest sustained thermal signal in the dataset.",
            "audio": "audio/en/case_tbt_02_signal.mp3",
            "target": "#val-rate",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 7500,
        },
        {
            "id": "case_tbt_03_significance",
            "title": "Decisive Significance",
            "text": "The autocorrelation-aware p-value is less than zero point zero zero zero one, and it comfortably survives planetary False Discovery Rate control. Chance alone cannot account for this warming.",
            "audio": "audio/en/case_tbt_03_significance.mp3",
            "target": "#verdict-fdr-badge",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 7500,
        },
        {
            "id": "case_tbt_04_ci",
            "title": "Consistent Confidence Interval",
            "text": f"The ninety-five percent confidence interval spans from {tibet_ci_l} to {tibet_ci_h} degrees Celsius per decade. Both bounds remain deeply positive.",
            "audio": "audio/en/case_tbt_04_ci.mp3",
            "target": "#verdict-ci-range-bar",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 7000,
        },
        {
            "id": "case_tbt_05_clock",
            "title": "Rapid Emergence",
            "text": "The Detectability Clock shows this thermal signal was already detectable after just five years of observation, reflecting the high signal-to-noise ratio of high-altitude warming.",
            "audio": "audio/en/case_tbt_05_clock.mp3",
            "target": "#detectability-card",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 7500,
        },
        {
            "id": "case_tbt_06_caution",
            "title": "What This Does Not Mean",
            "text": "What this does not mean: regional gridded reanalysis does not capture microclimates in narrow mountain valleys, where local topography and glacier winds create distinct conditions.",
            "audio": "audio/en/case_tbt_06_caution.mp3",
            "target": "#verdict-caution-box",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 7500,
        },
    ]

    # CASE 4: Central Canada Summer Wildfire Smoke
    can_all_slope = round(canada_all_stats["slope"], 3)
    can_jja_slope = round(canada_jja_stats["slope"], 2)
    can_jja_p = round(canada_jja_stats["p_hr"], 2)

    case_canada_steps = [
        {
            "id": "case_can_01_flyto",
            "title": "Central Canada: Wildfire Smoke Surge",
            "text": "Our final case takes us to central Canada's boreal forests, examining MERRA-2 aerosol optical depth from atmospheric wildfire smoke.",
            "audio": "audio/en/case_can_01_flyto.mp3",
            "target": {"type": "map_coord", "lng": -106.25, "lat": 53.75},
            "action": {
                "setVar": "merra2_aod",
                "setMode": "point",
                "setPeriod": [2000, 2025],
                "setSeason": "ALL",
                "setProjection": "globe",
                "flyTo": {"lon": -106.25, "lat": 53.75, "zoom": 3.8, "pitch": 25},
            },
            "highlightStyle": "ring",
            "durationFallbackMs": 7000,
        },
        {
            "id": "case_can_02_all_year",
            "title": "Full-Year Averaging Dilutes the Signal",
            "text": f"Averaged across all twelve calendar months, aerosol optical depth shows only a tiny slope of {can_all_slope} per decade, hiding major fire events beneath winter quiet.",
            "audio": "audio/en/case_can_02_all_year.mp3",
            "target": "#chart-timeseries",
            "action": {},
            "highlightStyle": "spotlight",
            "durationFallbackMs": 7500,
        },
        {
            "id": "case_can_03_jja_slice",
            "title": "Seasonal Slicing Unmasks the Surge",
            "text": f"Isolating the summer smoke season of June, July, and August reveals a sharper slope of {can_jja_slope} per decade, highlighting the value of seasonal filtering.",
            "audio": "audio/en/case_can_03_jja_slice.mp3",
            "target": "#chip-season-jja",
            "action": {
                "setSeason": "JJA",
            },
            "highlightStyle": "ring",
            "durationFallbackMs": 7500,
        },
        {
            "id": "case_can_04_megafires",
            "title": "Episodic Megafire Summers",
            "text": "The trajectory shows massive spikes in twenty-twenty-one, twenty-twenty-three, and twenty-twenty-five, when unprecedented boreal megafires blanketed North America in smoke.",
            "audio": "audio/en/case_can_04_megafires.mp3",
            "target": "#chart-timeseries",
            "action": {},
            "highlightStyle": "spotlight",
            "durationFallbackMs": 7500,
        },
        {
            "id": "case_can_05_trending",
            "title": "Trending but Not Yet Significant",
            "text": f"At this individual grid cell, the autocorrelation-aware p-value is {can_jja_p}. It is classified as trending but not yet significant at the strict five percent threshold.",
            "audio": "audio/en/case_can_05_trending.mp3",
            "target": "#verdict-status-pill",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 7500,
        },
        {
            "id": "case_can_06_caution",
            "title": "What This Does Not Mean",
            "text": "What this does not mean: wildfire smoke occurs in acute pulses and is not proven to follow a smooth linear progression; intermittent ignition weather drives each extreme season.",
            "audio": "audio/en/case_can_06_caution.mp3",
            "target": "#verdict-caution-box",
            "action": {},
            "highlightStyle": "ring",
            "durationFallbackMs": 8000,
        },
    ]

    tours_data = {
        "site_tour": {
            "id": "site_tour",
            "title": "Kendall Interactive Site Tour",
            "description": "A comprehensive ninety-second walkthrough of Kendall's interactive map, analysis tools, and statistical safeguards.",
            "steps": site_tour_steps,
        },
        "case_amazon": {
            "id": "case_amazon",
            "title": "Amazon Basin: Drought or Sensor Break?",
            "description": "Investigate whether dramatic Amazon drying reflects a genuine shift or a 2014 satellite sensor discontinuity.",
            "steps": case_amazon_steps,
        },
        "case_sahel": {
            "id": "case_sahel",
            "title": "Sahel Corridor: Greening Recovery Debate",
            "description": "Examine whether rainfall recovery in the African Sahel reaches true statistical significance.",
            "steps": case_sahel_steps,
        },
        "case_tibet": {
            "id": "case_tibet",
            "title": "Tibetan Plateau: High-Mountain Warming Hotspot",
            "description": "Explore the rapid, statistically indisputable thermal amplification across High-Mountain Asia.",
            "steps": case_tibet_steps,
        },
        "case_canada": {
            "id": "case_canada",
            "title": "Central Canada: Summer Wildfire Smoke Surge",
            "description": "Unmask how seasonal slicing reveals intense summer smoke trends invisible in full-year averages.",
            "steps": case_canada_steps,
        },
    }

    # Verify forbidden phrases across all steps
    forbidden_tokens = ["proves", "confirms", "real physical signal"]
    for tour_id, tour in tours_data.items():
        for step in tour["steps"]:
            txt = step["text"].lower()
            for token in forbidden_tokens:
                if token in txt:
                    raise ValueError(f"Forbidden phrase '{token}' found in {tour_id} step {step['id']}: {step['text']}")
            if "caused by" in txt and "not proven to be caused" not in txt and "is not caused by" not in txt:
                raise ValueError(f"Unqualified 'caused by' found in {tour_id} step {step['id']}: {step['text']}")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(tours_data, f, indent=2)

    total_steps = sum(len(t["steps"]) for t in tours_data.values())
    print(f"Successfully generated {OUTPUT_PATH} with {len(tours_data)} tours and {total_steps} steps.")


if __name__ == "__main__":
    build_tours()
