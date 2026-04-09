# Refactoring plan: `config_module` (модуль #6)

> **Статус:** 🟢 Выполнено (2026-04-09).  
> **Автор плана:** Claude (Opus 4.6), Фаза 1 мета-плана v4.1.  
> **Исполнитель:** Cursor Composer Agent (Agent mode / Composer 2).  
> **Ссылки:** [00_overview.md](./00_overview.md) · [ARCHITECTURE.md](../../Inspector_prototype/multiprocess_framework/ARCHITECTURE.md)

---

## 0. Контекст

`config_module` — второй мягкий модуль (после `data_schema_module`). Уже проведён рефакторинг 2026-03-15 (STATUS.md указывает 8/8 этапы завершены). Однако:

1. **DECISIONS.md отсутствует** — нет локального документирования архитектурных решений (как в других модулях post-refactoring).
2. **Dict at Boundary проверка** — нужно подтвердить, что ConfigStore действительно использует dict на границе, а Pydantic только внутри (requirement из overview).
3. **Устаревшая документация** — `docs/ARCHITECTURE.md` и `docs/USAGE_GUIDE.md` написаны в контексте старой версии; нужна уборка дублирующегося с README.

**Цель:** закрепить ConfigStore как Dict-at-Boundary паттерн, добавить DECISIONS.md, убрать дублирование документации, подготовить модуль к использованию в других модулях (logger, error, stats).

**Сложность:** ★★☆☆☆ (простая) — модуль уже рефакторен; работа документационная + проверка паттерна.

---

## 1. Текущее состояние (baseline)

- **Файлов:** 11 `.py` (без tests/__pycache__)
- **LOC:** 1 074 (из overview; нужно уточнить в Шаге 0)
- **Тестов:** 3 файла (test_config.py ~21 test, test_config_manager.py ~18 test, test_config_section.py ~10 test = ~49 total)
- **Публичный API:** Config, ConfigManager, ConfigSection, IConfigManager, IConfig, IConfigObserver, ConfigSchemaAdapter, ConfigManagerConfig

### 1.1. Структура модуля

```
config_module/
├── __init__.py              # Публичный API
├── interfaces.py            # IConfig, IConfigManager, IConfigObserver
├── configs/
│   ├── config_manager_config.py  # ConfigManagerConfig (SchemaBase)
│   └── __init__.py
├── core/
│   ├── config.py            # Config (~160 LOC)
│   ├── config_manager.py    # ConfigManager (~215 LOC)
│   └── __init__.py
├── sections/
│   └── config_section.py    # ConfigSection
├── adapters/
│   └── schema_adapter.py    # ConfigSchemaAdapter
├── docs/
│   ├── ARCHITECTURE.md      # Архитектура (может дублировать README)
│   └── USAGE_GUIDE.md       # Подробное руководство (может дублировать README)
├── tests/
│   ├── conftest.py
│   ├── test_config.py       # 21 тест
│   ├── test_config_manager.py # 18 тестов
│   └── test_config_section.py # 10 тестов
├── README.md               # Кратко обзор
├── STATUS.md               # Рефакторинг завершён 8/8 (2026-03-15)
└── DECISIONS.md            # ОТСУТСТВУЕТ ⚠️
```

### 1.2. Внешние потребители

| Модуль | Что импортирует | Затронут? |
|--------|----------------|-----------|
| `logger_module` | `ConfigManagerConfig` (из config_module.configs) | Нет (только Type hint) |
| `error_module` | Будет импортировать в будущем | Нет (ещё не рефакторен) |
| `statistics_module` | Будет импортировать в будущем | Нет (ещё не рефакторен) |

---

## 2. Атомарные шаги

### Шаг 0 — Baseline и аудит ⬜

1. `pytest modules/config_module/tests -v` — записать число тестов (ожидается ~49).
2. Подсчитать LOC: `find modules/config_module -name "*.py" -not -path "*/tests/*" -not -path "*__pycache__*" | xargs wc -l`
3. Проверить, что ConfigStore действительно Dict at Boundary:
   ```bash
   grep -rn "config_store" modules/config_module/ --include="*.py" | grep -v __pycache__
   ```
   Должны быть вызовы:
   - `self._shared_resources.config_store.store(name, config.data)` — сохранить dict
   - `self._shared_resources.config_store.get(name)` — загрузить dict
   - **НЕ** должны быть: `Config()` объекты, отправленные напрямую в ConfigStore.

