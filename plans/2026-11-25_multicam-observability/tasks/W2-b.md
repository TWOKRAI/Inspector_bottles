# Task W2-b: считыватель — поток-владелец; живая правка триггера не держит системный поток [часть 1 из 2]

- **Статус:** [PENDING] · **Level:** Senior · **Assignee:** teamlead
- **Module contract:** impl-only (`CodeReaderSdkPlugin`: колбэк подписки ставит правку в очередь; `interface.py` у `code_reader` нет)
- **Dependencies:** волна 1 слита (`mco-integ`, W1-b); часть 2 — W2-b1 на той же ветке сразу после
- **Gate:** `machine_gate.sh light <session>` по TESTS; радиус `Services/code_reader/tests` (medium) — новых красных нет против `baseline-red.md` (раздел волны 2)
- **Files:** `Services/code_reader/plugin/sdk_plugin.py`, `Services/code_reader/tests/test_sdk_trigger_live_hazards.py`, `Services/code_reader/tests/test_reader_owner_hazards.py`
- **Acceptance:** блок ACCEPTANCE; тесты части 1 файла tester-а зелёные
- **Handoff:** reviewer (стадия 0, opus) -> tester (слепой RED, один файл на W2-b и W2-b1) -> teamlead -> лид (инъекции) -> reviewer (стадия 5, opus)
- **ФАЙЛ TESTER-А (teamlead не правит):** `Services/code_reader/tests/test_reader_link_contract.py`

Основание: ревью W1-b — `_on_trigger_update` зовёт `self._reader.stop()` синхронно в потоке `set_field_value` (системный поток процесса): до ~4,75 с при бюджете стопа ребёнка 4,0 с. Разделено с W2-b1 (тишина, переподключение, готовность): вместе 8 файлов при пределе 6.

TASK: W2-b — один поток-владелец жизненного цикла читателя; колбэк подписки только ставит правку в очередь   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: teamlead
CHAIN: reviewer (стадия 0) -> tester (слепой RED) -> you -> лид (инъекции) -> reviewer (стадия 5)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. Поток-владелец. `configure` сначала останавливает прежнего владельца (`_stop_owner()`), затем в конце создаёт новые `stop = threading.Event()`, `cv = threading.Condition()`, `self._pending: dict[str, Any] = {}` и `threading.Thread(target=self._owner_main, args=(stop, cv), daemon=True, name=f"{reader_id}_owner")`; поток получает СВОИ `stop` и `cv` аргументами. `_stop_owner()` безопасен после половины `configure` (атрибутов может не быть — `getattr(..., None)`).
  2. Цикл `_owner_main(stop, cv)`: `with cv: cv.wait_for(lambda: bool(self._pending) or stop.is_set(), timeout=0.5)`; `stop.is_set()` -> выход. Затем шаги (в W2-b — только «правки»; W2-b1 добавит «тишину» и «переподключение»), КАЖДЫЙ в `try/except Exception`: ERROR `CodeReaderSdkPlugin[<id>]: поток-владелец: <ИмяТипа>` не чаще раза в 60 с, цикл продолжается. Перед каждым шагом, перед каждым `_take()` и `_fall_back` — проверка `stop.is_set()`.
  3. Колбэк `_on_trigger_update(field, value)`: первой строкой `if self._closed: return` (без очереди и лога); иначе под `cv` (ТОЛЬКО `cv`) `self._pending[field] = value`, `cv.notify()`, INFO `CodeReaderSdkPlugin[<id>]: queued field=<field> policy=restart` (литерал не начинается с `apply field=` — подсчёты строк W1-b не ломаются).
  4. Порядок замков `_trigger_lock -> cv`. Очередь забирается только под `_trigger_lock`: `_take_pending()` = `with cv: batch = dict(self._pending); self._pending.clear()`. Помощник `_apply_pending_locked()` (зовётся под `_trigger_lock`): забрать очередь и применить её ОДНИМ применением: `new = self._trigger_from({**{f: getattr(self._reg, f) for f in _TRIGGER_FIELDS}, **batch})`; `changed` = поля, где `new` отличается от `self._applied_trigger`. `new == self._applied_trigger` -> на КАЖДОЕ поле очереди INFO W1-b `... restarted=False: значение не изменило режим`. Иначе прежняя логика W1-b (`held` / не `held`, стоп, `set_trigger`, `_take`, откат) один раз на пакет; откат — если отказал узел поля из `changed` или появился отказ, которого не было до пакета (`param_errors` до/после). Итоговая строка исхода W1-b (литералы не меняются) — по одной на каждое поле очереди, с общим исходом.
  5. `cmd_take_device` и `cmd_release_device` под `_trigger_lock` сначала зовут `_apply_pending_locked()` (очередь не обгоняется командой), затем прежнее тело.
  6. `shutdown`: `self._closed = True` (колбэки отбрасываются), `_unsubscribe_trigger()`, `_stop_owner()` (`stop.set()`, `notify` под `cv`, `join(timeout=1.0)`; живой поток -> ERROR `CodeReaderSdkPlugin[<id>]: поток-владелец не вышел за 1.0 с`), затем прежнее тело под `_trigger_lock`. Почему 1,0 с: бюджет стопа ребёнка 4,0 с, стоп читателя — до 2,5 с (`timeout 2.0 + timeout_ms 500`).
  7. Чужие тесты, разрешение лида: в `tests/test_sdk_trigger_live_hazards.py` (автор — developer W1-b) правятся ТОЛЬКО строки `:208`, `:334`, `:399`, `:418`, `:459-465`, `:475-479` и тест `test_shutdown_waits_for_inflight_callback` (там `opens() == 2`) — синхронное ожидание исхода заменяется опросом с дедлайном 5 с; смысл утверждений не меняется. Слепой файл W1-b `tests/test_sdk_trigger_live_contract.py` правит только лид: краснеет из-за асинхронности -> стоп и отчёт лиду.
  8. Обязательные тесты опасности (файл 3 FILES; в REDS — 3-6): `test_shutdown_budget_with_slow_stop_and_refusal` (фейк: `stop_grabbing` задержан на 1,5 с, отказ узла `TriggerMode`; правка поставлена, сразу `shutdown` -> меньше 4,0 с, поток-владелец мёртв), `test_one_owner_after_reconfigure` (счёт потоков по имени `<reader_id>_owner`: ровно 1), `test_owner_survives_step_exception` (`stats()` бросает один раз -> следующая правка применяется), `test_take_device_applies_queue_first`, `test_callback_after_close_is_dropped`, `test_batch_rollback_on_changed_field_refusal`.

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. Services/code_reader/plugin/sdk_plugin.py — п.1-6
  2. Services/code_reader/tests/test_sdk_trigger_live_hazards.py — только строки п.7
  3. Services/code_reader/tests/test_reader_owner_hazards.py — новый, п.8

