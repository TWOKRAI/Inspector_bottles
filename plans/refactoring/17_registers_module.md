# Plan 17 — `registers_module` Refactoring

> **Автор плана:** Claude (Opus 4.6), 2026-04-10.  
> **Исполнитель:** Cursor Composer Agent v2.  
> **Ревьюер:** Claude (Opus 4.6) — ревью после исполнения.  
> **Ссылки:** [00_overview.md](./00_overview.md) · [ARCHITECTURE.md](../../multiprocess_framework/ARCHITECTURE.md) · [data_schema_module STATUS](../../multiprocess_framework/modules/data_schema_module/STATUS.md)

---

## 0. Резюме

`registers_module` — runtime-контейнер именованных регистров (SchemaBase-экземпляров) с подписками на изменения и dispatch-доставкой в бэкенд-процессы. Сейчас **6 файлов, ~556 LOC, 1 test-файл (4 теста)**.

**Главная проблема:** модуль дублирует логику, уже реализованную в `data_schema_module`:
- `RegistersManager.get_field_metadata()` вручную парсит `json_schema_extra` → `SchemaMixin.get_field_metadata()` делает то же самое, но корректнее и с кэшированием.
- `RegistersManager.validate_field_value()` проверяет min/max/access → `SchemaMixin.validate_field()` делает то же + FieldMeta-aware.
- `RegistersManager.model_dump_all()` / `model_validate_all()` → `RegistersContainer` в `data_schema_module` уже это реализует + diff/snapshot/save/load.

**Цель рефакторинга:** убрать дублирование, делегировать хранение и метаданные в `data_schema_module`, оставить в `registers_module` только уникальную ценность — **подписки (pub/sub)** и **dispatch routing**.

---

## 1. Анализ текущего состояния

### 1.1 Файловая структура

```
registers_module/
├── README.md
├── STATUS.md
├── __init__.py              # Публичный API
├── interfaces.py            # IRegistersManager, IRegistersConverter
├── core/
│   ├── __init__.py
│   ├── manager.py           # RegistersManager (300 LOC) — центральный класс
│   ├── connection_map_builder.py  # build_connection_map_from_registers (35 LOC)
│   └── routing_map.py       # build_routing_map, send_register_message (126 LOC)
└── tests/
    ├── __init__.py
    └── test_dispatch_routing.py   # 4 теста (dispatch priority, fan-out, fallback)
```

### 1.2 Дублирование с `data_schema_module`

| Метод RegistersManager | Аналог в data_schema_module | Разница |
|---|---|---|
| `get_field_metadata()` (220–258) | `SchemaMixin.get_field_metadata()` | RM парсит raw `json_schema_extra`; SchemaMixin использует `FieldMeta` с кэшем |
| `validate_field_value()` (260–279) | `SchemaMixin.validate_field()` | RM — ручная проверка min/max; SchemaMixin — полная проверка через FieldMeta |
| `model_dump_all()` / `model_validate_all()` | `RegistersContainer.model_dump_all()` / `model_validate_all()` | Идентичная логика |
| `register_names()`, `get_register()` | `RegistersContainer.register_names()`, `get_register()` | Идентично |

### 1.3 Что уникально в RegistersManager (НЕ дублируется)

1. **Observer pattern** — `subscribe()`, `unsubscribe()`, `subscribe_all()`, `unsubscribe_all()`, `notify_field_changed()`, `_notify_observers()`
2. **Dispatch routing** — `set_field_value()` + `_resolve_dispatch_targets()` (4-уровневый приоритет: FieldMeta.routing.process_targets → get_field_metadata → register_dispatch → connection_map)
3. **Backend connection** — `set_connection()`, `set_send_callback()`
4. **routing_map.py** — `build_routing_map()`, `send_register_message()` с error_callback

### 1.4 Мёртвый код

- **`IRegistersConverter`** — протокол без единой реализации. Нигде не импортируется кроме `__init__.py`.

### 1.5 Проблемы

| # | Проблема | Серьёзность |
|---|----------|-------------|
| P1 | Дублирование get_field_metadata / validate — расхождение с SchemaMixin | Высокая |
| P2 | Silent `except: pass` в observers и send_callback (строки 130–135, 194–210) | Средняя |
| P3 | Нет логирования (трассировка field changes невозможна) | Средняя |
| P4 | IRegistersConverter — мёртвый протокол | Низкая |
| P5 | Тестовое покрытие 4/~20 нужных тестов | Средняя |
| P6 | Нет DECISIONS.md | Низкая |

