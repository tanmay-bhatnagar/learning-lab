.PHONY: setup dev test build
setup:
	python3 -m venv .venv
	.venv/bin/pip install -r services/api/requirements-macos-py313.lock
	cd apps/web && npm ci

dev:
	.venv/bin/python scripts/dev.py

test:
	PYTHONPATH=services/api .venv/bin/python -m pytest services/api/tests tests -q
	cd apps/web && npm test

build:
	cd apps/web && npm run build
