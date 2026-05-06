# Plan: Phase 7 — Registers v2 (Plugin-Driven)

## Context

Phase 6 DONE (163 теста, 10 задач). Phase 7 = система регистров, автоматически строящаяся из plugin-конфигов.

**Текущее состояние:**
- `register_schema()` метод уже есть в `ProcessModulePlugin` (возвращает None)
- Только `color_mask` реализует его (возвращает `ColorMaskRegisters`)
- `FieldMeta` полностью готова (validation, i18n, access_level, min/max, routing)
- `PluginRegistry.discover()` работает
- Все 19 плагинов имеют `config.py` с `PluginConfig` наследниками и `Annotated[type, FieldMeta(...)]`
- `SchemaRegistry` (data_schema_module) хранит все зарегистрированные schema

**Ключевой инсайт:** config.py каждого плагина УЖЕ содержит полную Pydantic-схему с FieldMeta. НЕ нужно создавать отдельные register-классы для каждого плагина — можно извлекать схему из PluginConfig напрямую.

---

## Task 7.1 — Plugin Config Schema Protocol

**Goal:** Каждый плагин экспортирует Pydantic-схему конфига через стандартный метод.
**Level:** Middle (Sonnet)
**Files:**
- `multiprocess_framework/modules/process_module/plugins/base.py` — добавить `config_schema() → type[PluginConfig] | None`
- Все 19 плагинов — добавить `config_schema()` (возвращает свой PluginConfig class)

**Логика:**
```python
# В base.py:
@classmethod
def config_schema(cls) -> type | None:
    """Pydantic-модель конфига плагина для RegistersManager/GUI."""
    return None

# В каждом plugin.py:
@classmethod
def config_schema(cls) -> type:
    from .config import BlobDetectorConfig
    return BlobDetectorConfig
```

**Steps:**
1. Добавить `config_schema()` classmethod в `ProcessModulePlugin`
2. Для каждого из 19 плагинов — override с lazy import своего Config class
3. Обновить `PluginEntry` в registry.py: хранить `config_schema` при регистрации
4. Тесты: 5+ (проверить что все плагины возвращают schema, schema имеет fields)

**Acceptance:**
- [ ] `plugin.config_schema()` → Pydantic model class
- [ ] Модель содержит Annotated fields с FieldMeta
- [ ] Все 19 плагинов имеют config_schema

---

## Task 7.2 — RegistersManager v2

**Goal:** Менеджер, собирающий config-схемы из PluginRegistry автоматически.
**Level:** Middle+ (Sonnet)
**Files:**
- `multiprocess_prototype_2/registers/manager.py` (новый)
- `multiprocess_prototype_2/registers/field_info.py` (новый)

**Архитектура:**
```python
class FieldInfo:
    """Описание одного поля регистра для GUI."""
    plugin_name: str
    field_name: str
    field_type: type
    default: Any
    meta: FieldMeta | None     # description, min, max, unit, etc.
    current_value: Any

class RegistersManager:
    """Автоматически строит регистры из plugin config schemas."""
    
    @classmethod
    def from_registry(cls, registry: PluginRegistry) -> RegistersManager:
        """Сканирует все плагины, извлекает config schemas."""
    
    @classmethod
    def from_topology(cls, topology: dict) -> RegistersManager:
        """Строит из topology YAML (знает какие плагины с каким конфигом)."""
    
    def get_plugins(self) -> list[str]
    def get_fields(self, plugin_name: str) -> list[FieldInfo]
    def get_value(self, plugin_name: str, field_name: str) -> Any
    def set_value(self, plugin_name: str, field_name: str, value: Any) -> bool
    def get_categories(self) -> dict[str, list[str]]  # category → [plugin_names]
    def validate(self, plugin_name: str, field_name: str, value: Any) -> tuple[bool, str|None]
    def to_dict(self, plugin_name: str) -> dict  # snapshot текущих значений
```

