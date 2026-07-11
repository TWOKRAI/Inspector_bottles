# Архитектура версионирования документов + дом движка миграций (4.5)

- **Дата:** 2026-07-10
- **Источник:** анализ 5 Fable-агентов (data_schema / state_store-recipes / config / prototype-carve / карта версионирования) + sentrux DSM + codegraph. Read-only, ссылки на файлы:строки внутри отчётов.
- **Повод:** перед задачей 4.5 (движок миграций dict-документов) владелец попросил разобрать РЕАЛЬНУЮ ответственность data_schema / recipes / config и спроектировать чистую границу, а не втыкать движок «куда-нибудь».
- **Статус:** предложение, ждёт решения владельца по дому 4.5 (новый модуль vs подпакет).

---

## 1. Корень мутности: слово «version» несёт ТРИ разных смысла

Это центральная находка. Сегодня три ортогональных концерна прячутся под одним словом и путаются:

| Смысл | Что делает | Где живёт сейчас | Состояние |
|---|---|---|---|
| **A. Миграция формата** | «документ v2 → v3»: эволюция формы данных между релизами | `RecipeEngine.migration_fn` (инъекция, ОДИН шаг) + `meta.version` + 9 разрозненных механизмов | размазано, дублируется |
| **B. История содержимого** | снапшоты экземпляра + откат (undo/rollback), до 100 версий | `data_schema_module/versioning/VersionManager` (~464 стр.) | **мёртвый** (0 внешних потребителей) |
| **C. Совместимость / манифест** | «плагин требует api_version ≥ X» | плагины 4.4 (`AppManifest`, `api_version`) | **ещё не построен** |

Задача 4.5 — это строго **A**. Но имя `versioning/` в `data_schema` уже занято смыслом **B**. Положить A рядом с B — закрепить путаницу навсегда. Поэтому «дом» — не косметика.

---

## 2. Инвентарь версионирования (смысл A) — ~9 механизмов, 0 переиспользования

| # | Место | Что | Механизм | Domain/Generic |
|---|---|---|---|---|
| 1 | `state_store_module/recipes/recipe_engine.py:196-245` | рецепт `meta.version` | **единственный настоящий раннер**, но одношаговый (одна инъецированная `migration_fn`, без цепочки), side-effect перезаписи файла на READ | generic-каркас, заточен под 1 doc_type |
| 2 | `state_store_module/recipes/migrations/__init__.py` | — | пустой placeholder (`__all__=[]`) | generic (мёртвый) |
| 3 | `prototype/backend/state/recipes/migrations/v1_to_v2.py` | regions→nodes | доменный, инъекция в №1 | domain |
| 4 | `prototype/recipes/migrations/format_v1_to_v2.py` | **другой** v1→v2 (displays/blueprint) | доменный, инъекция в тот же №1 из другого места | domain |
| 5 | `prototype/recipes/migrations/{displays_to_recipe,drop_display_name}.py` | формат рецепта | one-shot CLI `python -m`, свой `.bak` | domain, ad-hoc |
| 6 | `recipe_io.py` + `launch.py:unwrap_recipe` | v2 vs v3 | **версия по ФОРМЕ** (`"blueprint" in raw`), не по номеру; дублируется ×3 | domain (цель 4.6) |
| 7 | `data_schema/versioning/version_manager.py` | история экземпляров | snapshot/rollback (смысл **B**, не A!) | мёртвый |
| 8 | `data_schema/registry/process_registry.py:63` | `version="1.0.0"` | **декларация без механизма** — никто не читает | мёртвая декларация |
| 9 | `observability_store.py`, `auth/*` | SQLite-схемы, данные | ALTER-по-probe / data-backfill (не dict-документы) | domain, вне scope 4.5 |

**Ловушки, которые это порождает:**
- **Два одноимённых `v1_to_v2`** (№3 и №4) с разной семантикой инъектируются в ОДИН движок из разных мест → кто ищет «миграцию рецепта», найдёт не ту.
- **Определение версии по форме** дублируется трижды (движок, `recipe_io`, `unwrap_recipe`) → v4 придётся править в 3 местах.
- **`.bak`-логика** реализована дважды.
- Предел движка №1: `migration_fn: Callable[[dict],dict]` — одна функция на весь путь, нет цепочки v2→v3→v4, нет реестра doc_type, нет target. **Именно поэтому** появился второй параллельный wiring (№4) вместо добавления шага.

