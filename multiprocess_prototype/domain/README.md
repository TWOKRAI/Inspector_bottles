# multiprocess_prototype.domain — изолированный domain-слой

## Назначение (Purpose)

Типизированный domain-слой для cross-tab архитектуры Inspector_bottles.
Создан в рамках Phase B рефакторинга `refactor/cross-tab-architecture`.

Слой **полностью изолирован** от runtime-кода прототипа: он не импортируется
существующими presenter'ами, AppContext или TopologyHolder. Подключение к
runtime выполняется в Phase D через `AppServices` DI-контейнер.

## Публичный API

```python
from multiprocess_prototype.domain import (
    # 7 frozen-entities
    PluginInstance,    # один плагин внутри Process
    Wire,              # соединение между узлами
    DisplayInstance,   # привязка узла к дисплею
    Process,           # процесс с цепочкой плагинов
    RecipeMeta,        # метаданные рецепта
    Recipe,            # рецепт: meta + Topology + сервисы + дисплеи
    Topology,          # топология: processes + wires + displays
    Project,           # корневой агрегат (editor state)
    # Исключения
    DomainError,
    EntityValidationError,
)
```

Все entities — `frozen=True, extra="forbid"` Pydantic v2 модели на базе `SchemaBase`.

## Структура пакета

```
domain/
├── __init__.py              # публичный API
├── README.md                # этот файл
├── errors.py                # DomainError, EntityValidationError
├── entities/
│   ├── __init__.py
│   ├── plugin.py            # PluginInstance
│   ├── wire.py              # Wire
│   ├── display.py           # DisplayInstance
│   ├── process.py           # Process
│   ├── recipe.py            # RecipeMeta + Recipe
│   ├── topology.py          # Topology
│   └── project.py           # Project (корневой агрегат)
└── tests/
    ├── __init__.py
    ├── conftest.py          # базовые фикстуры (fixtures_dir)
    └── test_entities_roundtrip.py
```

## Границы импортов (Boundaries)

**Разрешено:**
- `multiprocess_framework.modules.data_schema_module` (SchemaBase, FieldMeta)
- Стандартная библиотека Python
- Pydantic v2, typing_extensions

**Запрещено:**
- `PySide6`, `PyQt6`, `PyQt5` — domain UI-agnostic
- `multiprocess_prototype.frontend` — нет зависимости на GUI
- `multiprocess_prototype.backend` — нет зависимости на runtime
- `multiprocess_framework.modules.frontend_module` — нет зависимости на GUI-фреймворк

## Стабильность (Stability)

**Experimental** — пакет изолирован, к runtime не подключён.
Phase D подключит через `AppServices` DI-контейнер.
До Phase D любые изменения внутри `domain/` безопасны: runtime prototype не затронут.

## Ключевые решения (Decisions Log)

### SchemaBase вместо голого BaseModel
Все 7 entities наследуются от `SchemaBase` из `data_schema_module`, а не от
`pydantic.BaseModel` напрямую. Это даёт:
- `FieldMeta` — human-readable описания полей для Phase E (Inspector)
- `get_fields_for_access_level()` — permission-aware фильтрация полей (Phase E)
- `DataConverter` — готовая сериализация dict/JSON/YAML на границе
- `SchemaRegistry` — опциональный discovery (Phase E)

Layer-rules не нарушены: `multiprocess_framework → ... → multiprocess_prototype`,
импорт SchemaBase в `multiprocess_prototype/domain/` законен.

### frozen=True
`model_config = ConfigDict(frozen=True, populate_by_name=True, extra="forbid")`.
Все 7 entities immutable: попытка `entity.field = x` вызывает `TypeError`.
`validate_assignment` из SchemaBase теряет смысл при frozen — переопределяется.

### tuple вместо list
`Process.plugins`, `Topology.processes/wires/displays`, `Recipe.active_services/display_bindings` —
`tuple[..., ...]`. Validators `field_validator(..., mode="before")` автоматически
конвертируют `list` → `tuple` при `model_validate(dict)` (YAML десериализует как list).

### display_bindings: формат v3 (node_id/display_id)
YAML-рецепты используют формат v3 с ключами `node_id`/`display_id`:

```yaml
display_bindings:
  - node_id: merge_proc.render_overlay.rendered_frame
    display_id: main_output
```

Domain entity `DisplayInstance` использует `node_id`/`display_id` (формат v3).
Устаревший формат `source`/`display` больше **НЕ принимается** —
`DisplayInstance(extra='forbid')` бросит `ValidationError`.

### Topology.from_dict: extra-поля → metadata
`Topology.from_dict()` перемещает неизвестные ключи (например, `name`, `description`
из blueprint-заголовка) в `Topology.metadata`, не нарушая `extra="forbid"`.

### Recipe.from_dict: нормализация v3 формата
Формат рецептов v3 хранит `name`/`version`/`description` на верхнем уровне YAML.
`Recipe.from_dict()` собирает их в `RecipeMeta` и убирает с верхнего уровня
перед валидацией, чтобы не нарушать `extra="forbid"`.

### Process и PluginInstance: runtime-поля
`Process` включает поля `process_class` и `priority`; `PluginInstance` — `plugin_class`
и `category`. Эти поля присутствуют в реальных YAML-конфигах (pilot_widgets.yaml,
demo_webcam_split_merge.yaml) и нужны для round-trip совместимости. В Phase D
при подключении к runtime они будут явно разделены на «editor-only» и «runtime-config».

### SchemaRegistry registration
Domain entities опционально регистрируются в глобальном default `SchemaRegistry`
при импорте `multiprocess_prototype.domain`. Это даёт Inspector (Phase E) возможность
`SchemaRegistry.lookup("Process")`. Если глобальный registry конфликтует с изолированными
тестовыми registry — вынести регистрацию в фабрику `AppServices` (Phase D).

**TODO(B.1 → Phase D):** Решить, регистрировать в global registry или только через
AppServices factory. Текущее решение: регистрация при импорте, без блокировки acceptance.

## Производительность

Текущий дизайн оптимизирован для O(50–100) entities (реальные рецепты: единицы
процессов, целевое — десятки). При `model_copy` на каждом изменении (`Project.apply()`
в Task B.4) tuple-based immutability даёт приемлемую производительность.

При O(1000+) entities потребуются immutable persistent collections (`pyrsistent`) или
mutable inside-aggregate операции. Это ADR-стаб: зафиксировано, не реализовано.

## Ссылки

- Спецификация Phase B: `plans/2026-05-27_cross-tab-architecture/phase-b-domain.md`
- Аудит Phase A: `docs/refactors/2026-05_cross_tab_audit.md`
- Brief: `docs/refactors/2026-05_cross_tab_architecture.md`
- SchemaBase: `multiprocess_framework/modules/data_schema_module/core/schema_base.py`
