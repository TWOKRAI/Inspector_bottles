---
name: topology-event-ordering
description: Все правки графа идут через store → TopologyReplaced; активация доп. эмитит RecipeActivated ПОСЛЕ — это надёжный дискриминатор edit vs activate
metadata:
  type: project
---

Любая мутация editor-топологии (add/remove процесс/провод, конфиг ноды, undo/redo)
проходит через `CommandDispatcherOrchestrator.dispatch` → `topology_repo.save()` →
`TopologyRepositoryStore.set_topology` → publish `TopologyReplaced(reason="topology_changed")`.
Активация рецепта (`ActivateRecipe`) дополнительно эмитит `RecipeActivated(slug)`
СТРОГО ПОСЛЕ своих `TopologyReplaced` (domain `_apply_activate_recipe` возвращает
events `[TopologyReplaced(reason="recipe:{slug}"), RecipeActivated]`, а store.save в
dispatch публикует свой TopologyReplaced ещё раньше).

**Why:** порядок публикации фиксирован и синхронен (EventBus). Поэтому `RecipeActivated`
— единственный надёжный маркер «новая сессия / активация», а `TopologyReplaced` сам по
себе неотличим между правкой и активацией (reason у store всегда "topology_changed").
Это же использует `PipelinePresenter._on_recipe_activated` (чистка placed-but-unbound
боксов) и RS-4 dirty-контур (`TopologySession`: TopologyReplaced→mark_edited,
RecipeActivated→mark_activated; активация оставляет сессию чистой за счёт порядка).

**How to apply:** при работе над dirty/session/RecipeSession (целевая архитектура аудита
2026-07-12) НЕ пытайся различать edit vs activate по `reason` TopologyReplaced — завязывайся
на RecipeActivated (после) или на `undoable`-флаг dispatch. Load-from-file и стартовый
`load_topology_from_config` идут МИМО store (не публикуют TopologyReplaced) — их помечай
явно (`mark_loaded`) или оставляй чистыми на старте. Конвенция контейнеров: mutable/runtime
(callbacks, live) → `RuntimeDeps`; frozen catalogs → `AppServices` (10 полей, без Optional).
