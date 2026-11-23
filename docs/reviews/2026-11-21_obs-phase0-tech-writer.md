# Фаза 0 observability-signal-contracts: проход tech-writer (ADR и устаревшие тексты)

Дерево `/Users/twokrai/Project_code/Inspector_bottles--lane-N-wdocs`, ветка `refactor/obs-docs` от `984dbf6d0`. Ничего не закоммичено и не застейджено. Код не менялся: в `.py` правки только комментариев, докстрингов и строк описания инструмента MCP.

memory hits: `scripts/memory/search.py ADR DECISIONS tech-writer observability` -> уроков по теме нет (попадания про другие механизмы).

## Новые ADR

| ADR | Файл:строка | Тема |
|---|---|---|
| ADR-PM-063 | `multiprocess_framework/modules/process_module/DECISIONS.md:4490` | `state.fps`/`latency_ms`: пара самой медленной стадии, `None` вместо нуля, без округления, `stopped`/`completed` исключены, `last_cycle_age_s` только при `hz_ok` |
| ADR-CRM-020 | `channel_routing_module/DECISIONS.md:905` | часовой `REFUSED`, `LoggerCore.is_closed`, `_logger_slot_closed()` в окне голоса, пол и `emergency_log`; открытый вариант упрощения |
| ADR-RTR-016 | `router_module/DECISIONS.md:463` | синхронный `send` форвардера до Task 2.4, лог вне `_write_lock`/`_stats_lock`, фиксированные `reason`, без потока-писателя, условие пересмотра |

Коллизии номеров проверены `git grep` по `main` и всем локальным веткам из `git worktree list`: `ADR-PM-063`, `ADR-CRM-020`, `ADR-RTR-016` нигде не заняты. Индекс `multiprocess_framework/DECISIONS.md` обновлён только `python -m scripts.sync` (строки CRM `…019` -> `…020`, RTR `…015` -> `…016`).

## Что изменено по файлам

**process_module**
- `DECISIONS.md:2292` — пометка `**[Устарело 2026-11-21 …]**` на решении «`fps` = `max(effective_hz)`» внутри ADR-PM-038 (принятый в репо способ: инлайн-скобка, как на :2366).
- `DECISIONS.md:4490` — ADR-PM-063.
- `README.md:972` — абзац про `fps` фреймворка (было ~940): смысл числа сменился, отсылка на ADR.
- `README.md:804` — новый подраздел «Скорость и задержка процесса»; `README.md:827` — «Счётчики форвардеров в `introspect.observability`» (в README про `forwarders` не было ничего; описано по `forwarders_plane_report`).

**channel_routing_module**
- `DECISIONS.md:666` — пометка «Устарело» на «возврат `write()` на плоскости tap'ов не судится» (ADR-CRM-016); `DECISIONS.md:892` — пометка на «после 0.1 живых вызывающих нет» (ADR-CRM-019, п.3); `DECISIONS.md:905` — ADR-CRM-020.
- `README.md:384` — абзац про `_emit_to_taps`: возврат судится через `outcome_of`; `README.md:210` — живые вызывающие `count_outcome`.
- `core/channel_routing_manager.py:40` — комментарий над `LOSS_COUNTER_KEYS`: «Пять классов» -> «Семь ключей» (счёт по коду: `unresolved_channel_records`, `channel_write_errors`, `channel_refused_records`, `records_without_channels`, `tap_reentrant_suppressed`, `tap_write_errors`, `tap_refused_records`).
- `observability/store_tap.py:193-201` — докстринг `StoreTapChannel.write`: прежний довод «раздача возврат не читает» ложен после 0.5a; переписан.

**router_module**
- `DECISIONS.md:463` — ADR-RTR-016; `DECISIONS.md:326` и `:354` — пометки «Дополнено» к ADR-RTR-012 (счётчик моста ведёт `count_outcome`; WARNING теперь после выхода из `_write_lock`).
- `README.md:169` — абзац «Исход ответа `send`» (раздел «Отправка»).

**logger_module**
- `README.md:507` — абзац про отказ канала статусом: теперь `channel_refused_records`, `OSError` приёмников (0.4), закрытый логгер (0.6).
- `DECISIONS.md:141` — ADR-LOG-006: `format_exc()` -> `format_exception(exc)` (0.7).
- `core/redaction.py:6` — комментарий в докстринге модуля, то же.

**backend_ctl**
- `AGENTS.md` строки таблицы `set_register_verified` (:116) и `telemetry_snapshot` (:133): поля `verdict`/`vacuous`/`pre`; `class`, `age_s`, `gap_count`, `last_gap_at`.
- `mcp_tools.py` описания `telemetry_snapshot` (~:1387) и `set_register_verified` (:966) — только строки описания (проверка: `test_mcp_server_sdk.py` + `test_mcp_full_and_rules_doc_parity.py`: 74 passed).
- `overview.py:213` — комментарий: «ведущий темп» = `max(effective_hz)`, не `state.fps`.

