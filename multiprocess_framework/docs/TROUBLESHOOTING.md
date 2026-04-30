# Устранение неполадок (FAQ)

Краткие ответы для разработчиков и тестировщиков. Детали — в [FRAMEWORK_OVERVIEW.md](./FRAMEWORK_OVERVIEW.md), [CONFIG_GUIDE.md](./CONFIG_GUIDE.md), [PROBLEMS.md](../PROBLEMS.md).

---

## Процесс не стартует

| Симптом | Что проверить |
|---------|----------------|
| `ModuleNotFoundError` при spawn | **`class_path` / `class`** указывает на импортируемый модуль в **том же PYTHONPATH**, что и у child (Windows spawn). |
| Ошибка pickle | В bundle нет непickle-safe объектов; используйте dict и примитивы (см. ADR-008). |
| Пустые очереди | `SharedResourcesManager.register_process` вызван до старта; ключи очередей совпадают с контрактом `proc_dict`. |

---

## Сообщения не доставляются

- Разделяйте **имя процесса** (`targets`) и **имя канала Router** (`FieldRouting.channel`). См. [ROUTING_GLOSSARY.md](./ROUTING_GLOSSARY.md).
- Проверьте **`connection_map`** / **`routing_map`** в `registers_module` для `register_update`.

---

## Graceful shutdown зависает

- Уменьшите нагрузку на воркеры; проверьте обработку **stop_event** в циклах.
- Таймауты `SystemLauncher.stop_timeout` и каскад остановки в `process_manager_module` (**ADR-PMM-*** ).

---

## SharedMemory на macOS / разные ОС

- Уникальные имена SHM (см. глобальные ADR про SharedMemory).
- Очистка устаревших сегментов при старте.

---

## ModuleNotFoundError в тестах

- Запускайте pytest с **корнем текущий каталог** в PYTHONPATH (скрипт `python scripts/run_framework_tests.py`).
- Из каталога `multiprocess_framework/modules`: `python -m pytest` использует локальный `pytest.ini`.

---

## Логи и пути

- Пути к файлам логов не должны зависеть от cwd пакета `modules/`; в pytest задайте каталог явно (ADR-111).

---

## Куда сообщить о баге фреймворка

1. Воспроизведение минимальным `proc_dict` или unit-тестом.
2. Версия Python, ОС, ветка кода.
3. Ссылка на соответствующий ADR / модуль в [ADR_REGISTRY.md](./ADR_REGISTRY.md).
