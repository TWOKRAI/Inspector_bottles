# Вердикт CTO по эскалации Task 4.3 (2026-09-23)

База `60c1fe6c`. Эскалация `investigator` → `cto` через ведущего: разведка дизайна 4.3 упёрлась
в два вопроса, без ответа на которые RED-тесты были бы пустыми. Все выводы ниже CTO проверил
запуском, скрипты воспроизведения лежали в scratchpad сессии. Живой стенд при этом не поднимался.

## Q1 — стадия «audit»: вариант (a), стадий пять

`validate → layer → apply → verify → reply`. Отдельной стадии «audit» нет, аудит уже пишут два
существующих писателя:

- каждая мутация слоя пишет себя сама — 6 мест в `configs/observability_layers.py`;
- исход apply пишет `_rebuild_and_apply` записью `rebuild` с `ok/error`
  (`observability_reload.py:1521/1524`, для телеметрии `:1957/1962`).

Почему отвергнуты другие варианты:
- **(b)**, третья запись с вердиктом verify, была бы дублем ответа.
- **(c)**, вынос писателя в стадию, заглушил бы 9 вызывающих мутаций слоёв вне `config.reload`:
  `orchestrator.py:328`, `process_manager_process.py:2420/2433`, `process_module.py:497` и другие.

Воспроизведение, reload с `log_level=DEBUG`:
- в кольце аудита `[touch ok=True, rebuild ok=True]`, `verified=confirmed checked=1`;
- если `reconfigure` бросает `RuntimeError`, в кольце `[touch ok=True, rebuild ok=False]`, а L3
  остаётся `DEBUG` при effective `INFO`.

Кольцо честное. Отката слоя нет, это довесок к 4.3, а не её условие: расхождение видно в
introspect как `layers ≠ effective`.

## Q2 — область протокола: вариант (a), четыре плоскости

Счётчики форвардера — отдельная задача **4.3b**. Их нет ни в 4.3, ни в otel 3.4.

Подтверждено:
- в `RecordForwardChannel` нет ни одного счётчика;
- batch-канал живёт в замыкании `observability_wiring.py:279-283` и нигде не зарегистрирован;
- `_emit_to_taps` засчитывает `{"status":"dropped"}` как «принят» (CRM:1096);
- в `introspect.observability(full)` нет строк `observability_forward` и нет секции `forwarders`,
  в снимке стенда otel `tools/otel_stand/samples/1f40ce0d/` их тоже нет;
- `queue_observability_evicted` — счётчик очереди по типу, а не по подписчику
  (`router_manager.py:1775`), и его уже читает `introspect.router_stats`.

Новый счётчик внутри 4.3 означал бы смену поведения внутри рефакторинга, который по условию
поведение не меняет.

## Q3 — `flare` на стороне драйвера

Файл `backend_ctl/flare.py` делает веер вызовов `introspect.observability`, прецедент —
`overview.py` / `driver.system_overview`. К этому добавляется одна строка `fw_version` в
`introspect.observability`; `code_version()` кэшируется на процесс, так что строка ничего не стоит.

Размер бандла по снимку одного процесса — 20.2 КБ, из них `provenance` 9.9 КБ. На 20 процессах
бандл с `provenance` вышел бы около 400 КБ. Поэтому `provenance` отдаётся только по флагу.

## Поправленные критерии 4.3 (заменяют критерии 2–3 карточки)

- `_cmd_config_reload` ≤ 80 строк; `run_config_reload(svc, req, *, stages=CONFIG_RELOAD_STAGES)`,
  стадии заданы литеральным кортежем `("validate","layer","apply","verify","reply")`.
- Инвариант: за один reload кольцо получает `[<мутации…>, rebuild]`, и
  `rebuild.ok == reply.success`.
- Перестановка layer↔apply делает тест красным по двум признакам: по порядку кольца и по
  `verified.verdict` на ключе `log_level`. На ключе с `unverifiable` перестановка осталась бы
  зелёной.
- `layers.lock` охватывает layer и apply одним блоком. Тест 5.8 «ключ не воскресает в зазоре»
  добавить, либо назвать место незащищённым.
- `flare` на процесс отдаёт `fw_version` + `layers` + `counters` + `audit[-N:]` + `effective`,
  `provenance` — по флагу. Потолок ≤ 12 КБ на процесс без `provenance`, замер числом на 8
  процессах.
- Оракул команд зелёный: `_HANDLER_SOURCES` и `_commands_registered_by`
  (`test_command_contract_oracle.py:252`) ищут по всем файлам-источникам.
- Порядок частей: A протокол → B стадии → C распил хендлера → D `flare`.
  - B идёт до C, иначе 786 строк переезжают дважды.
  - D независима от остальных.
- Замечание для teamlead: `counters()` в CRM с `PLANE_COUNTER_KEYS` вносит в базовый класс ключи
  кардинальности StatsManager. Чище, когда база несёт общие ключи loss/delivery, а ключи плоскости
  добавляет override.

## Что в вердикте ненадёжно

- Харнесс Q1 собран с одним LoggerManager, без телеметрийной записи `rebuild`.
- Тест 5.8 искали по имени; он может существовать под другим именем.
- «9 вызывающих» посчитаны грепом.
- Размер `flare` — экстраполяция одного снимка (camera_0).
- Живого стенда не было.
