# Идея: `app_module` — «рыба-шаблон» приложения во framework

- **Статус:** НАБРОСОК (дизайн-заметка к мастер-плану, исполнение — в рамках Ф5)
- **Дата:** 2026-07-06
- **Ось:** чем больше универсального во framework — тем тоньше прототип (= рецепты + плагины + сервисы)
- **Связь с планом:** расширяет Ф5 (carve E + Phase 5); цель плана уже гласит: «composition root, где второе приложение = рецепт + манифест + тонкий bootstrap» — здесь эта цель материализуется в конкретный модуль

## 1. Целевая картина

Новое приложение на фреймворке — это **данные + декларации, почти без кода**:

```
my_app/
  app.yaml          # манифест: system, base-топология, активный pipeline, discovery-пути
  system.yaml       # системные настройки + defaults
  recipes/          # рецепты и топологии (продукт)
  registers/        # схемы регистров/форм
  plugins/          # свои плагины (опц.; общие берутся из Plugins/)
  theme/            # стилевой рецепт (опц.)
  run.py            # ~3 строки
```

```python
# run.py
from multiprocess_framework.modules.app_module import run_app
run_app(Path(__file__).parent / "app.yaml")
```

Слои (сверху вниз, импорты только вниз — как в правиле №9):

```
multiprocess_framework (20 модулей-механизмов)
        └── app_module (21-й) — «рыба»: generic composition root
Services (sql, hikvision, …) — интеграции
Plugins (vocabulary) — узлы пайплайна
my_app — данные (манифест, рецепты, регистры) + точечные хуки + branding
```

## 2. Что такое `app_module`

Не «ещё один менеджер», а **generic composition root**: код, который сегодня в
прототипе одинаков для любого приложения и отличается только конфигами/хуками.

### 2.1 Инвентарь переноса (по текущему коду)

| Кандидат | Сейчас (прототип) | Куда | Уже в плане? |
|---|---|---|---|
| Шов `SystemLauncher(...)+add_process` | `backend/launch.py:374-394` | `app_module.builder` | **Ф5.2 (E3)** |
| `SystemBuilder` целиком (build-контур: discover → normalize → assemble → launcher) | `backend/launch.py:228-396` | `app_module.builder` | E3 + новое |
| `AppManifest` + `load_manifest` | `backend/config/manifest.py` | `app_module.manifest` (с app-extras секцией) | новое |
| `unwrap_recipe` / `merge_topologies` / `load_topology_dict` | `backend/launch.py:58-161` | `app_module.recipes` поверх движка миграций **Ф4.5** | Ф4.6 частично |
| `BlueprintAssembler` / `normalize` / `FullReplacePlanner` | `backend/assembly/` | framework | **Ф5.3 (Phase 5)** |
| `RecipeManager` | `recipes/manager.py` | framework | **Ф5.3** |
| `ProcessManagerProcessApp` | `orchestrator.py` | `app_module.orchestrator` → generic `AppOrchestrator` с хук-точками | новое |
| `GenericProcessApp` (StateProxy-обвязка — уже 100% generic) | `generic_process_app.py` | `process_module` или `app_module` | новое, S |
| Bootstrap-контур (`resolve_manifest_path`, `persist_pipeline_choice`, `main`) | `main.py` | `app_module.entry` (`run_app`) | новое |
| `plugin_register_resolver` | — | framework | **Ф5.4 (E1)** |

Т.е. ~60% инвентаря уже запланировано (E1/E3/Phase 5) — `app_module` это
**крыша над carve-задачами Ф5**: они складываются не россыпью по модулям, а в
один связный модуль-шаблон с контрактом.

### 2.2 Точки расширения (где приложение подключает своё)

