# Task W2-b: считыватель — поток-владелец: тишина видна, прибор возвращается сам, правка триггера не держит системный поток

- **Статус:** [PENDING] · **Level:** Senior · **Assignee:** teamlead
- **Module contract:** impl-only (новые поля регистра и хук `readiness` у `CodeReaderSdkPlugin`; `interface.py` у `code_reader` нет)
- **Dependencies:** волна 1 слита (W1-b: `_on_trigger_update`, `_take`/`_release`, `_trigger_lock`, `_want_grab`)
- **Gate:** `machine_gate.sh light <session>` по файлам TESTS; радиус `Services/code_reader/tests` (medium) против снимка лида
- **Files:** `Services/code_reader/core/sdk_reader.py`, `Services/code_reader/plugin/sdk_plugin.py`, `Services/code_reader/plugin/sdk_registers.py`, `Services/code_reader/tests/test_reader_owner_hazards.py`
- **Acceptance:** блок ACCEPTANCE; файл tester-а зелёный
- **Handoff:** reviewer (стадия 0, opus) -> tester (слепой RED) -> teamlead -> лид (инъекции) -> reviewer (стадия 5, opus)
- **ФАЙЛ TESTER-А (teamlead не правит):** `Services/code_reader/tests/test_reader_link_contract.py`

Основание. Стенд 2026-11-25: кабель считывателя вынут ~80 с — `running`, health ok, errors 0, ноль строк лога; кадры вернулись сами (57 кадр/с), тоже без строки. Код (`mco-d-w1-b`): `E_NODATA` -> `None` -> `consecutive = 0`, `continue` (`sdk_reader.py:375-377`) — ни счётчика, ни лога; после трёх ошибок поток выходит, прибор вернёт только `take_device` (ADR-CR-009). Ревью W1-b: колбэк `_on_trigger_update` зовёт `self._reader.stop()` синхронно в потоке `set_field_value` (системный поток) — до ~4,75 с при бюджете стопа ребёнка 4,0 с. Решение владельца 3 пересматривает ADR-CR-009 (вариант B ADR: свой поток, пауза — поле регистра; триггер возврата записан в ADR).

TASK: W2-b — один поток-владелец жизненного цикла читателя в плагине: применение правок, переподключение, оценка тишины   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: teamlead
CHAIN: reviewer (стадия 0) -> tester (слепой RED) -> you -> лид (инъекции) -> reviewer (стадия 5)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. `sdk_reader.py`: `self._last_frame_mono: float | None = None` — на каждом `raw is not None` (до разбора); `self._nodata` += 1 на каждом `None`; `stats()` += `last_frame_age_s` (`None` до первого кадра, иначе `round(now - last, 3)`) и `nodata`. Других правок нет.
  2. `sdk_registers.py`, поля без `apply`: `reconnect: bool = True`, `link_silence_s: float = 3.0` (`min 0`, `max 60`; 0 — выкл.), `reconnect_interval_s: float = 2.0` (`min 0.5`, `max 60`).
  3. `sdk_plugin.py`, поток-владелец `_owner` (`threading.Thread(daemon=True, name=f"{reader_id}_owner")`), стартует в конце `configure`, ОДИН на плагин (повторный `configure` сначала останавливает прежний). Состояние: `self._cv = threading.Condition()`, `self._pending: dict[str, Any] = {}` (поле -> значение; последнее значение поля выигрывает), `self._owner_stop = threading.Event()`. Цикл: `with self._cv: self._cv.wait(timeout=0.5)`, забрать и очистить `_pending`; затем по порядку: (а) правки — прежнее тело `_on_trigger_update` (поле за полем, под `_trigger_lock`); (б) оценка тишины; (в) переподключение.
  4. `_on_trigger_update(field, value)` (колбэк подписки) только кладёт `_pending[field] = value` под `_cv` и `notify()`; INFO `CodeReaderSdkPlugin[<id>]: apply field=<field> policy=restart queued`. Литералы строк исхода применения W1-b не меняются; они пишутся из потока-владельца.
  5. Тишина (б). «Непрерывный режим» = `_applied_trigger` пуст, или `trigger_mode == "Off"`, или (`trigger_mode == "On"` и `trigger_source == "SelfTrigger"`). При `_want_grab`, состоянии читателя `running`, `link_silence_s > 0`, непрерывном режиме и `age = stats()["last_frame_age_s"]`: (`age is None` и с `take` прошло `>= link_silence_s`) или `age >= link_silence_s` -> `self._link = "lost"`, первый раз за выпадение WARNING `CodeReaderSdkPlugin[<id>]: нет кадров <age:.1f> с, прибор молчит`, `self._outages += 1`, `_publish_state()`. Кадры вернулись -> `_link = "up"`, INFO `CodeReaderSdkPlugin[<id>]: кадры возобновились через <s:.1f> с`, `_last_outage_s = s`. Не непрерывный режим -> `_link = "silent"` без WARNING (аппаратный триггер: тишина — норма).
  6. Переподключение (в). `self._reg.reconnect`, `_want_grab`, состояние читателя `error` (поток вышел) и с прошлой попытки прошло `>= reconnect_interval_s` -> под `_trigger_lock`: `r = self._take()`; `ok` -> INFO `CodeReaderSdkPlugin[<id>]: прибор возвращён, попыток <k>`; иначе счёт попыток, WARNING не чаще раза в 60 с `CodeReaderSdkPlugin[<id>]: прибора нет <s:.0f> с, попыток <k>`. `_want_grab` не трогается (намерение оператора). При `reconnect False` — поведение ADR-CR-009.
  7. `readiness(self, ctx) -> list[dict]` (новый хук; без замков и IO, голые атрибуты): не `_want_grab` -> `[]`; `_link == "lost"` -> `[{"severity": "failure", "reason": "считыватель: нет кадров"}]`; состояние читателя `error` -> `[{"severity": "failure", "reason": "считыватель: ошибка прибора, переподключение" if reconnect else "считыватель: ошибка прибора"}]`; иначе `[]`. Состояние читателя хук берёт из атрибута, который пишет поток-владелец (`self._reader_state`), не из `stats()` (там замок).
  8. Блок `link` в `_snapshot`: `{"state": _link, "outages", "attempts", "last_outage_s", "last_frame_age_s"}`.
  9. `shutdown`: первой строкой `_unsubscribe_trigger()`, затем `_owner_stop.set()`, `notify` под `_cv`, `join(timeout=1.0)`; живой после join поток -> одна ERROR `CodeReaderSdkPlugin[<id>]: поток-владелец не вышел за 1.0 с`; далее прежнее тело под `_trigger_lock`.

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. Services/code_reader/core/sdk_reader.py — `last_frame_age_s`, `nodata`
  2. Services/code_reader/plugin/sdk_plugin.py — поток-владелец, очередь правок, тишина, переподключение, `readiness`, блок `link`
  3. Services/code_reader/plugin/sdk_registers.py — три поля
  4. Services/code_reader/tests/test_reader_owner_hazards.py — новый (REDS 8-10)

