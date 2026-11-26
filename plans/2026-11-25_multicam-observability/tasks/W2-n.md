# Task W2-n: исход применения поля прибором — отказ возвращает регистр и делает «проверенную запись» ложной

- **Статус:** [PENDING] · **Level:** Senior+ · **Assignee:** teamlead
- **Module contract:** public-api-change (`RegistersManager`: `subscribe(..., reports_result=)`, `report_apply_result`, `last_apply`; ответ `register_update` +`apply`; команда `register_apply_status`; `set_register_verified` ждёт исход)
- **Dependencies:** W2-b, W2-b1 (тот же `Services/code_reader/plugin/sdk_plugin.py`: применение уже в потоке-владельце, очередь «последнее значение»); `plugin_orchestrator.py` делит с W2-j — кто слит первым, второй на его базе; `manager.py` и `backend_ctl/registers.py` — ни с кем
- **Gate:** `machine_gate.sh light <session>` по TESTS; радиусы `registers_module/tests`, `Services/code_reader/tests`, `backend_ctl/tests` (medium) против снимка лида; `process_module/tests` (heavy) — лид
- **Files:** `multiprocess_framework/modules/registers_module/core/manager.py`, `multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py`, `backend_ctl/registers.py`, `Services/code_reader/plugin/sdk_plugin.py`, `multiprocess_framework/modules/process_module/tests/test_register_apply_result.py`, `backend_ctl/tests/test_verified_apply_wait.py`
- **Handoff:** lead -> teamlead (REDS в брифе: красный прогон до правки src, break-injection) -> reviewer (стадия 5, opus: гонка двух потоков на регистре)

Основание — стенд 2026-11-25, проверка 4 (`docs/reviews/2026-11-25_stand-wave1.md`, F7), `reader_2` (`.11`): прибор принимает `TriggerSelfTriggerPeriod` от 32; запись 10 -> `0x80020102`, `applied=False fallback=old ok=True`, health `degraded` — прибор работает на 80. При этом `set_register_verified(10)` -> `verdict=confirmed, success=true, post=10`, `introspect_registers` = 10. Отказ виден только в `last_error` и журнале.

Причина в коде (проверено чтением `mco-stand` `ea65a3334`):
- `RegistersManager.set_field_value` пишет значение в регистр ДО подписчиков (`manager.py:207-211`), зовёт их (`:223`) и всегда отвечает `(True, None)` (`:240`). `_notify_observers` (`:258-269`) возвращаемое значение колбэка не читает, исключение глотает в WARNING. Канала «прибор не принял» у подписчика нет — для любого плагина.
- `_on_register_update` отвечает `success True` при `(True, None)` (`plugin_orchestrator.py:879-885`).
- Считыватель при отказе откатывает прибор (`sdk_plugin.py:504-515`: `_fall_back(old)`, `_mark_apply_failed`), регистр не трогает: в нём остаётся 10.
- `set_register_verified` судит по ack и образу регистра до/после (`backend_ctl/registers.py:154-202`, `judge` — `backend_ctl/verdict.py:54-99`: ack-отказ -> `failed`, `post != target` -> `failed`). При `success True` и `post == 10` — `confirmed`.
- Синхронное вето не годится: W2-b делает применение асинхронным (REDS W2-b `test_register_update_returns_before_restart_finishes`), перезапуск на стенде ~3,2 с. Исход приходит ПОСЛЕ ответа `register_update`, поэтому нужен отложенный исход, а не код возврата колбэка.

