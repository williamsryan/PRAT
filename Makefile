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

.PHONY: fetch-uamqp
fetch-uamqp:  ## Clone only azure-uamqp-c
	bash scripts/fetch-targets.sh uamqp

.PHONY: fetch-opendds
fetch-opendds:  ## Clone only OpenDDS
	bash scripts/fetch-targets.sh opendds

.PHONY: fetch-quiche
fetch-quiche:  ## Clone only Quiche
	bash scripts/fetch-targets.sh quiche

.PHONY: fetch-rav1e
fetch-rav1e:  ## Clone only rav1e
	bash scripts/fetch-targets.sh rav1e

.PHONY: fetch-aom
fetch-aom:  ## Clone only AOM (libaom)
	bash scripts/fetch-targets.sh aom

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

.PHONY: demo-ffmpeg-dca
demo-ffmpeg-dca: $(RESULTS)  ## Analyze FFmpeg DTS (dca) decoder feature (local)
	@test -d $(APP)/FFmpeg || (echo "✗ App/FFmpeg not found — run: make fetch-ffmpeg" && exit 1)
	$(PRAT) $(APP)/FFmpeg decoder=dca --output $(RESULTS)/ffmpeg-dca
	@echo ""
	@echo "✓ Reports in $(RESULTS)/ffmpeg-dca/"

.PHONY: demo-all
demo-all: demo-mosquitto-tls demo-mosquitto-bridge demo-ffmpeg-dca  ## Run the local single-feature analyses

# ── Batch / Graphs ──────────────────────────────────────────────────────────

.PHONY: batch-mosquitto
batch-mosquitto: $(RESULTS)  ## Batch-analyze ALL Mosquitto features
	@test -d $(APP)/mosquitto || (echo "✗ App/mosquitto not found — run: make fetch-mosquitto" && exit 1)
	$(PRAT) $(APP)/mosquitto --batch --output $(RESULTS)/mosquitto-batch

