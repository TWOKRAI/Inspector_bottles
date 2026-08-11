---
name: project_gui_stand_production_entry_only
description: GUI-стенд поднимается только боевой точкой входа + INSPECTOR_GUI_UNATTENDED=1; через BackendHarness процесс gui виснет
metadata:
  node_type: memory
  type: project
  originSessionId: 97ad4179-f790-4535-a14c-f8d1f4e65db7
  modified: 2026-08-11T14:33:57.599Z
---

Решение владельца 2026-08-11: живые замеры и приёмки поднимать **с настоящими окнами**
(headless занижает нагрузку в разы — строки 40–53 КБ против ~1900 байт), и подъём у
GUI-стенда ровно **один**:

```
BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/<прогон> \
    .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py
```

Зонды **подключаются** драйвером к поднятому стенду (`probe_gui_stand_live`), а не
поднимают свой. `BackendHarness` остаётся headless-стендом для тестов.

**Why:** через harness GUI не поднимается — процесс `gui` виснет в
`_init_application_threads`, до `run_gui` не доходит; следствия молчаливые (команды
timeout при живых соседях, очередь данных переполняется `delivery_failed`). Причина не в
сборке топологии: с боевым `build_launcher` через `launcher_factory` виснет так же.
Две дороги подъёма, из которых одна виснет, ломают сравнимость чисел между стендами молча.

**How to apply:** нужен GUI-прогон — поднимай боевой командой и подключайся; не пытайся
научить harness. `INSPECTOR_GUI_UNATTENDED=1` обязателен: без него прогон встаёт на вопросе
«сохранить несохранённые правки графа?» (модалка ждёт клика). Режим — `frontend/unattended.py`:
названный вопрос получает ответ «не сохранять» до показа окна, прочие модалки закрывает
сторож с записью в лог.

Родня: [[feedback_diagnose_live_system_with_backend_ctl]],
[[feedback_modal_dialog_waits_instead_of_failing]], [[project_backend_ctl_framework_module]].
