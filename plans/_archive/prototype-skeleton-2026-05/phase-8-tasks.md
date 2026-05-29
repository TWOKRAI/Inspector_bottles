# Phase 8 — Декомпозиция задач: Верификация и документация

> **Master plan**: [plan.md](plan.md)
> **Phase plan**: [phase-8-verification-and-docs.md](phase-8-verification-and-docs.md)
> **Branch**: `chore/verification-and-docs`
> **Дата декомпозиции**: 2026-05-27
> **Refs trailer** (обязателен во всех коммитах этой фазы):
> `Refs: plans/prototype-skeleton-2026-05/phase-8-verification-and-docs.md, plans/prototype-skeleton-2026-05/plan.md`

---

## Разведка (что уже сделано — не дублировать)

### ADR: уже существуют
- **ADR-128** (Foundation Phase 0 — FrameRouter, IStateAdapter, PluginManager, state schema) — есть в `multiprocess_framework/DECISIONS.md`
- **ADR-129** (ServiceRegistry) — есть, с полным текстом
- **ADR-130** (DisplayRegistry) — есть, с полным текстом
- **ADR-131** (SystemBlueprint generic + параллельные yaml-секции) — есть
- **ADR-132** (replace_blueprint с snapshot+rollback) — есть
- **ADR-SVC-001/002/003** — есть в `multiprocess_framework/modules/service_module/DECISIONS.md`
- **ADR-DM-001/002/003** — есть в `multiprocess_framework/modules/display_module/DECISIONS.md`

### STATUS: уже актуальны
- `multiprocess_framework/modules/service_module/STATUS.md` — актуален, Phase 3 DONE
- `multiprocess_framework/modules/display_module/STATUS.md` — актуален, Phase 4 DONE

### Что требует обновления
- `multiprocess_framework/MODULES_STATUS.md` — дата 2026-05-10, нет `service_module`, `display_module`, `webcam_camera`
- `Services/STATUS.md` — нет `webcam_camera` в таблице
- `multiprocess_prototype/STATUS.md` — **не существует**
- `docs/refactors/2026-05_prototype_skeleton.md` — **не существует**
- Memory-файлы `project_service_registry.md`, `project_display_registry.md`, `project_recipes_manager.md`, `project_pipeline_demo.md` — **не существуют**
- `project_processes_tab.md` — есть, но описывает только Phase 1; Phase 2–7b не отражены

---

## Порядок выполнения

```
Task 8.1 (smoke + sentrux)   ← первой, блокирует запись результата в 8.3
Task 8.2 (ADR) ──────────────┐
Task 8.3 (refactor-doc/STATUS)├── параллельно после 8.1
Task 8.4 (memory + close plan)┘ ← последней (зависит от 8.1/8.2/8.3)
```

---

## Задачи

### Task 8.1 — Smoke-прогон и sentrux-верификация

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** прогнать все smoke-тесты и получить sentrux health-отчёт; зафиксировать результат в `verification-report.md`

**Files:**
- `plans/prototype-skeleton-2026-05/verification-report.md` — создать (результат прогона)
- `scripts/validate.py` — только запустить, не менять
- `scripts/run_framework_tests.py` — только запустить, не менять

**Steps:**
1. Запустить `python scripts/validate.py` из корня проекта. Записать вывод (pass/fail, список ошибок если есть).
2. Запустить `python scripts/run_framework_tests.py`. Записать итог (N passed / N skipped / N failed).
3. Запустить `make gate` (если Makefile доступен). Записать вывод ruff + pyright + bandit.
4. Вызвать `mcp__sentrux__scan` + `mcp__sentrux__health` (если session_start не запускался — используем scan напрямую). Записать итоговый score.
5. Создать `plans/prototype-skeleton-2026-05/verification-report.md` с секциями: «Smoke», «Tests», «Gate», «Sentrux». Для каждой — статус (OK / WARN / FAIL) и краткий вывод.
6. Зафиксировать коммитом `chore(verification): smoke + sentrux Phase 8` с обязательным Refs trailer.