.PHONY: list-features-all
list-features-all: $(RESULTS)  ## List discovered features for every fetched target
	@for d in $(APP)/*/; do \
	  [ -d "$$d" ] || continue; \
	  echo ""; echo "=== $$d ==="; \
	  $(PRAT) "$$d" --list --verbose || true; \
	done

.PHONY: variants-mosquitto
variants-mosquitto: $(RESULTS)  ## Build the paper's 8-variant cumulative Mosquitto chain
	@test -d $(APP)/mosquitto || (echo "✗ App/mosquitto not found — run: make fetch-mosquitto" && exit 1)
	$(PRAT) $(APP)/mosquitto --variants 8 --output $(RESULTS)/mosquitto-variants

.PHONY: fuzz-mosquitto
fuzz-mosquitto: $(RESULTS)  ## Build the 8-variant chain and fuzz each variant over MQTT
	@test -d $(APP)/mosquitto || (echo "✗ App/mosquitto not found — run: make fetch-mosquitto" && exit 1)
	@$(VENV)/bin/python -c "import boofuzz" 2>/dev/null || \
	  (echo "✗ boofuzz not installed — run: $(VENV)/bin/pip install 'prat[fuzz]'" && exit 1)
	$(PRAT) $(APP)/mosquitto --variants 8 --fuzz --fuzz-seconds $${FUZZ_SECONDS:-600} \
	  --output $(RESULTS)/mosquitto-fuzz

.PHONY: graph
graph: $(RESULTS)  ## Open feature graph HTML (requires prior analysis run)
	@GRAPH=$$(find $(RESULTS) -name "feature_graph.html" | head -1); \
	if [ -z "$$GRAPH" ]; then \
	  GRAPH=$$(find $(RESULTS) -name "*.html" | head -1); \
	fi; \
	if [ -z "$$GRAPH" ]; then \
	  echo "✗ No HTML reports found in $(RESULTS)/ — run an analysis first"; exit 1; \
	fi; \
	open "$$GRAPH" 2>/dev/null || xdg-open "$$GRAPH" 2>/dev/null || echo "✓ Open manually: $$GRAPH"

# ── Docker Demos (self-contained — no local App/ needed) ────────────────────

.PHONY: docker-build
docker-build:  ## Build all Docker demo images
	$(PYTHON) src/demo-runner.py --build-all

.PHONY: docker-run
docker-run:  ## Run all Docker demos (cleans each image after run) and report
	$(PYTHON) src/demo-runner.py --run-all --cleanup --output $(RESULTS)/docker --report $(RESULTS)/demo_report.txt

.PHONY: docker-demo-mosquitto-tls
docker-demo-mosquitto-tls:  ## Docker: build + run Mosquitto TLS demo
	$(PYTHON) src/demo-runner.py --build mosquitto-tls
	$(PYTHON) src/demo-runner.py --run mosquitto-tls --output $(RESULTS)/docker

.PHONY: docker-demo-mosquitto-bridge
docker-demo-mosquitto-bridge:  ## Docker: build + run Mosquitto Bridge demo
	$(PYTHON) src/demo-runner.py --build mosquitto-bridge
	$(PYTHON) src/demo-runner.py --run mosquitto-bridge --output $(RESULTS)/docker

.PHONY: demo-release
demo-release:  ## Committee-safe Docker demo: Mosquitto TLS with manifest/logs
	$(PYTHON) src/demo-runner.py --build mosquitto-tls
	$(PYTHON) src/demo-runner.py --run mosquitto-tls --output $(RESULTS)/release-demo --report $(RESULTS)/release-demo/demo_report.txt
	@echo ""
	@echo "✓ Release demo artifacts in $(RESULTS)/release-demo/mosquitto-tls/"
	@echo "  - report.html"
	@echo "  - report.json"
	@echo "  - workflow_checkpoint.json"
	@echo "  - manifest.json"
	@echo "  - demo_manifest.json"
	@echo "  - container.log"

.PHONY: docker-demo-ffmpeg
docker-demo-ffmpeg:  ## Docker: build + run FFmpeg dca decoder demo
	$(PYTHON) src/demo-runner.py --build ffmpeg-dca
	$(PYTHON) src/demo-runner.py --run ffmpeg-dca --output $(RESULTS)/docker

.PHONY: docker-demo-uamqp
docker-demo-uamqp:  ## Docker: build + run azure-uamqp-c WebSockets demo
	$(PYTHON) src/demo-runner.py --build uamqp-websockets
	$(PYTHON) src/demo-runner.py --run uamqp-websockets --output $(RESULTS)/docker

.PHONY: docker-demo-opendds
docker-demo-opendds:  ## Docker: build + run OpenDDS content-filtered-topic demo
	$(PYTHON) src/demo-runner.py --build opendds-content-filtered-topic
	$(PYTHON) src/demo-runner.py --run opendds-content-filtered-topic --output $(RESULTS)/docker

.PHONY: docker-demo-quiche
docker-demo-quiche:  ## Docker: build + run Quiche qlog demo
	$(PYTHON) src/demo-runner.py --build quiche-qlog
	$(PYTHON) src/demo-runner.py --run quiche-qlog --output $(RESULTS)/docker

.PHONY: docker-demo-aom
docker-demo-aom:  ## Docker: build + run AOM encoder demo
	$(PYTHON) src/demo-runner.py --build aom-encoder
	$(PYTHON) src/demo-runner.py --run aom-encoder --output $(RESULTS)/docker

.PHONY: docker-build-all
docker-build-all: docker-build  ## Alias for docker-build (all images)

.PHONY: validate
validate:  ## Validate demo results against paper-reported numbers
	$(PYTHON) scripts/validate_paper_results.py $(RESULTS)/docker/ --json $(RESULTS)/validation_report.json

.PHONY: paper-check
paper-check:  ## Disk-safe full pipeline: per-demo build → run → rmi, then validate
	@mkdir -p $(RESULTS)/docker
	@for d in mosquitto-tls mosquitto-bridge ffmpeg-dca uamqp-websockets opendds-content-filtered-topic quiche-qlog aom-encoder; do \
	  echo "=== $$d ==="; \
	  $(PYTHON) src/demo-runner.py --build $$d || echo "[!] build failed: $$d (continuing)"; \
	  $(PYTHON) src/demo-runner.py --run $$d --cleanup --output $(RESULTS)/docker || echo "[!] run failed: $$d (continuing)"; \
	done
	$(MAKE) validate

.PHONY: paper-check-fast
paper-check-fast:  ## Quick pipeline: only the fast Mosquitto demos, then validate
	@mkdir -p $(RESULTS)/docker
	@for d in mosquitto-tls mosquitto-bridge; do \
	  $(PYTHON) src/demo-runner.py --build $$d; \
	  $(PYTHON) src/demo-runner.py --run $$d --cleanup --output $(RESULTS)/docker; \
	done
	$(MAKE) validate

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
lint:  ## Run ruff linter (src/)
	$(VENV)/bin/ruff check src/

.PHONY: typecheck
typecheck:  ## Run mypy type checker (src/prat/)
	$(VENV)/bin/mypy src/prat/

.PHONY: package-check
package-check:  ## Build source/wheel artifacts and validate metadata
	$(VENV)/bin/python -m build
	$(VENV)/bin/twine check dist/*

.PHONY: doctor
doctor:  ## Check local PRAT dependencies and optional Docker support
	$(PRAT) doctor

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
