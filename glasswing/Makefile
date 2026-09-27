.PHONY: api web test seed compose

export PYTHONPATH := packages/domain/src:packages/adapters/src:services/gateway/src:services/compiler/src:services/control-engine/src:services/investigator/src:services/actions/src:services/audit/src:services/ingestion/src

api:
	uv run uvicorn gateway.main:app --app-dir services/gateway/src --reload --port 8000

web:
	pnpm --dir apps/web dev

test:
	uv run pytest tests -q
	uv run ruff check packages services tests
	uv run mypy packages/domain/src/glasswing_domain
	pnpm --dir apps/web test

seed:
	uv run python scripts/seed_demo.py

compose:
	docker compose -f infra/docker-compose.yml up -d postgres redis localstack
