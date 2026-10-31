.PHONY: help test fixture run validate clean

SERVICE_NAME ?= sc-report
PYTHON ?= python3
WORKFLOW ?= ab

.DEFAULT: help

help:
	@echo "Make Help for $(SERVICE_NAME)"
	@echo ""
	@echo "make test      - pytest: synthetic upstream outputs of workflows A and B (each alone, each port alone, none) through the processor, both layouts (no Docker)"
	@echo "make fixture   - write the synthetic fixture to data/fixture/{linked,flat}/ (WORKFLOW=ab, a or b)"
	@echo "make run       - build the image and run it in Docker over data/fixture/linked/ (or INPUT_HOST=...), writing to data/output/"
	@echo "make validate  - app.yml against the manifest schema, CITATION.cff with cffconvert"
	@echo "make clean     - remove data/output/"
	@echo ""
	@echo "PYTHON=$(PYTHON) (set PYTHON=.venv/bin/python after pip install -r requirements-dev.txt)"

test:
	$(PYTHON) -m pytest -q tests

fixture:
	$(PYTHON) -m tests.make_fixture data/fixture --layout both --workflow $(WORKFLOW)

run: clean fixture
	mkdir -p data/output
	docker compose -f docker-compose.yml down --remove-orphans
	docker compose -f docker-compose.yml build
	docker compose -f docker-compose.yml up --exit-code-from processor
	docker compose -f docker-compose.yml down --remove-orphans
	@echo "--- outputs:"
	@find data/output -type f | sort

validate:
	$(PYTHON) scripts/validate.py

clean:
	rm -rf data/output
