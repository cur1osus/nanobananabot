#!/usr/bin/env bash
# Полный статический контроль проекта одним прогоном: стиль, типы,
# безопасность и сложность.
#
#   ./scripts/check.sh            # проверить bot/
#   ./scripts/check.sh path/to    # проверить произвольный путь (кроме mypy*)
#
# Обязательные чекеры (ruff, mypy, bandit) валят сборку — код возврата != 0,
# если хоть один нашёл проблему. radon — информационный: показывает горячие
# точки сложности, но на код возврата не влияет.
#
# * mypy берёт список файлов из [tool.mypy] в pyproject.toml (files = ["bot"]),
#   поэтому аргумент пути на него не действует.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
TARGET="${1:-bot}"

bold_blue=$'\033[1;34m'; green=$'\033[1;32m'; red=$'\033[1;31m'; reset=$'\033[0m'
failed=()

run() {
    # run "<имя>" <команда...> — печатает заголовок и фиксирует провал.
    local name="$1"; shift
    printf '\n%s=== %s ===%s\n' "$bold_blue" "$name" "$reset"
    if "$@"; then
        printf '%s✓ %s — ок%s\n' "$green" "$name" "$reset"
    else
        printf '%s✗ %s — есть замечания%s\n' "$red" "$name" "$reset"
        failed+=("$name")
    fi
}

# --- Обязательные проверки -------------------------------------------------
run "ruff lint"   uv run ruff check "$TARGET"
run "ruff format" uv run ruff format --check "$TARGET"
run "mypy"        uv run mypy
run "bandit"      uv run bandit -r "$TARGET" -c pyproject.toml -q

# --- Информационная: сложность --------------------------------------------
printf '\n%s=== radon (сложность ≥ C / maintainability) ===%s\n' "$bold_blue" "$reset"
uv run radon cc "$TARGET" -s -n C
uv run radon mi "$TARGET" -s

# --- Итог ------------------------------------------------------------------
printf '\n%s=== Итог ===%s\n' "$bold_blue" "$reset"
if (( ${#failed[@]} )); then
    printf '%sПровалено: %s%s\n' "$red" "${failed[*]}" "$reset"
    exit 1
fi
printf '%sВсе обязательные проверки пройдены.%s\n' "$green" "$reset"
