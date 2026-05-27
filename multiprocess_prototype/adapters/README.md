# multiprocess_prototype.adapters — adapter-слой

## Назначение (Purpose)

Пакет создан в рамках **Phase C** рефакторинга `refactor/cross-tab-architecture`.

Adapter-слой — тонкая прослойка между:
- **domain-слоем** (`multiprocess_prototype/domain/`) — типизированные Protocol'ы
- **реальными реестрами фреймворка** (`multiprocess_framework/modules/*`, `Services/*`, `Plugins/*`)
  и legacy runtime-объектами прототипа (`TopologyHolder`, `RecipeManager`, `RegistersManager`)

Каждый adapter реализует соответствующий Protocol из `domain/protocols/` путём делегирования
реальному реестру. Никакой бизнес-логики внутри adapter'ов — только mapping и преобразование типов.

**Место в архитектуре (Phase C/D/E):**

```
Phase D:  presenter'ы (Phase E) → AppServices DI-контейнер → adapters → реестры
Phase C:  adapters изолированы — к frontend не подключены
Phase F:  TopologyHolder и legacy holders удаляются → часть adapters упрощается
```

Подключение adapter'ов к `app.py` и `AppServices` выполняется в **Phase D Task D.1**.

---

## Публичный API

```python
from multiprocess_prototype.adapters import (
    # Auth
    AuthFacadeFromAuthState,         # AuthState → AuthFacade Protocol

    # Catalogs (read-only реестры)
    PluginCatalogFromRegistry,       # _PluginRegistry → PluginCatalog Protocol
    ServiceManagerFromRegistry,      # ServiceRegistry → ServiceManager Protocol
    ServiceCatalogFromRegistry,      # backward-compatible alias для ServiceManagerFromRegistry
    DisplayCatalogFromRegistry,      # DisplayRegistry → DisplayCatalog Protocol

    # Stores (persistence)
    TopologyRepositoryFromHolder,    # TopologyHolder → TopologyRepository Protocol
    RegistersBackendFromManager,     # RegistersManager → RegistersBackend Protocol
    RecipeStoreFromManager,          # RecipeManager → RecipeStore Protocol

    # Command orchestrator
    CommandDispatcherOrchestrator,   # dispatch(ProjectCommand) → list[ProjectEvent]
    ProjectHolder,                   # mutable wrapper над current frozen Project
)
```

