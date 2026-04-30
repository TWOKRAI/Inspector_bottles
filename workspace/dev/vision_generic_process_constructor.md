# Vision: GenericProcess + Plugin Constructor

## Суть

Фреймворк-конструктор: система собирается из конфигов, не из кода.
Новый процесс = новый конфиг, не новая папка с 6 файлами.

## Архитектура — три уровня

```
Уровень 3: Приложение
  SystemBlueprint (SchemaBase) — чертёж системы
  Описывает: какие процессы, какие плагины, связи между ними
  Редактируемый в UI, сохраняемый как рецепт
  Ноль кода — только данные

Уровень 2: Каталог плагинов + контракты
  Глобальный PluginRegistry — все плагины в одном месте
  Каждый плагин = SchemaBase с типизированными портами
  Порты: MIME-dtype + shape-шаблон (от GStreamer caps)
  Именованные выходы (от NiFi relationships)
  Валидация цепочки до запуска (от UE compile-time)

Уровень 1: Multiprocess Framework
  GenericProcess — тонкий контейнер (только lifecycle)
  CommandManager — исполнитель цепочки плагинов
  Auto-wiring портов внутри процесса
  State machine плагина: IDLE → READY → RUNNING → STOPPED (от GStreamer)
```

---

## Ключевые принципы

### 1. SchemaBase насквозь

Всё — SchemaBase: чертёж, конфиг процесса, конфиг плагина, порты.

- **Валидация** (Pydantic v2) — ошибки до запуска
- **Интроспекция** (FieldMeta) → автоматический UI, таблицы
- **Сериализация** (dict / JSON / YAML) → рецепты, сохранение, загрузка
- **Редактирование** в UI без кода

### 2. Единый каталог плагинов

Один глобальный **PluginRegistry** — все плагины системы.
Каждый процесс видит весь каталог и может использовать любой плагин.

Регистрация через декоратор (от Node-RED — простота):
```python
@register_plugin("color_mask", category="processing")
class ColorMaskPlugin(ProcessModulePlugin):
    ...
```

Каталог знает:
- Имя, категория, описание
- Входы/выходы (порты с типами)
- Параметры (SchemaBase config)
- Команды

UI показывает каталог с фильтром по совместимости с текущей цепочкой.

### 3. Плагин = SchemaBase + порты + команды

```python
@register_plugin("color_mask", category="processing")
class ColorMaskPlugin(ProcessModulePlugin):
    name = "color_mask"
    category = "processing"

    # Порты — типизированные (от GStreamer caps)
    # dtype = MIME-подобная строка: "image/bgr", "image/gray", "dict", "tensor/float32"
    # shape = шаблон с переменными: "(H, W, 3)" — разрешение согласуется при линковке
    inputs = [
        Port("frame", dtype="image/bgr", shape="(H, W, 3)"),
    ]

    # Именованные выходы (от NiFi relationships)
    # Плагин может иметь несколько выходов с разными типами
    outputs = [
        Port("mask", dtype="image/gray", shape="(H, W, 1)"),
        Port("stats", dtype="dict"),      # статистика (опционально)
    ]

    # Параметры — SchemaBase (редактируемые в UI)
    config_schema = ColorMaskConfig       # h_min, h_max, s_min, ...

    # Команды — привязаны к методам класса
    # Регистрируются в CommandManager автоматически
    commands = {
        "set_hsv_range": "set_range",     # имя_команды → имя_метода
        "get_mask_stats": "get_stats",
    }
```

Плагин декларирует:
- **Входы** — что ожидает (dtype + shape)
- **Выходы** — что отдаёт (именованные, типизированные)
- **Параметры** — SchemaBase-конфиг
- **Команды** — привязаны к методам, регистрируются в CommandManager

### 4. Типизация портов (от GStreamer caps + UE pins)

```python
@register_schema("PortV1")
class Port(SchemaBase):
    name: str           # "frame", "mask", "detection", "stats"
    dtype: str          # MIME-подобный: "image/bgr", "image/gray", "dict", "tensor/float32"
    shape: str = ""     # Шаблон: "(H, W, 3)", "(N, 4)", "" (произвольный)
    optional: bool = False  # Обязательный или нет
```

