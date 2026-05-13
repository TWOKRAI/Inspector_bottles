# Plan: Улучшение registers_module (5.5 → 8.5)

> **Дата:** 2026-04-10
> **Контекст:** registers_module — самый слабый модуль фреймворка (5.5/10 в общей оценке).
> Код чистый (9/10), но тесты неполные, README не объясняет интеграцию, STATUS рассинхронизирован.
> Нужно довести до уровня остальных модулей перед созданием прототипа.
> **Исполнитель:** Cursor Composer v2. Claude — review.

---

## 0. Текущее состояние

| Аспект | Было | Цель |
|--------|------|------|
| Тесты | 26 кейсов, 7/10 | 45+ кейсов, 9/10 |
| Документация | README 2.4 KB, 8/10 | README 5+ KB с примерами, 9/10 |
| STATUS.md | этап 5/8, scores outdated | этап 8/8, scores updated |
| interfaces.py | 4 метода (минимум) | расширить до реальной surface area |
| Итого | **5.5/10** | **8.5/10** |

**Что НЕ трогаем:** core/manager.py, core/dispatch.py, core/routing_map.py — код качественный (9/10), менять не нужно.

---

## 1. Тесты — добавить 20+ кейсов

### 1.1 test_manager.py — добавить

Файл: `modules/registers_module/tests/test_manager.py`

```python
# --- Пропущенные edge-case ---

def test_set_field_value_missing_register():
    """set_field_value для несуществующего регистра → (False, error)"""
    rm = RegistersManager({})
    ok, err = rm.set_field_value("ghost", "x", 1)
    assert ok is False
    assert "ghost" in err

def test_set_field_value_missing_field():
    """set_field_value для несуществующего поля → (False, error)"""
    rm = RegistersManager({"d": _Draw()})
    ok, err = rm.set_field_value("d", "nonexistent", 1)
    assert ok is False
    assert "nonexistent" in err

def test_set_connection():
    """set_connection обновляет connection_map"""
    rm = RegistersManager({"d": _Draw()})
    rm.set_connection("d", "new_process")
    # Verify через send_callback
    calls = []
    rm.set_send_callback(lambda ch, *a: calls.append(ch))
    rm.set_field_value("d", "dp", 5.0)
    assert calls == ["control_new_process"]

def test_set_send_callback():
    """set_send_callback меняет callback на лету"""
    calls_a, calls_b = [], []
    rm = RegistersManager({"x": _Disp()}, send_callback=lambda ch, *a: calls_a.append(ch))
    rm.set_field_value("x", "n", 1)
    assert len(calls_a) == 1
    rm.set_send_callback(lambda ch, *a: calls_b.append(ch))
    rm.set_field_value("x", "n", 2)
    assert len(calls_b) == 1
    assert len(calls_a) == 1  # Первый callback больше не вызывается

def test_set_send_callback_none_disables():
    """set_send_callback(None) отключает отправку"""
    calls = []
    rm = RegistersManager({"x": _Disp()}, send_callback=lambda ch, *a: calls.append(ch))
    rm.set_send_callback(None)
    rm.set_field_value("x", "n", 3)
    assert calls == []

def test_notify_field_changed_only_field_observers():
    """notify_field_changed НЕ вызывает global observers и НЕ вызывает send_callback"""
    field_seen, global_seen, send_seen = [], [], []
    rm = RegistersManager({"d": _Draw()}, send_callback=lambda *a: send_seen.append(1))
    rm.subscribe("d", "dp", field_seen.append)
    rm.subscribe_all(lambda r, f, v: global_seen.append(v))
    rm.notify_field_changed("d", "dp", 9.0)
    assert field_seen == [9.0]
    assert global_seen == []  # Не вызван
    assert send_seen == []    # Не вызван

def test_observer_exception_does_not_break_others():
    """Исключение в одном observer не мешает другим"""
    results = []
    def bad_cb(v): raise RuntimeError("boom")
    def good_cb(v): results.append(v)
    rm = RegistersManager({"d": _Draw()})
    rm.subscribe("d", "dp", bad_cb)
    rm.subscribe("d", "dp", good_cb)
    rm.set_field_value("d", "dp", 5.0)
    assert results == [5.0]

def test_global_observer_exception_does_not_break_others():
    """Исключение в global observer не мешает другим"""
    results = []
    def bad_gcb(r, f, v): raise RuntimeError("boom")
    def good_gcb(r, f, v): results.append(v)
    rm = RegistersManager({"d": _Draw()})
    rm.subscribe_all(bad_gcb)
    rm.subscribe_all(good_gcb)
    rm.set_field_value("d", "dp", 5.0)
    assert results == [5.0]

def test_send_callback_exception_logged_not_raised():
    """Исключение в send_callback логируется, не прерывает set_field_value"""
    def bad_send(ch, *a): raise ConnectionError("network down")
    rm = RegistersManager({"x": _Disp()}, send_callback=bad_send)
    ok, err = rm.set_field_value("x", "n", 5)
    assert ok is True  # Значение установлено, несмотря на ошибку callback

def test_subscribe_duplicate_ignored():
    """Повторная подписка того же callback — не дублирует"""
    rm = RegistersManager({"d": _Draw()})
    seen = []
    cb = lambda v: seen.append(v)
    rm.subscribe("d", "dp", cb)
    rm.subscribe("d", "dp", cb)  # duplicate
    rm.set_field_value("d", "dp", 5.0)
    assert seen == [5.0]  # Один раз, не два

def test_unsubscribe_nonexistent_callback_no_error():
    """unsubscribe несуществующего callback — без ошибки"""
    rm = RegistersManager({"d": _Draw()})
    rm.unsubscribe("d", "dp", lambda v: None)  # Не должно бросить

def test_unsubscribe_all_nonexistent_no_error():
    """unsubscribe_all несуществующего callback — без ошибки"""
    rm = RegistersManager({})
    rm.unsubscribe_all(lambda r, f, v: None)

def test_validate_field_value_missing_register():
    """validate_field_value для несуществующего регистра"""
    rm = RegistersManager({})
    ok, err = rm.validate_field_value("ghost", "x", 1)
    assert ok is False
    assert "ghost" in err

def test_model_dump_validate_roundtrip():
    """model_dump_all → model_validate_all roundtrip preserves data"""
    rm = RegistersManager({"d": _Draw()})
    rm.set_field_value("d", "dp", 7.5)
    dumped = rm.model_dump_all()
    rm2 = RegistersManager({"d": _Draw()})
    rm2.model_validate_all(dumped)
    assert rm2.get_register("d").dp == 7.5

def test_set_field_value_snapshot_in_send_callback():
    """send_callback получает snapshot (полный model_dump регистра)"""
    snapshots = []
    def send_cb(ch, reg, field, val, snapshot):
        snapshots.append(snapshot)
    rm = RegistersManager({"x": _Disp()}, send_callback=send_cb)
    rm.set_field_value("x", "n", 5)
    assert len(snapshots) == 1
    assert snapshots[0]["n"] == 5  # Snapshot содержит обновлённое значение
```

