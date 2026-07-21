# Plan: стек хранения — embedded-first (SQLite + плоские файлы)

- **Slug:** `storage-stack-embedded-first`
- **Дата:** 2026-07-21
- **Статус:** DRAFT
- **Ветка:** `feat/storage-stack-embedded-first` (создать при старте работы)
- **Связанные планы:** [`2026-06-05_sql-insert-many-atomic.md`](2026-06-05_sql-insert-many-atomic.md) (DRAFT, не выполнен — вливается сюда как Этап 1)
- **Связанные аудиты:** [`docs/audits/2026-06-18_command-undo-system.md`](../docs/audits/2026-06-18_command-undo-system.md) §4
- **Связанная memory:** `project_telemetry_db_sink`, `feedback_framework_first`, `feedback_fix_framework_forward`

---

## Вердикт (не пересматривается этим планом)

Два независимых раунда архитектурного анализа по коду → **остаёмся на embedded: SQLite через существующий
`Services/sql` + плоские файлы. Ноль новых зависимостей.**

Отклонённые кандидаты и почему:

| Кандидат | Отклонён, потому что |
|----------|---------------------|
| **PostgreSQL** | Опцион по триггеру, не решение сегодня. Диалектная граница (`adapters/postgresql.py`, `ddl_builder`) **уже существует** — её надо сохранять тестом, а не строить заново |
| **InfluxDB 3 / GreptimeDB** | Сервер + LSM-движок ради потока в ~2 строки/сек. Write-amplification убивает SD-карту Raspberry Pi |
| **Qdrant** | RAM-конфликт с GPU-инференсом на Jetson; векторных фич пока нет вообще |
| **DuckDB** | Лишний слой поверх того, что SQLite уже делает на наших объёмах |

Объёмы, на которых считалось: телеметрия ~30-40 МБ/сутки; результаты инспекции 0.9-3.5 ГБ/сутки при 20 FPS;
**картинки на 2-3 порядка тяжелее строк** — они главный потребитель диска при ЛЮБОМ движке. Смена движка БД
эту задачу не решает; решает её файловая политика (Этап 3) и ретенция (Этап 1).

## Что делает этот план

Приводит в порядок то, что уже есть (Этап 1), дёшево консервирует опцион Postgres, чтобы граница не сгнила
(Этап 2), добавляет снапшоты/кэш отрисовки на готовых кирпичах (Этап 3) и доводит Modbus-slave до
постоянной SCADA-ноды (Этап 4).

---

## Порядок выполнения и параллелизм

```
Этап 1 (гигиена) ──┬── Этап 2 (опцион Postgres)   ← после 1.1 (JSON-колонка влияет на схемы)
                   └── Этап 3 (снапшоты)          ← нужен атомарный insert_many (1.2)
Этап 4 (SCADA) ─────── независим, можно параллельно с любым этапом
```

- **Этап 1 самоценен и исполним отдельно** — это часы работы, дают эффект без остальных этапов.
- **Этап 4 ни от чего не зависит** — можно отдать второму исполнителю сразу.
- Внутри Этапа 1: 1.1, 1.3, 1.4 независимы друг от друга; 1.2 — отдельная ветка работы (см. родительский план).

---

## Этап 1 — гигиена существующего (ПРИОРИТЕТ, делать первым)

### Task 1.1 — `data` в JSON вместо Python-repr

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Колонка `detections.data` содержит валидный JSON, а не строку `str(dict)`.
**Context:** `Plugins/io/database/plugin.py:125` пишет `"data": str(data)` — это Python-repr
(`{'key': 'value'}` с одинарными кавычками, `True`/`None` вместо `true`/`null`). Такая строка не парсится
ни `json.loads`, ни SQL-функцией `json_extract`. Существующие ~318 строк невалидны — **объявляем их legacy,
конвертер repr→JSON не пишем** (дороже, чем ценность исторических данных demo-прогонов).

**Files:**
- `Plugins/io/database/plugin.py` — `_add_to_buffer`, строка 125
- `Plugins/io/database/schemas.py` — докстринг колонки `data`
- `Plugins/io/database/tests/` — тест

**Steps:**
1. `_add_to_buffer`: `"data": str(data)` → `json.dumps(data, ensure_ascii=False, default=str)`.
   `default=str` обязателен — в `data` попадают numpy-скаляры и `Path`, которые `json` не сериализует.
