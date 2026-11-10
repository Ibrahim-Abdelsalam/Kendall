/**
 * Numerical Validation Script: JavaScript vs. Python Statistical Equivalence
 * Tests 30 random valid cells per variable across all 6 datasets.
 */

const fs = require('fs');
const zlib = require('zlib');
const path = require('path');

const N_LATS = 72;
const N_LONS = 144;
const TOTAL_CELLS = N_LATS * N_LONS;

const VARIABLES = [
  'gpm_precip',
  'gldas_precip',
  'gldas_soil_moist',
  'gldas_temp',
  'gldas_evap',
  'merra2_aod',
];

function normalCdf(x) {
  const t = 1.0 / (1.0 + 0.2316419 * Math.abs(x));
  const d = 0.3989422804014327 * Math.exp(-x * x / 2.0);
  const prob = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return x >= 0 ? 1.0 - prob : prob;
}

function computeClientStats(series) {
  const validSeries = [];
  const timeIndices = [];
  for (let k = 0; k < series.length; k++) {
    if (series[k] !== null && !isNaN(series[k]) && isFinite(series[k])) {
      validSeries.push(series[k]);
      timeIndices.push(k);
    }
  }

  const n = validSeries.length;
  if (n < 10) return { slope: null, p_hr: null, p_plain: null };

  const slopes = [];
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      slopes.push((validSeries[j] - validSeries[i]) / (timeIndices[j] - timeIndices[i]));
    }
  }
  slopes.sort((a, b) => a - b);
  const mid = Math.floor(slopes.length / 2);
  const medianMonthlySlope = (slopes.length % 2 !== 0) ? slopes[mid] : (slopes[mid - 1] + slopes[mid]) / 2;
  const slopeDecade = medianMonthlySlope * 120.0;

  let s = 0;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const diff = validSeries[j] - validSeries[i];
      if (diff > 0) s += 1;
      else if (diff < 0) s -= 1;
    }
  }

  let varS = (n * (n - 1) * (2 * n + 5)) / 18.0;
  let zPlain = 0;
  if (s > 0) zPlain = (s - 1) / Math.sqrt(varS);
  else if (s < 0) zPlain = (s + 1) / Math.sqrt(varS);
  const pPlain = 2 * (1 - normalCdf(Math.abs(zPlain)));

  const detrended = [];
  for (let k = 0; k < n; k++) {
    detrended.push(validSeries[k] - medianMonthlySlope * timeIndices[k]);
  }
  let meanDetrend = 0;
  for (let k = 0; k < n; k++) meanDetrend += detrended[k];
  meanDetrend /= n;

  let numAuto = 0, denAuto = 0;
  for (let k = 0; k < n; k++) {
    const dev = detrended[k] - meanDetrend;
    denAuto += dev * dev;
    if (k > 0) {
      numAuto += (detrended[k] - meanDetrend) * (detrended[k - 1] - meanDetrend);
    }
  }
  const r1 = denAuto > 0 ? Math.max(-0.99, Math.min(0.99, numAuto / denAuto)) : 0;
  let eta = 1.0;
  if (r1 > 0.05) {
    eta = 1.0 + (2.0 * r1) / (1.0 - r1);
  }
  const varS_HR = varS * eta;

  let zHR = 0;
  if (s > 0) zHR = (s - 1) / Math.sqrt(varS_HR);
  else if (s < 0) zHR = (s + 1) / Math.sqrt(varS_HR);
  const pHR = 2 * (1 - normalCdf(Math.abs(zHR)));

  return {
    slope: slopeDecade,
    p_hr: Math.min(1.0, Math.max(0.0, pHR)),
    p_plain: Math.min(1.0, Math.max(0.0, pPlain)),
  };
}

function rank(arr) {
  const sorted = arr.map((val, idx) => ({ val, idx })).sort((a, b) => a.val - b.val);
  const ranks = new Array(arr.length);
  for (let r = 0; r < sorted.length; r++) {
    ranks[sorted[r].idx] = r + 1;
  }
  return ranks;
}

function spearmanRankCorr(x, y) {
  const rx = rank(x);
  const ry = rank(y);
  const n = x.length;
  let dSq = 0;
  for (let i = 0; i < n; i++) {
    const d = rx[i] - ry[i];
    dSq += d * d;
  }
  return 1 - (6 * dSq) / (n * (n * n - 1));
}

function runValidation() {
  console.log('='.repeat(80));
  console.log(' NUMERICAL VALIDATION: JAVASCRIPT VS. PYTHON PRECOMPUTED TRENDS');
  console.log(' (Tested across 30 random valid cells per variable = 180 cells total)');
  console.log('='.repeat(80));
  console.log('Variable'.padEnd(18) + ' | ' + 'Tested Cells'.padEnd(12) + ' | ' + 'Max Slope Diff'.padEnd(16) + ' | ' + 'p-val Rank Corr (r_s)'.padEnd(22) + ' | ' + 'Status');
  console.log('-'.repeat(80));

  for (let vid of VARIABLES) {
    const dir = path.join(__dirname, '..', 'web', 'data', vid);
    const meta = JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf8'));
    const trendJson = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(dir, 'trend.json.gz'))).toString('utf8'));
    const anomBuffer = zlib.gunzipSync(fs.readFileSync(path.join(dir, 'anomalies.bin.gz')));
    const anomInt16 = new Int16Array(anomBuffer.buffer, anomBuffer.byteOffset, anomBuffer.byteLength / 2);

    const scaleFactor = meta.compression.anom_scale_factor;
    const slopeScale = trendJson.slope_scale;

    // Collect all valid cells
    const validCoords = [];
    for (let i = 0; i < N_LATS; i++) {
      for (let j = 0; j < N_LONS; j++) {
        if (trendJson.valid[i][j] === 1 && trendJson.slopes[i][j] !== -32768) {
          validCoords.push([i, j]);
        }
      }
    }

    // Deterministic random sample of 30 cells
    const sample = [];
    const step = Math.floor(validCoords.length / 30);
    for (let k = 0; k < 30; k++) {
      sample.push(validCoords[(k * step + 7) % validCoords.length]);
    }

    const pySlopes = [];
    const jsSlopes = [];
    const pyPvals = [];
    const jsPvals = [];
    let maxDiff = 0;

    for (let [i, j] of sample) {
      const pySlope = trendJson.slopes[i][j] * slopeScale;
      const pyP = trendJson.p_values[i][j];

      // Extract time series
      const s = [];
      for (let t = 0; t < 304; t++) {
        const raw = anomInt16[t * TOTAL_CELLS + i * N_LONS + j];
        s.push(raw === -32768 ? null : raw * scaleFactor);
      }

      const jsRes = computeClientStats(s);
      if (jsRes.slope !== null) {
        const diff = Math.abs(pySlope - jsRes.slope);
        if (diff > maxDiff) maxDiff = diff;

        pySlopes.push(pySlope);
        jsSlopes.push(jsRes.slope);
        pyPvals.push(pyP !== null ? pyP : 1.0);
        jsPvals.push(jsRes.p_hr !== null ? jsRes.p_hr : 1.0);
      }
    }

    const r_s = spearmanRankCorr(pyPvals, jsPvals);
    const status = maxDiff < 0.05 && r_s > 0.90 ? 'PASS' : 'WARN';

    console.log(
      `${vid.padEnd(18)} | ` +
      `${sample.length.toString().padEnd(12)} | ` +
      `${maxDiff.toExponential(3).padEnd(16)} | ` +
      `${r_s.toFixed(4).padEnd(22)} | ` +
      `${status}`
    );
  }
  console.log('='.repeat(80));
}

runValidation();
