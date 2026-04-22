# Plan: multiprocess_prototype_v3 — Поэтапная сборка прототипа

## Context

**Проблема:** Фреймворк `multiprocess_framework` прошёл рефакторинг 15 модулей (1200+ тестов), но не проверен в реальной интеграции. Юнит-тесты не ловят проблемы на стыках модулей.

**Цель v3:** Построить прототип инспекции бутылок поэтапно, используя фреймворк как конструктор. Каждый этап — интеграционный тест группы модулей. Если что-то не работает — **чиним фреймворк**, а не делаем костыли.

**Результат:** Работающий многопроцессный прототип + список доработок фреймворка + уверенность, что конструктор собирает приложения чисто.

**Кто реализует:** Cursor-агент. **Кто ревьюит:** Claude Opus.

---

## META: Дорожная карта

```
M1 — Multiprocess Minimum (Stages 1-3)
  Stage 1: Скелет + 2 процесса + IPC + graceful shutdown
  Stage 2: Observability (логи, ошибки, метрики)
  Stage 3: Commands + интерактивное управление

M2 — Register-Driven App (Stages 4-6)
  Stage 4: Регистры + FieldRouting, данные через регистры
  Stage 5: Пайплайн 4 процесса + SharedMemory (camera_sim → processor → aggregator)
  Stage 6: Персистенция (ConfigStore, SQL)

M3 — PyQt GUI (Stage 7)
  Stage 7: GUI как отдельный процесс через frontend_module
```

**Критерий успеха M2:** `main.py` остаётся < 40 строк. Если раздувается — фреймворк недоработан.

---

## Структура файлов v3

```
multiprocess_prototype_v3/
    __init__.py
    main.py                              # Точка входа, растёт поэтапно

    backend/
        __init__.py
        configs/
            __init__.py
            base_config.py               # ProcessConfigBase (паттерн из v2)
            proc_assembly.py             # build_proc_dict / build_launch_tuple
            managers_schema.py           # get_default_managers_config
        processes/
            __init__.py
            producer/                    # Stage 1
                __init__.py
                config.py
                process.py
            consumer/                    # Stage 1
                __init__.py
                config.py
                process.py
            camera_sim/                  # Stage 5
                __init__.py
                config.py
                process.py
            processor/                   # Stage 5
                __init__.py
                config.py
                process.py
            aggregator/                  # Stage 5 (consumer → aggregator)
                __init__.py
                config.py
                process.py
            gui/                         # Stage 7
                __init__.py
                config.py
                process.py

    registers/                           # Stage 4+
        __init__.py
        names.py                         # Константы имён регистров
        boot.py                          # Boot values из схем
        factory.py                       # create_registers() → (RegistersManager, connection_map)
        producer.py                      # ProducerRegisters (Stage 4)
        camera_sim.py                    # CameraSimRegisters (Stage 5)
        processor_registers.py           # ProcessorRegisters (Stage 5)
        aggregator.py                    # AggregatorRegisters (Stage 5)

    frontend/                            # Stage 7
        __init__.py
        launcher.py
        widgets/

    persistence/                         # Stage 6
        __init__.py
        paths.py

    tests/
        __init__.py
        support/
            __init__.py
            harness.py                   # Обёртка SystemLauncher для тестов
        test_stage1_ipc.py
        test_stage2_observability.py
        test_stage3_commands.py
        test_stage4_registers.py
        test_stage5_pipeline.py
        test_stage6_persistence.py
        test_stage7_gui.py

    docs/
        STAGE_LOG.md                     # Обнаруженные проблемы фреймворка, по этапам
        README.md
```

---

## Stage 1: Скелет + 2 процесса + IPC (M1a)

### Цель
Доказать: `SystemLauncher` → `ProcessManagerProcess` → 2 дочерних процесса → обмен сообщениями → чистый shutdown.

### Процессы
| Процесс | Роль |
|---------|------|
| **producer** | Генерирует counter-сообщения каждые 0.5с, отправляет consumer |
| **consumer** | Принимает сообщения, печатает, считает |

### Что создать

**Инфраструктура (портируем паттерн из v2):**

1. `backend/configs/base_config.py` — копия паттерна из `multiprocess_prototype_v2/backend/configs/base_config.py`:
   - `ProcessConfigBase(SchemaBase)` с полями `process_name`, `class_path`, `priority`, `queues`
   - `class_path_from_type(cls)` для type-safe путей
   - `build()` → делегирует в `proc_assembly.build_launch_tuple`

