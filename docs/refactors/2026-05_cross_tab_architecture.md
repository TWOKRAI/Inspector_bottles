# Refactor brief — Cross-tab architecture, domain models, single source of truth

**Дата:** 2026-05-27
**Статус:** brief / problem statement, ещё **не утверждено**
**Где обсуждаем:** новый чат, после approval плана

---

## 1. Зачем этот документ

Прототип вырос до 7 табов (Settings / Recipes / Processes / Services / Plugins / Pipeline / Displays).
Каждый таб — самостоятельный MVP-модуль, но **между ними нет общей доменной модели**.
Обмен данными идёт через ad-hoc-точки:

- `AppContext.extras` — dict-bag без типов (`ctx.extras["topology_holder"]`, `["service_registry"]`, `["recipe_manager"]`...).
- `TopologyHolder` с `on_changed(callback)` — один broadcast «topology changed», без типов событий.
- Каждый presenter сам читает raw-`dict` topology и интерпретирует его по-своему (`topology.get("processes", [])` встречается в 10+ местах).
- Рецепты (`RecipeManager`) хранят blueprint **отдельно** от TopologyHolder и синхронизируются вручную.
- Конфиги сервисов (`config_defaults`, `user_overrides.yaml`) живут отдельной жизнью.
- Registers (`RegistersManager`) — отдельная система для параметров плагинов, не интегрирована с TopologyHolder.

**Симптом:** простое действие «создал процесс в табе Процессы → должен появиться в Pipeline» в недавнем сеансе потребовало:
1. Поправить чтение в `ProcessesPresenter.get_processes` (раньше читал только `config["topology"]`).
2. Поправить `PipelinePresenter.load_topology_from_config` (читал только `config["topology"]`, lazy load пропускал live state).
3. Добавить grid-позиции для новых нод (`_on_topology_changed_external` ставил все новые в (0, 0)).
4. Добавить логирование, потому что stdlib `logger` не пишет в общий loguru-канал и отладка наугад.
5. Reveal-flow (auto-switch на Pipeline + `centerOn`), чтобы пользователь увидел результат.

Каждый из этих фиксов — заплатка на симптом, а не на причину. Причина одна: **нет единой доменной модели и нет типизированных событий, у каждого таба свой источник истины**.

---

## 2. Текущая картина (как есть)

### 2.1. AppContext = бесформенный bag

[`multiprocess_prototype/frontend/app_context.py`](../../multiprocess_prototype/frontend/app_context.py)

```python
@dataclass
class AppContext:
    process: GuiProcess
    command_sender: CommandSender
    bridge: DataReceiverBridge
    config: dict[str, Any]
    extras: dict[str, Any]  # ← god-bag

    def topology_holder(self) -> TopologyHolder | None: ...
    def service_registry(self) -> ServiceRegistry | None: ...
    def plugin_registry(self) -> Any | None: ...
    def recipe_manager(self) -> Any | None: ...
    def registers_manager(self) -> RegistersManager | None: ...
    def action_bus(self) -> ActionBus | None: ...
    def topology_bridge(self) -> TopologyBridge | None: ...
    def command_catalog(self) -> CommandCatalog | None: ...
    def bindings(self) -> GuiStateBindings | None: ...
    def auth() -> AuthContext | None: ...
    # ... ещё ~6 method-accessor'ов
```

Все 15+ зависимостей — `Optional`, могут быть None, тип `Any`. Каждый consumer проверяет `if ... is None`.
Тестовые контексты используют `MagicMock` → легко скрыть баг.

### 2.2. Topology stored в трёх местах

| Где | Что | Когда | Кто пишет |
|-----|-----|-------|-----------|
| `ctx.config["topology"]` | стартовый snapshot из `DEFAULT_BLUEPRINT.yaml` | при старте app | `app.py:142` |
| `ctx.extras["topology"]` | копия для legacy fallback | при старте app | `app.py:174` |
| `TopologyHolder.topology` | live state с уведомлениями | при каждом изменении | Pipeline / Processes / Recipes |

`config` и `extras["topology"]` **никогда не обновляются** после старта. Если consumer читает оттуда — он видит начальное состояние навсегда.

**Эти три места считаются «эквивалентными» в fallback-chains** в `ProcessesPresenter.get_processes`, `PipelinePresenter.load_topology_from_config`, `TopologyBridge` — но это не так.

### 2.3. Domain model = raw dict

Нет классов `Process`, `Plugin`, `Wire`, `Display`. Везде работают с raw dict вида:

```python
{
  "process_name": "cam",
  "plugins": [{"plugin_name": "capture"}, {"plugin_name": "blur"}],
  "config": {...},
  "protected": False,
  "target_process": "...",   # появилось в Phase 7a
  "description": "...",      # появилось вчера
}
```

Поля **появляются и исчезают** по ходу эволюции. Никто не знает полный contract.
Pydantic-схема `SystemBlueprint` существует в framework, но prototype работает с dict-ами вокруг него (см. правило `Dict at Boundary`).

Низкоуровневые операции дублируются:

```python
# В 10+ местах:
for proc in topology.get("processes", []):
    name = proc.get("process_name") if isinstance(proc, dict) else getattr(proc, "process_name", "")
    plugins = proc.get("plugins", []) or []
    for p in plugins:
        pname = p.get("plugin_name", "") if isinstance(p, dict) else str(p)
        ...
```

См. `pipeline/model.py`, `pipeline/presenter.py`, `pipeline/io.py`, `processes/presenter.py`, `topology_bridge.py`, `startup_checks.py`, `recipe_form.py`.

### 2.4. События = один broadcast без типов

[`TopologyHolder._notify`](../../multiprocess_prototype/frontend/topology_holder.py):

```python
def _notify(self, topology):
    for cb in self._callbacks:
        try:
            cb(topology)
        except Exception:
            logger.exception(...)
```

Один callback `(new_topology) -> None`. Подписчик получает **полное состояние**, должен сам понять, что изменилось.