---

## 2. Целевая архитектура

### 2.1 Принцип

```
data_schema_module.RegistersContainer    ← хранение, метаданные, сериализация
        ▲ (композиция)
registers_module.RegistersManager        ← подписки, dispatch, send_callback
```

`RegistersManager` **композирует** `RegistersContainer` (не наследует) и **делегирует** ему хранение и доступ к метаданным. Уникальная логика (pub/sub + dispatch) остаётся в `RegistersManager`.

### 2.2 Целевая файловая структура

```
registers_module/
├── README.md                # Обновлённый
├── STATUS.md                # Обновлённый
├── DECISIONS.md             # Новый — ADR-RM-001..004
├── __init__.py              # Обновлённый публичный API
├── interfaces.py            # IRegistersManager (обновлённый), IRegistersConverter удалён
├── core/
│   ├── __init__.py
│   ├── manager.py           # RegistersManager с композицией RegistersContainer (~200 LOC)
│   ├── dispatch.py          # _resolve_dispatch_targets + build_connection_map (бывший connection_map_builder)
│   └── routing_map.py       # Без изменений (send_register_message, build_routing_map)
└── tests/
    ├── __init__.py
    ├── test_dispatch_routing.py    # Существующие (обновить импорты)
    ├── test_manager.py             # Новый — subscribe, set_field_value, model_dump_all delegation
    └── test_routing_map.py         # Новый — build_routing_map, send_register_message
```

### 2.3 Целевой API (изменения)

```python
class RegistersManager:
    """Runtime-менеджер с подписками и dispatch."""

    def __init__(
        self,
        registers: Optional[Dict[str, Any]] = None,
        connection_map: Optional[Dict[str, str]] = None,
        send_callback: Optional[Callable] = None,
    ):
        # Делегирование хранения
        self._container = RegistersContainer(registers or {})
        self._connection_map = dict(connection_map) if connection_map else {}
        self._send_callback = send_callback
        self._global_observers: List[Callable] = []
        self._field_observers: Dict[Tuple[str, str], List[Callable]] = defaultdict(list)

    # --- Делегация в RegistersContainer ---
    def get_register(self, name): return self._container.get_register(name)
    def set_register(self, name, inst): self._container[name] = inst
    def register_names(self): return self._container.register_names()
    def model_dump_all(self): return self._container.model_dump_all()
    def model_validate_all(self, data, strict=False): self._container.model_validate_all(data, strict=strict)

    # --- Делегация метаданных в SchemaMixin (через регистр) ---
    def get_field_metadata(self, register_name, field_name, **kw):
        return self._container.get_field_metadata(register_name, field_name, **kw)

    def validate_field_value(self, register_name, field_name, value, current_access_level=0):
        reg = self._container.get_register(register_name)
        if reg is None:
            return False, f"Регистр '{register_name}' не найден"
        return reg.validate_field(field_name, value, access_level=current_access_level)

    # --- Уникальная логика (без изменений) ---
    # subscribe(), unsubscribe(), subscribe_all(), unsubscribe_all()
    # set_field_value() + _resolve_dispatch_targets()
    # set_connection(), set_send_callback()
```

---

## 3. Фазы рефакторинга

### Фаза 1: Подготовка (без изменения поведения)

| Шаг | Действие | Файл |
|-----|----------|------|
| 1.1 | Создать `DECISIONS.md` с ADR-RM-001..004 (см. §4) | `DECISIONS.md` |
| 1.2 | Объединить `connection_map_builder.py` в новый `core/dispatch.py` | `core/dispatch.py` |
| 1.3 | Удалить `IRegistersConverter` из `interfaces.py` и `__init__.py` | `interfaces.py`, `__init__.py` |
| 1.4 | Обновить `IRegistersManager` — убрать `model_dump_all`/`model_validate_all` из протокола (они идут через container) | `interfaces.py` |

**Проверка:** существующие 4 теста проходят.

### Фаза 2: Композиция RegistersContainer

| Шаг | Действие | Файл |
|-----|----------|------|
| 2.1 | Добавить `from data_schema_module.container import RegistersContainer` в `manager.py` | `core/manager.py` |
| 2.2 | Заменить `self._registers: Dict` на `self._container: RegistersContainer` | `core/manager.py` |
| 2.3 | Делегировать `get_register`, `set_register`, `register_names`, `model_dump_all`, `model_validate_all` в `self._container` | `core/manager.py` |
| 2.4 | **Удалить** `get_field_metadata()` (220–258) — делегировать в `self._container.get_field_metadata()` | `core/manager.py` |
| 2.5 | **Заменить** `validate_field_value()` — делегировать в `reg.validate_field()` (SchemaMixin) | `core/manager.py` |
| 2.6 | Обновить `_resolve_dispatch_targets` — использовать `reg.get_field_meta()` напрямую (уже делает) | `core/manager.py` |

