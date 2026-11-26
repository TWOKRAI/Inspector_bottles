# W1-b — бриф tester

Спавн: `python scripts/plans_ledger.py brief W1-b.tester --plan plans/2026-11-25_multicam-observability`. Worktree на коммите ДО реализации; код реализации закрыт.

TASK: W1-b — слепые приёмочные тесты живой записи триггера считывателя (RED до кода)   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: tester
CHAIN: лид (бриф, стадия 0) -> tester -> developer (делает тесты зелёными) -> лид (инъекции, ревью)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. КОНТРАКТ: поля `trigger_mode`, `trigger_source`, `trigger_period_ms` регистра `CodeReaderSdkRegisters` (`Services.code_reader.plugin.sdk_registers`) — `apply == "restart"` (`get_all_fields_meta()[<поле>].apply`). `CodeReaderSdkPlugin` подписан на них: запись при идущем захвате -> стоп, новый режим, захват снова; без захвата — режим войдёт в следующий `take_device`; то же значение -> перезапуска нет. Отказ узла прибора при перезапуске — не «применено». Неудачный перезапуск -> прежний режим и попытка взять прибор снова. `SdkCodeReader.set_trigger(trigger)` (`Services.code_reader.core.sdk_reader`) при живом потоке захвата бросает `RuntimeError("режим съёмки меняется только при остановленном захвате")`.
  2. Строки лога: префикс `CodeReaderSdkPlugin[<reader_id>]: apply field=<field> policy=restart`, хвосты: ` restarted=True applied=True`; ` restarted=True applied=False param_errors=<узел: текст> fallback=old ok=<True|False>` (после отказа узла — откат на прежний режим); ` restarted=False error=<текст> fallback=old ok=<True|False>`; ` restarted=False: захват не идёт, значение войдёт в следующий take_device`; ` restarted=False: значение не изменило режим`.
  3. Настоящие объекты: `RegistersManager` + `PluginOrchestrator._on_register_update` по образцу `Services/camera_device/tests/test_live_apply_wiring.py` (менеджер подставляется оркестратору как `_registers_manager` и плагину как `ctx.registers`). Фейк прибора — `FakeNodeApi` и отказ узла — хелпер `_refused(...)` из `Services/code_reader/tests/test_sdk_trigger.py` (импорт как там); читатель — через `reader_factory` плагина с `api=<FakeNodeApi>` по образцу того же файла. Сообщение: `{"data": {"register": <имя>, "field": <поле>, "value": <значение>}}`. `reader_id "id_a"`.
  4. Импорты `CodeReaderSdkPlugin`, `SdkCodeReader`, `CodeReaderSdkRegisters` — внутри теста. Ожидание с дедлайном; зависающий вызов — в daemon-потоке с `join(timeout)`. Новый `.py`: `__all__ = []`, `Purpose:`.
  5. Сценарии:
     - `test_trigger_fields_declare_apply_restart`: у трёх полей `"restart"`; у `timeout_ms` — не `"restart"`.
     - `test_live_write_while_grabbing_restarts_and_reaches_device`: `auto_start True`, триггер пуст, захват идёт; `register_update trigger_mode "On"` -> ответ `success True`; в журнале фейка второе открытие и запись `TriggerMode` = `"On"` после него; `stats()["device_held"] True`; ровно одна INFO `CodeReaderSdkPlugin[id_a]: apply field=trigger_mode policy=restart restarted=True applied=True`.
     - `test_refused_node_write_is_not_reported_as_applied`: триггер в конфиге пуст, захват идёт (открытие 1); фейк отказывает в `set_enum_str` узла `TriggerMode` (`_refused`); `register_update trigger_mode "On"` -> перезапуск (открытие 2), откат на прежний режим (открытие 3); всего открытий 3; одна ERROR, начинающаяся `CodeReaderSdkPlugin[id_a]: apply field=trigger_mode policy=restart restarted=True applied=False param_errors=TriggerMode: ` и оканчивающаяся ` fallback=old ok=True`; событие `last_error` == `trigger apply: field=trigger_mode applied=False`; INFO `applied=True` нет.
     - `test_return_to_old_value_after_node_refusal_keeps_reader_on_old_mode`: продолжение предыдущего сценария; `register_update trigger_mode ""` -> новых открытий нет (открытий 3), INFO `... restarted=False: значение не изменило режим`; затем `release_device` и `take_device` -> открытие 4, после него НЕТ записи узла `TriggerMode` (читатель держит прежний режим, а не `"On"`).
     - `test_failed_restart_falls_back_to_old_trigger`: фейк отказывает во ВТОРОМ открытии и разрешает третье -> одна ERROR, начинающаяся `CodeReaderSdkPlugin[id_a]: apply field=trigger_mode policy=restart restarted=False error=` и оканчивающаяся ` fallback=old ok=True`; открытий 3; `last_error` == `trigger apply: field=trigger_mode restarted=False; прежний режим идёт`.
     - `test_same_value_does_not_restart`: конфиг `trigger_mode "On"`, захват идёт; `register_update trigger_mode "On"` -> новых открытий 0; INFO `CodeReaderSdkPlugin[id_a]: apply field=trigger_mode policy=restart restarted=False: значение не изменило режим`.
     - `test_live_write_while_stopped_applies_on_next_take`: `auto_start False`; `register_update trigger_source "SelfTrigger"` -> открытий 0; команда `take_device` -> `TriggerSource` записан `"SelfTrigger"`.
     - `test_set_trigger_refused_while_running`: идущий `SdkCodeReader` -> `set_trigger({"trigger_mode": "On"})` бросает `RuntimeError` с текстом п.1; после `stop()` не бросает.
     - `test_shutdown_unsubscribes`: после `shutdown` `register_update trigger_mode "Off"` -> новых открытий 0.

