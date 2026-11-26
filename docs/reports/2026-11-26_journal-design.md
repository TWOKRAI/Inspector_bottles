## Универсальный журнал: что уже есть и что предлагаю (inspector-bottles-d1)

Срез `main` 53efe24b9. Код не менял, ничего не коммитил. Индекс qex 39 дней, факты взяты из `git grep` и чтения. Пометки: **[П]** — прогнано мной, **[Ч]** — по чтению кода, **[Ч/помощник]** — карта помощника Haiku, решающие строки я не перечитывал.
Скрипт: `C:\Users\INNOTECH\AppData\Local\Temp\claude\65f734dde6ea3dc7\96295c47-68c9-45a7-997e-358c9fc73c33\scratchpad\jr\probe_journals.py`. Запуск: `PYTHONPATH=<корень> PYTHONUTF8=1 bash scripts/machine_gate.sh light inspector-bottles-d1 .venv/Scripts/python.exe <скрипт>`, только временные пути.
memory hits: `scripts/memory/search.py journal audit device command log` → `project_command_engine_audit.md` (ActionBus в проде мёртв); остальные попадания не по теме.

### Главное

**Отдельная служба журнала уже есть. Это плоскость документов `Services/documents`.** Это пакет слоя Services. Фреймворк знает только строку фабрики из конфига. Один файл `data/documents.db` на всю систему, срок хранения задаётся для каждого рода отдельно (`system.yaml:69-78`, `wiring.py:50-149` [Ч]). В неё уже пишут два писателя: аудит смен наблюдаемости во всех процессах и вердикты отбраковки (`robot_control/plugin.py:471`). Новый пакет или процесс не нужен. Нужно доделать эту плоскость и вести журнал команд по образцу `ObservabilityAudit`: кольцо, `seq`, строка лога, документ.

### 1. Журналы, найденные по коду

| # | Журнал | Пишет | Хранение и срок | Кто читает | Вывод |
|---|---|---|---|---|---|
| 1 | Вкладки «Логи», «Ошибки», «Статистика» | logger, error, stats каждого процесса → tap → `ObservabilityStore` | `logs/observability.db`; общий потолок 200 000 строк и 7 суток на ВСЕ роды сразу (`observability_config.py:270-296` [Ч/помощник]; `observability_store.py:931-987` [П]) | один класс `RecordHistoryPanel` на три вкладки; GUI сам открывает файл (`observability_tabs.py:36-40`, `record_source.py:101-115` [Ч]); `backend_ctl history_query` | уже **один** стор и **один** просмотр. Журналом команд не годится (ниже) |
| 2 | Аудит смен наблюдаемости | `ObservabilityAudit` в каждом процессе | кольцо 100 (`observability_audit.py:51`) + строка лога + документ `audit` на 1 год | `introspect.observability`; GUI документов не читает | **образец**: `seq`, `dropped = seq − len`, схлопывание повторов (`:193-286` [Ч]) |
| 3 | Вердикты брака | `robot_control` через `ctx.write_document` | `documents.db`, род `verdict`, 10 лет | читателя нет ни в GUI, ни в `backend_ctl` (grep [Ч]) | долговечная плоскость. Своего просмотра у неё нет |
| 4 | Аудит auth | `AuditWriter` → `SqliteAuditStorage` | своя SQLite | `audit_log_panel.py:283` | **спит**: `audit=None` (`app.py:720-721`), `AuditWriter(` вызывается только в тестах, `AuditMiddleware` висит на ActionBus, а он в проде мёртв |
| 5 | Обмен робота v2 (T5.6) | `ExchangeLog` | кольцо 2000 + файл `robot_exchange.log` через logger, до 100 строк/с (`system.yaml:113-119,147-150`) | `exchange_log_get` | оставить отдельно: сырой провод, большой объём |
| 6 | Аудит `backend_ctl` | `AuditLog` | кольцо 200 + `audit.jsonl`, срока хранения нет (`audit.py:40,82,162-172`) [Ч/помощник] | `session_log` | инструмент разработчика; позже — общий конверт |
| 7 | Запись и повтор `backend_ctl` | `Recorder` | очередь 50 000, отбрасывает новые записи (`recorder.py:49-53,362-366`) [Ч/помощник] | `record_load` | оставить: формат повтора |
| 8 | Дамп кольца (flight) | `FlightRecorder` | файлы `flight/`, хранится 5, по умолчанию выключен (`observability_config.py:203-243`) [Ч/помощник] | файлы | оставить: снимок, а не журнал |
| 9 | «История» в настройках | `ProjectHistory` (undo), 50 записей (`command_dispatcher.py:123-130`) [Ч/помощник] | память | `HistoryPresenter` | оставить: это состояние undo |
| 10 | `Services/sql/action_log` | был нужен ActionBus | своя таблица | — | заморожено вместе с ActionBus |
| 11 | `SimJournal` симулятора робота | `robot_host` (`plugin.py:72-83`) | кольца 50 и 200 | `sim_robot.journal` | оставить: эталон для тестов |
| 12 | Широкая запись, строки `word_layout` | `ctx.write_event`, logger | `observability.db` (log) | вкладка «Логи» | уже в журнале №1 |