**Acceptance criteria:**
- [ ] `python scripts/validate.py` — выход без ошибок (или список задокументирован в report)
- [ ] `python scripts/run_framework_tests.py` — 0 failed (skipped допустимо)
- [ ] sentrux score ≥ 7000 (baseline был 7161 до Phase 0; допустима просадка ≤ 5% за счёт новых модулей)
- [ ] `verification-report.md` создан и доступен для ссылки из Task 8.3
- [ ] Коммит содержит Refs trailer

**Out of scope:** исправление найденных багов (если есть ошибки — документировать в report и передать отдельной задачей). qt-mcp manual-прогон (не включён — интерактивный, выполняется пользователем руками согласно acceptance Phase 8).

**Edge cases:**
- Если `make gate` не установлен — пропустить, записать «skipped (Makefile not available)»
- Если sentrux недоступен (MCP не поднят) — запустить `mcp__sentrux__health` через CLI fallback; если и это недоступно — записать в report «sentrux unavailable, score not measured»

**Module contract:** n/a

---

### Task 8.2 — ADR: FrameRouter helper

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** tech-writer
**Goal:** создать ADR-133 (FrameRouter helper в prototype) в `multiprocess_framework/DECISIONS.md` и обновить TOC через scripts/sync

**Контекст:**
ADR-128 уже документирует Foundation Phase 0 и упоминает, что FrameRouter-логика осталась в prototype (`multiprocess_prototype/backend/routing/frame_router_setup.py`), а не в framework. Нужен отдельный ADR, фиксирующий это решение и его причину — чтобы будущие разработчики не пытались перенести camera_id-специфичный код в framework.

ADR-129..132 уже созданы (ServiceRegistry, DisplayRegistry, SystemBlueprint, replace_blueprint). Новый ADR только один — ADR-133.

**Files:**
- `multiprocess_framework/DECISIONS.md` — добавить ADR-133 и обновить TOC (секция `<!-- ADR-TOC:BEGIN ... ADR-TOC:END -->`)
- Запустить `python -m scripts.sync` для пересборки сводных разделов

**Steps:**
1. Прочитать `multiprocess_framework/DECISIONS.md` раздел ADR-128 — там уже описано почему FrameRouter остался в prototype. Понять суть.
2. Добавить в конец раздела «Принято» запись ADR-133 в стандартном формате:
   - Заголовок: `FrameRouter helper — camera_id-специфичная логика в prototype, не в framework`
   - Дата: 2026-05-27
   - Статус: принято
   - Контекст: FrameRouter (`frame_router_setup.py`) управляет `subscribe_to_camera/unsubscribe_from_camera` с sematics `camera_id`. Это Inspector-специфичная семантика, не generic routing.
   - Решение: `frame_router_setup.py` живёт в `multiprocess_prototype/backend/routing/`; framework предоставляет только `RouterManager.register_broadcast_route()` как строительный блок.
   - Причина: generic framework не должен знать о camera_id. Приложения с другой семантикой fan-out (аудио-каналы, lidar streams) строят свои helpers поверх framework API.
   - Отклонённые альтернативы: перенос в `shared_resources_module/routing/` — отклонено (нарушает generic-first принцип).
3. Добавить строку в `<!-- ADR-TOC:BEGIN ... ADR-TOC:END -->`:
   `- [ADR-133](#adr-133-...): FrameRouter helper — camera_id-специфичная логика в prototype`
4. Запустить `python -m scripts.sync` для валидации и пересборки.
5. Зафиксировать коммитом `docs(adr): ADR-133 FrameRouter helper — camera_id в prototype` с Refs trailer.

**Acceptance criteria:**
- [ ] ADR-133 добавлен в раздел «Принято» глобального DECISIONS.md
- [ ] TOC содержит ссылку на ADR-133
- [ ] `python -m scripts.sync` отработал без ошибок (нет sync-дрифта)
- [ ] Коммит содержит Refs trailer

