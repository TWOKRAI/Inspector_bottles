# Plan 08a: Пост-аудит Message(SchemaBase) — проверка зависимых модулей и закрытие долга

> **Статус:** ПЛАН  
> **Автор плана:** Claude (Opus 4.6), 2026-04-09  
> **Исполнитель:** Cursor Composer Agent v2  
> **Зависит от:** Plan 08 (завершён), Plan 07 (завершён)  
> **Ссылки:** [08_message_schema_base.md](08_message_schema_base.md) · [00_overview.md](00_overview.md) · [ARCHITECTURE.md](../../Inspector_prototype/multiprocess_framework/ARCHITECTURE.md)

---

## 0. Контекст

Plan 08 перевёл `Message` на `SchemaBase`. Полный аудит кодовой базы выявил:

### Найденные проблемы

| # | Проблема | Файл(ы) | Серьёзность |
|---|----------|---------|-------------|
| P1 | `router_manager.send_message()` не существует — в 3 интеграционных тестах вызывается несуществующий метод | `tests/integration/test_comprehensive_integration.py:493,634`, `tests/integration/test_template_application.py:190` | **HIGH** — тесты не могут пройти |
| P2 | Пустые директории `converters/` и `validators/` — остались с `__pycache__` | `message_module/converters/`, `message_module/validators/` | LOW — мусор |
| P3 | ADR-152 не документирует отсутствие `FieldRouting` на Message | `message_module/DECISIONS.md` | LOW — документация |
| P4 | Нет pickle-теста для Message объекта (не dict) | `message_module/tests/test_message.py` | MEDIUM — риск из §4 плана 08 |
| P5 | Нет теста для extra-полей в `to_dict()` | `message_module/tests/test_message.py` | MEDIUM — риск из §4 плана 08 |

### Что проверено и в порядке

