# Refactoring plan: `message_module` (модуль #7)

> **Статус:** ✅ Завершено (Steps 0–7, 2026-04-09).  
> **Автор плана:** Claude (Haiku 4.5), 2026-04-09.  
> **Исполнитель:** Cursor Composer Agent v2.  
> **Ссылки:** [00_overview.md](./00_overview.md) · [ARCHITECTURE.md](../../Inspector_prototype/multiprocess_framework/ARCHITECTURE.md)

---

## 0. Контекст

`message_module` (#7) — Messaging layer, лист графа зависимостей. Текущий **STATUS.md: Stage 2/8**.

**Шаги 0-2 уже завершены:**
- ✅ Шаг 0: Baseline audit (91 тестов, 2088 LOC)
- ✅ Шаг 1: Pickle-safe тесты, fix `get()` и `validate()` (95 тестов)
- ✅ Шаг 2: Удалили `MessageSchema` dataclass и `MessageFactory` класс (-100 LOC)

**Шаги 3–7 выполнены** (см. коммиты в репозитории).

**Сложность:** ★★★☆☆ — есть кодовые изменения, но структурированные и тестируемые.

---

## 1. Текущее состояние (after Steps 0-2)

- **Файлов:** 18 (было 21)
- **LOC:** ~2000 (было 2088)
- **Тестов:** 3 файла, **95 passed** (было 91)
- **message.py:** 508 LOC (целевое ≤350)
- **Публичный API:** `Message`, `MessageAdapter`, `MessageType`, `Priority`, `LogLevel`, функции `create_message()` и `parse_message()`

### Структура после Step 2

```
message_module/
├── core/message.py           # 508 LOC ⚠️ (главный кандидат на сжатие)
├── adapters/message_adapter.py
├── converters/message_converter.py
├── interfaces.py
├── types/message_types.py    # Удалён MessageSchema dataclass
├── factories/message_factory.py  # Удалён MessageFactory класс
├── schemas/
│   ├── base.py, command.py, log.py
├── validators/message_validator.py
├── utils/utils.py
├── tests/
│   ├── test_message.py (95 passed)
│   ├── test_schemas.py
│   └── test_adapter.py
├── README.md
├── STATUS.md
└── DECISIONS.md             # ПУСТО (создать в Шаге 4)
```

---

## 2. Атомарные шаги (3-7)

### Шаг 3 — Сжать `message.py` (508 → ≤350 LOC) ✅

#### 3a. Упростить lazy `_data` кэш → прямая генерация

**Что менять:** `Inspector_prototype/multiprocess_framework/modules/message_module/core/message.py`

**Действия:**
1. **Удалить `_sync_to_dict()` метод** (примерно строки 94-111)
2. **Удалить поля из `__init__`** (строки ~82-83):
   ```python
   # ЭТИ СТРОКИ УДАЛИТЬ:
   self._data: Optional[Dict[str, Any]] = None
   self._data_synced: bool = False
   ```

3. **Обновить методы доступа** для работы с атрибутами напрямую через `getattr()`:
   
   - **`get(key, default)`** (строка ~428):
     ```python
     def get(self, key: str, default: Any = None) -> Any:
         return getattr(self, key, default)
     ```
   
   - **`keys()`** (строка ~441):
     ```python
     def keys(self):
         return [f for f in VALID_MESSAGE_FIELDS if hasattr(self, f)]
     ```
   
   - **`values()`**:
     ```python
     def values(self):
         return [getattr(self, f, None) for f in VALID_MESSAGE_FIELDS if hasattr(self, f)]
     ```
   
   - **`items()`**:
     ```python
     def items(self):
         return [(f, getattr(self, f, None)) for f in VALID_MESSAGE_FIELDS if hasattr(self, f)]
     ```

4. **Проверить** что `__getitem__`, `__setitem__`, `__contains__` работают корректно (они уже работают через прямой доступ к атрибутам)

**Проверка:**
```bash
pytest Inspector_prototype/multiprocess_framework/modules/message_module/tests/test_message.py::TestDictInterface -v
```

---

#### 3b. Упростить `Message.__init__` (60 строк → ~10 строк)

**Текущий __init__:** строки 31-89 (~60 строк, где каждое поле `self.field = kwargs.get('field', default)`)

**Что делать:**

Заменить на:
```python
def __init__(self, **kwargs):
    """
    Инициализация сообщения.
    
    Прямая инициализация не рекомендуется.
    Используйте Message.create() для создания сообщений.
    """
    # Обязательные поля (явно для clarity)
    self.id: str = kwargs.get('id', generate_message_id(kwargs.get('type', 'general')))
    self.type: str = kwargs.get('type', 'general')
    self.sender: str = kwargs.get('sender', '')
    self.targets: List[str] = kwargs.get('targets', [])
    self.timestamp: float = kwargs.get('timestamp', time.time())
    
    # Применить type-defaults (устанавливает остальные поля)
    apply_type_defaults(self)
    
    # Внутренние поля схемы
    self._schema: Optional[Type['BaseModel']] = kwargs.pop('_schema', None)
    self._schema_info: Optional[Dict[str, str]] = kwargs.pop('_schema_info', None)
    self._schema_validated: bool = kwargs.pop('_schema_validated', False)
```

**Удалить все строки вроде:**
```python
# ❌ УДАЛИТЬ:
self.priority: str = kwargs.get('priority', 'normal')
self.routers: List[str] = kwargs.get('routers', ['internal'])
self.channel: Optional[str] = kwargs.get('channel', None)
# ... и все остальные
```

**Проверить** что `apply_type_defaults()` в `utils.py` корректно устанавливает оставшиеся поля через `setattr()` после первых 5 полей

---

#### 3c. Обновить `MessageConverter.to_dict()` если нужно

**Файл:** `Inspector_prototype/multiprocess_framework/modules/message_module/converters/message_converter.py`

**Проверить:** Метод `to_dict()` должен:
- Читать атрибуты объекта через `getattr()`
- Фильтровать по `VALID_MESSAGE_FIELDS`
- Применять исключения из `MESSAGE_TYPE_EXCLUDE_FIELDS`

**Если изменения не нужны** — оставить как есть.

---

#### 3d. Запустить тесты

```bash
python -m pytest Inspector_prototype/multiprocess_framework/modules/message_module/tests -v
```

**Ожидается:** ✅ 95+ passed (или >95 если добавились новые)

---

#### 3e. Коммит

```bash
git add -A && git commit -m "refactor(message.py): slim to ~300 LOC, remove lazy cache

Step 3 — Compress Message class:

1. Remove lazy _data cache:
   - Delete _sync_to_dict() method
   - Delete _data and _data_synced fields
   - Update get(), keys(), values(), items() to use getattr() directly

2. Simplify __init__ (~60 → ~10 lines):
   - Keep only essential fields
   - Rely on apply_type_defaults() for remaining
   - Remove repetitive kwargs.get() patterns

3. Update dict interface methods to use direct attribute access

Result: message.py 508 → ~300 LOC
Tests: 95+ passed

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"
```

---

### Шаг 4 — Создать DECISIONS.md (ADR-147…151) ✅

**Файл (новый):** `Inspector_prototype/multiprocess_framework/modules/message_module/DECISIONS.md`

**Действие:** Создать файл с содержимым (скопировать из этого плана раздел "Шаг 4" ниже):

```markdown
# message_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-008 Dict at Boundary)

## ADR-147: Message как value object с опциональной Pydantic-схемой

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Нужен IPC-примитив для передачи между процессами. Сообщение должно быть легковесным, но типизированным.  
**Решение:**
- `Message` — value object: нет ID-based equality.
- `schema=None` — нормальный путь. Pydantic схема — опциональное усиление.
- Между процессами: только `msg.to_dict()`.
- `Message.from_dict(raw)` — восстановление на стороне получателя.

**Последствия:** Message остаётся легковесным. Pydantic overhead только где нужна строгая валидация.

---

## ADR-148: MessageAdapter — единственная точка создания в процессе

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `Message.create()` требует повторения `sender=` в каждом вызове.  
**Решение:**
- `MessageAdapter(sender=name)` — один на процесс/менеджер.
- Все методы (`.command()`, `.log()`, `.event()`) имеют фиксированный sender.
- `Message.create()` остаётся для тестов.

**Последствия:** Устраняет повторение sender. Методы явно указывают намерение.

---

## ADR-149: Удаление MessageSchema dataclass

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `MessageSchema` дублировал `BaseMessageSchema` и `VALID_MESSAGE_FIELDS`.  
**Решение:** Удалить dataclass. Единственный источник истины:
- `VALID_MESSAGE_FIELDS` — валидация
- `BaseMessageSchema` — Pydantic
- `Message` атрибуты — runtime state

**Последствия:** При добавлении поля обновляем 2 места вместо 3.

---

## ADR-150: Поле `routers` — маршрутизация внутри процесса

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `routers` field роль неясна.  
**Решение:**
- `targets` — имена процессов (межпроцессная адресация)
- `channel` — имя канала в RouterManager получателя
- `routers` — список RouterManager'ов внутри одного процесса

**Последствия:** Default `["internal"]` — один RouterManager на процесс. LOG исключает из `to_dict()`.

---

## ADR-151: Нет pickle-safe гарантий для Message объекта

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Framework принцип #5 — pickle-safe для Windows spawn.  
**Решение:** `Message` НЕ гарантируется pickle-safe. Только `msg.to_dict()` (dict) пересекает границу.  
**Тест:** `test_message_dict_is_pickle_safe` проверяет dict-форму.

**Последствия:** Developers ВСЕГДА используют `msg.to_dict()` перед IPC отправкой.
```

**Коммит:**

```bash
git add modules/message_module/DECISIONS.md && git commit -m "docs(message_module): add DECISIONS.md (ADR-147…151)

Step 4 — Document architectural decisions:
- ADR-147: Message as lightweight value object
- ADR-148: MessageAdapter single factory
- ADR-149: Remove MessageSchema duplication
- ADR-150: Clarify routers field role
- ADR-151: Dict at Boundary pickle safety

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"
```

---

### Шаг 5 — Дополнить тесты (>90% coverage) ✅

**Файл:** `Inspector_prototype/multiprocess_framework/modules/message_module/tests/test_message.py`

**Добавить в конец файла (перед или после TestPickleSafe):**

```python
class TestClone:
    """Тесты clone() сохранения всех полей."""
    
    def test_clone_general_message(self):
        msg = Message.create(MessageType.GENERAL, sender="test", targets=["t"], content="x")
        cloned = msg.clone()
        assert cloned.to_dict() == msg.to_dict()
        assert cloned.id != msg.id  # новый ID
        assert cloned.timestamp >= msg.timestamp
    
    def test_clone_preserves_schema(self):
        from ..schemas import CommandMessageSchema
        msg = Message.create(
            MessageType.COMMAND, 
            sender="test", 
            targets=["t"], 
            command="start",
            schema=CommandMessageSchema
        )
        cloned = msg.clone()
        assert cloned._schema == msg._schema


class TestValidateWithoutSchema:
    """Тесты validate() без Pydantic схемы."""
    
    def test_validate_general_message(self):
        msg = Message.create(MessageType.GENERAL, sender="test", targets=["t"])
        result = msg.validate()
        assert result is msg  # fluent API
    
    def test_validate_missing_sender_raises(self):
        msg = Message.create(MessageType.GENERAL, sender="", targets=["t"])
        with pytest.raises(MessageValidationError):
            msg.validate()
    
    def test_validate_missing_targets_raises(self):
        msg = Message.create(MessageType.GENERAL, sender="test", targets=[])
        with pytest.raises(MessageValidationError):
            msg.validate()


class TestParseMessage:
    """Тесты parse_message() функции."""
    
    def test_parse_dict(self):
        data = {"type": "general", "sender": "test", "targets": ["t"]}
        msg = parse_message(data)
        assert msg.type == "general"
        assert msg.sender == "test"
    
    def test_parse_json(self):
        import json
        data_dict = {"type": "command", "sender": "test", "targets": ["t"], "command": "start"}
        json_str = json.dumps(data_dict)
        msg = parse_message(json_str)
        assert msg.type == "command"
        assert msg.command == "start"
    
    def test_parse_yaml(self):
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        
        yaml_str = """
type: log
sender: logger
targets: [logger]
level: info
message: test
"""
        msg = parse_message(yaml_str)
        assert msg.type == "log"
        assert msg.message == "test"
```

**Коммит:**

```bash
git add tests/test_message.py && git commit -m "test(message_module): add clone, validate, parse_message tests

Step 5 — Improve test coverage:
- TestClone: verify clone() preserves schema and generates new ID
- TestValidateWithoutSchema: validate without Pydantic schema, error cases
- TestParseMessage: parse_message() with dict, JSON, YAML

Expected coverage: >90%
Tests: 95 → 105+ passed

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"
```

---

### Шаг 6 — Обновить ARCHITECTURE.md и главный DECISIONS.md ✅

#### 6a. Добавить §6.7 в ARCHITECTURE.md

**Файл:** `Inspector_prototype/multiprocess_framework/ARCHITECTURE.md`

**Где:** После раздела про config_module (§6.6), добавить:

```markdown
### 6.7 `message_module` — IPC-примитив

**Роль:** Value object для межпроцессного взаимодействия. Leaf-зависимость (только `data_schema_module`).

**Message** (~300 LOC) — typed IPC container с fluent API и Dict at Boundary.  
**MessageAdapter** (~327 LOC) — контекстная фабрика (один на процесс, фиксированный sender).

```
Message (value object)
    ├── create(type, sender, targets, ...) — основной метод
    ├── to_dict() / from_dict() — Dict at Boundary
    ├── fluent API: set_priority(), set_targets(), set_channel()
    └── optional Pydantic schema через BaseMessageSchema

MessageAdapter(sender=name)
    ├── .command(targets, command, args)
    ├── .log(level, message, module)
    ├── .system(targets, action)
    ├── .broadcast(content)
    ├── .data(targets, data_type, data)
    ├── .request(targets, request_type)
    ├── .response(targets, request_id, result)
    └── .event(event_type, targets, data)
```

Ключевые решения (ADR-147…151):
- **Dict at Boundary:** только `msg.to_dict()` пересекает границу.
- **`schema=None` — нормальный путь,** Pydantic-схема — опциональное усиление.
- **MessageAdapter** — рекомендованный способ в процессах.
- **Поле `routers`:** RouterManager'ы внутри процесса.

📖 [`modules/message_module/README.md`](modules/message_module/README.md) · [`modules/message_module/DECISIONS.md`](modules/message_module/DECISIONS.md)
```

#### 6b. Добавить строку в главный DECISIONS.md

**Файл:** `Inspector_prototype/multiprocess_framework/DECISIONS.md`

**Где:** В разделе "Модульные решения" (после config_module), добавить строку:

```
| `message_module` | [`modules/message_module/DECISIONS.md`](modules/message_module/DECISIONS.md) | Messaging | ADR-147…151 (value object, MessageAdapter, no pickle guarantee, routers field) |
```

**Коммит:**

```bash
git add ARCHITECTURE.md DECISIONS.md && git commit -m "docs: add message_module to ARCHITECTURE.md §6.7 and main DECISIONS.md

Step 6 — Update framework documentation:
- ARCHITECTURE.md §6.7: Message and MessageAdapter roles
- Main DECISIONS.md: add message_module reference with ADR links
- Clarify Dict at Boundary principle

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"
```

---

### Шаг 7 — Финальная валидация ✅

**Команды для выполнения:**

```bash
# 1. Запустить тесты message_module
python -m pytest Inspector_prototype/multiprocess_framework/modules/message_module/tests -v

# 2. Проверить зависимые модули (router_module)
python -m pytest Inspector_prototype/multiprocess_framework/modules/router_module/tests -v

# 3. Запустить полную валидацию фреймворка
python Inspector_prototype/scripts/validate.py

# 4. Запустить все тесты фреймворка
python Inspector_prototype/scripts/run_framework_tests.py

# 5. Подсчитать финальные метрики
find Inspector_prototype/multiprocess_framework/modules/message_module -name "*.py" \
  -not -path "*/tests/*" -not -path "*__pycache__*" | xargs wc -l | sort -rn | head -10
```

**Ожидаемые результаты:**
- ✅ message_module тесты: 105+ passed (было 95)
- ✅ router_module тесты: все зелёные
- ✅ validate.py: зелёный
- ✅ message.py: ≤350 LOC (было 508)
- ✅ Общая LOC: ~1500 (было 2088)

#### 7a. Обновить метрики в 00_overview.md

**Файл:** `plans/refactoring/00_overview.md`

**Найти:** Таблица метрик (примерно строка 84-92), строка #7 (message_module):

**Заменить:**
```
| 7  | `message_module`             |  21   |  2088  |   3   |  TODO  | TODO | — | — | — |
```

**На:**
```
| 7  | `message_module`             |  18   |  1500  |   3   |  TODO  | TODO | 18 | 1500 | 3 (105+ passed) |
```

#### 7b. Финальный коммит

```bash
git add plans/refactoring/00_overview.md && git commit -m "refactor(message_module): final validation and metrics update (step 7)

Step 7 — Final validation:

Test results:
✅ message_module: 105+ passed
✅ router_module: green
✅ validate.py: green
✅ All framework tests: green

Metrics after refactoring:
- Files: 21 → 18
- LOC: 2088 → 1500
- message.py: 508 → 300 LOC
- Coverage: 75% → >90%

Updated 00_overview.md row #7 with final metrics.
Module #7 refactoring complete.

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"
```

---

## 3. Что НЕ делать

1. **НЕ** менять публичный API `Message.create()` — `schema=None` остаётся нормальным
2. **НЕ** менять сигнатуру `MessageAdapter` — frontend_module зависит
3. **НЕ** удалять `MessageType`, `Priority`, `LogLevel` enums
4. **НЕ** менять порядок аргументов в `Message.create()`
5. **НЕ** добавлять обязательный `schema=`
6. **НЕ** трогать `MessageAdapter` (кроме тестов)
7. **НЕ** делать router-интеграцию в этом плане (это Шаги 3-4 STATUS.md, для модуля #9)

---

## 4. Кросс-модульные изменения

| Модуль | Файл | Что меняется |
|--------|------|-------------|
| **message_module** | `core/message.py` | Удалить lazy cache, упростить __init__ |
| **message_module** | `DECISIONS.md` | СОЗДАТЬ (ADR-147…151) |
| **message_module** | `tests/test_message.py` | Добавить TestClone, TestValidate, TestParse |
| **multiprocess_framework** | `ARCHITECTURE.md` | Добавить §6.7 |
| **multiprocess_framework** | `DECISIONS.md` | Добавить строку про message_module |
| **plans/refactoring** | `00_overview.md` | Обновить метрики строки #7 |

**Нет** изменений в router_module, process_module, frontend_module.

---

## 5. Definition of Done (модуль #7)

- [x] Шаг 3: message.py сжат до ≤350 LOC, lazy cache удалён, __init__ упрощён. Тесты passed.
- [x] Шаг 4: DECISIONS.md создан (ADR-147…151), синтаксис correct.
- [x] Шаг 5: Тесты дополнены (TestClone, TestValidate, TestParse), coverage ~94% по пакету, 103 passed.
- [x] Шаг 6: ARCHITECTURE.md §6.7 добавлен, главный DECISIONS.md обновлён.
- [x] Шаг 7: Все проверки passed, метрики обновлены в 00_overview.md.
- [ ] Все коммиты сделаны с правильным форматом (делает пользователь).

---

## 6. Целевые метрики

| Метрика | До | После (цель) | После (факт) |
|---------|-----|--------------|--------------|
| Файлов (без tests) | 21 | 18 | — |
| LOC | 2088 | 1500 | — |
| `message.py` | 508 | ≤350 | — |
| Тестов (passed) | 95 | 105+ | — |
| Покрытие | ~75% | >90% | — |

---

## 7. Заметки

- **Шаги 0-2 завершены** на момент создания этого плана (коммиты: 0ff3a87, 79ecc63)
- **apply_type_defaults() функция** должна корректно устанавливать оставшиеся поля после 5 основных
- **MessageConverter.to_dict()** может оставаться как есть (должен уже работать с атрибутами)
- **ADR номера:** ADR-147…151 (config_module занял 143…146)
- **Следующий модуль:** #8 shared_resources_module (после message_module)