2. В докстринге `DetectionSchema.data` зафиксировать: «JSON-строка; строки, записанные до
   `<hash коммита>`, — Python-repr (legacy, не парсятся)».
3. Тест: `json.loads(record["data"])` возвращает dict; отдельный кейс с numpy-скаляром и `Path` внутри.

**Acceptance criteria:**
- [ ] `json.loads` успешно парсит записанное значение `data`
- [ ] несериализуемые значения (numpy, `Path`) не роняют flush — уходят через `default=str`
- [ ] кириллица в `data` не экранируется в `\uXXXX` (`ensure_ascii=False`)
- [ ] тесты `Plugins/io/database/tests/` зелёные

**Out of scope:** конвертер старых repr-строк; смена типа колонки на нативный JSON (SQLite всё равно TEXT).
**Edge cases:** `data` содержит незакрытый цикл ссылок → `json.dumps` бросит `ValueError`; это ловит
существующий `try/except` в `_do_flush` (проверить, что ловит именно там, а не в `_add_to_buffer` без обработки).
**Dependencies:** нет.
**Module contract:** impl-only

---

### Task 1.2 — атомарный `insert_many` (выполнить существующий план)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Выполнить [`plans/2026-06-05_sql-insert-many-atomic.md`](2026-06-05_sql-insert-many-atomic.md)
целиком — `insert_many` = одна транзакция, один commit, executemany-семантика.
**Context:** **Задача НЕ дублируется здесь.** Проверено по коду: `Services/sql/core/base_repository.py:80-94`
всё ещё per-row (`for i, row in enumerate(rows): self._adapter.execute(...)`), а
`BaseSyncAdapter.execute:53-60` открывает соединение и коммитит на КАЖДЫЙ вызов. План 2026-06-05 в статусе
DRAFT, ни одна его задача не закрыта. Он проработан и корректен — исполнять его как есть (Task 1.1-3.1
внутри него), а не переписывать.

**Files:** см. родительский план (`Services/sql/interfaces.py`, `adapters/sync_adapter.py`,
`core/base_repository.py`, `Plugins/io/database/plugin.py`, `Services/sql/tests/`)

**Steps:**
1. Открыть родительский план, выполнить его Task 1.1 → 1.2 → 1.3 → 2.1 → 3.1 в указанном порядке.
2. По завершении — проставить `[x]` + хеш коммита в **родительском** плане, статус `DONE`.
3. Здесь отметить `[x]` со ссылкой на тот же коммит.
4. Дополнительно к родительскому плану: снять устаревший комментарий в
   `Plugins/io/telemetry_sink/plugin.py:175-177` («repo.insert_many — per-row commit, не атомарна») —
   после фикса он лжёт.

**Acceptance criteria:**
- [ ] все acceptance-критерии родительского плана закрыты
- [ ] родительский план переведён в `DONE` с хешами
- [ ] комментарий в `telemetry_sink/plugin.py` про per-row commit убран
- [ ] `python scripts/run_framework_tests.py` без регрессий

**Out of scope:** async `insert_many`, `update_many` — явно вне scope родительского плана.
**Dependencies:** нет (но Этап 3 зависит от неё).
**Module contract:** impl-only

---

### Task 1.3 — WAL + `synchronous=NORMAL` опцией конфига

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** SQLite-соединения открываются в WAL-режиме, включаемом через конфиг, а не хардкодом.
**Context:** Проверено: в `Services/sql` **нигде не включён WAL** — `journal_mode` / `synchronous` дают ноль
совпадений. При этом `multiprocess_framework/modules/frontend_module/state/telemetry_history.py` читает
`telemetry.db` **из другого процесса** сырым `sqlite3`, а комментарий на его строке 43 описывает WAL-режим,
которого фактически нет. Сейчас читатель GUI и писатель-плагин конкурируют за блокировку файла в
rollback-journal режиме → `database is locked` под нагрузкой. WAL это чинит (читатели не блокируют писателя).

**Files:**
- `Services/sql/configs/sql_manager_config.py` — новые поля
- `Services/sql/core/engine_factory.py` — навесить PRAGMA на событие `connect`
- `Plugins/io/database/plugin.py`, `Plugins/io/telemetry_sink/plugin.py` — включить в `SQLManagerConfig`
- `Services/sql/tests/` — тест

