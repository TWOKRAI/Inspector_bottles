# process_module — Статус и метрики

## Текущий статус

✅ **Production Ready** — модуль готов к использованию

- **2026-05-08:** Рефакторинг `refactor/t1.1-plugin-composition`: composition pattern для plugin-системы (ADR-PM-007, ADR-PM-008). `IProcessServices` Protocol — явный контракт между plugin-системой и `ProcessModule`. `PluginOrchestrator` — composition class для plugin lifecycle. `ProcessHeartbeat` и `BuiltinCommands` извлечены из `ProcessModule` как отдельные composition classes. `GenericProcess` → deprecated shim (404 → 155 LOC). `MockProcessServices` для изолированного тестирования плагинов. 206 тестов — все green.
- **2026-04-09:** Рефакторинг по `plans/refactoring/12_process_module.md`: инициализация конфигурации/очередей в `ProcessLifecycle` с делегатами на `ProcessModule` (ADR-PM-005), pipeline `ProcessManagers.initialize()`, удалён shim `state/process_state_registry.py`, `DECISIONS.md` (ADR-PM-001…006), §6.11 в `ARCHITECTURE.md`, `importlib` для воркеров, удалён `reload_manager`, помечен deprecated `log()`.
- Корневая сборка `managers`: **`configs/managers_config.py`** — blueprint-дефолты, **`RouterManagerConfig` / `CommandManagerConfig`**, **`managers_from_log_dir`** / **`managers_payload_for_proc`** + тонкие **`from_log_dir`** / **`managers_for_proc_dict`** на классе (ADR-112, **ADR-113**, **ADR-114**); нормализация **`normalize_managers_view`** + **`ProcessLaunchConfig`** (ADR-104). Публичный импорт **`ManagersConfig`** / **`managers_*`** с корня пакета **`process_module`** — лениво (**`__getattr__`**, **ADR-115**), рядом с **`ProcessModule`**.
- Версия: 2.1.0 (Composition)
- Тесты: 206/206 в `process_module/tests` (pytest)
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
- **README**: единая точка чтения конфига — `get_config` / `config_handler`; ссылка на фреймворк [CONFIG_GUIDE.md](../../docs/CONFIG_GUIDE.md) (ADR-102).

## Структура модуля

```
process_module/
├── __init__.py              # Публичный API
├── interfaces.py            # Контракты: IProcessModule, ISharedResources, IProcessCommunication, IProcessServices
├── types/                   # ProcessStatus enum, TypedDict
├── core/                    # ProcessModule (главный класс, 586 LOC)
├── lifecycle/               # Жизненный цикл: initialize/shutdown
├── managers/                # Инициализация менеджеров
├── communication/           # IPC (send/receive/broadcast)
├── config/                  # Конфигурация
├── state/                   # Состояние процесса
├── threads/                 # Системные потоки
├── adapters/                # ProcessAdapter, SchemaAdapter
├── plugins/                 # PluginOrchestrator (333 LOC), MockProcessServices
├── heartbeat/               # ProcessHeartbeat (93 LOC)
├── commands/                # BuiltinCommands (208 LOC)
├── generic/                 # GenericProcess deprecated shim (155 LOC)
├── tests/                   # 206 unit-тестов
├── README.md                # Документация пользователя
├── ARCHITECTURE.md          # Архитектура и дизайн
├── docs/
│   └── COMMUNICATION.md     # IPC руководство
└── STATUS.md                # Этот файл
```

---

## Компоненты и ответственность

| Компонент | Класс | LOC | Назначение |
|-----------|-------|-----|-----------|
| **Ядро** | ProcessModule | 586 | Основной класс процесса, жизненный цикл |
| **Жизненный цикл** | ProcessLifecycle | — | initialize, shutdown, status transitions |
| **Менеджеры** | ProcessManagers | — | Инициализация WorkerManager, RouterManager, LoggerManager |
| **Коммуникация** | ProcessCommunication | — | send_message, receive_message, broadcast_message |
| **Конфигурация** | ProcessConfigHandler | — | get/update конфигурации |
| **Состояние** | ProcessState | — | Интеграция с shared_resources |
| **Потоки** | SystemThreads | — | Управление системными потоками |
| **Адаптеры** | ProcessAdapter, SchemaAdapter | — | Интеграция с внешними системами |
| **Composition: плагины** | PluginOrchestrator | 333 | Plugin lifecycle через IProcessServices (ADR-PM-007) |
| **Composition: heartbeat** | ProcessHeartbeat | 93 | Отправка heartbeat через IProcessServices |
| **Composition: команды** | BuiltinCommands | 208 | wire/worker команды через IProcessServices |
| **Тестирование** | MockProcessServices | — | Лёгкий мок IProcessServices для изолированных тестов |
| **Deprecated** | GenericProcess | 155 | Backward-compat shim (будет удалён, ADR-PM-008) |

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
2. `state/process_data.py` остаётся алиасом к `shared_resources_module` (типы/импорты)

---

## Что дальше

### Опционально
- Добавить метрики производительности
- Настроить CI/CD для тестов

---

## Ссылки

- **README.md** — быстрый старт и примеры
- **ARCHITECTURE.md** — дизайн, паттерны, диаграммы
- **docs/COMMUNICATION.md** — межпроцессная коммуникация
- **interfaces.py** — публичные контракты
- **tests/** — примеры использования
