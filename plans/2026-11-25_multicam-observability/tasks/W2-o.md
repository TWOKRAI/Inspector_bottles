# Task W2-o: выброс кадров приёмником виден в здоровье, а не только строкой ERROR

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Module contract:** public-api-change (`DataReceiver.__init__`: `health`, `lag_degraded_ratio`; поле `GenericProcessConfig.chain_lag_degraded_ratio`)
- **Dependencies:** нет (файлов ни с одной задачей волны 2 не делит; `generic_process.py`, `data_receiver.py`, `generic_process_config.py` в FILES других задач отсутствуют)
- **Блокер (мягкий):** Р-W2-13 — считать ли выброс у узла отображения деградацией по умолчанию; до ответа делается с умолчанием лида `0.1`
- **Gate:** `machine_gate.sh light <session>` по TESTS; радиус `multiprocess_framework/modules/process_module/tests` (heavy) — только лид; по исполнителю — `-k "receiver or lag or generic_process"` (medium) против снимка лида
- **Files:** `multiprocess_framework/modules/process_module/generic/data_receiver.py`, `multiprocess_framework/modules/process_module/generic/generic_process.py`, `multiprocess_framework/modules/process_module/generic/generic_process_config.py`, `multiprocess_framework/modules/process_module/tests/test_receiver_lag_health.py`
- **Handoff:** lead -> developer (REDS в брифе: красный прогон до правки src, break-injection) -> reviewer (стадия 5, sonnet)

Основание — стенд 2026-11-25 (`docs/reviews/2026-11-25_stand-wave1.md`, F4, F8), дерево `mco-stand` `ea65a3334`:
- `draw_1`: ERROR `DataReceiver: исполнитель не успевает` (всего 284 к 14:05:17; `draw_2` — 7), в `observability.db` `kind=error` у `draw_1` 45 строк. `health=ok`, в `anomalies` ничего.
- `introspect_router_stats` (`dropped=0, queue_data_evicted=0`) и `introspect_observability.counters` (потери 0) выброса не показывают; по отчёту «в state только `fps`/`latency_ms`».

Причина в коде (проверено чтением):
- Выброс делает потолок отставания `_bound_lag` (`data_receiver.py:231-306`, только при `chain_max_lag_items > 0`); голос — `_note_lag_drops` (`:362-377`): одна строка ERROR раз в 5 с. Здоровья у `DataReceiver` нет: в конструкторе (`:59-75`) нет параметра `health`, в файле нет ни одного обращения к здоровью. `GenericProcess` строит приёмник без здоровья (`generic_process.py:276-290`), а `SourceProducer` — с `HealthReporter(health_state, source=...)` (`:354`).
- Аномалия `health_degraded` в `system_overview` уже есть и работает (стенд: `reader_2` при отказе узла). Значит, достаточно заявки `degraded` — обзор менять не нужно.
- Счётчик ЕСТЬ: `lag_dropped_items` в `get_cycle_metrics()` при `max_lag_items > 0` (`data_receiver.py:168-169`), суммируется в `processes.<P>.state.lag_dropped_items` (`telemetry.py:72-75,214-221`), гейт по умолчанию включён (`telemetry_publish_config.py:130-182`, `default_enabled=True`). Почему стенд его не увидел — НЕ установлено (гейт рецепта, место чтения или другой путь): в REDS охранный тест проводки, на стенде — чтение `state_get_subtree processes.draw_1.state`.
- `router_stats` и `observability.counters` и не должны его показывать: это счётчики транспорта, выброс идёт после транспорта, в очереди исполнителя.

TASK: W2-o — приёмник ведёт окно «выброшено из принятых кадров» и заявляет `degraded` своего владельца при доле выше порога; снимает заявку в чистом окне   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: developer
CHAIN: lead -> you -> reviewer (стадия 5, sonnet)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. `DataReceiver.__init__`: именованные `health: IHealthReporter | None = None` (протокол `health/state.py:119`), `lag_degraded_ratio: float = 0.0` (`0` — заявок нет, прежнее поведение). Окно — тот же `self._lag_log_window` (5 с) и те же часы `self._clock`.
  2. Учёт окна (поток приёмника, замков не прибавляется): в `on_items_ready` для кадровой коллекции (`self._is_frame_collection(items)`, при `self._max_lag_items > 0`) — `self._win_frames += len(items)`; в `_bound_lag` рядом с `self._lag_dropped_items += len(victim)` (`:277`) — `self._win_dropped += len(victim)`.
  3. `_eval_lag_window(now)`: зовётся в конце `on_items_ready` и из периодической ветки `run_loop` (`:443-446`, раз в ~0,1 с — снимает заявку и без трафика). `health is None` или `lag_degraded_ratio <= 0` -> выход. `now - self._win_t0 < self._lag_log_window` -> выход. Иначе `seen = max(self._win_frames, self._win_dropped)`; `ratio = self._win_dropped / seen` (`seen == 0` -> 0). `ratio >= lag_degraded_ratio` и заявки нет -> `health.degraded("DataReceiver: исполнитель не успевает — кадры выбрасываются")`, `self._lag_claim = True`; `ratio < lag_degraded_ratio` и заявка есть -> `health.ok()`, `self._lag_claim = False`. Окно обнуляется: `_win_t0 = now`, `_win_frames = _win_dropped = 0`. Причина — постоянный литерал (числа живут в счётчике и строке ERROR): иначе каждое окно меняло бы причину и писало строку `[health]`.
  4. `generic_process.py`: `health_state = get_or_create_health_state(self)` до постройки приёмника (функция идемпотентна, `health/state.py:713`); `DataReceiver(..., health=HealthReporter(health_state, source="data_receiver"), lag_degraded_ratio=<поле>)`. Владелец заявки `data_receiver` отделён от плагинов и источников (ADR-PM-058, заявки по владельцу, `health/state.py:423-470`): заявка приёмника не снимается чужим `ok`.
  5. `generic_process_config.py`: `chain_lag_degraded_ratio: float = 0.1` рядом с `chain_max_lag_items` (`:189-200`); FieldMeta «Порог деградации по выбросу кадров», `min=0.0`, `max=1.0`, info: доля кадров, выброшенных потолком отставания за 5 с, при которой здоровье процесса `degraded`; `0` — без заявки; в рецепте — `extras.chain_lag_degraded_ratio`. Читается тем же путём, что `chain_max_lag_items`.
  6. Не меняется: литерал и окно строки ERROR `_note_lag_drops`, режимы `latest`/`every`, маркеры `lag`, `lag_dropped_items`, `lag_dropped_total`, блокирующая дорога `put` (`:402-424`).

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_framework/modules/process_module/generic/data_receiver.py — п.1-3
  2. multiprocess_framework/modules/process_module/generic/generic_process.py — п.4
  3. multiprocess_framework/modules/process_module/generic/generic_process_config.py — п.5
  4. multiprocess_framework/modules/process_module/tests/test_receiver_lag_health.py — новый