**Out of scope:**
- Не создавать ADR-128..132 повторно (уже есть)
- Не создавать локальные DECISIONS.md для service_module и display_module (уже существуют)
- Не трогать `multiprocess_framework/docs/MODULE_CONTRACTS.md` в этой задаче

**Dependencies:** Task 8.1 (логически, но можно параллельно — только данные smoke не нужны для ADR)

**Module contract:** n/a

---

### Task 8.3 — Refactor-doc и обновление STATUS

**Level:** Middle (Sonnet, normal)
**Assignee:** tech-writer
**Goal:** создать `docs/refactors/2026-05_prototype_skeleton.md` и обновить MODULES_STATUS.md + Services/STATUS.md + создать multiprocess_prototype/STATUS.md

**Контекст:**
После Phase 0–7b были созданы: `service_module`, `display_module` в framework; `webcam_camera` в Services; `blur` плагин; demo-рецепт. MODULES_STATUS.md имеет дату 2026-05-10 и не знает об этих модулях. Services/STATUS.md не содержит `webcam_camera`. У прототипа нет STATUS.md.

**Files:**
- `docs/refactors/2026-05_prototype_skeleton.md` — создать
- `multiprocess_framework/MODULES_STATUS.md` — обновить
- `Services/STATUS.md` — обновить
- `multiprocess_prototype/STATUS.md` — создать

**Steps:**

**Шаг 1 — Создать `docs/refactors/2026-05_prototype_skeleton.md`:**
Структура документа:
```
# Рефактор: Prototype Skeleton 2026-05
## Что было собрано (Phases 0–7b)
## Ключевые архитектурные решения (ссылки на ADR-128..133)
## Новые модули фреймворка (service_module, display_module)
## Новые Services (webcam_camera)
## Новые Plugins (blur)
## Как мигрировать со старого формата рецептов v1 → v2
## Известные ограничения и defer-ы
```
Данные для заполнения — из STATUS.md модулей и phase-*.md файлов в plans/.

**Шаг 2 — Обновить `multiprocess_framework/MODULES_STATUS.md`:**
- Изменить строку "Обновлено:" → 2026-05-27
- Добавить строки для `service_module` и `display_module` в таблицу (после `state_store_module` и до `console_module`):
  - `service_module` | stable | ~500 | 91 | ServiceRegistry singleton + lifecycle + scanner; ADR-129, ADR-SVC-001/002/003
  - `display_module` | stable | ~300 | 12 | DisplayRegistry singleton + YAML persist; ADR-130, ADR-DM-001/002/003
- Обновить счётчик «Итого framework:» с 20 на 22 пакета (или 21 — уточнить по факту)
- Обновить «Тестов:» строку (добавить ~103 тестов к счётчику)

**Шаг 3 — Обновить `Services/STATUS.md`:**
- Добавить строку `webcam_camera` в таблицу:
  - `webcam_camera` | stable | WebcamCameraService; @register_service; из backup Phase 0 | ADR-128
- Обновить дату "Обновлено:"

**Шаг 4 — Создать `multiprocess_prototype/STATUS.md`:**
Структура:
```
# multiprocess_prototype — STATUS.md
## Что это
## Ключевые пути (backend/, frontend/, recipes/)
## Состояние вкладок (6 вкладок: статус каждой)
## Зависимости от framework-модулей
## Конфигурационные файлы
## Точка входа
```
Таблица вкладок:
| Вкладка | Статус | Phase | Ключевые файлы |
| Процессы | production | Phase 1 | tabs/processes/ |
| Плагины | stable | Phase 2, 6 | tabs/plugins/ |
| Сервисы | stable | Phase 3 | tabs/services/ |
| Дисплеи | stable | Phase 4 | tabs/displays/ |
| Рецепты | stable | Phase 5 | tabs/recipes/ |
| Pipeline | stable | Phase 7a/7b | tabs/pipeline/ |

