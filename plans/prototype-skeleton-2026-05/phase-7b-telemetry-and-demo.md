# Phase 7b — Wire telemetry + end-to-end демо

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/pipeline-telemetry-and-demo`
> **Дней**: 4-5
> **Зависимости**: Phase 7a ✅
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-7b-telemetry-and-demo.md, plans/prototype-skeleton-2026-05/plan.md`
> **Парная фаза**: [phase-7a-display-node-and-io.md](phase-7a-display-node-and-io.md)

## Цель

Достроить телеметрию edges (раздельные slow/fast таймеры), создать плагин `blur`, собрать рабочий end-to-end демо `demo_webcam_split_merge.yaml`.

## Реальная фундация

- **Унаследованные идеи** из удалённого Constructor (`git show 9885bb88:`):
  - Раздельная wire-телеметрия: `WireStatus` (slow ~2с, цвет ok/idle/error) и `WireMetrics` (fast ~1с, fps/latency/buffer_fill) — два независимых таймера.
- Готовые плагины: `capture`, `resize`, `region_split`, `grayscale`, `color_mask`, `negative`, `flip`, `stitcher`, `render_overlay` (см. `Plugins/`). Плагин `blur` — **создать** (~50 строк, OpenCV GaussianBlur).
- `DisplayNodeItem`, `target_process` binding, `pipeline/io.py` — готовы в Phase 7a.
- `EdgeItem` (`multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/edge_item.py`) — QGraphicsPathItem с `update_path(source_pos, target_pos)` — есть точка крепления badge на midpoint.
- `RecipeManager` (`multiprocess_prototype/recipes/manager.py`) + `RecipeEngine` готовы (Phase 5).
- `IProcessManagerProcess.replace_blueprint(new_blueprint: dict) → dict` (`multiprocess_framework/modules/process_manager_module/interfaces.py:201`) — горячая замена рецепта без остановки GUI (Phase 5).
- `RouterManager.get_stats()` (`multiprocess_framework/modules/router_module/core/router_manager.py:469`) — глобальные `{sent_attempted, sent_ok, received, errors, middleware_dropped}` (не per-channel).

## Архитектурное решение по источнику данных телеметрии

`RouterManager` хранит только глобальные счётчики, не per-channel/per-wire. Реальное per-wire instrumentation потребовало бы изменений в framework (не в scope Phase 7b). MVP-подход:

1. **`WireMetricsModel` — pure model** с публичным API `update_metrics(src, tgt, fps, latency_ms, buffer_fill)` / `update_status(src, tgt, state)`. Источник наполнения — НЕ обязателен в этой фазе.
2. **WireMetricsFeed (опц.)** — заглушка/симулятор, периодически обновляет модель синтетическими данными по активным wire'ам (для demo-валидации UX). В production-режиме её замещают реальные обновления через state_store (вне scope 7b).
3. Реальный per-channel feed — отложен в Phase 8 или отдельный backlog item «framework: per-channel router stats».

## Декомпозиция (Task X.Y)

