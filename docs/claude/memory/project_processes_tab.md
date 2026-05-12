---
name: Processes tab implementation state
description: Вкладка "Процессы" — текущее состояние реализации, Phase 1-3 done, Phase 4+ pending
type: project
originSessionId: 892f4f9e-8065-4888-926c-7cfdb4ab3dca
---
Вкладка "Процессы" для GUI — мониторинг и управление процессами системы.

**Реализовано (2026-04-28):**
- Phase 1: ProcessMonitorModel + ProcessTreeView(BaseEditorTreeView) + ProcessDataBridge (singleton, push + fallback poll)
- Phase 1.1: GuiProcess polls system channel, ProcessMonitor periodic full broadcast (_broadcast_full_status every ~10s)
- Phase 2: ProcessControlPanel с Start/Stop/Restart + confirmation + debounce 2s
- Phase 3: CreateProcessDialog + кнопки "Создать"/"Удалить", process.command wrapper format
- Bug fixes: command routing через "process.command" wrapper (не прямой command_id), handlers принимают data=dict|**kwargs, crash isolation (не роняет систему), "created" status для нестартованных процессов

**Ключевые файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/` — 8 файлов (widget, tree, model, bridge, control_panel, create_dialog, constants, schemas)
- `multiprocess_prototype/registers/commands/routing.py` — process.command + process.* targets
- `multiprocess_prototype/registers/commands/catalog.py` — builders
- `multiprocess_prototype/frontend/commands/gui_command_handler.py` — публичный send() метод
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` — handlers data=None/**kwargs pattern
- `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py` — full broadcast, created status, crash isolation

**Why:** GUI routing через "process.command" wrapper: RoutedCommandSender шлёт command="process.command", data={cmd: "process.create", ...}, ProcessManager._handle_process_command ловит и диспатчит.

**How to apply:** Для следующих фаз (пауза, воркеры) нужно расширять heartbeat-протокол + фреймворк. Workers info должен включаться в broadcast от ProcessMonitor.