REDS (predicted red tests; `queue.Queue(maxsize=8)` без потребителя, `max_lag_items 2`, часы — подставные; здоровье — настоящие `HealthState` + `HealthReporter(state, source="data_receiver")`, как в тестах `health/`):
  - multiprocess_framework/modules/process_module/tests/test_receiver_lag_health.py::test_drops_over_ratio_degrade (20 кадровых коллекций за окно, выброшено 18; часы +5,1 с -> статус `degraded`, причина `DataReceiver: исполнитель не успевает — кадры выбрасываются`)
  - …::test_drops_below_ratio_stay_ok (`lag_degraded_ratio 0.95`, выброшено 18 из 20 -> `ok`)
  - …::test_clean_window_clears_claim (после окна `degraded` — окно без выброса -> `ok`)
  - …::test_claim_cleared_without_traffic (`run_loop` в daemon-потоке, `receive` всегда `None`, часы +5,1 с -> `ok` не позже 0,5 с; `join` с дедлайном)
  - …::test_two_degraded_windows_one_health_line (две подряд деградации -> ровно одна строка `[health] status → degraded`)
  - …::test_zero_ratio_makes_no_claim (`lag_degraded_ratio 0.0`, выброшено 18 из 20 -> `ok`, заявок 0)
  - …::test_other_owner_ok_keeps_receiver_claim (`HealthReporter(state, source="plugin_x").ok()` после заявки приёмника -> `degraded`)
  - …::test_config_default_ratio (`GenericProcessConfig().chain_lag_degraded_ratio == 0.1`)
  - охранный (ожидается зелёным до кода; красный — находка лиду): …::test_lag_dropped_items_reaches_process_state (`build_worker_telemetry({"rx": {"status": "running", **receiver.get_cycle_metrics()}}, "draw_1")` после 3 выброшенных items -> `state.lag_dropped_items == 3`)

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_receiver_lag_health.py` -> exit 0
  - `<py> -m pytest -q --tb=no -rfE multiprocess_framework/modules/process_module/tests -k "receiver or lag or generic_process"` (medium) -> новых красных нет против снимка лида
  - `ruff check -q` по четырём путям -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_receiver_lag_health.py   (`<py>` — python основного `.venv`, `PYTHONPATH=<корень worktree>`)

OUT OF SCOPE: почему `draw_1` не успевает (мощность, 47-59 кадр/с от `reader_1` в свободном режиме — рецепт и стенд); `errors.log` пуст при `kind=error` в базе (план ошибок без `proc_name`); счётчики `PipelineExecutor` (`stale_exec`) и двери SHM; аномалия в `backend_ctl/overview.py` (её даёт `health_degraded`); уровень строки ERROR (литерал W1 держат тесты).
TRAPS: `on_items_ready` зовётся и из `ItemCollector.check_timeouts` — тот же поток приёмника, но проверить на базе, что учёт окна не попадает под `chain.mutex` (`_bound_lag`: `+=` внутри `with chain.mutex` — допустимо, это поле приёмника). Блокирующая дорога `put` (`:402-424`) может держать поток до освобождения очереди: окно тогда судится после выхода из неё — это не потеря заявки. Конструктор `HealthState` — по образцу существующих тестов `health/`, не выдумывать.
HANDOFF IN: none
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, итог охранного теста, раздел «Что оставил открытым / ненадёжно».

Решение владельца Р-W2-13: выброс кадров узлом отображения (`draw_*`, политика `latest` + потолок) — деградация процесса по умолчанию (`0.1`, предложение лида: узел не тянет поток — факт мощности, оператор его видит) или только у узлов инспекции (`0` по умолчанию, рецепт включает на нужных узлах).