Pipeline на любое изменение делает `scene.load_from_data(nodes, edges)` — полная перерисовка. Теряются позиции (если не успели cache'нуть), теряется selection, теряется in-flight редактирование.

Нет событий уровня домена: `ProcessAdded(name)`, `PluginAdded(process, plugin, index)`, `WireConnected(src, tgt)`, `RecipeActivated(slug)`.

### 2.5. Реестры живут параллельно с topology

| Реестр | Кто хранит | Кто читает |
|--------|-----------|------------|
| **PluginRegistry** | глобальный singleton (decorator `@register_plugin`) | Pipeline palette, Plugins tab, Inspector, RegistersManager, RecipeForm |
| **ServiceRegistry** | singleton после `discover()` | Services tab, RecipeForm |
| **DisplayRegistry** | (state, оптимизировано) | Displays tab, Pipeline (через `ctx.display_registry`) |
| **RegistersManager** | от PluginRegistry + topology | Inspector, settings forms |
| **RecipeManager** | files `recipes/*.yaml` | Recipes tab, Pipeline (launch/save) |
| **TopologyHolder** | live dict | Pipeline, Processes, Services-adapter (none), TopologyBridge |
| **TopologyBridge** | proxy к runtime через IPC | используется при mutation |

Это **7 параллельных хранилищ** с пересекающимися данными. Например:
- В рецепте `active_services: ["webcam_camera"]` — это **строка**.
- В ServiceRegistry эту строку нужно разрешить в class + meta.
- В UI на Recipes tab показываем title из meta.
- В Services tab показываем lifecycle.
- При запуске рецепта (`replace_blueprint`) сервис не запускается автоматически — это отдельная ручная операция.

### 2.6. Lazy табы + подписки = пропуск событий

Все табы lazy. Подписка `Pipeline._on_topology_changed_external` срабатывает только если PipelineTab уже был инициализирован.

Если пользователь:
1. Запустил app.
2. Сразу зашёл в Processes → создал процесс.
3. Переключился в Pipeline.

Pipeline ещё не существовал → подписки не было → callback не приходил. Lazy-init читает из TopologyHolder вручную (мы поправили это вчера). Но это **подмена pattern**: вместо «события + подписка» получается «pull при init + событие после init».

### 2.7. Mutation rules не выровнены

Pipeline tab пишет в topology через `holder.set_topology(new_topo)`, при этом параллельно может работать ActionBus с undo/redo.
Processes tab пишет напрямую в holder (мы вчера добавили). Без ActionBus → нельзя откатить.
Recipes tab пишет в файл YAML напрямую, минуя holder.

Никаких инвариантов: «все mutation идут через X» — нет.

### 2.8. UI ↔ domain coupling

Inspector / palette / nav-tree / detail-card в каждом табе хардкодят форму данных:
- `process.plugins[0].plugin_name` в Pipeline scene
- `process["plugins"]` в Processes panel
- `recipe["blueprint"]["processes"]` в Recipes form

Изменение схемы топологии (например, переименовать `plugins` в `chain`) ломает 15 мест.

---

## 3. Что вижу как причину, не симптом

Сводно:

1. **Нет доменного слоя.** Есть `dict`-топология (boundary), но нет stable in-memory модели с типизированными операциями. Каждый таб делает свою «модель» из dict-а.

2. **Нет шины событий с типами.** Один callback на «всё изменилось» = каждый подписчик re-implements diff и реакцию.

3. **Нет явных границ модулей.** `AppContext.extras` — дырявая абстракция, любой может добавить ключ; consumer не знает требуемые ключи.

4. **State и runtime смешаны.** `TopologyHolder` — это и UI editor state (черновик графа), и snapshot прод-runtime. Это разные жизненные циклы — но один объект.

5. **Реестры не часть модели.** `PluginRegistry`, `ServiceRegistry`, `DisplayRegistry` — read-only catalogues. Topology ссылается на них по строковому имени. Связь не enforced (можно записать в process `plugin_name="nonexistent"` — увидим только через `StartupChecker`).

6. **Lazy + подписки = неконсистентность.** Lazy-инициализация табов сама по себе нормальна, но требует, чтобы каждый таб при первом show заново синхронизировался. Сейчас это вручную (load_topology_from_config + on_changed).

---

## 4. Куда хочу прийти (target)

### 4.1. Слои

```
┌────────────────────────────────────────────────────────────────┐
│  UI (Tabs, Inspectors, Dialogs) — только bind на observable    │
│  модели, никакого raw-dict внутри.                              │
└──────────────────────────────┬─────────────────────────────────┘
                               │ observe / dispatch
┌──────────────────────────────┴─────────────────────────────────┐
│  ViewModels / Presenters per tab                                │
│  Подписываются на доменные события, рендерят свой состав.       │
└──────────────────────────────┬─────────────────────────────────┘
                               │ commands / queries
┌──────────────────────────────┴─────────────────────────────────┐
│  Domain layer (single source of truth)                          │
│   • Project        — корневой агрегат: pipeline + recipes       │
│   • Pipeline       — Processes, Plugins (chain), Wires, Displays│
│   • Process        — name, description, plugins[], config,...    │
│   • Plugin         — ref в registry + params                    │
│   • Service        — ref в registry + config + lifecycle        │
│   • Display, Wire, RecipeRef — value-объекты                    │
│   События: ProcessAdded, PluginAdded, WireConnected, ...        │
└──────────────────────────────┬─────────────────────────────────┘
                               │ uses
┌──────────────────────────────┴─────────────────────────────────┐
│  Catalogs (read-only, framework-supplied)                       │
│  PluginCatalog, ServiceCatalog, DisplayCatalog                  │
│  Resolve(name) → spec (ports, config_schema, register fields).  │
└──────────────────────────────┬─────────────────────────────────┘
                               │ persistence / IPC
┌──────────────────────────────┴─────────────────────────────────┐
│  Adapters: YAML I/O, RecipeStorage, ProcessManagerProxy (IPC)   │
│  Доменный → dict at boundary.                                   │
└────────────────────────────────────────────────────────────────┘
```

### 4.2. Принципы

1. **Single Source of Truth.** Один `Project` объект на app session. Все табы читают из него и пишут через типизированные команды.

2. **Доменные события, не «topology changed».** События типа:
   - `ProjectEvents.process_added(process_id)`
   - `ProjectEvents.process_removed(process_id)`
   - `ProjectEvents.plugin_inserted(process_id, plugin_id, index)`
   - `ProjectEvents.wire_connected(src, tgt)`
   - `ProjectEvents.service_config_changed(service_id)`
   - `ProjectEvents.recipe_activated(slug)`

   Подписчик подписывается на конкретное событие, а не на «всё».

3. **Типы вместо dict в UI.** UI работает с `Process` / `Plugin` / etc. Сериализация в dict — только в adapter'ах persistence/IPC.

4. **Catalog ⇔ Instance.** Каталог даёт спеки (Plugin metadata, Service config_schema). Domain хранит instances со ссылкой на спеку. Resolve happens в одном месте.

5. **AppServices = типизированный DI.** Заменить `ctx.extras` на `AppServices` dataclass с явными полями. Optional → факультативные fields. Нет dict-доступа.

6. **Commands (для undo) + Queries (для UI).** Mutation через CommandBus с типами (`AddProcess(name)`, `InsertPlugin(process_id, plugin_name, position)`). Queries — read-only.

7. **Editor state vs runtime state.** Разделить:
   - `Project` (то, что редактирует пользователь — draft графа).
   - `RuntimeSnapshot` (текущее состояние ProcessManager: PID'ы, lifecycle, метрики).
   Сейчас всё в одном `TopologyHolder`.

### 4.3. Конкретные cross-tab сценарии после рефакторинга

| Сценарий | Сейчас | Должно быть |
|----------|--------|-------------|
| Создал процесс в Processes → видно в Pipeline | 5 фиксов, lazy-load pull, grid-pos hack, reveal-tab hack | dispatch `AddProcess` → `process_added` event → Pipeline ViewModel обновляет свою observable list → scene добавляет ровно одну ноду. Без полной перерисовки. |
| Активировал рецепт → процесс с camera → автостарт сервиса webcam_camera | сейчас не делается | команда `ActivateRecipe(slug)` → выявляет `services_required`, спрашивает / стартует через ServiceLauncher |
| Параметр плагина изменился в Inspector | через RegistersManager + ActionBus + topology_holder, 3 разных пути | команда `SetPluginParam(process_id, plugin_id, field, value)` → event → UI updates |
| Удалил процесс в Processes → wire'ы исчезли в Pipeline | каскадное удаление в `PipelineModel.remove_process` + scene re-load | команда `RemoveProcess` → каскад в domain → события `process_removed`, N×`wire_removed` |
| Recipe form показывает «параметры из используемых плагинов/сервисов» | вчера сделал tree dump из dict | bind на доменную `Recipe.process_chain()` → автогенерация по структуре |

---

## 5. Scope / план фаз

### Phase A — Audit (1-2 дня)
- Полный inventory всех потребителей `topology`, `ctx.extras`, реестров.
- Карта событий и подписок.
- Список raw-dict операций (для замены на доменные API).
- Список тестов с MagicMock-контекстом (для замены на builder).
- **Deliverable:** `docs/refactors/2026-XX_cross_tab_audit.md` (artefact: graphviz, csv).

### Phase B — Domain skeleton (3-5 дней)
- Создать `multiprocess_prototype/domain/` пакет:
  - `project.py` — корневой агрегат.
  - `process.py`, `plugin.py`, `service.py`, `display.py`, `wire.py`.
  - `events.py` — типизированные события (dataclass'ы).
  - `commands.py` — типизированные команды.
  - `event_bus.py` — pub/sub с типами.
- **Не подключать к UI yet.** Тесты на доменную логику в изоляции.
- **Deliverable:** Domain без зависимостей от Qt/framework.

### Phase C — Adapters (2-3 дня)
- `adapters/yaml_io.py` — Project ↔ blueprint dict (для YAML и IPC).
- `adapters/topology_holder_compat.py` — bridge между новым domain и existing TopologyHolder (для постепенной миграции).
- `adapters/process_manager.py` — domain commands → IPC к ProcessManager.
- **Deliverable:** Domain читается/пишется из всех источников.

### Phase D — AppServices DI (1 день)
- Заменить `AppContext.extras` на `AppServices` dataclass.
- Все табы получают `AppServices`, а не dict.
- **Deliverable:** Type-safe DI, deprecation warnings на `extras`.

### Phase E — Migrate per-tab (5-10 дней, по табу за заход)
Очерёдность по выгоде:
1. **Pipeline tab** — самый сложный, больше всех читает/пишет topology.
2. **Processes tab** — простой consumer, минимум mutation.
3. **Recipes tab** — переход на доменный `Recipe` + `Project.activate(recipe)`.
4. **Services tab** — мало взаимодействия с topology, но интегрируется с recipes.
5. **Plugins tab** — read-only от catalog'а, прост.
6. **Displays tab** — аналогично.
7. **Settings tab** — отдельная история (это persistent prefs).

Каждый таб мигрируется отдельной веткой, со своими тестами. Старый код остаётся, пока все табы не переехали.

### Phase F — Удаление legacy (1-2 дня)
- Удалить `ctx.extras["topology"]` и `ctx.config["topology"]` после миграции последнего consumer'а.
- Удалить fallback chains.
- Удалить `TopologyHolder` или редуцировать до compat-adapter'а.

### Phase G — UX-фишки, которые становятся легче (по 0.5-1 дню)
- Auto-reveal новых нод в Pipeline (уже сделали как hack — стать встроенным).
- Validation real-time: «процесс без плагинов запустить нельзя» — domain-level check.
- Cross-tab linking: клик по сервису в Recipes form → переключение на Services tab с этим сервисом.
- Diff-view рецепта vs текущего Project.

---

## 6. Открытые вопросы (обсудить в новом чате до фазы B)

1. **Pydantic v2 vs dataclass для domain?**
   Pydantic даёт сериализацию из коробки, но тяжелее. Dataclass + ручной to_dict проще, но добавляет boilerplate. Учитывая `Dict at Boundary` rule — склоняюсь к **dataclass + явные adapter'ы**.

2. **Editor state vs Runtime state — два отдельных aggregate?**
   Похоже да. `Project` = редактируемый draft (как у IDE). `RuntimeSnapshot` = read-only зеркало ProcessManager. Connect только в одну сторону: snapshot → Project (для отображения live-метрик). User-edits идут только в Project.

3. **EventBus implementation: signals (Qt) или Pure Python?**
   Domain должен быть UI-agnostic → Pure Python. UI-уровень оборачивает в Qt signals (как делает `bindings.GuiStateBindings` для StateProxy).

4. **Команды/undo vs прямые мутации?**
   ActionBus уже есть (`V2ActionBuilder`). Логично, чтобы все mutation Project'а шли через ActionBus → undo автоматический. Но требует декомпозиции существующего ActionBus.

5. **Совместимость со старыми рецептами.**
   У нас один рецепт `demo_webcam_split_merge.yaml`. Миграция: `RecipeManager` сначала читает старый формат, конвертит в новую domain-модель, пишет обратно в старом формате до Phase F. После — формат version=3.

6. **Тестовые стратегии.**
   Сейчас тесты с MagicMock-ctx скрывают реальные проблемы (вчерашний случай: тесты проходили, в живом GUI — нет). Хочу:
   - Domain-level unit tests без Qt.
   - Tab-level tests с реальным `AppServices` builder (не MagicMock).
   - End-to-end pytest-qt с автоматизацией без модальных диалогов (через monkey-patch dialog'ов как сделали для CreateProcessDialog).

7. **Размер PR.**
   Минимум 5-7 веток. Master plan + чёткие checkpoints. Каждая ветка независимо мержится в main с green tests.

---

## 7. Success criteria

После завершения рефакторинга:

- [ ] Запрос «где топология читается» возвращает **одно место** (вместо 10).
- [ ] Создание процесса = одна команда `Project.add_process(...)` → одно событие → каждый таб обновляется атомарно. Без `_sync_nav`, `_reveal_node_in_pipeline`, grid-pos hack.
- [ ] `AppServices` — dataclass с типами. `ctx.extras` удалён или deprecated.
- [ ] Никакого `topology.get("processes", [])` в presenter'ах. Только `project.processes`.
- [ ] Тест «создал процесс в Processes → видно в Pipeline» проходит без monkey-patch сложнее, чем patch event handlers.
- [ ] Recipe activation = одна команда, которая запускает services + replaces blueprint atomically.
- [ ] Удалось удалить:
  - `ctx.config["topology"]` post-bootstrap fallback
  - `ctx.extras["topology"]` (legacy)
  - дублирование `for proc in topology.get(...)` в 10+ местах
- [ ] Sentrux modularity score не упал (наоборот — ожидаем рост из-за уменьшения связности).

---

## 8. Антипаттерны, которых хочу избежать в самой переделке

- **Big bang.** Не переписывать всё за раз. Domain + adapter + миграция по табу.
- **Параллельная сущность.** Не делать `ProjectV2` рядом с `TopologyHolder` и оставлять оба навечно. Adapter'ы должны быть временные.
- **Over-engineering.** Не вводить CQRS / Event Sourcing полностью. Только domain events + commands; query — синхронный read из агрегата.
- **Премётивные абстракции.** Не делать `IPipelineEditor` / `IProcessRepository`. Только конкретные классы пока нет 2-го реализатора.

---

## 9. Что брать с собой в новый чат

При открытии нового чата:

1. **Открыть этот файл** + read CLAUDE.md (правила проекта).
2. Команда: `/plan refactor cross-tab architecture (см. docs/refactors/2026-05_cross_tab_architecture.md)`
3. Запросить **только Phase A (audit)** для начала. Phase B-G — после approval audit-результата.
4. Стартовать с investigator-агента (read-only) — сначала факты, потом план.

---

## 10. Связанные документы

- [`docs/refactors/2026-05_prototype_skeleton.md`](2026-05_prototype_skeleton.md) — текущий skeleton 7 табов.
- [`docs/refactors/2026-05_tab_template.md`](2026-05_tab_template.md) — шаблон создания таба.
- [`docs/refactors/2026-05_arch_cleanup.md`](2026-05_arch_cleanup.md) — предыдущий cleanup.
- [`multiprocess_framework/DECISIONS.md`](../../multiprocess_framework/DECISIONS.md) — ADR-129 (service_module), ADR-130 (display_module), ADR-131/132 (recipes v2), ADR-133 (FrameRouter).
- [`CLAUDE.md`](../../CLAUDE.md) — общие правила и слои импортов.
