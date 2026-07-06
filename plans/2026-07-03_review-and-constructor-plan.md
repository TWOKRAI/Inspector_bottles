# Ревью multiprocess_prototype (2026-07-03) + план «конструктор»

> Продолжение [`master-rework-roadmap.md`](master-rework-roadmap.md) (сверка 2026-06-18) и
> [`prototype-carveout.md`](prototype-carveout.md). Этот док: (1) свежая сверка статусов по живому
> коду на ветке `refactor/master-rework`, (2) новые находки ревью, (3) детальный волновой план
> «чистка → carve-out → конструктор».
>
> Методика: частично multi-agent workflow (2 из 13 агентов завершились до session-limit:
> дизайн god-split — [`2026-07-03_god-split-design.md`](2026-07-03_god-split-design.md),
> sentrux-метрики), остальное — инлайн-проверка точечными grep/чтением с верификацией каждого
> утверждения по коду. **Не покрыто глубоким ревью:** domain/adapters, backend, вкладки кроме
> pipeline — их можно догнать повторным прогоном workflow (`resumeFromRunId: wf_73aaf3ab-265`).

---

## 1. Свежие метрики (sentrux, 2026-07-03)

| Метрика | Raw | Score | Baseline роадмапа | Дельта |
|---|---|---|---|---|
| Quality signal | — | **7173** | 7031 | **+142** |
| Modularity (bottleneck) | 0.3441 | **5627** | 0.2700 / 5134 | **+493** |
| Acyclicity | 0 циклов | 10000 | 0 циклов | = |
| Depth | 5 | 6154 | — | `min_depth` FAIL (0.6154 < 0.65) |
| Redundancy | 0.0988 | 9012 | — | — |

- Carve-out'ы (event_module, SnapshotHistory, Services/Plugins) **дали измеримый эффект** — quality и modularity выросли.
- Bottleneck прежний: modularity (1606 из 2680 рёбер межмодульные, 60%). Главный хаб — `frontend.widgets` (374 fan-in); худший fan-out: `frontend/app.py` (28), `forms/factory.py` (15).
- DSM: above_diagonal = 0 — слои чистые, инверсий нет.

## 2. Сверка статусов роадмапа (verified 2026-07-03)

### Закрыто с 2026-06-18

