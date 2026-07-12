# app_module — архитектурные решения (ADR-APP-*)

Локальный индекс. Глобальный — `multiprocess_framework/DECISIONS.md`.

---

## ADR-APP-001 — app_module как верхний композиционный ярус (не 4-й корень)

**Контекст.** Композиционный код (assembly, launch, manifest, discover) исторически
застрял в прототипе. Нужен дом для generic-«рыбы» (Ф5.11).

**Решение.** Новый модуль `multiprocess_framework/modules/app_module` — ярус 2 внутри
framework. **Инвариант:** только композиция, ноль механизмов; внутри framework никто
его не импортирует (направление `app_module → остальные`). Enforce: sentrux boundary
`framework/* → app_module/*` + контракт-тест `test_no_other_framework_module_imports_app_module`.
Внутренние импорты — относительные (sentrux не резолвит relative → boundary ловит только
чужие absolute, не ложно-срабатывая на self).

**Отвергнуто:** (а) 4-й корневой пакет `multiprocess_platform/` — ещё одна граница и слой
шимов; ярус — роль в модели импортов, не директория. (б) builder внутри
`process_manager_module` — утолщение модуля яруса 1 содержимым яруса 2 (PM узнал бы про
рецепты/манифест). См. `app-template-idea.md §5`.

**Reversible:** yes (модуль аддитивен; прототип — тонкий шим поверх).

---

## ADR-APP-002 — манифест под движок миграций с первого дня (`version` + `extras`)

**Решение.** `AppManifest` несёт `version: int` (дефолт 1) + `extras: dict` (pass-through).
`extras` валидирует приложение, НЕ framework — туда складывается app-специфика
(тема/брендинг), которую generic-ядро не знает. Единый `version+extras`-контракт разделяют
`app.yaml`, манифест плагина (ADR-PM-013) и маркер сервиса `service.yaml`.

**Why:** иначе через год появится свой «unwrap_recipe» для манифеста. Задел движка
миграций дешевле ретрофита.

**Rejected:** плоский манифест без версии — отвергнут: миграция схемы стала бы ad-hoc.

---

## ADR-APP-003 — ManifestStore: единственная сериализованная точка read/write app.yaml (NEW-1)

**Контекст.** Манифест — разделяемое состояние двух процессов: backend
(`persist_pipeline_choice`) и GUI (`_persist_active_recipe`) независимо писали ключ
`pipeline` в `app.yaml` → гонка read-modify-write (потеря обновления, torn-read).

**Решение.** `ManifestStore` — одна точка: межпроцессный лок (`fcntl.flock` на sidecar
`<manifest>.lock`) сериализует RMW; атомарная запись (temp + `os.replace`) исключает
torn-read; комментарии сохраняются (ruamel round-trip). Оба писателя прототипа
переведены на `ManifestStore.set_pipeline`. Регресс гонки — `test_concurrent_writes_no_lost_update`.

**Why:** контракт «разделяемое состояние» сделан явным вместо конвенции «все пишут через
одну функцию».

**Risk:** low (flock advisory; на платформах без fcntl деградирует до in-process лока).
**Reversible:** yes.

---

## ADR-APP-004 — единый `discover()`: плагины по `plugin.py`, сервисы по маркеру `service.yaml`

**Контекст.** Плагины сканировались в ДВУХ местах (boot `launch.py` + switch
`orchestrator`), сервисы объявлялись вручную в топологии (A6).

**Решение.** Один framework-helper `discover(plugin_paths, service_paths)`:
- плагины — делегирование `PluginRegistry.discover` (рекурсивный `plugin.py`);
- сервисы — по маркер-файлу `service.yaml` в каталоге сервиса (директива владельца
  2026-07-11; симметрично `plugin.py`/манифесту плагина; тот же `version+extras`).

Обе копии в прототипе переведены на этот helper. Границы слоёв не нарушены: плагины
подгружаются динамически (`importlib`), сервисы читаются как YAML-данные — статических
импортов Plugins/Services из framework нет.

**Rejected:** дискавери сервиса по имени/конвенции каталога — отвергнуто владельцем в
пользу явного маркера (симметрия и явность важнее «магии»).

---

## ADR-APP-005 — два режима сборки; carve прикладного BlueprintAssembler отложен (вход Ф5.12)

**Решение.** `SystemBuilder` двухрежимный:
- **generic** — granular build-time хуки с framework-defaults (`default_blueprint_loader`
  + `assemble_proc_dicts`), базовый `ProcessManagerProcess`. minimal_app доказывает
  самодостаточность без прототипа.
- **factory** — `AppSpec.launcher_factory`: прототип собирает launcher своим сложившимся
  `SystemBuilder.build()` (снапшот 5.1 не трогаем); `run_app` даёт generic-контур.

**Осознанный остаток (Inspector-специфика за швом — вход Ф5.12).** Прикладной
`BlueprintAssembler` (framework-clean по зависимостям, но физически в
`multiprocess_prototype/backend/assembly`) добавляет per-category normalize из
прототипной `SystemConfig` + unwrap рецепта v3 + inject recipe_devices — этого нельзя
абстрагировать в generic `assemble_proc_dicts` без формализованных build-time хуков
(state-bootstrap/normalize) и generic `AppOrchestrator`, что и есть скоуп Ф5.12. Поэтому
`app_module.assemble_proc_dicts` (generic) и прототипный `BlueprintAssembler` (augmented)
временно сосуществуют: первый — для «рыбы» и как дом будущего carve, второй — за швом
`launcher_factory`. Физперенос assembler/planner → `process_manager/topology` (ADR-RCP-005)
и конвергенция — отдельные задачи после формализации хуков.

**Reversible:** yes (factory-режим — обёртка; удаление возвращает прямой вызов `build()`).
