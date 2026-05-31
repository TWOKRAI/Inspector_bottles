# План: Pipeline live-управление процессами (GUI → backend через IPC)

- **Slug:** pipeline-live-control
- **Дата:** 2026-05-31
- **Статус:** DRAFT
- **Ветка:** feat/pipeline-live-control
- **Refs:** docs/claude/memory/project_pipeline_editor_runtime_decoupled.md, plans/2026-05-31_transport-router-hub/ (P3 — зависимость Этапа 3)

## Обзор

GUI-редактор Pipeline сейчас меняет топологию-граф только в памяти фронта — изменения
**не доходят** до работающего `ProcessManagerProcess`. Кнопки в UI есть, но либо не
подключены к IPC, либо вызывают `proxy`, который не инициализирован (`app.py:441`,
`config={}`). Цель — подключить редактор к живому бэкенду через **готовый** транспорт
(`RouterManager` + command IPC), **переиспользуя** уже работающие API
(`replace_blueprint`, `start/stop/restart_process`, паттерн `SetPluginConfig`), не изобретая новое.

План разбит на **3 независимых этапа** (владелец решит порядок и объём в работу ПОСЛЕ
прочтения). Каждый этап самодостаточен и даёт видимый результат.

## Что уже готово и переиспользуется (НЕ писать заново)

| Механизм | Где | Статус |
|----------|-----|--------|
| `replace_blueprint(blueprint_dict)` | `process_manager_process.py:635` | работает, atomic replace с rollback, принимает dict (Dict at Boundary ✓) |
| `start_process / stop_process / restart_process` | `process_manager_process.py:964-1004` | работает, по **имени процесса** |
| `SetPluginConfig → PluginConfigChanged → rm.set_value` | плагины, live | работает (параметр плагина вживую) — паттерн для Этапа 3 |
| `launch_active_recipe` | `pipeline/presenter.py:1491` | уже зовёт `proxy.replace_blueprint`, но `proxy=None` |
| `apply_topology_diff` | `bridge/topology_bridge.py:497` | был на legacy ActionBus, отключён при G.4.2 — оживить в Этапе 2 |
| `on_set_active` / `replace_blueprint_fn` | `recipes/presenter.py:287` | проброс проверить/доделать |
| `CommandSender(process)` — готовый IPC GUI→backend | `app.py:108`, `frontend/bridge/command_sender.py` | **переиспользовать как транспорт proxy** (не изобретать) |
| `PluginConfigChanged → rm.set_value → IPC` (живой путь) | `app.py:476-490` | образец «событие→IPC» для Этапа 3 |
| подписка на `TopologyReplaced` (уже есть) | `app.py:462-464` (сейчас только инвалидация IPC-кэша bridge) | точка подключения Этапа 2 |
| `_recipe_manager`, `topology_store`, `event_bus` в составе AppServicesDeps | `app.py:434-444` | доступны для проброса в proxy/presenter |

## Главный блокер (общий для всех этапов)

`process_manager_proxy` **нигде не создаётся** для GUI-процесса. AppServices собирается
с `config={}` (`app.py:441`), поэтому `launch_active_recipe` зовёт `proxy.replace_blueprint`
по `None`. **Этап 1 закрывает этот блокер** созданием IPC-моста GUI → ProcessManagerProcess —
это фундамент, на котором стоят Этапы 2 и 3.

## Порядок выполнения

### Этап 1 — Ручные кнопки управления (простой, «применить целиком»)
Сложность: **Middle / Middle+** · Риск: **низкий-средний** (новый IPC-мост — точка интеграции)
- Task 1.1: **[VERTICAL SLICE]** IPC-мост GUI→PM + кнопка «Перезапустить» через `replace_blueprint` [PENDING]
  - **Module contract:** public-api-change (новый прокси-фасад) + impl-only (app.py wiring)
- Task 1.2: Кнопки Запустить / Остановить / Перезапустить на вкладке Pipeline [PENDING]
  - **Module contract:** impl-only
- Task 1.3: Сохранить / Загрузить рецепт на вкладке Recipes (`replace_blueprint_fn`) [PENDING]
  - **Module contract:** impl-only

### Этап 2 — Реактивный hot-apply процессов (средний)
Сложность: **Middle+ / Senior** · Риск: **средний** (конфликты с ручными кнопками, консистентность)
- Task 2.1: Оживить `apply_topology_diff` на событие `TopologyReplaced` [PENDING]
  - **Module contract:** impl-only
- Task 2.2: Политика «когда авто-apply, когда только по кнопке» (режим/флаг) [PENDING]
  - **Module contract:** impl-only

### Этап 3 — Granular live по router-адресу (сложный, поверх transport-router-hub P3)
Сложность: **Senior+** · Риск: **высокий** (новый IPC-контракт, гонки, полукадры, фреймворк)
- Task 3.1: Новый метод фреймворка `stop_worker(address)` / per-worker управление [PENDING]
  - **Module contract:** public-api-change (interfaces.py process_manager_module)
- Task 3.2: IPC-контракт адресного управления (плагин/воркер/процесс) [PENDING]
  - **Module contract:** new-lite (новый command-контракт)
- Task 3.3: Консистентность живого графа при отцепке ноды (гонки, полукадры) [PENDING]
  - **Module contract:** impl-only

## Риски и ограничения (сводно)

- **Dict at Boundary:** между GUI-процессом и ProcessManagerProcess — только `dict`
  (`to_dict`/`from_dict`). `replace_blueprint` уже принимает dict — соблюдено.
- **IPC только через RouterManager:** не создавать новый транспорт — переиспользовать
  существующий хаб (см. transport-router-hub P0-P2 DONE).
- **Плагины не читают SHM напрямую** — Этап 3 идёт через middleware/команды, не через прямой доступ.
- **qt-mcp smoke обязателен** для каждой GUI-задачи (pytest-qt не доказывает реальную сборку,
  см. `feedback_qt_mcp_smoke_verification`).
- **Этап 3 завязан на transport-router-hub P3** (отложен) и hierarchical addressing —
  начинать только после/совместно с P3, не дублировать его per-worker stop.
- **No global taskkill** при ручной проверке процессов (PID-specific / TaskStop).

## Пересечение с существующими планами

- `plans/2026-05-31_transport-router-hub/` — его **P3** (granular live по router-адресу,
  per-worker stop) — это транспортная основа Этапа 3 данного плана. **Не дублировать:**
  Этап 3 здесь = pipeline-сторона (IPC-контракт из GUI, консистентность графа),
  P3 там = транспортная доставка по адресу. При работе над Этапом 3 — синхронизировать с P3.

## Файлы плана

- `phase-1.md` — Этап 1 (Task 1.1–1.3)
- `phase-2.md` — Этап 2 (Task 2.1–2.2)
- `phase-3.md` — Этап 3 (Task 3.1–3.3)
