# minimal_app — референс-приложение на фреймворке (Ф5.11–Ф5.13)

Второй потребитель фреймворка (после `multiprocess_prototype`) и **forcing function**
против Inspector-специфики в «универсальном» `app_module`. Приложение = данные +
декларации + ~3 строки bootstrap; ни камеры, ни GUI, ни прототипа.

```
minimal_app/
  app.yaml                            # манифест: name/version + pipeline + discovery-пути
  pipeline.yaml                       # 2 процесса на базовом GenericProcess + IPC между ними
  plugins/tick_source/plugin.py       # генератор тика: лог + send_message получателю
  plugins/console_consumer/plugin.py  # приёмник тика: считает полученные сообщения
  services/echo_service/service.yaml  # маркер сервиса (авто-скан находит по нему)
  run.py                              # run_app(app.yaml)
  tests/test_ci_smoke.py              # headless boot + доказанный IPC (harness_smoke)
```

## Запуск

```bash
python examples/minimal_app/run.py
```

Стартуют два headless-процесса:

- **`ticker`** — плагин `tick_source`: раз в секунду логирует счётчик и отправляет
  межпроцессное сообщение `console_sink`;
- **`console_sink`** — плагин `console_consumer`: принимает сообщение, увеличивает
  счётчик приёма, логирует.

Остановка — Ctrl+C (штатный shutdown лончера).

## Своё приложение: пошагово

Это исполняемая документация «сделай второе приложение на фреймворке» —
`minimal_app` проходит все шаги сам:

1. **Манифест** (`app.yaml`) — имя, версия, путь к pipeline, папки для авто-скана.
2. **Топология** (`pipeline.yaml`) — список процессов на framework-классе
   `GenericProcess`, у каждого свои плагины с конфигом.
3. **Плагины** (`plugins/<name>/plugin.py`) — `@register_plugin(...)` +
   `ProcessModulePlugin` с `configure/start/shutdown`. Авто-скан находит их по
   файлу `plugin.py` в папке из `discovery.plugin_paths`.
4. **Сервисы** (`services/<name>/service.yaml`) — маркер-файл, авто-скан находит
   каталог по его присутствию (симметрично `plugin.py` для плагинов). В
   `minimal_app` сервис **намеренно без кода** — это осознанный остаток, не
   пробел: реальный код сервиса (клиент/адаптер к внешней системе, наподобие
   `Services/sql`/`Services/hikvision`) — прикладной уровень, из которого
   framework ничего не резолвит; `service.yaml` доказывает только сам факт
   авто-обнаружения каталога-сервиса. Придумывать generic-механизм загрузки
   произвольного сервисного кода — вне объёма `app_module` (framework не знает
   про Services/Plugins, см. `.sentrux/rules.toml`).
5. **Bootstrap** (`run.py`) — `run_app(Path(__file__).parent / "app.yaml")`, три
   строки без прикладной логики.

## Живой IPC между процессами (Ф5.13)

Ревью Ф5.11 отметило, что каркас с `wires: []` доказывал только boot, а не
реальную межпроцессную доставку. `tick_source` теперь шлёт каждый тик через
`ctx.send_message("console_sink", {...})`, `console_consumer` принимает его через
`ctx.router_manager.register_message_handler("tick", handler)` — тот же канонический
путь, что документирован в `multiprocess_framework/docs/AGENT_CHEATSHEET.md` (Dict at
Boundary, ADR-008).

**Формат сообщения — `type="event"` + явный `queue_type="system"` + payload под
`data`** (не `type="system"`/`"command"` — это зарезервированный control-plane kind
ProcessManager/heartbeat, и не смешивать прикладное событие с ним). Это ТОТ ЖЕ
конверт-формат, что у двух прод-прецедентов прикладных событий фреймворка:
`state.changed` (`state_store_module/manager/delta_dispatcher.py`) и
`observability.record` (`channel_routing_module/observability/record_forward_channel.py`).

**Почему `queue_type="system"` — это выбор физической очереди, а не control-plane
kind:** `RouterManager._select_queue_type` уважает явный `queue_type` в первую
очередь; без него `type in ("command", "system")` тоже кладёт сообщение в
"system"-очередь. "system"-очередь — единственная, которую **всегда** опрашивает
фоновый `SystemThreads`-поток процесса (`message_processor`), независимо от того,
есть ли у процесса processing-плагины. Обычная "data"-очередь (куда попало бы
сообщение без явного `queue_type`, будь его `type` прикладным) опрашивается
`DataReceiver`, а он создаётся `GenericProcess` только когда у процесса есть хотя бы
один processing-плагин (`generic_process.py: _init_data_pipeline`) — для чистого
consumer-плагина без такого пайплайна сообщение осело бы в очереди недоставленным.
`type="event"` при этом честно метит сообщение как прикладное — важно для будущих
QoS-профилей по kind (Ф7 G.4: `system`-kind = never-drop, `event`-kind получит
собственный профиль; смешивать прикладной тик с control-plane kind было бы
неотличимо для QoS).

**`wires: []` в `pipeline.yaml` остаётся пуст осознанно** — это не пробел: формат
`wires:` в topology-схеме (`process_manager_module/topology/blueprint.py`) —
типизированный data-plane граф кадров/изображений через SHM, избыточный для
простого dict-сообщения между headless-плагинами. Framework даёт для этого
отдельный канонический путь `send_message`/`register_message_handler` (см. выше).

## Что доказывает

- «Рыба» бутится **на framework-дефолтах** (`GenericProcess` + generic-оркестратор
  `GenericProcessManagerApp`, Ф5.12), без импортов прототипа;
- авто-скан `app_module.discover` находит **И оба плагина** (`plugin.py`), **И
  сервис** (маркер `service.yaml`) из папок, объявленных в `app.yaml`;
- **реальный межпроцессный IPC**: сообщение от `ticker` доходит до `console_sink` —
  проверяется live-тестом (см. ниже);
- баннер старта — из `manifest.name`;
- `examples/*` НЕ импортирует `multiprocess_prototype` (sentrux-boundary +
  grep-контракт-тест, `multiprocess_framework/modules/app_module/tests/test_contract.py`).

## CI-smoke

`tests/test_ci_smoke.py` — headless boot через `backend_ctl.harness.BackendHarness`
(тот же паттерн, что `backend_ctl/tests/test_health_live.py`): поднимает
`minimal_app` реальными ОС-процессами (без GUI, без железа), подключает
`BackendDriver` и опрашивает `console_sink.consumer_status`, пока счётчик приёма
не станет > 0 — это и есть доказательство доставки. Помечен
`@pytest.mark.harness_smoke` (тот же маркер, что у остальных live-тестов
`backend_ctl`) — не входит в дефолтный сбор pytest (`testpaths` в
корневом `pyproject.toml`), гоняется отдельным CI-job'ом
`examples-smoke` в `.github/workflows/ci.yml`:

```bash
python -m pytest examples/minimal_app/tests -m harness_smoke -q
```

Лёгкая (non-live) проверка самодостаточности каркаса — `build_app`/discovery/
названия процессов — в
`multiprocess_framework/modules/app_module/tests/test_minimal_app_smoke.py`
(гоняется обычным `scripts/run_framework_tests.py`, без спавна ОС-процессов через
harness).