2. `backend/configs/proc_assembly.py` — копия паттерна из `multiprocess_prototype_v2/backend/configs/proc_assembly.py`:
   - `build_proc_dict(cfg)` → `{"class": ..., "queues": ..., "config": cfg.model_dump(), "managers": ...}`
   - `build_launch_tuple(cfg)` → `(process_name, proc_dict)`
   - `DEFAULT_QUEUES = {"system": {"maxsize": 100}, "data": {"maxsize": 50}}`

3. `backend/configs/managers_schema.py` — минимальный конфиг менеджеров:
   - `get_default_managers_config()` → `{"logger": {...}, "error": {...}, "stats": {...}}`
   - Stage 1: логи только в stdout, error/stats выключены

**Процессы:**

4. `backend/processes/producer/process.py` — `ProducerProcess(ProcessModule)`:
   ```python
   class ProducerProcess(ProcessModule):
       def _init_application_threads(self):
           self._counter = 0
           self._interval = self.get_config("interval", 0.5)
           config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
           self.worker_manager.create_worker("produce", self._produce_worker, config, auto_start=True)

       def _produce_worker(self, stop_event, pause_event):
           while not stop_event.is_set():
               if pause_event.is_set():
                   time.sleep(0.05); continue
               self._counter += 1
               msg = self.msg.data(targets=["consumer"], data_type="counter", data={"value": self._counter})
               self.send(msg)
               self._log_info(f"Sent #{self._counter}")
               stop_event.wait(self._interval)
   ```

5. `backend/processes/consumer/process.py` — `ConsumerProcess(ProcessModule)`:
   ```python
   class ConsumerProcess(ProcessModule):
       def _init_application_threads(self):
           self._received = 0
           config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
           self.worker_manager.create_worker("consume", self._consume_worker, config, auto_start=True)

       def _consume_worker(self, stop_event, pause_event):
           while not stop_event.is_set():
               if pause_event.is_set():
                   time.sleep(0.05); continue
               msgs = self.receive(timeout=0.1, channel_types=["data"])
               for msg_dict in msgs:
                   self._received += 1
                   value = msg_dict.get("data", {}).get("value", "?")
                   self._log_info(f"Received #{self._received}: value={value}")
               time.sleep(0.02)
   ```

6. `backend/processes/producer/config.py`:
   ```python
   @register_schema("ProducerConfig")
   class ProducerConfig(ProcessConfigBase):
       process_name: str = "producer"
       class_path: str = class_path_from_type(ProducerProcess)
       interval: float = 0.5
   ```

7. `backend/processes/consumer/config.py` — аналогично.

8. `main.py` — **максимум 25 строк**:
   ```python
   from multiprocess_framework.modules.process_manager_module import SystemLauncher
   from multiprocess_framework.modules.data_schema_module import process

   launcher = SystemLauncher(stop_timeout=5.0)
   launcher.add_process(*process(ProducerConfig()))
   launcher.add_process(*process(ConsumerConfig()))
   launcher.run()
   ```

9. `tests/support/harness.py` — тестовый хелпер:
   - `start_system(configs, timeout)` — запуск SystemLauncher в треде, ожидание ready
   - `stop_system(timeout)` — остановка, проверка что зомби-процессов нет
   - `wait_for_messages(process_name, count, timeout)` — ожидание N сообщений

10. `tests/test_stage1_ipc.py` — автотест: запуск 3с → consumer получил >3 сообщений → чистый stop.

### Референсные файлы фреймворка
- `multiprocess_prototype_v2/backend/configs/base_config.py` — паттерн ProcessConfigBase
- `multiprocess_prototype_v2/backend/configs/proc_assembly.py` — сборка proc_dict
- `multiprocess_prototype_v2/backend/processes/robot_simulator/robot_simulator_process.py` — простейший ProcessModule (образец для producer/consumer)
- `multiprocess_framework/modules/process_manager_module/core/system_launcher.py` — API SystemLauncher
- `multiprocess_framework/modules/data_schema_module/core/process_schema.py` — функция `process()`

