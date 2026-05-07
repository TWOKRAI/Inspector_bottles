# Plan: Phase 7 — Registers v2 (Plugin-Embedded)

## Context

В `multiprocess_prototype_2` существует скрытое дублирование: поля `h_min/h_max/s_min/...` описаны и в [plugins/color_mask/config.py](../plugins/color_mask/config.py) (как `ColorMaskPluginConfig.h_min`), и в [registers/color_mask.py](../registers/color_mask.py) (как `ColorMaskRegisters.min_h`) — два класса с разными именами полей описывают пересекающиеся данные. В [plugins/color_mask/plugin.py:65-71](../plugins/color_mask/plugin.py) есть hardcoded mapping между ними, который и есть симптом проблемы.

---

## Выбранный подход: V3_MY_PURE

> **Решение принято 2026-05-07.** Сравнение 6 вариантов — в [`plugins/color_mask/_pilots/README.md`](../plugins/color_mask/_pilots/README.md).

### Принцип

**Register = самодостаточный модуль плагина** (все параметры + memory + FieldMeta).
**Config = identity + routing** (plugin_class, plugin_name, category, register_bindings).
**Plugin = самодостаточен** — создаёт локальный register если RegistersManager нет.

```
Plugin (работает на defaults)
  ├── Config attached? → identity + register_bindings (YAML discovery)
  └── Register attached? → ВСЕ параметры + memory + FieldMeta
       managed (RegistersManager → GUI) или локальный (defaults)
```

### Контракт

```python
# plugins/color_mask/registers.py — ВСЕ параметры + memory
@register_schema("ColorMaskRegistersV3")
class ColorMaskRegisters(SchemaBase):
    camera_id: Annotated[int, FieldMeta("ID камеры")] = 0
    resolution_width: Annotated[int, FieldMeta("Ширина кадра", unit="px")] = 640
    resolution_height: Annotated[int, FieldMeta("Высота кадра", unit="px")] = 480

    h_min: Annotated[int, FieldMeta("Min Hue", min=0, max=179, unit="°")] = 0
    h_max: Annotated[int, FieldMeta("Max Hue", min=0, max=179, unit="°")] = 179
    s_min: Annotated[int, FieldMeta("Min Saturation", min=0, max=255)] = 50
    s_max: Annotated[int, FieldMeta("Max Saturation", min=0, max=255)] = 255
    v_min: Annotated[int, FieldMeta("Min Value", min=0, max=255)] = 50
    v_max: Annotated[int, FieldMeta("Max Value", min=0, max=255)] = 255

    @property
    def memory(self) -> dict[str, Any] | None:
        return {
            f"mask_{self.camera_id}": (self.resolution_height, self.resolution_width, 1),
            "coll": 1,
        }
```

```python
# plugins/color_mask/config.py — identity + binding
@register_schema("ColorMaskPluginConfigV3")
class ColorMaskPluginConfig(PluginConfig):
    plugin_class: str = "...ColorMaskPlugin"
    plugin_name: str = "color_mask"
    category: str = "processing"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [ColorMaskRegisters]
```

```python
# plugins/color_mask/plugin.py — self-contained
def configure(self, ctx):
    cfg = ctx.config
    self._reg = (ctx.registers.get_register(self.name) if ctx.registers else None) or ColorMaskRegisters()
    # YAML overrides → синхронизируем в register
    for field in self._reg.model_fields:
        if field in cfg:
            setattr(self._reg, field, cfg[field])

def process(self, item):
    # ВСЕГДА через self._reg — никаких if/else
    lower = np.array([self._reg.h_min, self._reg.s_min, self._reg.v_min])
    upper = np.array([self._reg.h_max, self._reg.s_max, self._reg.v_max])
```

### Целевая файловая структура

```
plugins/color_mask/
├── __init__.py
├── plugin.py        # ColorMaskPlugin (self-contained)
├── config.py        # ColorMaskPluginConfig (identity + register_bindings)
└── registers.py     # ColorMaskRegisters (все параметры + memory + FieldMeta)

multiprocess_prototype_2/registers/
├── __init__.py
├── manager.py       # RegistersManager v2 (Task 7.3)
├── connection_map.py# ConnectionMap (Task 7.4)
├── field_info.py    # FieldInfo dataclass
└── shared/          # cross-plugin регистры
    ├── processing_node.py
    ├── frame_message.py
    └── detection.py
```

### FW-рефактор (~13 строк)

