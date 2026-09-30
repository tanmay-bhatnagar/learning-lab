DOCLING_MODELS_DIR := $(CURDIR)/data/external/modelweights/docling
EMBEDDING_TOKENIZER_DIR := $(CURDIR)/data/external/modelweights/tokenizers/bert-base-uncased

.PHONY: setup docling-models embedding-tokenizer dev test build
setup:
	python3 -m venv .venv
	.venv/bin/pip install -r services/api/requirements-macos-py313.lock
	cd apps/web && npm ci

docling-models:
	mkdir -p "$(DOCLING_MODELS_DIR)"
	DOCLING_ARTIFACTS_PATH="$(DOCLING_MODELS_DIR)" .venv/bin/docling-tools models download --output-dir "$(DOCLING_MODELS_DIR)" layout tableformer

embedding-tokenizer:
	mkdir -p "$(EMBEDDING_TOKENIZER_DIR)"
	EMBEDDING_TOKENIZER_DIR="$(EMBEDDING_TOKENIZER_DIR)" .venv/bin/python scripts/download_embedding_tokenizer.py

dev:
	.venv/bin/python scripts/dev.py

test:
	PYTHONPATH=services/api .venv/bin/python -m pytest services/api/tests -q
	cd apps/web && npm test

build:
	cd apps/web && npm run build