### Модули фреймворка под проверкой
| Модуль | Что проверяем |
|--------|---------------|
| `process_manager_module` | SystemLauncher.add_process, run, stop; ProcessManagerProcess spawn 2 детей |
| `process_module` | Lifecycle: initialize → _init_application_threads → run → shutdown |
| `data_schema_module` | SchemaBase, process(), model_dump, merge_with_defaults |
| `shared_resources_module` | QueueRegistry, IPC через multiprocessing.Queue |
| `message_module` | MessageAdapter, Message.to_dict(), dict at boundary |
| `worker_module` | WorkerManager.create_worker(LOOP), auto_start, stop |
| `router_module` | RouterManager send/receive через очереди |

### Критерии приёмки
- [ ] `python main.py` стартует, в stdout видны сообщения producer и consumer, Ctrl+C → чистый shutdown за 5с
- [ ] Нет зомби-процессов после shutdown
- [ ] Consumer получает сообщения от producer (видно в логах)
- [ ] `test_stage1_ipc.py` проходит
- [ ] `main.py` ≤ 25 строк кода

### Риски
- **Queue naming**: producer шлёт в "consumer", но очередь может называться иначе в SRM → проверить `DEFAULT_QUEUES`
- **Spawn на macOS**: pickle-safety всех объектов → проверить что ProcessModule pickle-safe
- **sys.path**: v2 использует `sys.path.insert` в main.py → для v3 настроить через `pyproject.toml` или аналогично

---

## Stage 2: Observability — логи, ошибки, метрики (M1b)

### Цель
Включить LoggerManager, ErrorManager, StatsManager. Логи в файлы, ошибки отдельно, метрики считаются.

### Изменения

1. **`managers_schema.py`** — расширить конфиг:
   - LoggerManager: каналы `file` (→ `logs/{process_name}.log`) + `stdout`
   - ErrorManager: канал `file` (→ `logs/errors.log`), severity routing
   - StatsManager: канал `memory` (in-process aggregation)

2. **ProducerProcess** — добавить:
   - `self._log_info(f"Produced {n} messages")` каждые 10 сообщений
   - Запись метрики `self._record_stat("messages_produced", self._counter)` через ObservableMixin

3. **ConsumerProcess** — добавить:
   - Периодическое логирование `self._log_info(f"Total received: {self._received}")`
   - Симуляция ошибки на каждом 25-м: `self._log_error("Simulated error at message 25")`

4. **`tests/test_stage2_observability.py`**:
   - Запуск 5с → проверить что файлы логов существуют → проверить что в error.log есть "Simulated error"

### Модули фреймворка под проверкой
| Модуль | Что проверяем |
|--------|---------------|
| `logger_module` | LoggerManager init через ObservableMixin, FileChannel, _log_info/_log_error |
| `error_module` | ErrorManager captures errors, severity routing, файл errors.log |
| `statistics_module` | StatsManager.record(), aggregation в памяти |
| `channel_routing_module` | CRM как база для Logger/Error/Stats каналов |
| `config_module` | managers config dict → runtime config в каждом процессе |

### Критерии приёмки
- [ ] В `logs/` появляются файлы логов после запуска
- [ ] Каждый процесс идентифицируется по имени в логах
- [ ] `logs/errors.log` содержит симулированную ошибку consumer
- [ ] Метрики доступны (через StatsManager.get_metrics или лог)
- [ ] Если LoggerManager не работает → issue в фреймворке, не workaround

---

## Stage 3: Commands + управление (M1c)

### Цель
CommandManager для диспетчеризации команд. Интерактивное управление producer/consumer.

### Изменения

1. **ProducerProcess** — регистрация команд:
   ```python
   self.command_manager.register_command("pause_producing", self._cmd_pause)
   self.command_manager.register_command("resume_producing", self._cmd_resume)
   self.command_manager.register_command("get_status", self._cmd_status)
   ```
   - `_cmd_pause` → устанавливает pause_event у worker
   - `_cmd_resume` → снимает pause_event
   - `_cmd_status` → возвращает dict с counter, interval, is_paused

2. **ConsumerProcess** — команда `get_count` → возвращает `{"received": self._received}`

3. **Тест `test_stage3_commands.py`**:
   - Через harness отправить команду `pause_producing` → проверить что producer перестал слать
   - Отправить `resume_producing` → проверить что возобновил
   - Отправить `get_status` → проверить ответ