**Steps:**
1. В `SQLManagerConfig` добавить `sqlite_journal_mode: str = "WAL"` и `sqlite_synchronous: str = "NORMAL"`
   (оба с `FieldMeta`). Пустая строка = не трогать PRAGMA (escape hatch).
2. В `create_sync_engine`: после `create_engine` повесить `sqlalchemy.event.listens_for(engine, "connect")`,
   который выполняет `PRAGMA journal_mode=<...>` и `PRAGMA synchronous=<...>`. **Только для sqlite-URL** —
   на postgres/mysql PRAGMA не существует, ветку не выполнять.
3. Значения PRAGMA подставляются из whitelist (`{"WAL","DELETE","TRUNCATE","MEMORY",""}` и
   `{"OFF","NORMAL","FULL","EXTRA",""}`) — не сырой строкой из конфига (PRAGMA не принимает bind-параметры,
   конкатенация без whitelist = инъекция).
4. Включить в двух плагинах-писателях (`database`, `telemetry_sink`) явно, дефолтом.
5. Актуализировать комментарий `telemetry_history.py:43` — теперь он описывает реальность.

**Acceptance criteria:**
- [ ] `PRAGMA journal_mode` на соединении возвращает `wal` для файловой SQLite-БД
- [ ] значение вне whitelist → `ValueError` при создании engine, не выполняется как SQL
- [ ] postgres/mysql-URL: PRAGMA не отправляется (тест на mock/spy)
- [ ] in-memory SQLite не падает (WAL на `:memory:` игнорируется движком — проверить, что не бросает)
- [ ] `TelemetryHistorySource.list_range` читает БД, в которую параллельно идёт запись, без `database is locked`

**Out of scope:** `PRAGMA mmap_size`, `cache_size`, `busy_timeout` — отдельные ручки, сейчас не нужны;
async-адаптер (нет потребителей).
**Edge cases:** WAL создаёт рядом `-wal` и `-shm` файлы — при копировании/бэкапе БД их надо брать вместе
(зафиксировать в README `Services/sql`); WAL не работает на сетевых ФС (для Pi с USB-SSD не проблема).
**Dependencies:** нет.
**Module contract:** public-api-change (новые поля `SQLManagerConfig`)

---

### Task 1.4 — дефолт ретенции телеметрии 0 → 14 дней

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** БД телеметрии перестаёт расти вечно — ретенция реально применяется, а не только настраивается.
**Context:** `Plugins/io/telemetry_sink/registers.py:46` — `retention_days: int = 0` («выключено»). При
30-40 МБ/сутки за год это ~13 ГБ, который никто не удалит.

**ВАЖНО (правка после ревью плана):** смены дефолта НЕДОСТАТОЧНО. `_cmd_purge_old` — команда, вызываемая
вручную; в проде её никто не вызывает. Дефолт `14` сам по себе не удалит ни одной строки, и задача выглядела
бы закрытой, не дав эффекта. Поэтому здесь же — минимальный вызов purge при старте плагина. Полноценный
планировщик по-прежнему вне scope.

**Files:**
- `Plugins/io/telemetry_sink/registers.py` — дефолт и текст `info`
- `Plugins/io/telemetry_sink/plugin.py` — вызов purge в `start()`
- `Plugins/io/telemetry_sink/README.md` / `STATUS.md`
- `Plugins/io/telemetry_sink/tests/`

**Steps:**
1. `retention_days` = `14`; в `info` дописать «по умолчанию 14 дней; 0 = хранить вечно».
2. В `start()` — ПОСЛЕ `create_tables`, до старта sample-worker'а — один вызов `_cmd_purge_old({})`.
   Обернуть в `try/except`: битая/занятая БД не должна мешать старту процесса, только залогировать.
   Этого достаточно: процессы перезапускаются регулярно, окно роста ограничено одним аптаймом.
3. Обновить README/STATUS: ретенция применяется при старте, не по расписанию.

**Acceptance criteria:**
- [ ] дефолт `14`, `0` по-прежнему означает «без ретенции»
- [ ] после `start()` на БД со строками старше 14 дней эти строки удалены (тест на файловой БД)
- [ ] `retention_days=0` → `start()` ничего не удаляет
- [ ] исключение внутри purge не срывает `start()` плагина
- [ ] тесты `Plugins/io/telemetry_sink/tests/` зелёные

**Out of scope:** **планировщик периодической ротации** (по таймеру во время работы) — отдельная задача;
purge при старте её не заменяет, а ограничивает худший случай.
**Dependencies:** нет.
**Module contract:** impl-only

