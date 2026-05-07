# Inspector_bottles — Проектный контекст

## Проект

Фреймворк для приложений с **многопроцессной архитектурой** (процессы-воркеры, разделяемая память, очередь задач).
На его основе — **прототип** системы инспекции дефектов через камеру (PySide6, OpenCV, детекция брака).

## Архитектура

- **Оркестрация:** `SystemLauncher` → `ProcessManagerProcess` → дочерние процессы (`ProcessModule`)
- **IPC:** `Message` / `MessageAdapter` → `RouterManager` → `shared_resources_module` (pickle-safe)
- **Внутри процесса:** `CommandManager`, `worker_module`, `LoggerManager` / `ErrorManager` / `StatsManager` (база `channel_routing_module`), `RouterManager`
- **Данные/конфиг:** `data_schema_module` (`SchemaBase`), `config_module` + `ConfigStore`
- **Состояние:** `state_store_module` — реактивное дерево (StateStoreManager + StateProxy + glob-подписки)
- **Pipeline-исполнители:** `chain_module` — DAG/Chain engine (ChainRunnable, DagRunnable, WorkerPoolDispatcher)
- **GUI:** `frontend_module` (PySide6), схемы регистров в приложении. Виджеты v3 сгруппированы по доменам (`chrome/`, `sources/`, `recipes/`, `processing/`, `settings/`, `pipeline/`, `tabs_setting/`, `base/`) — детали в [`docs/refactors/2026-04_widgets_reorg.md`](docs/refactors/2026-04_widgets_reorg.md).
- **Роутинг:** НЕ путать **имя процесса** (`targets`, `send_message`) и **канал Router** (`FieldRouting.channel`, `msg["channel"]`). См. `ROUTING_GLOSSARY.md`
- **Всего модулей в `multiprocess_framework/modules/`:** 21 (см. [`MODULES_STATUS.md`](multiprocess_framework/MODULES_STATUS.md), [`docs/MODULES_OVERVIEW.md`](multiprocess_framework/docs/MODULES_OVERVIEW.md))

## Ключевые пути

| Что | Путь |
|-----|------|
| **АКТИВНЫЙ прототип** | `multiprocess_prototype/` ← **только сюда вносить изменения** |
| Фреймворк | `multiprocess_framework/` |
| Документация фреймворка | `multiprocess_framework/docs/` (`MODULES_OVERVIEW.md`, `MODULE_CONTRACTS.md`, `DIAGRAMS.md`) |
| Конструктор-blueprint фреймворка (21 модуль) | [`multiprocess_framework/docs/CONSTRUCTOR_BLUEPRINT.md`](multiprocess_framework/docs/CONSTRUCTOR_BLUEPRINT.md) |
| Точка входа v3 | `multiprocess_prototype/run.py` |
| Регистры приложения v3 | `multiprocess_prototype/registers/` |
| Конспект правил | `docs/claude/FRAMEWORK_RULES_EXTRACT.md` |
| Нарратив «конструктор» | `docs/claude/FRAMEWORK_CONSTRUCTOR_OVERVIEW.md` |
| Настройка qex | `docs/claude/qex/README.md` (quick-start), `docs/claude/qex/SETUP_GUIDE.md` (полный) |

## АРХИВ — НЕ ТРОГАТЬ

> **CRITICAL:** Директории ниже — архивные версии прототипа. Агентам запрещено вносить в них изменения. Для любой задачи использовать только `multiprocess_prototype/`.

| Директория | Статус |
|-----------|--------|
| `multiprocess_prototype/` | АРХИВ v1 — только чтение |
| `multiprocess_prototype_v2/` | АРХИВ v2 — только чтение |

## Стек

Python 3.12 (см. корневой `pyproject.toml`), PySide6 6.10 (Phase 2 завершена 2026-04), OpenCV 4.13, NumPy 2.x | SQLite/PostgreSQL
Ollama, pytest + pytest-qt (`qt_api = pyside6`) | Pydantic v2, loguru
ML (Phase 1.5): PyTorch 2.11 + Ultralytics YOLO + ONNX Runtime — extras `[ml]` в pyproject

## Правила проекта

1. **Dict at Boundary** — между процессами только `dict` (`to_dict`/`from_dict`); Pydantic внутри процесса
2. Зависимости через `interfaces.py`; у каждого модуля `README.md`, `STATUS.md`, `tests/`
3. **ADR-решения:**
   - Локальные → `modules/X/DECISIONS.md`
   - Глобальные → `multiprocess_framework/DECISIONS.md`
4. **Тесты:** из корня — `python scripts/validate.py`, `python scripts/run_framework_tests.py`. Ручной pytest — из `` (иначе `ModuleNotFoundError`)
5. Конфиг на границе — dict, внутри Pydantic v2
6. Логи через `ObservableMixin`, пути из env (`MULTIPROCESS_LOG_DIR` / `INSPECTOR_LOG_DIR`)
7. Индекс ADR: `multiprocess_framework/DECISIONS.md` → ссылки на локальные DECISIONS.md
8. **Документация — auto-sync:** при правках `multiprocess_framework/DECISIONS.md` или `multiprocess_framework/modules/*/DECISIONS.md` запусти `python -m scripts.sync` для пересборки сводных разделов («Оглавление», «Модульные решения», «Устарело», «Коды модулей»). CI ловит дрифт через `python scripts/validate.py`. Список синхронизируемых разделов: `python -m scripts.sync --list`.

## MCP: qex (семантический поиск)

**qex** = Ollama (`qwen3-embedding:4b`) + BM25 (Tantivy) + brute-force dense vectors (`~/.qex/`). `search_code` — гибрид dense+sparse.
Холодный старт: `ollama serve` (или `/cold-start`). Docker/Qdrant не нужны.

**qex-first правило:** при рефакторинге, анализе «где используется», смене API/IPC-контракта — **сначала `mcp__qex__search_code`**, потом `Grep`. Подробная логика: `/qex-search`.

## Проектные команды

| Команда | Действие |
|---------|----------|
| `/validate` | `python scripts/validate.py` |
| `/fw-test` | `python scripts/run_framework_tests.py` |
| `/qex-status` | Статус qex-индекса |
| `/qex-reindex` | Переиндексация кодовой базы |
| `/run-proto` | Запуск прототипа |
| `/cold-start` | Холодный старт: Ollama + venv |