### Модули фреймворка под проверкой
| Модуль | Что проверяем |
|--------|---------------|
| `command_module` | register_command, handle_command, dispatch |
| `dispatch_module` | EXACT_MATCH стратегия |
| `console_module` | Интерактивный ввод команд (если подключаем) |

### Критерии приёмки
- [ ] Команда `pause_producing` останавливает генерацию
- [ ] `resume_producing` возобновляет
- [ ] `get_status` возвращает корректный статус
- [ ] Команды идут через CommandManager, не через парсинг очередей вручную
- [ ] **M1 complete**: 2 процесса + IPC + логи + команды + graceful shutdown

---

## Stage 4: Регистры + FieldRouting (M2a)

### Цель
Register-driven pattern. SchemaBase-регистры с FieldMeta + FieldRouting. Изменение регистра → Router → процесс применяет.

### Новые файлы

1. **`registers/producer.py`**:
   ```python
   class ProducerRegisters(SchemaBase):
       interval: float = Field(default=0.5, metadata=FieldMeta(label="Interval", min=0.1, max=5.0, unit="s"))
       message_prefix: str = Field(default="msg", metadata=FieldMeta(label="Message prefix"))
       enabled: bool = Field(default=True, metadata=FieldMeta(label="Enabled"))

       class Meta:
           routing = {
               "interval": FieldRouting(channel="control", process_targets=("producer",)),
               "message_prefix": FieldRouting(channel="control", process_targets=("producer",)),
               "enabled": FieldRouting(channel="control", process_targets=("producer",)),
           }
   ```

2. **`registers/names.py`** — `PRODUCER_REGISTER = "producer"`, `CONSUMER_REGISTER = "consumer"`

3. **`registers/boot.py`** — `producer_boot_values() → ProducerRegisters().model_dump()`

4. **`registers/factory.py`** — `create_registers() → (RegistersManager, connection_map)`

5. **ProducerConfig** — boot values из `registers/boot.py`:
   ```python
   _BOOT = producer_boot_values()
   class ProducerConfig(ProcessConfigBase):
       interval: float = _BOOT["interval"]
       message_prefix: str = _BOOT["message_prefix"]
       enabled: bool = _BOOT["enabled"]
   ```

6. **ProducerProcess** — обработка `register_update`:
   ```python
   self.command_manager.register_command("register_update", self._apply_register_update)

   def _apply_register_update(self, data):
       field = data.get("field")
       value = data.get("value")
       if field == "interval":
           self._interval = value
       elif field == "enabled":
           # pause/resume worker
       elif field == "message_prefix":
           self._prefix = value
   ```

### Модули фреймворка под проверкой
| Модуль | Что проверяем |
|--------|---------------|
| `registers_module` | RegistersManager, set_field_value dispatch, connection_map |
| `data_schema_module` | FieldMeta, FieldRouting, RegisterDispatchMeta |
| `router_module` | Маршрутизация register_update по FieldRouting.channel + process_targets |

### Критерии приёмки
- [ ] Изменение `interval` в регистре → producer меняет частоту отправки
- [ ] `enabled = false` → producer останавливается
- [ ] `connection_map` строится автоматически из `FieldRouting.process_targets`
- [ ] Boot values приходят из дефолтов регистров
- [ ] Поток: console/тест → RegistersManager.set_field_value → Router → producer queue → apply

---

## Stage 5: Пайплайн 4 процесса + SharedMemory (M2b)

### Цель
Масштабирование до реального пайплайна с SharedMemory. Эмуляция инспекции без реального железа.

### Процессы
| Процесс | Роль | SharedMemory |
|---------|------|-------------|
| **camera_sim** | Генерирует синтетические кадры (numpy, цветной шум), пишет в SHM | owner: `camera_frame` (480,640,3) |
| **processor** | Читает кадр из SHM, вычисляет среднюю яркость, порог → defect/ok | reader: `camera_frame` |
| **aggregator** | Собирает результаты, ведёт статистику, пишет отчёт | — |
| **console** | Интерактивное изменение регистров (или producer из Stage 1-3 убираем) | — |

**producer/consumer** из Stage 1-3 остаются в коде как простейший пример, но `main.py` переключается на пайплайн.

### SharedMemory Layout
```python
# CameraSimConfig
@property
def memory(self) -> dict:
    return {"camera_frame": (480, 640, 3), "coll": 2}  # 2 слота, double-buffering
```