**Ожидаемый результат:** manager.py ~200 LOC (было ~300). Вся логика metadata/validation — из `data_schema_module`.

**Проверка:** существующие 4 теста + ручная проверка delegate-методов.

### Фаза 3: Улучшение observer pattern

| Шаг | Действие | Файл |
|-----|----------|------|
| 3.1 | Заменить `except: pass` в `_notify_observers` на `except Exception as e: logger.warning(...)` | `core/manager.py` |
| 3.2 | Заменить `except: pass` в `set_field_value` send_callback на `except Exception as e: logger.error(...)` | `core/manager.py` |
| 3.3 | Добавить `import logging; logger = logging.getLogger(__name__)` | `core/manager.py` |
| 3.4 | Добавить debug-лог в `set_field_value` при успешном изменении | `core/manager.py` |

### Фаза 4: Тесты

| Шаг | Действие | Файл |
|-----|----------|------|
| 4.1 | Обновить `test_dispatch_routing.py` — исправить импорты (dispatch.py вместо connection_map_builder) | `tests/test_dispatch_routing.py` |
| 4.2 | Создать `test_manager.py`: тесты RegistersManager | `tests/test_manager.py` |
|     | — `test_get_register_existing` | |
|     | — `test_get_register_missing_returns_none` | |
|     | — `test_set_register_dynamic` | |
|     | — `test_register_names` | |
|     | — `test_model_dump_all_delegates_to_container` | |
|     | — `test_model_validate_all_delegates_to_container` | |
|     | — `test_get_field_metadata_delegates` | |
|     | — `test_validate_field_value_delegates` | |
|     | — `test_subscribe_and_notify` | |
|     | — `test_unsubscribe` | |
|     | — `test_subscribe_all_global` | |
|     | — `test_set_field_value_validates_and_notifies` | |
|     | — `test_set_field_value_invalid_returns_error` | |
|     | — `test_set_field_value_calls_send_callback` | |
|     | — `test_set_field_value_readonly_rejected` | |
| 4.3 | Создать `test_routing_map.py`: тесты routing_map.py | `tests/test_routing_map.py` |
|     | — `test_build_routing_map_with_routing_fields` | |
|     | — `test_build_routing_map_no_routing_returns_empty` | |
|     | — `test_get_routing_for_message` | |
|     | — `test_send_register_message_success` | |
|     | — `test_send_register_message_routing_not_found` | |
|     | — `test_send_register_message_process_unreachable` | |

**Проверка:** `python -m pytest tests/ -v` — все тесты проходят.

### Фаза 5: Документация и финализация

| Шаг | Действие | Файл |
|-----|----------|------|
| 5.1 | Обновить `README.md` — архитектура с композицией, примеры | `README.md` |
| 5.2 | Обновить `STATUS.md` — этапы, оценки, история | `STATUS.md` |
| 5.3 | Обновить `__init__.py` — убрать `build_connection_map_from_registers` из экспорта (теперь в dispatch.py, реэкспорт для обратной совместимости) | `__init__.py` |
| 5.4 | Обновить §6.17 в `ARCHITECTURE.md` (или добавить, если нет) | `ARCHITECTURE.md` |
| 5.5 | Добавить ссылку на `DECISIONS.md` в главный `multiprocess_framework/DECISIONS.md` | `DECISIONS.md` |

---

## 4. ADR (Architectural Decision Records)

### ADR-RM-001: Композиция RegistersContainer вместо дублирования

**Контекст:** RegistersManager дублирует хранение (Dict[str, Any]), метаданные (get_field_metadata парсит json_schema_extra вручную) и сериализацию (model_dump_all/model_validate_all) — всё это уже реализовано в data_schema_module.RegistersContainer.

**Решение:** RegistersManager **композирует** RegistersContainer для хранения и делегирует ему get_register, register_names, model_dump_all, model_validate_all, get_field_metadata. Уникальная логика (pub/sub, dispatch) остаётся в RegistersManager.

**Почему не наследование:** RegistersContainer — data-oriented (diff, snapshot, save/load). RegistersManager — runtime-oriented (подписки, dispatch, send_callback). Наследование создаёт ложную иерархию "is-a"; композиция чётко разделяет ответственность.

