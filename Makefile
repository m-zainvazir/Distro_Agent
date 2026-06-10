.PHONY: dev test test-phase2 lint db-migrate agent-test

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v --asyncio-mode=auto

test-phase2:
	pytest tests/workflows/test_phase2_workflow.py tests/agents/test_copywriter_agent.py tests/agents/test_negotiator.py tests/agents/test_scheduling.py tests/agents/test_reply_handler.py tests/services/test_email_service.py tests/services/test_similarity.py -v --asyncio-mode=auto

lint:
	ruff check app/ tests/
	mypy app/ --ignore-missing-imports

db-migrate:
	alembic upgrade head

agent-test:
	python -m scripts.test_agent
