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


.PHONY: lint
lint:
	uv run ruff check $(app-dir)
	uv run ruff format --check $(app-dir)


.PHONY: typecheck
typecheck:
	uv run mypy


.PHONY: security
security:
	uv run bandit -r $(app-dir) -c pyproject.toml -q


.PHONY: complexity
complexity:
	uv run radon cc $(app-dir) -s -n C
	uv run radon mi $(app-dir) -s


# Полный статический контроль одним прогоном: стиль + типы + безопасность +
# сложность (см. scripts/check.sh). Падает, если обязательный чекер нашёл проблему.
.PHONY: check
check:
	./scripts/check.sh $(app-dir)


.PHONY: test
test:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run --extra dev pytest -q


.PHONY: dev
dev:
	python3.12 -m compileall bot
	./run.sh .env.dev


.PHONY: e2e
e2e:
	UV_CACHE_DIR=$(UV_CACHE_DIR) PYTHONPATH=. uv run python scripts/e2e_smoke.py