### Task 7b.1 — WireMetricsModel + WireStatus/WireMetrics dataclasses

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Чистая модель данных wire-телеметрии с двумя независимыми сигналами (slow status / fast metrics).
**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/telemetry/__init__.py` (новый)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/telemetry/wire_metrics_model.py` (новый)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_wire_metrics_model.py` (новый)
**Steps:**
1. `@dataclass WireStatus(state: Literal["ok", "idle", "error"], last_message_time: float)`. Дефолт `state="idle"`, `last_message_time=0.0`.
2. `@dataclass WireMetrics(fps: float, latency_ms: float, buffer_fill: float)`. Дефолты 0.0.
3. `WireMetricsModel(QObject)`:
   - Хранит `_statuses: dict[tuple[str, str], WireStatus]` и `_metrics: dict[tuple[str, str], WireMetrics]`.
   - Сигналы: `statuses_changed(dict)` и `metrics_changed(dict)` — для слабосвязанного UI-обновления.
   - Методы: `update_status(src, tgt, state, last_message_time)`, `update_metrics(src, tgt, fps, latency_ms, buffer_fill)`, `get_status(src, tgt) → WireStatus | None`, `get_metrics(src, tgt) → WireMetrics | None`, `clear()`.
   - **Сигналы НЕ испускаются на каждый update** — а только через метод `emit_statuses()` / `emit_metrics()` (вызывается извне таймерами в Task 7b.3).
4. Unit-тесты pure Python (без pytest-qt где можно, но QObject — нужен QApplication-fixture):
   - `test_update_status_stores_value`, `test_update_metrics_stores_value`, `test_get_returns_none_for_unknown`.
   - `test_emit_statuses_signal`, `test_emit_metrics_signal` — через `QSignalSpy`.
   - `test_clear_resets_state`.
**Acceptance criteria:**
- [x] WireMetricsModel хранит данные по `(src, tgt)`-ключу.
- [x] Два независимых сигнала испускаются ТОЛЬКО при явном вызове `emit_*` (для контроля частоты извне).
- [x] 6-8 unit-тестов проходят. (16/16, коммит: см. ниже)
**Out of scope:** UI badge (Task 7b.2), таймеры/интеграция (Task 7b.3), реальный feed (вне MVP).

---

### Task 7b.2 — WireMetricsBadge (QGraphicsItem)

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Визуальный overlay-badge на edge — текст «fps | latency | fill%» + цвет фона по WireStatus.
**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/telemetry/wire_metrics_badge.py` (новый)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_wire_metrics_badge.py` (новый)
**Steps:**
1. `WireMetricsBadge(QGraphicsItem)` (наследует напрямую `QGraphicsItem` или `QGraphicsRectItem`).
2. Геометрия: маленький прямоугольник ~80×24px с закруглёнными углами. Текст внутри (QGraphicsTextItem child).
3. Цвет фона по `WireStatus.state`:
   - `ok` → зелёный (`#2e7d32`)
   - `idle` → серый (`#757575`)
   - `error` → красный (`#c62828`)
4. Метод `update_position(midpoint: QPointF)` — переместить центр badge в `midpoint`.
5. Метод `update_metrics(metrics: WireMetrics)` — обновить текст (формат: `f"{fps:.0f}fps | {latency_ms:.0f}ms | {buffer_fill*100:.0f}%"`).
6. Метод `update_status(status: WireStatus)` — обновить цвет фона + кэшированный `state`.
7. Z-value — выше edge (badge не должен прятаться).
8. По умолчанию: текст `"-- fps | -- ms | --%"`, цвет idle.
9. Unit-тесты pytest-qt:
   - `test_badge_creation_default_text`, `test_badge_update_metrics_changes_text`, `test_badge_update_status_changes_color`, `test_badge_position`.
**Acceptance criteria:**
- [ ] Badge добавляется в QGraphicsScene, отображает форматированный текст.
- [ ] Смена WireStatus → смена цвета фона.
- [ ] 4-5 unit-тестов проходят.
**Out of scope:** автообновление от модели (Task 7b.3), привязка к EdgeItem.midpoint (Task 7b.3).

---

### Task 7b.3 — WireMetricsController: интеграция модели + EdgeItem + два таймера

**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Связать `WireMetricsModel`, badges и edges. Два независимых таймера обновляют UI: `statuses_changed` каждые 2с (цвет), `metrics_changed` каждый 1с (текст).
**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/telemetry/wire_metrics_controller.py` (новый)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` (wire-up controller через ctx)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py` (передать scene + model в controller)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_wire_metrics_controller.py` (новый)
**Steps:**
1. `WireMetricsController(QObject)`:
   - Конструктор: `__init__(scene: GraphScene, model: WireMetricsModel, parent=None)`.
   - Внутри: словарь `_badges: dict[tuple[str, str], WireMetricsBadge]`.
   - Подписка на `scene` — отслеживать addition/removal edges (через `scene._edges` или сигналы; если их нет — добавить публичный сигнал `edge_added(EdgeItem)` / `edge_removed(EdgeItem)` в GraphScene и использовать).
   - При новом edge → создать badge + добавить в scene + сохранить в `_badges`.
   - При удалении edge → удалить badge из scene и из `_badges`.
2. **Два QTimer**:
   - `_status_timer` (2с): дёргает `model.emit_statuses()` и затем обновляет цвета всех badges из текущего состояния модели.
   - `_metrics_timer` (1с): дёргает `model.emit_metrics()` и обновляет тексты badges.
