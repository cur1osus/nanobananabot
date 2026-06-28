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
	uv export --no-dev --no-emit-project --format requirements-txt > .reqs.tmp
	uvx --from safety safety check -r .reqs.tmp --output text || true
	@rm -f .reqs.tmp


.PHONY: complexity
complexity:
	uv run radon cc $(app-dir) -s -n C
	uv run radon mi $(app-dir) -s


# Профилирование живого процесса бота без остановки и правок кода.
# Использование: make profile PID=<pid>  (граф пламени → profile.svg)
.PHONY: profile
profile:
	uv run py-spy record -o profile.svg --pid $(PID)


# Полный статический контроль: стиль + типы + сложность + безопасность.
.PHONY: check
check: lint typecheck complexity security


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