Итого **10 публичных классов** (9 adapter'ов + `ProjectHolder` как вспомогательный).

---

## Структура пакета

```
adapters/
├── __init__.py                      # публичный API, re-export всех 10 классов
├── README.md                        # этот файл (module contract)
│
├── auth/
│   ├── __init__.py
│   └── auth_facade.py               # AuthFacadeFromAuthState
│
├── catalogs/
│   ├── __init__.py
│   ├── plugin_catalog.py            # PluginCatalogFromRegistry
│   ├── service_catalog.py           # ServiceManagerFromRegistry + ServiceCatalogFromRegistry
│   └── display_catalog.py           # DisplayCatalogFromRegistry
│
├── stores/
│   ├── __init__.py
│   ├── topology_repository.py       # TopologyRepositoryFromHolder + suppress_legacy_notify()
│   ├── registers_backend.py         # RegistersBackendFromManager
│   └── recipe_store.py              # RecipeStoreFromManager
│
├── dispatch/
│   ├── __init__.py
│   └── command_dispatcher.py        # CommandDispatcherOrchestrator + ProjectHolder
│
└── tests/
    ├── __init__.py
    ├── conftest.py                  # фикстуры (clean_*_registry)
    ├── test_catalogs.py             # 3 catalog adapter'а
    ├── test_recipe_store.py
    ├── test_registers_backend.py
    ├── test_topology_repository.py
    ├── test_command_dispatcher.py
    ├── test_auth_facade.py
    └── test_integration_assembly.py # Phase C.7 integration smoke
```

---

## Границы импортов (Boundaries)

### Разрешено

- `multiprocess_prototype.domain.*` — все entities, protocols, events, commands
- `multiprocess_framework.modules.*` — реестры, модули фреймворка
- `Services/*` — прикладные сервисы (auth, sql, hikvision, …)
- `Plugins/*` — vocabulary плагинов
- другие `multiprocess_prototype/*` модули — recipes/, registers/, backend/, …

### ЗАПРЕЩЕНО

- **PySide6** / Qt в любой форме — adapter-слой UI-agnostic
- **`multiprocess_prototype.frontend.widgets*`** — adapter'ы не импортируют Qt-виджеты
- `multiprocess_prototype.frontend.*` (за исключением ниже)

### Исключение (задокументированное)

`adapters/stores/topology_repository.py` импортирует
`multiprocess_prototype.frontend.topology_holder.TopologyHolder`.

Это **bridge-объект**: `TopologyHolder` — простой Python-контейнер (не Qt-виджет),
хранящий topology dict с уведомлениями об изменении. Он используется GUI-слоем
как legacy source of truth до Phase F.

Импорт зафиксирован в **decisions Q1** (2026-05-27):
> Project = source of truth в Phase D+. TopologyHolder остаётся как derived store;
> dispatcher после `Project.apply()` пишет через `TopologyRepositoryFromHolder.save()`.

**Phase F:** `TopologyHolder` будет удалён после миграции всех подписчиков
`holder.on_changed` на чистый EventBus. Тогда `topology_repository.py` упростится
до in-memory store.

Правила enforced через `.sentrux/rules.toml` (границы `adapters → !frontend/widgets*`
и `adapters → !PySide6/*`). Исключение documented в decisions Q1.

---

## Стабильность (Stability)

| Компонент | Стабильность |
|-----------|-------------|
| Публичный API (`__init__.py`) | **Stable** — Phase D зависит от него |
| `PluginCatalogFromRegistry` / `DisplayCatalogFromRegistry` | **Stable** |
| `ServiceManagerFromRegistry` | **Stable** (lifecycle methods) |
| `TopologyRepositoryFromHolder` | **Временный** — Phase F: holder удаляется |
| `RecipeStoreFromManager` | **Временный** — Phase F: YAML format v2→v3 migration |
| `RegistersBackendFromManager` | **Временный** — Phase E: Inspector mapping refinement |
| `CommandDispatcherOrchestrator` | **Stable** (core orchestrator Phase D+) |
| `AuthFacadeFromAuthState` | **Stable** |

**Adapter Layer** в целом — временный слой Phase C–E. В Phase F часть adapters будет
упрощена или удалена после полной миграции legacy holders на чистый EventBus.

---

## Решения (Decisions Log)

Полные обоснования — в
[`plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md`](../../plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md),
секция «Решения (decisions log)».

Краткая сводка:

### Q1 — Источник истины: Project vs TopologyHolder

**Решение:** Project = source of truth в Phase D+. `TopologyHolder` = derived store.
`CommandDispatcherOrchestrator.dispatch()` после `Project.apply()` пишет topology
в holder через `TopologyRepositoryFromHolder.save()` (legacy callbacks вызываются).

**Исключение:** `topology_repository.py` импортирует `topology_holder.py` —
это bridge-объект, удаляется в Phase F.

### Q2 — Recipe YAML backward-compat (Variant A)

**Решение:** При `RecipeStoreFromManager.write()` мета-данные денормализуются
`meta → top-level` (name, version, description — на верхнем уровне YAML).
Это сохраняет совместимость с legacy reader'ами. Формат v2→v3 migration — Phase F.

### Q3 — Wire.description + Process.metadata

**Решение:** `Wire.description: str = ""` добавлено как семантическое поле.
`Process.metadata: dict[str, Any]` — passthrough-bag для runtime-полей
(например, `source_target_fps`). `source_target_fps` НЕ стало отдельным полем.

### Q4 — RegistersBackend адресация (Variant A)

**Решение:** `RegistersBackendFromManager` принимает `topology_repo + plugin_catalog`
в конструкторе. Маппинг `plugin_index → register_name` локализован в adapter
через `topology_repo.load() → plugins[plugin_index] → plugin_catalog.resolve()`.

### Q5 — DisplayRegistry: singleton напрямую

**Решение:** `DisplayCatalogFromRegistry(DisplayRegistry())` — adapter получает
singleton напрямую. В `ctx.extras` его нет — добавление было бы scope creep.

### Q6 — suppress_legacy_notify() context manager

**Решение:** Реализован в `TopologyRepositoryFromHolder` как toggle-флаг
`holder._suppress_notify`. **Не применяется по умолчанию** (см. Q7).
Доступен в API на случай Phase F.

### Q7 — Двойная нотификация (user-confirmed)

**Решение:** `CommandDispatcherOrchestrator` вызывает `topology_repo.save()` штатно —
legacy `holder.on_changed` callbacks срабатывают как обычно. EventBus публикует
параллельно. Двойная нотификация — осознанный временный компромисс Phase D/E.

**Причина:** 2 prod подписчика на `holder.on_changed` (`app.py:197` TopologyBridge +
`pipeline/presenter.py:60` PipelinePresenter) — подавление до их миграции
в Phase E приведёт к UI рассинхрону. Suppression активируется в Phase F.

---

### Компромиссы (Compromises)

**PluginSpec — нет `plugin_class: type` / `register_classes: list[type]`:**
`PluginSpec` не содержит ссылки на Python-класс плагина. `sandbox.py` и
`command_catalog.py` остаются на raw `ctx.plugin_registry()`. Adapter покрывает
«catalog read» (~35% prod call sites), не все 100%.
Документировано в investigator-followup (см. References).

**ServiceManager — `discover()` не реализован в adapter:**
`ServicesPresenter` мигрирует в Phase E частично. `discover()` добавляется
при Phase E migration когда станут понятны точные требования.

**RecipeStore — `set_active(None)` обращается к `engine._active_name`:**
`RecipeStoreFromManager.set_active(None)` обращается к приватному полю движка
(C.5 коммит). Phase F refactor устранит это при YAML format migration.

**TopologyHolder import — bridge-исключение (Q1):**
`topology_repository.py` нарушает общее правило «adapters не импортируют frontend»,
но holder — не UI-объект. Исключение задокументировано, удаляется в Phase F.

---

## Ссылки (References)

| Документ | Описание |
|----------|----------|
| [`plans/2026-05-27_cross-tab-architecture/plan.md`](../../plans/2026-05-27_cross-tab-architecture/plan.md) | Master plan рефакторинга (Phase A–G) |
| [`plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md`](../../plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md) | Phase C детальный план (Tasks C.0–C.7, decisions Q1–Q7) |
| [`docs/refactors/2026-05_cross_tab_investigator_followup.md`](../../docs/refactors/2026-05_cross_tab_investigator_followup.md) | Investigator-followup: lossy mapping, PluginSpec compromise, discovery gaps |
| [`docs/refactors/2026-05_cross_tab_architecture.md`](../../docs/refactors/2026-05_cross_tab_architecture.md) | Architecture brief (cross-tab refactor overview) |
| [`multiprocess_prototype/domain/README.md`](../domain/README.md) | Domain-слой: entities, protocols, events, commands |
| [`plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md`](../../plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md) | Phase D: AppServices factory в `app.py` (следующий этап) |
