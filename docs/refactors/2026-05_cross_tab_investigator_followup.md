---
title: "Cross-tab refactor — Investigator follow-up после C.0/C.1"
type: investigation-report
date: 2026-05-27
phase: C (in progress)
related:
  - plans/2026-05-27_cross-tab-architecture/plan.md
  - plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md
  - plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md
  - docs/refactors/2026-05_cross_tab_audit.md
---

# Investigator follow-up — валидация Phase C benefit + Phase D prep

## Контекст

После завершения **C.0** (`1f1d28ff`+`210f21a1`) и **C.1** (`551ebdad`) — read-only catalog adapters — пользователь попросил архитектурную валидацию: даёт ли Phase C реальный benefit, или это только подготовка к Phase D без немедленной ценности.

Investigator (Opus, read-only) проанализировал call sites в production-коде через grep/qex и сравнил их с покрытием adapter'ов.

## Резюме

Phase C **полезна** как фундамент Phase D, но C.1 adapter-слой в исходной форме покрывал **только 14-35% prod call sites**. Без корректировок Phase E pipeline migration упёрлась бы в lossy mapping. Investigator выявил 5 рекомендаций; пользователь принял 4 из них.

После корректировок (C.1.5 + C.1.6, C.6 без suppress) adapter покрытие выросло, ServicesPresenter получил путь миграции, риск UI рассинхрона снят.

## Анализ покрытия — call sites

### PluginRegistry — 14 prod call sites

| Файл / линия | Что использует | После Phase D (без C.1.5) | После C.1.5 |
|--------------|----------------|----------------------------|-------------|
| `pipeline/presenter.py:315` | `port.optional` для PortSchema | NO | **YES** |
| `pipeline/presenter.py:461-540` | `are_ports_compatible(out, in)` — framework Port objects | NO | NO (framework dep) |
| `pipeline/presenter.py:651-671` | `entry.category` | YES | YES |
| `pipeline/tab.py:200-222` | `entry.description` | NO | **YES** |
| `plugins/presenter.py:42-60` | `description`, `register_classes` | NO | PARTIAL (description) |
| `plugins/presenter.py:68-106` | `inputs`/`outputs` Port objects + `register_classes` | NO | PARTIAL |
| `plugins/sandbox.py:411-421` | `entry.register_classes[0]` (real class) | NO | NO (compromise) |
| `plugins/sandbox_presenter.py:99-136` | `entry.plugin_class` | NO | NO (compromise) |
| `plugins/sandbox_presenter.py:185-192` | `entry.plugin_class` instantiation | NO | NO (compromise) |
| `processes/presenter.py:53-92` | `entry.description` (getattr fallback) | PARTIAL | **YES** |
| `bridge/command_catalog.py:103-127` | `entry.plugin_class.commands` + `register_classes` | NO | NO (compromise) |
| `startup_checks.py:118-135` | `registry.names()` | YES | YES |

**Итого до C.1.5:** YES 14% / PARTIAL 21% / NO 65%.
**После C.1.5:** YES ~35% / PARTIAL ~20% / NO ~45% (45% — `plugin_class`/`register_classes` consumers оставлены на raw registry по compromise).

### ServiceRegistry — 7 prod call sites

| Файл / линия | Что использует | До C.1.6 | После C.1.6 |
|--------------|----------------|----------|-------------|
| `services/presenter.py:46-54` | name, meta, lifecycle | NO (read-only adapter) | **YES** |
| `services/presenter.py:73-99` | `entry.cls()` + lifecycle мутация | NO | **YES** (ServiceManager.start) |
| `services/presenter.py:113-134` | lifecycle мутация | NO | **YES** (stop/restart) |
| `services/presenter.py:160-164` | lifecycle чтение | NO | **YES** (get_lifecycle) |
| `services/presenter.py:214-225` | `discover()` rescan | NO | NO (out of scope) |
| `plugins/sandbox.py:479,538` | `svc_registry.get("webcam_camera")` + cls() | NO | PARTIAL |

**Итого до C.1.6:** YES 0%.
**После C.1.6 (ServiceManager Protocol):** YES ~70% (6 из 7 call sites). `discover()` остаётся, sandbox hardcode — частично.

### DisplayRegistry — 6 prod call sites

| Файл / линия | Использование | После Phase D |
|--------------|---------------|---------------|
| `displays/tab.py:156-159` | full CRUD через presenter | NO (write needs) |
| `displays/presenter.py:68-237` | register/unregister/persist | NO (write needs) |
| `pipeline/presenter.py:189` | get(display_id) → name | YES |
| `pipeline/inspector/inspector_panel.py:439-444` | list() для combo | YES |
| `pipeline/io.py:216-222` | get(display_id) → name | YES |

**Итого:** YES 50% (3/6, все read-only consumers).

### Fallback chains, которые исчезнут после Phase D