**1. `PluginConfig` — `extra="allow"` (~3 строки)**

```python
# generic_process_config.py
class PluginConfig(SchemaBase):
    model_config = ConfigDict(extra="allow", validate_assignment=True, populate_by_name=True)
```

**2. `from_plugins()` — memory из register (~10 строк)**

```python
for pc in plugin_configs:
    mem = pc.memory
    if hasattr(pc, 'register_bindings') and pc.register_bindings:
        extras = getattr(pc, '__pydantic_extra__', {}) or {}
        for reg_cls in pc.register_bindings:
            reg_fields = {k: v for k, v in extras.items() if k in reg_cls.model_fields}
            reg = reg_cls(**reg_fields)
            if hasattr(reg, 'memory') and reg.memory:
                mem = reg.memory
    if mem:
        merged_memory.update(mem)
```

### Анти-паттерны

- **Не пишем** HSV-поля в config.py — они живут только в registers.py.
- **Не дублируем** camera_id/resolution в обоих файлах.
- **Не делаем** register наследником config (это подход V3_INHERIT — отвергнут).
- **Не вводим** `FieldMeta(bind="...")` точечный mapping.

---

## Tasks

### Task 7.0 — FW: PluginConfig extra="allow" + from_plugins() memory proxy

**Goal:** Минимальный FW-рефактор чтобы V3_MY_PURE работал.

**Files:**
- [generic_process_config.py](../../multiprocess_framework/modules/process_module/generic/generic_process_config.py) — `extra="allow"` в PluginConfig + memory proxy в `from_plugins()`

**Steps:**
1. Добавить `model_config = ConfigDict(extra="allow")` в `PluginConfig` (или дополнить существующий)
2. В `from_plugins()` — если у PluginConfig есть `register_bindings`, инстанцировать register из extra-полей и взять `memory` оттуда
3. Тесты: существующие плагины работают без изменений

**Acceptance:**
- [ ] `PluginConfig` принимает extra-поля без ошибок
- [ ] `from_plugins()` корректно вычисляет memory через register
- [ ] Существующие тесты проходят
- [ ] 3+ новых теста на extra + memory proxy

---

### Task 7.1 — Reference implementation: color_mask

**Goal:** Реализовать V3_MY_PURE паттерн на color_mask.

**Files:**
- `plugins/color_mask/registers.py` — **новый** (все параметры + memory + FieldMeta)
- `plugins/color_mask/config.py` — убрать все поля кроме identity, добавить register_bindings
- `plugins/color_mask/plugin.py` — паттерн self._reg always exists, убрать mapping
- `registers/color_mask.py` — **удалить**

**Steps:**
1. Создать `plugins/color_mask/registers.py` (из `_pilots/v3_my_pure/registers.py`)
2. Очистить `config.py` — оставить identity + register_bindings
3. Рефакторить `plugin.py`:
   - `configure()`: `self._reg = ... or ColorMaskRegisters()` + sync из cfg
   - `process()`: всегда через `self._reg`
   - `set_hsv_range()`: всегда через `self._reg`
   - Убрать `self._lower` / `self._upper` numpy fallback
4. Обновить импорты
5. Удалить `registers/color_mask.py`
6. Smoke: `python -m multiprocess_prototype_2.main --topology inspection_basic`

**Acceptance:**
- [ ] `process()` не содержит if/else для reg vs config
- [ ] Plugin работает без RegistersManager (local register)
- [ ] Plugin работает с RegistersManager (managed register)
- [ ] YAML overrides HSV-полей синхронизируются в register
- [ ] Smoke проходит

**Зависимости:** Task 7.0 (extra="allow" нужен чтобы YAML-поля HSV не терялись)

---

### Task 7.2 — Plugin Schemas Protocol

**Goal:** Стандартизировать `register_schema()` в `ProcessModulePlugin`.

**Files:**
- [base.py](../../multiprocess_framework/modules/process_module/plugins/base.py) — `register_schema()` → classmethod, возвращает **классы** (не instances)
- [registry.py](../../multiprocess_framework/modules/process_module/plugins/registry.py) — `PluginEntry` хранит schema
- [generic_process_config.py](../../multiprocess_framework/modules/process_module/generic/generic_process_config.py) — `register_bindings` в `PluginConfig` base

**Acceptance:**
- [ ] `Plugin.register_schema()` → list of SchemaBase classes
- [ ] Default `register_schema()` возвращает `cls.config_schema().register_bindings`
- [ ] 5+ тестов

