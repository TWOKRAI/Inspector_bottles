# План улучшения фреймворка — 2026-05-02

**Источник:** [`ASSESSMENT_2026_05.md`](ASSESSMENT_2026_05.md), глубокий semantic-анализ через qex (1879 файлов, 17516 чанков).
**Целевая дата релиза 2.1:** ~3-4 недели.
**Стратегия:** **сначала Tier-1 (3 дня)**, потом — прототип. Tier-2 параллельно с прототипом.

> **Критерий «успех плана»**: пройдя Tier-1 + Tier-2, мы получаем фреймворк, который можно открыть внешней команде без оговорок. Tier-3 — perfectionism, делается по мере роста.

---

## Tier 1 — БЛОКЕРЫ (3 дня, до прототипа)

Без этого продолжать новые сборки **не имеет смысла** — каждая фича будет нести долг дальше.

### 1.1 Синхронизация документации: 19 → 21 модуль

**Проблема.** `MODULE_CONTRACTS.md`, `DIAGRAMS.md`, `STRUCTURE.md`, `__init__.py` (комментарий «49 экспортов») говорят о 19 модулях. По факту — 21 (`state_store_module`, `chain_module`).

**Файлы:**
- [x] `docs/MODULE_CONTRACTS.md` — заголовок и сводная таблица *(уже сделано 2026-05-02)*.
- [x] `docs/DIAGRAMS.md` — пункты 1, 5: добавлены `state_store_module` (L5) и `chain_module` (L6) в layer cake и dependency graph; «19 packages» → «21 packages».
- [x] `STRUCTURE.md` — «всего пакетов под `modules/`: 19» → 21; в дерево добавлены `chain_module/` и `state_store_module/`.
- [x] `MODULES_STATUS.md` — единая цифра 21; убрано упоминание «2 known-failing» (тесты теперь зелёные, см. п.1.4).
- [x] `README.md` — «19 готовых модулей-«деталей»» → 21; «49 экспортов» → 60; «1 877 passed / 30 skipped / 2 known-failing» → актуальные цифры.
- [x] `SPEC.md` — §3 «19 модулей» → 21 (с расширением слоёв L5/L6 под state_store/chain); граф зависимостей §4 дополнен; §7 «49 символов» → 60 (плюс новые секции State Store / Chain Engine / Storage / UI); §11 актуальные цифры тестов.
- [x] `DOCUMENTATION_INDEX.md`, `docs/README.md` — упоминания «19» → 21.

**Acceptance:**
```bash
grep -rn "19 модул\|19 packages\|19 пакет" multiprocess_framework/ --include="*.md"
```
**Ожидание:** пусто или только в исторических ADR (`DECISIONS.md`).

**Срок:** 0.5 дня.

### 1.2 Восстановить целостность корневого фасада

**Проблема.** `__init__.py` экспортирует только 17 модулей. `state_store`, `chain`, `sql`, `frontend` доступны только по полному пути — это нарушение R-1 («единый канал импортов»). Документация заявляет «49 экспортов», по факту — меньше.

**Действия:**
- [x] Добавлены экспорты `state_store_module`, `chain_module`, `sql_module`, `frontend_module` (опциональный — try/except) в корневой `__init__.py`.
- [x] `__all__` обновлён — добавлены 11 новых публичных имён (StateStoreManager/StateProxy/GuiStateProxy/IStateRouter, ChainRunnable/DagRunnable/ParallelChainRunnable/ChainContext/ChainResult, SQLManager, FrontendManager).
- [x] Таблица «Публичный API» в `SPEC.md` §7 — добавлены секции State Store, Chain Engine, Storage, UI; ProcessStatusMonitor добавлен в Orchestration.
- [x] Комментарии «49 экспортов» обновлены: `README.md` (60), `SPEC.md` §7 (60), `STRUCTURE.md` (60).

**Acceptance:**
```python
import multiprocess_framework as mf
assert mf.StateStoreManager
assert mf.ChainRunnable
assert mf.SQLManager
assert len(mf.__all__) >= 55  # ориентир
```

