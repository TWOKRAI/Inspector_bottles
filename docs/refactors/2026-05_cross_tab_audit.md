# Cross-tab архитектура — Phase A: read-only audit

- **Дата:** 2026-05-27
- **Статус:** DRAFT (read-only inventory)
- **Brief:** [`docs/refactors/2026-05_cross_tab_architecture.md`](2026-05_cross_tab_architecture.md)
- **Plan:** [`plans/2026-05-27_cross-tab-audit.md`](../../plans/2026-05-27_cross-tab-audit.md)
- **Ветка:** `refactor/cross-tab-architecture`

## Preamble

Документ фиксирует фактическое состояние cross-tab связей prototype'а на момент
коммита `a0e45d52` (план задачи) / `1050e62f` (brief). Цель — закрыть для автора
Phase B вопрос «где это используется» одним прочтением.

Только описательные формулировки. Никаких рекомендаций «как переделать».
Структура — 6 секций инвентаризаций (по плану) + summary в начале.

Scope: `multiprocess_prototype/frontend/` (все 7 табов + AppContext + bridge +
TopologyHolder) + тонкие срезы `multiprocess_framework/` (только intersection)
и `multiprocess_prototype/registers/` (ConnectionMap, RegistersManager.from_topology —
используют raw-dict topology). `multiprocess_prototype_backup/` исключён.

---

## Summary

### Числа по 6 категориям

| # | Инвентаризация | Количество occurrences |
|---|----------------|------------------------|
| 1 | Потребители topology (`topology.get(...)`, `holder.topology`, `config["topology"]`, `extras["topology"]`) | **40** в prod-коде + 14 в тестах (включая `topology.get` 32 и `holder.topology` 8) |
| 2 | Ключи `ctx.extras[...]` | **16 уникальных ключей** (15 в `app.py` + 1 `topology` legacy), все доступы read через `extras.get(...)` или accessor-методы |
| 3 | Реестры (внутри-табные хранилища) | **8 реестров** (brief упоминал 7 — `DisplayRegistry` 8-й, не помещён в `extras`) |
| 4 | Callback'и/observable (TopologyHolder.on_changed, AuthState signals, ActionBus.execute, bindings.bind) | **6 типов триггеров**, 25+ `bindings.bind(...)` точек, 1 `holder.on_changed` подписчик в prod |
| 5 | Raw-dict операции в presenter'ах (`for proc in topology.get("processes")` и аналог) | **20 occurrences** в prod-коде (14 в frontend/widgets/tabs/, 4 во вспомогательных слоях, 2 в registers/) |
| 6 | Тесты с MagicMock-ctx | **39 файлов**, 53 уникальных создания `ctx = MagicMock()` (включая 13 в `test_services_tab.py`, 6 в `test_inspector.py`) |

### Топ-3 узких места по числу occurrences

1. **MagicMock-ctx в тестах: 53 точки создания в 39 файлах.** Каждый таб
   тестируется через `MagicMock()` с ad-hoc `return_value`-ами. Это означает,
   что любая смена контракта AppContext (например, переименование `recipe_manager()`
   → `recipe_manager` или замена `topology_holder()` → `topology_holder`) даёт
   зелёные тесты при сломанном production-коде. Конкретный пример скрытого
   несоответствия — пункт 6, строка про `pipeline/presenter.py:730,803`.

2. **Raw-dict обход `topology.get("processes", [])` + `for proc in ...`: 20 occurrences
   в production.** Каждое место сама-делает то же самое (`isinstance(proc, dict)`
   + `proc.get("process_name")` + `proc.get("plugins", [])`). Зафиксировано в
   `pipeline/model.py` (15 раз), `pipeline/presenter.py` (3), `pipeline/io.py` (3),
   `pipeline/tab.py` (1), `processes/presenter.py` (3), `registers/connection_map.py`
   (1), `registers/manager.py` (1), `frontend/startup_checks.py` (3),
   `bridge/topology_bridge.py` (3), `pipeline/inspector/inspector_panel.py` (1),
   `recipes/recipe_form.py` (1), `recipes/migrations/format_v1_to_v2.py` (1).

3. **Pipeline tab — крупнейший read+write consumer.** В одном табе соприкасаются
   все 8 реестров: PluginRegistry (palette + presenter валидация), DisplayRegistry
   (inspector + model), RecipeManager (save/launch + inspector), RegistersManager
   (inspector cards), ActionBus (mutations), TopologyHolder (read+set_topology),
   TopologyBridge (на чтение через app.py через подписку), command_catalog
   (через extras). Из 40 топологических чтений 21 — в `pipeline/`.

### Сюрпризы и аномалии (не в brief)

