---
name: project-pipeline-live-control-stage2
description: Этап 2 GUI-мост live field-write DONE; worker-side блокер — плагины без register_schema
metadata:
  type: project
---

Этап 2 `plans/2026-05-31_pipeline-live-control/phase-2.md` (переписан под видение владельца: live-параметры по адресу процесс→плагин через RouterManager; scope params-first, ноды → Этап 3; «воркер» в адресе = процесс-исполнитель). Ветка feat/pipeline-live-control.

**GUI-мост DONE (commit 81326a8c):** `resolve_plugin_register(topology, process, plugin_index)→plugin_name` (frontend/bridge/plugin_register_resolver.py, 8 тестов). `app.py::_on_plugin_config_changed` резолвит плагин + шлёт `register_update` IPC через CommandSender→RouterManager (НЕ через мёртвый FrontendRegistersBridge — он в v3 не инстанцируется, send_callback=None). GUI rm.set_value теперь по plugin_name, не process_name (корректно для multi-plugin). Проверено qt-mcp live: listener+резолвер верны, IPC уходит.

**Корневой блокер (worker-side, для Этапа 2.x):** live-параметры архитектурно НЕ поддержаны плагинами region_pipeline. Эмпирически `schema loaded`=0 во всех процессах → плагины (resize и др.) не отдают `register_schema()` → `PluginOrchestrator._boot_registers` не вызван → handler `register_update` НИГДЕ не зарегистрирован → IPC доходит до очереди, но приёмника нет (тихо отбрасывается, без ошибки). Плюс `ResizePlugin.configure()` кэширует `self._scale_factor` — `process()` не перечитывает. Поля inspector берутся из @register_plugin/config-схемы (отображение) → ложное ощущение «живого» параметра.

Чтобы live реально применялся: плагин (а) отдаёт `register_schema()` (появится приёмник) и (б) перечитывает значение в `process()`, не кэширует в configure(). Generic worker-side контракт во фреймворке; эталон — resize.

qt-mcp заметка: ноды Pipeline кликаются по **viewport** GraphView (QWidget-ребёнок), не по самой QGraphicsView. Связано: [[project-pipeline-live-control-stage1]], [[project-transport-router-hub]], [[project-backend-control-mcp]].