### 1.2 test_dispatch_routing.py — добавить

Файл: `modules/registers_module/tests/test_dispatch_routing.py`

```python
def test_empty_process_targets_no_dispatch():
    """FieldRouting(process_targets=()) → пустой dispatch, send_callback не вызван"""
    # Регистр с пустым process_targets
    class _Empty(SchemaBase):
        register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
            process_targets=(),
        )
        x: Annotated[int, FieldMeta("x")] = 0
    
    calls = []
    rm = RegistersManager({"e": _Empty()}, send_callback=lambda *a: calls.append(1))
    rm.set_field_value("e", "x", 5)
    assert calls == []

def test_no_dispatch_no_connection_map_no_send():
    """Регистр без dispatch и без connection_map → send_callback не вызван"""
    class _Plain(SchemaBase):
        y: Annotated[int, FieldMeta("y")] = 0
    
    calls = []
    rm = RegistersManager({"p": _Plain()}, send_callback=lambda *a: calls.append(1))
    rm.set_field_value("p", "y", 3)
    assert calls == []

def test_channel_prefix_not_duplicated():
    """Если process_targets уже с 'control_' — не добавлять повторно"""
    class _Ctrl(SchemaBase):
        register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
            process_targets=("control_renderer",),
        )
        z: Annotated[int, FieldMeta("z")] = 0
    
    calls = []
    rm = RegistersManager({"c": _Ctrl()}, send_callback=lambda ch, *a: calls.append(ch))
    rm.set_field_value("c", "z", 1)
    assert calls == ["control_renderer"]  # НЕ "control_control_renderer"
```

