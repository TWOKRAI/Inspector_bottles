# bridge — IPC-мосты для frontend_module

Примитивы для коммуникации GUI ↔ процессы. Модули пакета не импортируют Qt на верхнем уровне,
кроме `frame_pump` (`FramePump`): он тянет PySide6 и не импортируется через `import bridge`.
Остальные модули не зависят от IPC-транспорта (Qt-опции ленивые).

## Ключевые символы

- `CommandSender` — формирует и отправляет IPC-команды с debounce
- `FramePump` (`bridge/frame_pump.py`, Qt, импортировать явно) — вытягивает кадры из ящика «последний на ключ» таймером на ключ; ADR FE-007
- `IProcess` — минимальный Protocol процесса для CommandSender
- `CommandValidator` — валидирует команды перед отправкой в IPC
- `ValidationResult` — результат валидации (ok / error)
- `WireConfig` — конфигурация wire (source → target)
- `ShmConfig` — параметры shared memory региона
- `validate_wire` — проверка корректности WireConfig
- `WireStatusMonitor` — отслеживает статусы и метрики wire'ов
- `WireStatus` — enum жизненного цикла wire
- `WireMetrics` — fps / latency_ms / buffer_fill
- `TopologyDiff` — diff между двумя topology dict
- `compute_diff` — вычислить diff
- Builders (`build_process_start`, `build_wire_setup`, …) — фабрики IPC-команд

## Stability

`partial` — API стабилен, покрытие тестами неполное
(→ `contract` после Task C1)

→ Корневой README: `../../README.md`