### Регистры
- `CameraSimRegisters` — `fps` (int), `resolution_width`, `resolution_height`, `frame_color` (str, для симуляции)
- `ProcessorRegisters` — `brightness_threshold` (int, 0-255), `enabled` (bool)
- `AggregatorRegisters` — `report_interval` (float, сек)

### Поток данных
```
camera_sim → [SHM: camera_frame] → processor → [Queue: data] → aggregator
                                                                    ↓
                                                              stdout / logs
```

### Модули фреймворка под проверкой
| Модуль | Что проверяем |
|--------|---------------|
| `shared_resources_module` | MemoryManager.write_images, read_images, find_free_index, cleanup |
| Все предыдущие | Масштабирование на 4 процесса |

### Критерии приёмки
- [ ] camera_sim пишет кадры в SHM, processor их читает
- [ ] Изменение `fps` в регистре camera_sim → частота кадров меняется
- [ ] Изменение `brightness_threshold` в processor → меняется порог
- [ ] aggregator печатает периодическую сводку
- [ ] 4 процесса стартуют и останавливаются чисто
- [ ] Нет утечек SharedMemory после shutdown

---

## Stage 6: Персистенция + ConfigStore (M2c)

### Цель
ConfigStore для кросс-процессного конфига. SQL для сохранения результатов.

### Изменения

1. **ConfigStore** в SRM хранит текущее состояние регистров. При старте регистры загружаются из ConfigStore (если есть), а не из дефолтов.

2. **Aggregator** использует `sql_module` для записи результатов в SQLite:
   - Таблица `detections` — `frame_id`, `brightness`, `is_defect`, `timestamp`
   - Команда `get_report` → SELECT из SQLite

3. **`persistence/paths.py`** — пути к данным: `data/config.json`, `data/detections.db`

### Модули фреймворка под проверкой
| Модуль | Что проверяем |
|--------|---------------|
| `config_module` | ConfigStore read/write, sync_config, cross-process config |
| `sql_module` | SQLManager, dict-at-boundary запросы, SQLite |

### Критерии приёмки
- [ ] После рестарта регистры сохраняют значения предыдущего запуска
- [ ] aggregator пишет результаты в SQLite
- [ ] Конфиг-изменения распространяются через ConfigStore
- [ ] **M2 complete**: приложение полностью register-driven; `main.py` < 40 строк

---

## Stage 7: PyQt GUI (M3)

### Цель
GUI как отдельный процесс через `frontend_module`. Стандартный IPC, не встроенный в ядро.

### Подход
1. `GuiProcess(ProcessModule)` по паттерну v2 (`gui_process.py`)
2. Минимальный GUI: одно окно, 2 вкладки:
   - **Camera** — счётчик кадров, FPS, слайдер `fps`
   - **System** — статистика aggregator, кнопки start/stop
3. `FrontendManager` / `FrontendLauncher` из `frontend_module`
4. FieldMeta даёт label/min/max/unit → авто-генерация контролов
5. UI changes → `RegistersManager.set_field_value` → Router → backend

### Модули фреймворка под проверкой
| Модуль | Что проверяем |
|--------|---------------|
| `frontend_module` | FrontendManager, WindowManager, BaseConfigurableWidget |
| Все предыдущие | Полная end-to-end интеграция |

### Критерии приёмки
- [ ] GUI окно открывается, показывает FPS и статистику
- [ ] Слайдер `fps` → register change → camera_sim меняет частоту
- [ ] Toggle `enabled` → processor start/stop
- [ ] Закрытие GUI не крашит backend-процессы
- [ ] **M3 complete**: полный прототип работает

---

## Конфигурация Observability по этапам

| Stage | LoggerManager | ErrorManager | StatsManager |
|-------|--------------|-------------|-------------|
| 1 | stdout only | disabled | disabled |
| 2 | file + stdout | file (errors.log) | memory |
| 3 | то же | то же | то же |
| 4-6 | file + stdout | file + severity routing | memory + file |
| 7 | + GUI channel | + GUI notification | + UI display |

---

## Риски и митигации

