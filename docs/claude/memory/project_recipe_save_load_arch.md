---
name: project-recipe-save-load-arch
description: Архитектура save/load рецептов — корни «не сохраняет правки полей» и «кривая загрузка», что починено и что осталось (recipe-orchestrator-unify)
metadata:
  type: project
---

Разбор 2026-06-16 (многоагентный workflow) пути save/load рецептов в прототипе.

**ГЛАВНЫЙ СЮРПРИЗ:** бэкенд УЖЕ делает «остановить всё → собрать заново» (НЕ инкрементальный hot-swap). `FullReplacePlanner` (`backend/assembly/planner.py`): `diff()` всегда `has_changes:True` → фазы `stop_all`(все non-protected) → `cleanup` → `provision`→`create`→`start`. Выживают только protected (gui, devices). Точка входа: GUI→`proxy.apply_topology`→IPC `topology.apply`→`process_manager_process.apply_topology`(транзакция snapshot/rollback)→`TopologyManager.apply`. Значит требование владельца «перед загрузкой всё останавливать» — уже поведение; менять стратегию планировщика НЕ нужно. (`IncrementalPlanner` лишь упомянут как будущий.)

**БАГ САХРАНЕНИЯ (починен).** Правка поля в инспекторе → `presenter._on_inspector_field_changed` диспатчит `SetPluginConfig` под `_block_signals()` (`_suppress=True`) → `_on_topology_replaced` подавлен → `self._model` НЕ синкался с domain. `save_to_active_recipe` сериализует `graph_to_blueprint(self._model)` → писал СТАРЫЙ конфиг. Узлы (AddProcess) сохранялись (диспатч без suppress). **Фикс:** после dispatch синкать `self._model.from_topology_dict(services.topology.load().to_dict())` (чистый deepcopy, без scene-reload). Регресс-тест `test_save_recipe.py::TestFieldEditPersistsToRecipe` (нужен `make_pipeline_services_with_orchestrator` — реальный dispatch).

**БАГ ЗАГРУЗКИ «кривая» (починен главный).** В `recipes/presenter.py::on_set_active` порядок был неверный: `dispatch(ActivateRecipe)` (синхронно шлёт `RecipeActivated`) ШЁЛ ДО `store.set_active`. `_rebuild_displays` (app.py, на `RecipeActivated`) читает `recipe_manager.get_active()` → видел СТАРЫЙ slug → слоты/routing дисплеев собирались по предыдущему рецепту (кадры нового летели не в тот слот). **Фикс:** `set_active` ДО `dispatch` (+ откат slug при отклонении валидации). `set_active` событий не шлёт, безопасен.

**inspector-нормализация.** `inspector`(join) — прямой ключ ProcessConfig; GUI-save/домен кладут под metadata (Process не имеет поля inspector). Канонизируется в `backend/launch.py::unwrap_recipe::_hoist_inspector_from_metadata` (поднимает из metadata) — это нормализация на границе загрузки (как прочие в unwrap_recipe), не временный костыль. Тесты `backend/topology/tests/test_inspector_hoist.py`. См. [[project_recipe_inspector_join_key]].

**ОСТАВШИЕСЯ ДОЛГИ (план recipe-orchestrator-unify, отдельно — высокий риск):**
- **L2:** Recipes-«Загрузить» = fire-and-forget без `on_result` → ложный «успех» при backend-rollback/debounce, тихий debounce при повторном клике. Pipeline-«Запустить» уже через `on_result` (presenter.py:1672-1685) — унифицировать.
- **switch≠boot:** рантайм `orchestrator._build_proc_dicts` НЕ делает `merge_topologies(base.yaml)`, а boot делает → состав процессов на switch держится лишь на том, что gui/devices живые+protected. Рецепты без gui/devices внутри собираются иначе, чем на boot.
- **display-SHM (ИСТОЧНИК #1):** SHM дисплеев привязан к protected ui_process, аллоцируется только на boot → смена размеров/числа дисплеев требует РЕСТАРТА приложения (apply_topology reload'ит только метаданные DisplayRegistry, не физический SHM; ADR-DM-003).
- **graceful-stop hang ~5с** при kill камеры (finally не доходит) → OS-хэндл/SHM держится; см. [[project_graceful_stop_debt]].
- три кнопки = три источника истины (Recipes-Загрузить=сохранённый рецепт; Pipeline-Запустить=сохранённый; Pipeline-Перезапустить=in-memory граф).

Статус: save+load для заявленных симптомов (правки полей не сохранялись; дисплеи грузились по старому рецепту) ПОЧИНЕНЫ + 675 тестов зелёные. Структурные долги — отдельный план. Связано: [[project_recipe_hotswap]], [[project_pipeline_editor_runtime_decoupled]].
