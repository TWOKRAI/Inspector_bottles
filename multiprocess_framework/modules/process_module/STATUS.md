# process_module — Статус и метрики

## Текущий статус

✅ **Production Ready** — модуль готов к использованию

- **2026-08-16 (вторая редакция 3.5, Р3.5-11…Р3.5-15):** инвариант «один лист — одно значение — один владелец» перенесён с ОБЪЯВЛЕНИЯ на ПУБЛИКАЦИЮ. `PluginLevels` ключуется парой `(имя, публикатор)`; `build_plugin_levels` берёт лист, только если объявленный владелец равен публикатору, — отбор по членству в общем каталоге **заменён**, а не дополнен. Ключ-пара (2026-08-17, находка инъекции И1): при ключе-имени публикация соседа ЗАТИРАЛА ячейку владельца, сборщик отбрасывал затёртое по владению, и лист исчезал целиком — перехватчик не мог подменить число, но мог его уничтожить одной опечаткой в имени. Голос дедуплицируется тоже по паре: иначе перехватчик, появившийся позже первого, молча проглатывался бы. Владельца реестр знал всегда, наружу его вывела новая `observability_declarations.metric_owners()` (зеркало `declared_sources()`). Три merge тика схлопнуты в один `_publish_telemetry_to_tree` (воркеры + агрегат + `shm` + уровни под `processes.<name>`) — возврат к принципу E6/Task 5.7, попутно 3 IPC-сообщения на тик → 1; политика наложения ADR-PM-038 («порядок несущий», «плагин побеждает») снята ЦЕЛИКОМ вместе с зеркалами в докстрингах. Свежесть держит жизненный цикл: `PluginLevels.retract(owner)` зовёт фреймворк в `ProcessModulePlugin._do_shutdown` ПОСЛЕ пользовательского `shutdown`. Владелец вычисляется в одном месте — `PluginContext._metric_owner()` — и им пользуются объявление, публикация и снятие. Прикладной слой: измеренная частота захвата разведена с частотой цикла (`capture_fps` против `fps`), метка `fps` во всех местах показа стала «Циклов/с». **Поправка владельца 2026-08-17:** слота на карточке процесса НЕТ — карточка generic (`_METRIC_KEYS` константа на все процессы), прикладное понятие «кадры» в универсальном месте дало бы вечный прочерк шести процессам из семи. Измеренная частота показывается строкой «FPS (измеренный)» в камерной секции инспектора рядом с «FPS (по драйверу)» (`cap.get`); гейт секции расширен до `{camera_service, capture}` — эти два плагина, вопреки посылке постановки, НИКОГДА не живут в одном процессе (проверено по всем 14 рецептам), и без расширения строка была бы мертва везде. Повод — воспроизведённый блокер: продовое правило троттла `processes.**.state.fps: 0.05` вырезало второй merge тика ВСЕГДА (0.5 мс между записями против 15.6-мс сетки Windows), `rejection_reason` отсутствовал, и оператор при остановленном захвате видел 21.4 вместо 0.0. Тесты: 21 приёмочный независимого тестера (`tests/test_plugin_levels_ownership_acceptance.py`) + 38 hazard автора; гейт фреймворка 8420 passed / 8 skipped.
- **2026-08-16:** уровень плагина едет сборщиком тика (ADR-PM-038, план `telemetry-stage6` задача 3.5, вход K-8): `ctx.declare_metric(имя)` + `ctx.publish_metric(имя, значение)` на `PluginContext` и `SubPluginContext` (+ `from_parent`, обе дороги сразу). Второго реестра НЕТ — имя объявляется существующим `observability_declarations` (плоскость `KIND_METRIC`), тем же, что открыл `GATED_METRICS`; второго сборщика тоже нет — `build_plugin_levels` один на push (`ProcessHeartbeat._publish_telemetry_to_tree` → `processes.<p>.state.<имя>`) и на опрос (`current_levels_snapshot` → `introspect.telemetry.levels`). Хранилище `PluginLevels` (порт `plugin_levels` в `IProcessServices` + атрибут класса у `ProcessModule`, одной правкой) создаётся **лениво**, на первой отдаче значения; лок нужен не ради присваивания, а потому что копия растущего словаря без него даёт `RuntimeError` (писатель — поток воркера, читатель — heartbeat). Необъявленное имя не публикуется НИКОГДА (гейт обходит каталог объявлений) и называется WARNING'ом один раз на тике, а не в `publish_metric` — порядок «объявил → отдал» на момент публикации ещё не устоялся. Универсальность судится **положительным** свойством: имя `zzz_made_up_level`, которого нет нигде в репозитории, доезжает и в дерево, и в опрос. Мигрирован ОДИН писатель — `Plugins/sources/capture` (уровни захвата); его фронты остались прямой записью, реестр семи немигрированных писателей с причинами — в `README.md`. Граница названа: `uptime`/`status`/`pid` принадлежат ПМ (знание о ЧУЖОМ процессе из своего `first_seen`) и опросом процесса не отдаются по построению. Повод — живой замер: гейт `camera_0` закрыт на `fps`, за 41.1 с `latency_ms` и `shm.boundary_crossings` дали **0** дельт, а `state.fps` — **35**, потому что писал его плагин напрямую. Тесты: 24 hazard автора (`tests/test_plugin_levels_hazards.py`) + 4 у мигрированного плагина, из них один на НАСТОЯЩЕМ `PluginContext` (`Plugins/sources/capture/tests/test_plugin.py`). `forget_declarations` получила точечную форму `names=...`: восстановление реестра повторным объявлением подменяет владельца.
- **2026-08-16:** flight recorder — кольцо ЗАПИСЕЙ процесса по вызову (ADR-PM-037, план `telemetry-stage6` задача 5.1, вход С-5): `ctx.flight_dump(reason="", /, **fields) -> bool` на `PluginContext` и `SubPluginContext` (+ `from_parent`), выгружает существующий `MemoryChannel` логгера в `<база логов>/<процесс>/flight/<ts>_<reason>.jsonl`. Своего кольца НЕТ: читается дорогой `ChannelRoutingManager.read_sink_tail`, путь резолвится дорогой файлов журнала (`log_paths.process_log_directory` — вынесена из `LoggerCore._resolved_file_path`, второй клиент). Формат JSONL, первая строка — шапка `flight_manifest` (причина, `trace_id`, источник, снимок кольца `capacity`/`size`/`written`/`evicted`); несериализуемая запись заменяется заглушкой `flight_record_unreadable`, а не роняет дамп. Живой хозяин — `FlightRecorder` на процессе (порт `flight_recorder` в `IProcessServices` + атрибут класса у `ProcessModule`, одной правкой). Ручки `observability.flight.{enabled,sink,keep,limit}` идут дорогой трёх точек и подключены на ШЕСТИ дорогах пересборки (`config.reload`, `make_observability_on_reload`, оба watcher'а оркестратора, возврат по TTL, switch рецепта у PM); readback ЖИВОГО рекордера — в `introspect.observability -> flight` и в `effective` (без него вердикт отвечал бы `unverifiable` при `checked=0`). Дефолт `enabled=false`, и это ЕДИНСТВЕННЫЙ выключатель (Р5.1-5). Три РАЗНЫХ названных отказа со своими счётчиками: `refused_disabled` (ручка), `refused_no_ring` (приёмник не объявлен / не `type: memory` / не смаршрутизирован — ловушка, в диффе не видная), `refused_failed` (диск). Ретеншен по числу файлов, голос INFO на КАЖДОЕ вытеснение; `keep=0` — без предела. Эмитент — `RobotControlPlugin` на фронте pass→reject, ПОСЛЕ `write_event(decisive=True)` и `_write_verdict` (порядок несущий: кольцо снимается в момент вызова). Секреты обходной дороги не получают — `SecretRedactor` стоит до кольца, сторож судит ФАЙЛ ДАМПА. Тесты — **82 по задаче**, шесть файлов (числа по `pytest --collect-only`): 35 hazard автора (`tests/test_flight_recorder_hazards.py`), 14 на настоящей проводке и боевом рецепте (`tests/test_flight_recorder_real_wiring.py`), 23 приёмочных независимого тестера (`tests/test_flight_recorder_acceptance.py`), 6 у эмитента (`Plugins/control/robot_control/tests/test_flight_dump_emitter.py`) и **четыре сторожа, заведённые по нулевым инъекциям** — 2 на оба файловых watcher'а оркестратора (`app_module/tests/test_observability_watcher_flight.py`) и 2 на switch рецепта у ПМ (`process_manager_module/tests/test_switch_resets_flight_policy.py`). Последние живут НЕ рядом с механизмом: `process_module` слоем ниже и импортировать `app_module`/ПМ не вправе (контракт слоёв, уже ронялся на 4.1). Инъекции: снятие рекордера по одной строке на каждой из шести дорог красит ровно свой сторож (4/4 по дорогам, которые до этого давали НОЛЬ красных); снятие лока рекордера целиком красит `test_the_dump_is_mutually_exclusive_end_to_end` 5/5 — барьер ВНУТРИ критической секции, потому что шторм потоков взаимного исключения не доказывает (прежний «сторож конкуренции» был вакуумен: снятие лока не красило ничего из 81). **Цена:** 500 записей (файл 142 КБ, 284 Б/запись) — медиана 2.96 мс, p95 3.17, max 3.24; с ретеншеном `keep=5` медиана 3.32 мс, max 6.65. Бюджет редкого события: на кадре 25 FPS это ~8% бюджета, поэтому триггер на фронте.
- **2026-08-16:** широкая запись о единице работы (ADR-PM-036, план `telemetry-stage6` задача 4.1, вход С-4): `ctx.write_event(kind, summary, /, *, unit=None, decisive=False, **fields) -> bool` на `PluginContext` и `SubPluginContext` (+ `from_parent`), носитель — существующий `log_info` (`BUSINESS`/`INFO`), нового порта записи НЕТ. `trace_id` едет **в тексте** записи (FTS5 стора не смотрит в `extra`), структурные поля — в `extra`, конверт кладётся после нагрузки. Живой хозяин отбора — `WideEventSelector` на процессе (порт `event_selector` в `IProcessServices` + атрибут класса у `ProcessModule`), сшивка `wire_event_selector` у каждого процесса. Ручки `observability.events.{first_n,every_mth}` идут дорогой трёх точек: схема `ObservabilityEventsConfig` → `wire_event_selector` + ветка в `_rebuild_and_apply` (`config.reload`, возврат по сроку, switch у PM) → readback ЖИВОГО селектора в `introspect.observability -> events` (`declared`, действующие ручки, `selected`/`skipped`/`decisive` по родам, `refused`, `kinds_saturated`). Дефолт `0/0` — поток не пишется, фронты (`decisive=True`) идут мимо отбора всегда. Исход у носителя сверяется ДВУМЯ способами (`except` + счётчик `manager_call_failures`): `ObservableMixin._call_manager` ловит исключение у себя, и без сверки счётчика поля `scope`/`level` давали `write_event=True` при нуле строк на диске. Штамп источника — часть конверта: прикладное поле `module` больше не может увести запись под чужое имя. Тесты: 46 hazard (`tests/test_wide_event_hazards.py`) + 9 на настоящей проводке (`tests/test_wide_event_real_wiring.py`, строки с диска) + 7 у эмитента (`Plugins/control/robot_control/tests/test_wide_event_emitter.py`) + 1 у оркестратора (`app_module/tests/test_observability_watcher_events.py`); 13 инъекций раунда 2, 12 совпали точно. Спаны — из `unit["trace"]` при `MULTIPROCESS_FRAME_TRACE`, иначе `spans: "off"` в самой записи. **Цена (живой стенд 2026-08-16, 21.3 ед/с):** 476 Б/запись; `every_mth=9` → 3.88 МиБ/ч (вдвое выше ориентира гейта ≤2 МиБ/ч — укладываются дефолт 0/0 либо прореживание не чаще ~1/18); фасад при закрытом отборе 661 нс, эмитент 2.14 мкс при 1 дефекте и 74.2 мкс при 500 (потолка нет).
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
