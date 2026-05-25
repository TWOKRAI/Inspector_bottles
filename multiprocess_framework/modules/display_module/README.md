# display_module

## Назначение

`display_module` — framework-модуль декларативного реестра именованных SHM-каналов для отображения кадров.

Модуль является **generic-компонентом фреймворка** и не знает о vision-семантике (`element_shape`, `dtype`, numpy). Он предоставляет контракт (`DisplayEntry`, `IDisplayRegistry`, `IDisplayChannel`), thread-safe реестр (`DisplayRegistry`) с YAML-персистентностью. Конкретный numpy-shape и создание SHM-сегмента вычисляет prototype-слой при следующем запуске `ProcessManagerProcess` через `SharedResourcesManager` (ADR-025).

Inspector-приложение потребляет модуль через публичный API: `DisplayRegistry().register(entry)` → `persist(path)` → при старте процессов `SharedResourcesManager` читает blueprint и создаёт SHM-сегменты. GUI (`DisplaysTab`, `PreviewWindow`) подписывается на канал через `RouterManager.register_broadcast_route`.

## Структура модуля

```
display_module/
├── __init__.py        # Публичный API — реэкспорт ключевых имён
├── interfaces.py      # DisplayEntry dataclass + IDisplayRegistry, IDisplayChannel Protocol
├── registry.py        # DisplayRegistry singleton + persist/load YAML
├── README.md
├── STATUS.md
├── DECISIONS.md
└── tests/
    ├── __init__.py
    └── test_registry.py  # ≥8 тестов (Task 4.8)
```

## Публичный API

```python
from multiprocess_framework.modules.display_module import (
    DisplayEntry,       # dataclass — конфигурационная запись дисплея
    IDisplayRegistry,   # Protocol — контракт реестра дисплеев
    IDisplayChannel,    # Protocol — контракт SHM-канала кадров
    DisplayRegistry,    # singleton — thread-safe реестр с YAML-персистентностью
)
```

### Таблица компонентов

| Компонент | Тип | Описание |
|-----------|-----|----------|
| `DisplayEntry` | `@dataclass` | Конфиг дисплея: `id`, `name`, `width`, `height`, `format`, `fps_limit`, `ring_buffer_blocks` |
| `IDisplayRegistry` | `@runtime_checkable Protocol` | Контракт: `register`, `unregister`, `get`, `list`, `persist` |
| `IDisplayChannel` | `@runtime_checkable Protocol` | Контракт: `channel_key`, `subscribe`, `unsubscribe`, `is_active` |
| `DisplayRegistry()` | singleton | Реестр: `register`, `unregister`, `get`, `list`, `persist`, `load`, `clear` |

## Быстрый старт

```python
from multiprocess_framework.modules.display_module import DisplayRegistry, DisplayEntry
from pathlib import Path

# Получить singleton (всегда тот же объект)
reg = DisplayRegistry()

# Зарегистрировать дисплей
reg.register(DisplayEntry(
    id="main",
    name="Основной",
    width=1280,
    height=720,
    format="BGR",
    fps_limit=30.0,
    ring_buffer_blocks=3,
))

# Сохранить в YAML (путь решает prototype-слой, ADR-DM-002)
reg.persist(Path("multiprocess_prototype/backend/config/displays.yaml"))

# Прочитать обратно при следующем запуске
reg.load(Path("multiprocess_prototype/backend/config/displays.yaml"))

# CRUD
entry = reg.get("main")          # DisplayEntry | None
all_entries = reg.list()          # list[DisplayEntry] (копия)
removed = reg.unregister("main")  # True если был найден
```

### Формат YAML

```yaml
displays:
  - id: main
    name: Основной
    width: 1280
    height: 720
    format: BGR
    fps_limit: 30.0
    ring_buffer_blocks: 3
  - id: debug
    name: Отладочный
    width: 640
    height: 480
    format: GRAY
    fps_limit: 15.0
    ring_buffer_blocks: 2
```

## Связь с blueprint