Журнала ошибок или статистики отдельно от №1 в прототипе нет. Это роды `error` и `stats` одного стора.

**Свойства, проверенные прогоном:**
- `ObservabilityStore` [П]: структурные поля лога сохраняются (`extra.context = {device, job_id, verdict}`), свой род `device_command` тоже записывается. Но фильтры есть только по колонкам `kind/module/process/metric/severity/ts` (`:698-756`), поиск только по `message/module/process` (`record_display.py:241-245`). Главное: `purge(max_rows=500)` после 1000 строк `stats` удалил **и строку лога, и строку журнала**: `log=0 custom=0 stats=500`. Статистика вытесняет редкие роды.
- `DocumentStore` [П]: `append` синхронный, на потоке вызывающего: медиана 7.4 мс, максимум 17.6 мс здесь. Проект сам мерил 928 мс под конкуренцией (`base.py:384-389`). `query` фильтрует только `kind/since/until` (по прибору и `job_id` нельзя), порядок по `ts`. Род без срока не удаляется никогда. Потолка по размеру нет (`store.py:153-167`).
- Аудит auth [П]: очередь без предела (`maxsize 0`, `audit_writer.py:73`). Докстринг про «очередь заполнена → JSONL» (`:147-148`) ложный. Запись по одной строке. `stop()` за 5 с записал 1362 из 20 000; остальное в потоке-демоне, при выходе процесса теряется. После `stop()` запись принимается без ошибки. «Только добавление» держится на уровне репозитория (`delete` → `AuditImmutableError`), но публичный `clear_audit()` стирает всё (`audit_storage.py:275-278`): 0 строк.

### 2. Журнал и logger, error, stats, дерево состояния

| Что | Куда | Чего не дублировать |
|---|---|---|
| Строка для человека о каждой записи журнала | logger (один писатель); долетает в «Логи» с полями в `extra.context` [П] | машины по этим строкам не разбирают (вердикт CTO) |
| Инцидент: связь потеряна, исход `error` или `unknown` | `report_error` основы | отказ допуска — не инцидент: строка и счётчик |
| Счётчики accepted / refused / failed / unknown, длительность | stats, одна точка подсчёта | счётчики в самом журнале не хранить |
| Текущее состояние (`link`, `last_command`) | дерево | историю в дерево не класть: replay отбрасывает dict |
| Запись о решении и команде, которая переживает рестарт | плоскость документов | в `observability.db` не класть: вытеснение и горизонт часов [П] |

Хранилище для журнала уже есть, это `documents.db`. Не хватает трёх вещей: записи, которая не блокирует, фильтра по прибору и `seq`, потолка размера.

### 3. Журнал и `Services/auth`

