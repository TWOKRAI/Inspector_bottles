# Task W2-m: частота источника — по данным, а не по такту цикла

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Module contract:** public-api-change (ключ статуса воркера `data_hz`; смысл `processes.<P>.state.fps` у процесса-источника; `hz` в `system_overview`)
- **Dependencies:** W2-d (тот же `backend_ctl/overview.py`: сливается первым, W2-m — на его базе); с камерой и считывателем файлов не делит
- **Gate:** `machine_gate.sh light <session>` по TESTS; радиус `multiprocess_framework/modules/process_module/tests` — `heavy`, только у лида; `backend_ctl/tests` (medium) — новых красных нет против снимка лида
- **Files:** `multiprocess_framework/modules/process_module/generic/source_producer.py`, `multiprocess_framework/modules/process_module/heartbeat/telemetry.py`, `backend_ctl/overview.py`, `multiprocess_framework/modules/process_module/tests/test_source_data_rate.py`, `backend_ctl/tests/test_overview_source_hz.py`
- **Handoff:** lead -> developer (REDS в брифе: красный прогон до правки src, break-injection) -> reviewer (стадия 5, sonnet)

Основание — стенд 2026-11-25 (`docs/reviews/2026-11-25_stand-wave1.md`, F9, F10, F2), дерево `mco-stand` `ea65a3334`:
- Кабель `camera_1` вынут (14:10:30-14:10:43): `plugins.hikvision.fps=0.0`, `frames` стоит (1621), но `processes.camera_1.state.fps=25.02`, `hz=25`.
- Кабель `reader_1` вынут (ping 0/2): `reader_1 hz=20.01`, а `draw_1 hz=0.05` (данные встали).
- В работе: `processes.camera_0.state.fps=24.99`, `hz=25` при `plugins.hikvision.fps` 4-14.

Причина в коде (проверено чтением):
- `SourceProducer.run_loop` пишет такт в `CycleMetricsRecorder` на КАЖДОЙ итерации, и при `items == []` (`source_producer.py:256-257`); темп держит `FramePacer` (`:254`). Пустой `produce()` для камеры и считывателя — норма (`plugin_base.py:689-690`), поэтому `effective_hz` воркера = частота цикла (`target_fps` 25 / 20), а не данных.
- `build_worker_telemetry` берёт `state.fps` процесса из `effective_hz` воркера пары (`telemetry.py:216-246`, правило пары — докстринг `:140-200`).
- `system_overview`: `hz` процесса — максимум `effective_hz` по воркерам (`backend_ctl/overview.py:55-78`); подсказка `hz_degraded` сравнивает `effective_hz` с целевым темпом — у цикла источника он всегда в норме, подсказки нет.
- Прецедент в том же framework: `DataReceiver` пишет такт только на итерации с сообщением — «иначе effective_hz отражал бы частоту опроса, а не реальный поток данных» (`data_receiver.py:127-131,508-509`).

TASK: W2-m — `SourceProducer` меряет частоту отданных items (`data_hz`); `state.fps` процесса-источника и `hz` обзора берут её, а не такт цикла   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: developer
CHAIN: lead -> you -> reviewer (стадия 5, sonnet)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. `source_producer.py`: второй рекордер `self._data_rate = CycleMetricsRecorder(target_interval_s=0.0)` (тот же класс `cycle_metrics.py`, новой машинерии нет). В `run_loop` после цикла отправки — `self._data_rate.record(0.0)` один раз на каждый отправленный item-dict (маркер `not_inspected` от W2-l — тоже единица данных, считается). `effective_hz` и `cycle_duration_ms` цикла НЕ меняются (их читают сторожа темпа и `pacer_late`).
  2. `get_cycle_metrics()` (`source_producer.py:124-136`): ключ `data_hz` всегда: `effective_hz` рекордера данных (`0.0`, пока items не было; `None` — передаётся как есть). Рекордер даёт `min(темп окна, 1/возраст)` — после потока тишина спадает как `1/возраст`, без нового таймера.
  3. `telemetry.py`: `METRIC_DATA_HZ = declare_metric("data_hz", owner=__name__)`. В `build_worker_telemetry`: у отработавшего воркера с числовым `data_hz` — лист `workers.<w>.data_hz` (гейт `_ok("data_hz")`, число включая 0, NaN/inf -> `None`, как у `effective_hz`); в выборе пары частота такого воркера = `data_hz`, а не `effective_hz`; `latency_ms` — по-прежнему его `cycle_duration_ms`. Воркер без ключа `data_hz` — прежнее правило без изменений.
  4. `backend_ctl/overview.py`, `_process_hz`: ведущий `hz` процесса = максимум по воркерам из `data_hz`, если ключ есть у воркера, иначе `effective_hz`; подсказка `hz_degraded` по-прежнему по `effective_hz` и целевому темпу (идле-камера с аппаратным триггером не становится «деградировавшей»).
  5. Не меняется: `FramePacer`, ветка паузы/гейта работы (`source_producer.py:155-161` — там `record` не зовётся и сейчас), `pacer_late`, `DataReceiver`, `IdleWorker`.

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_framework/modules/process_module/generic/source_producer.py — п.1, 2
  2. multiprocess_framework/modules/process_module/heartbeat/telemetry.py — п.3
  3. backend_ctl/overview.py — п.4
  4. multiprocess_framework/modules/process_module/tests/test_source_data_rate.py — новый
  5. backend_ctl/tests/test_overview_source_hz.py — новый