---

## Этап 2 — консервация опциона PostgreSQL

> Смысл этапа: граница диалектов **уже написана**. Если её не проверять, она сгниёт за пару месяцев
> незаметно — кто-нибудь положит в схему SQLite-изм, и «опцион Postgres» окажется фикцией ровно в тот
> момент, когда понадобится. Это дёшево (один CI-тест), но должно быть сделано.

### Task 2.1 — CI-тест диалектной совместимости схем

**Level:** Middle (Sonnet)
**Assignee:** tester
**Goal:** Любая sink-схема строит валидный DDL под `dialect="postgresql"`, иначе CI красный.
**Context:** `Services/sql/adapters/postgresql.py` и диалектная логика `core/ddl_builder.py:46-76,203-234`
существуют. Тест ловит SQLite-измы в схемах **в момент их появления**, а не через полгода при миграции.

**Files:** `Services/sql/tests/test_dialect_compat.py` (создать)

**Steps:**
1. Собрать список всех прикладных схем-таблиц: `DetectionSchema` (`Plugins/io/database/schemas.py`),
   `TelemetrySnapshot` (`Plugins/io/telemetry_sink/schemas.py`) + всё, что появится в Этапе 3.
2. Параметризованный тест: для каждой схемы × каждого диалекта из `("sqlite", "postgresql")` —
   `DDLBuilder.build_create_table(schema, dialect=...)` не бросает и возвращает непустой SQL.
3. Проверить отсутствие SQLite-измов в postgres-выводе: нет `AUTOINCREMENT` (в PG это `SERIAL`/`IDENTITY`),
   нет `unixepoch`.
4. Индексы: `build_create_index` (если есть) — тот же прогон по обоим диалектам.

**Acceptance criteria:**
- [ ] тест падает, если в схему добавить поле с SQLite-специфичным типом/дефолтом (проверить намеренной поломкой)
- [ ] список схем собирается так, что новая забытая схема заметна (реестр в одном месте + комментарий-инструкция)
- [ ] тест запускается в общем прогоне `python scripts/run_framework_tests.py`

**Out of scope:** реальное подключение к PostgreSQL, тесты на живой БД, docker-фикстуры. Проверяем **только
генерацию DDL** — это и есть предмет консервации.
**Dependencies:** после Task 1.1 (если она меняет колонку `data`).
**Module contract:** n/a

---

### Task 2.2 — правило «никакого сырого SQL мимо адаптера»

**Level:** Junior (Haiku)
**Assignee:** docs-writer
**Goal:** Зафиксировать правило письменно + пометить единственное известное исключение.
**Context:** Сегодня `telemetry_sink._cmd_purge_old` (`plugin.py:284`) шлёт сырой
`DELETE FROM telemetry_snapshots WHERE ts < :cutoff` через `SQLManager.execute`. Это работает на обоих
диалектах и **переписывать его не надо** — но надо зафиксировать как известное исключение, чтобы оно не
размножилось.

**Files:**
- `Services/sql/README.md` — раздел «Правила для потребителей»
- `Plugins/io/telemetry_sink/plugin.py` — комментарий над `_cmd_purge_old`

**Steps:**
1. В README `Services/sql`: новый код sink'ов работает через `GenericRepository` / `SQLManager.create_tables`.
   Сырой SQL — только если конструкции нет в репозитории, и только диалектно-нейтральный (без `unixepoch`,
   `AUTOINCREMENT`, `PRAGMA`, `ON CONFLICT` SQLite-формы).
2. Над `_cmd_purge_old` — комментарий: «известное исключение, диалектно-нейтральный DELETE; см. README
   Services/sql» + ссылка на этот план.

**Acceptance criteria:**
- [ ] правило в README `Services/sql` со списком запрещённых конструкций
- [ ] исключение помечено в коде и не выглядит как образец для подражания

**Out of scope:** переписывать `_cmd_purge_old`; линтер/AST-проверка на сырой SQL (можно позже, если правило
начнут нарушать).
**Dependencies:** нет.
**Module contract:** n/a

---