**Steps (продолжение):**
5. Зафиксировать коммитом `docs(status): refactor-doc + STATUS обновления Phase 8` с Refs trailer.

**Acceptance criteria:**
- [ ] `docs/refactors/2026-05_prototype_skeleton.md` создан, содержит секции согласно структуре
- [ ] `MODULES_STATUS.md` содержит строки `service_module` и `display_module`
- [ ] `Services/STATUS.md` содержит строку `webcam_camera`
- [ ] `multiprocess_prototype/STATUS.md` создан, содержит таблицу 6 вкладок
- [ ] Коммит содержит Refs trailer

**Out of scope:**
- Не обновлять локальные STATUS.md модулей service_module и display_module (уже актуальны)
- Не обновлять `multiprocess_framework/docs/MODULES_OVERVIEW.md` — это отдельный большой документ (вне scope)
- Не писать полные описания каждого метода в refactor-doc — только архитектурный обзор

**Dependencies:** Task 8.1 (нужен verification-report.md для ссылки из refactor-doc)

**Module contract:** n/a

---

### Task 8.4 — Закрыть master plan и обновить memory (dual-write)

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** отметить Phase 8 DONE в master plan и создать/обновить memory-файлы в обоих местах (dual-write)

**Files:**
- `plans/prototype-skeleton-2026-05/plan.md` — отметить Phase 8 DONE + коммит-хэш
- `docs/claude/memory/project_service_registry.md` — создать
- `docs/claude/memory/project_display_registry.md` — создать
- `docs/claude/memory/project_recipes_manager.md` — создать
- `docs/claude/memory/project_pipeline_demo.md` — создать
- `docs/claude/memory/project_processes_tab.md` — обновить (добавить Phase 2–7b)
- `docs/claude/memory/MEMORY.md` — обновить индекс (добавить 4 новых записи)
- `~/.claude/projects/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/memory/` — дублировать все изменения (dual-write)

**Steps:**

**Шаг 1 — Обновить master plan:**
В `plans/prototype-skeleton-2026-05/plan.md` найти строку Phase 8 в таблице индекса фаз и добавить `✓` + комментарий `<!-- DONE <хэш> -->` (хэш — финальный коммит Phase 8).

**Шаг 2 — Создать memory-файлы (git-tracked часть в `docs/claude/memory/`):**

`project_service_registry.md`:
```yaml
---
name: ServiceRegistry implementation state
description: service_module в framework — реестр и lifecycle long-running сервисов
type: project
---
```
Содержание: singleton через __new__+Lock (ADR-SVC-001), IService Protocol (ADR-SVC-002), хранит классы не экземпляры (ADR-SVC-003); 91 тест; 4 сервиса зарегистрированы (webcam_camera, sql, hikvision_camera, auth); ADR-129 в DECISIONS.md; Phase 3 DONE коммит 3ed4ec4.

`project_display_registry.md`:
```yaml
---
name: DisplayRegistry implementation state
description: display_module в framework — реестр именованных SHM-каналов для отображения
type: project
---
```
Содержание: singleton (по образу ServiceRegistry); generic (нет vision-полей, ADR-DM-001); persist(path) явный аргумент (ADR-DM-002); cleanup только warning (ADR-DM-003); 12 тестов; ADR-130 в DECISIONS.md; Phase 4 DONE коммит b7fa95db.

`project_recipes_manager.md`:
```yaml
---
name: RecipesManager (RecipeEngine v2) state
description: Менеджер рецептов-blueprint'ов в прототипе; replace_blueprint с rollback
type: project
---
```
Содержание: Recipe = SystemBlueprint + параллельные секции (ADR-131); replace_blueprint с snapshot+rollback (ADR-132, ADR-PM-009); формат v1→v2 миграция; RecipeEngine из framework; Phase 5 DONE коммит 506308a1. Ключевые пути: `multiprocess_prototype/recipes/`, `multiprocess_prototype/backend/state/adapters/recipe_adapter.py`.

