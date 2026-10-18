# Inspector_bottles

**Фреймворк для приложений с многопроцессной архитектурой** (процессы-воркеры,
разделяемая память, очередь задач) и построенный на нём **прототип системы инспекции
дефектов** через камеру (PySide6 + OpenCV, детекция брака).

Проект — это одновременно переиспользуемый «конструктор» (framework) и эталонное
приложение (prototype), собранное из его модулей.

---

## Что внутри

| Слой | Каталог | Роль |
|------|---------|------|
| **Фреймворк** | [`multiprocess_framework/`](multiprocess_framework/) | 24 модуля-кирпича: оркестрация, IPC, роутинг, состояние, pipeline-исполнители, GUI-база |
| **Прикладные сервисы** | [`Services/`](Services/) | SQL, Hikvision-камера и прочее «мясо» приложения (Phase 4 carve-out) |
| **Плагины** | [`Plugins/`](Plugins/) | Vocabulary переиспользуемых плагинов (reuse между приложениями, см. ADR-120) |
| **Активный прототип** | [`multiprocess_prototype/`](multiprocess_prototype/) | Composition root — единственное место для app-specific изменений. Точка входа: [`run.py`](multiprocess_prototype/run.py) |
| **Планы** | [`plans/`](plans/) | Plan-Driven Development: дорожные карты и задачи (см. [`master-rework-roadmap.md`](plans/master-rework-roadmap.md)) |
| **Документация** | [`docs/`](docs/), [`multiprocess_framework/docs/`](multiprocess_framework/docs/) | Архитектура, ADR, диаграммы, memory |

**Слои импортов** (строго однонаправленно, enforced через `.sentrux/rules.toml`):

```
multiprocess_framework → Services → Plugins → multiprocess_prototype
```

Обратные импорты запрещены. Плагин знает только `PluginContext` и не импортирует
`multiprocess_prototype.*`.

## Архитектура (кратко)

- **Оркестрация:** `SystemLauncher` → `ProcessManagerProcess` → дочерние процессы (`ProcessModule`).
- **IPC:** `Message` / `MessageAdapter` → `RouterManager` → `shared_resources_module` (pickle-safe).
- **Внутри процесса:** `CommandManager`, `worker_module`, `LoggerManager` / `ErrorManager` / `StatsManager`, `RouterManager`.
- **Состояние:** `state_store_module` — реактивное дерево (StateStoreManager + StateProxy + glob-подписки).
- **Pipeline:** `chain_module` — DAG/Chain engine.
- **GUI:** `frontend_module` (PySide6), виджеты сгруппированы по доменам.

Подробнее — в [`CLAUDE.md`](CLAUDE.md) и
[`CONSTRUCTOR_BLUEPRINT.md`](multiprocess_framework/docs/CONSTRUCTOR_BLUEPRINT.md).

## Стек

Python 3.12 · PySide6 6.10 · OpenCV 4.13 · NumPy 2.x · SQLite/PostgreSQL · Pydantic v2 ·
loguru · pytest + pytest-qt. ML-опция (extras `[ml]`): PyTorch + Ultralytics YOLO + ONNX
Runtime. Управление зависимостями — [`uv`](https://docs.astral.sh/uv/).

## Быстрый старт

```bash
# 1. Установить зависимости (виртуальное окружение создаётся автоматически)
uv sync

# 2. Быстрые проверки: ruff + pyright + bandit
make check

# 3. Тесты (pytest с coverage)
make test

# 4. Полный gate: check + test
make gate

# 5. Запустить прототип инспекции
python multiprocess_prototype/run.py
#   или через Makefile (опц. выбор pipeline):
make run PIPELINE=inspection_basic
```

Все targets — `make help`. Единая точка входа для разработки — `Makefile`.

Дополнительно:

- `make test-fw` — тесты фреймворка через [`scripts/run_framework_tests.py`](scripts/run_framework_tests.py).
- `python scripts/validate.py` — валидация структуры (импорты, `interfaces.py`, `README`/`STATUS`, синхронизация ADR).
- GUI-тесты в headless-среде: `QT_QPA_PLATFORM=offscreen`.

## Ключевые документы

| Документ | О чём |
|----------|-------|
| [`CLAUDE.md`](CLAUDE.md) | Проектный контекст, архитектура, правила, карта путей — единый источник правды |
| [`CONSTRUCTOR_BLUEPRINT.md`](multiprocess_framework/docs/CONSTRUCTOR_BLUEPRINT.md) | Blueprint конструктора: 24 модуля фреймворка |
| [`MODULES_RESPONSIBILITY_MAP.md`](multiprocess_framework/docs/MODULES_RESPONSIBILITY_MAP.md) | Карта ответственности и границы модулей |
| [`plans/`](plans/) | Дорожные карты и задачи (Plan-Driven Development) |
| [`docs/claude/COMMIT_GUIDE.md`](docs/claude/COMMIT_GUIDE.md) | Формат commit-сообщений |
| [`docs/notes/2026_shared-resources-pickle-notes.md`](docs/notes/2026_shared-resources-pickle-notes.md) | Исходные заметки прежнего README (pickle-баг) |

## Правила проекта (главное)

1. **Dict at Boundary** — между процессами ходит только `dict` (`to_dict` / `from_dict`);
   Pydantic v2 — внутри процесса. То же для конфига на границе.
2. **Слои импортов** — только сверху вниз (см. выше), enforced через sentrux.
3. **Зависимости через `interfaces.py`** — у каждого модуля есть `README.md`, `STATUS.md`,
   `tests/`.
4. **Commit-сообщения** — Conventional Commits + обязательные trailers `Why:` и `Layer:`.
   Полный гайд — [`docs/claude/COMMIT_GUIDE.md`](docs/claude/COMMIT_GUIDE.md); формат
   валидирует git-hook.

Полный свод правил и карта путей — в [`CLAUDE.md`](CLAUDE.md).


powershell -ExecutionPolicy Bypass -File scripts\run_sim_all.ps1