**Срок:** 0.5 дня.

### 1.3 Удалить алиас `ProcessStatus = ProcessStatusMonitor`

**Проблема.** В `process_manager_module/core/process_status.py:111` живёт `ProcessStatus = ProcessStatusMonitor` — backward-compat от ADR-117. Это **семантический конфликт**: `ProcessStatus` — где-то Enum, где-то класс мониторинга.

**Действия:**
- [x] Поиск показал единственного потребителя — `process_manager_module/core/__init__.py` и тест `tests/test_process_status.py`. Прикладного кода (прототипа), импортирующего `ProcessStatus` из process_manager_module как класс мониторинга, нет.
- [x] Тест `tests/test_process_status.py` мигрирован на `ProcessStatusMonitor` (импорт + имя класса `TestProcessStatusMonitor`).
- [x] Алиас `ProcessStatus = ProcessStatusMonitor` удалён в `process_manager_module/core/process_status.py`; обновлены `core/__init__.py` и `process_manager_module/__init__.py` (`__all__` без локального `ProcessStatus`).
- [x] ADR-117 в `multiprocess_framework/DECISIONS.md` дополнен записью «Дополнение 2026-05-02: алиас удалён».

**Acceptance:** прогон тестов остаётся зелёным; `grep -rn "ProcessStatus = ProcessStatusMonitor"` — пусто.

**Срок:** 0.5 дня.

### 1.4 Починить 2 failing-теста

**Проблема.** Из `PROBLEMS.md`:
1. `test_process_manager_process.py::test_init_creates_components` — `pmp._create_components()` без полного `initialize()`, `config_handler` ещё не выставлен.
2. `test_managers_normalize.py::test_console_process_config_build_and_process_helper` — изменился контракт `proc_dict["class"]`.

**Решение (вариант минимум):**
- [x] Оба теста уже зелёные на момент начала Tier-1 (2026-05-02): `test_init_creates_components` патчит `pmp.config_handler = None`, `test_console_process_config_build_and_process_helper` принимает `isinstance(proc_dict["class"], str)` без проверки на «не пусто».
- [x] `PROBLEMS.md` и `MODULES_STATUS.md` обновлены — упоминания «2 known-failing» убраны, актуальный счёт «2 465 passed / 29 skipped / 0 failed» зафиксирован.

**Acceptance:**
```bash
python scripts/run_framework_tests.py
```
**Ожидание:** **0 failed**, 30 skipped, остальное — passed.

**Срок:** 1-2 часа.

### 1.5 Обновить корневой CLAUDE.md под 21 модуль

**Проблема.** В `/Users/twokrai/Project_code/Inspector_bottles/CLAUDE.md` стек упоминает «19 готовых модулей-«деталей»» (через ссылку на README) и не упоминает state_store/chain.

**Действия:**
- [x] В разделе «Архитектура» добавлены пункты про `state_store_module` и `chain_module`; добавлена строка «Всего модулей в `multiprocess_framework/modules/`: 21».
- [x] Ссылка на устаревшие `FRAMEWORK_OVERVIEW.md` / `ARCHITECTURE_REFERENCE.md` заменена на актуальные `MODULES_OVERVIEW.md` / `MODULE_CONTRACTS.md` / `DIAGRAMS.md`; в таблицу «Ключевые пути» добавлена ссылка на `multiprocess_framework/docs/CONSTRUCTOR_BLUEPRINT.md`.

**Срок:** 30 минут.

---

## Tier 2 — АРХИТЕКТУРНЫЕ ДОЛГИ (1-2 недели, параллельно с прототипом)

Делается **не блокируя** новые сборки. Каждый пункт — самостоятельный PR.

### 2.1 Унификация comm-API на ProcessModule (`send_message` → `send`)

**Проблема.** Два API делают одно (ADR-163): `send_message(target, msg) -> bool`, `send(msg) -> dict`. Лишний выбор.

