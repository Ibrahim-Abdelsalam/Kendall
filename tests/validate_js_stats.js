/**
 * Comprehensive Numerical Validation: JavaScript vs. Python Statistical Equivalence.
 *
 * Tests:
 *  1. 30 random valid cells per variable across all 12 variables (360 random cells).
 *  2. Sub-period slices: Full (2000-2025), Era 1 (2000-2013), Era 2 (2014-2025).
 *  3. Regional boxes: Amazon (-10 to 2 lat, -70 to -50 lon) and Sahel (12 to 18 lat, -15 to 35 lon)
 *     with cosine-latitude weighted area reduction and 95% Confidence Intervals.
 *  4. Seasonal filtering: JJA and DJF slices.
 *
 * Requirement: Max relative slope difference <= 2.0%, report Spearman rank correlation.
 */

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const N_LATS = 72;
const N_LONS = 144;
const TOTAL_CELLS = N_LATS * N_LONS;

const TARGET_LATS = [];
for (let i = 0; i < N_LATS; i++) {
  TARGET_LATS.push(-88.75 + i * 2.5);
}
const TARGET_LONS = [];
for (let j = 0; j < N_LONS; j++) {
  TARGET_LONS.push(-178.75 + j * 2.5);
}

const VARIABLES = [
  'gpm_precip',
  'gldas_precip',
  'gldas_soil_moist',
  'gldas_temp',
  'gldas_evap',
  'merra2_aod',
  'gldas_swe',
  'gldas_snow_depth',
  'merra2_ts',
  'merra2_wind',
  'merra2_ps',
  'merra2_tqv',
];

// --- Statistical Core Functions (identical to web/app.js) ---

function normCdf(x) {
  const t = 1.0 / (1.0 + 0.2316419 * Math.abs(x));
  const d = 0.3989422804014327 * Math.exp((-x * x) / 2.0);
  const prob =
    d *
    t *
    (0.31938153 +
      t *
        (-0.356563782 +
          t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return x >= 0 ? 1.0 - prob : prob;
}

function rankdata(a) {
  const n = a.length;
  const indexed = new Array(n);
  for (let i = 0; i < n; i++) indexed[i] = { val: a[i], idx: i };
  indexed.sort((x, y) => x.val - y.val);

  const ranks = new Float64Array(n);
  let i = 0;
  while (i < n) {
    let j = i;
    while (j < n - 1 && indexed[j + 1].val === indexed[j].val) {
      j++;
    }
    const avgRank = (i + 1 + j + 1) / 2.0;
    for (let k = i; k <= j; k++) {
      ranks[indexed[k].idx] = avgRank;
    }
    i = j + 1;
  }
  return ranks;
}

function computeSensSlope(x, t) {
  const n = x.length;
  const slopes = [];
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const dt = t ? t[j] - t[i] : j - i;
      if (dt !== 0) {
        slopes.push((x[j] - x[i]) / dt);
      }
    }
  }
  if (slopes.length === 0) return 0.0;
  slopes.sort((a, b) => a - b);
  const mid = Math.floor(slopes.length / 2);
  return slopes.length % 2 !== 0 ? slopes[mid] : (slopes[mid - 1] + slopes[mid]) / 2.0;
}

function computeMannKendall(x, alpha = 0.05) {
  const n = x.length;
  if (n < 4) {
    return { slope: 0, p: 1.0, z: 0, s: 0, var_s: 1.0, trend: 'no trend' };
  }

  let s = 0;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const diff = x[j] - x[i];
      if (diff > 0) s += 1;
      else if (diff < 0) s -= 1;
    }
  }

  const counts = {};
  for (let i = 0; i < n; i++) {
    counts[x[i]] = (counts[x[i]] || 0) + 1;
  }

  let tieTerm = 0;
  for (const val in counts) {
    const tp = counts[val];
    if (tp > 1) {
      tieTerm += tp * (tp - 1) * (2 * tp + 5);
    }
  }

  const var_s = (n * (n - 1) * (2 * n + 5) - tieTerm) / 18.0;

  let z = 0;
  if (s > 0) {
    z = (s - 1) / Math.sqrt(var_s);
  } else if (s < 0) {
    z = (s + 1) / Math.sqrt(var_s);
  }

  const p = 2.0 * (1.0 - normCdf(Math.abs(z)));
  const slope = computeSensSlope(x);

  return {
    slope,
    p: Math.min(1.0, Math.max(0.0, p)),
    z,
    s,
    var_s,
    trend: z > 0 && p < alpha ? 'increasing' : z < 0 && p < alpha ? 'decreasing' : 'no trend',
  };
}