### 1.3 test_routing_map.py — добавить

Файл: `modules/registers_module/tests/test_routing_map.py`

```python
def test_send_register_message_with_error_callback():
    """error_callback вызывается при ROUTING_NOT_FOUND"""
    errors = []
    result = send_register_message(
        router=_FakeRouter(),
        routing_map={},  # Пустой — routing не найден
        register_name="camera",
        field_name="fps",
        value=30,
        error_callback=lambda code, info: errors.append(code),
    )
    assert result is not None
    assert result.get("error") == ROUTING_NOT_FOUND
    assert errors == [ROUTING_NOT_FOUND]

def test_build_routing_map_multiple_registers():
    """routing_map из нескольких регистров с разными routing"""
    # Используя несколько регистров, проверить что маппинг полный
    ...
```

---

## 2. interfaces.py — расширить

Файл: `modules/registers_module/interfaces.py`

Текущий IRegistersManager имеет 4 метода. Добавить остальные, которые реально используются в frontend_module и prototype:

```python
class IRegistersManager(Protocol):
    """Полный runtime-контракт registers_module."""
    
    # --- Storage (delegation) ---
    def get_register(self, name: str) -> Optional[Any]: ...
    def set_register(self, name: str, instance: Any) -> None: ...
    def register_names(self) -> List[str]: ...
    def get_field_metadata(self, register_name: str, field_name: str, **kw) -> Dict[str, Any]: ...
    def validate_field_value(self, register_name: str, field_name: str, value: Any, current_access_level: int = 0) -> Tuple[bool, Optional[str]]: ...
    def model_dump_all(self) -> Dict[str, Any]: ...
    def model_validate_all(self, data: Dict[str, Any], strict: bool = False) -> None: ...
    
    # --- Pub/Sub ---
    def subscribe(self, register_name: str, field_name: str, callback: Callable) -> None: ...
    def unsubscribe(self, register_name: str, field_name: str, callback: Callable) -> None: ...
    def subscribe_all(self, callback: Callable) -> None: ...
    def unsubscribe_all(self, callback: Callable) -> None: ...
    
    # --- Write + Dispatch ---
    def set_field_value(self, register_name: str, field_name: str, value: Any) -> Tuple[bool, Optional[str]]: ...
    def notify_field_changed(self, register_name: str, field_name: str, value: Any) -> None: ...
    
    # --- Config ---
    def set_connection(self, register_name: str, backend_channel: str) -> None: ...
    def set_send_callback(self, callback: Optional[Callable]) -> None: ...
```

---

## 3. README.md — переписать

Файл: `modules/registers_module/README.md`

### Структура нового README:

1. **Назначение** — runtime pub/sub + dispatch для SchemaBase регистров
2. **Архитектура** — mermaid-диаграмма (3 слоя: data_schema → registers → frontend/router)
3. **Quick Start** — минимальный пример:
   ```python
   from registers_module import RegistersManager
   from data_schema_module import SchemaBase, FieldMeta, FieldRouting, RegisterDispatchMeta
   
   class CameraRegisters(SchemaBase):
       register_dispatch = RegisterDispatchMeta(process_targets=("camera_process",))
       fps: Annotated[int, FieldMeta("FPS", min=1, max=120, routing=FieldRouting(channel="control_camera"))] = 25
   
   rm = RegistersManager(
       registers={"camera": CameraRegisters()},
       send_callback=lambda ch, reg, field, val, snap: print(f"→ {ch}: {field}={val}")
   )
   rm.set_field_value("camera", "fps", 30)
   # → control_camera_process: fps=30
   ```
4. **Dispatch Priority** — таблица 4 уровней (field → class → connection_map → nothing)
5. **Pub/Sub API** — subscribe/unsubscribe/notify_field_changed
6. **Интеграция с frontend** — как FrontendRegistersBridge подключает RegistersManager к Router
7. **Интеграция с прототипом** — как factory создаёт RegistersManager
8. **send_callback сигнатура** — `(channel, register_name, field_name, value, snapshot)` + объяснение `control_` prefix
9. **Зависимости** — data_schema_module (RegistersContainer, SchemaBase, FieldMeta, FieldRouting, RegisterDispatchMeta)
10. **Ссылки** — DECISIONS.md, interfaces.py, ROUTING_GLOSSARY.md