4. Проверить наличие Pydantic использования:
   ```bash
   grep -rn "Pydantic\|ValidationError\|BaseModel" modules/config_module/ --include="*.py" | grep -v __pycache__
   ```
   Ожидается: только `ConfigManagerConfig` в `configs/config_manager_config.py`.

5. Анализ docs/:
   - Что дублирует README.md?
   - Какие части подробные и не в README?

6. Коммит: `docs(config_module): baseline audit before cleanup`.

---

### Шаг 1 — Уточнить Dict at Boundary и документировать ⬜

#### 1a. Проверить ConfigStore API

В `core/config_manager.py` методы `sync_config()` и `load_config_from_storage()` должны работать только с dict:

**Ожидается:**
```python
# sync_config: сохранить dict
config_dict = config.data  # возвращает dict копию
self._shared_resources.config_store.store(name, config_dict)

# load_config_from_storage: загрузить dict
data = self._shared_resources.config_store.get(name)  # returns dict
self.create_config(name, initial_data=data)  # Config создаётся локально из dict
```

**Если нарушения:** отреагировать (маловероятно, STATUS.md показывает завершённый рефакторинг).

#### 1b. Убедиться, что Pydantic только внутри

- `ConfigManagerConfig` (в `configs/config_manager_config.py`) — это SchemaBase (Pydantic v2), используется для **конфигурации самого менеджера** (не для хранилища).
- На границе (ConfigStore) — всегда dict.

#### 1c. Обновить README.md

Добавить явный раздел про Dict at Boundary, если его нет:

```markdown
## Dict at Boundary

ConfigStore хранит конфигурации как `Dict[str, dict]`, не как Config объекты.

- **На границе (между процессами):** dict (pickle-safe, стандартный)
- **Внутри процесса:** Config объекты (runtime, с подписками)
- **Конфигурация менеджера:** ConfigManagerConfig (SchemaBase, Pydantic v2) — описывает сам менеджер, не хранилище

Это обеспечивает безопасность при cross-process коммуникации.
```

**Коммит:** `docs(config_module): clarify Dict at Boundary in README`.

---

### Шаг 2 — Убрать дублирование документации ⬜

#### 2a. Анализ `docs/ARCHITECTURE.md`

Содержит (~180 строк):
- Концепцию трёх слоёв
- Описание компонентов (Config, ConfigManager, ConfigSection, ConfigSchemaAdapter)
- Интеграцию с другими модулями
- Дизайн-решения (5 пунктов)
- Производительность

**Дублирует ли с README.md?**
- README: 5–10 строк про архитектуру + быстрый старт
- docs/ARCHITECTURE.md: полная архитектура + дизайн-решения

**Вердикт:** docs/ARCHITECTURE.md не дублирует. Оставить, но обновить ссылку в README (если нет).

#### 2b. Анализ `docs/USAGE_GUIDE.md`

Содержит (~300+ строк):
- Базовый старт (создание Config)
- С менеджером
- С подписками
- С env-fallback
- Работа с секциями
- С ConfigStore
- Расширенные паттерны (кастомные валидаторы, интеграция с data_schema_module)

**Дублирует ли с README.md?**
- README: быстрый старт (3–4 примера)
- docs/USAGE_GUIDE.md: полный гайд (15+ примеров)

**Вердикт:** docs/USAGE_GUIDE.md не дублирует, дополняет. Оставить.

**Вывод:** docs/ не содержит устаревшую информацию. Возможно, требование из overview.md уже выполнено в рамках рефакторинга 2026-03-15. Убедиться, что файлы актуальны:

1. Проверить даты в файлах (# Last updated).
2. Если даты > 2026-03-15 — актуальны.
3. Если даты раньше — обновить хотя бы дату.

**Коммит:** `docs(config_module): mark docs as reviewed (ARCHITECTURE.md, USAGE_GUIDE.md actuals)`.

---

### Шаг 3 — Создать DECISIONS.md ⬜

Создать `modules/config_module/DECISIONS.md` (новый файл):

```markdown
# config_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md)

## ADR-023: config_module — тонкая обёртка над data_schema_module

**Статус:** принято  
**Дата:** 2026-03-15  
**Контекст:** Требуется отделить runtime-доступ к конфигу (Config, ConfigManager) от его валидации и сериализации (data_schema_module).  
**Решение:**
- `Config` — простой контейнер (dict + подписки + dot-notation), НЕ валидирует.
- `ConfigManager` — коллекция Config объектов с синхронизацией через ConfigStore.
- Валидация (если нужна) — через DataValidator из data_schema_module.
- Сериализация файлов — через DataConverter (не в config_module).

**Последствия:** Config максимально простой (~160 LOC), ConfigManager — коллекционер и синхронизатор (~215 LOC).

---

## ADR-024: Dict at Boundary для ConfigStore

**Статус:** принято  
**Дата:** 2026-03-15  
**Контекст:** ConfigStore должен хранить конфиги между процессами безопасно.  
**Решение:**
- На границе (ConfigStore): `Dict[str, dict]` (pickle-safe)
- Внутри процесса: `Config` объекты (runtime, с подписками)
- `sync_config()` сохраняет `config.data` (dict) в ConfigStore
- `load_config_from_storage()` загружает dict из ConfigStore и создаёт Config локально

**Последствия:** ConfigStore не требует pickle-safe Config, гарантируется cross-process безопасность.

---

## ADR-025: Нет файловой I/O в config_module

**Статус:** принято  
**Дата:** 2026-03-15  
**Контекст:** config_module должен быть ортогональным к источнику конфигов (файлы, env, API).  
**Решение:**
- Config принимает dict, возвращает dict
- Загрузка JSON/YAML/TOML — ответственность DataConverter (из data_schema_module)
- Логирование путей и ошибок — ответственность вызывающего кода

**Последствия:** Config простой, тестируемый, не зависит от I/O.

---

## ADR-026: Пять компонентов модуля

**Статус:** принято  
**Дата:** 2026-03-15  
**Решение:** Модуль состоит из 5 независимых компонентов:

| Компонент | LOC | Ответственность |
|-----------|-----|-----------------|
| `Config` | ~160 | Контейнер одной конфигурации (dot-notation, подписки) |
| `ConfigManager` | ~215 | Коллекция Config с синхронизацией (create/load/sync/shutdown) |
| `ConfigSection` | ~60 | View на часть конфигурации |
| `ConfigSchemaAdapter` | ~40 | Адаптация SchemaBase → dict параметров |
| `ConfigManagerConfig` | ~30 | SchemaBase для параметров менеджера |

**Последствия:** каждый компонент имеет одну ответственность, легко тестировать и модифицировать.

---

## ADR-027: Env-fallback как опциональный feature

**Статус:** принято  
**Дата:** 2026-03-15  
**Контекст:** Config.get() должна поддерживать env-fallback, но это не должно быть обязательным.  
**Решение:**
- Если `env_prefix` передан в Config конструктор — fallback включен
- Если нет — env не используется
- Fallback ищет переменную `{env_prefix}_{KEY}` (точки → подчёркивания)

**Последствия:** Config работает и без env, максимально гибкий API.

```

**Коммит:** `docs(config_module): add DECISIONS.md (ADR-023…027)`.

---

### Шаг 4 — Обновить главный DECISIONS.md и ARCHITECTURE.md §6.6 ⬜

#### 4.1. Главный DECISIONS.md

Добавить строку в раздел "Модульные решения":
```
| `config_module` | [`modules/config_module/DECISIONS.md`](modules/config_module/DECISIONS.md) | Infrastructure | ADR-023…027 (runtime доступ, Dict at Boundary, no I/O, 5 компонентов) |
```

#### 4.2. ARCHITECTURE.md §6.6

Добавить раздел (после §6.5 `logger_module`):

```markdown
### 6.6 `config_module` — конфигурационное хранилище

**Роль:** Runtime-доступ к конфигурациям со scope-based подписками.

**Config** (~160 LOC) — простой контейнер (dict + dot-notation + RLock), БЕЗ валидации или I/O.
**ConfigManager** (~215 LOC) — коллекция Config объектов с синхронизацией через ConfigStore (Dict at Boundary).

```
Config (dict + RLock + подписки)
    ├── dot-notation: get("database.host")
    ├── подписки: subscribe(callback, key="*")
    ├── ConfigSection — view на подсекцию
    └── env-fallback (опциональный, через env_prefix)

ConfigManager
    ├── _configs: Dict[str, Config]
    ├── ConfigStore (SRM): Dict[str, dict] для cross-process синхронизации
    ├── create_config(), get_config(), remove_config()
    └── sync_config() → ConfigStore (dict)
    └── load_config_from_storage() ← ConfigStore (dict)
```

Ключевые решения (ADR-023…027):
- **Config** — не валидирует, не делает I/O. Максимально простой.
- **Dict at Boundary:** ConfigStore хранит dict, не Config объекты.
- **Pydantic только внутри:** ConfigManagerConfig (SchemaBase) — для конфигурации менеджера, не хранилища.
- Пять компонентов, каждый с одной ответственностью.

📖 Подробнее: [`modules/config_module/README.md`](modules/config_module/README.md) · [`modules/config_module/DECISIONS.md`](modules/config_module/DECISIONS.md) · [`modules/config_module/docs/ARCHITECTURE.md`](modules/config_module/docs/ARCHITECTURE.md)
```

**Коммит:** `docs(config_module): fill ARCHITECTURE.md §6.6, update main DECISIONS.md`.

---

### Шаг 5 — Финальная валидация ⬜

1. `pytest modules/config_module/tests -v` — зелёные (ожидается ~49 passed).
2. `pytest modules/logger_module/tests -v` — зелёные (так как logger будет импортировать ConfigManagerConfig).
3. `python Inspector_prototype/scripts/validate.py` — зелёный.
4. `python Inspector_prototype/scripts/run_framework_tests.py` — все зелёные.
5. Собрать метрики «после».
6. Обновить `plans/refactoring/00_overview.md` — строка `config_module` (если был рефакторинг).
7. Коммит: `refactor(config_module): final validation and metrics`.

---

## 3. Что НЕ делать

1. **НЕ** переписывать Config или ConfigManager — модуль уже рефакторен и работает.
2. **НЕ** менять API ConfigManager — публичный контракт стабилен.
3. **НЕ** добавлять файловую I/O — это ответственность DataConverter.
4. **НЕ** добавлять валидацию в Config — это ответственность DataValidator.
5. **НЕ** трогать тесты — только обновить, если нужно для новой документации.
6. **НЕ** удалять docs/ — ARCHITECTURE.md и USAGE_GUIDE.md нужны для полного понимания.
7. **НЕ** менять ConfigManagerConfig (SchemaBase) — конфигурация менеджера, не хранилища.

---

## 4. Кросс-модульные изменения

Этот модуль относительно независим. Изменения:

| Модуль | Файл | Что меняется |
|--------|------|-------------|
| **config_module** | **DECISIONS.md** | СОЗДАТЬ (ADR-023…027) |
| **multiprocess_framework** | **DECISIONS.md** (главный) | Добавить строку про config_module |
| **multiprocess_framework** | **ARCHITECTURE.md** | Добавить §6.6 про config_module |

**Нет** затрагиваемых модулей (config_module уже используется как зависимость в future modules).

---

## 5. Definition of Done (модуль #6)

- [x] Baseline аудит пройден (тесты зелёные, LOC подсчитаны, Dict at Boundary проверена).
- [x] ConfigStore API подтверждён (только dict на границе).
- [x] Pydantic / SchemaBase: `ConfigManagerConfig` в `configs/`; адаптер схем — без хранения в ConfigStore.
- [x] Документация: `docs/ARCHITECTURE.md` и `docs/USAGE_GUIDE.md` помечены ревизией 2026-04-09; README дополнен.
- [x] `DECISIONS.md` создан: локальные **ADR-143…146** (глобальные **ADR-024…027** заняты другими темами — см. файл).
- [x] Главный `DECISIONS.md` обновлён (строка про config_module).
- [x] ARCHITECTURE.md §6.6 заполнен.
- [x] Все тесты config_module зелёные (49 passed).
- [x] `validate.py` зелёный; полный прогон фреймворка зелёный.
- [x] Метрики «после» в `00_overview.md`.

---

## 6. Целевые метрики

| Метрика | До | После (цель) |
|---------|-----|--------------|
| Файлов (без tests) | 11 | 11 (без изменений структуры) |
| LOC | ~1 074 | ~1 074 (без изменений кода, только docs) |
| `config.py` | ~160 | ~160 |
| `config_manager.py` | ~215 | ~215 |
| Тестов | 3 файла (~49 passed) | 3 файла (~49 passed) |
| Публичный API | Без изменений (всё уже стабильно) |
| Документация | 2 doc-файла (ARCHITECTURE.md, USAGE_GUIDE.md) | 3 (+ DECISIONS.md) |

---

## 7. Заметки

- **STATUS.md говорит 8/8** — рефакторинг завершён 2026-03-15. Работа на Шагах 0–5 — в основном документационная (добавить DECISIONS.md, обновить главный DECISIONS.md и ARCHITECTURE.md).
- **Никаких кодовых изменений не планируется** — модуль стабилен.
- **Dict at Boundary проверка** — критична для валидации архитектуры перед использованием в других модулях (logger, error, stats).
