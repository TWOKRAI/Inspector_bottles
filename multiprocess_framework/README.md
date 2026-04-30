# Multiprocess Framework

**Конструктор многопроцессных приложений на Python.**

Скрывает многопроцессорную «боль» Python (spawn/fork, pickle-safe сериализацию, lifecycle, IPC, маршрутизацию, наблюдаемость) и даёт **19 готовых модулей-«деталей»**, которые собираются друг в друга через явные интерфейсы.

**Версия:** 2.0 · **Python:** 3.11+ · **Статус:** Production · **License:** MIT

---

## Start Here

| Кто | Куда смотреть |
|-----|---------------|
| **Новый разработчик / агент** | [`SPEC.md`](./SPEC.md) → [`docs/MODULES_OVERVIEW.md`](./docs/MODULES_OVERVIEW.md) → `modules/<X>/README.md` |
| **Архитектор** | [`SPEC.md`](./SPEC.md) + [`docs/MODULE_CONTRACTS.md`](./docs/MODULE_CONTRACTS.md) + [`DECISIONS.md`](./DECISIONS.md) |
| **Расширяющий фреймворк** | [`docs/DESIGN_RULES.md`](./docs/DESIGN_RULES.md) + [`docs/EXTENSION_GUIDE.md`](./docs/EXTENSION_GUIDE.md) + [`docs/MODULE_README_TEMPLATE.md`](./docs/MODULE_README_TEMPLATE.md) |
| **Тестировщик** | [`PROBLEMS.md`](./PROBLEMS.md) + раздел [Testing](#testing) ниже |

---

## Полный индекс

См. [`DOCUMENTATION_INDEX.md`](./DOCUMENTATION_INDEX.md).

---

## Quick example

```python
from multiprocess_framework import (
    SystemLauncher, ProcessModule, ThreadConfig,
)


class HelloProcess(ProcessModule):
    def initialize(self) -> bool:
        self.create_worker(
            "ticker", self._tick, ThreadConfig(), auto_start=True
        )
        return True

    def _tick(self, stop_event, pause_event):
        n = 0
        while not stop_event.is_set():
            self.log_info(f"tick {n}")
            n += 1
            stop_event.wait(timeout=1.0)

    def shutdown(self) -> bool:
        return True


if __name__ == "__main__":
    SystemLauncher(processes=[
        ("hello", {"class_path": "my_app.HelloProcess", "config": {}}),
    ]).run()
```

---

## Установка

Фреймворк живёт внутри текущей директории. Устанавливается как editable-пакет вместе с проектом:

```bash

uv sync --group dev
```

После этого:

```python
from multiprocess_framework import SystemLauncher                           # каноничный путь
from multiprocess_framework.modules.data_schema_module import SchemaBase    # тоже OK
```

`from data_schema_module import ...` (без префикса) — **запрещён** ([`docs/DESIGN_RULES.md#R-1`](./docs/DESIGN_RULES.md)).

---

## Testing <a id="testing"></a>

```bash
# Полный прогон unit-тестов фреймворка:
python scripts/run_framework_tests.py

# Конкретный модуль:
python scripts/run_framework_tests.py base_manager/tests -v
```

**Ожидаемый результат:** 1 877 passed / 30 skipped / 2 known-failing (см. [`PROBLEMS.md`](./PROBLEMS.md)).

---

## Структура

```
multiprocess_framework/
├── SPEC.md                 ← главное ТЗ
├── README.md               ← этот файл
├── DOCUMENTATION_INDEX.md
├── MODULES_STATUS.md
├── PROBLEMS.md
├── DECISIONS.md            ← глобальные ADR
├── STRUCTURE.md
├── __init__.py             ← публичный фасад (49 экспортов)
├── modules/                ← 19 модулей
│   ├── base_manager/
│   ├── data_schema_module/
│   ├── ...
│   └── frontend_module/
└── docs/
    ├── README.md
    ├── MODULES_OVERVIEW.md      ← навигатор по модулям
    ├── MODULE_CONTRACTS.md      ← контракты
    ├── INTERACTION_FLOWS.md     ← цепочки вызовов
    ├── DESIGN_RULES.md          ← обязательные правила
    ├── GLOSSARY.md
    ├── ROUTING_GLOSSARY.md
    ├── DIAGRAMS.md
    ├── QUICK_START.md, TROUBLESHOOTING.md, EXTENSION_GUIDE.md, ...
    ├── ADR_REGISTRY.md
    └── archive/                  ← устаревшие документы
```

Подробное дерево — [`STRUCTURE.md`](./STRUCTURE.md).

---

## Принципы (коротко)

1. **Dict at Boundary** — между процессами только `dict`.
2. **Регистры — единый источник истины** — `SchemaBase` + `FieldMeta` + `FieldRouting` декларируют поле один раз.
3. **Каноничные импорты** — внутри фреймворка только `from multiprocess_framework.modules.<X> import Y`.
4. **`BaseManager` + `ObservableMixin`** — каждый менеджер.
5. **Канал ≠ имя процесса** — двухуровневая маршрутизация.
6. **Graceful shutdown без `sys.exit()`** — только `stop_event.set()`.

Полный список — [`docs/DESIGN_RULES.md`](./docs/DESIGN_RULES.md).