**Стратегия:**
- [ ] Оставить только `send(msg) -> dict`. Возвращает `{"status": "success"|"error", ...}`.
- [ ] Пометить `send_message`, `broadcast_message`, `receive_message` (всё это алиасы в `ProcessCommunication`) как `@deprecated` с `DeprecationWarning`.
- [ ] Через 2 версии (2.3) — удалить.
- [ ] Мигрировать прототип на `send`.

**Срок:** 2 дня + 3-5 дней миграция прототипа.

### 2.2 Унификация двойного dispatch (`CommandManager` ↔ `RouterManager.message_dispatcher`)

**Проблема.** `ProcessLifecycle._register_commands_with_router` копирует все команды из `command_manager.dispatcher` в `router_manager.message_dispatcher`. Два индекса для одной таблицы — опасно при рассогласовании.

**Решение (вариант A, рекомендуется):** оставить только один dispatcher. `RouterManager.message_dispatcher` принимает все incoming-сообщения; `CommandManager` становится **тонкой оболочкой**, которая регистрирует свои handlers сразу в `router.message_dispatcher` (через ссылку).

**Решение (вариант B):** оставить два, но добавить контракт «синхронизатор» — `command_manager.attach_to_router(router)` единственный путь регистрации.

**Срок:** 2-3 дня + ADR с обоснованием выбора A или B.

### 2.3 Декомпозиция `data_schema_module` (16K LOC)

**Проблема.** Самый большой модуль. Внутри: `core/`, `tools/`, `extensions/`, `builders/`, `validators/`, `ui/`. Растёт быстрее всех.

**Стратегия (вариант мягкий):** оставить пакет, но **формализовать sub-packages** с явными `__init__.py` и `interfaces.py`:
- [ ] `data_schema_module/core/` — `SchemaBase`, `FieldMeta`, `FieldRouting`, `SchemaMixin` (фундамент).
- [ ] `data_schema_module/runtime/` — `SchemaRegistry`, `RegistersContainer`, `DataConverter`.
- [ ] `data_schema_module/tools/` — генератор UI-метаданных, `schema_documentation_generator`.
- [ ] `data_schema_module/extensions/` — `register_schema` декоратор, кастомные validators.
- [ ] Каждый sub-package имеет `interfaces.py` и `README.md`.

**Срок:** 1 неделя.

### 2.4 ADR с разграничением `registers_module` ↔ `state_store_module`

**Проблема.** Оба дают pub/sub изменений; граница только в документации, не в коде.

**Действия:**
- [ ] Написать ADR-RM-002 (или ADR-SS-011): «Когда применять регистры, когда — state store».
- [ ] Чётко разграничить:
  - `registers_module` — **именованные регистры приложения** (Pydantic-инстансы, типизированные поля, валидация по `FieldMeta`, fan-out по `FieldRouting`). Применять для конфигурации устройств, UI-настроек.
  - `state_store_module` — **произвольное иерархическое дерево** (dict-tree, glob-patterns, delta-only IPC). Применять для real-time состояния, метрик, телеметрии, динамических топологий.
- [ ] Добавить раздел в `CONSTRUCTOR_BLUEPRINT.md` §4 «Семь паттернов» — добавить восьмой: «Регистр vs State Store».

**Срок:** 0.5 дня.

### 2.5 Plugin-механизм для `ProcessManagerProcess`

**Проблема.** Уже 3 хука (`_setup_console_manager`, `_setup_topology_manager`, `_setup_state_store`); каждый новый = править наследие. Превращается в template method для всего.

**Решение:**
- [ ] Ввести `IProcessManagerPlugin` (Protocol) с методами `setup(pmp)`, `teardown(pmp)`, `priority: int`.
- [ ] `ProcessManagerProcess.add_plugin(plugin)` — реестр плагинов.
- [ ] Console / Topology / StateStore переписать как плагины.
- [ ] Прикладной код добавляет свои плагины через `launcher.add_orchestrator_plugin(...)`.

**Срок:** 3-4 дня. Требует ADR-PM-007.

### 2.6 CI matrix (GitHub Actions)