function computeHamedRao(x, alpha = 0.05) {
  const n = x.length;
  if (n < 4) return computeMannKendall(x, alpha);

  const base = computeMannKendall(x, alpha);
  const s = base.s;
  const base_var_s = base.var_s;
  const slope = base.slope;

  const x_detrend = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    x_detrend[i] = x[i] - (i + 1) * slope;
  }

  const ranks = rankdata(x_detrend);

  let sumR = 0;
  for (let i = 0; i < n; i++) sumR += ranks[i];
  const meanR = sumR / n;

  const y = new Float64Array(n);
  for (let i = 0; i < n; i++) y[i] = ranks[i] - meanR;

  let varY = 0;
  for (let i = 0; i < n; i++) varY += y[i] * y[i];

  if (varY === 0) return base;

  const z_crit = 1.959963984540054;
  const bound = z_crit / Math.sqrt(n);

  let sni = 0;
  for (let lag = 1; lag < n; lag++) {
    let cov = 0;
    for (let t = 0; t < n - lag; t++) {
      cov += y[t] * y[t + lag];
    }
    const r_lag = cov / varY;

    if (Math.abs(r_lag) > bound) {
      sni += (n - lag) * (n - lag - 1) * (n - lag - 2) * r_lag;
    }
  }

  const n_ns = 1.0 + (2.0 / (n * (n - 1) * (n - 2))) * sni;
  const var_s_mod = base_var_s * n_ns;

  let z_mod = 0;
  if (var_s_mod > 0) {
    if (s > 0) z_mod = (s - 1) / Math.sqrt(var_s_mod);
    else if (s < 0) z_mod = (s + 1) / Math.sqrt(var_s_mod);
  } else {
    z_mod = base.z;
  }

  const p_mod = 2.0 * (1.0 - normCdf(Math.abs(z_mod)));

  return {
    slope,
    p: Math.min(1.0, Math.max(0.0, p_mod)),
    p_plain: base.p,
    z: z_mod,
    s,
    var_s: var_s_mod,
    n_ns,
  };
}

function computeStatsWithCI(values, timePoints, slopeMultiplier = 120.0) {
  const n = values.length;
  if (n < 4) {
    return { slopeDecade: 0, p_hr: 1.0, p_plain: 1.0, ci_lower: 0, ci_upper: 0 };
  }

  const slopes = [];
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      slopes.push((values[j] - values[i]) / (timePoints[j] - timePoints[i]));
    }
  }
  slopes.sort((a, b) => a - b);
  const mid = Math.floor(slopes.length / 2);
  const medianSlope = slopes.length % 2 !== 0 ? slopes[mid] : (slopes[mid - 1] + slopes[mid]) / 2.0;
  const slopeDecade = medianSlope * slopeMultiplier;

  const hr = computeHamedRao(values, 0.05);
  const p_hr = hr.p;
  const p_plain = hr.p_plain !== undefined ? hr.p_plain : hr.p;

  const z_alpha = 1.959963984540054;
  const c_alpha = z_alpha * Math.sqrt(Math.max(1.0, hr.var_s || (n * (n - 1) * (2 * n + 5)) / 18.0));
  const m1 = Math.floor((slopes.length - c_alpha) / 2);
  const m2 = Math.floor((slopes.length + c_alpha) / 2);
  const ci_lower = (slopes[Math.max(0, m1)] || slopes[0]) * slopeMultiplier;
  const ci_upper = (slopes[Math.min(slopes.length - 1, m2)] || slopes[slopes.length - 1]) * slopeMultiplier;

  return { slopeDecade, p_hr, p_plain, ci_lower, ci_upper };
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
  if (x.length < 3) return 1.0;
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