REDS (predicted red tests; источник — фейк-плагин с `produce()`, `target_fps 25`, цикл в daemon-потоке, `join` с дедлайном):
  - multiprocess_framework/modules/process_module/tests/test_source_data_rate.py::test_empty_produce_gives_zero_data_hz (1,0 с пустого `produce()` -> `data_hz == 0.0`, `effective_hz >= 20.0`)
  - …::test_one_item_per_cycle_data_hz_near_target (1 item на такт 1,5 с -> `20.0 <= data_hz <= 27.0`)
  - …::test_two_items_per_cycle_counts_items (2 item на такт -> `40.0 <= data_hz <= 54.0`, `effective_hz <= 27.0`)
  - …::test_silence_after_data_decays (1,0 с с items, затем 2,0 с пусто -> `data_hz <= 0.5`)
  - …::test_process_fps_follows_data_hz (`build_worker_telemetry({"src": {"status": "running", "effective_hz": 25.0, "data_hz": 0.0, "last_cycle_age_s": 0.04, "cycle_duration_ms": 40.0}}, "camera_1")` -> `state.fps == 0.0`, `workers.src.effective_hz == 25.0`, `workers.src.data_hz == 0.0`)
  - …::test_cable_pulled_wiring (настоящие `SourceProducer` + `build_worker_telemetry` по `get_cycle_metrics()`: 1,0 с items, затем 2,0 с пусто -> `state.fps <= 0.5`)
  - backend_ctl/tests/test_overview_source_hz.py::test_source_hz_is_data_rate (воркер `effective_hz 25.0`, `data_hz 0.0`, целевой 40 мс -> `hz == 0.0`, подсказок `hz_degraded` 0)
  - охранные (зелёные до кода): …::test_worker_without_data_hz_keeps_effective_hz (`state.fps == 25.0`); backend_ctl …::test_receiver_hz_unchanged

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_source_data_rate.py backend_ctl/tests/test_overview_source_hz.py` -> exit 0
  - `<py> -m pytest -q --tb=no -rfE multiprocess_framework/modules/process_module/tests -k "telemetry or source_producer or cycle"` (medium) -> новых красных нет против снимка лида; полный `process_module/tests` (heavy) — лид
  - `ruff check -q` по пяти путям -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_source_data_rate.py backend_ctl/tests/test_overview_source_hz.py   (`<py>` — python основного `.venv`, `PYTHONPATH=<корень worktree>`)

OUT OF SCOPE: `fps` плагина (`plugins.<p>.fps`, уже по данным); GUI-вкладка процессов (`worker_table.py` — читает `effective_hz`, prototype, отдельно); факт `link` и аномалия `source_lost` (W2-a1, W2-b1, W2-d); `DataReceiver` и `PipelineExecutor`; soak-проба.
TRAPS: литералы старых тестов, где `state.fps` источника = такт цикла с пустым `produce()`, станут красными — это ожидаемое изменение смысла: перечислить их в отчёте, не править молча (решение — лид). Пара процесса — воркер с НАИМЕНЬШЕЙ частотой: камера с `data_hz 0` прижмёт `fps` процесса к 0 — так и задумано. Счёт — по item-dict, не по вызовам `produce()` (камера отдаёт пачку из очереди). Аппаратный триггер при стоящей линии честно даёт `fps 0` — это не дефект (Р-W2-10).
HANDOFF IN: W2-d — `backend_ctl/overview.py` после его коммита.
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, список старых литералов, раздел «Что оставил открытым / ненадёжно».

Не установлено: откуда ровно берётся `hz=25` в отчёте стенда (обзор `backend_ctl` или вкладка GUI) — по коду обзор даёт максимум `effective_hz` (`overview.py:55-78`); вкладка GUI (`_panels.py:1125`) не читалась.
