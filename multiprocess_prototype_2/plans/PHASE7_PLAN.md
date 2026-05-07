# Plan: Phase 7 — Registers v2 + Plugin Simplification

## Статус: Phase 7A + 7B + 7C ЗАВЕРШЕНЫ (2026-05-07)

**Результат:**
- 163 теста плагинов — ✅ все прошли
- 924 теста суммарно (plugins + FW + registers) — ✅ все прошли
- ~200 строк boilerplate убрано из плагинов (7A-7B)
- MagicMock убран из production-кода (chain_executor, worker_pool)
- Commands dict вместо замыканий в capture + camera_service (7C)
- Дубли plugin_name/category убраны из 19 config.py (7C)
- memory property убран из 7 processing плагинов (7C)

---

## Что было сделано

### Phase 7A — Framework (2 файла)

**7A.1 — base.py: start() non-abstract + _init_register() + SubPluginContext**
- `start()` — убран `@abstractmethod`, default no-op
- `_init_register(ctx, register_cls=None)` — helper для инициализации register:
  managed (GUI) → локальный fallback → YAML overrides. Одна строка вместо пяти.
- `SubPluginContext` — dataclass, замена `unittest.mock.MagicMock` в production.
  Логирование через callable `log_info`/`log_error` (передаются из родительского ctx).

**7A.2 — registry.py: register_class на плагине**
- `PluginEntry` теперь сначала ищет `register_class` атрибут на классе плагина,
  потом fallback на `register_schema()` → `config_class().register_bindings`.
- Плагинам с registers больше не нужен config.py для привязки.

### Phase 7B — Prototype (19 файлов плагинов + 6 файлов тестов)

**7B.1 — Убраны пустые start() из 10 плагинов:**
grayscale, flip, negative, resize, frame_counter, region_split,
stitcher, color_mask, blob_detector, render_overlay, renderer_compositor,
robot_control, frame_saver

**7B.2 — _init_register(ctx) в 9 stateful плагинах:**
color_mask, blob_detector, render_overlay, renderer_compositor,
robot_control, database, frame_saver, chain_executor, worker_pool

Каждый плагин получил `register_class = XxxRegisters` как атрибут класса.
Boilerplate (5 строк) → одна строка `self._reg = self._init_register(ctx)`.

**7B.3 — SubPluginContext в chain_executor + worker_pool:**
Убран `from unittest.mock import MagicMock` из production-кода.
MagicMock → SubPluginContext с проброшенным log_info/log_error из родителя.

**7B.4 — config.py оставлены по решению пользователя** (на будущее).

### Phase 7C — Cleanup (2 файла plugin.py + 19 config.py + 7 registers/config)

**7C.1 — Commands dict вместо замыканий (capture + camera_service)**
- `capture/plugin.py`: 4 замыкания в `configure()` → 4 метода + `commands` dict
- `camera_service/plugin.py`: 14 замыканий в `_register_commands()` → 14 методов + `commands` dict
  - 8 основных команд: методы `cmd_*`
  - 6 hik_* passthrough: `_hik_passthrough()` helper + 6 тонких методов `cmd_hik_*`
  - `_register_commands()` удалён полностью

**7C.2 — Убраны дубли plugin_name/category из 19 config.py**
- Каждый config.py переопределял `plugin_name` и `category`, дублируя `@register_plugin()` декоратор.
- Базовый `PluginConfig` уже имеет эти поля с `""` defaults. YAML topology передаёт реальные значения.

**7C.3 — Убран memory property из 7 processing плагинов**
- Processing-плагины не нуждаются в SHM pre-allocation (SHM прозрачен через middleware).
- Убрано из registers.py: `color_mask`
- Убрано из config.py: `grayscale`, `stitcher`, `region_split`, `flip`, `negative`, `resize`
- `resize/config.py`: также убран helper `_output_size()`
- `color_mask/registers.py`: убраны поля `camera_id`, `resolution_width`, `resolution_height` (были только для memory)
- Source-плагины (`capture`, `camera_service`) memory property сохранён.

---

## Подход: V3_MY_PURE (принят 2026-05-07)

**Register = единый источник runtime-параметров** (FieldMeta, defaults).
**Config = identity + routing** (plugin_class, plugin_name, category).
**Plugin = самодостаточен** — `_init_register(ctx)` создаёт локальный register если RegistersManager нет.

### Целевой минимум для нового плагина

**Stateless (1 файл):**
```python
@register_plugin("my_filter", category="processing", description="...")
class MyFilterPlugin(ProcessModulePlugin):
    inputs  = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]
    outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    def configure(self, ctx):
        self._threshold = ctx.config.get("threshold", 128)

    @for_each
    def process(self, item):
        frame = item.get("frame")
        if frame is None:
            return None
        return {**item, "frame": apply_filter(frame, self._threshold)}
```

**Stateful с registers (2 файла):**
```python
# registers.py
class MyRegisters(SchemaBase):
    sensitivity: Annotated[float, FieldMeta("Чувствительность", min=0.0, max=1.0)] = 0.5

# plugin.py
@register_plugin("my_detector", category="processing", description="...")
class MyDetectorPlugin(ProcessModulePlugin):
    register_class = MyRegisters
    commands = {"set_sensitivity": "set_sensitivity"}

    def configure(self, ctx):
        self._ctx = ctx
        self._reg = self._init_register(ctx)  # ← одна строка
```

---

## Критические файлы (изменённые)

| Файл | Что изменено |
|------|-------------|
| `multiprocess_framework/.../plugins/base.py` | start() non-abstract, _init_register(), SubPluginContext |
| `multiprocess_framework/.../plugins/registry.py` | PluginEntry: register_class приоритет |
| `multiprocess_framework/.../plugins/__init__.py` | Экспорт SubPluginContext |
| 16 файлов `plugins/*/plugin.py` | Убраны start(), _init_register, SubPluginContext |
| 6 файлов `plugins/*/tests/test_*.py` | Обновлены ассерты: _attr → _reg.attr |

## SHM архитектура (уточнение)

SHM проходит через RouterManager → FrameShmMiddleware → MemoryManager:
- **Source-плагины**: `memory` property в config.py для pre-allocation ring buffer
- **Processing-плагины**: SHM прозрачен через middleware, `memory` не нужен
- Плагины работают с `list[dict]` — фреймворк делает сериализацию/десериализацию

## Verification

```bash
# Все тесты плагинов
python -m pytest multiprocess_prototype_2/plugins/ -q
# 163 passed

# Тесты FW
python -m pytest multiprocess_framework/modules/registers_module/tests/ multiprocess_framework/modules/data_schema_module/tests/ -q
# 578 passed
```