3. Подключение `model.statuses_changed` → `_apply_statuses(dict)`, `model.metrics_changed` → `_apply_metrics(dict)` — там идёт перебор и `badge.update_*`.
4. Метод `update_badge_positions()` — вызывается при перемещении узлов (если scene умеет уведомлять) — пересчитывает midpoint каждого edge и зовёт `badge.update_position`. На MVP — обновлять в `_metrics_timer` (раз в секунду — приемлемо).
5. В `PipelinePresenter.__init__` — создать `WireMetricsModel` (если ctx предоставляет `wire_metrics_model()`, использовать его; иначе — собственный экземпляр).
6. В `PipelineTab.__init__` — создать `WireMetricsController(self._scene, model)` после установки scene.
7. **Source feed**: в этой задаче feed не подключаем — просто `WireMetricsController.set_metrics(src, tgt, fps, latency, fill)` как публичный proxy в модель — для будущего внешнего feed-а. По умолчанию все wire'ы остаются в `idle`-статусе.
8. Unit/integration тесты pytest-qt:
   - `test_controller_creates_badge_for_each_edge`, `test_controller_removes_badge_on_edge_remove`.
   - `test_status_timer_updates_color` — через `qtbot.wait` + `model.update_status(...)` → badge цвет меняется.
   - `test_metrics_timer_updates_text`.
   - `test_badge_position_follows_edge_midpoint`.
**Acceptance criteria:**
- [ ] При добавлении edge — рядом появляется badge с дефолтным текстом.
- [ ] При вызове `model.update_metrics(...)` + тик таймера — текст badge обновляется.
- [ ] При вызове `model.update_status(..., "error")` + тик таймера — цвет badge меняется на красный.
- [ ] При удалении edge — badge удаляется.
- [ ] 4-6 integration-тестов проходят.
**Out of scope:** реальный per-channel feed из router stats (отдельный backlog item); подгрузка истории; `ShmDashboardPanel` (отложено).

---

### Task 7b.4 — Плагин blur

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Создать processing-плагин `blur` (OpenCV GaussianBlur) — последний недостающий плагин для demo-рецепта.
**Files:**
- `Plugins/processing/blur/__init__.py` (новый)
- `Plugins/processing/blur/plugin.py` (новый, ~60 строк)
- `Plugins/processing/blur/config.py` (новый)
- `Plugins/processing/blur/tests/__init__.py` (новый)
- `Plugins/processing/blur/tests/test_plugin.py` (новый)
**Steps:**
1. Структура — по образцу `Plugins/processing/grayscale/`.
2. `BlurPlugin(ProcessModulePlugin)`:
   - `name = "blur"`, `category = "processing"`, `thread_safe = True`.
   - `inputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр")]`.
   - `outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Размытый BGR-кадр")]`.
   - Декоратор `@register_plugin("blur", category="processing", description="GaussianBlur размытие")`.
   - Параметры через `configure(ctx)`: `kernel_size: int = 5` (нечётный), `sigma: float = 0.0`.
   - `@for_each def process(item)` — `cv2.GaussianBlur(frame, (k, k), sigma)`.
3. `BlurPluginConfig` (Pydantic, `register_schema("BlurPluginConfigV2")`):
   - Поля: `plugin_class: str = "Plugins.processing.blur.plugin.BlurPlugin"`, `kernel_size: int = 5`, `sigma: float = 0.0`.
   - Валидация: `kernel_size` должен быть нечётным и положительным (Pydantic field_validator).
4. Тесты:
   - `test_blur_default_config` — kernel_size=5, sigma=0.
   - `test_blur_processes_bgr_image` — синтетический np.ones((H,W,3)) → blur не падает, форма сохраняется.
   - `test_blur_returns_none_on_missing_frame` — item без `frame` → None.
   - `test_blur_kernel_size_even_rejected` — Pydantic ValidationError при чётном kernel_size.
**Acceptance criteria:**
- [ ] Плагин обнаруживается через `PluginRegistry.discover(Plugins/processing/)`.
- [ ] Обрабатывает BGR-кадр без ошибок.
- [ ] Параметры доступны через config.
- [ ] 4-5 unit-тестов проходят.
**Out of scope:** интеграция в demo-рецепт (Task 7b.6).

---

### Task 7b.5 — Кнопка «Запустить активный рецепт»

