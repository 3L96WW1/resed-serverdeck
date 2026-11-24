PYTHON ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

.PHONY: install dev test lint demo once check clean

install:
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install .

dev:
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e '.[dev]'

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check serverdeck tests
	$(PY) -m ruff format --check serverdeck tests

demo:
	$(PY) -m serverdeck --demo

once:
	$(PY) -m serverdeck --once

check:
	$(PY) -m serverdeck --check

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
	find serverdeck tests -type d -name __pycache__ -prune -exec rm -rf {} +
