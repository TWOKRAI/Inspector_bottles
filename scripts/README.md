# scripts/ — каталог утилит проекта

Учётный индекс всего, что лежит в `scripts/`. Один источник истины: какие скрипты есть, для чего и как запускать.

Все скрипты запускать **из корня проекта** (`/Users/twokrai/Project_code/Inspector_bottles`), иначе `ModuleNotFoundError`. Зависимости — stdlib Python 3.12+ (см. оговорки у конкретных скриптов).

---

## 1. Точки входа фреймворка

Тонкие обёртки над тем, что должно запускаться часто и из CI.

| Скрипт | Slash-команда | Назначение | Подробности |
|--------|---------------|------------|-------------|
| [`validate.py`](validate.py) | `/validate` | Структурная валидация фреймворка: импорты модулей, наличие `interfaces.py`, ADR-индекс, sync-дрифт. Exit 0/1. | docstring в [`validate.py`](validate.py) |
| [`run_framework_tests.py`](run_framework_tests.py) | `/fw-test` | Pytest по `multiprocess_framework/modules/*/tests/` (editable install). | docstring в [`run_framework_tests.py`](run_framework_tests.py) |

---

## 2. Метрики и аудит (отчётные подпакеты)

Каждый — самостоятельный подпакет: `*.py` + `*.toml` (конфиг) + `README.md` (детальная справка). Без зависимостей сверх stdlib, кроме `code_stats_tokei.py` (нужен бинарь `tokei`).

| Подпакет | Slash | Что показывает | README |
|----------|-------|----------------|--------|
| [`code_stats/`](code_stats/) | `/code-stats`, `/code-stats-tokei` | LOC / файлы / символы по расширениям и директориям. Два движка: stdlib (с docstrings и chars) и `tokei` (точный multi-language). | [README](code_stats/README.md) |
| [`channel_map/`](channel_map/) | `/channel-map` | AST-карта IPC: декларации каналов (`FieldRouting`), отправки (`send_message`), подписки. Поиск разрывов declaration↔send. | [README](channel_map/README.md) |
| [`message_contracts/`](message_contracts/) | `/message-contracts` | AST-дамп классов `SchemaBase` / `Message` / `BaseModel` с полями. Аудит Dict-at-Boundary и диф контрактов между ветками. | [README](message_contracts/README.md) |
| [`test_ratio/`](test_ratio/) | `/test-ratio` | LOC-отношение `tests/` к `code/` на каждый модуль. Дополнение к `/sentrux-gaps` (объёмная метрика). | [README](test_ratio/README.md) |
| [`todo_inventory/`](todo_inventory/) | `/todo-inventory` | Сбор `TODO/FIXME/HACK/XXX/BUG/NOTE` с автором и возрастом через `git blame`. | [README](todo_inventory/README.md) |
| [`clean_cache/`](clean_cache/) | `/clean-cache` | Чистка `__pycache__/`, `.pytest_cache/`, `*.pyc`, `.coverage` и т.п. **Dry-run по умолчанию**, реальное удаление — `--apply`. | [README](clean_cache/README.md) |

Конфиг подпакета лежит рядом с `*.py` (например, [`code_stats/code_stats.toml`](code_stats/code_stats.toml)) — CLI-флаги перекрывают значения из конфига.

---

## 3. Авто-синхронизация ADR-документации

| Подпакет | Запуск | Что делает | README |
|----------|--------|------------|--------|
| [`sync/`](sync/) | `python -m scripts.sync` (write), `python -m scripts.sync --check` (CI), `python -m scripts.sync --list` | Пересборка генерируемых разделов в `multiprocess_framework/DECISIONS.md` и `docs/ADR_REGISTRY.md` (оглавление, модульные решения, «Устарело», коды модулей). Источник истины — заголовки `## ADR-…` в локальных `modules/*/DECISIONS.md`. | [README](sync/README.md) |

Slash-команды у `sync/` нет — это инфраструктурный скрипт, упомянутый в CLAUDE.md (правило 8). Дрифт ловит `/validate`.

---

## 4. Инфраструктура MCP