1. `processes/presenter.py:45-51` — `config["topology"]` ↔ `extras.get("topology")` → `services.topology.load()`.
2. `displays/tab.py:156-159` — `getattr(ctx, "display_registry")` → fallback `DisplayRegistry()` → `services.displays`.
3. `pipeline/presenter.py:189` — `getattr(self._ctx, "display_registry")` → `services.displays`.
4. `pipeline/inspector/inspector_panel.py:439` — `getattr(ctx, "display_registry")` → `services.displays`.
5. `pipeline/inspector/inspector_panel.py:397` — `getattr(ctx, "recipe_manager")` → `services.recipes`.
6. `recipes/tab.py:88` — `getattr(ctx, "recipe_manager")` → `services.recipes`.

Все 6 fallback'ов закроются для read-only потребителей. CRUD-fallback'ы (DisplaysPresenter, ServicesPresenter) — частично, благодаря C.1.6.

## Pitfalls Phase D

### P1 — DisplayRegistry lazy load (BLOCKER → закрыт в C.1.5)

DisplayRegistry заполнялся только при открытии DisplaysTab. После Phase D `services.displays.list_displays()` мог бы возвращать пустой tuple до первого открытия вкладки → pipeline scene без display names.

**Fix (C.1.5):** preload в `app.py` через `load_displays_config()` + `displays_config_to_registry()` после ServiceRegistry init. Idempotent — DisplaysTab при открытии не пересоздаёт записи.

### P2 — `holder.on_changed` legacy callbacks vs suppress_legacy_notify (BLOCKER → закрыт правкой плана C.6)

2 prod подписчика на `holder.on_changed`:
- `app.py:197` — TopologyBridge (cross-tab routing).
- `pipeline/presenter.py:60` — PipelinePresenter (scene update при apply recipe).

Если C.6 CommandDispatcher включает suppress_legacy_notify по умолчанию **до миграции этих 2 подписчиков на EventBus**, dispatch заглушит legacy callbacks → **UI рассинхрон** (Pipeline scene не обновится).

**Fix (decision Q7):** dispatcher НЕ использует suppress по умолчанию. Двойная нотификация (legacy callbacks + EventBus) — осознанный временный компромисс на Phase D/E. Suppression активируется только в Phase F после миграции всех подписчиков. Context manager `suppress_legacy_notify()` остаётся в `TopologyRepository` API на случай Phase F.

### P3 — timing инициализации (NO ISSUE)

`discover_plugins()` в `app.py:86` выполняется до создания AppServices (строка ~387) → adapter получает заполненный registry. Безопасно.

`ServiceRegistry` discover на строках 119-132 → тоже до AppServices. Безопасно.

## Принятые решения (после ответов пользователя)

| Решение | Выбор | Реализовано в |
|---------|-------|---------------|
| PluginSpec gaps | Сейчас (backport) — добавить description/optional/shape | **C.1.5 ✅** (`05d86857`) |
| ServiceCatalog vs ServicesPresenter | Расширить до ServiceManager Protocol с lifecycle | **C.1.6 ✅** (`5b45eab8`+`e4668a69`) |
| suppress_legacy_notify в C.6 | НЕТ — double notification до Phase F | план обновлён (`011f6706`) |
| DisplayRegistry preload | В Phase C (C.1.5) | **C.1.5 ✅** |
| `plugin_class`/`register_classes` в PluginSpec | НЕТ — compromise. Sandbox и command_catalog остаются на raw registry | задокументировано в decisions log |

## Status Phase C на момент пишу handoff

**4 из 9 Tasks DONE:**
- ✅ C.0 (`1f1d28ff` + `210f21a1`)
- ✅ C.1 (`551ebdad`)
- ✅ C.1.5 (`05d86857` + `d710a6a2`)
- ✅ C.1.6 (`5b45eab8` + `e4668a69`)

**Осталось:**
- C.2 — AuthFacade (Junior+, Sonnet)
- C.3 — TopologyRepositoryFromHolder + `suppress_legacy_notify()` cm (Middle+)
- C.4 — RegistersBackendFromManager (Middle+, variant A: знает Topology+PluginCatalog)
- C.5 — RecipeStoreFromManager (Senior, variant A: denormalize meta→top-level)
- C.6 — CommandDispatcherOrchestrator **без suppress по умолчанию** (Senior)
- C.7 — adapters/__init__.py + README + integration smoke (Middle)

**Метрики:**
- domain: 240 tests passed
- adapters: 53 passed + 2 skipped (smoke OK)
- ruff: 0 errors
- 8 коммитов локально на `refactor/cross-tab-architecture`, не запушены

## Ссылки

- Brief: [`docs/refactors/2026-05_cross_tab_architecture.md`](2026-05_cross_tab_architecture.md)
- Audit (Phase A deliverable): [`docs/refactors/2026-05_cross_tab_audit.md`](2026-05_cross_tab_audit.md)
- Master plan: [`plans/2026-05-27_cross-tab-architecture/plan.md`](../../plans/2026-05-27_cross-tab-architecture/plan.md)
- Phase C plan: [`plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md`](../../plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md)
- Phase D plan: [`plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md`](../../plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md)
