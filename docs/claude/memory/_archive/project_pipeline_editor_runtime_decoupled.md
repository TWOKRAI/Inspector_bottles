---
name: project_pipeline_editor_runtime_decoupled
description: "Pipeline GUI editor и running backend РАЗВЯЗАНЫ — правка графа меняет только in-memory модель, не трогает живые процессы. Движок hot-apply почти весь готов, но не подключён (IPC-мост)."
metadata:
  type: project
---

Расследование 2026-05-31 (investigator, confidence HIGH): владелец удалил ноду process_negative в Pipeline-редакторе — негатив продолжал обрабатываться на дисплее. Гипотеза «editor и runtime независимы» ПОДТВЕРЖДЕНА.

**Почему так (by design + недоделка):**
- GUI и ProcessManagerProcess — разные OS-процессы, связь только через RouterManager (IPC). Прямого вызова нет.
- Удаление ноды: `presenter.remove_selected` → `dispatch(RemoveProcess)` → `command_dispatcher` делает только `project.apply()` → `topology_repo.save()` (in-memory) → `event_bus.publish(TopologyReplaced)` → перерисовка графа. **Никакого IPC к живым процессам.**
- Процессы стартуют ОДИН раз: `main.py` → `app.yaml` → `SystemBuilder` → `SystemLauncher.run()`. Дальше автономны. GUI грузит ту же топологию в ОТДЕЛЬНУЮ in-memory копию (TopologyRepositoryStore) для рисования.

**Что УЖЕ готово во фреймворке (не писать заново):**
- `replace_blueprint` (горячая замена набора процессов) — process_manager_process.py:635, покрыт тестами (test_replace_blueprint.py).
- `start_process`/`stop_process`/`restart_process` — process_manager_process.py:964-1004 (процесс целиком; per-worker остановки в API НЕТ).
- Загрузка/активация рецепта → hot replace: recipes/presenter.py:287 `on_set_active` → `replace_blueprint_fn`.
- Сохранение/загрузка рецепта (файл): recipes/manager.py:90-115 load/save.
- Hot add/remove процессов через IPC: topology_bridge.py:497 `apply_topology_diff` — код ЕСТЬ, но ОТКЛЮЧЁН (был на legacy ActionBus, снят при G.4.2).
- **Параметры плагина вживую УЖЕ работают:** `SetPluginConfig → PluginConfigChanged → rm.set_value → IPC`. Структуру (add/remove) — не шлёт никто.

**Главный блокер подключения:** `process_manager_proxy`/`replace_blueprint_fn` не прокинут в GUI — app.py:441 `config={}`. Кнопка «Запустить» (presenter.py:1491 `launch_active_recipe`) уже зовёт `proxy.replace_blueprint`, но proxy=None → «ProcessManager-proxy недоступен».

**План владельца — 3 этапа (по сложности):**
1. ПРОСТО: кнопки Запустить/Остановить/Перезапустить (Pipeline) + Сохранить/Загрузить рецепт (Recipes). Модель «применить целиком» через 1 IPC-мост к готовым replace_blueprint/stop/start. Закрывает ~80%.
2. СРЕДНЕ: реактивный hot add/remove ПРОЦЕССОВ — оживить apply_topology_diff на TopologyReplaced.
3. СЛОЖНО (отдельно, поверх [[project_transport_router_hub]]): granular live-управление воркерами/структурой по адресу router. Per-worker stop + новый IPC-контракт + консистентность живого графа (гонки, полукадры).

Связано: [[project_pipeline_recipe_driven_launch]], [[project_transport_router_hub]], [[project_hierarchical_addressing]], [[project_recipes_manager]], [[project_processes_workers_runtime]].
