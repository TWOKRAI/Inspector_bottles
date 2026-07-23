# backend-ctl-review-remediation — правда агрегации, контракт ответов, серверный транспорт

> Slug: `backend-ctl-review-remediation` · Ветка: `fix/backend-ctl-review-remediation` (создать от свежего `main` после merge `fix/truth-holes-closure`) · Создан 2026-07-23
> Основание: максимальное ревью backend_ctl 2026-07-23 (6 агентов + верификация Fable), принято владельцем.
> Итог ревью: [`docs/audits/2026-07-23_backend-ctl-max-review.md`](../docs/audits/2026-07-23_backend-ctl-max-review.md)
> Статус: **единственный активный план backend_ctl** (правило «один активный план на инструмент»; `backend-ctl-proof-discipline` закрыт 2026-07-22 → в архив при старте исполнения).

## Context

Ревью дало общий вердикт ~7/10: инструмент рабочий и сходится, пересборка не показана.
Найдены: 4 подтверждённых P0 класса «правда есть, но не агрегируется», серверные P1
транспорта SocketChannel, и корень «вечных переверификаций» — незапиненный контракт ответов
сервера. Владелец выбрал скоуп **P0 + контракт + P1-сервер**, старт — **после закрытия
`truth-holes-closure`** (soak, 6.3 = вариант A, закрывающий коммит — сосед-сессия).

Действующие правила: BCTL-ADR-007 («сигнал без доказанного ненуля не подключён»; гоночное/
флаговое — только парой ON/OFF); коммиты с `Refs: plans/backend-ctl-review-remediation.md`,
`Why:`, `Layer:`; live-прогоны строго одиночные. Новые MCP-инструменты НЕ создаются.

**Секвенция с телеметрийными планами: этот план — ДО них.** Причины: (1) телеметрийные фазы
будут приниматься этим инструментом — сначала заточить его; (2) запиновка контракта (Ф2)
удешевляет верификацию самого телеметрийного плана — дрифт форм станет виден на unit-уровне;
(3) переделывать ничего не придётся: «read-model на generic-VM» остаётся за блокером coherence
Task 3.5 (сюда не входит), решение по level-метрикам pull-on-demand записано блокером в том
плане. Gap-детекция (Task 1.3) живёт в ingest драйвера и телеметрийными планами не задевается.

---

## Фаза 0 — Live-подтверждение находок (baseline «до»)

### Task 0.1 — Прогнать чек-лист live-верификации из аудита (7 пунктов)
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Goal:** Каждая ревью-находка получает live-исход до начала фиксов; baseline «до» для пар Фаз 1–3.
**Steps:** собственный harness на свободном 8765, по пунктам раздела «Чек-лист live-верификации»
аудита: (1) reject `full=true` реальным SDK-клиентом; (2) стейл read-model против
`state_get_subtree`; (3) head-of-line при долгой команде; (4) второй клиент → мусор в плоскости
`other`; (5) `queue_senders.lost==0` при `data_evicted>0`; (6) HOL-гипотеза `sendall`;
(7) `lost_responses` бриджа.
**Acceptance criteria:**
- [ ] Все 7 пунктов имеют строку ПОДТВЕРЖДЁН/ОПРОВЕРГНУТ с числами в новом audit-файле
- [ ] Опровергнутые находки вычеркнуты из скоупа задач ниже (урок: «VERIFIED по коду» ≠ live-факт)

---

## Фаза 1 — P0: правда агрегации

### Task 1.1 — `system_overview` читает счётчики потерь
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Files:** `backend_ctl/overview.py:216-237`, `backend_ctl/tests/test_overview.py`
**Goal:** «anomaly_count: 0» при реальных потерях невозможен.
**Steps:** новые виды аномалий `never_drop_loss` / `evict_blocked` / `data_evicted` по образцу
эмиттера `router_dropped`, gated на `_is_positive`; «счётчик отсутствует» уже покрыт `counter_missing`.
**Acceptance criteria:**
- [ ] Пара: подставной ответ с потерями → аномалии в сводке; без потерь → тишина
- [ ] Live: на харнессе со стартовым burst'ом data-очереди `anomaly_count > 0`
- [ ] Ответ остаётся под `RESPONSE_BYTE_CAP`

