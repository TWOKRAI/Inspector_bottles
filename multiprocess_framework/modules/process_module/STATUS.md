# process_module — Статус и метрики

## Текущий статус

✅ **Production Ready** — модуль готов к использованию

- **2026-08-12:** stats-разъём плагинов (ADR-PM-033, план `telemetry-stage6` задача 1.1, вход C1/Ф8.3): узкий протокол `IPluginStatsManager` (четвёрка `record_metric`/`gauge`/`record_timing`/`histogram`), порт `stats_manager` в `IProcessServices`, четвёрка на `PluginContext` и `SubPluginContext` (+ `from_parent`), дубль `MockStatsManager` с умением отказать, секция `stats` в `introspect.observability` (`declared` / `without_plane`). Сигнатуры дословны `StatsManager`, единица `record_timing` — **секунды**; метрика штампуется тегом `plugin`. Цена фасада — 0.31–0.38 мкс сверх прямого вызова. Тесты: 33 (`tests/test_plugin_stats_road.py`), 10 инъекций. Доставка `kind=stats` в стор/хвост — задача 2.1, не здесь.
- **2026-07-07:** health-примитив наблюдаемости отказов (ADR-PM-010, Ф2 Task 2.1): подпакет `health/` (`HealthState` + `HealthReporter` + контракт путей `schema.py`), `ctx.health.report_error/set_status/degraded` в PluginContext, self-publish через `ProcessHeartbeat` в `processes.<name>.health.*`, диагностика `health.report`/`health.status` в BuiltinCommands. Откат — `INSPECTOR_HEALTH_LOG_ONLY`. Тесты: 30 unit (schema/state/context) + 2 live (harness_smoke).
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


## Обновление 2026-08-06 (Ф8.1 — каталог метрик объявлениями)

`GATED_METRICS` как кортеж-литерал **исчез**. Метрика объявляется там, где считается
(`declare_metric` рядом с вычислением), каталог отдаёт `gated_metrics()`. Приложение
или плагин заводит свою метрику, не трогая фреймворк. Разбор — ADR-PM-027.

Живая проверка 2026-08-06: `introspect_telemetry("seg").gated_metrics` вернул все пять
имён отсортированными — собранные объявлениями.

**Резидуал:** GUI строит строки контролов из ИМПОРТА производителей, а не из readback,
поэтому метрика, объявленная только в бэкенд-процессе, строки во вкладке не получит.

## Задача 3.3 (2026-08-11) — последний рубеж каталога логов (ADR-138)

`ProcessLaunchConfig._resolve_log_dir` держал последним рубежом строку `"logs"` —
относительную, то есть «пиши рядом с рабочим каталогом того, кто запускает». Теперь рубеж —
`default_log_base_directory()` (системный temp). Порядок не менялся: свой конфиг → env → рубеж.

Стражи — `tests/test_log_dir_last_resort.py` (6 тестов): приоритет обеих env-ручек проверяется
парой с ЯВНОЙ очисткой соседней (иначе тест мерил бы приоритет, а не действие переменной), и
отдельно — что путь рубежа лежит вне дерева репозитория.

## Задача 3.2 (2026-08-14) — опрос уровней: пакетный снимок по запросу (ADR-PM-035)

`introspect.telemetry` отвечала «что публикуется», но не «сколько сейчас»: закрытый
publisher-гейт уносил числа вместе с трафиком. Команда дополнена двумя секциями —
`levels` (пакетный снимок: все метрики и все воркеры одним ответом, поддерево
`processes.<name>` — `workers.*` и `state.*`, включая `state.shm.*`) и `snapshot_ts`
(эпоха момента снятия: потребитель на другой стороне IPC отличает «свежо» от «завис»).
Новой команды не заведено — развилка РТ-3 решена расширением существующей.

`levels` **не зависит от гейта** (гейт про push, а не про знание процесса о себе) и
собирается ТЕМ ЖЕ сборщиком, что тик публикации — `ProcessHeartbeat.current_levels_snapshot()`,
одна точка, а не вторая дорога. Опрос ничего не пишет в дерево и не двигает расписание
гейта. Список shm-счётчиков выехал из публикатора в `build_router_shm_telemetry` (у
публикатора осталась политика «все нули → не грузим дерево»; у опроса те же нули —
показание «всё чисто»).

**Цена опроса — на полу транспорта** (ревью-блокер 1). Первая редакция звала ради тринадцати
int'ов полный `RouterManager.get_stats()` со сборкой маршрутов/хендлеров/каналов: живьём
65.73 мс против 11 мс пола, и шторм опросов 21.7/с просаживал боевой fps на 7.4 %. Появился
узкий `RouterManager.get_shm_stats()`; `get_stats()` splice'ит его результат к себе, поэтому
точка вычисления по-прежнему одна. После: **11.13 мс** — неотличимо от `introspect.status`
(11.00), а шторм **80.4 опр/с** даёт +0.2 % по fps, то есть интерференции нет. Выигрыш
достаётся и push-тику, который платил ту же цену каждый такт heartbeat'а.

**`snapshot_ts` — возраст ОТВЕТА, не возраст чисел** (ревью-блокер 2, найдено воспроизведением:
у остановленного воркера штамп идёт, а `fps`/`latency_ms` стоят; при зависании процесса целиком
ответа нет вовсе). Свежесть САМИХ ЧИСЕЛ даёт per-worker `cycles` — счётчик `CycleMetricsRecorder`,
который `WorkerManager.get_worker_status` уже подмешивает в статус, поэтому поле бесплатно.
Едет только опросом (`include_cycles`, в push выключен). Живьём: за 3.01 с счётчик +64 при
fps 21.2–21.4 — дельта счётчика делится на время и сходится с частотой.

Тесты: 14 приёмочных (`tests/test_telemetry_levels_poll_acceptance.py`, независимый тестер —
писались без доступа к реализации) + 15 авторских на опасности механизма
(`tests/test_telemetry_levels_poll_hazards.py`: опрос посреди тика из чужого потока,
неприкосновенность расписания гейта, локализация отказа секции, отвязанность снимка,
эквивалентность переписанного guard'а публикатора, `shm` при закрытом для push гейте).

**Резидуал (найден живым стендом 2026-08-14, для 3.3):** `levels` отдаёт то, что собирает
телеметрийный тик, а не весь `processes.<name>.state`. У живого `camera_0` рядом лежат
восемь ключей от ДРУГИХ публикаторов — `uptime`, `frame_count`, `drops`, `status`, `pid`,
`error`, `paused`, `frozen` (в дереве 11 ключей, опрос отдаёт 3). Опросом они не приходят,
а `uptime` при этом в `DEFAULT_TRACKED_SUFFIXES` read-model. Список назван поимённо и
целиком: он — вход развилки 3.3 (GUI берёт их push'ем ИЛИ их эмитенты въезжают в общий
сборщик), а неполный вход даст неполное решение. В 3.2 выбор не делается.

`backend_ctl` второго механизма не получил: `introspect_telemetry` проходит сырым dict'ом,
новые секции приезжают без правок драйвера. `telemetry_snapshot` / `telemetry_history` —
по-прежнему локальная read-model (ADR-136, 0 IPC) и с опросом не путаются: у них push-дельты
под активной подпиской, у `levels` — поход в процесс, работающий при закрытой публикации.
