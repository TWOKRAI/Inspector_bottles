# Quick Start

Минимальный путь к запуску нескольких процессов под `SystemLauncher`. Полный прототип: `multiprocess_prototype/main.py`.

---

## Предпосылки

- **Python** 3.9+ (рекомендуется версия проекта).
- **Pydantic v2** (типизированные схемы `SchemaBase`).
- **PYTHONPATH** должен включать каталог текущий каталог (как в `python scripts/run_framework_tests.py`).

---

## 1. Два процесса за ~50 строк

```python
# minimal_launcher.py — запуск из корня проекта в PYTHONPATH
from multiprocess_framework import SchemaBase, SystemLauncher


class ProcConfig(SchemaBase):
    """Минимальная схема: поля дополняются DEFAULT_PROCESS_SCHEMA при merge."""

    class Config:
        extra = "allow"


def main() -> None:
    launcher = SystemLauncher(stop_timeout=5.0)
    # process(cfg) -> (name, proc_dict); укажите class_path на ваш ProcessModule
    launcher.add_process(
        "worker",
        {
            "class": "myapp.worker_process.WorkerProcess",
            "config": ProcConfig().model_dump(),
        },
    )
    launcher.add_process(
        "helper",
        {
            "class": "myapp.helper_process.HelperProcess",
            "config": ProcConfig().model_dump(),
        },
    )
    launcher.run()


if __name__ == "__main__":
    main()
```

Замените `class` на реальные пути подклассов `ProcessModule`. Для полей очередей и приоритетов см. [CONFIG_GUIDE.md](./CONFIG_GUIDE.md) и `merge_with_defaults` в оркестраторе.

---

## 2. Конфигурация через SchemaBase

- Описывайте поля в Pydantic-модели, наследнике `SchemaBase`.
- На границе процесса передавайте **`model_dump()`**, не сырой объект модели.

---

## 3. Сообщения между процессами

- Создание: `MessageAdapter` + тип из `MessageType`.
- Отправка: `ProcessModule.send` / `send_message` → Router → очереди целевого процесса.
- Подробнее: [ROUTING_GLOSSARY.md](./ROUTING_GLOSSARY.md).

---

## 4. Worker-потоки

- Внутри процесса: `WorkerManager` + `ThreadConfig` из `worker_module`.
- Регистрация задач — после `ProcessModule.initialize()`.

---

## 5. Логирование

- `LoggerManager` (каналы CRM), опционально `ErrorManager` для severity-файлов.
- Пути логов: не от cwd пакета; в тестах каталог задаётся pytest (см. глобальный ADR-111).

---

## 6. Graceful shutdown

- `SystemLauncher.run()` обрабатывает сигналы; таймаут `stop_timeout`.
- Дочерние процессы получают stop-event через оркестратор (см. **ADR-PMM-001**).

---

## Что читать дальше

| Цель | Документ |
|------|----------|
| Архитектура | [FRAMEWORK_OVERVIEW.md](./FRAMEWORK_OVERVIEW.md) |
| Конфиг и dict | [CONFIG_GUIDE.md](./CONFIG_GUIDE.md) |
| Расширение процесса | [EXTENSION_GUIDE.md](./EXTENSION_GUIDE.md) |
| Проблемы запуска | [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) |
| ADR | [../DECISIONS.md](../DECISIONS.md), [ADR_REGISTRY.md](./ADR_REGISTRY.md) |