- **Кто послал.** Через границу процессов личность не идёт. Обработчик плагина получает только `data` (`cmd_*(self, data)`, `plugin.py:958-1297`); права проверяются только в GUI (`access_context.py:35-41`, frontend_module) [Ч]. Значит, `source` и `user` журнал записывает со слов отправителя, а не после проверки. Это надо назвать прямо.
- **Проверка прав при допуске** — не дело журнала. В 1.0 GUI проверяет права до отправки, хаб пишет заявленного автора. Проверка в бэкенде требует передачи личности по IPC, это 2.0.
- **Делить с auth нужно личность, а не хранилище.** Поля `user` и `role` в конверте; auth от журнала не зависит, и наоборот.
- **Можно ли перевести аудит auth на общую плоскость?** Да, и обещанных им гарантий это не убавит. Сегодня их нет: нет проводки, `clear_audit`, потери на `stop` [П]. `AuditEntry` (`models.py:304-364`) ложится в документ рода `auth_audit`: `before_json/after_json` идут в payload, `user_id` — в `subject`. Таблица `auth_sessions` — это состояние (UPDATE `logout_at`), она остаётся в auth. Старые классы заморозить, не удалять.

### 4. Схема

**Конверт v1** (dict, один на все журналы): `v=1, journal, seq, boot, ts, subject` (device_id или user_id), `subject_kind, event` (`admit|refuse|outcome|link|change`), `op, source, user, job_id, ref_seq` (у исхода), `verdict` с `reason` (код и текст), `outcome` (`done|error|cancelled|unknown`), `dur_ms, wire_seq` (CMD_SEQ, связь с обменом), `args` (урезать до 1 КБ, как `_VALUE_CAP`).

**API записи:** `journal.record(event, **fields) -> seq`. Метод никогда не бросает исключений. Выключенный журнал возвращает 0 до того, как собирает dict: гейт у источника, как `ObservabilityCommandsConfig.log_success` (`observability_config.py:583-599`).
**API чтения:** `read(after_seq, boot, subject, limit) -> {boot, records, last_seq, lost, dropped}`. Команда хаба `device_journal_get` и тот же вызов из `backend_ctl`. Курсор читается из кольца в памяти, не из SQLite.
**Обратное давление.** Кольцо под коротким замком: микросекунды. Документы идут через ограниченную очередь (сброс старых, счётчик `dropped`) и один поток-писатель на процесс. Готовая форма — `BoundedChannel` и `BatchDrainWorker` (`batch_drain.py:124,159` [Ч/помощник]). Отказ стока: `dropped` + одна строка. Команду журнал не роняет и не задерживает.
**Процесс.** Журнал живёт в процессе владельца прибора (`devices`). Пишут поток команд (допуск) и поток тика (исход). В IPC идёт только dict ответа.

| Вариант | За | Против |
|---|---|---|
| A. Только кольцо в хабе (вердикт CTO как есть) | быстрее всех | после рестарта ничего нет; следующий журнал будет копией |
| **B. Кольцо у владельца + конверт v1 + копия в плоскости документов, неблокирующая** | слоёв не прибавляется; служба уже есть; один просмотр для audit, verdict и команд | нужны неблокирующий сток и колонки `subject`/`seq` в `Services/documents` |
| C. Отдельный процесс журнала | один писатель на систему | лишний переход по IPC и лишняя точка отказа; WAL с писателем на процесс эту задачу уже решает |
| D. Всё через logger: канал-сток в БД | буквально «один писатель» | допуск по уровню и троттлинг теряют записи; проект этот путь уже отверг (README documents `:131-137`, ADR-CRM-013) |

**Рекомендую B.** В 1.0 класс лежит в `Services/device_hub/journal.py`. Его импортирует только Plugins. Фреймворк не трогаем.

**Конфиг через data_schema** (дороги уже есть [Ч]):
- Процессный уровень: секция `observability` идёт слоями. L1 `system.yaml`, затем L2 спутник рецепта (`launch.py:724-735`), затем L3 команда, сборка в `process_observability_layers().resolve()` (`observability_wiring.py:1241-1290`). Отсюда приходит `ObservabilityDocumentsConfig` (factory и dict: `db_path`, `retention_sec`; `:65-90`). Срок хранения журнала задаётся ключом `retention_sec.device_command`.
- Уровень плагина: новая вложенная `SchemaBase` `JournalPolicy` (`enabled`, `ring`, `exclude_ops`, `durable`) в `DeviceHubPluginConfig` (`config.py:16-24`). Конфиг плагина едет внутри blueprint рецепта.
- **`domain/entities/recipe.py` трогать не нужно.** Верхний уровень там `extra="forbid"` (`:95-99`), но конфиг плагина лежит внутри `blueprint`, а `devices` — это `dict[str, Any]` (`:122-125`).