FORBIDDEN PATHS (no edits, no reads of implementation): Services/code_reader/plugin/sdk_registers.py, Services/code_reader/plugin/sdk_plugin.py, Services/code_reader/core/sdk_reader.py, Services/code_reader/tests/test_sdk_trigger_live_hazards.py, plans/2026-11-25_multicam-observability/tasks/W1-b.md, docs/reviews/2026-11-25_obs-audit-multicam.md, docs/reviews/2026-11-25_obs-audit-multicam-2-control-tasks.md, docs/reviews/2026-11-25_obs-audit-multicam-3-reliability-cto-map.md
FILES (complete list — nothing else; need another file -> stop and report):
  1. Services/code_reader/tests/test_sdk_trigger_live_contract.py — new

REDS (expected RED before code):
  - Services/code_reader/tests/test_sdk_trigger_live_contract.py::test_trigger_fields_declare_apply_restart
  - Services/code_reader/tests/test_sdk_trigger_live_contract.py::test_live_write_while_grabbing_restarts_and_reaches_device
  - Services/code_reader/tests/test_sdk_trigger_live_contract.py::test_refused_node_write_is_not_reported_as_applied
  - Services/code_reader/tests/test_sdk_trigger_live_contract.py::test_return_to_old_value_after_node_refusal_keeps_reader_on_old_mode
  - Services/code_reader/tests/test_sdk_trigger_live_contract.py::test_failed_restart_falls_back_to_old_trigger
  - Services/code_reader/tests/test_sdk_trigger_live_contract.py::test_same_value_does_not_restart
  - Services/code_reader/tests/test_sdk_trigger_live_contract.py::test_live_write_while_stopped_applies_on_next_take
  - Services/code_reader/tests/test_sdk_trigger_live_contract.py::test_set_trigger_refused_while_running
  - Services/code_reader/tests/test_sdk_trigger_live_contract.py::test_shutdown_unsubscribes

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short Services/code_reader/tests/test_sdk_trigger_live_contract.py

OUT OF SCOPE: read-back в state (шаг 2), TCP-плагин, существующие тесты пакета.
REPORT: STATUS (DONE|BLOCKED), files, число собранных и красных; RED падает внутри теста (утверждение или `AttributeError`), не на сборе. Записи отказов `FakeNodeApi.fail` статичны (`test_sdk_trigger.py:129`): для «отказать во втором открытии, разрешить третье» напишите подкласс `FakeNodeApi` со счётчиком открытий в СВОЁМ файле `test_sdk_trigger_live_contract.py`; `test_sdk_trigger.py` не правится.