**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Добавить в action-колонку `PipelineTab` кнопку «Запустить». Логика: если `replace_blueprint`-канал доступен — вызвать его с blueprint текущего рецепта; иначе — warning через QMessageBox.
**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py` (добавить кнопку)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` (`launch_active_recipe(parent)`)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_launch_recipe.py` (новый)
**Steps:**
1. Прочитай `multiprocess_framework/modules/process_manager_module/interfaces.py:201` (`replace_blueprint`). Прочитай как GUI-процесс уже отправляет сообщения через router/IPC (см. `multiprocess_prototype/frontend/app.py` startup wire-up). Найди существующий механизм отправки `process_manager.replace_blueprint` запроса (если есть). Если нет — реализуй простейший proxy через `ctx.send_message(...)`.
2. Кнопка `"Запустить"` в action-колонке после «Сохранить». action_id `"launch_recipe"`. Permission gate `tabs.pipeline.edit`.
3. `_on_toolbar_action("launch_recipe")` → `self._presenter.launch_active_recipe(parent=self)`.
4. `PipelinePresenter.launch_active_recipe(parent) → bool`:
   - Получить `recipe_mgr = self._ctx.recipe_manager()`. Если None → warning, return False.
   - Получить `active_slug = recipe_mgr.get_active()`. Если None → warning «нет активного рецепта», return False.
   - Прочитать current recipe → `current = recipe_mgr.read_recipe(active_slug)`. Достать `blueprint = current.get("blueprint", {})`.
   - Найти proxy для отправки `replace_blueprint`. Варианты:
     - Если в `ctx.extras` есть `process_manager_proxy` или `system_launcher` — использовать.
     - Иначе через router/send_message к процессу `process_manager` с командой `replace_blueprint`.
     - Если ни одного proxy нет — `QMessageBox.warning(parent, "Запуск рецепта", "ProcessManager-proxy недоступен в GUI-процессе. Запуск возможен только при работающей системе.")`, return False.
   - Вызвать proxy `replace_blueprint(blueprint)` в try/except. На успех — `QMessageBox.information(...)` с replaced/skipped списком. На ошибку — `QMessageBox.critical(...)`.
5. Тесты:
   - `test_launch_no_active_recipe_warns` — без active recipe → warning, return False.
   - `test_launch_no_proxy_warns` — без proxy → warning, return False.
   - `test_launch_calls_replace_blueprint` — proxy замокан, успех.
   - `test_launch_handles_exception` — proxy raises → critical, return False.
**Acceptance criteria:**
- [ ] Кнопка «Запустить» появляется в action-колонке.
- [ ] Permission gate работает.
- [ ] Без активного рецепта / без proxy — warning, не падает.
- [ ] При успехе — information с результатом replace_blueprint.
- [ ] 4-5 тестов проходят.
**Out of scope:** реальный launch без работающего ProcessManager (это вне MVP — GUI-only процесс не может стартовать систему с нуля); прогресс-индикатор при долгом старте.

---

### Task 7b.6 — Demo-рецепт demo_webcam_split_merge.yaml + integration-тест

**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Собрать demo-рецепт по образцу из master-плана. Проверить, что blueprint валидируется через `SystemBlueprint.model_validate`, плагины из реестра, RecipeManager.load работает.
**Files:**
- `multiprocess_prototype/recipes/demo_webcam_split_merge.yaml` (новый)
- `multiprocess_prototype/recipes/tests/test_demo_recipe.py` (новый)
**Steps:**
1. Создать `multiprocess_prototype/recipes/demo_webcam_split_merge.yaml` следуя формату v2 (см. `recipes/manager.py` + `RecipeEngine`). Структура из master-плана (упрощённая под реальные плагины):
   ```yaml
   version: 2
   name: demo_webcam_split_merge
   description: webcam → split ROI → parallel processing → merge → display
   blueprint:
     name: demo_webcam_split_merge
     description: ...
     processes:
       - process_name: capture_proc
         plugins:
           - plugin_name: capture
           - plugin_name: resize
           - plugin_name: region_split
       - process_name: roi_a_proc
         plugins:
           - plugin_name: grayscale
           - plugin_name: color_mask
       - process_name: roi_b_proc
         plugins:
           - plugin_name: negative
           - plugin_name: blur
       - process_name: merge_proc
         plugins:
           - plugin_name: stitcher
           - plugin_name: render_overlay
     wires:
       - {source: "capture_proc.region_split.region", target: "roi_a_proc.grayscale.frame"}
       - {source: "capture_proc.region_split.region", target: "roi_b_proc.negative.frame"}
       - {source: "roi_a_proc.color_mask.frame", target: "merge_proc.stitcher.region"}
       - {source: "roi_b_proc.blur.frame", target: "merge_proc.stitcher.region"}
   active_services: [webcam_camera]
   display_bindings:
     - {source: "merge_proc.render_overlay.frame", display: "main_output"}
     - {source: "capture_proc.resize.frame", display: "debug_input"}
   ```
2. Если `display_bindings` или `active_services` не предусмотрены текущей структурой recipe (см. `RecipeEngine.save`/`load`) — положить их в `data:` блок, чтобы сохранились при чтении/записи через `RecipeManager.read_recipe`.
3. Integration-тесты `test_demo_recipe.py`:
   - `test_demo_recipe_file_exists` — файл присутствует в `recipes/`.
   - `test_demo_recipe_loads_via_manager` — `RecipeManager.list()` содержит `demo_webcam_split_merge`; `read_recipe(...)` возвращает dict с `blueprint`.
   - `test_demo_recipe_blueprint_validates` — `blueprint` проходит `SystemBlueprint.model_validate(...)` если разрешено (мб нужен `_find_plugin_entry` поэтому используем `check()` опционально — если valid_check ругается, документируй причину).
   - `test_demo_recipe_references_existing_plugins` — все плагины из `processes` действительно есть в `Plugins/` (через `PluginRegistry.discover` + проверка `registry.get(name)`).
**Acceptance criteria:**
- [ ] Файл `recipes/demo_webcam_split_merge.yaml` присутствует.
- [ ] `RecipeManager.list()` его видит, `read_recipe` возвращает корректный dict.
- [ ] Все 4 плагина (capture, resize, region_split, grayscale, color_mask, negative, blur, stitcher, render_overlay) есть в реестре.
- [ ] 3-4 integration-теста проходят.
**Out of scope:** реальный запуск через ProcessManager с webcam (вне unit-test scope); validation через `SystemBlueprint.check()` (зависит от plugin metadata, может требовать polish — допустимо xfail с TODO).

---

## Acceptance (Phase 7b в целом) ✅ DONE

- [x] WireMetricsBadge на каждом edge показывает fps/latency/buffer_fill (даже idle "-- fps | -- ms | --%").
- [x] Цвет badge меняется по WireStatus (ok/idle/error).
- [x] Плагин `blur` обнаруживается в реестре и валидно обрабатывает BGR.
- [x] `recipes/demo_webcam_split_merge.yaml` загружается через RecipeManager, integration-тест зелёный.
- [x] Кнопка «Запустить активный рецепт» в action-колонке (graceful warning без proxy).
- [x] 77 unit/integration тестов суммарно (план был 25-35, превышено).
- E2E-тест с реальной webcam — вне scope (требует hardware), но рецепт готов к запуску при наличии работающего ProcessManager.

### Итоговые коммиты Phase 7b

| Task | Hash | Тесты |
|------|------|-------|
| 7b.1 | `30516920` | 16 |
| 7b.2 | `420c896d` | 15 |
| 7b.3 | `c39c4e45` | 18 |
| 7b.4 | `238fe9e2` | 15 |
| 7b.5 | `da227903` | 8 |
| 7b.6 | `1cdadfcc` | 5 |
| fix (clear_all + Literal) | `4a3b0b28` | +1 |

**Суммарно**: 322/322 pipeline-тестов проходят, validate.py PASS, регрессий нет. Reviewer вердикт после фикса — **APPROVED**.

### Что закрыто фиксом по ревью

- **medium**: `GraphScene.clear_all()` теперь эмиттит `edge_removed` для каждого wire до `clear()` — `WireMetricsController._badges` больше не держит stale-ссылки на удалённые C++ объекты.
- **low**: `WireMetricsModel.update_status` теперь принимает `Literal["ok", "idle", "error"]` — type checker ловит опечатки.

## Out of scope (отложено)

- Per-channel router stats в framework — отдельный backlog item (или в Phase 8).
- `ShmDashboardPanel` — отложено после MVP.
- Реальный smoke с camera — требует hardware setup.
- Drag-time preview red wire — отложено (Task 7a.6 уже даёт post-create warning).
- Hot-reload плагинов в RUNNING-процессах — вне scope.