**Действия:**
- [ ] `.github/workflows/test.yml` — matrix: `os = [ubuntu-latest, windows-latest, macos-latest]`, `python = [3.12, 3.13]`.
- [ ] Прогон `python scripts/run_framework_tests.py` + `python scripts/validate.py`.
- [ ] Skip-маркер для macOS-`SharedMemory`-тестов уже есть — на CI должно работать.
- [ ] Бейдж в README.md.

**Срок:** 1 день настройки + 1-2 дня починки flaky на других платформах.

### 2.7 Performance baseline

**Действия:**
- [ ] `tests/performance/` с pytest-benchmark.
- [ ] Сценарии:
  - Throughput RouterManager: 1k/10k/100k send_async/sec.
  - Latency end-to-end: msg.command(A → B) p50/p95/p99.
  - LoggerManager BatchBuffer: 10k logs/sec, измерить flush latency.
  - StateStore: 100 подписчиков на `cameras.*.config.*`, измерить delta dispatch latency.
  - SRM: 1000 register_process за раз, измерить spawn-latency.
- [ ] Сохранить baseline в `tests/performance/baseline.json`. Падение >20% — fail в CI.

**Срок:** 3 дня.

---

## Tier 3 — ПОЛИРОВКА (по мере роста, ≥1 месяц)

Не блокирует ничего, но повышает зрелость продукта.

### 3.1 Sphinx или mkdocs

- [ ] Автогенерация API-доки из docstrings.
- [ ] Интеграция с GitHub Pages.
- **Срок:** 2-3 дня.

### 3.2 CHANGELOG.md

- [ ] Корневой `CHANGELOG.md` с привязкой версий к ADR.
- [ ] Bump `__version__` до 2.1.0 после Tier-1.
- **Срок:** 0.5 дня + дисциплина в каждом релизе.

### 3.3 Линтер инвариантов

- [ ] Pre-commit hook с проверкой R-1 (каноничные импорты), R-3 (Dict at Boundary), R-9 (нет `print`), R-11 (нет `sys.exit`).
- [ ] Запускать в CI.
- **Срок:** 2 дня.

### 3.4 Decompose `frontend_module` в отдельный пакет

- [ ] Вынести в `frontend_framework/` как опциональный pip-package с зависимостью на `multiprocess_framework`.
- [ ] Зафиксировать ADR-FE-001.
- **Срок:** 1-2 недели.

### 3.5 OpenTelemetry-adapter в `RouterManager`

- [ ] Distributed tracing для cross-process сообщений.
- [ ] Полезно при росте на несколько хостов.
- **Срок:** 3-5 дней.

### 3.6 Prometheus-adapter в `StatsManager`

- [ ] Native exporter `/metrics` endpoint.
- [ ] Готовые dashboards для Grafana.
- **Срок:** 2-3 дня.

### 3.7 Cookiecutter-шаблон приложения

- [ ] `template-app/` с заглушками: SystemLauncher + 2 процесса + 1 регистр + 1 виджет.
- [ ] `cookiecutter` или `copier`-совместимый.
- **Срок:** 2 дня.

### 3.8 Deployment guide

- [ ] `docs/DEPLOYMENT.md`: Docker / systemd / Windows Service / macOS launchd.
- [ ] Примеры `Dockerfile` и `compose.yml`.
- **Срок:** 2-3 дня.

---

## Расписание (предлагаемое)

```
Неделя 0 (текущая) — 2-3 дня
├── Tier 1.1  Sync docs                         (0.5 д)
├── Tier 1.2  Root facade restoration           (0.5 д)
├── Tier 1.3  Remove ProcessStatus alias        (0.5 д)
├── Tier 1.4  Fix 2 failing tests               (0.25 д)
└── Tier 1.5  Update CLAUDE.md                  (0.25 д)
    Итого:                                      ~2-3 дня
    Acceptance: зелёный CI + ноль 19→21 расхождений + чистый __init__.py

Неделя 1-2 — параллельно с прототипом
├── Tier 2.1  Unify comm API                    (2 д + миграция)
├── Tier 2.4  ADR registers vs state_store      (0.5 д)
├── Tier 2.6  CI matrix                         (1-3 д)
└── Tier 2.7  Performance baseline              (3 д)

Неделя 3-4 — параллельно с прототипом
├── Tier 2.2  Unify double dispatch             (2-3 д)
├── Tier 2.3  Decompose data_schema_module      (1 неделя)
└── Tier 2.5  Plugin mechanism for PMP          (3-4 д)

Месяц 2+ — Tier 3 по мере необходимости
```

