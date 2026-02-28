app-dir = bot
UV_CACHE_DIR ?= .uv-cache

.PHONY: generate
generate:
	uv run alembic revision --m="$(NAME)" --autogenerate


.PHONY: migrate
migrate:
	uv run alembic upgrade head


.PHONY: format
format:
	uv run ruff check --fix --unsafe-fixes $(app-dir)
	uv run ruff format $(app-dir)


.PHONY: dev
dev:
	python3.12 -m compileall bot
	./run.sh .env.dev


.PHONY: e2e
e2e:
	UV_CACHE_DIR=$(UV_CACHE_DIR) PYTHONPATH=. uv run python scripts/e2e_smoke.py
