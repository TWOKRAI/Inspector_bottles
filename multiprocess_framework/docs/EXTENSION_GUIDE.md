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

## 3a. Разъёмы наблюдаемости (обязательный пункт для любого нового кода)

Подробный рецепт — [`observability/NEW_MODULE_RECIPE.md`](./observability/NEW_MODULE_RECIPE.md).
Здесь — минимум, который проверяется:

1. **Писать только через разъём.** Модуль/менеджер — `self._log_*`, `self._track_error`,
   `self._record_metric`; плагин — `ctx.log_*`, `ctx.health.report_error`, `ctx.write_document`.
   Голый `logging.getLogger` запрещён и ловится стражем по AST
   (`logger_module/tests/test_std_logger_guard.py`): у stdlib-root в живых процессах нет
   хендлеров, `INFO`/`DEBUG` теряются всегда, под `pythonw` — вообще всё. Нужен stdlib-стиль —
   `get_std_logger(__name__)`, это **вид** над тем же писателем.
2. **Объявить имя источника рядом с константой** в `interfaces.py`:
   `LOG_SOURCE = declare_log_source("multiprocess_framework.modules.<модуль>", owner=__name__)`.
   Имя **точечное**, не ярлык: правило по префиксу работает на поддереве, плоское имя — лист.
3. **`_log_debug` на пути каждой записи — отложенным сообщением** (`lambda: f"…"`): f-строка
   собирается до гейта и никаким порогом не снимается.
4. **`ctx.log_error` ≠ `ctx.health.report_error`** (ADR-PM-030): первое — диагностическая строка в
   плоскость логов, второе — **инцидент** в плоскость ошибок + счётчик health. Выбор осознанный,
   не по вкусу.
5. **Свой тип приёмника — `register_sink_factory`**, свой уровень ошибок — `severity_routes`,
   своя метрика телеметрии — `declare_metric`. Правок во фреймворке при этом ноль; если правка
   понадобилась — сначала проверь, не пытаешься ли ты обойти реестр.
6. **Доказать доставку прогоном, а не тестом:** `observability.sink.tail` на кольце `memory` +
   `introspect.observability` (имя в `declared_sources` и в `sources`, приёмник не в `idle_sinks`,
   `channel_written_records` растёт).

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
- [OBSERVABILITY_MAP.md](./OBSERVABILITY_MAP.md) и четыре справочника в [`observability/`](./observability/CONNECTORS.md)
- Навыки репозитория: `add-process-module`, `add-register-schema`
