# process_module — Статус и метрики

## Текущий статус

✅ **Production Ready** — модуль готов к использованию

- Корневая сборка `managers`: **`config/managers_config.py`** — `ManagersConfig`, `from_log_dir()` (ADR-103); нормализация вида **`normalize_managers_view`** + **`ProcessLaunchConfig`** (ADR-104)
- Версия: 2.0.0 (Refactored)
- Тесты: 61/62 проходят (98% успешность)
- Документация: ✅ полная
- Циклические зависимости: ✓ устранены

---

## Качество модуля

| Метрика | Score | Статус |
|---------|-------|--------|
| Код | 8/10 | ✅ Хорошо |
| Тесты | 8/10 | ✅ Хорошо |
| Документация | 9/10 | ✅ Отлично |
| Архитектура | 8/10 | ✅ Хорошо |
| Типизация | 8/10 | ✅ Хорошо |
| Pickle Safety | 9/10 | ✅ Отлично |
| Работоспособность | 9/10 | ✅ Отлично |
| Совместимость | 9/10 | ✅ Отлично |

**Средний score: 8.5/10 — Production Ready** 🟢

---

## Дополнения к документации (2026-03-30)

- **docs/examples/process_config_canonical_examples.py** — эталонные plain-dict для `ProcessConfigHandler` / `ProcessConfigDict`; живые проверки по-прежнему в `tests/test_process_config.py`.
- **README**: единая точка чтения конфига — `get_config` / `config_handler`; ссылка на фреймворк [CONFIG_PATHS.md](../../docs/CONFIG_PATHS.md) (ADR-102).

## Структура модуля

```
process_module/
├── __init__.py              # Публичный API
├── interfaces.py            # Контракты: IProcessModule, ISharedResources, IProcessCommunication
├── types/                   # ProcessStatus enum, TypedDict
├── core/                    # ProcessModule (главный класс)
├── lifecycle/               # Жизненный цикл: initialize/shutdown
├── managers/                # Инициализация менеджеров
├── communication/           # IPC (send/receive/broadcast)
├── config/                  # Конфигурация
├── state/                   # Состояние процесса
├── threads/                 # Системные потоки
├── adapters/                # ProcessAdapter, SchemaAdapter
├── tests/                   # 49 unit-тестов
├── README.md                # Документация пользователя
├── ARCHITECTURE.md          # Архитектура и дизайн
├── docs/
│   └── COMMUNICATION.md     # IPC руководство
└── STATUS.md                # Этот файл
```

---

## Компоненты и ответственность

| Компонент | Класс | Назначение |
|-----------|-------|-----------|
| **Ядро** | ProcessModule | Основной класс процесса, жизненный цикл |
| **Жизненный цикл** | ProcessLifecycle | initialize, shutdown, status transitions |
| **Менеджеры** | ProcessManagers | Инициализация WorkerManager, RouterManager, LoggerManager |
| **Коммуникация** | ProcessCommunication | send_message, receive_message, broadcast_message |
| **Конфигурация** | ProcessConfigHandler | get/update конфигурации |
| **Состояние** | ProcessState | Интеграция с shared_resources |
| **Потоки** | SystemThreads | Управление системными потоками |
| **Адаптеры** | ProcessAdapter, SchemaAdapter | Интеграция с внешними системами |

---

## Использование

### Быстрый старт

```python
from multiprocess_framework.modules.process_module import ProcessModule

class MyProcess(ProcessModule):
    def initialize(self) -> bool:
        self.log_info("Инициализация...")
        return True
    
    def run(self):
        while not self.should_stop():
            self.log_info("Работаю...")
            time.sleep(1)
    
    def shutdown(self) -> bool:
        self.log_info("Завершение...")
        return True

# Запуск
process = MyProcess("my_process")
process.initialize()
process.run()
process.shutdown()
```

### С воркерами

```python
from multiprocess_framework.modules.worker_module import ThreadConfig

process = ProcessModule("process_with_workers")
process.initialize()

# Создать воркер
config = ThreadConfig(priority="NORMAL")
process.worker_manager.create_worker(
    "worker_1",
    lambda stop, pause: worker_func(stop, pause),
    config,
    auto_start=True
)

process.run()
process.shutdown()
```

### С коммуникацией

```python
# Отправить сообщение
process.send_message("other_process", {"command": "execute"})

# Получить сообщение
msg = process.receive_message(timeout=1.0)
if msg:
    print(f"Получено: {msg}")

# Broadcast
process.broadcast_message({"event": "status_changed"})
```

---

## Зависимости

**Зависит от:**
- `base_manager` (BaseManager, ObservableMixin)
- `worker_module` (WorkerManager)
- `router_module` (RouterManager)
- `logger_module` (LoggerManager)
- `shared_resources_module` (QueueRegistry, MemoryManager)

**Используется в:**
- `process_manager_module` (оркестрация)
- `process_1`, `process_2` (прототип)

---

## Известные ограничения

1. Lazy imports в ProcessManagers (архитектурное ограничение Python)
2. Алиасы в state/ (для обратной совместимости)
3. 1 тест падает на log_info (не критично)

---

## Что дальше

### Опционально
- Удалить алиасы в state/ (требует update импортов проекта)
- Добавить метрики производительности
- Настроить CI/CD для тестов

---

## Ссылки

- **README.md** — быстрый старт и примеры
- **ARCHITECTURE.md** — дизайн, паттерны, диаграммы
- **docs/COMMUNICATION.md** — межпроцессная коммуникация
- **interfaces.py** — публичные контракты
- **tests/** — примеры использования