---

### Task 7.3 — RegistersManager v2

**Goal:** Менеджер собирает регистры из `register_bindings` всех плагинов.

**Files:** `multiprocess_prototype_2/registers/manager.py` (новый), `field_info.py` (новый)

**API:**
- `RegistersManager.from_registry(registry) → RegistersManager`
- `manager.get_register(plugin_name) → SchemaBase | None`
- `manager.get_fields(plugin_name) → list[FieldInfo]`
- `manager.set_value(plugin, field, value) → bool`
- `manager.validate(plugin, field, value) → tuple[bool, str|None]`

**Acceptance:**
- [ ] Строится автоматически из PluginRegistry
- [ ] Pydantic validation при set_value
- [ ] FieldInfo содержит FieldMeta
- [ ] 12+ тестов

---

### Task 7.4 — ConnectionMap

**Goal:** Маппинг `(plugin_name, field_name) → (process_name, command_name, arg_key)` из YAML.

**Files:** `multiprocess_prototype_2/registers/connection_map.py` (новый)

**Acceptance:**
- [ ] `resolve(plugin, field) → (process, command, arg_key)`
- [ ] 6+ тестов

---

### Task 7.5 — Rollout на остальные 8 runtime-плагинов

**Goal:** Применить V3_MY_PURE ко всем плагинам с runtime-параметрами.

**Плагины:**
- blob_detector, render_overlay, renderer_compositor
- robot_control, database, frame_saver
- chain_executor, worker_pool

Для каждого: создать registers.py (параметры + memory если есть), очистить config.py, обновить plugin.py.

---

### Task 7.6 — Shared Registers Migration

**Goal:** Перенести cross-plugin регистры в `registers/shared/`.

**Files (move):**
- `registers/pipeline/processing_node.py` → `registers/shared/processing_node.py`
- Остальные cross-plugin — по мере появления

---

### Task 7.7 — Cleanup

**Goal:** Удалить `_pilots/`, обновить документацию.

- [ ] Удалить `plugins/color_mask/_pilots/`
- [ ] Обновить `PHASE7_PLAN.md` — пометить завершённые таски
- [ ] Обновить `MODULES_STATUS.md` если нужно

---

## Порядок выполнения

1. **Task 7.0** — FW-рефактор (extra="allow" + memory proxy)
2. **Task 7.1** — Reference: color_mask
3. **Task 7.2** — Protocol в base.py
4. **Task 7.3** + **Task 7.4** — параллельно (RegistersManager v2 + ConnectionMap)
5. **Task 7.5** — Rollout на 8 плагинов
6. **Task 7.6** — Shared registers
7. **Task 7.7** — Cleanup

---

## Критические файлы

| Файл | Что делать |
|------|-----------|
| [generic_process_config.py](../../multiprocess_framework/modules/process_module/generic/generic_process_config.py) | Task 7.0: extra="allow" + memory proxy |
| [base.py](../../multiprocess_framework/modules/process_module/plugins/base.py) | Task 7.2: register_schema() classmethod |
| [registry.py](../../multiprocess_framework/modules/process_module/plugins/registry.py) | Task 7.2: PluginEntry + schema |
| [plugins/color_mask/plugin.py](../plugins/color_mask/plugin.py) | Task 7.1: self._reg always exists |
| [plugins/color_mask/config.py](../plugins/color_mask/config.py) | Task 7.1: identity only |
| plugins/color_mask/registers.py | Task 7.1: **новый** — все параметры + memory |
| [registers/color_mask.py](../registers/color_mask.py) | Task 7.1: **удалить** |
| [_pilots/README.md](../plugins/color_mask/_pilots/README.md) | Сравнение 6 подходов (reference) |

## Verification

```bash
# Task 7.0
python scripts/run_framework_tests.py

# Task 7.1
python -m multiprocess_prototype_2.main --topology inspection_basic
# Цвет фильтруется, GUI слайдеры работают

# Task 7.3
python -m pytest multiprocess_prototype_2/registers/tests/test_manager.py -v

# Task 7.4
python -m pytest multiprocess_prototype_2/registers/tests/test_connection_map.py -v
```

## Что без изменений

- `FieldMeta` готова — не трогаем
- `PluginRegistry.discover()` работает — не трогаем
- `SchemaRegistry` (data_schema_module) — не трогаем
- Startup-only плагины (10 шт.) — **0 изменений** пока не появятся runtime-параметры
