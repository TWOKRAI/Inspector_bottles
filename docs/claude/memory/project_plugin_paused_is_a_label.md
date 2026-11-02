---
name: project_plugin_paused_is_a_label
description: "PluginState.PAUSED — ярлык, не гейт: PluginRunner.call_process проверяет только plugin.enabled, плагин в PAUSED получает process() как в RUNNING; пауза режет поток только после Task 1.9 system-run-state / PAUSED plugin still receives process(), pause is a label not a gate"
module: [process_module]
mechanism: [lifecycle]
metadata:
  type: project
---

Предпосылка «плагин в `PAUSED` не получает кадры» ложна. Чтение (cto, 2026-11-02, план system-run-state, Task 0.1): `generic/plugin_runner.py:152-180` `call_process` ветвится только по `plugin.enabled` (bypass); `plugin_operation_step.py:83` и `pipeline_executor.py:153,199` состояние плагина не смотрят; единственная проверка `state` в data-plane — `generic_process.py:185`, для источников при сборке pipeline. `_do_pause` (`plugins/base.py:1628`) меняет ярлык и больше ничего; живых вызывающих `_do_pause/_do_resume` до этого плана нет.

**Why:** план проектировался на вере, что пауза = «не обрабатывает»; на ней стояли превью в `ready` (В2) и лист `paused: true`, подтверждающий STOP. Без проверки в раннере `paused: true` — ложь.

**How to apply:** любой план, где «paused» должен значить «не обрабатывает», добавляет проверку в `PluginRunner.call_process` (system-run-state Task 1.9) и доказывает её тестом «плагин в `PAUSED`, кадр на вход, счётчик `process()` = 0». Сначала проверять факт чтением раннера, а не `plugins/*.py`; отсутствие ветки в одном месте не доказывает отсутствия резки в другом. См. [[project_state_topology_gate]].