**Проверка предложения координатора.**
- «Рецепт задаёт, что пишется, и подробность» — согласен.
- «Путь, срок и потолок задаёт только системный конфиг» — **код этого не обеспечивает.** `documents` перекрывается рецептом L2 и командой L3 (`observability_config.py:766-769`). Нужен замок ключа; есть ли он в `observability_layers`, я не нашёл. Потолка размера в `DocumentStore` нет, его надо добавить.
- «Рецепт не может выключить аудит auth» — верно по пустой причине: аудит auth в рецепт не входит и сегодня уже выключен проводкой.
- «Выключенный журнал почти ничего не стоит» — достижимо гейтом у источника.

### 5. Этапы

**До 2026-11-30, самый маленький полезный срез:**
1. `Services/device_hub/journal.py`: кольцо 4096, `seq`, `boot`, конверт v1, `record/read`, `dropped`, `lost`.
2. `Plugins/hub/device_hub/plugin.py`: в `_kind_call` и `_driver_call` (`:908-944`) писать `admit/refuse` до кода драйвера и `outcome` по ответу. Там же поправить `_safe_call`: сейчас он считает `status:error` успехом (`:887-897`). Добавить команду `device_journal_get` и строку лога на каждую запись.
3. `robot_io`: передавать `source` и `job_id`, не снимать их.
4. `exclude_ops` для чтений, `get_telemetry` и `jog_hold`.
5. Тесты: отказ оставляет строку; переполнение даёт `lost` и `dropped`; исключение журнала не роняет команду (инъекция); `seq` монотонен на двух потоках.
Документов в срезе нет. На первую неделю хватит лога процесса (7 суток) и `device_journal_get`.

**1.0:**
- Неблокирующий сток в `Services/documents` (опция фабрики) и колонки `subject`/`seq` с индексом.
- Род `device_command` в `system.yaml`.
- Инструмент `backend_ctl journal_query`: чтение только на чтение, как `history_query`.
- Вкладка «Журналы» поверх `documents.db` (прототип).
- Исход задания до `word_layout`, записи `link`, ПЧ.
- Потолки по родам в `ObservabilityStore`: дефект вытеснения [П], полоса наблюдаемости.

**2.0:**
- Общий примитив `Journal` в framework. Первые пользователи: `ObservabilityAudit` и камера. Делать, только когда два пакета реально его импортируют.
- Аудит auth переходит на плоскость, старые классы заморожены.
- Личность через границу процессов.

**Не делать никогда:**
- Одна БД для логов, статистики и журналов.
- Сырой обмен в долговечной плоскости.
- Отдельный процесс журнала.
- Проверку прав внутри журнала.

### 6. Стыки с полосами

- **Р2 (отчёт `r2-device-arch`).** Срез выше — это расширенный S0.2. Вердикт CTO **меняется частично**:
  - стоит: контракт и журнал в `device_hub`, framework не трогаем до 2.0;
  - меняется: долговечная копия идёт в существующую плоскость документов, а не во вторую БД хаба; конверт v1 фиксируется сразу как общий.
- **`refactor/observability-signal-contracts`** (в работе): владеет tap, стором и отказами записи. Потолки `ObservabilityStore` и любые правки `record_display` — после их слияния.
- **Плоскость документов** (`observability-unified-routing.md` Ф8.5, ADR-PM-028/029). Неблокирующий `append` меняет смысл Post «True = записан» на «принят». Нужен ADR и согласие владельца пакета. Владельца я не установил.
- **`device-common-base` (`docs/camera-plan-merge`):** камера в 1.0 журнал не пишет, конфликта нет. **`multicam-observability`:** SUPERSEDED (`plan.md:5`).
- **`r2-servo`:** серво будет следующим пользователем. Конверт v1 надо опубликовать до того, как там пишут путь команд.
- **`recipe.py`:** не затрагивается.