1. **Данные** — манифест, рецепты+топологии, registers-схемы, тема. Ноль кода.
2. **Плагины** — `discovery.plugin_paths` в system.yaml (уже работает так).
3. **Сервисы** — Services/* объявляются процессами/плагинами в топологии (уже так).
4. **Код-хуки** (минимум, через Protocol + DI, вместо наследования):
   - `state_bootstrap(bp_dict, sys_config) -> dict` — initial_state
     (сейчас `backend/state/bootstrap.py`);
   - `throttle_rules() -> list` (сейчас `backend/state/manager_setup.py`);
   - `topology_hooks: list[TopologyHook]` — обёртки вокруг `apply_topology`
     (сегодняшний пример: display_definitions reload/rollback в `orchestrator.py:148-198`
     становится **готовым хуком в комплекте**, а не наследником);
   - GUI: TabRegistry/TAB_ORDER (**Ф5.10**), branding (имя в баннере), theme;
   - `RuntimeDeps` двухслойный: FrameworkRuntime + app-extras (**Ф5.8**).

Проектный принцип: **декларация + хуки вместо наследования**. Базовый
`AppOrchestrator` во framework, app-специфика — списком хуков в `AppSpec`:

```python
spec = AppSpec(
    manifest_path=...,
    state_bootstrap=build_initial_state,      # хук, не подкласс
    topology_hooks=[DisplayDefinitionsHook()],# готовый хук из комплекта
    orchestrator_class=None,                  # аварийный люк: подкласс всё ещё можно
)
run_app(spec)   # или run_app("app.yaml") — spec собирается из манифеста
```

Наследование остаётся аварийным люком (`orchestrator_class_path` уже
DI-параметр по E3), но целевой путь — хуки.

### 2.3 «Рыба» = три артефакта

1. **`app_module`** — runtime-ядро (manifest, builder, orchestrator, entry).
2. **`examples/minimal_app/`** — референс-приложение из ~5 файлов
   (манифест + system.yaml + 1 рецепт + 1 плагин-генератор + run.py),
   живёт во framework и гоняется в CI как smoke. Это и исполняемая
   документация, и гарантия что framework самодостаточен (0 импортов из
   прототипа — enforced sentrux-boundary).
3. **Scaffold** (позже, опц.): `python -m multiprocess_framework.app new my_app`
   — копирует minimal_app с подстановкой имён. Дешёво, когда есть п.2.

## 3. Что НЕ утончается этим треком (честно)

- **frontend 78.6k LOC** — главная масса прототипа. Её тонизация идёт другими
  осями: трек F (god-split), E4 (формы 4→1), Ф5.8-5.10 (RuntimeDeps, GUI
  state-plane, TabSpec). Долгая цель — виджеты-домены постепенно во
  frontend_module, app-specific остаются вкладки/branding. Судьба флагмана —
  вопрос G0/G2, не этого наброска.
- **domain 8.8k + adapters 7.2k** — кандидаты в Services/Plugins по мере
  надобности, отдельными решениями (Принцип №1: без per-item одобрения ничего
  не переезжает «гигиенически»).

Метрика оси (вне frontend): сейчас backend 8.0k + top-level 0.5k generic-кода;
цель после Ф5+app_module — backend → ~1-2k тонких шимов, top-level run.py < 100 LOC.

## 4. Встраивание в мастер-план (без ломки порядка)

Порядок фаз не трогаем: `launch.py` — общий файл Ф4↔Ф5 (матрица конфликтов),
unwrap_recipe уходит в движок миграций в Ф4.6 → carve E3/5.3 после Ф4, как и
запланировано. Предлагаемые **новые задачи в Ф5** (после 5.1-5.3):

| Task | Суть | Acceptance | Усилие |
|---|---|---|---|
| 5.11 | `app_module` skeleton: manifest + entry (`run_app`) + generic `SystemBuilder` (собирает E3/5.3 под одну крышу); прототип — тонкий шим | оба рецепта бутятся через `run_app`; check_rules: 0 reverse-import | M |
| 5.12 | `AppOrchestrator` generic + хук-точки (state_bootstrap, throttle, topology_hooks); `ProcessManagerProcessApp` → композиция хуков; `GenericProcessApp` → framework | qt-smoke обоих рецептов; orchestrator прототипа ≤ ~30 LOC | M |
| 5.13 | `examples/minimal_app` + CI-smoke (headless boot через BackendHarness Ф1.3) | smoke зелёный; sentrux-boundary: examples не импортирует prototype | S/M |
| 5.14 опц | scaffold-генератор `app new` | сгенерированное приложение бутится | S |

Дисциплина module-contract (правило исполнения плана): `app_module` — новый
публичный модуль → README + Protocol-интерфейс + contract-тесты обязательны.

**Что можно уже сейчас, не дожидаясь Ф4/Ф5:** ничего кодом (Ф0 не закрыт:
0.2-0.6), но бумажно — зафиксировать этот набросок и учесть `app_module` в
вердиктах G0 (Ф0.5): ярус core должен включать всё, от чего зависит «рыба».
Единственный безопасный ранний код-кандидат — 5.4 (E1, чистая функция, конфликтов нет).

## 5. Открытые вопросы (к владельцу, по мере подхода к Ф5)

1. Имя: `app_module` / `application_module` / `bootstrap_module`? (реком.: `app_module`)
2. GUI-часть «рыбы»: входит ли generic-запуск frontend-процесса в 5.11 или
   отдельной задачей после 5.8/5.10? (реком.: отдельно, после)
3. minimal_app: с GUI-вкладкой или headless-only? (реком.: headless-only в 5.13,
   GUI-пример после Ф5.10)
