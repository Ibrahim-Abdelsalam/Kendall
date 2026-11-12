#!/usr/bin/env bash
# ==============================================================================
# Unified Audit & Test Suite Runner for Kendall (Plot Twist)
# Runs the full verification pipeline across Python, Node.js, and Headless Browser:
#   1. Layer-by-layer Data Integrity Audit (src/audit.py)
#   2. Numerical & Scientific Pytest Suite (tests/)
#   3. JavaScript vs. Python Statistical Parity Engine (tests/validate_js_stats.js)
#   4. End-to-End Headless Browser Smoke Tests (tests/test_browser_smoke.py)
# ==============================================================================

PYTHON_ENV="/opt/anaconda3/envs/plot-twist/bin/python"
PYTHON_BASE="/opt/anaconda3/bin/python"
NODE="/usr/local/bin/node"

echo "================================================================================"
echo " Kendall Scientific Audit & End-to-End Test Suite"
echo " Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo " Machine: $(uname -s) $(uname -m)"
echo " Python (plot-twist): $PYTHON_ENV"
echo " Python (base):       $PYTHON_BASE"
echo " Node:                $NODE ($($NODE -v))"
echo "================================================================================"
echo ""

# Stage 1: Data Completeness & Integrity Audit
echo ">>> [STAGE 1/4] Running Data Integrity Audit (src/audit.py)..."
"$PYTHON_ENV" src/audit.py
echo ">>> Stage 1 Complete."
echo ""

# Stage 2: Numerical, Scientific & Regression Tests
echo ">>> [STAGE 2/4] Running Numerical & Scientific Pytest Suite..."
"$PYTHON_ENV" -m pytest \
    tests/test_units.py \
    tests/test_regridding.py \
    tests/test_anomalies.py \
    tests/test_statistics.py \
    tests/test_regression.py \
    tests/test_time_order.py \
    tests/test_tour_text.py \
    -v --tb=short
echo ">>> Stage 2 Complete."
echo ""

# Stage 3: JavaScript vs Python Statistical Parity
echo ">>> [STAGE 3/4] Running JS vs Python Statistical Parity Validation..."
"$NODE" tests/validate_js_stats.js
echo ">>> Stage 3 Complete."
echo ""

# Stage 4: Playwright Headless Browser Smoke Tests
echo ">>> [STAGE 4/4] Running Playwright Headless Browser Smoke & Tour Suite..."
"$PYTHON_BASE" -m pytest tests/test_browser_smoke.py tests/test_tour_browser.py -v --tb=short
echo ">>> Stage 4 Complete."
echo ""

echo "================================================================================"
echo " ALL AUDIT CHECKS AND AUTOMATED TESTS COMPLETED"
echo " See docs/AUDIT.md for full report, methodology, and scientific notes."
echo "================================================================================"