---

## Acceptance критерии релиза 2.1

Релиз можно объявлять, когда выполнены **все** условия:

- [ ] Tier-1 (1.1–1.5) полностью закрыт.
- [ ] Tier-2.1 (унификация `send`) выполнено и прототип мигрирован.
- [ ] Tier-2.4 (ADR registers vs state_store) написан.
- [ ] Tier-2.6 (CI на 3 ОС) — зелёный на всех платформах.
- [ ] Tier-2.7 (performance baseline) — зафиксирован.
- [ ] `__version__` поднят до `2.1.0`.
- [ ] `CHANGELOG.md` создан, секция 2.1 описана.
- [ ] `python scripts/run_framework_tests.py` — 0 failed.

После этого фреймворк можно показывать сторонним командам как production-ready.

---

## Anti-targets (что НЕ делаем в этом плане)

Эти пункты — соблазны, которые могут показаться полезными, но **не приоритет**:

| Чего не делаем | Почему |
|----------------|--------|
| Переписывать `RouterManager` под asyncio | Текущий thread-pipeline корректен и тестируется. Переписывание = +1 месяц без бизнес-ценности. |
| Унифицировать `ChannelRoutingManager` через Composition вместо Inheritance | Inheritance работает, тесты есть. Перепиливание под Strategy ради «правильности» — рефакторинг ради рефакторинга. |
| Вводить новый top-level пакет `multiprocess_framework_legacy` для backward-compat | Делаем clean break, как и было прописано в I-11 «backward compat удаляется без жалости». |
| Включать SchemaBase из Pydantic 1 для совместимости | Pydantic v2 уже в стеке. Не вводим dual-mode. |
| Заменять `loguru` на `structlog` | Никаких объективных преимуществ; работает — не трогаем. |
| Добавлять ORM поверх `sql_module` | Уже есть `QuerySet` + `Repository` + `UoW`. Достаточно. SQLAlchemy — отдельный pip-extra при реальной нужде. |

---

## Метрики для трекинга

Перед стартом и после каждого Tier измеряем:

| Метрика | Сейчас | Целевое (после Tier-1) | Целевое (релиз 2.1) |
|---------|--------|------------------------|----------------------|
| Failing tests | 2 | 0 | 0 |
| Корневых экспортов в `__all__` | ~46 | ~55 | ~55 |
| Документация: упоминаний «19 модулей» | >5 | 0 | 0 |
| ADR-конфликтов (алиас ProcessStatus) | 1 | 0 | 0 |
| CI matrix coverage | 0 платформ | 1 (mac) | 3 (linux/win/mac) |
| Performance baseline | нет | нет | есть |
| LOC `data_schema_module` | 16 168 | 16 168 | 4-5 sub-packages по 3-5K |
| Documentation drift score (вручную) | средний | низкий | низкий |

---

## Итог

Tier-1 за 2-3 дня снимает 80% документационного и фасадного долга. Это **минимально необходимая работа** перед сборкой следующих фич прототипа. Остальное (Tier-2/3) — растягивается параллельно.

**Главный риск, если игнорировать Tier-1:** новые фичи продолжат класться поверх несинхронизированной документации. Через 1-2 недели рассогласование станет необратимым (без выделенного спринта на cleanup).

**Главное преимущество, если пройти Tier-1:** дальнейшая работа над прототипом будет идти на «чистой» базе — каждое изменение сразу проверяется на актуальность в одном месте, без поиска по 4-5 местам.