**прочее**
- `multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py:917-919` — комментарий про ts кольца (время источника; без метки и у `state.uptime` — приёма).
- `telemetry_readmodel_module/DECISIONS.md` — только пункт про `_panels.py` (помечен исправленным). Остальное в README/DECISIONS Task 0.10 сверено с кодом `read_value`/довыставления: ложного не нашёл.

## Проверка

- `python -m scripts.sync` — `[ЗАПИСАНО] multiprocess_framework/DECISIONS.md`.
- `python scripts/validate.py` — «Ошибок нет! Предупреждений нет!».
- `ruff check` на изменённых `.py`: `All checks passed!` для всех, кроме одной строки `backend_ctl/mcp_tools.py:874` (E501, не моя, была до правок).
- `git diff -U0 -- '*.py'`: удалённые/добавленные строки — комментарии, докстринги и строки описания MCP; логика не тронута.
- Все запуски через `machine_gate.sh light tech-writer-wdocs`.

## Что НЕ сделано и почему

- `process_module/heartbeat/process_heartbeat.py` докстринги — по брифу (Task 0.9 на ревью).
- `logger_module/adapters/std_facade.py`, `docs/claude/OPEN_QUESTIONS.md`, `plan.md`, `contract.lock` — по брифу.
- Другие комментарии «пять классов»: `process_module/managers/observability_reload.py:1120`, `statistics_module/core/stats_manager.py:1160`, `statistics_module/observation/observation_manager.py:625`, `logger_module/core/logger_core.py:646` («Четыре класса»). Вне FILES; в них «пять» относится к стыку «менеджер -> канал» без `tap_*` и может быть верным в своём контексте, я не проверял каждый. Не менял.
- `backend_ctl/probes/g7_soak_probe.py:174-179` считает «темп процесса» как `max(effective_hz)` и пропускает ложные значения: теперь число другого смысла, чем `state.fps`. Вне FILES; назван в ADR-PM-063.
- `channel_routing_module/STATUS.md:103` — историческая строка журнала («возврат `write()` не читается»); журнал не правил.
- Стенд (такт heartbeat хаба, `state.fps` через 5 и 30 с после `worker.stop`, `forwarders` при живом подписчике) — не запускал, это не задача tech-writer.

## Расхождения с брифом

- Файл с фактами для ADR (а): в брифе `process_module/core/process_heartbeat.py`; сборка пары живёт в `process_module/heartbeat/telemetry.py` (`build_worker_telemetry`, `_DELIBERATELY_FINAL_STATUSES`), ADR написан по нему.
- `backend_ctl/` лежит в корне репо, не в `multiprocess_framework/`; `_panels.py` — в `multiprocess_prototype/frontend/widgets/tabs/processes/`, не в `frontend_module`.
- Строки брифа `AGENTS.md:116,133` — это `set_register_verified` и `telemetry_snapshot`; в `mcp_tools.py` «965-982» оказалось `set_register_verified`, описание `telemetry_snapshot` — около :1387. Правил оба.
- `backend_ctl/overview.py:212` — комментарий про «ведущий темп»; он не писал, что `state.fps` — максимум, я добавил предупреждение, а не исправил ложь.

## Что я оставил открытым / ненадёжным

- **Фактов о поведении под нагрузкой в ADR нет.** ADR-RTR-016: длительность блокировки такта heartbeat хаба при синхронном `send` не измерена; «до 0.5 с» — это таймаут сокета `SocketChannel` (ADR-RTR-012) и ожидание Opus, не замер. Бюджет такта числом нигде не назван; условие пересмотра записано как «выход за бюджет на стенде».
- **ADR-CRM-020, «снимает 3.1».** В `tasks/3.1.md` связь `REFUSED`/`is_closed` с задачей прямо не названа (задача правит те же `observable_mixin.py`, `logger_core.py`, `interfaces.py`). Я записал это как точку решения для 3.1, а не принятое решение; смысл пометки Opus мог быть другим.
- **ADR-PM-063:** пороги алертов (`process_manager_module/core/alert_rules.py`) на `None` / малые значения не разбирал; `wire_monitor.py` (падение на `float(None)`) взят из отчёта исполнителя 0.8, сам не проверял. Утверждение «десять файлов `process_module/tests` переписаны» — по отчёту 0.8, не пересчитывал.
- **ADR-CRM-020, п.4:** «закрытый логгер другого типа окно голоса не распознает» — вывод из чтения `_logger_slot_closed`, не проверен тестом.
- **README channel_routing / router:** перечень «так отвечают `RecordForwardChannel`, `RouterPushChannel.write`, `StoreTapChannel.write`» перенесён из прежнего текста и кода форвардера; `RouterPushChannel` и `StoreTapChannel` на ответ `error` заново не проверял.
- **Пометки «Устарело» в ADR-CRM-016 и ADR-CRM-019** — инлайн, текст самих решений не переписывал (ADR — запись о моменте решения). Если лид предпочитает отдельный `Superseded`, это правка трёх строк.
- Полный `validate.py` зелёный, но он проверяет структуру `DECISIONS.md`, а не истинность моих утверждений; истинность — только чтение кода и тестов.
