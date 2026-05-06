# Task 5.1 — InspectorManager

**Status:** IN PROGRESS
**Branch:** `feat/phase5-task5.1-inspector-manager`
**Level:** Senior (Opus)
**Assignee:** teamlead

## Цель

Создать InspectorManager — компонент буферизации items по `(camera_id, seq_id)` для fan-in сценариев. Без fan-in (нет `total_regions`) — pass-through.

## Контекст

В текущей архитектуре stitcher сам буферизует регионы по seq_id с timeout. Эта логика выносится в универсальный менеджер внутри GenericProcess. InspectorManager принимает item из Data Worker, проверяет `total_regions`, буферизует по `(camera_id, seq_id)`, и когда коллекция готова — отдаёт `list[dict]` в очередь Chain Worker.

## Файлы

| Действие | Путь |
|----------|------|
| СОЗДАТЬ | `multiprocess_framework/modules/process_module/generic/inspector_manager.py` |
| ИЗМЕНИТЬ | `multiprocess_framework/modules/process_module/generic/__init__.py` |
| СОЗДАТЬ | `multiprocess_framework/modules/process_module/tests/test_inspector_manager.py` |

## API

```python
class InspectorManager:
    def __init__(
        self,
        timeout_sec: float = 0.5,
        on_ready: Callable[[list[dict]], None] | None = None,
        log_info: Callable[[str], None] | None = None,
        log_error: Callable[[str], None] | None = None,
    ):
        """on_ready — callback для отправки готовых коллекций в Chain Worker."""

    def on_item(self, item: dict) -> None:
        """Принять item. Без fan-in → сразу on_ready([item]).
        С fan-in → буферизация по (camera_id, seq_id)."""

    def check_timeouts(self) -> None:
        """Выдать просроченные коллекции. Вызывается периодически."""
```

## Логика

1. **Ключ буфера:** `(camera_id, seq_id)` — составной, изолирует камеры
2. **Pass-through:** если `total_regions` нет или == 0 или == 1 → `on_ready([item])` немедленно
3. **Fan-in:** `total_regions > 1` → добавить в буфер `{(cam, seq): {region_name: item, ...}}`
4. **Готовность:** `len(buffer[(cam, seq)]) >= total_regions` → `on_ready(list(items.values()))`
5. **Timeout:** `time.monotonic() - first_arrival > timeout_sec` → flush неполной коллекции
6. **Дубликат region_name:** перезапись с warning
7. **Defaults:** `camera_id` default 0, `seq_id` default 0
8. **Thread-safety:** `threading.Lock` на буфер
9. **Cleanup:** `check_timeouts()` удаляет записи старше `2 * timeout_sec`

## Тесты (≥ 9)

1. Pass-through без `total_regions`
2. Pass-through с `total_regions=0`
3. Pass-through с `total_regions=1`
4. Fan-in: 3 items → on_ready вызван 1 раз с 3 items
5. Multi-camera изоляция: `(cam=0, seq=5)` и `(cam=1, seq=5)` — два вызова on_ready
6. Timeout: 2/3 items + timeout → flush неполной коллекции
7. Cleanup: старые записи удаляются
8. Дубликат region_name → перезапись, warning
9. Thread-safety: concurrent on_item без race condition
10. Default camera_id=0 если отсутствует

## Acceptance Criteria

- [ ] Без fan-in: немедленный pass-through
- [ ] Fan-in: буферизация по (camera_id, seq_id), ready при полной коллекции
- [ ] Multi-camera изоляция работает
- [ ] Timeout flush неполных коллекций
- [ ] Thread-safe
- [ ] ≥ 9 тестов проходят

## Out of Scope

- Не менять GenericProcess (Task 5.3)
- Не трогать IPC/SHM
- Не менять другие файлы кроме указанных