REDS (predicted red tests; 1-2 — файл tester-а `W2-b.tester.md`):
  - Services/code_reader/tests/test_reader_link_contract.py::test_register_update_returns_before_restart_finishes
  - Services/code_reader/tests/test_reader_link_contract.py::test_burst_of_writes_is_one_application
  - Services/code_reader/tests/test_reader_owner_hazards.py::test_shutdown_budget_with_slow_stop_and_refusal
  - Services/code_reader/tests/test_reader_owner_hazards.py::test_one_owner_after_reconfigure
  - Services/code_reader/tests/test_reader_owner_hazards.py::test_owner_survives_step_exception
  - Services/code_reader/tests/test_reader_owner_hazards.py::test_take_device_applies_queue_first

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short Services/code_reader/tests/test_reader_owner_hazards.py Services/code_reader/tests/test_reader_link_contract.py -k "returns_before or burst"` -> exit 0
  - прежние W1-b — `<py> -m pytest -q --tb=short Services/code_reader/tests/test_sdk_trigger_live_contract.py Services/code_reader/tests/test_sdk_trigger_live_hazards.py` -> exit 0 (красный слепого файла — к лиду, п.7)
  - радиус `Services/code_reader/tests` (medium) -> новых красных нет; `ruff check -q` по трём путям -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short Services/code_reader/tests/test_reader_owner_hazards.py

OUT OF SCOPE: тишина, переподключение, `readiness`, поля регистра (W2-b1); read-back (T5 шаг 2); TCP-плагин; README — `tech-writer` после слияния пары.
TRAPS: команды `take_device`/`release_device` ждут `_trigger_lock` за применением (до ~2,5 с стопа + открытие) — известный предел, они синхронны намеренно. Колбэк подписки не берёт `_trigger_lock` (иначе системный поток снова ждёт). Литералы исхода W1-b не меняются.
HANDOFF IN: none
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».