После `persist` prototype-слой читает `displays.yaml` и создаёт SHM-запись в blueprint. Это делает `multiprocess_prototype/backend/displays/blueprint_binding.py` через функцию `bind_displays_to_blueprint`:

```python
# Пример из prototype-слоя (не часть display_module)
from multiprocess_prototype.backend.displays.blueprint_binding import bind_displays_to_blueprint
from multiprocess_framework.modules.display_module import DisplayRegistry
from pathlib import Path

reg = DisplayRegistry()
reg.load(Path("backend/config/displays.yaml"))
bind_displays_to_blueprint(reg.list(), blueprint)
```

Фактическое создание SHM-сегмента происходит при следующем запуске `ProcessManagerProcess` через `SharedResourcesManager` (ADR-025). До старта процессов SHM-сегмент не существует — дисплей зарегистрирован декларативно.

## Что НЕ входит в display_module

- **Создание SHM-сегмента** — делает `SharedResourcesManager` при старте `ProcessManagerProcess` по blueprint (ADR-025)
- **Чтение кадров** — делает `PreviewWindow` в `multiprocess_prototype/frontend/widgets/displays/preview_window.py`
- **Fan-out routing** — делает `RouterManager.register_broadcast_route` в `router_module`
- **Vision-семантика** (`element_shape`, `dtype`) — вычисляет prototype-слой через `_format_to_channels(format)` при создании SHM-сегмента (ADR-DM-001)

## Зависимости

- **Зависит от:** `stdlib` (`threading`, `dataclasses`, `pathlib`), `PyYAML` (`yaml.safe_dump`, `yaml.safe_load`)
- **Используется в:** `multiprocess_prototype/frontend/widgets/tabs/displays/` (Task 4.2), `multiprocess_prototype/backend/displays/blueprint_binding.py` (Task 4.3), `multiprocess_prototype/backend/state/adapters/display_state_adapter.py`
- **Слой импортов:** `multiprocess_framework → Services → Plugins → multiprocess_prototype` (обратные запрещены)

## Ограничения

- **SHM cleanup при `unregister`** — `_cleanup_shm_channel` только логирует предупреждение. Фактическое освобождение SHM происходит при следующем рестарте `ProcessManagerProcess` (ADR-DM-003 / ADR-025). До рестарта зомби-SHM может занимать память.
- **`IDisplayChannel` без конкретной реализации в framework** — Protocol объявлен, конкретная реализация создаётся в `RouterManager` или prototype-обёртке (Phase 7). Это не ошибка: Protocol служит контрактом для type-checker.
- **Нет интеграции с StateStore / GUI** — синхронизацию обеспечивает `DisplayStateAdapter` в `multiprocess_prototype/` (не часть этого модуля).

## Связанные модули

- [`shared_resources_module/`](../shared_resources_module/README.md) — создание SHM-сегмента при старте процессов по конфигурации blueprint (ADR-025).
- [`router_module/`](../router_module/README.md) — `RouterManager.register_broadcast_route` реализует fan-out routing на SHM-каналы.
- [`service_module/`](../service_module/README.md) — образец паттерна singleton+YAML-реестр (ADR-129), на котором основан `DisplayRegistry`.
- ADR-130 (Task 4.9) — глобальное решение в [`multiprocess_framework/DECISIONS.md`](../../DECISIONS.md): «DisplayRegistry: декларативный реестр SHM-каналов».

## Тесты

```bash
# Запускать из корня проекта
pytest multiprocess_framework/modules/display_module/tests/
```

≥8 тестов в `test_registry.py` (Task 4.8). Покрытие: singleton-гарантия, thread-safety при конкурентной регистрации, дублирующиеся id → `ValueError`, `clear()` для изоляции между тестами, `persist`/`load` round-trip, `unregister` несуществующего → `False`.

## Phase 4 trace

Модуль создан в **Phase 4** плана `prototype-skeleton-2026-05` (Tasks 4.1–4.9) на ветке `feat/displays-tab`. Полное ТЗ фазы: [`plans/prototype-skeleton-2026-05/phase-4-displays-tab.md`](../../../../plans/prototype-skeleton-2026-05/phase-4-displays-tab.md).