REDS (predicted red tests; семь — файл tester-а, `W2-b.tester.md`):
  - Services/code_reader/tests/test_reader_link_contract.py::test_register_update_returns_before_restart_finishes
  - Services/code_reader/tests/test_reader_link_contract.py::test_burst_of_writes_applies_last_value_once
  - Services/code_reader/tests/test_reader_link_contract.py::test_silence_in_free_run_marks_lost_with_warning
  - Services/code_reader/tests/test_reader_link_contract.py::test_silence_in_hardware_trigger_is_not_lost
  - Services/code_reader/tests/test_reader_link_contract.py::test_frames_resume_logs_info_and_clears_readiness
  - Services/code_reader/tests/test_reader_link_contract.py::test_error_state_is_retaken_automatically
  - Services/code_reader/tests/test_reader_link_contract.py::test_reconnect_off_keeps_adr_cr_009
  - Services/code_reader/tests/test_reader_owner_hazards.py::test_shutdown_joins_owner_within_budget (shutdown при идущем применении — меньше 4,0 с)
  - Services/code_reader/tests/test_reader_owner_hazards.py::test_one_owner_after_reconfigure
  - Services/code_reader/tests/test_reader_owner_hazards.py::test_readiness_takes_no_lock (хук отвечает, пока `_trigger_lock` взят другим потоком)

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short Services/code_reader/tests/test_reader_link_contract.py Services/code_reader/tests/test_reader_owner_hazards.py` -> exit 0
  - прежние зелёные W1-b — `<py> -m pytest -q --tb=short Services/code_reader/tests/test_sdk_trigger_live_contract.py Services/code_reader/tests/test_sdk_trigger_live_hazards.py` -> exit 0 (тесты, ждавшие синхронного применения, ждут исхода опросом с дедлайном; правка ЧУЖОГО теста — к лиду)
  - радиус `Services/code_reader/tests` (medium) -> красные = снимок лида; `ruff check -q` по четырём путям -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short Services/code_reader/tests/test_reader_link_contract.py Services/code_reader/tests/test_reader_owner_hazards.py

OUT OF SCOPE: read-back триггера из прибора (T5 шаг 2); TCP-плагин; `backend_ctl`; рецепт.
TRAPS: команды `take_device`/`release_device` остаются синхронными под `_trigger_lock` (явный ответ оператору, стоп ≤ 2,5 с при `timeout_ms 500`) — в поток-владелец уходят только колбэк подписки и переподключение. Тесты W1-b ждали синхронного исхода в потоке записи: если они краснеют — это ожидаемо из-за п.4, но правит их не teamlead, а лид решает (файл слепого tester-а W1-b). `readiness` зовётся ~2 Гц из потока снимка: ни замка, ни `stats()`. Опрос `stats()` берёт замок читателя — только из потока-владельца, не из колбэков читателя.
HANDOFF IN: none
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».