**Извлечение FieldMeta из Pydantic model:**
```python
for field_name, field_info in config_class.model_fields.items():
    # field_info.metadata содержит FieldMeta если Annotated
    meta = None
    for m in field_info.metadata:
        if isinstance(m, FieldMeta):
            meta = m
            break
    # field_info.default — значение по умолчанию
    # field_info.annotation — тип
```

**Steps:**
1. Создать `FieldInfo` dataclass
2. Создать `RegistersManager` с from_registry() и from_topology()
3. Извлечение FieldMeta из `model_fields.metadata`
4. get/set/validate через Pydantic validation
5. Тесты: 12+ (from_registry, from_topology, get/set, validation, categories)

**Acceptance:**
- [ ] RegistersManager строится из PluginRegistry автоматически
- [ ] get/set по plugin_name.field_name
- [ ] Pydantic validation при set_value
- [ ] FieldInfo содержит FieldMeta (min/max/description/unit)
- [ ] 12+ тестов

---

## Task 7.3 — Connection Map (Register → Process)

**Goal:** Маппинг register field → target process + command для отправки изменений.
**Level:** Middle (Sonnet)
**Files:**
- `multiprocess_prototype_2/registers/connection_map.py` (новый)

**Логика:**
```python
class ConnectionMap:
    """Маппинг: (plugin_name, field_name) → (process_name, command_name, arg_key)."""
    
    @classmethod
    def from_topology(cls, topology: dict) -> ConnectionMap:
        """Из topology YAML: plugin X запущен в process Y."""
        # Для каждого process → для каждого plugin → запомнить process_name
    
    def resolve(self, plugin_name: str, field_name: str) -> tuple[str, str, str] | None:
        """Вернуть (process_name, command_name, arg_key).
        
        command_name генерируется: 'set_{field_name}' или из commands dict плагина.
        """
    
    def get_process(self, plugin_name: str) -> str | None:
        """В каком процессе запущен плагин."""
```

**Steps:**
1. Парсинг topology: `process.plugins[].plugin_name → process_name`
2. Для каждого field → генерация command: проверить plugin.commands dict, иначе `set_{field}`
3. resolve() → (process_name, command, arg_key)
4. Тесты: 6+ (from_topology, resolve, missing plugin, multiple processes)

**Acceptance:**
- [ ] ConnectionMap строится из topology YAML
- [ ] resolve() → (process_name, command_name, arg_key)
- [ ] 6+ тестов

---

## Порядок выполнения

1. **Task 7.1** — config_schema protocol (зависимость для 7.2)
2. **Task 7.2 + 7.3** — параллельно (RegistersManager + ConnectionMap)
3. Верификация: все тесты Phase 7

## Справочники

- [base.py](multiprocess_framework/modules/process_module/plugins/base.py) — ProcessModulePlugin.register_schema()
- [registry.py](multiprocess_framework/modules/process_module/plugins/registry.py) — PluginRegistry, PluginEntry, discover()
- [generic_process_config.py](multiprocess_framework/modules/process_module/generic/generic_process_config.py) — PluginConfig
- [field_meta.py](multiprocess_framework/modules/data_schema_module/core/field_meta.py) — FieldMeta с validation/i18n
- [color_mask/plugin.py](multiprocess_prototype_2/plugins/color_mask/plugin.py) — пример register_schema()
- [registers/color_mask.py](multiprocess_prototype_2/registers/color_mask.py) — пример SchemaBase register
- [registers/__init__.py](multiprocess_prototype_2/registers/__init__.py) — convention mapping docs

## Верификация

```bash
# Task 7.1
python -m pytest multiprocess_prototype_2/tests/test_config_schema.py -v

# Task 7.2
python -m pytest multiprocess_prototype_2/registers/tests/test_manager.py -v

# Task 7.3
python -m pytest multiprocess_prototype_2/registers/tests/test_connection_map.py -v
```
