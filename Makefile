.PHONY: dev test lint db-migrate agent-test

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v --asyncio-mode=auto

lint:
	ruff check app/ tests/
	mypy app/ --ignore-missing-imports

db-migrate:
	alembic upgrade head

agent-test:
	python -m scripts.test_agent