---

## 3. Сопутствующий долг, вскрытый анализом (НЕ scope 4.5 — отдельные тикеты)

Разбор границ обнажил накопленный долг в самих модулях. Фиксируем, чтобы не потерять; исполнение — отдельными задачами (в духе freeze-over-kill, Принцип №1 — не удаляем):

**data_schema_module** (10 237 LOC, 12 подпакетов — по факту 4 модуля под одной крышей):
- **~2 kLOC мёртвого «менеджерского стека»**: `versioning/VersionManager`, `api/`, `factory/`, `models/` — 0 внешних потребителей; `save_document/get_document` («версии рецептов») не зовётся нигде. Единственная нить — `shared_resources/adapters/data_schema_adapter.py:29`.
- Инфраструктура в «описании схем»: `storage/`, `serialization/file_storage.py` (файловый I/O).
- Топология процессов не на месте: `container/config_converters.py` (`process()`, `build_process_with_workers`) собирает proc_dict для лаунчера — дом рядом с `process_manager_module`.
- Прикладные типы в ядре framework: `core/field_types.py` — `HsvHue/FpsLimit/ImageScale` (CV-домен прототипа).

**config_module**:
- Скрытый от README слой `tools/` (loader/watcher/merge) — треть модуля.
- «Cross-process синхронизация через ConfigStore» — **мёртвая ветка**: ребёнок получает снапшот на spawn, живой синхронизации нет.
- **Латентный баг**: `ConfigManager._load_all_from_store` зовёт `config_store.list_keys()` — метода НЕТ; `AttributeError` глотается голым `except: pass` (`config_manager.py:206`); зелёный тест мокает несуществующий метод (`test_config_manager.py:27`) — ровно урок [[feedback_test_params_hide_defect_window]].
- **Три** реализации deep-merge с разной семантикой (`data_schema.merge_with_defaults`, `config.tools.deep_merge` (самозван «каноническим»), `prototype._deep_merge`).

**Граница config ↔ state_store**: различие не в механике (дерево+подписки+merge дублируются), а в **жизненном цикле и транспорте**: config = слоистый медленный вход (spawn-время + редкий hot-reload); state = высокочастотное runtime-дерево с адресной IPC-доставкой. Hot-reload watcher размывает границу — либо явный ADR-исключение, либо через штатный `config_reload`.

---

## 4. Решение по дому 4.5: **новый leaf-модуль `doc_migration_module`**

Сходимость 5 агентов: 4 из 5 → отдельный модуль или как минимум НЕ в текущих домах. Решающий аргумент — слои.

**Почему отдельный модуль, а не подпакет:**

1. **Клиенты движка распределены по ВСЕМ слоям** (`framework → Services → Plugins → prototype`, `.sentrux/rules.toml` order 0→3):
   - framework: `state_store/recipes` (№1), манифесты плагинов 4.4 (`process_module/plugins`)
   - Plugins: сами манифесты, `drawing_io.SCHEMA_VERSION`
   - prototype: рецепты, конфиги
   Любой дом выше framework (Services/prototype) отрезал бы framework-клиентов обратным импортом. План 4.5 фиксирует «ядро framework», 5.3 уже ссылается «форматы — из движка 4.5».

2. **Оба альтернативных дома тянут баласт:**
   - `state_store_module/recipes/` — движок = чистые dict→dict, ноль зависимостей от TreeStore; config/layout-клиенты тянули бы реактивное дерево; recipes сам — предмет carve-out 5.3.
   - `data_schema_module/` — там `versioning/` = смысл **B** (история), смешение усилит путаницу; модуль уже перегружен (12 подпакетов, ~2 kLOC мёртвого кода).

3. **Отдельный leaf** — единственный вариант, где `import doc_migration_module` не тянет НИЧЕГО (только stdlib). План так и говорит: «новый модуль с contract-тестами».