TASK: W2-n — подписчик поля сообщает исход применения; отказ возвращает в регистр значение, на котором работает прибор; `register_update` говорит «ждёт исхода», `set_register_verified` ждёт его и при отказе отвечает `failed`   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: teamlead
CHAIN: lead -> you -> reviewer (стадия 5, opus)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. `manager.py`, `subscribe(register_name, field_name, callback, *, reports_result: bool = False)`: признак хранится рядом с колбэком. `set_field_value`: если у поля есть хоть один подписчик с `reports_result` — под новым `self._apply_lock` (`threading.Lock`) после успешного `apply_values`: `self._apply_seq += 1`, `self._apply_state[(r, f)] = {"seq": seq, "status": "pending", "reason": None, "attempted": value}` (`value` — сохранённое, нормализованное, `:221`). Колбэки, `send_callback` и журнал — ВНЕ `_apply_lock` (колбэк вправе сообщить исход синхронно). Сигнатура и ответ `set_field_value` не меняются (на них опирается W2-i).
  2. `report_apply_result(register_name, field_name, *, attempted, status: Literal["applied", "refused", "deferred"], in_effect=None, reason: str | None = None) -> bool`: под `_apply_lock`: запись `pending` поля есть и её `attempted == attempted` -> исход принят (`status`, `reason`), иначе — устаревший исход: `False`, DEBUG, регистр не трогается (новая запись уже легла поверх). `refused` и `getattr(reg, f) == attempted` -> `reg.apply_values({f: in_effect})` (отказ `apply_values` -> ERROR, `False`). После замка, только при откате: WARNING `registers: <r>.<f> не применено прибором, регистр возвращён (<reason>)` (значений в строке нет, ADR-RM-007), глобальные наблюдатели и `send_callback` с возвращённым значением — тем же кодом, что `:224-239` (вынести помощник); ПОЛЕВЫЕ наблюдатели НЕ зовутся (иначе новое применение). Зовётся из любого потока.
  3. `last_apply(register_name, field_name) -> dict | None`: копия `{"seq", "status", "reason"}` без `attempted`; поле без отчитывающегося подписчика -> `None`.
  4. `plugin_orchestrator.py`: успешный ответ `_on_register_update` получает `"apply": rm.last_apply(r, f)`, если не `None` (прежние ключи не меняются). Новый обработчик `register_apply_status` (`data {register, field}`) -> `{"success": True, "register", "field", "apply": rm.last_apply(...)}`; регистрация — рядом с `register_update` (искать по символу `_on_register_update`).
  5. `backend_ctl/registers.py`, `set_register_verified(..., apply_timeout_s: float = 10.0)`: ack с `apply.status == "pending"` -> опрос `register_apply_status` тем же путём отправки, раз в 0,2 с, пока `seq` тот же и статус `pending`, не дольше `apply_timeout_s`. `refused` -> ack для `judge` = `{**ack, "success": False, "error": f"прибор не принял: {reason}"}` (правило 1 -> `failed`); истёк срок -> то же с `error "исход применения не пришёл за <t:g> с"`; `applied`/`deferred` -> ack как есть. Образ `post` читается ПОСЛЕ исхода. В ответ — ключ `apply_status` (`None | applied | refused | deferred | timeout`). `judge` не меняется.
  6. `sdk_plugin.py` (база после W2-b1): подписка `_subscribe_trigger` — `reports_result=True`. Исход пакета (`_apply_pending_locked`) — по одному `report_apply_result(self.name, field, attempted=<значение из пакета>, ...)` на каждое поле пакета: принят -> `applied`; откат -> `refused`, `in_effect` = значение поля в прежнем `_applied_trigger`, `reason` = `f"узел {node} отказал"` или `"захват не остановился в срок"`; захват не идёт (значение войдёт в следующий `take_device`) -> `deferred`; исключение -> `refused`, `reason` = имя типа. `_mark_apply_failed`, health, журнал W1-b — без изменений.
  7. Не меняется: статическое вето (`readonly`, уровень доступа, `manager.py:202`), «всё или ничего» `apply_values`, поля без отчитывающегося подписчика (ответ `register_update` бит в бит прежний).

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_framework/modules/registers_module/core/manager.py — п.1-3
  2. multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py — п.4
  3. backend_ctl/registers.py — п.5
  4. Services/code_reader/plugin/sdk_plugin.py — п.6
  5. multiprocess_framework/modules/process_module/tests/test_register_apply_result.py — новый (менеджер + оркестратор)
  6. backend_ctl/tests/test_verified_apply_wait.py — новый (ожидание исхода + проводка со считывателем)

