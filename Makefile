# PRAT — Makefile
# Simple entrypoint for setup, analysis, and demos.

PYTHON   := python3
VENV     := .venv
PIP      := $(VENV)/bin/pip
PRAT     := $(VENV)/bin/prat
APP      := App

# Output directories
RESULTS  := results

.DEFAULT_GOAL := help

# ── Setup ───────────────────────────────────────────────────────────────────

.PHONY: setup
setup: $(VENV)/bin/prat  ## Create venv and install PRAT + dev deps

$(VENV)/bin/prat:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip -q
	$(PIP) install -e ".[dev]"
	@echo ""
	@echo "✓ PRAT installed. Activate with: source $(VENV)/bin/activate"

.PHONY: fetch
fetch:  ## Clone target projects (Mosquitto v2.0.15, FFmpeg n5.1.4) into App/
	bash scripts/fetch-targets.sh

.PHONY: fetch-mosquitto
fetch-mosquitto:  ## Clone only Mosquitto
	bash scripts/fetch-targets.sh mosquitto

.PHONY: fetch-ffmpeg
fetch-ffmpeg:  ## Clone only FFmpeg
	bash scripts/fetch-targets.sh ffmpeg

# ── Tests ───────────────────────────────────────────────────────────────────

.PHONY: test
test:  ## Run full test suite
	$(VENV)/bin/pytest src/tests/ -v

.PHONY: test-fast
test-fast:  ## Run tests (quiet, stop on first failure)
	$(VENV)/bin/pytest src/tests/ -q -x

# ── Analyses (local — requires App/ targets fetched) ────────────────────────

$(RESULTS):
	mkdir -p $(RESULTS)

.PHONY: demo-mosquitto-tls
demo-mosquitto-tls: $(RESULTS)  ## Analyze Mosquitto TLS feature (local)
	@test -d $(APP)/mosquitto || (echo "✗ App/mosquitto not found — run: make fetch-mosquitto" && exit 1)
	$(PRAT) $(APP)/mosquitto TLS --output $(RESULTS)/mosquitto-tls
	@echo ""
	@echo "✓ Reports in $(RESULTS)/mosquitto-tls/"

.PHONY: demo-mosquitto-bridge
demo-mosquitto-bridge: $(RESULTS)  ## Analyze Mosquitto BRIDGE feature (local)
	@test -d $(APP)/mosquitto || (echo "✗ App/mosquitto not found — run: make fetch-mosquitto" && exit 1)
	$(PRAT) $(APP)/mosquitto BRIDGE --output $(RESULTS)/mosquitto-bridge
	@echo ""
	@echo "✓ Reports in $(RESULTS)/mosquitto-bridge/"

.PHONY: demo-ffmpeg-x264
demo-ffmpeg-x264: $(RESULTS)  ## Analyze FFmpeg x264 feature (local)
	@test -d $(APP)/FFmpeg || (echo "✗ App/FFmpeg not found — run: make fetch-ffmpeg" && exit 1)
	$(PRAT) $(APP)/FFmpeg x264 --output $(RESULTS)/ffmpeg-x264
	@echo ""
	@echo "✓ Reports in $(RESULTS)/ffmpeg-x264/"

.PHONY: demo-all
demo-all: demo-mosquitto-tls demo-mosquitto-bridge demo-ffmpeg-x264  ## Run all three analyses

.PHONY: batch-mosquitto
batch-mosquitto: $(RESULTS)  ## Batch-analyze ALL Mosquitto features
	@test -d $(APP)/mosquitto || (echo "✗ App/mosquitto not found — run: make fetch-mosquitto" && exit 1)
	$(PRAT) $(APP)/mosquitto --batch --output $(RESULTS)/mosquitto-batch

# ── Docker Demos (self-contained — no local App/ needed) ────────────────────

.PHONY: docker-build
docker-build:  ## Build all Docker demo images
	$(PYTHON) src/demo-runner.py --build-all

.PHONY: docker-run
docker-run:  ## Run all Docker demos and generate comparison report
	$(PYTHON) src/demo-runner.py --run-all --output $(RESULTS)/docker --report $(RESULTS)/demo_report.txt

.PHONY: docker-demo-mosquitto-tls
docker-demo-mosquitto-tls:  ## Docker: build + run Mosquitto TLS demo
	$(PYTHON) src/demo-runner.py --build mosquitto-tls
	$(PYTHON) src/demo-runner.py --run mosquitto-tls --output $(RESULTS)/docker

.PHONY: docker-demo-mosquitto-bridge
docker-demo-mosquitto-bridge:  ## Docker: build + run Mosquitto Bridge demo
	$(PYTHON) src/demo-runner.py --build mosquitto-bridge
	$(PYTHON) src/demo-runner.py --run mosquitto-bridge --output $(RESULTS)/docker

.PHONY: docker-demo-ffmpeg
docker-demo-ffmpeg:  ## Docker: build + run FFmpeg x264 demo
	$(PYTHON) src/demo-runner.py --build ffmpeg-x264
	$(PYTHON) src/demo-runner.py --run ffmpeg-x264 --output $(RESULTS)/docker

# ── Utilities ───────────────────────────────────────────────────────────────

.PHONY: list-features
list-features:  ## List discoverable features for Mosquitto (requires App/mosquitto)
	@test -d $(APP)/mosquitto || (echo "✗ App/mosquitto not found — run: make fetch-mosquitto" && exit 1)
	$(PRAT) $(APP)/mosquitto --list

.PHONY: clean-results
clean-results:  ## Delete generated results/
	rm -rf $(RESULTS)

.PHONY: clean-venv
clean-venv:  ## Delete virtual environment
	rm -rf $(VENV)

.PHONY: clean
clean: clean-results  ## Clean results (keep venv and App/)

.PHONY: lint
lint:  ## Run ruff linter
	$(VENV)/bin/ruff check src/prat/

.PHONY: typecheck
typecheck:  ## Run mypy (advisory)
	$(VENV)/bin/mypy src/prat/

.PHONY: help
help:  ## Show this help
	@echo "PRAT — available targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*## "}; {printf "  %-28s %s\n", $$1, $$2}'
	@echo ""
	@echo "Quick start:"
	@echo "  make setup fetch demo-mosquitto-tls"
	@echo ""
	@echo "Docker (no local targets needed):"
	@echo "  make docker-build docker-run"
