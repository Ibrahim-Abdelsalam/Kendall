// Statistical functions for Plot Twist in JavaScript

function normCdf(x) {
  // Constants for Abramowitz & Stegun approximation (formula 7.1.26)
  const a1 = 0.254829592;
  const a2 = -0.284496736;
  const a3 = 1.421413741;
  const a4 = -1.453152027;
  const a5 = 1.061405429;
  const p = 0.3275911;

  const sign = x < 0 ? -1 : 1;
  const absX = Math.abs(x) / Math.SQRT2;

  const t = 1.0 / (1.0 + p * absX);
  const y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-absX * absX);

  return 0.5 * (1.0 + sign * y);
}

function rankdata(arr) {
  const n = arr.length;
  const indexed = new Array(n);
  for (let i = 0; i < n; i++) {
    indexed[i] = { val: arr[i], idx: i };
  }
  indexed.sort((a, b) => a.val - b.val);

  const ranks = new Float64Array(n);
  let i = 0;
  while (i < n) {
    let j = i;
    while (j < n - 1 && indexed[j + 1].val === indexed[j].val) {
      j++;
    }
    const tieCount = j - i + 1;
    // average rank (1-based)
    const avgRank = (i + 1 + j + 1) / 2.0;
    for (let k = i; k <= j; k++) {
      ranks[indexed[k].idx] = avgRank;
    }
    i = j + 1;
  }
  return ranks;
}

function computeSensSlope(x) {
  const n = x.length;
  const slopes = [];
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      slopes.push((x[j] - x[i]) / (j - i));
    }
  }
  slopes.sort((a, b) => a - b);
  const mid = Math.floor(slopes.length / 2);
  const slope = slopes.length % 2 !== 0 ? slopes[mid] : (slopes[mid - 1] + slopes[mid]) / 2.0;
  return slope;
}

function computeMannKendall(x, alpha = 0.05) {
  const n = x.length;
  if (n < 4) {
    return { slope: 0, p: 1.0, z: 0, s: 0, trend: 'no trend' };
  }

  // Mann-Kendall score S
  let s = 0;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const diff = x[j] - x[i];
      if (diff > 0) s += 1;
      else if (diff < 0) s -= 1;
    }
  }

  // Ties calculation
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

  // Z-score
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
  if (n < 4) {
    return computeMannKendall(x, alpha);
  }

  const base = computeMannKendall(x, alpha);
  const s = base.s;
  const base_var_s = base.var_s;
  const slope = base.slope;

  // Detrend
  const x_detrend = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    x_detrend[i] = x[i] - (i + 1) * slope;
  }

  const ranks = rankdata(x_detrend);

  // Mean of ranks
  let sumR = 0;
  for (let i = 0; i < n; i++) sumR += ranks[i];
  const meanR = sumR / n;

  // Autocorrelation of ranks (ACF)
  const y = new Float64Array(n);
  for (let i = 0; i < n; i++) y[i] = ranks[i] - meanR;

  let varY = 0;
  for (let i = 0; i < n; i++) varY += y[i] * y[i];

  if (varY === 0) {
    return base;
  }

  // Critical bound
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
    trend: z_mod > 0 && p_mod < alpha ? 'increasing' : z_mod < 0 && p_mod < alpha ? 'decreasing' : 'no trend',
  };
}

module.exports = {
  normCdf,
  rankdata,
  computeSensSlope,
  computeMannKendall,
  computeHamedRao,
};