| Модуль | Статус | Как использует Message |
|--------|--------|----------------------|
| `base_manager` (#1) | OK | Не импортирует Message |
| `data_schema_module` (#2) | OK | Не импортирует Message (Message зависит от него) |
| `dispatch_module` (#3) | OK | Не импортирует Message |
| `channel_routing_module` (#4) | OK | Не импортирует Message |
| `logger_module` (#5) | OK | Lazy import `Message.create()` + `add_metadata()` — совместимо |
| `config_module` (#6) | OK | Не импортирует Message |
| `router_module` (#9) | OK | `send()` вызывает `_to_dict()`, `receive()` — `from_dict()` — Dict at Boundary соблюдён |
| `process_module` (#11) | OK | `ProcessCommunication.send()` вызывает `message.to_dict()` — Dict at Boundary |
| `multiprocess_prototype` | OK | Использует только `MessageAdapter` — полностью совместим |

**Удалённые API:** `MessageConverter`, `MessageValidator`, `VALID_MESSAGE_FIELDS`, `MESSAGE_FIELD_DEFAULTS`, `apply_type_defaults`, `BaseMessageSchema` (как отдельный класс) — **0 использований** за пределами message_module.

---

## 1. Атомарные шаги

### Шаг 1: Исправить `send_message()` → `send()` в интеграционных тестах (P1)

**КРИТИЧЕСКИЙ.** 3 файла вызывают несуществующий метод `router_manager.send_message()`.

**Файл 1:** `Inspector_prototype/multiprocess_framework/tests/integration/test_comprehensive_integration.py`

Строка 493 — заменить:
```python
# БЫЛО:
result = app.vision_process.router_manager.send_message(message)
# СТАЛО:
result = app.vision_process.router_manager.send(message)
```

Строка 634 — заменить:
```python
# БЫЛО:
result = app.vision_process.router_manager.send_message(broadcast_message)
# СТАЛО:
result = app.vision_process.router_manager.send(broadcast_message)
```

**Файл 2:** `Inspector_prototype/multiprocess_framework/tests/integration/test_template_application.py`

Строка 190 — заменить:
```python
# БЫЛО:
result = app.vision_process.router_manager.send_message(message)
# СТАЛО:
result = app.vision_process.router_manager.send(message)
```

**Верификация:** grep `send_message` в `tests/integration/` — должно остаться только в `test_usage_scenarios.py:91` (имя теста, не вызов метода).

### Шаг 2: Удалить пустые директории converters/ и validators/ (P2)

```bash
# Удалить __pycache__ и пустые директории
rm -rf Inspector_prototype/multiprocess_framework/modules/message_module/converters/
rm -rf Inspector_prototype/multiprocess_framework/modules/message_module/validators/
```

**Проверить:** `__init__.py` модуля не импортирует из этих директорий (уже проверено — нет).

### Шаг 3: Добавить примечание про FieldRouting в ADR-152 (P3)

**Файл:** `Inspector_prototype/multiprocess_framework/modules/message_module/DECISIONS.md`

В конец ADR-152 (после строки «Публичный API ... сохранён.») добавить:

```markdown

**Примечание:** `Message` — единственный `SchemaBase`-наследник без `FieldRouting`. Это осознанное решение: `Message` — value object для IPC-транспорта, а не регистр с маршрутизацией полей. Маршрутизация сообщений определяется полями `targets` / `channel` / `routers` напрямую, без `FieldRouting`.
```

### Шаг 4: Добавить pickle-тесты для Message объекта (P4)

**Файл:** `Inspector_prototype/multiprocess_framework/modules/message_module/tests/test_message.py`

Добавить в класс `TestPickleSafe`:

```python
def test_message_object_pickle_roundtrip(self):
    """Message объект должен быть pickle-safe (Pydantic BaseModel сериализуется)."""
    import pickle
    msg = Message.create(
        MessageType.COMMAND, "sender",
        targets=["target"], command="start", args={"key": "value"}
    )
    msg.add_metadata("test", 123)
    
    pickled = pickle.dumps(msg)
    restored = pickle.loads(pickled)
    
    assert restored.type == msg.type
    assert restored.sender == msg.sender
    assert restored.command == msg.command
    assert restored.args == msg.args
    assert restored.metadata == msg.metadata

def test_message_dict_pickle_roundtrip(self):
    """to_dict() → pickle → unpickle → from_dict() — полный цикл."""
    import pickle
    msg = Message.create(
        MessageType.LOG, "logger_proc",
        targets=["logger"], level="info", message="test log"
    )
    
    d = msg.to_dict()
    restored_dict = pickle.loads(pickle.dumps(d))
    restored_msg = Message.from_dict(restored_dict)
    
    assert restored_msg.type == "log"
    assert restored_msg.message == "test log"
    assert restored_msg.sender == "logger_proc"
```

### Шаг 5: Добавить тесты extra-полей в to_dict() (P5)

**Файл:** `Inspector_prototype/multiprocess_framework/modules/message_module/tests/test_message.py`

Добавить новый класс (или в `TestSchemaBaseIntegration`):

```python
class TestExtraFields:
    """Поведение extra='allow' при сериализации."""

    def test_extra_field_in_constructor(self):
        """Extra-поля через конструктор попадают в model_dump."""
        msg = Message(type="general", sender="s", targets=["t"], custom_field="value")
        dump = msg.model_dump()
        assert "custom_field" in dump

    def test_extra_field_in_to_dict(self):
        """Extra-поля попадают в to_dict() (не фильтруются)."""
        msg = Message(type="general", sender="s", targets=["t"], custom_field="value")
        d = msg.to_dict()
        assert "custom_field" in d

    def test_extra_field_not_in_model_fields(self):
        """Extra-поля не регистрируются как model_fields."""
        assert "custom_field" not in Message.model_fields

    def test_extra_field_survives_from_dict(self):
        """Extra-поля выживают при from_dict() → to_dict() roundtrip."""
        data = {"type": "general", "sender": "s", "targets": ["t"], "custom_field": "value"}
        msg = Message.from_dict(data)
        assert msg.custom_field == "value"  # доступ через атрибут
        d = msg.to_dict()
        assert d.get("custom_field") == "value"
```

### Шаг 6: Обновить README message_module (структура без converters/validators)

**Файл:** `Inspector_prototype/multiprocess_framework/modules/message_module/README.md`

Убрать из дерева каталогов упоминания `converters/` и `validators/` если они ещё есть (после физического удаления в Шаге 2). Проверить что дерево соответствует реальной файловой структуре.

### Шаг 7: Запуск тестов и верификация

```bash
# 1. Тесты message_module
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/message_module/tests -v

# 2. Тесты router_module (зависимый)
python -m pytest multiprocess_framework/modules/router_module/tests -v

# 3. Тесты logger_module (зависимый)
python -m pytest multiprocess_framework/modules/logger_module/tests -v

# 4. Полная валидация фреймворка
python scripts/run_framework_tests.py
python scripts/validate.py

# 5. Grep-проверка: send_message в integration тестах
grep -rn "send_message" multiprocess_framework/tests/integration/ --include="*.py"
# Ожидаем: только test_usage_scenarios.py:91 (имя теста, не вызов)
```

### Шаг 8: Обновить STATUS.md message_module

**Файл:** `Inspector_prototype/multiprocess_framework/modules/message_module/STATUS.md`

Обновить количество тестов (было 112, станет ~120 после добавления тестов в шагах 4-5).
Добавить строку в лог рефакторинга: «Plan 08a: удалены converters/, validators/; исправлены integration тесты send_message→send; добавлены pickle + extra тесты.»

### Шаг 9: Коммит

```bash
git add -A && git commit -m "fix(message_module): post-audit cleanup — Plan 08a

Fixed:
- Integration tests: send_message() → send() (method doesn't exist)
- Removed empty converters/ and validators/ directories

Added:
- Pickle roundtrip tests for Message object and dict form
- Extra fields behavior tests (extra='allow')
- ADR-152 note: Message is only SchemaBase without FieldRouting

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## 2. Что НЕ менять

- Код `Message`, `MessageAdapter`, схем — только тесты и документация
- `router_module`, `logger_module`, `process_module` — аудит подтвердил совместимость
- `multiprocess_prototype` — использует только `MessageAdapter`, полностью совместим
- `00_overview.md` таблица — уже исправлена (16 файлов, 1306 LOC, 112 tests)

## 3. Критерии завершения

- [ ] `grep send_message tests/integration/` — 0 вызовов метода
- [ ] `converters/` и `validators/` директории удалены
- [ ] pickle roundtrip тесты проходят
- [ ] extra-field тесты проходят  
- [ ] ADR-152 дополнен примечанием про FieldRouting
- [ ] `python scripts/run_framework_tests.py` — зелёные
- [ ] STATUS.md обновлён