### Task 2.3 — пути к файлам в БД только относительные

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Все файловые пути, попадающие в БД, — относительные от единого корня данных.
**Context:** **Самая дешёвая закладка именно сейчас, пока строк мало.** Абсолютный
`D:\PROJECT_INNOTECH\...\frames\2026-07-21\frame_007.jpg` в БД ломает вообще всё при переносе Win→Jetson/Pi
и при переезде каталога данных на другой диск. После Этапа 3 таких ссылок станут миллионы, и починка
превратится в миграцию. Сейчас — это одно решение и один хелпер.

**Files:**
- `Services/sql/paths.py` (создать) — хелперы `to_storage_path` / `from_storage_path` + корень данных
- `Plugins/io/database/plugin.py` — применить при записи путей
- `Services/sql/tests/test_paths.py` (создать)

**Steps:**
1. Определить корень данных: env `INSPECTOR_DATA_ROOT`, дефолт — `data/` относительно корня проекта.
   Один источник истины, задокументировать.
2. `to_storage_path(abs_path) -> str`: относительный путь от корня, **разделитель всегда `/`** (POSIX),
   даже на Windows. Путь вне корня → `ValueError` (явная ошибка лучше молчаливого абсолютного пути).
3. `from_storage_path(rel) -> Path`: обратно, через `os.path.join` с текущим корнем.
4. Применить в `DatabasePlugin` везде, где в запись попадает путь к файлу.
5. Зафиксировать инвариант в README `Services/sql`: «в БД не хранится ни один абсолютный путь».

