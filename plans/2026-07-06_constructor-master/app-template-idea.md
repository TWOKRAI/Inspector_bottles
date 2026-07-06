# Идея: `app_module` — «рыба-шаблон» приложения во framework

- **Статус:** НАБРОСОК v2 (дизайн-заметка к мастер-плану, исполнение — в рамках Ф5)
- **Дата:** 2026-07-06 (v2 — после ревью: модель уровней, двухсортные хуки, вердикт по prototype_2)
- **Ось:** чем больше универсального во framework — тем тоньше прототип (= рецепты + плагины + сервисы)
- **Связь с планом:** расширяет Ф5 (carve E + Phase 5); цель плана уже гласит: «composition root, где второе приложение = рецепт + манифест + тонкий bootstrap» — здесь эта цель материализуется в конкретный модуль

## 1. Модель уровней (директива владельца, 2026-07-06)

| Уровень | Что это | Физический дом |
|---|---|---|
| 0 | Python + библиотеки | — |
| 1 | **Механизмы**: процессы, IPC, роутинг, state store, plugin-runtime | `multiprocess_framework` (20 модулей) — есть |
| 2 | **Платформа**: композиция, plugin-словарь, сервисы, движок рецептов | `app_module` (верхний ярус framework) + `Plugins/` + `Services/` |
| 3 | **Приложение**: Inspector Bottles | `multiprocess_prototype` — данные + branding + свои виджеты |

Критерий границы 1/2 — **механизм vs содержимое**: `PluginRegistry`/`PluginRunner` —
механизм (уровень 1, правильно живёт в framework), 19 плагинов словаря — содержимое
(уровень 2, правильно в `Plugins/`). Ничего из plugin-runtime не двигаем.

Уровень — это **роль в модели импортов** (правило №9 CLAUDE.md), а не обязательно
директория. Уровень 2 сегодня размазан: `Plugins/` и `Services/` уже выделены, а
композиционный код (assembly, launch, orchestrator, манифест, движок рецептов)
застрял в прототипе — его выделение и есть предмет этой заметки (= carve Ф4/Ф5 +
`app_module`). Формализация ярусной карты — в Ф8 H.1 (там же sentrux-boundaries).

## 2. Целевая картина

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

## 3. Что такое `app_module`

Не «ещё один менеджер», а **generic composition root**: код, который сегодня в
прототипе одинаков для любого приложения и отличается только конфигами/хуками.

**Инвариант (enforce в `.sentrux/rules.toml`):** `app_module` — только композиция,
ноль собственных механизмов; внутри framework никто не импортирует `app_module`
(он — верхний ярус). Если куску нужна своя логика — его место в существующем
модуле уровня 1. Это защита от «модуля-свалки».

### 3.1 Инвентарь переноса (по текущему коду)

| Кандидат | Сейчас (прототип) | Куда | Уже в плане? |
|---|---|---|---|
| Шов `SystemLauncher(...)+add_process` | `backend/launch.py:374-394` | `app_module.builder` | **Ф5.2 (E3)** |
| `SystemBuilder` целиком (build-контур: discover → normalize → assemble → launcher) | `backend/launch.py:228-396` | `app_module.builder` | E3 + новое |
| `AppManifest` + `load_manifest` | `backend/config/manifest.py` | `app_module.manifest` (core-поля + `extras` + `version`) | новое |
| `unwrap_recipe` / `merge_topologies` / `load_topology_dict` | `backend/launch.py:58-161` | `app_module.recipes` поверх движка миграций **Ф4.5** | Ф4.6 частично |
| `BlueprintAssembler` / `normalize` / `FullReplacePlanner` | `backend/assembly/` | framework | **Ф5.3 (Phase 5)** |
| `RecipeManager` | `recipes/manager.py` | framework | **Ф5.3** |
| `ProcessManagerProcessApp` | `orchestrator.py` | `app_module.orchestrator` → generic `AppOrchestrator` с хук-точками | новое |
| `GenericProcessApp` (StateProxy-обвязка — уже 100% generic) | `generic_process_app.py` | **строго `app_module`** (см. §3.2-прим.) | новое, S |
| Bootstrap-контур (`resolve_manifest_path`, `persist_pipeline_choice`, `main`) | `main.py` | `app_module.entry` (`run_app`) | новое |
| `plugin_register_resolver` | — | framework | **Ф5.4 (E1)** |

Т.е. ~60% инвентаря уже запланировано (E1/E3/Phase 5) — `app_module` это
**крыша над carve-задачами Ф5**: они складываются не россыпью по модулям, а в
один связный модуль-шаблон с контрактом.