| # | Риск | Вероятность | Митигация |
|---|------|------------|-----------|
| 1 | Pickle-safety на macOS/Windows spawn | Средняя | Stage 1 сразу проверяет. Если класс не pickle-safe → фикс в фреймворке |
| 2 | Queue naming mismatch | Низкая | `DEFAULT_QUEUES` в proc_assembly стандартизирует |
| 3 | SharedMemory leak при crash | Средняя | Фреймворк имеет `cleanup_known_shm_at_startup()`. Верифицируем в Stage 5 |
| 4 | frontend_module readiness | Высокая | Stage 7 последний. Backend уже проверен. Frontend issues изолированы |
| 5 | console_module на macOS | Средняя | Тестируем в Stage 3. Если broken → issue и fix |
| 6 | Race conditions в регистрах | Низкая | RegistersManager single-writer (GUI или console). Документируем |
| 7 | Переполнение очередей | Средняя | `maxsize` на очередях = backpressure. Stage 5 стресс-тестирует |

---

## Рекомендации и идеи

### Для фреймворка
1. **`launcher.wait_until_ready(timeout)`** — сейчас нет встроенного способа узнать, что все процессы стартовали. Нужно для тестов. Возможно добавить в `SystemLauncher`.
2. **Register persistence** — v2 использует YAML (`persistence/user_prefs.py`). ConfigStore не поддерживает file-backed нативно. Это gap для Stage 6.
3. **Test harness как часть фреймворка** — `tests/support/harness.py` из v3 может стать `multiprocess_framework/testing/harness.py` для переиспользования.
4. **Tiered `__init__.py`** — `from multiprocess_framework import SystemLauncher, ProcessModule, SchemaBase` должно работать без цепочки `from modules.process_manager_module import ...`. Это сильно упростит main.py.

### Для прототипа
5. **main.py как north star** — если >40 строк → конструктор не работает, возвращаемся к фреймворку.
6. **`docs/STAGE_LOG.md`** — каждая проблема фреймворка документируется: модуль, симптом, фикс. Это **главная ценность** v3.
7. **Не пропускать этапы** — соблазн "перейти и поправить потом" убивает смысл инкрементального подхода.
8. **Harness для тестов** — обёртка над SystemLauncher для программных тестов (start, wait, send_command, assert, stop).

### Архитектурные улучшения (идеи на будущее)
9. **Health probes** — `process.is_healthy()` → ProcessMonitor → Prometheus-ready. Пока не в scope, но Stage 5 покажет потребность.
10. **Event bus** — для register updates pub/sub может быть удобнее чем command-based. Оценить после Stage 4.
11. **Hot-reload** — плагины ProcessModule без рестарта системы. Полезно для dev-цикла.

---

## Порядок работы для Cursor-агента

```
Для каждого Stage N:
  1. Прочитать этот план, секцию Stage N
  2. Прочитать референсные файлы v2 (указаны в Stage 1)
  3. Создать файлы по списку
  4. Запустить `python main.py` — проверить вручную
  5. Запустить `tests/test_stageN_*.py` — все тесты зелёные
  6. Если фреймворк не работает → записать в docs/STAGE_LOG.md, НЕ делать workaround
  7. Claude Opus ревьюит код и STAGE_LOG
  8. Только после приёмки → переход к Stage N+1
```

---

## Verification (как проверить что всё работает)

### Per-stage
```bash
# Stage 1
cd Inspector_prototype
python -m multiprocess_prototype_v3.main     # Ctrl+C через 5с
python -m pytest multiprocess_prototype_v3/tests/test_stage1_ipc.py -v

# Stage 2
python -m pytest multiprocess_prototype_v3/tests/test_stage2_observability.py -v
ls multiprocess_prototype_v3/logs/            # файлы логов

# Stage 3
python -m pytest multiprocess_prototype_v3/tests/test_stage3_commands.py -v

# Stage 4
python -m pytest multiprocess_prototype_v3/tests/test_stage4_registers.py -v

# Stage 5
python -m pytest multiprocess_prototype_v3/tests/test_stage5_pipeline.py -v

# Stage 6
python -m pytest multiprocess_prototype_v3/tests/test_stage6_persistence.py -v
ls multiprocess_prototype_v3/data/            # SQLite файл

# Stage 7
python -m multiprocess_prototype_v3.main      # GUI окно должно открыться
```

### Full validation
```bash
cd Inspector_prototype
python -m pytest multiprocess_prototype_v3/tests/ -v
python scripts/validate.py                     # фреймворк тесты тоже не сломаны
```
