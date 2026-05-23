# bridge — IPC-мосты для frontend_module

Pure-Python примитивы для коммуникации GUI ↔ процессы.
Нет зависимостей от Qt или IPC-транспорта (Qt-опции ленивые).

## Ключевые символы

- `CommandSender` — формирует и отправляет IPC-команды с debounce
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