| Пункт | Статус |
|---|---|
| Carve EventBus → `event_module` | ✅ Сделано чисто: `domain/event_bus.py` и `domain/protocols/event_bus.py` — тонкие re-export-шимы; Qt-обёртка (`frontend/qt_event_bus.py`) корректно маршалит cross-thread publish через `Signal` + QueuedConnection |
| Carve SnapshotHistory[T] → framework | ✅ (коммит ef2d6a6e) |
| Удаление `multiprocess_prototype_backup/` | ✅ 694 файла (e128b930), **но остались хвосты — см. находки Н-1, Н-2, Н-8** |
| SC-12 READ-normalize рецептов | 🟡 **Частично**: единая точка `unwrap_recipe` есть ([launch.py:58](../multiprocess_prototype/backend/launch.py#L58)), `recipes/presenter.py:386` передаёт полный raw — но в [pipeline/presenter.py:1225](../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L1225) осталась своя or-цепочка `raw.get("blueprint") or raw.get("data", {}).get("blueprint")` |

### Всё ещё открыто (подтверждено по коду)

| ID | Где | Факт |
|---|---|---|
| M-err-1 | [Plugins/sources/camera_service/plugin.py:153-155](../Plugins/sources/camera_service/plugin.py#L153) | `except Exception: return []` — камера умирает молча (чёрный экран) |
| M-err-2 | [Plugins/sources/capture/plugin.py:152](../Plugins/sources/capture/plugin.py#L152) | аналогичный swallow |
| M-race-1 | [Plugins/hub/device_hub/plugin.py](../Plugins/hub/device_hub/plugin.py) | 10 мест читают приватные `_manager._entries/_drivers` без лока (строки 210, 223, 275, 287, 335, 446, 451, 452, 900, 903); `snapshot_registry()` не появился |
| M-leak-3 | [pipeline/presenter.py:167,177](../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L167) | обе EventBus-подписки живут вечно: ни `unsubscribe`, ни `dispose` нет ни в presenter.py, ни в tab.py |
| M-leak-2 | [frontend/app.py:269](../multiprocess_prototype/frontend/app.py#L269) | `add_state_listener` без пути отписки; `remove_state_listener` во framework отсутствует |
| M-leak-5 | [services/robot/calibration/controller.py:142](../multiprocess_prototype/frontend/widgets/tabs/services/robot/calibration/controller.py#L142) | `unbind()` отписывает только progress, robot-telemetry fanout (`:111-112`) не отписывается никогда; `_unbind_progress` (`:160-165`) лишь сбрасывает метки — сам комментарий признаёт «явного unbind по owner здесь нет» |
| K1 | [frontend/app.py:466-470](../multiprocess_prototype/frontend/app.py#L466) | мёртвая проводка `_legacy_action_bus` стоит (решение 2026-06-18 — снять) |
| K10 / HP-2 | [frame_shm_middleware.py](../multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py) | 7 `[TRACE]`-логов в hot-path на месте |
| HP-1 | там же | замеров latency нет (0 вхождений perf_counter/monotonic) |
| CARVE-resolver | [frontend/bridge/plugin_register_resolver.py](../multiprocess_prototype/frontend/bridge/plugin_register_resolver.py) | всё ещё в прототипе (потребитель app.py:535) |
| CARVE-seam | backend/launch.py | шов SystemBuilder не вынесен, характеризационного теста `build()` нет |

## 3. Новые находки ревью (2026-07-03)

| # | Sev | Где | Что |
|---|---|---|---|
| Н-1 | 🔴 | [tests/test_plugin_chain.py:20-26](../tests/test_plugin_chain.py#L20) | Импортирует удалённый `multiprocess_prototype_backup.*` → pytest падает на этапе collection. **Регрессия коммита e128b930** |
| Н-2 | 🟠 | `.tmp_factcheck/` (5 файлов: c.json, c_main.json, c_v2.json, isaac.md, rel.json) | Временный мусор закоммичен в репо тем же e128b930 (в сообщении коммита прямо упомянут). Удалить + в .gitignore |
| Н-3 | 🟠 | [pipeline/presenter.py:986](../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L986) | `QTimer()` без parent, никогда не останавливается — при пересоздании вкладки таймер может дёрнуть `_persist_layout_to_recipe` мёртвого presenter'а |
| Н-4 | 🟠 | [inspector_panel.py:496-507, 525-571](../multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py#L496) | camera-телеметрия: unbind вызывается только при смене ноды/clear; при разрушении панели с активной camera-нодой хэндлы `_bindings.bind(...)` остаются живыми |
| Н-5 | 🟡 | [forms/factory.py:789-802, 866-878, 942-954](../multiprocess_prototype/frontend/forms/factory.py#L789) | Блок чтения old_value из RM (`_on_editing_finished`) скопирован дословно 3 раза, с одинаковым широким `except (AttributeError, KeyError, TypeError)` |
| Н-6 | 🟡 | [inspector_panel.py:448-454](../multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py#L448) | Вложенная манипуляция `_suppress_changes` с двумя `finally` — внешний спасает, но любой рефакторинг ломает подавление сигналов |
| Н-7 | 🟡 | [plugin_orchestrator.py:193-201](../multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py#L193) | Multi-instance фикс (f8619de0) **сменил семантику для всех плагинов**: `plugin_name` теперь всегда перекрывает классовый `name` (раньше — только если пустой). Конвенция register_name == plugin_name задокументирована в комменте, но контракт-теста «каждый плагин процесса получает уникальный instance.name» нет |
| Н-8 | ⚪ | pyproject.toml (116, 119, 123, 149, 178, 187, 213), .pre-commit-config.yaml (7, 54), scripts/*.toml, .claude/security-patterns.json | Мёртвые упоминания удалённого `multiprocess_prototype_backup` в конфигах инструментов — безвредно, но мусор |

Правки рецептов в e128b930 (app.yaml → webcam_sketch, gui_positions) — безобидны, проблем не найдено.

## 4. Волновой план (обновление W-решётки)

Порядок сохраняет политику владельца: **гигиена → утечки → hot-path swallow → гонки → carve/split → comm S4/S5 последними**. Параллелизм: ≤2 агента без worktree; hot-path строго последовательно.

### Волна A — Гигиена (немедленно, ~час, риск 0)

1. **Н-1**: `tests/test_plugin_chain.py` — тест тестирует удалённый backup-код: удалить файл (владелец подтверждает) или переписать на живой `multiprocess_prototype` эквивалент, если он есть.
2. **Н-2**: `git rm -r .tmp_factcheck/` + строка в `.gitignore`.
3. **Н-8**: вычистить `multiprocess_prototype_backup` из pyproject.toml / .pre-commit-config.yaml / scripts/*.toml / .claude/security-patterns.json.
4. Прогон `python scripts/validate.py` + pytest collection — зелёный.

*Acceptance:* pytest собирается без ошибок; `git status` чистый; grep по backup в конфигах пуст.

### Волна B — Утечки/teardown (W1, риск низкий)

1. **M-leak-3 + Н-3**: `PipelinePresenter.dispose()` — `unsubscribe()` обеих подписок + `stop()` таймера + обнуление сцены; вызов из `PipelineTab` (closeEvent/деструктор). Тест: fake-EventBus, dispose, publish → handler не вызван. Готовый эскиз — в [god-split-design §0](2026-07-03_god-split-design.md).
2. **Н-4**: `dispose()` для camera-секции inspector (баланс bind/unbind = 0 на fake-bindings).
3. **M-leak-5**: в `GuiStateBindings` завести `unbind_by_owner(owner)` (или unbind-хэндлы из `bind_fanout`), в calibration controller — полный `unbind()` (progress + robot telemetry).
4. **M-leak-2**: `remove_state_listener` во framework (симметрия API; накопления сейчас нет — задел на будущее).
5. **K1**: снять мёртвую проводку `_legacy_action_bus` (app.py:466-470) + no-op мосты (per решение 2026-06-18; сам ActionBus/`actions_module` во framework остаётся как patch-tier).

*Acceptance:* qt-smoke пересборки вкладок; тесты на отписку; sentrux-дельта ≥ 0.

### Волна C — Error-swallow hot-path (W2, продукт, СТРОГО последовательно)

1. **M-err-1** (camera_service:153-155), **M-err-2** (capture:152): принцип contain → report → degrade — лог + `status=error` в state-дерево + вернуть `[]`. НЕ пробрасывать (обрушит воркер).
2. Агрегатный аудит остальных `except Exception: pass/return []` по Plugins/sources и hot-path (~30 мест по старому аудиту) — той же схемой.

*Acceptance:* qt-smoke: выдёргиваем камеру → в GUI видимая ошибка, соседние процессы живут (fault-isolation критерий §1.1 роадмапа); FPS ≥ baseline.

### Волна D — Гонки device_hub (W3-C)

1. **M-race-1**: публичные `snapshot_registry()` / `connected_ids()` под `_registry_lock` в менеджере; плагин перестаёт читать `_manager._entries/_drivers` во всех 10 местах (210, 223, 275, 287, 335, 446, 451, 452, 900, 903); незалоченный `list_devices()` — тоже на snapshot.
2. Fault-isolation тест: убить один драйвер → хаб и соседние девайсы живут, статус деградации виден.

### Волна E — Carve-out → конструктор (W4/W5, параллельный трек B)

Правило: выносить **только** zero-coupling или app-agnostic контракт (≥2 потребителей реальных или очевидных). Каждый вынос = полная дисциплина модуля: `interfaces.py`, README, STATUS, контракт-тесты, thin re-export shim в прототипе, `check_rules` зелёный.

| Шаг | Что | Куда | Усилие | Предусловие |
|---|---|---|---|---|
| E1 | `plugin_register_resolver` (чистая функция, 1 потребитель app.py:535, тесты есть) | `frontend_module` или `registers_module` | S | нет |
| E2 | `qt_event_bus.py` — generic Qt-мост для event_module (imports: только шимы + `ProjectEvent` как type-bound → обобщить до Event-Protocol) | `frontend_module/qt_event_bridge.py` | S/M | обобщить type-bound; прототип держит шим |
| E3 | **Шов SystemBuilder**: `SystemLauncher(...) + add_process` (launch.py:374-394), `_ORCHESTRATOR_CLASS_PATH` → DI-параметр | `process_manager_module` (или новый `system_builder`) | M | **characterization-тест `build()` ПЕРВЫМ** (snapshot: blueprint dict → N процессов + orchestrator_config) — его до сих пор нет |
| E4 | Forms: сперва **diff `forms/factory.py` ↔ `frontend_module/widgets/entity_editor/params_form.py`** (роадмап §7.7 требует diff до ТЗ). Затем split factory на пакет (см. god-split §2: `kinds.py` — чистый резолвер, builders_legacy/binding, json_editor, реестр KindBuilders). Carve во framework — только если diff покажет реальную унифицируемость | `frontend_module` | M/L | split-пакет в прототипе сначала; Н-5 чинится попутно (общий `_rm_old_value` helper) |
| E5 | Graph-editor: сперва `graph/data.py` (чистые NodeData/EdgeData/PortSchema без Qt — сейчас лежат в node_item.py рядом с QGraphicsItem) + `graph_codec.py` (см. god-split §1.A). Вынос generic graph-editor во framework — **later**, после того как codec отделён и появится второй потребитель | `frontend_module` (later) | L | W6 шаги 1a-2 |
| E6 | Телеметрия self-publish → переиспользуемый helper/mixin поверх `process_heartbeat._publish_metrics_to_tree` | framework | S | нет |

**Отложено (single-consumer trap, без изменений):** domain/* (кроме уже вынесенного), adapters/CommandDispatcherOrchestrator, GuiStateBindings как целое, DataReceiverBridge (после S4/S5), tab_factory (сцеплен с RuntimeDeps — см. §5 «контракт реестра вкладок» как будущую замену).

### Волна F — God-split (W6, отдельный worktree, параллельно D/E)

Детальный проект: [`2026-07-03_god-split-design.md`](2026-07-03_god-split-design.md). Сводно:

- `pipeline/presenter.py` (1827) → core (~400) + `graph_codec.py` + `layout_controller.py` + `wire_validation.py` + `mutations.py` + `runtime_control.py` + `recipe_io.py`. Порядок: dispose → graph/data.py → characterization-тесты codec → codec → validation → runtime → layout → io/mutations.
- `forms/factory.py` (1190) → пакет `forms/factory/` (kinds / builders_legacy / builders_binding / json_editor / реестр) — характеризационные тесты по таблице из дизайна.
- `inspector_panel.py` (1151) → 5 секций-виджетов по образцу уже существующей `IoDebugSection` + чистый `selectors_data.py`.

Попутно закрывается **SC-12-остаток**: `graph_codec`/`recipe_io` начинают ходить через `unwrap_recipe` вместо своей or-цепочки (presenter.py:1225).

*Acceptance:* sentrux modularity — числовая дельта от **5627** (не от старых 4488/5134!); вкладки Pipeline/Inspector живы в qt-smoke; внешние контракты (сигналы панели, публичные методы presenter из tab.py) не изменены.

### Волна G — Comm S4/S5 (W7/W8, ПОСЛЕДНИМИ, hot-path)

Без изменений против роадмапа §8: снять 7 TRACE (K10) → замер baseline latency (HP-1, нулевой шаг) → характеризационный тест паритета каналов (дефолт `"queue"`!) → проводка `resolve_channel_kind` в `_resolve_channels` (~15 строк) под feature-flag `use_kind_channels` → аудит opt-out'ов `manages_own_reply`. HP-5 (replace_blueprint × in-flight кадр) — явный gate-вопрос перед стартом.

## 5. Целевая картина «конструктора» (куда всё это ведёт)

После волн E/F фреймворк даёт блоки, из которых новое приложение собирается декларативно:

| Блок | Статус | Что остаётся сделать |
|---|---|---|
| Процессы/IPC/SHM/роутинг (process_module, router, SHM) | ✅ есть | S4 kind-каналы (волна G) |
| Типизированный pub/sub (`event_module`) + Qt-мост | 🟡 ядро есть | E2: qt-мост |
| Undo двух tier'ов: snapshot (`SnapshotHistory`) + patch (`actions_module`) за контрактом `UndoRedoController` | 🟡 ядро есть | RBAC-hook на контракте; transactional/debounced commit — только после замера |
| Формы по схеме (params_form + kinds/builders) | 🟡 две реализации | E4: diff → split → merge |
| Graph-editor (сцена + чистый codec) | ❌ app-specific | E5/F: сначала data.py+codec |
| SystemBuilder (blueprint → процессы) | ❌ app-specific | E3: вынести шов |
| Registers/live-пульт (registers_module) | ✅ есть | конвенция instance.name == plugin_name — добавить контракт-тест (Н-7) |
| Реестр вкладок (tab-registry contract) | ❌ ad-hoc (`tab_factory` + RuntimeDeps) | later: декларативный контракт «вкладка = фабрика(services, runtime)» — после 2-го приложения |
| Recipe-store (versioned yaml + migrations engine) | ❌ app-specific | later: смотреть после E3 — есть ли app-agnostic ядро |

Метрика прогресса: доля composition root'а прототипа (`app.py`, 28 fan-out; `launch.py`), которая сводится к вызовам framework-блоков. Carve — forcing-function; метрику modularity двигает прежде всего app-side split (волна F), не сам вынос.

## 6. Правила выполнения (без изменений)

- Каждая волна: `session_start` → правки → `session_end`, дельта в коммит-трейлер `Tested:`.
- Hot-path (камеры, kind-каналы) — строго последовательно, FPS-baseline до, feature-flag откат.
- Kill-list (K3-K9, ~2666 LOC) — per-item решения владельца, отдельным заходом, ничего не удалять в одностороннем порядке.
- Коммиты: Conventional Commits + `Why:`/`Layer:` + `Refs: plans/2026-07-03_review-and-constructor-plan.md`.

## 7. Открытые вопросы владельцу

1. Н-1: `tests/test_plugin_chain.py` — удалить или переписать на живую структуру? (Рекомендация: удалить — он тестировал backup-виджеты, у живого кода свои тесты.)
2. Подтвердить порядок A → B → C → D → (E ∥ F) → G. E и F можно вести параллельно в worktree.
3. E4 (forms): если diff покажет глубокое расхождение семантики — оставить две реализации (framework для новых приложений, прототипная — замороженной) или мигрировать прототип на framework-формы? 
4. Догнать несделанную часть ревью (domain/adapters, backend, прочие вкладки) повторным multi-agent прогоном после сброса лимита?