---

## 4. STATUS.md — обновить

Файл: `modules/registers_module/STATUS.md`

После выполнения этого плана:

```markdown
## Текущий этап: 8 / 8

| Критерий | Оценка |
|----------|--------|
| Код | 9 |
| Тесты | 9 |  (было 8 → 45+ кейсов)
| Документация | 9 |  (было 8 → полный README с примерами)
| Связанность | 8 |
| Дублирование | 9 |
| Работоспособность | 9 |

- [x] Этап 7: Unit-тесты (45+ кейсов)
- [x] Этап 8: README, interfaces, DECISIONS
```

Чеклист этапов 1-6 (оркестратор, subprocess, Router, ДНК, CommandManager, graceful shutdown) — **пометить N/A**: registers_module это runtime-обёртка, не ProcessModule. Эти этапы не применимы к данному модулю. Добавить ADR-RM-005 в DECISIONS.md с обоснованием.

---

## 5. DECISIONS.md — добавить ADR-RM-005

Файл: `modules/registers_module/DECISIONS.md`

```markdown
## ADR-RM-005: Этапы 1-6 не применимы к registers_module

**Статус:** Принято (2026-04-10)

**Контекст:** registers_module — не ProcessModule, а runtime-библиотека. Этапы 1-6
(оркестратор, subprocess, Router, DNA, CommandManager, graceful shutdown) определены
для модулей, работающих как отдельные процессы или менеджеры внутри процесса.

**Решение:** Пометить этапы 1-6 как N/A. Модуль считается полностью завершённым
после этапов 0, 7, 8.

**Обоснование:** RegistersManager создаётся внутри процесса (обычно GUI) и не имеет
собственного lifecycle, Router-подключения или CommandManager. Интеграция с Router
происходит через send_callback, который предоставляет FrontendRegistersBridge.
```

---

## 6. __init__.py — добавить экспорты утилит

Файл: `modules/registers_module/__init__.py`

Добавить экспорт `build_connection_map_from_registers` — используется в frontend_module:

```python
from .core.dispatch import build_connection_map_from_registers, resolve_dispatch_targets
from .core.routing_map import build_routing_map, get_routing_for_message, send_register_message
from .core.routing_map import ROUTING_NOT_FOUND, PROCESS_UNREACHABLE, MESSAGE_LOST
```

---

## 7. Порядок исполнения

| # | Задача | Файл | Приоритет |
|---|--------|------|-----------|
| 1 | Добавить 15 тестов в test_manager.py | tests/test_manager.py | P0 |
| 2 | Добавить 3 теста в test_dispatch_routing.py | tests/test_dispatch_routing.py | P0 |
| 3 | Добавить 2 теста в test_routing_map.py | tests/test_routing_map.py | P0 |
| 4 | Расширить interfaces.py до 16 методов | interfaces.py | P0 |
| 5 | Переписать README.md с примерами | README.md | P1 |
| 6 | Добавить ADR-RM-005 | DECISIONS.md | P1 |
| 7 | Обновить STATUS.md до 8/8 | STATUS.md | P1 |
| 8 | Расширить __init__.py экспорты | __init__.py | P1 |
| 9 | Обновить MODULES_STATUS.md (registers 8/8) | MODULES_STATUS.md | P2 |

---

## 8. Верификация

```bash
# Из multiprocess_framework/modules:
python -m pytest registers_module/tests/ -v
# Ожидание: 45+ passed, 0 failed

# Полный прогон:
 && python scripts/run_framework_tests.py
# Ожидание: 1699+ passed (не меньше чем было)
```

## 9. Чего НЕ делаем

- **НЕ меняем** core/manager.py, core/dispatch.py, core/routing_map.py — код уже 9/10
- **НЕ добавляем** BaseManager/ObservableMixin наследование — RegistersManager это data-layer, не manager с lifecycle
- **НЕ создаём** адаптеры (adapters/) — интеграция через send_callback достаточна
- **НЕ добавляем** новые зависимости