### Task 1.2 — Контракт `full=true`: подсказка не советует невозможное
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Files:** `backend_ctl/mcp_tools.py` (схемы, `_obj`), `backend_ctl/dispatch.py:275-293`, `backend_ctl/tests/test_response_cap.py`
**Goal:** Совет `_cap_heavy` «передай full=true» исполним для каждого усекаемого инструмента.
**Steps:** всем инструментам вне `_UNCAPPED_TOOLS` добавить `full: _FULL` в схему; конформанс-тест:
для каждого ToolSpec вне `_UNCAPPED_TOOLS` схема декларирует `full` (новые инструменты не воспроизведут дыру).
**Acceptance criteria:**
- [ ] Пара через реальный SDK-путь (jsonschema-валидация): до — `full=true` на `session_log` → validation error (зафиксировано в 0.1); после — проходит и отдаёт полный объём
- [ ] Полный unit-suite зелёный

### Task 1.3 — Детекция разрывов в read-model драйвера
**Level:** Middle+ (Sonnet), ревью Reviewer (Opus) · **Assignee:** developer
**Files:** `backend_ctl/driver.py:1039-1068` (`_ingest_state_changed`), `backend_ctl/events.py` (`iter_state_deltas` — прокинуть `revision`/`first_revision`), `backend_ctl/tests/test_telemetry_driver.py`
**Goal:** Стейл read-model перестаёт быть молчаливым (дыра класса truth-holes у самого инструмента).
**Steps:** зеркало непрерывности GUI (`gui_state_proxy.py:84-118`): трекать `[first_revision, revision]`
по подписке; при разрыве — `gap_count` (+ `last_gap_at`) в `telemetry_snapshot`. Авторесинк через
`state_get_subtree` — только если тривиален, иначе отдельным решением (не раздувать).
**Acceptance criteria:**
- [ ] Пара unit: непрерывные revision → `gap_count=0`; конверт с дыркой → `gap_count=1`
- [ ] Существующие telemetry-тесты зелёные без смысловых правок
- [ ] Live: `gap_count=0` на спокойном харнессе (ненуль-способность доказана unit-плечом)

### Task 1.4 — Атрибуция вытеснений в `queue_senders`
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer: framework**
**Files:** `multiprocess_framework/modules/shared_resources_module/queues/core/manager.py` (`send_to_queue:230-252`, `_count_sender`, `get_sender_stats`), `backend_ctl/protocol.py` (RouterStats), `test_queue_sender_attribution.py`, `test_wrappers.py`
**Goal:** «Кто душит очередь X» отвечает честно и на drop_oldest-очередях (где кадры реально теряются).
**Steps:** новый вид `evicted` (НЕ перегружать `lost` — семантики разные: невозвратная потеря
never-drop vs вытеснение стейла): на пути `remove_old_if_full` атрибутировать отправителя
ВЫТЕСНЕННОГО сообщения; та же lock-free дисциплина. В докстринге `put` зафиксировать «попытки, не enqueue».
**Acceptance criteria:**
- [ ] Пара unit: drop_oldest с вытеснением → `evicted` у отправителя вытесненного груза; never-drop ветка не задета (24 существующих теста зелёные)
- [ ] Live: стартовый burst → `evicted > 0` у реального отправителя (BCTL-ADR-007)

---

## Фаза 2 — Контракт ответов: одна структурная инвестиция

### Task 2.1 — Golden-фикстура форм ответов сервера
**Level:** Senior (Opus) · **Assignee:** teamlead
**Files:** новый `backend_ctl/tests/contract_fixtures.py` (или JSON + загрузчик), генератор в стиле `dump_capabilities.py`; потребители: `tests/conftest.py:34-51`, `test_wrappers.py:31-96`, `test_overview.py`
**Goal:** Одна истина форм ответов вместо N ручных копий; конец классу «probe/fake читает не тот уровень конверта» (3 рецидива).
**Steps:** снять с живого harness формы `introspect.status` / `queues` / `memory` / `router_stats` /
`telemetry` / `supervision.status` / `state.changed`; ручные `_ROUTER_RESP`/`_STATUS_RESP`/`_QUEUES_RESP`/
дубль `ROUTER_COUNTERS` → единый источник; известные отставания фейков закрыть (`pid` в status, `state`-очередь в queues).
**Acceptance criteria:**
- [ ] Unit-фейки кормятся ТОЛЬКО golden-фикстурой (grep ручных дублей пуст)
- [ ] Regen-команда документирована; drift-gate: live-тест сверяет фикстуру с живым ответом
**Out of scope:** переписывание сценарной логики тестов — только источник форм.

