---
name: project-observability-control-plane
description: observability-control-plane plan DONE — единая секция observability + hot-reload watcher в оркестраторе + sink-фабрики + ADR-CRM-006
metadata:
  type: project
---

План `plans/2026-06-03_observability-control-plane/` **ЗАВЕРШЁН** (2026-06-05, Phase 1-4):

- **Phase 1** (`d63bae62`, влит ранее): `reconfigure(config: dict)` на CRM через хук `_rebuild_from_config` (Logger/Error/Stats — все три переопределяют ХУК, не сам reconfigure; база CRM оркестрирует flush→close→rebuild) + `invalidate_decision_cache` в Logger.
- **Phase 2** (`6e6cf15f`): реестр sink-фабрик — `register_sink_factory(type, cls)` / `get_registered_sink_types()` поверх `create_channel` (`logger_module/channels/log_channel.py`, `_SINK_FACTORIES`).
- **Phase 3** (`6a85dc33`+`a1dbe976`+`675d91e7`): `ObservabilityConfig` фасад + `expand_observability(dict)→{logger,error,stats}` (`process_module/configs/observability_config.py`); секция `observability` в `system.yaml` → overlay в managers процессов (launch.py); hot-reload `ConfigFileWatcher` в оркестраторе (`process_module/managers/observability_reload.py`, вызов из `ProcessManagerProcessApp.initialize/shutdown`).
- **Phase 4** (`8348d303`): ADR-CRM-006 (channel_routing_module/DECISIONS.md) — 5 точек расширения (SQLChannel/SocketChannel/IPC config.reload/GUI/remote-stats) с якорями, design-only.

**Ключевые решения (для будущих итераций):**
- Watcher живёт в **оркестраторе** (Option B, решение владельца) — forward-compatible с Phase 4 IPC `config.reload`: watcher остаётся в PM, дети получат IPC-хендлер, **нет выбрасываемого кода**. В Iteration 1 hot-reload только менеджеров PM.
- Использован `on_reload`-callback ConfigFileWatcher'а вместо `Config.subscribe` → снята неоднозначность `Config._notify("*")`.
- **Премисса плана «ErrorManager не создаётся» устарела:** `managers_from_log_dir` уже даёт полный набор (logger/error/stats/router/command/console); секция observability — лишь overlay пользовательских значений.
- `expand_observability` НЕ эмитит `log_directory=None` (иначе overlay затёр бы резолвнутый абсолютный путь). console/file тогглы переиспуют дефолтные каналы `LoggerManagerConfig` (сохранён scopes/per-module граф).
- Добавлена зависимость **watchdog>=4.0** (pyproject + uv.lock `133d9d11`) — `ConfigFileWatcher` был написан под неё, но не подключён.

**Verify:** framework 3219 passed; прод qt-smoke FPS 21.0 baseline + стабилен после live-правки `system.yaml` log_level (reconfigure живого логгера в потоке watchdog не ломает систему). Запуск с probe — `QT_MCP_PROBE=1`.

Связано: [[feedback-logger-error-stats-managers]], [[feedback-no-shm-hacks]], [[project-backend-control-mcp]].