`project_pipeline_demo.md`:
```yaml
---
name: Pipeline demo recipe and telemetry state
description: Демо-рецепт webcam→split→processing→merge→display + wire telemetry Phase 7b
type: project
---
```
Содержание: demo_webcam_split_merge.yaml рецепт; Phase 7a — DisplayNodeItem + target_process binding; Phase 7b — WireStatus telemetry, blur plugin, edge_removed fixes; clear_all эмиттит edge_removed (4a3b0b28). Ключевые пути: `multiprocess_prototype/recipes/demo_webcam_split_merge.yaml`, `multiprocess_prototype/frontend/widgets/tabs/pipeline/`.

**Шаг 3 — Обновить `project_processes_tab.md`:**
Добавить секции Phase 2 (discovery + paths), Phase 3 (ServiceRegistry integration), Phase 5 (replace_blueprint кнопка «Запустить активный рецепт», da227903), Phase 7b (pipeline tab). Список ключевых коммитов по этим фазам взять из master plan.

**Шаг 4 — Обновить `docs/claude/memory/MEMORY.md`:**
Добавить 4 новых строки:
```
- [ServiceRegistry state](project_service_registry.md) — Phase 3 DONE: service_module framework, 91 tests, 4 services, ADR-129/SVC-001/002/003
- [DisplayRegistry state](project_display_registry.md) — Phase 4 DONE: display_module framework, 12 tests, generic (no vision fields), ADR-130/DM-001/002/003
- [RecipesManager v2 state](project_recipes_manager.md) — Phase 5 DONE: Recipe=SystemBlueprint+yaml-sections, replace_blueprint with rollback, ADR-131/132
- [Pipeline demo and telemetry](project_pipeline_demo.md) — Phase 7b DONE: webcam→split→merge→display demo, WireStatus telemetry, blur plugin
```

Обновить строку `project_processes_tab.md` в MEMORY.md (Phase 1-7b done, все 6 вкладок активны).

**Шаг 5 — Dual-write:**
Продублировать все созданные/изменённые файлы из `docs/claude/memory/` в `~/.claude/projects/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/memory/`. Обновить MEMORY.md там же.

**Шаг 6 — Коммит:**
`docs(plans): закрыть Phase 8 DONE + memory dual-write` с Refs trailer.

**Acceptance criteria:**
- [ ] В `plan.md` строка Phase 8 содержит `✓` и комментарий `<!-- DONE <хэш> -->`
- [ ] Все 4 новых memory-файла созданы в `docs/claude/memory/`
- [ ] `project_processes_tab.md` обновлён — отражает Phase 1–7b
- [ ] `docs/claude/memory/MEMORY.md` содержит 4 новых строки
- [ ] Дублирование в `~/.claude/.../memory/` выполнено (dual-write)
- [ ] Коммит содержит Refs trailer

**Out of scope:**
- Не трогать memory типа `feedback_*` (они не меняются)
- Не закрывать отдельные phase-*.md файлы (только master plan.md)
- Не создавать `handoff`-документ (выходит за scope Phase 8)

**Dependencies:** Task 8.1, 8.2, 8.3 (финальная задача)

**Module contract:** n/a

---

## Итоговая сводка

| Task | Исполнитель | Уровень | Блокирует | Дней |
|------|-------------|---------|-----------|------|
| 8.1 Smoke + sentrux | developer | Middle | 8.3 (report), 8.4 (коммит-хэш) | 0.5 |
| 8.2 ADR-133 | tech-writer | Middle+ | — | 0.5 |
| 8.3 Refactor-doc + STATUS | tech-writer | Middle | 8.4 | 0.5 |
| 8.4 Close plan + memory | developer | Middle | — | 0.5 |
| **Итого** | | | | **2 дня** |

**Параллелизация:** 8.1 и 8.2 — параллельно (нет зависимостей между собой). 8.3 — после 8.1. 8.4 — последней.
