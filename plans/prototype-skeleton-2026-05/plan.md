# Прототип Inspector: целевой скелет «конструктора» (master plan)

> **Slug**: `prototype-skeleton-2026-05`
> **Дата**: 2026-05-24
> **Статус**: обзорный (master plan). Каждая фаза — отдельный файл в этой папке (`phase-*.md`) с собственной веткой `feat/<phase-slug>` или `chore/<phase-slug>`.
> **Внутренний trace в Claude Code**: `~/.claude/plans/multiprocess-prototype-drifting-hoare.md` (sync через dual-save).

## Контекст и история ревизий

Первая версия плана опиралась на ошибочные допущения: «готовый» Constructor-слой (DisplayTargetNode, WireMetricsBadge, PluginGraphAdapter — ~3300 строк) на самом деле **удалён в коммите `261b90f`**; PipelineTab сейчас на **нативном QGraphicsScene** (не NodeGraphQt); плагин `blur` не существует; stitcher имеет один порт `region` и работает через **InspectorManager fan-in** (по `seq_id`), а не через multi-port wires; конфиг живёт в `backend/config/`, не `config/`.

Параллельно вторая разведка выявила, что **в `multiprocess_prototype_backup/` есть готовые куски**, которые сэкономят недели работы:
- `backend/shm/{registry,ring_buffer}.py` — SHM-инфраструктура display-каналов
- `backend/routing/frame_router_setup.py` — fan-out с `subscribe_to_camera/unsubscribe_from_camera`
- `state_store/recipes/recipe_engine.py` + v1→v2 миграции — паттерн версионирования рецептов
- `plugins/manager.py` — auto-discovery + `importlib.reload` (hot-reload)
- `state_store/adapters/{recipe,camera_state,registers}_adapter.py` — двусторонняя синхронизация StateStore ↔ домен
- `services/{camera,database,metrics}` — чистые service-классы (готовые жители ServiceRegistry)

**Цель**: связать готовые блоки в живой контур «процессы → плагины → сервисы → дисплеи → рецепты → pipeline», максимально config-driven. **Эталон верификации** уточнён под реальную архитектуру stitcher: webcam → resize → region_split (выдаёт N items с `target=stitcher_proc.stitcher` и `total_regions=N`) → 2 параллельных процесса (gray+color_mask, negative+blur) → InspectorManager собирает в merge-процессе → stitcher склеивает → render_overlay → display через SHM-канал.

**Подход**: НЕ возвращаемся к NodeGraphQt (текущий QGraphicsScene с Schema-Driven Ports уже работает). НЕ восстанавливаем удалённый PluginGraphAdapter слепо (используем как reference через `git show 9885bb88:<path>`). **Наследуем идеи** (раздельная wire-status/metrics телеметрия, display как узел первого класса, signal-suppression). **Переносим из backup** готовый код, который покрывает реальные дыры.

## Принцип «framework first»

**Любой компонент, имеющий смысл вне конкретного приложения Inspector, проектируется и живёт в `multiprocess_framework/`. Prototype потребляет framework через публичные API и Protocol-контракты — он не место для повторно используемой логики.**

Это значит:
- `ServiceRegistry`, `DisplayRegistry`, `RecipeEngine`, `FrameRouter`, `PluginManager` (hot-reload), `IStateAdapter`, расширения `ProcessManager` — все эти кирпичи **в framework**.
- В prototype остаются: конфиги, blueprints/рецепты как данные, конкретные адаптеры (реализуют framework Protocol), MVP-вью вкладок, точки входа (`main.py`, `app.py`), регистрация конкретных плагинов/сервисов.
- Каждый новый framework-модуль имеет: `interfaces.py` (Protocol), `README.md`, `STATUS.md`, `DECISIONS.md` (локальный ADR), `tests/` с unit-тестами публичного API. Без этого модуль не считается завершённым.
- Plugins/Services следуют ADR-120/121/122 — vocabulary в `Plugins/`, прикладные SDK в `Services/`, импорты только вверх по слою.

