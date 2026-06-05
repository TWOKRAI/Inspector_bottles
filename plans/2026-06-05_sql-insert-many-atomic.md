# Plan: атомарный и батчевый `insert_many` в Services/sql

- **Slug:** sql-insert-many-atomic
- **Дата:** 2026-06-05
- **Статус:** DRAFT
- **Ветка:** `fix/sql-insert-many-atomic` (создать при старте работы)
- **Родитель:** [`2026-06-04_telemetry-db-sink.md`](2026-06-04_telemetry-db-sink.md) — дефект вскрыт при миграции DatabasePlugin (Phase 2, ревью Opus)
- **Связанные memory:** `project_telemetry_db_sink`, `feedback_fix_framework_forward`

## Проблема (что не так сейчас)

`GenericRepository.insert_many` (`Services/sql/core/base_repository.py:80-94`) выполняет **per-row**:
для каждой строки — отдельный `self._adapter.execute(sql, params)`, а `SyncEngineAdapter.execute`
(`Services/sql/adapters/sync_adapter.py:53-60`) на КАЖДЫЙ вызов открывает новое соединение
(`engine.connect()`) и делает свой `commit()`.

Последствия (подтверждено на миграции DatabasePlugin, коммит `0da4d582`):
1. **Нет атомарности batch.** Сбой на строке k оставляет строки 0..k-1 закоммиченными. Из исключения
   не узнать k → безопасный «fallback переинсертом всего пакета» невозможен (даёт дубли). Пришлось
   писать построчно в `DatabasePlugin._do_flush` и `telemetry_sink` лишился атомарности снимка.
2. **Производительность.** N коммитов вместо одного. Для SQLite каждый commit ≈ fsync → под нагрузкой
   (тысячи строк/с) запись в разы-десятки раз медленнее, чем `executemany` + один commit.
3. **«Красивый» API субтильно неверен.** `insert_many` выглядит как batch, но им не является; нет
   публичного способа атомарной пакетной вставки (только raw SQL через `SQLManager.execute`).

Это делает миграцию raw `sqlite3` → `SQLManager` локально нейтрально-хуже (исходник использовал
`executemany`+один commit). Цель плана — сделать `insert_many` строго лучше raw-варианта.

## Цель

`insert_many(entities)` — **одна транзакция, один commit, executemany-семантика**: либо все строки
записаны, либо ни одной (rollback при сбое). Сигнатура и возвращаемое значение (`List[T]`) не меняются.
После этого потребители возвращаются к атомарному batch + безопасному fallback.

## Решение (design)

SQLAlchemy `conn.execute(text(sql), list_of_param_dicts)` = executemany (один statement, повтор по строкам;
лимит переменных SQLite не задевается — на строку идёт ровно `ncols` параметров). `adapter.connection()`
(`sync_adapter.py:72-82`) уже даёт ровно «commit на выходе / rollback при исключении».

Ключевые решения:
- **(а)** Добавить в `ISyncEngineAdapter` + `SyncEngineAdapter` метод `execute_many(sql, params_list) -> int`
  (один `with self.connection() as conn: conn.execute(text(sql), params_list)`). НЕ ломать существующий
  `execute` (используется в `SQLManager.execute`, DDL, командах).
- **(б)** `GenericRepository.insert_many` строит ОДИН INSERT с именованными плейсхолдерами `:col` и
  вызывает `adapter.execute_many(sql, [row_dict, ...])` — один commit, атомарно. Возврат — как сейчас
  (`model_validate(row)` по входным строкам).
- **(в)** Порядок колонок берётся из первой строки; все строки обязаны иметь одинаковый набор ключей
  (как сейчас). Edge: пустой список → `[]` (без обращения к БД).