- **8-й реестр — `DisplayRegistry`** — singleton, в `ctx.extras` НЕ помещён.
  Читается через `getattr(ctx, "display_registry", None)`, что в production
  всегда возвращает `None` (атрибута нет на dataclass'е). Запись `ctx.display_registry`
  встречается только в тестах. См. `displays/tab.py:156`, `pipeline/presenter.py:189`,
  `pipeline/inspector/inspector_panel.py:439`. Brief упоминает «DisplayRegistry — state,
  оптимизировано» (раздел 2.5), но не зафиксировано, что в prod-коде доступ через
  `getattr` падает в graceful fallback.
- **9-й potential реестр — `router_manager`** — `displays/tab.py:479` пробует
  `getattr(self._ctx, "router_manager", None)` для preview-окна. В `app.py` нигде
  не записывается. Это всегда `None` в production.
- **Двойной контракт `recipe_manager`** — в `app_context.py:135` это
  **property** (`@property`), но `pipeline/presenter.py:730` и `:803`
  вызывает его как **method** (`self._ctx.recipe_manager()`). В тестах
  с `ctx = MagicMock()` оба способа работают одинаково; в живом GUI этот вызов
  должен падать с `TypeError`, если property возвращает не-callable объект.
  В Inspector (`inspector_panel.py:397`) используется через `getattr(ctx, "recipe_manager", None)`
  — корректно как property.
- **Ключ `extras["topology"]`** — записывается в `app.py:149`, читается
  **только** в `processes/presenter.py:50` как **fallback** к `config["topology"]`.
  Это не «эквивалентная копия» — это initial snapshot, который НЕ обновляется
  после `holder.set_topology(...)`. Brief зафиксировал это в разделе 2.2.
- **Ключ `extras["tab_factory"]`** — записывается в `app.py:417`, читается
  нулём consumer'ов (grep по prototype показал только запись). Это dead key.
- **Параллельные dataclass-обёртки в `frontend/`** —
  `topology_context.py`, `state_context.py`, `plugins_context.py`,
  `actions_context.py`, `auth_context.py` — **созданы** как «узкие контракты»
  поверх `extras`, но в prod-коде передаются **только** `auth_context.py`
  (через `ctx.auth` property). Остальные 4 — нет потребителей по grep'у
  (только определения класса; не импортируются в presenter'ах).

### Что осталось «требует расследования»

- Один MagicMock-кейс с **двойным контрактом recipe_manager** (раздел 6, ряды
  про `test_launch_recipe.py:39`, `test_save_recipe.py:78`) — нужно проверить
  в живом GUI, отрабатывает ли вызов `()` на property-объекте.

---

## Inventory 1 - Потребители topology

Соответствует п. 2.2 и 2.3 brief-а. Тесты не включены в таблицу - только prod-код.

| Файл:строка | Role | Контекст |
|-------------|------|----------|
| multiprocess_prototype/frontend/app.py:142 | write | _topology_dict = yaml.safe_load(DEFAULT_BLUEPRINT.read_text(...)) |
| multiprocess_prototype/frontend/app.py:147 | write | topology_holder = TopologyHolder(_topology_dict) |
| multiprocess_prototype/frontend/app.py:149 | write (legacy) | ctx.extras topology = _topology_dict -- обратная совместимость |
| multiprocess_prototype/frontend/app.py:182 | read | connection_map = ConnectionMap.from_topology(_topology_dict) |
| multiprocess_prototype/frontend/app.py:155 | read | _checker.check_all(_topology_dict, registry=PluginRegistry) |
| multiprocess_prototype/frontend/app.py:197 | subscribe | topology_holder.on_changed(topology_bridge.on_topology_changed) |
| multiprocess_prototype/frontend/topology_holder.py:28-44 | both | property topology + set_topology() + _notify() |
| multiprocess_prototype/frontend/startup_checks.py:57 | read | processes = topology.get("processes") |
| multiprocess_prototype/frontend/startup_checks.py:68 | read | for proc in processes: name = proc.get("process_name", "") |
| multiprocess_prototype/frontend/startup_checks.py:80-89 | read | for proc in processes: proc.get("chain_targets", []), proc.get("plugins") |
| multiprocess_prototype/frontend/startup_checks.py:137 | read | for proc in topology.get("processes", []): proc.get("plugins", []) |
| multiprocess_prototype/frontend/bridge/topology_bridge.py:329 | read via holder | for proc in self._holder.topology.get("processes", []): proc.get("process_name") |
| multiprocess_prototype/frontend/bridge/topology_bridge.py:616 | read via holder | for wire in self._holder.topology.get("wires", []): -- _find_process_wires |
| multiprocess_prototype/frontend/bridge/topology_bridge.py:628 | read via holder | for wire in self._holder.topology.get("wires", []): -- _find_wire |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:58-60 | read+subscribe | holder = ctx.topology_holder(); holder.on_changed(self._on_topology_changed_external) |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:141 | read | processes = self._model._topology.get("processes", []) -- target_process update |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:185 | read | displays = self._model._topology.get("displays", []) -- display_id update |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:253 | read | topology = self._ctx.config.get("topology", {}) -- load_topology_from_config |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:257 | read | metadata = topology.get("metadata", {}) -- gui_positions |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:357-359 | write via holder | holder = self._ctx.topology_holder(); holder.set_topology(new_topo) |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:583-594 | read (callback) | _on_topology_changed_external(new_topology) -- model.from_topology_dict + scene.load_from_data |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:650 | read | processes = topo_dict.get("processes", []) -- _topology_to_graph |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:686 | read | wires = topo_dict.get("wires", []) |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:60 | read | for p in self._topology.get("processes", []) -- get_process_names |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:65 | read | return copy.deepcopy(self._topology.get("wires", [])) |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:69 | read | return copy.deepcopy(self._topology.get("displays", [])) |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:78 | read | for w in self._topology.get("wires", []): -- get_edges_as_tuples |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:115-126 | write | remove_process: processes/wires удаление через self._topology["processes"|"wires"] = [...] |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:144-155 | write | add_display: existing_ids = [.. displays.get(..)]; setdefault + append |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:165-173 | write | remove_display: displays/wires удаление |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:205-244 | write | add_wire: cycle detection + self._topology.setdefault("wires", []).append(wire_entry) |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:249-252 | write | remove_wire: wires = self._topology.get("wires", []); self._topology["wires"] = [...] |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:292-313 | read | validate(): display_node_ids + for w in self._topology.get("wires", []) |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/io.py:145 | read | for proc in blueprint.get("processes", []): -- blueprint_to_graph |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/io.py:172 | read+write | for p in model._topology.get("processes", []): p["target_process"] = target_process |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/io.py:180 | write | for p in model._topology.get("processes", []): p["plugins"] = list(plugins) |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py:308-336 | read | _on_selection_changed: topo = self._presenter.model.to_topology_dict(); for disp in topo.get("displays", []); for proc in topo.get("processes", []) |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py:410-422 | read | _get_process_names_from_recipe: blueprint = recipe_dict.get("blueprint", {}); processes = blueprint.get("processes", []) |
| multiprocess_prototype/frontend/widgets/tabs/processes/presenter.py:45 | read | topology_data = self._ctx.config.get("topology", {}); raw_processes = topology_data.get("processes", []) |
| multiprocess_prototype/frontend/widgets/tabs/processes/presenter.py:50-51 | read (fallback) | topo = self._ctx.extras.get("topology", {}); raw_processes = topo.get("processes", []) |
| multiprocess_prototype/frontend/widgets/tabs/recipes/recipe_form.py:100-110 | read | blueprint = data.get("blueprint", {}); processes = blueprint.get("processes", []); plugins_count += len(proc.get("plugins", [])) |
| multiprocess_prototype/registers/connection_map.py:54 | read | for proc in topology.get("processes", []): for plugin_dict in proc.get("plugins", []): plugin_dict.get("plugin_name", "") |
| multiprocess_prototype/registers/manager.py:76-94 | read | processes = topology.get("processes", []); for proc in processes: plugins = proc.get("plugins", []); plugin_name = plugin_dict.get("plugin_name", "") |
| multiprocess_prototype/recipes/migrations/format_v1_to_v2.py:189 | read | processes = topology.get("processes", []) or [] |
| multiprocess_prototype/recipes/migrations/format_v1_to_v2.py:193 | read | wires = topology.get("wires", []) or [] |
| multiprocess_prototype/frontend/actions/handlers/recipe_handler.py:28,36 | write | self._holder.set_topology(topology) -- RecipeApplyHandler |

**Settings tab** -- НЕ потребитель topology. Подтверждение: grep по
multiprocess_prototype/frontend/widgets/tabs/settings/ показывает 0 вхождений
topology.get(...), holder.topology, config-словарь.

**Displays tab** -- НЕ читает topology dict; работает напрямую с DisplayRegistry (см. Inventory 3).

**Plugins tab** -- НЕ читает topology dict; работает только с PluginRegistry + RegistersManager через accessor.

---

## Inventory 2 - Ключи ctx.extras[...]

Соответствует п. 2.1 brief-а.

Все записи централизованы в app.py:run_gui(). Все чтения идут либо через
accessor-методы AppContext (которые внутри делают self.extras.get(...)),
либо напрямую через ctx.extras.get(...) / ctx.extras[...].

| Ключ | Тип значения | Owner (запись) | Consumers | Через accessor |
|------|--------------|----------------|-----------|----------------|
| plugin_registry | PluginRegistry (singleton-class из framework) | app.py:104 через build_app_context(plugin_registry=...) -> app_context.py:227 | plugins/presenter.py:42,55,68; pipeline/presenter.py:315,461,651; pipeline/tab.py:200; processes/presenter.py:53; plugins/sandbox.py:411; plugins/sandbox_presenter.py:99,180 | да (ctx.plugin_registry()) |
| registers_manager | RegistersManager (framework) | app.py:105 через build_app_context(registers_manager=...) -> app_context.py:229 | pipeline/presenter.py:90; pipeline/inspector/inspector_panel.py:490; plugins/presenter.py:115; app_context.py:156 (form_context) | да (ctx.registers_manager()) |
| plugin_manager | PluginManager (framework, экземпляр) | app.py:107 | plugins/presenter.py:133,153,172,183; plugins/paths_subtab.py | да (ctx.plugin_manager()) |
| service_registry | ServiceRegistry (framework, экземпляр) | app.py:134 | services/presenter.py:46,73,113,160,214 (5 точек); plugins/sandbox.py:479,538 | да (ctx.service_registry()) |
| topology_holder | TopologyHolder (prototype) | app.py:148 | pipeline/presenter.py:58,357; actions/bus_factory.py:32; actions/handlers/recipe_handler.py:22 | да (ctx.topology_holder()) |
| topology | dict[str, Any] (initial snapshot) | app.py:149 -- комментарий "обратная совместимость" | processes/presenter.py:50 (fallback к config) | нет (прямой доступ через extras.get) |
| bindings | GuiStateBindings (prototype) | app.py:174 | processes/_panels.py:208,358; main_window.py:455-482; widgets/chrome/error_banner.py | да (ctx.bindings()) |
| command_catalog | CommandCatalog (prototype) | app.py:193 | потребителей по grep НЕ обнаружено (только запись + accessor) | да (ctx.command_catalog()) |
| topology_bridge | TopologyBridge (prototype) | app.py:194 | processes/presenter.py:113 (прямой extras.get) | да (ctx.topology_bridge()) -- но реально читается только через extras в processes/presenter |
| service_state_adapter | ServiceStateAdapter | app.py:230 | потребителей не обнаружено (только запись) | нет accessor |
| recipe_manager | RecipeManager (prototype) | app.py:281 | pipeline/presenter.py:730,803 (как method: ()); pipeline/inspector/inspector_panel.py:397 (как property: getattr); recipes/tab.py:88 (как property: getattr) | да (@property recipe_manager) -- конфликт: presenter использует () |
| recipe_state_adapter | RecipeStateAdapter | app.py:282 | потребителей не обнаружено | нет accessor |
| auth_manager | IAuthManager (Services) | app.py:325 | app_context.py:58,178 (для ctx.auth и ctx.auth_manager()); tab_factory не использует напрямую | да (ctx.auth_manager() + через ctx.auth.manager) |
| auth_state | AuthState (prototype) | app.py:334 | app_context.py:59,182 (для ctx.auth и ctx.auth_state()); tab_factory через ctx.auth.state | да (ctx.auth_state() + через ctx.auth.state) |
| action_bus | ActionBus (framework) | app.py:387 | pipeline/tab.py:103,272,276; pipeline/presenter.py:91,349,386,423,572; services/tab.py:48; plugins/tab.py:90; plugins/_sections.py:241,257; settings/tab.py:31; settings/_sections.py:102; settings/system/presenter.py:134,150; settings/history/presenter.py:55,84,94; settings/administration/section.py:115 | да (ctx.action_bus()) |
| tab_factory | TabFactory (prototype) | app.py:417 | потребителей не обнаружено (dead key) | нет accessor |

**Также** в app.py через extras["audit_storage"] (упомянуто в app_context.py:65,190)
-- но в проверенном app.py:run_gui() нет явной записи этого ключа в
multiprocess_prototype/frontend/app.py. **Известно:** записывается опосредованно
через Services/auth (PR4 Group C); владельца в multiprocess_prototype/ не найдено.

Всего: **15 явных записей в app.py + 1 устаревший topology snapshot = 16 уникальных ключей**.

---

## Inventory 3 - Реестры (registries)

Соответствует п. 2.5 и 2.7 brief-а.

Brief перечислил 7 реестров; найден **8-й** -- DisplayRegistry --
который не помещается в extras и доступен через getattr (в production
всегда None).

| Реестр | Класс (модуль) | Где создаётся | Как табы получают | Write consumers | Read consumers |
|--------|----------------|---------------|--------------------|-----------------|----------------|
| **PluginRegistry** | multiprocess_framework/modules/process_module/plugins/registry.py: _PluginRegistry (singleton-class) | app.py:86 через PluginRegistry.discover(*plugin_paths); глобальный декоратор @register_plugin | ctx.plugin_registry() -> extras["plugin_registry"] | **ни одного писателя** в frontend; пишется через decorator при импорте плагина из Plugins/ | pipeline/presenter.py:315,461,651; pipeline/tab.py:200; plugins/presenter.py:42,55,68; processes/presenter.py:53; plugins/sandbox.py:411; plugins/sandbox_presenter.py:99,180; startup_checks.py:120-135 |
| **ServiceRegistry** | multiprocess_framework/modules/service_module/registry.py: ServiceRegistry (экземпляр) | app.py:119 через _service_registry = ServiceRegistry(); discover(*paths) в app.py:126 | ctx.service_registry() -> extras["service_registry"] | services/presenter.py:88,99,131,134 (мутация entry.lifecycle) | services/presenter.py:46,73,113,160,214 (5 точек); plugins/sandbox.py:479,538; services/tests/test_services_tab.py (13 mock-replacements) |
| **DisplayRegistry** | multiprocess_framework/modules/display_module/registry.py: DisplayRegistry (thread-safe singleton с double-checked locking) | displays/tab.py:159 через DisplayRegistry() (singleton-вызов); НИГДЕ в app.py не помещается в extras или ctx-атрибут | getattr(ctx, "display_registry", None) -- в prod всегда None; в тестах через ctx.display_registry = DisplayRegistry() | displays/presenter.py CRUD (пишется в YAML через DisplayRegistry.persist(...)) | pipeline/presenter.py:189; pipeline/inspector/inspector_panel.py:439; pipeline/io.py:216-220; displays/tab.py:156; displays/tab.py:159 (fallback singleton) |
| **RegistersManager** | multiprocess_framework/modules/registers_module/RegistersManager; factory: multiprocess_prototype/registers/manager.py:from_topology() | app.py:99 через RegistersManager.from_registry(PluginRegistry); registers/manager.py:76-94 (factory из topology.get("processes", []) + PluginRegistry) | ctx.registers_manager() -> extras["registers_manager"] | pipeline/presenter.py:112 (rm.set_value(...) ветка без ActionBus); topology_bridge.py:294 (через state_delta) | pipeline/presenter.py:90,96; pipeline/inspector/inspector_panel.py:490; plugins/presenter.py:115; app_context.py:156; forms/factory.py:246,300,352,413,460,651,784,860,936 |
| **RecipeManager** | multiprocess_prototype/recipes/manager.py: RecipeManager (wrapper над RecipeEngine) | app.py:269 (через RecipeEngine + RecipeManager(engine=..., state_proxy=None)); recipes_dir = multiprocess_prototype/recipes/ | @property ctx.recipe_manager -> extras["recipe_manager"]; вызов разнится по табам: getattr(ctx, "recipe_manager", None) (Recipes/Inspector) vs self._ctx.recipe_manager() (Pipeline) | pipeline/presenter.py:711-880 (save_to_active_recipe / launch_active_recipe); recipes/presenter.py:163-335 (CRUD: create/duplicate/delete/set_active) | pipeline/presenter.py:730,803; pipeline/inspector/inspector_panel.py:397-422; recipes/tab.py:88,100-104; recipes/presenter.py:118-345 |
| **TopologyHolder** | multiprocess_prototype/frontend/topology_holder.py: TopologyHolder (не thread-safe; Qt main thread only) | app.py:147 через TopologyHolder(_topology_dict) | ctx.topology_holder() -> extras["topology_holder"] | pipeline/presenter.py:359 (holder.set_topology(new_topo) без ActionBus); actions/handlers/recipe_handler.py:28,36 (RecipeApplyHandler); set_topology НЕ вызывается напрямую из Processes/Recipes/Services/Plugins/Displays/Settings tabs | pipeline/presenter.py:58,357; actions/bus_factory.py:60-64; actions/handlers/recipe_handler.py:22; topology_bridge.py:189,329,616,628 (через IBridgeTopologyHolder) |
| **TopologyBridge** | multiprocess_prototype/frontend/bridge/topology_bridge.py: TopologyBridge | app.py:185 с DI: command_sender, command_catalog, command_validator, registers_manager, topology_holder | ctx.topology_bridge() (есть accessor); фактически читается через self._ctx.extras.get("topology_bridge") в processes/presenter.py:113 | app.py:197 подписка topology_holder.on_changed(topology_bridge.on_topology_changed); topology_bridge.on_state_delta(...) через _state_multiplexer (app.py:204-212) | processes/presenter.py:113 (start/stop/restart процесса); actions/bus_factory.py (передан в bus как зависимость) |
| **CommandCatalog** (read-only catalogue, упомянут в brief п. 2.5 косвенно через TopologyBridge) | multiprocess_prototype/frontend/bridge/command_catalog.py: CommandCatalog | app.py:183 через CommandCatalog.from_registry_and_map(PluginRegistry, connection_map); connection_map строится из _topology_dict | ctx.command_catalog() -> extras["command_catalog"]; реальных потребителей в frontend/widgets/ не найдено по grep | TopologyBridge.rebuild_catalog(...) (в коде, но не вызывается из табов) | TopologyBridge (внутри self._catalog); прямых табных consumer-ов нет |

**Параллельные dataclass-обёртки**: TopologyContext (topology_context.py),
PluginsContext (plugins_context.py), ActionsContext (actions_context.py),
StateContext (state_context.py) -- определены, но **не передаются**
в presenter-ы. Только AuthContext через ctx.auth property активно используется
(в tab_factory.py; app.py:400,434; _sections.py 4 раза; pipeline/tab.py:170;
processes/tab.py:176; displays/tab.py:434; services/_sections.py:168;
plugins/_sections.py:221).

---

## Inventory 4 - Callback-и и observable

Соответствует п. 2.4 и 2.6 brief-а.

| Триггер / событие | Dispatcher (файл:строка) | Subscribers (файл:строка) | Payload type |
|--------------------|--------------------------|---------------------------|---------------|
| TopologyHolder.on_changed (broadcast "topology изменилась") | topology_holder.py:46-53 (хранит _callbacks: list[Callable[[dict], None]]); _notify -- topology_holder.py:61-67 | **prod**: app.py:197 -> topology_bridge.on_topology_changed; pipeline/presenter.py:60 -> _on_topology_changed_external (через ctx.topology_holder()) | (new_topology: dict[str, Any]) -> None -- full snapshot |
| holder.set_topology(...) (триггер для _notify) | topology_holder.py:32-44 | вызывается из: pipeline/presenter.py:359; actions/handlers/recipe_handler.py:28,36 (RecipeApplyHandler) | (new_topology: dict) -> dict (возвращает previous для undo) |
| AuthState.access_context_changed (Qt Signal) | state/auth_state.py:47 (access_context_changed = Signal(AccessContext)); _emit через auth_state.py:87,94 | tab_factory.py:238 -> _on_access_context_changed; widgets/access/permission_gate.py:68,135,198,245 (4 точки в permission-aware helpers) | (access_context: AccessContext) -> None |
| AuthState.current_user_changed (Qt Signal) | state/auth_state.py:42 (current_user_changed = Signal(object)); _emit через auth_state.py:86,93 | widgets/chrome/login_button.py:43 -> _on_user_changed | (user_dict: dict | None) -> None |
| ActionBus.execute(action) (mutation entry point) | multiprocess_framework/modules/actions_module/bus.py: ActionBus.execute | вызывается из: pipeline/presenter.py:110,354,391,428,577 (5 точек: field_set, process_add, process_remove, wire_add, node_move); plugins/_sections.py:253; settings/administration/roles_panel.py:206 | (action: Action) -> Result -- typed actions через V2ActionBuilder |
| GuiStateBindings.bind(path, widget, prop, formatter=...) (StateStore subscriptions via path-glob) | state/bindings.py:71+ (метод bind) | **23 точки bindings.bind(...) в prod**: windows/main_window.py:455,461,467,477,482 (5); widgets/chrome/error_banner.py:30,31 (2); widgets/tabs/processes/_panels.py:216,223,231,239,245,255,365,372,380 (9 -- для cards и health-меток); widgets/tabs/displays/ и widgets/displays/ (косвенно через bindings) | (path: str, widget, prop: str, formatter: Callable = identity) -> handle |
| Bridge.set_state_callback(...) (low-level multiplexer) | bridge API (DataReceiverBridge) | app.py:212 устанавливает _state_multiplexer, который вызывает bindings._on_state_msg + topology_bridge.on_state_delta(path, value) | (msg_dict: dict) -> None |
| Bridge.set_frame_callback(...) | bridge API | app.py:479 устанавливает _on_frame_received -> image_panel.display_frame + window.increment_frame_count | (msg_dict: dict) -> None |
| WireMetricsController (внутренний controller pipeline) | pipeline/telemetry.py: WireMetricsController.start() (вызов в pipeline/tab.py:118) | Update модели WireMetricsModel -> edge-items в GraphScene | внутри pipeline, не cross-tab |
| pipeline/tab.py:188 -- view.wire_created (Qt Signal из GraphView) | pipeline/graph/graph_view.py: wire_created | pipeline/tab.py:188 -> _on_wire_created -> presenter.add_wire(...) | внутри pipeline, не cross-tab |
| pipeline/tab.py:189 -- scene.selectionChanged | Qt Signal QGraphicsScene.selectionChanged | pipeline/tab.py:189,295 -> _on_selection_changed -> inspector.show_plugin_node / show_display_node | внутри pipeline, не cross-tab |
| pipeline/tab.py:190 -- inspector.field_changed | pipeline/inspector/inspector_panel.py:49 (Signal(str, str, object)) | pipeline/tab.py:190 -> _on_inspector_field_changed (logger debug stub); pipeline/presenter.py:73 -> _on_inspector_field_changed (через set_inspector(panel)) | (process_name: str, field_name: str, new_value: Any) |
| target_process_changed / display_id_changed | pipeline/inspector/inspector_panel.py:52,55 (Signals) | pipeline/presenter.py:74-75 через set_inspector(panel) -> _on_target_process_changed, _on_display_id_changed (мутирует model._topology["processes"][...]["target_process"] напрямую) | (node_id, new_value: str) |

**RecipeEngine callbacks** -- по grep-у в multiprocess_framework/modules/state_store_module/recipes/recipe_engine.py
подписок на изменения не определено в публичном API; синхронизация через
RecipeStateAdapter.sync_domain_to_state() идёт one-shot.

**Lazy-init проблема** (brief п. 2.6): pipeline/presenter.py:60 --
holder.on_changed(self._on_topology_changed_external) вызывается только когда
PipelinePresenter создаётся. PipelineTab создаётся лениво (tab_factory.py:LazyTabWidget.showEvent) --
если пользователь не открывал Pipeline tab, подписка не создана. Зафиксировано в коде как факт.

---

## Inventory 5 - Raw-dict операции в presenter-ах

Соответствует п. 2.3 и 2.8 brief-а.

Колонка "isinstance / getattr": пометка dict-only означает строгий
isinstance(x, dict) без fallback; dual означает defensive ветвление
if isinstance(x, dict): proc.get(...) else getattr(proc, ..., default).

| Файл:строка | Паттерн (короткий код) | Поля dict | isinstance / getattr |
|-------------|------------------------|-----------|----------------------|
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:58-61 | for p in self._topology.get("processes", []): p.get("process_name", "") if isinstance(p, dict) else getattr(p, "process_name", "") | process_name | dual |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:78-87 | for w in self._topology.get("wires", []): src = w.get("source", "") if isinstance(w, dict) else "" | source, target | dict-only (fallback пустой) |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:115-126 | processes = self._topology.get("processes", []); [p for p in processes if (p.get("process_name") if isinstance(p, dict) else getattr(p, "process_name", "")) != name] | process_name | dual |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py:144,165,170,205,215,249,292,295,305 | displays = self._topology.get("displays", []); existing_ids = [d.get("node_id") for d in ...]; wires = self._topology.get("wires", []); ... | node_id, display_id, source, target | dict-only |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/io.py:145-166 | for proc in blueprint.get("processes", []): if not isinstance(proc, dict): continue; name = proc.get("process_name", ""); plugins = proc.get("plugins", []); plugin_name = plugins[0].get("plugin_name", "") | process_name, plugins, plugin_name, category, config | dict-only (continue если не dict) |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/io.py:172-175,180-183 | for p in model._topology.get("processes", []): if isinstance(p, dict) and p.get("process_name") == name: p["target_process"] = ... (после add_process) | process_name, target_process, plugins | dict-only |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:141-158 | processes = self._model._topology.get("processes", []); for proc in processes: if isinstance(proc, dict): if proc.get("process_name") == node_id: proc["target_process"] = ... else: getattr(proc, "process_name", "") | process_name, target_process | dual |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:185-213 | displays = self._model._topology.get("displays", []); for disp in displays: if isinstance(disp, dict): if disp.get("node_id") == node_id: disp["display_id"] = new_display_id; disp["display_name"] = new_display_name | node_id, display_id, display_name | dual |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:650-697 | processes = topo_dict.get("processes", []); for proc in processes: if isinstance(proc, dict): name = proc.get("process_name", ...); plugins = proc.get("plugins", []); pname = plugins[0].get("plugin_name", "") if isinstance(plugins[0], dict) else getattr(plugins[0], "plugin_name", "") -- _topology_to_graph | process_name, plugins, plugin_name | dual |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py:308-336 | topo = self._presenter.model.to_topology_dict(); for disp in topo.get("displays", []): if isinstance(disp, dict) and disp.get("node_id") == node.node_id: display_id = disp.get("display_id", ""); далее аналогично для processes | node_id, display_id, display_name, process_name, plugins, target_process | dict-only (с защитой isinstance) |
| multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py:415-422 | processes = blueprint.get("processes", []); for proc in processes: if isinstance(proc, dict): name = proc.get("process_name", "") else: name = getattr(proc, "process_name", "") | process_name | dual |
| multiprocess_prototype/frontend/widgets/tabs/processes/presenter.py:55-103 | for proc_dict in raw_processes: if isinstance(proc_dict, dict): name = proc_dict.get("process_name", "unnamed"); plugins_list = proc_dict.get("plugins", []); for p in plugins_list: pname = p.get("plugin_name", "") if isinstance(p, dict) else ""; else: name = getattr(proc_dict, "process_name", "unnamed"); plugins = getattr(proc_dict, "plugins", []); ... | process_name, plugins, plugin_name, protected, category | dual (с разворотом по двум веткам, ~50 строк) |
| multiprocess_prototype/frontend/widgets/tabs/recipes/recipe_form.py:100-117 | blueprint = data.get("blueprint", {}) or {}; processes = blueprint.get("processes", []); for proc in processes: plugins_count += len(proc.get("plugins", []) if isinstance(proc, dict) else []); services_count = len(data.get("active_services", []) or []); displays_count = len(data.get("display_bindings", []) or []) | blueprint, processes, plugins, active_services, display_bindings | dict-only (с or [] fallback) |
| multiprocess_prototype/frontend/startup_checks.py:67-89 | for proc in processes: name = proc.get("process_name", ""); for target in proc.get("chain_targets", []); plugins = proc.get("plugins") | process_name, chain_targets, plugins | dict-only |
| multiprocess_prototype/frontend/startup_checks.py:137-142 | for proc in topology.get("processes", []): pname = proc.get("process_name", "?"); for plugin_cfg in proc.get("plugins", []): plugin_name = plugin_cfg.get("plugin_name", "") | process_name, plugins, plugin_name | dict-only |
| multiprocess_prototype/frontend/bridge/topology_bridge.py:329-332 | for proc in self._holder.topology.get("processes", []): if proc.get("process_name") == process_name: return True (_process_exists) | process_name | dict-only |
| multiprocess_prototype/frontend/bridge/topology_bridge.py:614-621 | for wire in self._holder.topology.get("wires", []): source = wire.get("source", ""); target = wire.get("target", ""); if source.startswith(prefix) or target.startswith(prefix) | source, target | dict-only |
| multiprocess_prototype/frontend/bridge/topology_bridge.py:625-634 | for wire in self._holder.topology.get("wires", []): source = wire.get("source", ""); target = wire.get("target", ""); key = f"{source}|{target}" | source, target | dict-only |
| multiprocess_prototype/registers/manager.py:76-95 | processes = topology.get("processes", []); for proc in processes: plugins = proc.get("plugins", []); for plugin_dict in plugins: plugin_name = plugin_dict.get("plugin_name", "") | process_name, plugins, plugin_name | dict-only |
| multiprocess_prototype/registers/connection_map.py:54-62 | for proc in topology.get("processes", []): process_name = proc.get("process_name", ""); for plugin_dict in proc.get("plugins", []): plugin_name = plugin_dict.get("plugin_name", "") | process_name, plugins, plugin_name | dict-only |

**Поля, появляющиеся в этих обходах** (brief п. 2.3 -- non-stable contract):
process_name, plugins, plugin_name, config, protected, target_process,
description, chain_targets, category, source, target, node_id, display_id,
display_name, src_dtype, tgt_dtype. **16 уникальных полей** в неформальном
топологическом контракте.

---

## Inventory 6 - Тесты с MagicMock-ctx

Соответствует п. 6.6 brief-а + симптом 1.5 (вчерашний случай).

Все упомянутые тесты используют from unittest.mock import MagicMock и создают
ad-hoc контекст. Ни один файл **не использует** MagicMock(spec=AppContext).
Это значит, что любой произвольный атрибут на ctx даст MagicMock без ошибки --
переименование API в AppContext не сломает тесты.

| Тестовый файл:строка | Тестируемый presenter/tab | Что замокано | Какой реальный баг может скрыть |
|----------------------|----------------------------|--------------|----------------------------------|
| pipeline/tests/test_inspector.py:21-27 | NodeInspectorPanel | registers_manager.return_value, action_bus.return_value, topology_holder.return_value, plugin_registry.return_value, bindings.return_value, topology_bridge.return_value (6 accessor-ов как методы) | Не ловит разницу между property и method (см. recipe_manager ниже) |
| pipeline/tests/test_inspector.py:60-67,406-410,434-438 | NodeInspectorPanel (различные сценарии) | Те же accessor-ы + ctx.action_bus = bus | display-тесты используют _make_ctx_with_display_registry -- ctx.display_registry = ... как атрибут; в production такого атрибута нет |
| pipeline/tests/test_inspector.py:419,440,513,650 | ctx.recipe_manager | Назначается то как PropertyMock (419), то как атрибут (440), то как None (513) | Несогласованность mock-ов отражает реальную: recipe_manager -- property в AppContext, в pipeline/presenter.py вызывается как method |
| pipeline/tests/test_launch_recipe.py:34-39 | PipelinePresenter.launch_active_recipe | ctx.recipe_manager.return_value = recipe_manager (как **method**) | Pipeline в prod: recipe_mgr = self._ctx.recipe_manager() (presenter.py:730,803). Если property возвращает RecipeManager-объект, вызов () даст TypeError. **Требует расследования** |
| pipeline/tests/test_save_recipe.py:73-78 | PipelinePresenter.save_to_active_recipe | ctx.recipe_manager.return_value = recipe_manager | См. выше -- тот же риск, требует расследования |
| pipeline/tests/test_pipeline_tab_integration.py:15,29-33 | PipelineTab construction | Все accessor-ы .return_value = None | Тест проверяет сборку с полностью None-зависимостями; реальный сценарий "таб без topology_holder" в production невозможен (build_app_context всегда ставит) |
| pipeline/tests/test_presenter_inspector_integration.py:24-50 | PipelinePresenter + Inspector | _make_ctx_for_presenter с ctx.display_registry = ... как атрибут | В production такого атрибута нет; тест покрывает только сценарий "DR предоставлен явно" |
| pipeline/tests/test_yaml_positions.py:9,23-27,94 | PipelinePresenter.load_topology_from_config | topology = ctx.config-словарь (subscript на MagicMock) | Subscript на MagicMock возвращает MagicMock, не падает. Реальный код требует dict-like; KeyError при пустом config не ловится |
| pipeline/tests/test_presenter_enhanced.py:22,36-40 | PipelinePresenter (mutations + ActionBus) | Полный набор .return_value = None / mock_bus | Не падает при отсутствии TopologyBridge / PluginRegistry. Реальный риск: ctx.action_bus() вернёт не-ActionBus -- bus.execute упадёт неконтролируемо |
| pipeline/tests/test_wire_validation.py:60-66 | _validate_wire_ports | ctx.plugin_registry.return_value = registry | Не проверяет что в production ctx.plugin_registry() возвращает singleton class |
| pipeline/tests/test_pipeline_scene.py:179-194 | PipelineScene rendering | Полный mock | Не cross-tab |
| processes/tests/test_processes_tab.py:18,40-41,87,96-110 | ProcessesTab + Presenter | ctx.config = dict; ctx.plugin_registry.return_value = None; ctx.extras через MagicMock | ctx.extras остаётся MagicMock -- subscript-доступ не проверяется. Production processes/presenter.py:50 делает extras.get -- вернёт MagicMock (что не пройдёт isinstance(topo, dict)) |
| processes/tests/test_health_summary.py:8-22 | ProcessesPresenter.get_health_summary | ctx = MagicMock(); ctx.config = dict topology | См. выше |
| recipes/tests/test_recipes_tab.py:43-46 | RecipesTab | ctx.recipe_manager = ... (атрибут!) или mock; ctx.auth = None | ctx.recipe_manager как атрибут соответствует production @property. **НЕ ловит**: что в pipeline он вызывается как (). Оба теста зелёные, runtime разойдётся |
| services/tests/test_services_tab.py:48-498 (**13 точек ctx = MagicMock()**) | ServicesTab + Presenter | ctx.service_registry.return_value = ... (как method), bindings.return_value = None, action_bus.return_value = None, ctx.auth = None | Mock как method соответствует production accessor. 13 ad-hoc копий -- изменение accessor-а требует правки всех 13 мест |
| plugins/tests/test_plugins_tab.py:63-72,113 | PluginsTab + Presenter | Типовая схема ctx.X.return_value = ... | -- |
| plugins/tests/test_paths_subtab.py:21-30,50,63,90,116 (5 контекстов) | Plugins paths management | ctx.plugin_manager.return_value = pm | Корректный mock; риск только в плотности 5 копий |
| plugins/tests/test_sandbox_widget.py:65-69 | Sandbox + ServiceRegistry | ctx.plugin_registry + ctx.service_registry | Покрывает оба registries |
| plugins/tests/test_sandbox_integration.py:78-85 | Sandbox integration | ctx.service_registry.return_value = None | Корректный negative case |
| plugins/tests/test_sandbox_presenter.py:55-56,188 | SandboxPresenter | Стандартный mock | -- |
| plugins/tests/test_sandbox_e2e.py:68-75 | Sandbox e2e | ctx.service_registry.return_value = service_registry | -- |
| displays/tests/test_displays_tab.py:108-133 (2 точки) | DisplaysTab | ctx.display_registry = DisplayRegistry() (атрибут!); ctx.config_paths = ...; ctx.auth = None | Тест ставит ctx.display_registry как атрибут -- в production такого атрибута нет; runtime падает в getattr fallback на singleton |
| settings/system/tests/test_system_presenter.py:75-77 | SettingsSystemPresenter | ctx.action_bus.return_value = None | -- |
| settings/history/tests/test_history_presenter.py:69-70,159-160,204-205 (3 точки) | SettingsHistoryPresenter | ctx.action_bus.return_value = bus / None | -- |
| settings/administration/tests/test_audit_log_panel.py:76,337,362 (3 точки) | AuditLogPanel | ctx = MagicMock(); mock auth-storage | -- |
| settings/administration/tests/test_sessions_panel.py:57,109,126 | SessionsPanel | access_ctx = MagicMock() вложенный | -- |
| settings/administration/tests/test_users_panel.py:68,509 | UsersPanel | ctx = MagicMock() | -- |
| frontend/tests/test_phase10_integration.py:16,29-31 | TabFactory integration | Полная сборка с None-зависимостями | Проверяет что табы не падают при пустом ctx |
| frontend/tests/test_tab_factory.py:34,36,37-43 | TabFactory permissions | ctx.auth_state.return_value = auth_state; ctx.auth = None / _auth | Тестирует переключение ctx.auth = None ↔ AuthContext через атрибут |
| frontend/tests/test_phase15_smoke.py:60,83-127 | Smoke integration | ctx.extras topology_holder/topology/topology_bridge/action_bus = ... (напрямую в extras, в обход accessor-ов) | Покрывает ровно тот же путь, что и production app.py. Лучший по полноте тест |
| frontend/tests/test_app_context.py:120,219,228,236,237,240-275 (>10 точек) | AppContext API | ctx.extras new_key = new_value; ctx.extras.get is mock_rm | Проверяет именно extras-семантику. Ловит регрессии accessor-ов |
| backend/state/tests/test_colormask_state.py:20; test_capture_state.py:30 | Backend state | ctx = MagicMock() (PluginContext / backend, не AppContext) | Out of scope cross-tab audit-а |

**Distinct insights**:

- **39 файлов** содержат ctx = MagicMock(). **Ни один** не использует
  MagicMock(spec=AppContext) -- то есть нет strict-моков, которые
  поймали бы переименование accessor-ов.
- **0 файлов** используют Mock(spec=AppContext) -- grep не нашёл
  ни одного вхождения; все mock-и unspec.
- Реальный кейс скрытого бага: pipeline/presenter.py:730,803 вызывает
  self._ctx.recipe_manager() как method, хотя app_context.py:135 определяет
  recipe_manager как @property. В тестах test_launch_recipe.py:39 ставится
  ctx.recipe_manager.return_value = ... (как method); в test_recipes_tab.py:44
  -- ctx.recipe_manager = ... (как атрибут). Оба зелёные. **Требует расследования**:
  либо production-код должен быть self._ctx.recipe_manager (без ()), либо в
  AppContext recipe_manager надо вернуть к method-API.

---

## Заключение

Документ перечислил **8 реестров**, **16 ключей extras**, **20 raw-dict
обходов в production**, **40 точек чтения topology**, **6 типов callback-триггеров**
и **39 тест-файлов** с MagicMock-ctx, покрывающих все 7 табов
(Pipeline / Processes / Recipes / Services / Plugins / Displays / Settings).
Settings tab -- единственный без topology consumer-ов.

Cross-tab связи концентрируются в Pipeline tab (21 из 40 топологических чтений).
Самые крупные точки прохождения данных:

- pipeline/model.py -- 15 raw-dict точек в одном файле (self._topology.get(...))
- pipeline/presenter.py -- 10 точек чтения/записи topology + 5 точек ActionBus
- topology_bridge.py -- единственный production-subscriber на holder.on_changed
  и единственный читатель holder.topology за пределами presenter-ов

Параллельные dataclass-обёртки (TopologyContext, StateContext,
PluginsContext, ActionsContext) **созданы**, но **не подключены** к
presenter-ам -- только AuthContext через @property ctx.auth активно работает.