dtype-иерархия (от UE — наследование типов):
```
image/*         — любое изображение
  image/bgr     — BGR 3-канальное
  image/gray    — grayscale 1-канальное
  image/rgba    — RGBA 4-канальное
tensor/*        — тензор
  tensor/float32
  tensor/uint8
dict            — словарь (произвольные данные)
bytes           — сырые байты
```

Совместимость: `image/bgr` подходит к `image/*`, но не к `image/gray`.
Аналог: GStreamer caps intersection + UE pin type inheritance.

### 5. Валидация цепочки до запуска (от UE compile-time)

При сборке чертежа — автоматическая проверка:

```
capture.outputs[frame]     → color_mask.inputs[frame]
  image/bgr (H,W,3)       → image/bgr (H,W,3)         ✓ СОВМЕСТИМО

color_mask.outputs[mask]   → blur.inputs[frame]
  image/gray (H,W,1)      → image/bgr (H,W,3)         ✗ ОШИБКА dtype

blur.outputs[result]       → render.inputs[overlay]
  image/bgr (H,W,3)       → image/* (H,W,*)            ✓ wildcard match
```

UI показывает ошибки при редактировании — **до** запуска системы.
`blueprint.validate()` → список ошибок или OK.

### 6. Auto-wiring внутри процесса

Если в процессе цепочка `[A, B, C]`:
- Выход A автоматически подключается ко входу B
- Выход B → ко входу C
- SHM-имена генерируются автоматически
- Ручное подключение — только для нестандартных связей

```python
ProcessConfig(
    process_name="processor_0",
    plugins=[ColorMask(...), Blur(...), EdgeDetect(...)],
    # auto-wiring: ColorMask.mask → Blur.frame → EdgeDetect.frame
    # переопределение: wires={"blur.frame": "color_mask.stats"}
)
```

Аналог: GStreamer `gst_element_link()` с автоматическим согласованием caps.

### 7. State machine плагина (от GStreamer)

```
IDLE → READY → RUNNING → STOPPED
       ↑          ↓
       ←── PAUSED ←
```

| Состояние | Что происходит | Аналог GStreamer |
|-----------|----------------|-----------------|
| **IDLE** | Плагин зарегистрирован в каталоге, не инициализирован | NULL |
| **READY** | configure() выполнен: ресурсы выделены, команды зарегистрированы | READY |
| **RUNNING** | start() выполнен: воркеры запущены, данные текут | PLAYING |
| **PAUSED** | Воркеры приостановлены, ресурсы удерживаются | PAUSED |
| **STOPPED** | shutdown() выполнен: ресурсы освобождены | NULL |

Тяжёлый плагин (capture, database): полный lifecycle IDLE→READY→RUNNING→STOPPED.
Лёгкий плагин (blur, threshold): IDLE→READY→RUNNING, минимальные ресурсы.

Интерфейс один — плагин сам решает что ему нужно на каждом переходе.

### 8. CommandManager как исполнитель

GenericProcess не содержит логики — только lifecycle контейнер:
1. Получает конфиг с `plugins: [...]`
2. Загружает плагины из каталога (PluginRegistry)
3. Переводит их через state machine: IDLE → READY → RUNNING
4. Команды плагинов автоматически регистрируются в CommandManager
5. CommandManager выполняет цепочку в порядке конфига

Плагины взаимодействуют через CommandManager — тот же механизм что уже есть в каждом процессе.

### 9. Чертёж (SystemBlueprint) — SchemaBase

```python
blueprint = SystemBlueprint(
    name="color_mask_demo",
    description="Вебкамера → HSV-маска → overlay",
    processes=[
        ProcessConfig(
            process_name="camera_0",
            priority="high",
            plugins=[
                CapturePluginConfig(camera_id=0, fps=25, resolution=(640, 480)),
            ],
        ),
        ProcessConfig(
            process_name="processor_0",
            plugins=[
                ColorMaskPluginConfig(h_range=(35, 85), s_range=(50, 255)),
                # добавить в цепочку:
                # BlurPluginConfig(kernel=5),
                # EdgeDetectPluginConfig(threshold=100),
            ],
        ),
        ProcessConfig(
            process_name="renderer",
            plugins=[
                RenderPluginConfig(mask_alpha=0.5, color=(0, 255, 0)),
            ],
        ),
    ],
    # Межпроцессные связи (между процессами — через IPC/SHM)
    wires=[
        Wire(source="camera_0.capture.frame", target="processor_0.color_mask.frame"),
        Wire(source="processor_0.color_mask.mask", target="renderer.render.mask"),
        Wire(source="camera_0.capture.frame", target="renderer.render.frame"),
    ],
)
```