- **(г)** `autoincrement id`: строки с `id=None` уходят как NULL → SQLite присвоит PK (как сейчас; проверено
  live-proof'ом 318/258 строк).
- **(д)** Async — ВНЕ scope: async `insert_many` в репозитории нет, async-потребителей нет. Если появятся —
  отдельная задача (`AsyncEngineAdapter.execute_many`).

## Откат построчных обходов у потребителей (после фикса)

- `DatabasePlugin._do_flush` — вернуть атомарный batch + fallback one-by-one (теперь безопасный: при сбое
  batch ничего не закоммичено, fallback вставляет каждую строку ровно один раз). Контракт/счётчики прежние.
- `telemetry_sink._sample_once` — `insert_many(rows)` остаётся, получает атомарность снимка бесплатно;
  guard в `_sample_loop` оставить (защита от прочих ошибок).

## Порядок выполнения

### Task 1.1 — `execute_many` в sync-адаптере
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Добавить атомарный батчевый executemany в синхронный адаптер, не трогая `execute`.
**Files:**
- `Services/sql/interfaces.py` — в `ISyncEngineAdapter` добавить `execute_many(sql, params_list) -> int`
- `Services/sql/adapters/sync_adapter.py` — реализация через `self.connection()` (один commit/rollback)
**Steps:**
1. `def execute_many(self, sql, params_list): with self.connection() as conn: r = conn.execute(text(sql), params_list); return r.rowcount`
2. Пустой `params_list` → return 0 без обращения к БД.
**Acceptance criteria:**
- [ ] `execute_many` атомарен: при сбое одной строки — rollback, 0 строк в БД
- [ ] один commit на весь пакет (проверить через mock/счётчик commit)
- [ ] `execute` не изменён; существующие sql-тесты зелёные
**Module contract:** impl-only

### Task 1.2 — `GenericRepository.insert_many` через `execute_many`
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Переписать `insert_many` на один INSERT + `execute_many` (атомарно, один commit).
**Files:** `Services/sql/core/base_repository.py`
**Steps:**
1. Построить `INSERT INTO "t" (cols) VALUES (:c1,:c2,...)` один раз.
2. `rows = [mapper.entity_to_row(e) for e in entities]`; `adapter.execute_many(sql, rows)`.
3. Вернуть `[schema.model_validate(r) for r in rows]`. Пустой вход → `[]`.
**Acceptance criteria:**
- [ ] Вставка N строк = 1 транзакция/commit; сбой → 0 строк (атомарно)
- [ ] autoincrement id работает (id=None → присвоен СУБД)
- [ ] возврат и сигнатура не изменились; `Services/sql/tests` зелёные
**Module contract:** impl-only

### Task 1.3 — тесты Services/sql
**Level:** Middle (Sonnet)
**Assignee:** tester
**Files:** `Services/sql/tests/`
**Acceptance criteria:**
- [ ] тест атомарности: сбой в середине пакета → таблица пуста (rollback)
- [ ] тест «один commit» (mock соединения)
- [ ] тест executemany на ≥1000 строк (нет ошибки лимита переменных SQLite)
- [ ] postgres/sqlite — параметризация диалекта, если есть фикстуры

### Task 2.1 — откат построчного обхода в DatabasePlugin
**Level:** Middle (Sonnet)
**Assignee:** developer
**Files:** `Plugins/io/database/plugin.py`, `tests/`
**Steps:**
1. `_do_flush`: вернуть `repo.insert_many(rows)` (быстрый атомарный путь) + fallback one-by-one ТОЛЬКО при
   исключении (теперь безопасно — batch атомарен, дублей нет). Обновить docstring (убрать про per-row).
2. Тесты: атомарность batch (сбой → 0 строк, потом fallback), счётчики `_total_written/_total_errors`.
**Acceptance criteria:**
- [ ] batch-путь атомарен; fallback не плодит дубли; счётчики корректны
- [ ] 18+ тестов зелёные

### Task 3.1 — приёмка
**Level:** Middle+ (Sonnet)
**Assignee:** teamlead
**Acceptance criteria:**
- [ ] `python scripts/run_framework_tests.py` без регрессий (database, telemetry_sink, modbus, sql)
- [ ] headless live-proof `inspection_full` (запись `detections`) и `telemetry_sink.yaml` — без ошибок
- [ ] sentrux `check_rules` — без новых нарушений; quality не просел

## Риски

- **Совместимость возврата** — `insert_many` возвращает `List[T]` по входным строкам, без re-SELECT; id
  присвоенный СУБД в возврате может быть None (как и сейчас) — задокументировать, не регресс.
- **executemany rowcount** — у SQLite/драйвера `rowcount` для executemany может быть -1; не полагаться на
  него для подсчёта (возвращать `len(rows)`).
- **Async-путь** — намеренно вне scope; зафиксировать как известный gap.
- **Диалекты** — кавычки идентификаторов уже учтены в текущем коде; проверить на postgres-фикстуре, если есть.

## Out of scope

- Async `insert_many` (нет потребителей).
- `update_many` (отдельный аналогичный кандидат — упомянуть, не делать).
- Переход telemetry_sink на batch-команды/UoW (его `insert_many` и так станет атомарным).