| Файл | Назначение |
|------|------------|
| [`qex-launcher.py`](qex-launcher.py) | Symlink на [`.claude/mcp/qex-launcher.py`](../.claude/mcp/qex-launcher.py). Лаунчер MCP-сервера qex (Ollama + Tantivy). Сам файл не редактировать — менять исходник в `.claude/mcp/`. |

---

## 5. Депрекейты и эксперименты (не использовать, сохранены ради истории)

Эти файлы оставлены как есть (по решению владельца проекта), но в актуальном пайплайне **не задействованы**. Не запускать без явной необходимости.

| Файл | Статус | Почему устарел |
|------|--------|----------------|
| [`reorganize_decisions.py`](reorganize_decisions.py) | **DEPRECATED** | Одноразовая ранняя пересборка `DECISIONS.md`. Заменён на [`scripts/sync/`](sync/) (см. правило 8 в [`CLAUDE.md`](../CLAUDE.md)). |
| [`check-qex-env.sh`](check-qex-env.sh) | **OUTDATED** | Поднимает Qdrant в Docker и тянет модель `nomic-embed-text-v2-moe`. Текущая архитектура qex: brute-force dense vectors в `~/.qex/`, без Qdrant/Docker; модель — `qwen3-embedding:4b` (Win) / `8b` (macOS). Холодный старт окружения теперь через [`/cold-start`](../.claude/commands/cold-start.md). |
| [`_test_bundle_queue.py`](_test_bundle_queue.py) | **EXPERIMENT** | Разовая разведка паттерна `multiprocessing.Queue` через mid_process на Windows spawn. Не часть тест-сьюта (не лежит в `tests/`, pytest не подбирает). |
| [`_test_queue_isolation.py`](_test_queue_isolation.py) | **EXPERIMENT** | То же — изоляция Queue между 3 уровнями subprocess. |
| [`_test_queue_nested.py`](_test_queue_nested.py) | **EXPERIMENT** | То же — Queue, созданная в mid_process, переданная двум воркерам. |

Префикс `_test_*` намеренно: pytest по умолчанию ловит `test_*`, эти файлы не попадают в коллекцию.

---

## 6. Конвенции для новых скриптов

Если добавляешь новый скрипт — придерживайся стиля проекта:

1. **Подпакет, а не один файл.** Если у скрипта есть конфиг, тесты, или больше одной функции — выноси в `scripts/<name>/` с `<name>.py`, `<name>.toml`, `README.md`, опционально `tests/`.
2. **README обязателен.** Минимум: «Что находит / Запуск / Колонки / Когда полезно / Ограничения» — единый стиль с существующими подпакетами.
3. **Конфиг через TOML.** CLI-флаги перекрывают значения, дефолтный конфиг рядом с `.py`.
4. **Запуск из корня.** Все пути относительные от `Inspector_bottles/`. Не использовать `cd`.
5. **Stdlib first.** Внешние зависимости — только если без них нельзя (`tokei`, `ollama`). Указать в README раздел «Требования».
6. **Slash-команда для частого.** Если скрипт планируется к регулярному вызову — завести `.claude/commands/<slash>.md` с однострочным описанием и шорткатом.
7. **Учёт здесь.** После создания добавить строку в подходящий раздел этого README.

---

## 7. Быстрая навигация по slash-командам

| Slash | Скрипт |
|-------|--------|
| `/validate` | [`validate.py`](validate.py) |
| `/fw-test` | [`run_framework_tests.py`](run_framework_tests.py) |
| `/code-stats` | [`code_stats/code_stats.py`](code_stats/code_stats.py) |
| `/code-stats-tokei` | [`code_stats/code_stats_tokei.py`](code_stats/code_stats_tokei.py) |
| `/channel-map` | [`channel_map/channel_map.py`](channel_map/channel_map.py) |
| `/message-contracts` | [`message_contracts/message_contracts.py`](message_contracts/message_contracts.py) |
| `/test-ratio` | [`test_ratio/test_ratio.py`](test_ratio/test_ratio.py) |
| `/todo-inventory` | [`todo_inventory/todo_inventory.py`](todo_inventory/todo_inventory.py) |
| `/clean-cache` | [`clean_cache/clean_cache.py`](clean_cache/clean_cache.py) |

Полный список slash-команд проекта — в корневом [`CLAUDE.md`](../CLAUDE.md#проектные-команды).