### Task 2.2 — Live `missing==[]` расширить с 4 до всех типизированных обёрток
**Level:** Middle (Sonnet) · **Assignee:** developer
**Files:** `backend_ctl/tests/test_wrappers.py:439-489` (паттерн `TestWrappersLive`)
**Steps:** добавить `introspect_memory` (MemoryStats), `introspect_telemetry`, `introspect_status`
(`pid`), `supervision_status` (per-process `alive`/`instance_restarts` — урок парных маркеров).
**Acceptance criteria:**
- [ ] Live-прогон: все обёртки `missing==[]`, 3/3 подряд

### Task 2.3 — Конформанс схем 49 инструментов против dispatch
**Level:** Middle+ (Sonnet), ревью Reviewer (Opus) · **Assignee:** developer
**Files:** новый `backend_ctl/tests/test_schema_conformance.py`; `backend_ctl/mcp_tools.py:517-536` (`system_command`), `backend_ctl/dispatch.py:339` (E.2 preflight)
**Goal:** Схема каждого инструмента соответствует тому, что хендлер реально читает; `system_command` получает контракт.
**Steps:** (а) у всех properties есть `type` (класс бага коэрсии `"0.15"`); (б) required ⊆ properties;
(в) recording-fake фиксирует читаемые хендлером ключи args и диффует со схемой (класс `process` vs
`process_name`); `system_command`: вложенная схема `command{cmd, process_name}` + расширение E.2 preflight.
**Acceptance criteria:**
- [ ] Конформанс-тест зелёный по всем инструментам реестра
- [ ] Пара для `system_command`: опечатка ключа → обучающая ошибка ДО отправки, не таймаут

---

## Фаза 3 — P1-сервер: транспорт SocketChannel

> Все три задачи — **Layer: framework**, файлы `multiprocess_framework/modules/router_module/channels/socket_channel.py` + `adapters/socket_bridge_adapter.py`.
> Приёмка каждой — live-парой («болезнь воспроизведена в 0.1 → исчезла»). Sentrux `session_start` до Фазы → `session_end` после.

### Task 3.1 — Убрать head-of-line: воркер вместо синхронного `router.request` в read-цикле
**Level:** Senior+ (Opus) · **Assignee:** teamlead
**Steps:** `_read_loop`/`on_inbound` (`socket_channel.py:277-323` → `socket_bridge_adapter.py:86`):
per-connection очередь намерений + воркер-поток (паттерн applier из WatchController); read-цикл только читает и кладёт.
**Acceptance criteria:**
- [ ] Пара live: до (0.1 п.3) — `send_command(timeout=60)` + параллельный `state_get` → второй ждёт; после — второй отвечает за обычное время
- [ ] Полный suite router_module зелёный

### Task 3.2 — Изоляция второго клиента
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Steps:** дефолт — «одна дверь»: второй одновременный клиент на канале `backend_ctl` отклоняется
с обучающей ошибкой (single-client инвариант); `session_isolation=True` — только если отклонение
ломает легитимный сценарий (HTTP-мультиплекс уже имеет `require_isolation`).
**Acceptance criteria:**
- [ ] Пара live: до (0.1 п.4) — мусор в плоскости `other` второго драйвера; после — второй клиент получает явный отказ, первый не деградирует

### Task 3.3 — Ограничить блокирующий `sendall` + границы кадров
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Steps:** send-timeout на write-путь клиентских сокетов (осознанно, задокументировать);
max-line-length в обоих `_read_loop` (drop+log вместо безграничного `buf`); байт-кап колец EventHub.
Если 0.1 п.6 опровергает HOL-гипотезу — задача сжимается до max-line + байт-капа.
**Acceptance criteria:**
- [ ] Unit: оверсайз-кадр дропнут с логом, соединение живо
- [ ] Существующие reconnect-live зелёные

---

## Фаза 4 — Гигиена доверия

### Task 4.1 — `record_start`/`record_dump`: честная классификация
**Files:** `backend_ctl/mcp_tools.py:1007,1141-1147,1184`, `backend_ctl/recorder.py:86`, тесты
**Steps:** переклассифицировать в `SAFETY_WRITE` (пишут файлы) ИЛИ read + защита от перезаписи
(`open("x")`/суффикс) + включить в `_AUDITED_SAFETY`. Решение — припиской к BCTL-ADR-002/006.
**Acceptance criteria:**
- [ ] Перезапись существующей записи невозможна молча; вызовы видны в `session_log`
- [ ] `--read-only` режим больше не разрешает запись файлов

