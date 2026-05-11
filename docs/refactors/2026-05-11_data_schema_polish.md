# Полировка `data_schema_module` (Tier 2.3 re-scoped)

**Дата:** 2026-05-11
**Контекст:** Пользователь предложил «декомпозировать `data_schema_module` по красоте, с фасадом и паттернами». Tier 2.3 в [IMPROVEMENT_PLAN.md](../../multiprocess_framework/IMPROVEMENT_PLAN.md#L127-L138) обещал именно это («оставить пакет, формализовать sub-packages с явными `__init__.py` и `interfaces.py`»).

**Главный вывод после разведки:** **модуль уже декомпозирован.** [STATUS.md модуля](../../multiprocess_framework/modules/data_schema_module/STATUS.md) фиксирует чек-лист 11/11 закрытым на 2026-04-09, оценки 8-9/10 по архитектуре/читаемости/модульности. Структура (`core/registry/serialization/container/storage/extensions`) — результат предыдущего рефакторинга v2.0. IMPROVEMENT_PLAN.md был написан **до** этого рефакторинга и устарел в части Tier 2.3.

То есть «декомпозировать» сейчас означает **полировать остаточные шероховатости**, а не переархитектурить.

## Что есть на сегодня (факты)

### Размер по слоям (без тестов и docs/, в LOC)

| Слой | Файлы | LOC | Назначение |
|---|---|---|---|
| `core/` | 13 | 1863 | SchemaBase, FieldMeta, FieldRouting, validators, exceptions, helpers, references — фундамент без внешних зависимостей |
| `tools/` | 5 | 1216 | SchemaVisualizer, doc generator (визуализация и документирование схем) |
| `registry/` | 4 | 1114 | SchemaRegistry (без Singleton), discovery, process_registry |
| `storage/` | 3 | 745 | StorageManager, ProcessDataContainer (зависит от process_module) |
| `factory/` | 3 | 660 | ModelFactory (динамические классы) |
| `interfaces.py` | 1 | **594** | Монолит публичных контрактов (~30 Protocol/ABC) |
| `serialization/` | 4 | 552 | DataConverter, io (dict/JSON/YAML), FileStorage |
| `api/` | 3 | 523 | simple_api (create_config / get_config), manager_adapter |
| `models/` | 4 | 495 | BaseComponentModel, ComponentDNA |
| `versioning/` | 2 | 477 | VersionManager (зависит от config_module) |
| `container/` | 3 | 447 | RegistersContainer, config_converters (`process()`) |
| `extensions/` | 8 | 181 | Тонкие реэкспорт-обёртки (ADR-DS-004 — изолятор зависимостей) |
| `__init__.py` | 1 | 211 | Корневой фасад: 60+ экспортов |
| **Итого «продакт»** | **54** | **~9078** | |
| tests/ | 28 | ~4000 | Полное покрытие |
| docs/ + examples | 6 + 6 | ~956 | Markdown + runnable примеры |

**С тестами и docs ~14K LOC** (IMPROVEMENT_PLAN.md писал 16K — близко). Без — **~9K**. STATUS.md модуля упоминает 3.5K, но эта цифра старая (~2026-03, до расширения tools/factory/models).

### Архитектурные решения, которые трогать нельзя

- **ADR-DS-004:** `extensions/` — это **изолятор зависимостей** от других модулей фреймворка (process_module, config_module). Удалять или схлопывать нельзя — `core/` потеряет свою zero-dependency гарантию.
- **ADR-DS-001/002/003:** Уже сделан cleanup shim'ов (`_compat.py`, `fields/`, `utils/`, `tests_backup/`). Не пересматриваем.
- **DDD-слои фактически есть:** `core/` = domain (zero deps), `registry/container/serialization/` = application, `storage/versioning/` = infrastructure. Формализация в DDD-терминологию без рефакторинга кода — церемония, не польза.

### Реальные шероховатости

1. **`interfaces.py` (594 LOC)** — монолит, который объявляет интерфейсы для всех слоёв сразу. Удобно для импорта (`from data_schema_module import ISchemaRegistry`), но плохо для понимания границ: `IVersionManager` сидит рядом с `ISchema` и `IRegisterStorage`.
2. **16 файлов используют прямые импорты в обход фасада** — `from data_schema_module.core.field_meta import FieldMeta` вместо `from data_schema_module import FieldMeta`. Это создаёт лишние file-to-file edges (sentrux это считает).
3. **3 файла в `docs/` помечены в STATUS как «❌ УДАЛИТЬ»**: `EVALUATION.md`, `DISCOVERY_AND_PACKAGES.md`, `EVALUATION_FRAMEWORK_AND_REGISTERS.md` (старая версия 1.0). До сих пор лежат.
4. **`USER_GUIDE.md`** помечен «частично устаревший — обновить ссылки».
5. **STATUS.md модуля устарел в LOC** (говорит 3500, реально 9000) и в перечне TODO (некоторые закрыты).
6. **README/STATUS только на верхнем уровне** — у sub-packages своих нет. Это снижает navigability и DSM-кластеризацию.
7. **Фасад `__init__.py`** хороший, но без `__version__`, импорты не сгруппированы по слоям с заголовками-комментариями.

## План полировки

### Этап 1: Cleanup устаревшей документации (0.5 дня, риск низкий)

- Удалить 3 файла по указанию STATUS.md: `EVALUATION.md`, `DISCOVERY_AND_PACKAGES.md`, `EVALUATION_FRAMEWORK_AND_REGISTERS.md`.
- Обновить `USER_GUIDE.md` — синхронизировать ссылки с текущим API.
- Сверить `README.md` модуля с реальностью (60+ экспортов, не 50; ссылки на actions_module и т.п.).

**Acceptance:** `grep -r "EVALUATION.md\|DISCOVERY_AND_PACKAGES.md\|EVALUATION_FRAMEWORK" docs/` — пусто.

### Этап 2: Декомпозиция `interfaces.py` (1 день, риск средний)

Разнести 594-строчный монолит по слоям, оставив корневой `interfaces.py` как re-export для backward compat:

- `core/interfaces.py` — `ISchema`, `ISchemaAdapter`, `HasBuild`, `IDataValidator`
- `registry/interfaces.py` — `ISchemaRegistry`, `ISchemaManager`
- `serialization/interfaces.py` — `IDataConverter` (с `FormatType`)
- `storage/interfaces.py` — `ISchemaStorage`, `IAsyncSchemaStorage`, `IRegisterStorage`, `IAsyncRegisterStorage`, `IStorageManager`
- `versioning/interfaces.py` — `IVersionManager`
- `tools/interfaces.py` — `IVisualizationFormatter`, `IDocumentationFormatter`, `ISchemaVisualizer`, `ISchemaDocumentationGenerator`

**Решение:** ADR-DS-005 в `data_schema_module/DECISIONS.md`.

**Acceptance:**
- Корневой `interfaces.py` остаётся (~50 строк, только re-export) — все потребители работают без изменений.
- Каждый sub-package имеет свой `interfaces.py` с описанием домена.
- Тесты проходят без модификаций.

### Этап 3: Audit фасада `__init__.py` (0.5 дня, риск низкий)

- Группировать импорты по слоям с заголовками-комментариями (см. шаблон корневого `multiprocess_framework/__init__.py` со слоями `LAYER 1: FOUNDATION` …).
- Аудит `__all__`: проверить, что каждый экспорт реально импортируется (`grep` по всем потребителям).
- Добавить `__version__ = "2.0.0"`.
- Дополнить docstring краткой таблицей «что → где импортируется».

### Этап 4: Sed-замена прямых импортов на фасадные (0.5 дня, риск низкий)

16 файлов сейчас:
```python
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase, RegisterBase
```

Заменить на:
```python
from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, RegisterBase
```

**Решение:** ADR-DS-006 в `data_schema_module/DECISIONS.md` — «прямые импорты в обход `__init__.py` запрещены для public API».

**Эффект:** −10..−15 file-to-file edges в DSM, +0.002..+0.005 modularity, плюс соблюдение R-1 «единый канал импортов».

### Этап 5: README + STATUS в каждом sub-package (1-1.5 дня, риск отсутствует)

Сейчас README/STATUS только в корне модуля. Добавить мини-README в:
- `core/` — Schema fundamentals (zero deps, что внутри, как расширять через `@register_field_type`)
- `registry/` — SchemaRegistry pattern, discovery, ProcessRegistersRegistry
- `serialization/` — DataConverter strategies, FileStorage
- `container/` — RegistersContainer, `process()` helper
- `storage/` — StorageManager + ProcessData (зависит от process_module)
- `extensions/` — изолятор зависимостей, ADR-DS-004 (что и зачем)
- `tools/` — Visualizer, doc generator (опциональная зависимость)
- `factory/` — ModelFactory (динамические классы)
- `models/` — ComponentDNA, BaseComponentModel
- `versioning/` — VersionManager
- `api/` — simple_api, manager_adapter

Шаблон — короткий (40-80 строк, по образцу [actions_module/README.md](../../multiprocess_framework/modules/actions_module/README.md)).

### Этап 6: Validate + tests + sentrux дельта (0.5 дня)

- `python scripts/validate.py`
- `python scripts/run_framework_tests.py`
- `pytest Plugins/` + `pytest multiprocess_prototype/`
- `mcp__sentrux__session_start` (baseline) → правки → `session_end` (дельта)

**Итого: 3.5-4.5 дня работы, низкий-средний риск.**

## Прогноз метрик

| Метрика | Сейчас | Прогноз |
|---|---|---|
| quality_signal | 6230 | 6240..6260 (+10..+30) |
| modularity (raw) | 0.2705 | 0.273..0.278 (+0.003..+0.008) |
| equality (raw) | 0.3795 | 0.39..0.40 (+0.01..+0.02 — sub-package README'ы добавляют клочки для DSM-кластеров) |
| cross_module_edges | 1431 | 1416..1421 (−10..−15 от sed-замены) |
| check_rules | 9/9 pass | 9/9 pass |

## Anti-targets (что НЕ делаем)

| Чего не делаем | Почему |
|---|---|
| Удалять `extensions/` | ADR-DS-004: это слой изоляции зависимостей. `core/` потеряет zero-dependency гарантию. |
| Carve-out `tools/` → отдельный top-level модуль | Без проверки DSM — риск как с `_examples` (intra → cross edges). Возможно стоит проверить и сделать, но **в отдельном плане**, не в этой полировке. |
| Переименовать слои в DDD-термины (domain/application/infrastructure) | Слои уже de-facto, переименование = церемония без выигрыша. |
| Формализовать паттерны (Strategy/Builder/Repository/Adapter) явными ABC | Они уже применены: SchemaRegistry — Repository, DataConverter+FormatType — Strategy, `@register_schema` — Builder, ISchemaAdapter — Adapter. Дополнительная "формализация" = boilerplate. |
| Переписывать Pydantic-логику или валидацию | Стабильно работает, ничем не плохо. |
| Менять публичный API символов | 43 файла-потребителя, 200+ импортов — высокая стоимость, нулевая выгода. |
| Мега-rewrite ради «чистоты» | YAGNI. Полировка достаточна. |

## Расписание (если поехали по этому плану)

```
Сессия 1: Этап 1 (cleanup docs) + Этап 3 (facade audit)    ~1 день
Сессия 2: Этап 2 (interfaces decompose) + ADR-DS-005      ~1 день
Сессия 3: Этап 4 (sed-replace direct imports) + ADR-DS-006 ~0.5 дня
Сессия 4: Этап 5 (sub-package README, по 2-3 за раз)      ~1.5 дня
Сессия 5: Этап 6 (tests + sentrux delta) + commits        ~0.5 дня
```

**Промежуточный merge** в main после каждой сессии — не накапливать одной megafeature.

## Развилка: что делать с `tools/` (опц., в отдельный план)

`tools/` — 5 файлов, 1216 LOC, плюс docs/ (956 LOC) — это **изолированная подсистема визуализации и документации**. Если её внешние потребители — только sentrux/scripts/IDE-плагины (не runtime), а связи с `core/` слабые, она может быть кандидатом на carve-out в `data_schema_tools_module/`.

Перед `git mv` обязательная проверка (по критериям carve-out из [2026-05-11_modularity_facades_next.md](2026-05-11_modularity_facades_next.md)):
- Обратные импорты `tools/` → `core/`: должно быть ≤2.
- Внешние потребители: должно быть ≥5.
- Размер: ≥8 файлов / ≥500 LOC — ✅ (5 файлов / 1216 LOC, на границе).

**Если делать — отдельный план, отдельная сессия.** В рамках полировки этого не трогаем.