**Acceptance criteria:**
- [ ] round-trip: `from_storage_path(to_storage_path(p)) == p` на Windows и POSIX-путях
- [ ] в сохранённой строке никогда нет `\` и никогда нет буквы диска / ведущего `/`
- [ ] путь вне корня данных → `ValueError` с внятным сообщением
- [ ] смена `INSPECTOR_DATA_ROOT` меняет разрешение существующих записей (тест: записали при корне A,
      прочитали при корне B — путь указывает в B)

**Out of scope:** миграция существующих строк (их ~318 и они legacy — см. Task 1.1); символические ссылки;
UNC-пути.
**Edge cases:** регистр букв — на NTFS `Frames/` и `frames/` одно и то же, на ext4 разные; хелпер **не**
нормализует регистр, но README обязан предупредить (см. раздел «Портируемость»).
**Dependencies:** нет; но Этап 3 обязан использовать этот хелпер с самого начала.
**Module contract:** public-api-change (новый публичный модуль `Services/sql/paths.py`)

---

## Этап 3 — снапшоты и кэш отрисовки

> Единственный этап с новой функциональностью. Целиком строится на **готовых кирпичах**, писать с нуля
> ничего не надо: `Plugins/io/frame_saver` (папки-дни, resume нумерации, retention удалением каталога,
> атомарная запись `*.tmp` + `replace`, sidecar-JSON — `plugin.py:211-280`) и
> `Plugins/io/drawing_io/store.py` (sidecar `stem.json` + `stem.png`).

### Task 3.1 — [ВЕРТИКАЛЬНЫЙ СРЕЗ] снапшот кадра end-to-end

**Level:** Senior (Opus)
**Assignee:** teamlead
**Goal:** Один кадр проходит весь путь: расширенная строка в БД → файлы на диске → чтение через read-фасад.
**Context:** Тонкий сквозной срез через все три слоя (схема / файловое хранилище / чтение), каждый в
минимальной форме: одна новая колонка, один снапшот из одного кадра, один метод чтения. Даёт обратную связь
на первой же задаче, а не в конце этапа. Углубление слоёв — в 3.2 и 3.3.

**Files:**
- `Plugins/io/database/schemas.py` — расширить `DetectionSchema`
- `Plugins/io/snapshot_store/store.py` (создать) — запись каталога снапшота
- `multiprocess_framework/modules/frontend_module/state/` — read-фасад (по образцу `telemetry_history.py`)
- тесты рядом с каждым

**Steps:**
1. `DetectionSchema` + поля: `snapshot_id: Optional[str]`, `frame_path: Optional[str]` (**относительный**,
   через `Services/sql/paths.py` из Task 2.3), `recipe_slug: Optional[str]`, `verdict: Optional[str]`.
   Индекс `(camera_id, frame_id)` в `SQLMeta.indexes`. Все поля `Optional` — старые строки остаются валидны.
2. `snapshot_store.save_frame(...)`: пишет `snapshots/<дата>/<snap_id>/frame_00.jpg` + `frame_00.json`.
   Обобщить `drawing_io/store.py` (та же идея sidecar `stem.json` + `stem.<ext>`), атомарную запись
   (`*.tmp` → `.replace`) взять из `frame_saver/plugin.py:211-220`.
3. Read-фасад: метод «дай результаты кадра X» — SQLite `mode=ro` URI, соединение на запрос, **пустой
   результат вместо исключения** при отсутствии файла/таблицы (тот же контракт отказоустойчивости, что у
   `TelemetryHistorySource` — он для GUI обязателен).
4. Сквозной тест: записали один кадр → в БД строка со `snapshot_id` и относительным `frame_path` → фасад
   вернул её и файл по пути реально существует.

**Acceptance criteria:**
- [ ] сквозной тест «записали кадр → прочитали через фасад → файл на месте» зелёный
- [ ] `frame_path` в БД относительный (нет `\`, нет буквы диска)
- [ ] старые строки `detections` без новых колонок читаются без ошибок
- [ ] фасад на несуществующей БД возвращает `[]`, не бросает
- [ ] запись атомарна: убитый процесс между `tmp` и `replace` не оставляет битый `.jpg`

**Out of scope:** множественные кадры в снапшоте, `manifest.json`, `.npz` — это 3.2; ретенция снапшотов — 3.3.
**Edge cases:** `snap_id` должен быть безопасен как имя каталога (без `:` — запрещён в NTFS); дата в имени —
локальная, зафиксировать это явно, чтобы прогон через полночь не путал.
**Dependencies:** Task 1.2 (атомарный `insert_many`), Task 2.3 (хелпер путей).
**Module contract:** new-lite (`snapshot_store/store.py`) + public-api-change (`DetectionSchema`)

---

### Task 3.2 — полный снапшот: несколько кадров, manifest, крупные массивы в `.npz`

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Снапшот — каталог из N кадров с манифестом; тяжёлые массивы лежат файлами, в БД только путь.
**Context:** Ключевое правило размещения: **payload ≤ ~100 КБ — в JSON-колонку БД; крупные массивы
(маски, контуры) — в `.npz` рядом с кадром, в строке БД только относительный путь.** SQLite прекрасно
хранит мелкий JSON и отвратительно — мегабайтные блобы: они раздувают файл, ломают локальность страниц и
делают `VACUUM` неподъёмным.

**Files:**
- `Plugins/io/snapshot_store/store.py` — расширить
- `Plugins/io/snapshot_store/tests/`

**Steps:**
1. Структура каталога: `snapshots/<дата>/<snap_id>/frame_NN.jpg` + `frame_NN.json` + `manifest.json`.
   `manifest.json` — версия схемы, `snap_id`, время, `recipe_slug`, список кадров, итоговый `verdict`.
2. Порог размещения: сериализованный payload > ~100 КБ **или** значение — `np.ndarray` → в
   `frame_NN.npz` (`np.savez_compressed`), в JSON/БД остаётся `{"npz": "frame_NN.npz", "key": "mask"}`.
   Порог — константа модуля с комментарием, не магическое число.
3. `manifest.json` пишется **последним** и атомарно — его наличие = маркер «снапшот целый». Каталог без
   манифеста считается недописанным.
4. Загрузка: `load_snapshot(snap_id)` → манифест + кадры + лениво поднятые `.npz`.

**Acceptance criteria:**
- [ ] снапшот из 3 кадров пишется и читается round-trip
- [ ] массив 5 МБ уходит в `.npz`, в БД/JSON — путь, не блоб
- [ ] каталог без `manifest.json` распознаётся как недописанный и не отдаётся как валидный
- [ ] запись прерванного снапшота не ломает чтение остальных

**Out of scope:** сжатие кадров отличное от того, что уже умеет `frame_saver`; версионирование/миграция
формата манифеста (заложить поле `version`, механику миграции — не писать).
**Dependencies:** Task 3.1.
**Module contract:** public-api-change

---

### Task 3.3 — ретенция снапшотов

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Снапшоты не растут вечно — старые дни удаляются, строки БД не ссылаются в пустоту.
**Context:** Картинки — главный потребитель диска (0.9-3.5 ГБ/сутки). Без ретенции Pi с USB-SSD
заканчивается за недели. `frame_saver` уже умеет удалять каталог-день целиком
(`_cleanup_old_days`, `plugin.py:324-347`) — переиспользовать подход, не изобретать.

**Files:**
- `Plugins/io/snapshot_store/store.py` или отдельный `retention.py`
- регистры плагина-владельца — `snapshot_retention_days`

**Steps:**
1. Ретенция по каталогам-дням (удаление `snapshots/<дата>/` целиком) — дёшево, как в `frame_saver`.
2. Параметр `snapshot_retention_days`, дефолт **7** (кадры тяжелее телеметрии — срок короче, ср. Task 1.4).
3. Строки БД, чей `frame_path` указывает на удалённый день: **не удалять**. Строка остаётся как факт
   инспекции, фасад отдаёт её с признаком «файл недоступен». Удаление строк — отдельное решение, не здесь.
4. Тяжёлый `rmtree` — вне блокировки data-пути (тот же приём, что `frame_saver`: взвести флаг под lock,
   выполнить вне).

**Acceptance criteria:**
- [ ] каталоги старше N дней удаляются, свежие не трогаются
- [ ] `rmtree` не выполняется под блокировкой горячего пути
- [ ] фасад на строке с удалённым файлом возвращает запись + флаг «файла нет», не бросает
- [ ] `snapshot_retention_days=0` = ретенция выключена (согласовано с семантикой `telemetry_sink`)

**Out of scope:** ретенция по суммарному размеру/свободному месту (полезно, но это отдельная задача);
удаление строк БД; архивация на внешний носитель.
**Edge cases:** каталог занят другим процессом (Windows) → `rmtree` частично упадёт; логировать и
повторить на следующем цикле, не считать фатальным.
**Dependencies:** Task 3.2.
**Module contract:** impl-only

---

## Этап 4 — SCADA-endpoint (независим, можно параллельно)

### Task 4.1 — `sim_server` → постоянная Modbus-нода с картой регистров в YAML

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Постоянно работающий Modbus-TCP slave, чью карту регистров задаёт YAML, а не код.
**Context:** `Services/modbus/server/sim_server.py` — **рабочий** Modbus-TCP slave на pymodbus 3.13
(`SimData`/`SimDevice`, `trace_pdu`), demo уже пишет результаты в holding-регистры. Каркас SCADA-endpoint
фактически готов — нужно перевести его из «симулятора для demo» в постоянную ноду с декларативной картой.
Протокольные YAML-файлы уже есть: `Services/modbus/core/protocol_file.py`, `register_map.py`. Полезно при
**любой** будущей SCADA — это стандартный промышленный протокол, а не ставка на конкретного вендора.

**Files:**
- `Services/modbus/server/sim_server.py` — карта из YAML вместо хардкода размера
- `Services/modbus/server/__main__.py` — аргумент пути к YAML
- `Services/modbus/README.md`, `Services/modbus/tests/`

**Steps:**
1. Читать карту регистров через существующий `protocol_file.py` / `register_map.py` — **не писать новый
   парсер YAML**.
2. Публикация значений: метод/команда «обновить регистр по имени из карты» — писатель не должен знать
   числовых адресов.
3. Graceful degradation сохранить: модуль импортируется без pymodbus (`MODBUS_AVAILABLE = False`),
   ошибка — только при попытке старта.
4. Тесты без pymodbus: разбор карты и разрешение «имя → адрес» — чистые функции (как `format_recv`).

**Acceptance criteria:**
- [ ] карта регистров задаётся YAML-файлом, код не содержит хардкод адресов
- [ ] запись по имени попадает в правильный holding-регистр (тест на разрешении адреса без сети)
- [ ] модуль импортируется в окружении без pymodbus
- [ ] существующий demo-сценарий не сломан

**Out of scope:** **OPC UA / `asyncua` — НЕ делать**, пока не названа конкретная SCADA-платформа; аутентификация;
Modbus RTU поверх последовательного порта; master-роль (она уже есть в `sdk/client.py`).
**Dependencies:** нет — можно вести параллельно любому этапу.
**Module contract:** public-api-change

---

## Не делать (явный отказ)

| Не делаем | Почему |
|-----------|--------|
| **Parquet-writer** | Нет аналитической нагрузки, которой не хватает SQLite. Плюс зависимость (pyarrow) весом с половину проекта |
| **DuckDB** | Лишний слой поверх SQLite на наших объёмах |
| **PostgreSQL / GreptimeDB / InfluxDB 3** | См. вердикт. Postgres — опцион по триггеру (Этап 2 его консервирует), остальные отклонены по существу |
| **Qdrant / любая векторная БД** | Векторных фич нет; на Jetson конфликтует по RAM с GPU-инференсом |
| **Логи в БД** | Логи идут через `logger_manager` в файлы. БД для логов — классическая ошибка: раздувает файл и конкурирует за блокировку с горячим путём записи результатов |
| **Undo в БД** | Решено аудитом [`2026-06-18_command-undo-system.md`](../docs/audits/2026-06-18_command-undo-system.md) §4 — undo остаётся in-memory |
| **Рецепты в SQLite** | Остаются YAML: `ruamel` сохраняет комментарии, есть git-диффы, история и миграции. БД всё это ломает ради нулевой выгоды |
| **Конвертер legacy repr→JSON** | ~318 строк demo-прогонов; дороже написать, чем стоят данные (Task 1.1) |
| **OPC UA (`asyncua`)** | Пока не названа конкретная SCADA-платформа с OPC UA |

---

## Триггеры перехода (когда пересматривать вердикт)

Зафиксировано числами, чтобы будущий читатель не гадал.

| Переход | Триггер |
|---------|---------|
| **→ файл-БД на день** (шардирование по дате вместо одного файла) | Устойчиво **> 1-2 ГБ/сутки** записи в БД |
| **→ PostgreSQL** | Любое из: **(а)** вторая машина, пишущая к нам **по сети**; **(б)** контрактное требование прямого SQL-доступа от SCADA/MES-интегратора; **(в)** внешняя система, пишущая в нашу БД |
| **→ `sqlite-vec`** (не Qdrant!) | Первая **реальная** фича similarity-поиска при **≤ 1 млн векторов**. Выше миллиона — пересмотреть заново |
| **→ `asyncua` (OPC UA)** | Названа конкретная SCADA-платформа, требующая OPC UA |

Ни один триггер не срабатывает «на всякий случай» — только по факту.

---

## Портируемость: Windows / Jetson / Raspberry Pi

Риски, которые обязаны учитывать все задачи плана:

1. **Регистр в путях.** NTFS регистронечувствительна, ext4 — чувствительна. Код, работающий на Windows с
   `Frames/` и `frames/` как с одним каталогом, на Jetson/Pi сломается. Правило: имена каталогов и файлов
   генерируем в нижнем регистре, сравнение путей — никогда не через `.lower()`-нормализацию (это маскирует
   баг, а не чинит).
2. **Абсолютные Windows-пути в данных.** Закрывается Task 2.3 — в БД только относительные POSIX-пути.
3. **Windows-обходы должны быть no-op на Linux.** Retry на `os.replace` при `WinError 5` (см. известный долг
   `project_app_module_windows_test_debt`) обязан оставаться безвредным на Linux: ловить конкретный
   `PermissionError`/`OSError` с проверкой платформы, а не глотать все исключения.
4. **Raspberry Pi — данные на USB-SSD, не на системную SD-карту.** SD не переживёт постоянной записи;
   это же главный аргумент против LSM-движков (Influx/Greptime). Путь данных — через
   `INSPECTOR_DATA_ROOT` (Task 2.3), чтобы вынос на другой носитель был сменой env, а не правкой кода.
5. **Flush-интервалы не короче 1-2 с.** Частый fsync на SD/eMMC — прямой износ. Дефолты
   `flush_interval_sec` / `sample_interval_sec` не опускать ниже 1 с без замера.
6. **WAL-файлы.** `-wal` и `-shm` при копировании/бэкапе БД берутся вместе с основным файлом (Task 1.3).

---

## Риски

- **Task 1.3 (WAL) трогает общий слой** — включается для ВСЕХ потребителей `Services/sql`. Митигация:
  опция конфига с escape hatch (пустая строка = не трогать PRAGMA), полный прогон
  `python scripts/run_framework_tests.py`.
- **Task 1.2 — чужой план.** Риск, что исполнитель начнёт его переписывать вместо выполнения. В спеке
  явно: исполнять как есть, свериться, не дублировать.
- **Этап 3 меняет `DetectionSchema`** — все новые поля `Optional`, старые строки обязаны читаться.
  Проверяется отдельным acceptance-критерием в 3.1.
- **Task 2.1 может оказаться сразу красным** — если в текущих схемах уже есть SQLite-изм. Это не провал
  задачи, а её польза; починка найденного — в рамках той же задачи, если укладывается в 1-2 файла,
  иначе отдельная задача.