### Task 4.2 — Счётчик отказов durable-аудита
**Files:** `backend_ctl/audit.py:162-172`, `backend_ctl/dispatch.py` (`session_log`)
**Steps:** `_append_file` считает неудачи (`file_write_failures`), `session_log` отдаёт счётчик + путь.
**Acceptance criteria:**
- [ ] Пара unit: исправный путь → 0; сломанный каталог → счётчик растёт, запись остаётся в кольце, инструмент не падает

### Task 4.3 — Покрытие `logger_sink_enable/disable` + стейл в тестах
**Files:** `backend_ctl/tests/` (вернуть тесты уровня dispatch; удалить сиротский `__pycache__/test_mcp_server.cpython-312.pyc`), `tests/test_harness.py:7,84` (стейл `queue_type='system'`/«xfail» → текущая истина `state`)
**Acceptance criteria:**
- [ ] Оба инструмента покрыты unit + вызваны в live-смоуке; grep стейла пуст

### Task 4.4 — Эфемерный порт live-фикстуры
**Files:** `backend_ctl/tests/conftest.py` (`headless_backend`), `backend_ctl/harness.py`, `backend_ctl/endpoint_config.py`
**Goal:** Снять вшитую в suite ловушку «двух бэкендов на 8765».
**Steps:** харнесс биндит `:0` → фактический порт пробрасывается драйверу; 8765 — дефолт только ручного запуска.
**Acceptance criteria:**
- [ ] Два параллельных `harness_smoke` не конфликтуют
- [ ] Полный live-suite проходит при занятом 8765
**Примечание порядка:** сделать РАНЬШЕ остальных live-задач — разблокирует работу рядом с живым GUI.

### Task 4.5 — Доки и границы
**Files:** `backend_ctl/STATUS.md` («47»→актуальное число тестом, не глазами), `mcp_tools.py:444-449` (описание `introspect_router_stats` — новые поля `queue_senders`/`queue_never_drop_loss_total`), `README.md` (полный индекс инструментов), `pyproject.toml` + контракт `[tool.importlinter]` (backend_ctl → prototype запрещён, исключения harness/probes; либо аргументированно удалить зависимость), перенос `process_manager_module/tests/test_backend_ctl_endpoint.py` в `backend_ctl/tests/`
**Acceptance criteria:**
- [ ] `lint-imports` зелёный; `python -m scripts.sync` без дрифта
- [ ] Счётчик инструментов в доках совпадает с `len(TOOLS)` (проверка тестом)

---

## Решения записаны — НЕ строим (до реального столкновения / внешнего гейта)

- **Переезд в `tooling/`** — за гейтом codemod `framework-layer-grouping`; при старте codemod заложить carve-out `tooling/` в sentrux + import-linter (иначе 10 файлов красные в день переезда).
- **`GUI_DEFAULT_PATTERNS` деривация из топологии** — по первому расхождению с GUI (сейчас бит-в-бит, `watch.py:30-35`).
- **`telemetry-pull-on-demand`** — при принятии того плана решить путь level-метрик драйвера (poll как GUI или своя подписка) и readback обеих плоскостей каскада. Блокер записан там.
- **Рефактор `_TransportMixin`/`_EventChannelMixin` → композиция** и **вынос telemetry-блока (~320 строк) из фасада** — при следующем росте фасада; вместе с ними снять test-only re-export'ы `driver.py:44,68,70,658-666`.

## Verification (гейт плана)

1. Unit: `python -m pytest backend_ctl -q` зелёный; framework-сьюты задетых модулей (`shared_resources`, `router_module`, `process_module`) зелёные; `python scripts/validate.py` чист.
2. Live (одиночный прогон, свой порт после 4.4): полный live-suite backend_ctl 3/3; MCP-смоук initialize → tools/list → `capabilities` → `system_overview`.
3. Каждая находка Фаз 1–3 закрыта **парой** «болезнь воспроизведена (0.1) → исчезла»; каждый новый сигнал показан ненулевым live (BCTL-ADR-007).
4. Sentrux `session_start` (до Фазы 3) → `session_end` (после) — не хуже baseline.
5. Аудит-файл ревью дополнен исходами; memory-записи об опровергнутых находках (dual-write).

## Порядок и зависимости

```
Ф0 (baseline) → Ф1 (1.1–1.4 параллелимы; 1.4 framework) → Ф2 (2.1 → 2.2, 2.3)
Ф3 после Ф0 (независима от Ф1/Ф2; framework, sentrux-парой)
Ф4 — по касанию; 4.4 раньше остальных live-задач (снимает ловушку порта)
Макс. 2 агента без worktree; правки driver.py/overview.py не параллелить (worktree при одном файле).
```
