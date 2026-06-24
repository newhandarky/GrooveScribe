PYTHON ?= python3

.PHONY: backend-test pipeline-smoke normalize-help compile-check git-status

backend-test:
	cd backend && $(PYTHON) -m pytest

pipeline-smoke:
	PYTHONPATH=. $(PYTHON) scripts/run_local_pipeline.py --output-dir storage/local/jobs/dev-smoke

normalize-help:
	PYTHONPATH=. $(PYTHON) scripts/run_normalize_audio.py --help

compile-check:
	$(PYTHON) -m compileall backend/app ai_pipeline worker/app scripts

git-status:
	git status --short --branch