SchemaBase → можно:
- Сохранить как рецепт (YAML)
- Загрузить из рецепта
- Редактировать в UI-таблицах
- Валидировать цепочки и связи до запуска
- Передать в ProcessManager как чертёж → он реализует

### 10. Дополнительные возможности

**Plugin hot-reload:**
Параметры плагина меняются через StateProxy → плагин применяет на лету.
Основа для UI-редактирования в реальном времени (h_min/h_max slider → мгновенный результат).

**Plugin metrics (автоматические):**
PluginContext оборачивает process/tick в замер — без кода в плагине.
- Время обработки (мс)
- FPS
- Количество ошибок
- Загрузка очереди

Данные видны в UI (Processes tab). Аналог: NiFi processor stats.

**Plugin test bench:**
Тестировать плагин изолированно без запуска процесса:
```python
bench = PluginTestBench(ColorMaskPlugin, config={"h_min": 35, "h_max": 85})
result = bench.process(test_frame)
assert result.outputs["mask"].shape == (480, 640, 1)
```

---

## Индустриальные решения — что взяли

| Что берём | Откуда | Зачем |
|-----------|--------|-------|
| Типизированные порты (caps) | GStreamer | Совместимость портов, валидация цепочки |
| MIME-подобный dtype | GStreamer caps | Простая иерархия типов (`image/*` → `image/bgr`) |
| Именованные выходы (relationships) | Apache NiFi | Плагин с несколькими выходами (mask, stats, error) |
| Compile-time валидация | UE Blueprints | Ошибки до запуска, не в runtime |
| Наследование типов пинов | UE Blueprints | `image/bgr` совместим с `image/*` |
| Простая регистрация (@decorator) | Node-RED | Минимальный boilerplate |
| State machine (NULL→READY→PLAYING) | GStreamer | Lifecycle тяжёлых плагинов |
| Launch-конфиг как данные | ROS2 | SystemBlueprint как SchemaBase |
| Processor stats | Apache NiFi | Автометрики без кода |
| PropertyDescriptor + validate | NiFi / Node-RED | SchemaBase + FieldMeta (уже есть, лучше) |

---

## Что уже сделано (Phase 1) — commit 5492ab5

- GenericProcess — загружает плагины из конфига ✓
- ProcessModulePlugin — единый интерфейс (configure/start/shutdown) ✓
- PluginContext — фасад над ProcessModule ✓
- PluginConfig (SchemaBase) — базовый конфиг плагина ✓
- GenericProcessConfig — ProcessLaunchConfig с plugins[] ✓
- 3 плагина: capture, color_mask, render ✓
- SystemBlueprint (Django-style) + demo_generic.py ✓
- Существующие тесты не сломаны (1932 passed) ✓

## Roadmap (Phase 2+)

### Phase 2: Port + PluginRegistry
- `Port(name, dtype, shape)` — SchemaBase для типизированных портов
- `@register_plugin` декоратор → глобальный PluginRegistry
- Добавить ports к существующим 3 плагинам
- `PluginRegistry.list()`, `.get()`, `.filter(category=...)`, `.compatible_with(port)`

### Phase 3: SchemaBase-чертёж + Wire
- SystemBlueprint и ProcessConfig как SchemaBase (переделать Django-style)
- `Wire(source, target)` — межпроцессные связи
- Auto-wiring внутри процесса (порядок в списке)
- `blueprint.validate()` — проверка совместимости портов до запуска
- Сериализация / десериализация → рецепты

### Phase 4: State machine + CommandManager
- State machine плагина: IDLE → READY → RUNNING → PAUSED → STOPPED
- Команды плагинов → CommandManager автоматически
- GenericProcess → тонкий контейнер (только lifecycle + state transitions)
- Hot-reload параметров через StateProxy

### Phase 5: Метрики + TestBench
- Автометрики в PluginContext (время, fps, ошибки) без кода
- PluginTestBench — тестирование плагина изолированно
- Данные метрик → UI (Processes tab)

### Phase 6: UI-интеграция
- Каталог плагинов в UI (фильтр по категории, совместимость)
- Редактирование чертежа в таблицах (SystemTopology)
- Визуализация цепочки с портами и типами
- Save/load чертежей как рецепты
- Drag & drop плагинов в цепочку