Если по ходу возникает сомнение «куда положить» — дефолт **framework**, prototype получает лишь то, что не имеет смысла без конкретного приложения (специфичные конфиги, конкретные blueprint'ы, конкретные сервисы вроде `webcam_camera`).

---

## Архитектурное видение

Шесть вкладок, каждая — view над общим Config + StateStore. Ключевые архитектурные решения:

- **Рецепт = полный SystemBlueprint + application-секции** (`active_services`, `display_bindings`). Старый формат `recipe_N.yaml` (8 слотов с topology dict) → новый `recipe_<slug>.yaml` через `RecipeEngine` (уже в framework) с новой миграцией формата v1→v2.
- **Дисплей = именованный SHM-канал** (через `shared_resources_module` + `RouterManager.register_broadcast_route`). Не плагин, не процесс. Узел `Display` в PipelineTab — декларативный приёмник (QGraphicsItem с входным портом).
- **Сервисы — гибрид**: `ServiceRegistry` (singleton по образу `PluginRegistry`) для long-running объектов (камеры, БД, auth), в pipeline вызываются через плагин-обёртки (как `hikvision_camera`).
- **Fan-out на уровне Router**: один output_port → несколько edges → broadcast в несколько каналов через `RouterManager.register_broadcast_route()` (уже готово).
- **Fan-in на уровне InspectorManager**: для merge остаётся существующий паттерн (region_split проставляет `item["target"]` и `total_regions`, InspectorManager буферизует по `(camera_id, seq_id)`, stitcher получает коллекцию). Демо собирается под этот паттерн, не под мультипорт.

| Вкладка | Роль | Что показывает / редактирует |
|---------|------|------------------------------|
| **Процессы** | Runtime | Список запущенных процессов из активного рецепта; GUI+orchestrator защищены; мониторинг (heartbeat, cpu, memory) |
| **Плагины** | Каталог + sandbox | Discovery из `plugin_paths` (через `PluginManager` из backup); подвкладка «Пути»; sandbox-тест плагина (файл/камера → preview) |
| **Сервисы** | Каталог + lifecycle | Discovery из `service_paths`; подвкладка «Пути»; start/stop/restart долгоживущих сервисов |
| **Дисплеи** | CRUD SHM-приёмников | CRUD дисплеев (id, размер, формат, fps_limit, ring_buffer_size); preview-окно для проверки; layout-пресеты (1x1/2x2) — опционально после MVP |
| **Рецепты** | Менеджер blueprints | CRUD рецептов; выбор активного → `ProcessManager.replace_blueprint()` (рабочие процессы перезапускаются, GUI и orchestrator живут); регистры = базовые + от плагинов/сервисов рецепта |
| **Pipeline** | Сборка цепочек активного рецепта | QGraphicsScene-редактор: chain из плагинов+сервисов+display-узлов; привязка узла к процессу; persist в рецепт |

Все вкладки читают/пишут через `ConfigManager`, `StateProxy`, `PluginRegistry`, `ServiceRegistry`, `DisplayRegistry`, `RecipeManager`. Никаких параллельных источников правды.

---

## Индекс фаз

| Phase | Файл | Slug ветки | Дней | Зависимости |
|-------|------|------------|------|-------------|
| **0** ✓ | [phase-0-foundation.md](phase-0-foundation.md) | `chore/foundation-from-backup-and-state-schema` | 2-3 | — | <!-- DONE bea4c72 -->
| **1** ✓ | [phase-1-processes-protection.md](phase-1-processes-protection.md) | `feat/processes-protection` | 1 | Phase 0 | <!-- DONE c6b9862 -->
| **2** ✓ | [phase-2-discovery-config-paths.md](phase-2-discovery-config-paths.md) | `feat/discovery-config-paths` | 2-3 | Phase 0 | <!-- DONE d405e1e -->
| **3** ✓ | [phase-3-service-registry.md](phase-3-service-registry.md) | `feat/service-registry` | 3-4 | Phase 0 | <!-- DONE 3ed4ec4 -->
| **4** ✓ | [phase-4-displays-tab.md](phase-4-displays-tab.md) | `feat/displays-tab` | 5-7 | Phase 0 | <!-- DONE b7fa95db -->
| **5** ✓ | [phase-5-recipes-manager-v2.md](phase-5-recipes-manager-v2.md) | `feat/recipes-manager-v2` | 7-10 | 2, 3, 4 | <!-- DONE 506308a1 -->
| **6** ✓ | [phase-6-plugin-sandbox.md](phase-6-plugin-sandbox.md) | `feat/plugin-sandbox` | 2-3 | Phase 3 | <!-- DONE 3947353e -->
| **7a** ✓ | [phase-7a-display-node-and-io.md](phase-7a-display-node-and-io.md) | `feat/pipeline-display-node-and-io` | 4-5 | 4, 5 | <!-- DONE 935c2b49 -->
| **7b** ✓ | [phase-7b-telemetry-and-demo.md](phase-7b-telemetry-and-demo.md) | `feat/pipeline-telemetry-and-demo` | 4-5 | Phase 7a | <!-- DONE 4a3b0b28 -->
| **8** ✓ | [phase-8-verification-and-docs.md](phase-8-verification-and-docs.md) | `chore/verification-and-docs` | 2-3 | All previous | <!-- DONE 9665ed4d -->

**Параллелизация**:
- Phase 0 — обязательно первой, блокирует 4, 5, частично 3 (нужен StateAdapterBase).
- Phase 1, 2 — независимые, можно параллельно после Phase 0.
- Phase 3 — после 0 (для StateAdapterBase + регистрации сервисов).
- Phase 4 — после 0.
- Phase 5 — после 2 (paths), 3 (services), 4 (displays).
- Phase 6 — после 3 (для webcam snapshot).
- Phase 7a — после 4 (DisplayRegistry) и 5 (recipe → graph IO).
- Phase 7b — после 7a.

---

## Реалистичная оценка

| Phase | Days | Что | Ключевой риск |
|-------|------|-----|---------------|
| 0 | 2-3 | Перенос из backup (без ring_buffer/RecipeEngine — уже в framework) + state schema | Скрытые зависимости backup-кода |
| 1 | 1 | Защита процессов | — |
| 2 | 2-3 | Discovery + paths UI + PluginManager hot-reload | — |
| 3 | 3-4 | ServiceRegistry + 1-2 сервиса | lifecycle state machine bugs |
| 4 | 5-7 | DisplayRegistry + tab + preview | SHM lifecycle при удалении дисплея |
| 5 | 7-10 | RecipeManager + НОВАЯ миграция формата + replace_blueprint с rollback | replace_blueprint partial-failure rollback (15-20 integration-тестов) |
| 6 | 2-3 | Sandbox плагина | mock SubPluginContext для render-плагинов |
| 7a | 4-5 | DisplayNodeItem + target_process + graph↔blueprint serialization | двусторонняя сериализация |
| 7b | 4-5 | Wire telemetry (rewrite по чертежу) + создание blur + end-to-end демо + integration test | InspectorManager seq_id sync через 3 процесса |
| 8 | 2-3 | Верификация + docs | — |
| **Итого** | **32-44 рабочих дня** | — | — |

С учётом buffer на интеграционные баги — **40-55 дней календарного времени** одного разработчика. Параллелизация (Phases 1, 2, 3 независимы; 4 после 0; 5 после 2+3+4; 6 после 3; 7a/7b финальная пара) сжимает до **4-6 недель** при работе 2-3 агентов.

---

## Конвенция Refs trailer

Каждый коммит фазы → оба плана через запятую:

```
Refs: plans/prototype-skeleton-2026-05/phase-N-<slug>.md, plans/prototype-skeleton-2026-05/plan.md
```

Пример для Phase 1:

```
Refs: plans/prototype-skeleton-2026-05/phase-1-processes-protection.md, plans/prototype-skeleton-2026-05/plan.md
```

---

## Критические файлы (мутации, агрегировано)

**Framework (новое — основной фокус «framework first»)**:
- `multiprocess_framework/modules/service_module/{interfaces,registry,lifecycle,scanner}.py` + `tests/` + `README.md` + `STATUS.md` + `DECISIONS.md` (Phase 3)
- `multiprocess_framework/modules/display_module/{interfaces,registry}.py` + `tests/` + `README.md` + `STATUS.md` + `DECISIONS.md` (Phase 4)
- `multiprocess_framework/modules/shared_resources_module/routing/frame_subscribe.py` — utility helper над `RouterManager.register_broadcast_route`, **не** отдельный модуль (Phase 0; альтернатива — в prototype если останется Inspector-специфика, ADR в Phase 0)
- `multiprocess_framework/modules/process_module/plugins/manager.py` — PluginManager hot-reload (Phase 0, из backup)
- `multiprocess_framework/modules/state_store_module/adapters/base.py` — `IStateAdapter` + `StateAdapterBase` (Phase 0)
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` — новый метод `replace_blueprint` с snapshot+rollback (Phase 5)
- `multiprocess_framework/DECISIONS.md` — индекс новых ADR (SystemBlueprint generic, FrameRouter helper, ServiceRegistry, DisplayRegistry, replace_blueprint)

**Framework НЕ трогаем** (уже готово, проверено в ревью):
- `multiprocess_framework/modules/state_store_module/recipes/recipe_engine.py` — `RecipeEngine` готов, используем как есть
- `multiprocess_framework/modules/shared_resources_module/buffers/ring_buffer.py` — `RingBuffer` готов
- `multiprocess_framework/modules/channel_routing_module/`, `router_module/` — `RouterManager.register_broadcast_route()` готов
- `.sentrux/rules.toml` — generic `from = "multiprocess_framework/*"` уже покрывает новые модули; после Phase 0 запускаем `mcp__sentrux__check_rules` для валидации

**Prototype (только application-specific — потребляет framework через публичные API)**:
- `multiprocess_prototype/main.py` + `frontend/app.py` — config-driven discovery (Phase 2)
- `multiprocess_prototype/backend/config/system.yaml` (+ optional `user_overrides.yaml`) — секция `discovery` (Phase 2)
- `multiprocess_prototype/backend/config/displays.yaml` — данные дисплеев (Phase 4, конкретный application config)
- `multiprocess_prototype/backend/state/adapters/{recipe,registers,service,display}_adapter.py` — конкретные адаптеры, наследуют framework `StateAdapterBase` (Phases 0/3/4/5)
- `multiprocess_prototype/backend/state/bootstrap.py` — application-bootstrap state-дерева (Phases 3/4/5)
- `multiprocess_prototype/recipes/` — папка с конкретными рецептами как данные (Phase 5/7)
- `multiprocess_prototype/recipes/manager.py` — application-обёртка над `RecipeEngine` из framework, держит `state.recipes.active` (Phase 5)
- `multiprocess_prototype/recipes/migrations/format_v1_to_v2.py` — конкретная миграция Inspector v1→v2 (Phase 5)
- `multiprocess_prototype/registers/manager.py` — учёт активного рецепта (Phase 5)
- `multiprocess_prototype/frontend/widgets/tabs/processes/` — защита (Phase 1)
- `multiprocess_prototype/frontend/widgets/tabs/plugins/` — подвкладка «Пути» + sandbox (Phases 2, 6)
- `multiprocess_prototype/frontend/widgets/tabs/services/` — каталог + подвкладка «Пути» + lifecycle (Phase 3)
- `multiprocess_prototype/frontend/widgets/tabs/displays/` — полное переписывание (Phase 4)
- `multiprocess_prototype/frontend/widgets/tabs/recipes/` — полное переписывание под blueprint-менеджер (Phase 5)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/` — DisplayNodeItem, target_process binding, io, telemetry (Phase 7)
- `multiprocess_prototype/frontend/widgets/displays/preview_window.py` — окно превью SHM-канала (Phase 4)

**Services (новое — webcam_camera + регистрация остальных)**:
- `Services/webcam_camera/service.py` + `__init__.py` — новый сервис из backup (Phase 3)
- `Services/sql/service.py`, `Services/hikvision_camera/service.py`, `Services/auth/service.py` — регистрация в ServiceRegistry (Phase 3)

**Plugins (минимально)**:
- `Plugins/processing/blur/` — новый плагин (Phase 7, ~50 строк, OpenCV GaussianBlur)
- Остальные 19 плагинов без изменений.

---

## Что **НЕ** входит в этот план

- Авторизация / RBAC (Services/auth — только регистрация в ServiceRegistry, не интеграция в GUI).
- Hot-reload плагинов **на лету в работающих процессах** (rescan каталога — да, замена кода в RUNNING-плагине — нет).
- Drag-drop плагина из палитры прямо на процесс в ProcessesTab.
- Сохранение результатов sandbox в файл / history.
- Запись/replay сессий кадров через дисплеи.
- Версионирование рецептов (история изменений), кроме миграции v1→v2.
- Layout-композитор дисплеев (1x1, 2x2) — отложен до после MVP; preview-окна отдельных дисплеев — да.
- Восстановление NodeGraphQt-слоя.
- ML-фазы (PyTorch, YOLO) — выходят за рамки скелета.

---

## Открытые вопросы (требуют решения по ходу)

1. **Persist путей** — `user_overrides.yaml` (рекомендую) vs прямо в `system.yaml`.
2. **Sandbox для sources-плагинов** — отложено. Альтернатива: live-preview в ServicesTab.
3. **Fan-out производительность** — fan-out по SHM при 30fps на full-res (1920x1080 BGR ~6.2 MB) даёт +186 MB/s per fan-out. Для debug-дисплея после resize (640x480) приемлемо. Для full-res нужно бенчмаркить в Phase 7.
4. **replace_blueprint partial failure** — rollback на предыдущий blueprint или partial state с warning? Решить в Phase 5.
5. **Dangling display references** — что если рецепт ссылается на display id, которого нет в `displays.yaml`? Валидация при загрузке + предупреждение пользователю. Решить в Phase 5.
6. **layout-композитор дисплеев** (1x1, 2x2 в одном окне) — нужен для finished продукта? Если да — отдельная фаза после MVP. Если только debug-окна на каждый дисплей — текущий план достаточен.
7. **Hot-reload плагинов** в RUNNING-процессах — выходит за scope, но требует решения «откладываем навсегда» или «отдельная фаза».

---

## Известные риски

1. **Перенос из backup может не быть чистым** — есть скрытые зависимости. План: portable модули копируем, остальное пишем с нуля по чертежу.
2. **replace_blueprint** — это **новый сложный код в framework**. Тестировать особо аккуратно, включая rollback на partial failure. Минимум 15-20 integration-тестов.
3. **Wire-телеметрия** — переписывание под нативный QGraphicsScene из NodeGraphQt-кода. Нужно проверить производительность (overlay-элементы на 30+ wire'ах при 30fps обновлении).
4. **InspectorManager seq_id sync** — для демо в Phase 7 region_split + stitcher должны корректно работать через несколько процессов. Возможны баги маршрутизации.
5. **Sentrux может потерять score** — много нового кода в framework (3 новых модуля). Контролировать через `session_start`/`session_end` на каждой фазе.

---

## История ревизий

- **v1** (изначальная) — содержала фактические ошибки про несуществующие компоненты, неверный формат stitcher, неверные пути конфига. Отвергнута на ревью.
- **v2** — переписана с учётом разведки: реальная фундация, перенос ценного из backup, разбивка на 9 фаз, принцип «framework first».
- **v2.1** — точечные правки после второй итерации ревью: убраны лишние ring_buffer/recipe_module (уже в framework), FrameRouter → utility, новая миграция формата (не та что в backup), display_bindings/active_services вне SystemBlueprint, реалистичные оценки Phase 5/7.
- **v3** (текущая) — переезд из одиночного `plans/prototype-skeleton-2026-05.md` в multi-phase папку `plans/prototype-skeleton-2026-05/` (master `plan.md` + phase-N файлы).