**Форма движка (смысл A):**
```
Реестр:   @migration(doc_type, from_=N, to=N+1) → step_fn(dict) → dict
Раннер:   migrate(doc_type, data, target)
            — читает meta.version (или detect_fn для legacy без версии)
            — строит цепочку v_n → v_{n+1} → ... → target
            — пишет meta.version = target
Политики: backup(.bak) — hook, не хардкод; strict/lenient при дыре в цепочке
Адаптер:  runner.as_migration_fn(doc_type, target) → Callable[[dict],dict]
            runner.as_check_fn(doc_type) → Callable[[dict],bool]
```

**Инварианты (property-тесты round-trip, приёмка 4.5):**
- цепочка монотонна и без дыр;
- идемпотентность: `migrate(migrate(x,n),n) == migrate(x,n)`;
- сохранение неизвестных ключей (Dict at Boundary — документы несут чужие секции);
- legacy без версии → detect_fn определяет старт-версию.

**Реестр — не через import-side-effects.** Система многопроцессная: шаги регистрируются в каждом процессе при boot (composition root), документ остаётся pickle-safe dict (Правило 1 Dict at Boundary).

---

## 5. Целевая карта ответственности (чистая архитектура)

| Ответственность | Дом (чистый) | Сегодня |
|---|---|---|
| **A. Миграция формата** dict-документов (generic) | **`doc_migration_module`** (новый leaf) | размазано ×9 |
| Конкретные шаги миграции рецепта (v1→v2 и т.д.) | prototype, **регистрируются** в движок декоратором | 2 одноимённых, мёртвые дефолты |
| **B. История/откат** содержимого | `data_schema/versioning` (или заморозить — мёртв) | мёртвый стек |
| **C. Манифест/совместимость** | плагины 4.4 (`AppManifest.api_version`) | не построен |
| Snapshot config-ветвей в YAML | `state_store/recipes/RecipeEngine` (убрать доменный `DEFAULT_CONFIG_PATHS`) | доменная протечка |
| Runtime-доступ к конфигу + слоистая сборка | `config_module` (сузить, внести `tools/` в README) | scope creep |
| Runtime-состояние + IPC-доставка | `state_store_module` | ок |
| Описание схем (Field/Routing/dispatch) + сериализация | `data_schema_module/core+registry+serialization` (вынести/заморозить мёртвый стек) | 4 модуля в одном |
| Единая READ-точка рецептов (`unwrap_recipe`) | 4.6 → через движок A | ветвление по форме ×3 |

---

## 6. Последовательность

1. **4.5** — построить `doc_migration_module` (реестр + раннер + адаптеры + property-тесты + module-contract). Аддитивно, ничего не ломает: существующие механизмы работают до перевода на адаптеры.
2. **4.6** — единая READ-точка: `unwrap_recipe`/`recipe_io` detect-by-shape → `detect_fn` реестра; grep формат-веток вне движка = 0.
3. **4.8** — канонизация записи рецепта как migration-шаг (байт-diff на одобрение владельца).
4. **5.3** — carve: `yaml_io` + assembler/planner + RecipeManager → framework; `duplicate()` через generic yaml_io + формат-стратегию из движка (блокер снят). Порядок **4.5 → 4.8 → 5.3** обязателен.
5. Legacy-инъекция `migration_fn` **не выпиливается** — прототип кормит её `runner.as_migration_fn(...)`; со временем (после 4.6/5.3) остаётся только для реально legacy envelope-файлов и замораживается.

**Отдельные тикеты (сопутствующий долг §3):** мёртвый стек data_schema (freeze), баг `list_keys()` + мок-тест config, три deep-merge → один, доменные протечки (`DEFAULT_CONFIG_PATHS`, `field_types`, `container/`). Не смешивать с 4.5.

---

## 7. Governance при заведении `doc_migration_module`

Новый модуль → инвариант «24 модуля» становится 25:
- обновить `multiprocess_framework/MODULES_STATUS.md`, `docs/MODULES_RESPONSIBILITY_MAP.md`, корневой CLAUDE.md (счётчик + строка),
- структура по Правилу 2: `interfaces.py` + `README.md` + `STATUS.md` + `DECISIONS.md` + `tests/`,
- module-contract skill обязателен (README + Protocol + contract-тесты),
- `python -m scripts.sync` + `python scripts/validate.py` после,
- ADR: локальный `doc_migration_module/DECISIONS.md` + индекс в `multiprocess_framework/DECISIONS.md`.