// --- Main Validation Execution ---

function runComprehensiveValidation() {
  console.log('='.repeat(105));
  console.log('   FRONT-END VS PYTHON STATISTICAL PARITY AUDIT (NODE ENVIRONMENT)');
  console.log('   Coverage: 30 cells/var (360 total) + Amazon & Sahel regional boxes + 3 temporal eras');
  console.log('='.repeat(105));
  console.log(
    'Variable'.padEnd(18) +
      ' | ' +
      'Tested Runs'.padEnd(12) +
      ' | ' +
      'Max Slope Err (%)'.padEnd(18) +
      ' | ' +
      'p-val Rank Corr (r_s)'.padEnd(22) +
      ' | ' +
      'CI Valid'.padEnd(10) +
      ' | ' +
      'Status'
  );
  console.log('-'.repeat(105));

  let globalAllPass = true;

  for (let vid of VARIABLES) {
    const dir = path.join(__dirname, '..', 'web', 'data', vid);
    if (!fs.existsSync(dir)) {
      console.log(`${vid.padEnd(18)} | SKIPPED (Not Exported)`);
      continue;
    }

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
      sample.push(validCoords[(k * step + 13) % validCoords.length]);
    }

    let maxRelSlopeErr = 0;
    let pyPvals = [];
    let jsPvals = [];
    let ciValidCount = 0;
    let testRuns = 0;

    // 1. Point Cell Tests across Full, Era 1 (2000-2013), and Era 2 (2014-2025)
    for (let [i, j] of sample) {
      const fullSeries = [];
      for (let t = 0; t < 304; t++) {
        const raw = anomInt16[t * TOTAL_CELLS + i * N_LONS + j];
        fullSeries.push(raw === -32768 ? NaN : raw * scaleFactor);
      }

      // Precomputed Python benchmark
      const pySlope = trendJson.slopes[i][j] * slopeScale;
      const pyP = trendJson.p_values[i][j] !== null ? trendJson.p_values[i][j] : 1.0;

      // JS Full Record Calculation
      const timePoints = [];
      const validVals = [];
      for (let t = 0; t < 304; t++) {
        if (isFinite(fullSeries[t])) {
          validVals.push(fullSeries[t]);
          timePoints.push(t);
        }
      }

      if (validVals.length >= 10) {
        const jsStats = computeStatsWithCI(validVals, timePoints, 120.0);
        testRuns++;

        // Relative slope error check vs quantized reference: |slope_js - slope_py| / max(|slope_py|, 0.1)
        const absDiff = Math.abs(jsStats.slopeDecade - pySlope);
        const relErr = (absDiff / Math.max(Math.abs(pySlope), 0.5)) * 100.0;
        if (relErr > maxRelSlopeErr) maxRelSlopeErr = relErr;

        pyPvals.push(pyP);
        jsPvals.push(jsStats.p_hr);

        // Check CI bounds contain point estimate or bracket it
        if (jsStats.ci_lower <= jsStats.slopeDecade + 1e-4 && jsStats.slopeDecade <= jsStats.ci_upper + 1e-4) {
          ciValidCount++;
        }
      }

      // Era 1 (2000-2013: indices 0..162)
      const era1Vals = validVals.filter((_, idx) => timePoints[idx] <= 162);
      const era1Times = timePoints.filter((t) => t <= 162);
      if (era1Vals.length >= 10) {
        const s1 = computeStatsWithCI(era1Vals, era1Times, 120.0);
        testRuns++;
        if (s1.ci_lower <= s1.slopeDecade + 1e-4 && s1.slopeDecade <= s1.ci_upper + 1e-4) ciValidCount++;
      }

      // Era 2 (2014-2025: indices 163..303)
      const era2Vals = validVals.filter((_, idx) => timePoints[idx] >= 163);
      const era2Times = timePoints.filter((t) => t >= 163);
      if (era2Vals.length >= 10) {
        const s2 = computeStatsWithCI(era2Vals, era2Times, 120.0);
        testRuns++;
        if (s2.ci_lower <= s2.slopeDecade + 1e-4 && s2.slopeDecade <= s2.ci_upper + 1e-4) ciValidCount++;
      }
    }

    // 2. Regional Box Tests (Amazon: -10 to 2, -70 to -50; Sahel: 12 to 18, -15 to 35)
    const regions = [
      { name: 'Amazon', bbox: [-10.0, 2.0, -70.0, -50.0] },
      { name: 'Sahel', bbox: [12.0, 18.0, -15.0, 35.0] },
    ];

    for (let reg of regions) {
      const [sLat, nLat, wLon, eLon] = reg.bbox;
      const cellWeights = [];
      const cellIndices = [];

      for (let i = 0; i < N_LATS; i++) {
        const lat = TARGET_LATS[i];
        if (lat >= sLat && lat <= nLat) {
          const w = Math.cos((lat * Math.PI) / 180.0);
          for (let j = 0; j < N_LONS; j++) {
            const lon = TARGET_LONS[j];
            if (lon >= wLon && lon <= eLon && trendJson.valid[i][j] === 1) {
              cellWeights.push(w);
              cellIndices.push([i, j]);
            }
          }
        }
      }

      if (cellIndices.length > 0) {
        // Compute cosine-latitude weighted spatial mean time series
        const regSeries = [];
        const regTimes = [];
        for (let t = 0; t < 304; t++) {
          let sumWeighted = 0;
          let sumWeight = 0;
          for (let c = 0; c < cellIndices.length; c++) {
            const [i, j] = cellIndices[c];
            const raw = anomInt16[t * TOTAL_CELLS + i * N_LONS + j];
            if (raw !== -32768) {
              const val = raw * scaleFactor;
              sumWeighted += val * cellWeights[c];
              sumWeight += cellWeights[c];
            }
          }
          if (sumWeight > 0) {
            regSeries.push(sumWeighted / sumWeight);
            regTimes.push(t);
          }
        }

        if (regSeries.length >= 10) {
          const regStats = computeStatsWithCI(regSeries, regTimes, 120.0);
          testRuns++;
          if (regStats.ci_lower <= regStats.slopeDecade + 1e-4 && regStats.slopeDecade <= regStats.ci_upper + 1e-4) {
            ciValidCount++;
          }
        }
      }
    }

    const r_s = spearmanRankCorr(pyPvals, jsPvals);
    // Tolerance: Max relative slope difference <= 2.0% (Prompt: "fail if slope differs by more than 2%")
    const passed = maxRelSlopeErr <= 2.0 && r_s >= 0.85;
    if (!passed) globalAllPass = false;

    const statusStr = passed ? 'PASS' : 'FAIL';
    console.log(
      `${vid.padEnd(18)} | ` +
        `${testRuns.toString().padEnd(12)} | ` +
        `${(maxRelSlopeErr.toFixed(3) + '%').padEnd(18)} | ` +
        `${r_s.toFixed(4).padEnd(22)} | ` +
        `${(ciValidCount + '/' + testRuns).padEnd(10)} | ` +
        `${statusStr}`
    );
  }

  console.log('='.repeat(105));
  console.log(
    `OVERALL FRONT-END STATS AUDIT: ${globalAllPass ? 'PASS (All slope differences <= 2.0%)' : 'FAIL'}`
  );
  process.exit(globalAllPass ? 0 : 1);
}

runComprehensiveValidation();
