---
name: project_gui_stand_production_entry_only
description: GUI-стенд поднимается только боевой точкой входа + INSPECTOR_GUI_UNATTENDED=1; через BackendHarness процесс gui виснет
metadata:
  node_type: memory
  type: project
  originSessionId: 97ad4179-f790-4535-a14c-f8d1f4e65db7
  modified: 2026-08-11T14:33:57.599Z
---

Правило перенесено в команда `core:quality:observability-acceptance` и `.claude/skills/project-rules/SKILL.md` §5 (2026-10-04).

**Why:** через harness GUI не поднимается — процесс `gui` виснет в
`_init_application_threads`, до `run_gui` не доходит; следствия молчаливые (команды
timeout при живых соседях, очередь данных переполняется `delivery_failed`). Причина не в
сборке топологии: с боевым `build_launcher` через `launcher_factory` виснет так же.
Две дороги подъёма, из которых одна виснет, ломают сравнимость чисел между стендами молча.


**Как за одну строку узнать, Qt-стенд или дренирующий** (добавлено 2026-08-18, S-21):
вход `multiprocess_prototype/run.py` — это вход **бэкенда**, он `INSPECTOR_PRESENTATION` не
выставляет, а `app.yaml` ключа `presentation:` не содержит вовсе → процесс `gui` едет
`HeadlessGuiProcess`, у которого `run_gui` нет как метода. Снаружи это неотличимо от
штатного бута: 8 процессов, живые Гц, команды отвечают, окна нет. Отличать так —

```
grep "Creating process 'gui' from" logs/<прогон>/ProcessManager/system.log | tail -1
```

`…frontend.process.GuiProcess` — окно будет; `…headless_process.HeadlessGuiProcess` — не будет.
Второй отпечаток: воркер `data_drain` в журнале `gui` вместо `data_receiver`. Не искать
причину в Qt, зонде и `QT_MCP_PROBE`, пока эта строка не прочитана: сессия 2026-08-18 сузила
диагноз до `app.py:61` при том, что класс был назван в журнале на каждом прогоне с 11.08
(174 headless-строки против 6 Qt).

Родня: [[feedback_backend_ctl_for_agents]],
[[feedback_modal_dialog_waits_instead_of_failing]], [[project_backend_ctl_framework_module]].
