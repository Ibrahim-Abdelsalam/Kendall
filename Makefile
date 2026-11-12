.PHONY: audit test audit-data audit-stats audit-browser

audit:
	@bash scripts/run_all_checks.sh

test:
	@/opt/anaconda3/envs/plot-twist/bin/pytest tests/test_units.py tests/test_regridding.py tests/test_anomalies.py tests/test_statistics.py tests/test_regression.py tests/test_time_order.py -v

audit-data:
	@/opt/anaconda3/envs/plot-twist/bin/python src/audit.py

audit-stats:
	@/usr/local/bin/node tests/validate_js_stats.js

audit-browser:
	@/opt/anaconda3/bin/pytest tests/test_browser_smoke.py -v
