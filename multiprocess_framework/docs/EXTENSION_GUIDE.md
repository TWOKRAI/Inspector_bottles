# Руководство по расширению

Как безопасно добавлять код поверх фреймворка без нарушения границ процессов.

---

## 1. Когда что расширять

| Задача | Механизм |
|--------|----------|
| Новый OS-процесс с менеджерами | Подкласс **`ProcessModule`** + запись в схеме запуска |
| Новый менеджер с каналами | Наследник **`ChannelRoutingManager`** + `ChannelRoutingConfig` |
| Локальная диспетчеризация в процессе | **`Dispatcher`** / сценарии `dispatch_module` |
| Новый тип канала Router | Регистрация в **`RouterManager`**, контракт `IChannel` / `IMessageChannel` |

---

## 2. Чеклист нового ProcessModule

1. Класс наследует `ProcessModule`, `class_path` в `proc_dict` указывает на модуль, импортируемый в child.
2. Реализованы **`initialize()`**, **`run()`** (или цикл), **`shutdown()`** по контракту базового класса.
3. Конфиги менеджеров — **dict** в bundle; внутри — Pydantic при необходимости.
4. IPC только через **Router / очереди**, без общих объектов между процессами.
5. Воркеры регистрируются через **`WorkerManager`**, если нужны потоки.
6. Тесты: изоляция через mock SRM / фейковые очереди; см. `modules/process_module/tests/`.
7. **`README.md`** и **`STATUS.md`** по шаблону; при архитектурных решениях — **`DECISIONS.md`** с **ADR-{CODE}-NNN** (см. [ADR_REGISTRY.md](./ADR_REGISTRY.md)).
8. Запуск: `python scripts/validate.py` и `python scripts/run_framework_tests.py` из текущий каталог.

---

## 3. Чеклист нового Manager (BaseManager + ObservableMixin)

1. Наследование от **`BaseManager`**; при наблюдаемости — **`ObservableMixin`** (или CRM для каналов).
2. Публичный контракт только в **`interfaces.py`**.
3. Конфиг: приём **`dict`**, валидация Pydantic внутри модуля.
4. Не добавлять **`sys.path.insert`** в production-коде.

---

## 4. Dict at Boundary

- Между процессами и в публичных IPC API — **только `dict`**.
- `SchemaBase.model_dump()` / `model_validate()` на границе; внутри — типизированные модели.

---

## 5. Паттерны тестирования

- pytest, файлы `test_*.py` в `tests/` модуля.
- Общие фикстуры — `modules/conftest.py` при необходимости.
- Не полагаться на глобальное состояние менеджеров без сброса между тестами.

---

## 6. Документация

- **`README.md`** по [MODULE_README_TEMPLATE.md](./MODULE_README_TEMPLATE.md).
- Изменения контракта — обновить **`interfaces.py`** и тесты; крупные решения — ADR.

---

## См. также

- [QUICK_START.md](./QUICK_START.md)
- [CONFIG_GUIDE.md](./CONFIG_GUIDE.md)
- Навыки репозитория: `add-process-module`, `add-register-schema`
