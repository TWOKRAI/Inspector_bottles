# Inspector_bottles — Проектный контекст

## Проект

Фреймворк для приложений с **многопроцессной архитектурой** (процессы-воркеры, разделяемая память, очередь задач).
На его основе — **прототип** системы инспекции дефектов через камеру (PyQt5, OpenCV, детекция брака).

## Архитектура

- **Оркестрация:** `SystemLauncher` → `ProcessManagerProcess` → дочерние процессы (`ProcessModule`)
- **IPC:** `Message` / `MessageAdapter` → `RouterManager` → `shared_resources_module` (pickle-safe)
- **Внутри процесса:** `CommandManager`, `worker_module`, `LoggerManager` / `ErrorManager` / `StatsManager` (база `channel_routing_module`), `RouterManager`
- **Данные/конфиг:** `data_schema_module` (`SchemaBase`), `config_module` + `ConfigStore`
- **GUI:** `frontend_module` (PyQt5), схемы регистров в приложении
- **Роутинг:** НЕ путать **имя процесса** (`targets`, `send_message`) и **канал Router** (`FieldRouting.channel`, `msg["channel"]`). См. `ROUTING_GLOSSARY.md`

## Ключевые пути

| Что | Путь |
|-----|------|
| **АКТИВНЫЙ прототип** | `Inspector_prototype/multiprocess_prototype_v3/` ← **только сюда вносить изменения** |
| Фреймворк | `Inspector_prototype/multiprocess_framework/` |
| Документация фреймворка | `multiprocess_framework/docs/` (`FRAMEWORK_OVERVIEW.md`, `ARCHITECTURE_REFERENCE.md`) |
| Точка входа v3 | `multiprocess_prototype_v3/run.py` |
| Регистры приложения v3 | `multiprocess_prototype_v3/registers/` |
| Конспект правил | `docs/claude/FRAMEWORK_RULES_EXTRACT.md` |
| Нарратив «конструктор» | `docs/claude/FRAMEWORK_CONSTRUCTOR_OVERVIEW.md` |
| Настройка qex | `docs/claude/qex/README.md` (quick-start), `docs/claude/qex/SETUP_GUIDE.md` (полный) |

## АРХИВ — НЕ ТРОГАТЬ

> **CRITICAL:** Директории ниже — архивные версии прототипа. Агентам запрещено вносить в них изменения. Для любой задачи использовать только `multiprocess_prototype_v3/`.

| Директория | Статус |
|-----------|--------|
| `Inspector_prototype/multiprocess_prototype/` | АРХИВ v1 — только чтение |
| `Inspector_prototype/multiprocess_prototype_v2/` | АРХИВ v2 — только чтение |

## Стек

Python 3.12 (см. корневой `pyproject.toml`), PyQt5 → PySide6 (Phase 2), OpenCV 4.13, NumPy 2.x | SQLite/PostgreSQL, Qdrant
Docker, Ollama, pytest | Pydantic v2, loguru
ML (Phase 1.5): PyTorch 2.11 + Ultralytics YOLO + ONNX Runtime — extras `[ml]` в pyproject

## Правила проекта

1. **Dict at Boundary** — между процессами только `dict` (`to_dict`/`from_dict`); Pydantic внутри процесса
2. Зависимости через `interfaces.py`; у каждого модуля `README.md`, `STATUS.md`, `tests/`
3. **ADR-решения:**
   - Локальные → `modules/X/DECISIONS.md`
   - Глобальные → `multiprocess_framework/DECISIONS.md`
4. **Тесты:** из корня — `python Inspector_prototype/scripts/validate.py`, `python Inspector_prototype/scripts/run_framework_tests.py`. Ручной pytest — из `Inspector_prototype/` (иначе `ModuleNotFoundError`)
5. Конфиг на границе — dict, внутри Pydantic v2
6. Логи через `ObservableMixin`, пути из env (`MULTIPROCESS_LOG_DIR` / `INSPECTOR_LOG_DIR`)
7. Индекс ADR: `multiprocess_framework/DECISIONS.md` → ссылки на локальные DECISIONS.md

## MCP: qex (семантический поиск)

**qex** = Qdrant (вектор) + Ollama (`qwen3-embedding:4b`) + BM25 (Tantivy). `search_code` — гибрид dense+sparse.
Холодный старт: `docker start qdrant && ollama serve` (или `/cold-start`).

**qex-first правило:** при рефакторинге, анализе «где используется», смене API/IPC-контракта — **сначала `mcp__qex__search_code`**, потом `Grep`. Подробная логика: `/qex-search`.

## Проектные команды

| Команда | Действие |
|---------|----------|
| `/validate` | `python Inspector_prototype/scripts/validate.py` |
| `/fw-test` | `python Inspector_prototype/scripts/run_framework_tests.py` |
| `/qex-status` | Статус qex-индекса |
| `/qex-reindex` | Переиндексация кодовой базы |
| `/run-proto` | Запуск прототипа |
| `/cold-start` | Холодный старт: Qdrant + Ollama + venv |
