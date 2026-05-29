# Inspector_bottles — единая точка входа для разработки
# Использование: make <target>
# Справка: make help

.DEFAULT_GOAL := help
SHELL := /bin/bash

# ── Пути ──
# `uv run` префикс — чтобы targets работали без активированной venv
# (на Windows venv часто не активирована в Git Bash / VSCode terminal).
UV_RUN := uv run
PYTHON := $(UV_RUN) python
PYTEST := $(UV_RUN) pytest
RUFF := $(UV_RUN) ruff
PYRIGHT := $(UV_RUN) pyright
BANDIT := $(UV_RUN) bandit

FRAMEWORK := multiprocess_framework
PROTOTYPE := multiprocess_prototype
SERVICES := Services
PLUGINS := Plugins
DIAGRAMS_DIR := docs/diagrams

# ── Быстрые проверки (секунды) ──

.PHONY: lint
lint: ## Ruff lint (без автофикса)
	$(RUFF) check .

.PHONY: lint-fix
lint-fix: ## Ruff lint + автофикс
	$(RUFF) check --fix .
	$(RUFF) format .

.PHONY: typecheck
typecheck: ## pyright type checking (gradual, basic mode)
	$(PYRIGHT) $(FRAMEWORK) $(PROTOTYPE)

.PHONY: security
security: ## bandit security scan
	$(BANDIT) -r $(FRAMEWORK) $(PROTOTYPE) $(SERVICES) -c pyproject.toml -q

.PHONY: check
check: lint typecheck security ## Все быстрые проверки (ruff + pyright + bandit)

# ── Тесты ──

.PHONY: test
test: ## pytest с coverage-отчётом
	$(PYTEST) --cov=$(FRAMEWORK) --cov-report=term-missing --cov-config=pyproject.toml

.PHONY: test-fast
test-fast: ## pytest без coverage (быстрее)
	$(PYTEST)

.PHONY: test-fw
test-fw: ## Тесты фреймворка (через скрипт)
	$(PYTHON) scripts/run_framework_tests.py

# ── Quality gate (полный цикл) ──

.PHONY: gate
gate: check test ## Полный gate: ruff + pyright + bandit + tests

# ── Диаграммы ──

.PHONY: diagrams
diagrams: diagrams-classes diagrams-per-module diagrams-deps ## Регенерация всех диаграмм

.PHONY: diagrams-classes
diagrams-classes: ## UML классов всего фреймворка (один большой файл)
	@mkdir -p $(DIAGRAMS_DIR)/classes
	pyreverse -o puml -p Framework $(FRAMEWORK) -d $(DIAGRAMS_DIR)/classes/ 2>/dev/null || \
		echo "[SKIP] pyreverse не установлен — uv sync --group diagrams"

.PHONY: diagrams-per-module
diagrams-per-module: ## UML по каждому модулю отдельно (читаемые файлы)
	@mkdir -p $(DIAGRAMS_DIR)/classes/per-module
	@for mod in $(FRAMEWORK)/modules/*_module $(FRAMEWORK)/modules/base_manager; do \
		if [ -d "$$mod" ]; then \
			name=$$(basename $$mod); \
			pyreverse -o puml -p "$$name" "$$mod" -d $(DIAGRAMS_DIR)/classes/per-module/ 2>/dev/null && \
			echo "[OK] $$name"; \
		fi; \
	done

.PHONY: diagrams-deps
diagrams-deps: ## Граф зависимостей через pydeps (требует Graphviz в PATH)
	@mkdir -p $(DIAGRAMS_DIR)/deps
	pydeps $(FRAMEWORK) -o $(DIAGRAMS_DIR)/deps/framework-overview.svg --cluster --max-bacon 2 --rankdir LR --no-show 2>/dev/null || \
		echo "[SKIP] pydeps/Graphviz не установлены — uv sync --group diagrams && winget install Graphviz"
	pydeps $(FRAMEWORK) -o $(DIAGRAMS_DIR)/deps/framework-modules.svg --cluster --max-bacon 2 --max-module-depth 3 --rankdir LR --no-show 2>/dev/null || true

# ── Валидация проекта ──

.PHONY: validate
validate: ## Валидация структуры (scripts/validate.py)
	$(PYTHON) scripts/validate.py

.PHONY: stats
stats: ## Статистика кода
	$(PYTHON) -m scripts.code_stats

# ── Запуск приложения ──

.PHONY: run
run: ## Запустить приложение (опц. PIPELINE=<имя>, напр. make run PIPELINE=inspection_basic)
	$(PYTHON) $(PROTOTYPE)/run.py $(PIPELINE)

# ── Очистка ──

.PHONY: clean
clean: ## Удалить Python-кэши (pyright/ruff caches тоже)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pyright_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".coverage" -delete 2>/dev/null || true
	@echo "Кэши очищены"

# ── Справка ──

.PHONY: help
help: ## Показать эту справку
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
