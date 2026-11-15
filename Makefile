.PHONY: serve audit-data

serve:
	@python -m http.server 8000 --directory web

audit-data:
	@if [ -f /opt/anaconda3/envs/kendall/bin/python ]; then /opt/anaconda3/envs/kendall/bin/python src/audit.py; else python src/audit.py; fi