### 7. Идея владельца

**Что верно:**
- один конверт;
- одна долговечная служба для решений и команд, отдельная от диагностики;
- один просмотр;
- конфиг через схему;
- auth даёт личность.

Половина этого уже построена (документы, общий стор логов), просто не доведена.

**Что рискованно:**
1. «Свести к одному» в смысле одного хранилища — ошибка. Объём, потери и сроки различаются в разы: статистика каждые 10 с, обмен до 100 строк/с, аудит хранится год. Прогон показал, что общий потолок стирает редкие роды.
2. Отдельный процесс прибавляет слой.
3. Связывать журнал команд с auth на горячем пути нельзя: auth живёт в GUI.
4. Обобщать в framework до второго потребителя — это API на догадке.
5. Срок до 2026-11-30 вмещает только срез из §5.

Принцип «один пишущий логгер» проект уже сознательно ослабил для документов (ADR-CRM-013). Журнал пойдёт тем же прецедентом, и это стоит сказать владельцу прямо.

### 8. Вопросы владельцу

1. Срок хранения, путь и потолок журнала: только `system.yaml`, или рецепт тоже может их менять? *Рекомендую только `system.yaml`. Это новый замок ключа, сегодня рецепт может.*
2. Включать ли аудит auth в 1.0? *Рекомендую нет; в 1.x как род `auth_audit` в плоскости документов, без выключателя в рецепте.*
3. Нужна ли в 1.0 проверка прав на стороне бэкенда (кто может командовать роботом)? *Рекомендую нет: GUI проверяет, журнал пишет заявленного автора, проверенная личность — в 2.0.*

```
ESCALATION -> cto
Question: Change the CTO verdict partly: keep the journal in device_hub for 1.0, but send the durable copy to the existing documents plane (not a second hub DB) and fix envelope v1 as common now?
Tried: read Services/documents, ObservabilityAudit, auth audit; probe probe_journals.py (outputs A1-A9, B1-B5, C1-C4 above)
Blocked on: CTO decision; owner of Services/documents for the async-append contract change
Files: Services/device_hub/journal.py (new), Plugins/hub/device_hub/plugin.py, Services/documents/{store,schema,wiring}.py
```

MEMORY LESSON feedback_shared_store_row_cap_evicts_rare_kinds.md
```
---
name: feedback_shared_store_row_cap_evicts_rare_kinds
description: Общий потолок строк в сторе (ObservabilityStore.purge max_rows) вытесняет редкие роды (error, journal) объёмом stats / shared store row cap evicts rare kinds, journal, retention per kind
role: investigator
module: [channel_routing_module]
mechanism: [retention]
---
ObservabilityStore.purge(max_rows) deletes the oldest rows across ALL kinds. Probe: 1 log + 1 custom-kind row + 1000 stats, purge(max_rows=500) -> log=0 custom=0 stats=500. Before reusing a shared store as a journal or audit store, check retention per kind; prefer the documents plane (per-kind time retention, unknown kind never purged).
```
(Тег `mechanism: retention` я не сверял с `TAGS.yaml`, лиду надо проверить.)

### 9. Что оставил открытым

- Тело `ObservabilityHistoryConfig`, `purge` в проводке, `BatchDrainWorker`, `AuditLog` и `Recorder` `backend_ctl`, `ProjectHistory`, `FlightRecorder` — карта помощника, строки я не перечитывал.
- Не проверено:
  - пишет ли logger в файл синхронно, то есть цена строки-проекции;
  - есть ли в `observability_layers` замок ключа;
  - проверяет ли реестр приборов поле `journal` внутри `devices`.
- Владелец `Services/documents` и ADR-PM-028/029 не прочитаны. Смена контракта на неблокирующий `append` не согласована.
- Задержки `DocumentStore` мерил на одном процессе без конкуренции. Цифра 928 мс взята из кода проекта, не из моего прогона.
- Оценки объёма работ нет. Стенда и робота не было.
