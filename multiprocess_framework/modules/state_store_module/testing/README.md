# testing/ — Утилиты для тестирования state_store_module

## Назначение

Этот подпакет предоставляет публичные testing-helpers — mock-реализации для написания unit-тестов прикладного кода, интегрирующегося с `state_store_module`.

**Принцип:** фреймворк предоставляет testing-утилиты как часть публичного API (ADR-SS-010).

---

## InMemoryRouter

Mock-реализация `IRouter`. Хранит зарегистрированные handlers и доставляет сообщения синхронно в том же процессе — без реального IPC/multiprocessing.

### Пример: StateProxy с InMemoryRouter

```python
from multiprocess_framework.modules.state_store_module.testing import InMemoryRouter
from multiprocess_framework.modules.state_store_module.interfaces import IRouter

# InMemoryRouter реализует IRouter Protocol
router = InMemoryRouter()
assert isinstance(router, IRouter)

# Использование с StateProxy и StateStoreManager (доступны после задачи 2.1.3)
# from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager
# from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy
#
# manager = StateStoreManager(router=router, initial_state={"some": {"path": 0}})
# manager.initialize()
#
# proxy = StateProxy("test_proc", router=router)
# router.register_message_handler("state.changed", proxy.on_state_changed)
#
# proxy.set("some.path", 42)
# assert proxy.get("some.path") == 42
```

### Пример: проверка отправленных сообщений

```python
router = InMemoryRouter()

# ... настройка manager и proxy ...

# Проверить что конкретная команда была отправлена
set_msgs = [m for m in router.sent_messages if m.get("command") == "state.set"]
assert len(set_msgs) == 1
assert set_msgs[0]["data"]["path"] == "some.path"

# Очистить историю между тестами
router.clear()
assert len(router.sent_messages) == 0
```

### Пример: регистрация и вызов handler-а

```python
router = InMemoryRouter()

received = []
router.register_message_handler("my.command", lambda msg: received.append(msg))
router.send_async({"command": "my.command", "data": {"key": "value"}})

assert len(received) == 1
assert received[0]["data"]["key"] == "value"
```

---

## Отличие от MockBus в integration-тестах прототипа

`InMemoryRouter` — упрощённая публичная версия:
- Один handler на ключ (повторная регистрация перезаписывает)
- Нет таргетной доставки state.changed по process_name

`MockBus` в `tests/integration/test_state_store_integration.py`:
- Несколько handlers на один ключ (нужно для нескольких StateProxy)
- Таргетная доставка state.changed (только целевым процессам)

Для сложных интеграционных тестов с несколькими StateProxy — используй `MockBus` напрямую из integration-тестов или расширь `InMemoryRouter`.