REDS (predicted red tests; регистр теста `R(SchemaBase)` с полем `period: int = 80`, имя `"r"`):
  - multiprocess_framework/modules/process_module/tests/test_register_apply_result.py::test_refused_outcome_restores_register_without_reapply (подписчик `reports_result=True`; `set_field_value("r","period",10)` -> `(True, None)`, `last_apply == {"seq": 1, "status": "pending", "reason": None}`; `report_apply_result(..., attempted=10, status="refused", in_effect=80, reason="узел отказал")` -> `True`, `period == 80`, колбэк вызван ровно 1 раз со значением 10, `last_apply["status"] == "refused"`)
  - …::test_stale_outcome_keeps_newer_value (запись 10, запись 20, исход `refused` для 10 -> `False`, `period == 20`, `last_apply == {"seq": 2, "status": "pending", "reason": None}`)
  - …::test_applied_outcome_keeps_value (`period == 10`, статус `applied`)
  - …::test_revert_reaches_global_observer_and_send_callback (глобальный наблюдатель получил `("r", "period", 80)` после отказа; `send_callback` — значение 80)
  - …::test_outcome_from_owner_thread_during_new_write (исход из второго потока, запись 20 в основном; 200 повторов -> никогда `period == 80` после записи 20)
  - …::test_register_update_reply_carries_pending (настоящий `PluginOrchestrator`: ответ `success True`, `apply == {"seq": 1, "status": "pending", "reason": None}`)
  - …::test_register_apply_status_reports_refused (`register_apply_status` после отказа -> `apply.status == "refused"`, `apply.reason == "узел отказал"`)
  - backend_ctl/tests/test_verified_apply_wait.py::test_verified_fails_on_refused_apply (фейк-транспорт: ack `pending`, третий опрос `refused`, образ после = 80 -> `verdict == "failed"`, `success is False`, `apply_status == "refused"`)
  - …::test_verified_apply_timeout_fails (`pending` всегда, `apply_timeout_s 0.6` -> `verdict == "failed"`, `apply_status == "timeout"`, длительность < 1,5 с)
  - …::test_reader_period_refusal_end_to_end (настоящие `RegistersManager` + `PluginOrchestrator` + `CodeReaderSdkPlugin` на `FakeNodeApi`, отказ узла `TriggerSelfTriggerPeriod` на 10; захват идёт с 80 -> `verdict == "failed"`, регистр `trigger_period_ms == 80`)
  - охранный (зелёный до кода): …/test_register_apply_result.py::test_field_without_reporting_subscriber_unchanged (ответ `register_update` без ключа `apply`)

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_register_apply_result.py backend_ctl/tests/test_verified_apply_wait.py` -> exit 0
  - радиусы `multiprocess_framework/modules/registers_module/tests`, `Services/code_reader/tests`, `backend_ctl/tests` (medium, `--tb=no -rfE`) -> новых красных нет против снимка лида
  - `ruff check -q` по шести путям -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_register_apply_result.py backend_ctl/tests/test_verified_apply_wait.py   (`<py>` — python основного `.venv`, `PYTHONPATH=<корень worktree>`)

OUT OF SCOPE: камера (`Services/camera_device/plugin_base.py`, отказы `param_errors` живой правки) — отдельная задача W2-n1 (текст не написан) по тому же протоколу, после W2-a1: в этой задаче 6 файлов при пределе брифа 6; показ отказа в инспекторе GUI (prototype; GUI сегодня увидит возвращённое значение регистра при следующем чтении); read-back значения из прибора (T5 шаг 2); `set_config` (W2-i — получит учёт исхода сам, он идёт через `set_field_value`).
TRAPS: колбэк поля зовётся в потоке вызывающего `set_field_value`; исход приходит из потока-владельца — оба пишут регистр: сравнение `attempted` и откат — под одним `_apply_lock`, наблюдатели — вне его (иначе взаимная блокировка с синхронным исходом). Устаревший исход НЕ откатывает новую запись (REDS 2, 5). Ответ `register_update` для полей без отчитывающегося подписчика не меняется ни ключом. Как отправлять команду из `backend_ctl/registers.py` — тем же путём, что `register_update` в этом методе; нельзя связать проводку в одном процессе — стоп и вопрос лиду, тест 10 переносится в `Services/code_reader/tests` без `backend_ctl`.
HANDOFF IN: W2-b1 — `_apply_pending_locked`, поток-владелец считывателя.
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».

Выбор лида без слова владельца (сказать владельцу): срок ожидания исхода 10 с (перезапуск захвата на стенде 3,2 с, худший расчёт W1-b 4,75 с); истёк срок — `failed`, а не `unverifiable`; `deferred` (захват не идёт) — вердикт по регистру, как сегодня, с `apply_status "deferred"`.