**Следствие:** manager.py сокращается с ~300 до ~200 LOC. Метаданные и валидация берутся из SchemaMixin (с кэшированием), а не парсятся заново при каждом вызове.

### ADR-RM-002: Удаление IRegistersConverter

**Контекст:** Протокол `IRegistersConverter` (to_dict, from_dict, to_flat_dict, from_flat_dict) объявлен в interfaces.py, но не имеет ни одной реализации и нигде не импортируется.

**Решение:** Удалить. Если понадобится конвертация — RegistersContainer уже поддерживает to_dict/from_dict/to_json/to_yaml.

### ADR-RM-003: Объединение dispatch-логики в core/dispatch.py

**Контекст:** `build_connection_map_from_registers()` в отдельном файле `connection_map_builder.py` (35 LOC) тематически связан с `_resolve_dispatch_targets()` в manager.py.

**Решение:** Вынести `build_connection_map_from_registers()` и `_resolve_dispatch_targets()` (как публичную функцию `resolve_dispatch_targets()`) в `core/dispatch.py`. RegistersManager вызывает функцию из dispatch.py.

**Почему:** Single Responsibility — manager.py = контейнер + подписки; dispatch.py = вся логика определения целей доставки. Упрощает тестирование dispatch отдельно.

### ADR-RM-004: Логирование вместо silent except pass

**Контекст:** Ошибки в observer callbacks и send_callback проглатываются `except: pass`. Это маскирует баги подписчиков и делает невозможной трассировку проблем доставки.

**Решение:** Использовать `logging.getLogger(__name__)`. Observer exceptions → `logger.warning()`. send_callback exceptions → `logger.error()`. Успешные set_field_value → `logger.debug()`.

---

## 5. Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| frontend_module использует raw dict из get_field_metadata (формат может отличаться) | Средняя | SchemaMixin.get_field_metadata() возвращает тот же формат dict с теми же ключами. Проверить совместимость перед Фазой 2 |
| RegistersContainer.__setitem__ отличается от set_register | Низкая | Делегировать через обёртку |
| Тесты в frontend_module мокают RegistersManager | Средняя | Протокол IRegistersManager не меняет сигнатуры — моки останутся валидными |
| _resolve_dispatch_targets использует get_field_metadata() — при делегации формат routing может измениться | Средняя | В Фазе 2.6 убедиться, что SchemaMixin возвращает routing dict с ключом process_targets |

### Митигация для routing-формата (критично)

Текущий `get_field_metadata()` в manager.py возвращает:
```python
{"routing": dict(extra["routing"])}  # raw dict из json_schema_extra
```

`SchemaMixin.get_field_metadata()` возвращает:
```python
{"routing": {"channel": "...", "process_targets": [...]}}  # из FieldRouting
```

**Действие:** в Фазе 2.4 проверить, что `_resolve_dispatch_targets` работает с обоими форматами, и при необходимости адаптировать. FieldRouting хранит данные как dict-compatible (у FieldRouting есть `__getitem__`/`.get()`), поэтому проблем не ожидается.

---

## 6. Метрики до/после

| Метрика | До | После (цель) |
|---------|-----|---------------|
| Файлы .py (без tests) | 5 | 5 |
| LOC (core) | ~460 | ~300 |
| Тест-файлы | 1 | 3 |
| Тесты | 4 | ~25 |
| Дублирование с data_schema | ~100 LOC | 0 |
| DECISIONS.md | нет | ADR-RM-001..004 |

---

## 7. Зависимости и порядок

```
data_schema_module (DONE, v2.0)
        │
        ▼
registers_module (этот план, #17)
        │
        ├──► frontend_module (#19, после)
        └──► prototype интеграция (после)
```

**Блокеры:** нет. `data_schema_module` полностью готов (v2.0, 2026-04-09).

---

## 8. Чеклист исполнителя

- [ ] **Фаза 1:** DECISIONS.md, dispatch.py, удалить IRegistersConverter → тесты проходят
- [ ] **Фаза 2:** Композиция RegistersContainer, делегация методов → тесты проходят
- [ ] **Фаза 3:** Logging вместо silent except → тесты проходят
- [ ] **Фаза 4:** Новые тесты (test_manager.py, test_routing_map.py) → все ~25 тестов проходят
- [ ] **Фаза 5:** README, STATUS, ARCHITECTURE, главный DECISIONS.md → документация актуальна
- [ ] **Финал:** `python scripts/run_framework_tests.py` — registers_module тесты зелёные