**Примечание к `GenericProcessApp`:** `process_module` ссылается на state_store
только под `TYPE_CHECKING` (`process_module/core/process_module.py:11-12`) —
runtime-зависимости нет. Перенос в `process_module` создал бы новое межмодульное
ребро (runtime-импорт `StateProxy`) и просадил sentrux modularity/depth. Поэтому —
только `app_module` (композиционный слой).

### 3.2 Точки расширения (где приложение подключает своё)

1. **Данные** — манифест, рецепты+топологии, registers-схемы, тема. Ноль кода.
2. **Плагины** — `discovery.plugin_paths` в system.yaml (уже работает так).
3. **Сервисы** — Services/* объявляются процессами/плагинами в топологии (уже так).
4. **Код-хуки** — минимум, через Protocol + DI, вместо наследования. **Хуки двух
   сортов** (следствие spawn + Dict-at-Boundary):

   | Сорт | Где выполняется | Форма | Примеры |
   |---|---|---|---|
   | **build-time** | launcher-процесс, до spawn | обычный callable | `state_bootstrap(bp_dict, sys_config) -> dict` (сейчас `backend/state/bootstrap.py`), `throttle_rules()` (`backend/state/manager_setup.py`) |
   | **runtime** | PM/дочерние процессы, после spawn | **import-path (строка) + конфиг-dict** — callable через spawn не пиклится | `topology_hooks`: display_definitions reload/rollback (`orchestrator.py:148-198`) становится готовым хуком в комплекте |

   Runtime-хуки — тот же паттерн, что уже работающий `orchestrator_class_path`
   (строка в `orchestrator_config`, `launch.py:377-391`): DI по import-path,
   конфиг — pickle-safe dict.

5. **GUI**: TabRegistry/TAB_ORDER (**Ф5.10**), branding (имя в баннере), theme;
   `RuntimeDeps` двухслойный: FrameworkRuntime + app-extras (**Ф5.8**).

Проектный принцип: **декларация + хуки вместо наследования**:

```python
spec = AppSpec(
    manifest_path=...,
    state_bootstrap=build_initial_state,        # build-time: callable
    topology_hooks=[                             # runtime: import-path + dict
        ("multiprocess_framework.modules.app_module.hooks.DisplayDefinitionsHook", {}),
    ],
    orchestrator_class_path=None,                # аварийный люк: подкласс всё ещё можно
)
run_app(spec)   # или run_app("app.yaml") — spec собирается из манифеста
```

**Правило против hook-взрыва (защита от обобщения с N=1):** хук попадает в
`AppSpec` только если (а) прототип нуждается в нём сегодня И (б) minimal_app
может жить без него (хук опционален). Никакого «hook-фреймворка» — плоский
список типизированных точек.

### 3.3 «Рыба» = три артефакта

1. **`app_module`** — runtime-ядро (manifest, builder, orchestrator, entry).
2. **`examples/minimal_app/`** — референс-приложение из ~5 файлов
   (манифест + system.yaml + 1 рецепт + 1 плагин-генератор + run.py).
   **Строится ОДНОВРЕМЕННО с 5.11/5.12, не после** — это второй потребитель
   и forcing function против Inspector-специфичных допущений в «универсальном».
   Гоняется в CI как smoke = исполняемая документация + автоматическое
   доказательство самодостаточности уровня 2 (0 импортов из прототипа —
   enforced sentrux-boundary).
3. **Scaffold** (позже, опц.): `python -m multiprocess_framework.app new my_app`
   — копирует minimal_app с подстановкой имён. Дешёво, когда есть п.2.

### 3.4 Сопутствующая гигиена (в acceptance 5.11)

- **Env-нейтральность**: брендинг уже протёк во framework — `INSPECTOR_PID_FILE`
  (`pid_registry.py:26`, `system_launcher.py:129`); logger уже умеет двойной ключ
  `MULTIPROCESS_*/INSPECTOR_*` (`log_paths.py:20`). Добавить алиасы (НЕ
  переименование — back-compat).
- **Манифест под движок миграций с первого дня**: `version: 1` + `extras: dict`
  (pass-through, валидирует приложение, не framework) — иначе через год появится
  свой «unwrap_recipe» для манифеста.
- **Манифест = разделяемое состояние двух процессов**: backend и GUI читают один
  app.yaml (`persist_pipeline_choice` существует именно поэтому). В `app_module`
  контракт сделать явным — одна точка read/write, а не конвенция.

## 4. Что НЕ утончается этим треком (честно)

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

## 5. Отвергнутые альтернативы (решения 2026-07-06)

| Альтернатива | Почему отвергнута |
|---|---|
| **`multiprocess_prototype_2`** (новый прототип рядом) | Двойная поддержка (каждый фикс ×2), 78k LOC frontend быстро не переписать, директива «2 живых рецепта не ломать» держит старый живым надолго. Проект уже проходил параллельные версии — v1/v2/backup удалены совсем недавно (e128b930). Правильная механика — **strangler fig на месте**: характеризационный тест 5.1 → carve → тонкий шим → рецепты работают каждый день. Пользу prototype_2 («доказать самодостаточность уровня 2») даёт minimal_app за 1/100 цены. Если понадобится второе продуктовое приложение — оно создастся из «рыбы» за день, и это будет подтверждение конструктора, а не копия |
| **Четвёртый корневой пакет `multiprocess_platform/`** | Уровень 2 уже имеет три дома (`app_module` + `Plugins/` + `Services/`). Новый корень = ещё одна граница в rules.toml, слой шимов ×2, вечный спор «framework или platform?» на каждом переносе. Уровень — роль в модели импортов, не директория |
| **Builder внутри `process_manager_module/launcher`** (предлагал docstring `launch.py`) | PM-модуль узнал бы про рецепты/манифест/state bootstrap — утолщение модуля уровня 1 содержимым уровня 2 |
| **Хуки-callable в runtime-точках** | Не пиклятся через spawn; runtime-расширения — только import-path + dict (паттерн `orchestrator_class_path`) |

## 6. Встраивание в мастер-план (без ломки порядка)

Порядок фаз не трогаем: `launch.py` — общий файл Ф4↔Ф5 (матрица конфликтов),
unwrap_recipe уходит в движок миграций в Ф4.6 → carve E3/5.3 после Ф4, как и
запланировано. Предлагаемые **новые задачи в Ф5** (после 5.1-5.3):

| Task | Суть | Acceptance | Усилие |
|---|---|---|---|
| 5.11 | `app_module` skeleton: manifest (`version`+`extras`) + entry (`run_app`) + generic `SystemBuilder` (собирает E3/5.3 под одну крышу) + env-алиасы `MULTIPROCESS_*`; прототип — тонкий шим. **Параллельно каркас minimal_app** | оба рецепта бутятся через `run_app`; minimal_app бутится headless; check_rules: 0 reverse-import, внутри framework 0 импортов app_module | M |
| 5.12 | `AppOrchestrator` generic + хук-точки двух сортов (§3.2); `ProcessManagerProcessApp` → композиция хуков; `GenericProcessApp` → `app_module`. minimal_app живёт без единого хука (проверка опциональности) | qt-smoke обоих рецептов; orchestrator прототипа ≤ ~30 LOC | M |
| 5.13 | `examples/minimal_app` финализация + CI-smoke (headless boot через BackendHarness Ф1.3) | smoke зелёный в CI; sentrux-boundary: examples не импортирует prototype | S/M |
| 5.14 опц | scaffold-генератор `app new` | сгенерированное приложение бутится | S |

Дисциплина module-contract (правило исполнения плана): `app_module` — новый
публичный модуль → README + Protocol-интерфейс + contract-тесты обязательны.

**Что можно уже сейчас, не дожидаясь Ф4/Ф5:** ничего кодом (Ф0 не закрыт:
0.2-0.6), но бумажно — этот набросок зафиксирован; в вердиктах G0 (Ф0.5)
проверить, что ярус core покрывает **транзитивные зависимости «рыбы»** (чтобы
freeze-вердикт не заморозил то, на чём стоит шаблон). Единственный безопасный
ранний код-кандидат — 5.4 (E1, чистая функция, конфликтов нет).

## 7. Открытые вопросы (к владельцу, по мере подхода к Ф5)

1. Имя: `app_module` / `application_module` / `bootstrap_module`? (реком.: `app_module`)
2. GUI-часть «рыбы»: входит ли generic-запуск frontend-процесса в 5.11 или
   отдельной задачей после 5.8/5.10? (реком.: отдельно, после)
3. minimal_app: с GUI-вкладкой или headless-only? (реком.: headless-only в 5.13,
   GUI-пример после Ф5.10)

~~4. Куда `GenericProcessApp` — `process_module` или `app_module`?~~ — РЕШЕНО:
строго `app_module` (§3.1-прим., иначе новое runtime-ребро process→state_store).
