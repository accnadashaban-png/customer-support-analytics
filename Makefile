.PHONY: setup sync test lint run report eval

setup:   ## install with dev tools
	pip install -e ".[dev]"

sync:    ## load demo data (safe to run again)
	python -m support_analytics sync

test:
	pytest --cov=support_analytics --cov-report=term-missing

lint:
	ruff check .
	mypy support_analytics

report: sync  ## last-30-day summary in the terminal
	python -m support_analytics report --days 30

run: sync    ## dashboard on http://127.0.0.1:8000
	uvicorn support_analytics.api.app:app --reload

eval:    ## metric accuracy: exact scenarios + invariants on 25 random datasets
	python -m support_analytics eval
