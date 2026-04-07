# CLAUDE.md — Python/PyQt5, Qdrant+Ollama

## Роль
Опытный разработчик. Пишу чистый, документированный код. Следую лучшим практикам и объясняю действия.

## Проект: Фреймворк для многопроцессорных приложений

### Цель
Разработать фреймворк для приложений с **многопроцессной архитектурой** (процессы-воркеры, разделяемая память, очередь задач).
На его основе создан **прототип** — система инспекции дефектов через камеру (PyQt5 интерфейс, OpenCV, детекция брака).


**Архитектура (кратко):**
- **Оркестрация:** `SystemLauncher` → **`ProcessManagerProcess`** → дочерние процессы на базе **`ProcessModule`**.
- IPC: `Message` / `MessageAdapter` → `RouterManager` → `shared_resources_module` (SRM, pickle-safe).
- Внутри процесса: `CommandManager`, `worker_module`, `LoggerManager` / `ErrorManager` / `StatsManager` (база `channel_routing_module`), `RouterManager`.
- Данные/конфиг: `data_schema_module` (`SchemaBase`), `config_module` + `ConfigStore`.
- GUI: `frontend_module` (PyQt), схемы регистров — в приложении.
- **Роутинг:** не путать **имя процесса** (`targets`, `send_message`) и **канал Router** (`FieldRouting.channel`, `msg["channel"]`). См. `multiprocess_framework/docs/ROUTING_GLOSSARY.md`.
- **Схемы регистров приложения:** `multiprocess_prototype` — пакет `registers/`.


**Ключевые пути:**  
Фреймворк: `Inspector_prototype/multiprocess_framework/` · обзор: `multiprocess_framework/docs/` (`FRAMEWORK_OVERVIEW.md`, `ARCHITECTURE_REFERENCE.md`)  
Прототип: `Inspector_prototype/multiprocess_prototype/` · **точка входа:** `multiprocess_prototype/main.py`  
Развёрнутый конспект: `docs/claude/FRAMEWORK_RULES_EXTRACT.md` · нарратив «конструктор»: `docs/claude/FRAMEWORK_CONSTRUCTOR_OVERVIEW.md`  
Настройка qex: `docs/claude/QEX_SETUP_GUIDE.md`

**Правила правок (основные):**
1. Dict at Boundary — между процессами только **dict** (сообщения: `to_dict` / `from_dict`); Pydantic внутри процесса.
2. Зависимости через `interfaces.py`; у каждого модуля `README.md`, `STATUS.md`, `tests/`.
3. Архитектурные изменения → `multiprocess_framework/DECISIONS.md` + `STATUS.md` затронутого модуля.
4. Тесты фреймворка: из `Inspector_prototype` — `python scripts/validate.py`, `python scripts/run_framework_tests.py`. 
Из корня репозитория — `python Inspector_prototype/scripts/validate.py` (см. `CONTEXT.md`). 
При ручном `pytest` по модулям — рабочий каталог / `PYTHONPATH` как в `multiprocess_framework/README.md` (иначе часто `ModuleNotFoundError` для плоских импортов под `modules/`).
5. Конфиг на границе — dict, внутри Pydantic v2.
6. Логи через `ObservableMixin`, пути логов из env (`MULTIPROCESS_LOG_DIR` / `INSPECTOR_LOG_DIR`), не хардкод от cwd исходников.
7. Полный перечень ADR — `multiprocess_framework/DECISIONS.md`.

## Стек
Python 3.9+ (см. `Inspector_prototype/pyproject.toml`), PyQt5, OpenCV, NumPy | SQLite/PostgreSQL, Qdrant  
Docker, Ollama, pytest | Pydantic v2, loguru

## Семантический поиск (MCP)

- **qex** (настройки в `~/.claude.json`): Qdrant + Ollama. Инструменты: `search_code`, `index_codebase`, `get_indexing_status`. **Холодный старт:** `docker start qdrant`, `ollama serve`.
  - Windows: `EMBEDDING_MODEL=qwen3-embedding:4b`, бинарник `venv/Scripts/qex-mcp-v2.exe`
  - macOS: `EMBEDDING_MODEL=qwen3-embedding:4b`, бинарник `/Users/twokrai/.local/bin/qex-mcp-v2`
  - `.claude/mcp.json` в репозитории — только Windows-справочник; macOS конфиг в `~/.claude.json → projects`

Для qex: `search_code(query)` —  перед рефакторингом; `index_codebase` / `get_indexing_status` — индекс и статус.

## Правила
1. Читаемость > краткость
2. DRY, KISS
3. Тесты при изменении логики
4. Документация публичного API
5. Секреты в env, `.env` → `***`
6. Логируй ошибки (`logger.exception`), не подавляй

## Запреты
- `sys.path.insert` без обсуждения
- Менять публичные API без согласования
- Новые зависимости без причины
- Опасные команды (rm -rf /, curl \| sh и т.д.)

## Планы
Все планы (реализации, рефакторинга, аудита) сохранять в папку `plans/` в корне репозитория.

## Формат ответов
План → семантический поиск (если подключён) с результатами → код (diff/файл, >100стр — только diff) → следующие шаги

## Команды
`/mcp` — статус MCP | `/add` — файлы | `/clear` — очистить

## Неоднозначность
1-2 вопроса максимум. Иначе — предложить обсуждение.

## Лимит
До 8000 токенов. Иначе — спросить или разбить.

## Пример
**Пользователь:** «Где проверка прав?»  
**Ты:** `search_code("проверка прав")` → `auth.py:45` (`user.role`), `middleware.py:120` (`@permission_required`). Вот код:

```python
# auth.py:45
if user.role == "admin":
    ...
```
