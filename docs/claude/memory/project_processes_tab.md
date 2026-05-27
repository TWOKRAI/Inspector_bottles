---
name: Processes tab implementation state
description: Вкладка "Процессы" — состояние реализации Phase 1-7b done, все 6 вкладок активны
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

**Phase 1 prototype-skeleton-2026-05 (2026-05-24, ветка feat/processes-protection, коммит c6b9862):**
- ProcessInfo.protected: bool = False, Presenter.is_protected(name)
- 6 topology YAML: gui помечен protected: true (orchestrator вне blueprint)
- Defense in depth — 7 точек: UI (3 не рендерит Stop) + handlers (4 early-return guard): _on_button_action, _on_card_action, _on_toolbar_action(stop_all), AllProcessesPanel, SingleProcessPanel, toolbar buttons
- 9 unit-тестов в TestProtectedProcesses (presenter + tab + panel + toolbar)

**Phase 2 — Discovery + paths (ветка feat/discovery-config-paths, коммит d405e1e):**
- PluginsTab подвкладка «Пути» (`plugin_paths` в `system.yaml`): PluginManager hot-reload из backup
- Config-driven discovery: секция `discovery` в `backend/config/system.yaml`
- `multiprocess_prototype/main.py` + `frontend/app.py` обновлены под config-driven init

**Phase 3 — ServiceRegistry integration (ветка feat/service-registry, коммит 3ed4ec4):**
- ServicesTab: каталог зарегистрированных сервисов + lifecycle start/stop/restart
- ServiceRegistry singleton в framework; 4 сервиса: webcam_camera, sql, hikvision_camera, auth
- Подвкладка «Пути» (`service_paths` в system.yaml)

**Phase 5 — replace_blueprint кнопка (коммит da227903):**
- RecipesTab: кнопка «Запустить активный рецепт» → `ProcessManager.replace_blueprint()`
- Рабочие процессы перезапускаются, GUI и orchestrator живут

**Phase 7a/7b — Pipeline tab (коммиты 935c2b49, 4a3b0b28):**
- PipelineTab полностью функционален: DisplayNodeItem, target_process binding, WireStatus telemetry
- Демо-рецепт `demo_webcam_split_merge.yaml` запускается штатно

**Ключевые файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/` — 8 файлов (widget, tree, model, bridge, control_panel, create_dialog, constants, schemas)
- `multiprocess_prototype/registers/commands/routing.py` — process.command + process.* targets
- `multiprocess_prototype/registers/commands/catalog.py` — builders
- `multiprocess_prototype/frontend/commands/gui_command_handler.py` — публичный send() метод
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` — handlers data=None/**kwargs pattern
- `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py` — full broadcast, created status, crash isolation

**Why:** GUI routing через "process.command" wrapper: RoutedCommandSender шлёт command="process.command", data={cmd: "process.create", ...}, ProcessManager._handle_process_command ловит и диспатчит.

**Статус:** Phase 1–7b завершены (2026-05-27). Все 6 вкладок активны: Процессы, Плагины, Сервисы, Дисплеи, Рецепты, Pipeline.
