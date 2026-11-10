
    const fs = require('fs');
    const { computeHamedRao } = require('./test_js_stats_engine.js');

    const cases = JSON.parse(fs.readFileSync('scratch/validation_input.json', 'utf8'));
    const results = {};

    for (const tc of cases) {
      const valid = tc.data.filter(v => v !== null && isFinite(v));
      if (valid.length < 10) {
        results[tc.id] = { slope: 0, p_hr: 1.0, p_plain: 1.0 };
        continue;
      }
      const res = computeHamedRao(valid);
      results[tc.id] = {
        slope: res.slope * 120.0,
        p_hr: res.p,
        p_plain: res.p_plain,
      };
    }

    fs.writeFileSync('scratch/validation_output_js.json', JSON.stringify(results));
    