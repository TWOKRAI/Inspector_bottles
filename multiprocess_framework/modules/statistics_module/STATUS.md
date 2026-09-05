# statistics_module — Статус рефакторинга

## Текущий этап: 5 / 8

## Оценки (0–10)

| Критерий        | Оценка | Комментарий                                                                   |
|-----------------|--------|-------------------------------------------------------------------------------|
| Код             | 9      | ChannelRoutingManager + AggregationWindow; sentinel-паттерн для broadcast     |
| Тесты           | 9      | Число смотреть командой — `pytest multiprocess_framework/modules/statistics_module/tests --collect-only -q` (**207** на 2026-08-13). Точное число в тексте устарело дважды за одну задачу 2.2, поэтому здесь стоит команда, а не литерал. Покрыто: integration, adapter, thread-safety, tags, подавление пустых, предел строки, канал в hub, бакеты/слияние/потолок серий (2.2), приёмка независимого тестера + бенч с эталоном прежней модели |
| Документация    | 10     | DECISIONS.md (ADR-SM-001…013), §6.15 в ARCHITECTURE.md, README fix              |
| Связанность     | 9      | Наследует CRM; IStatsManager(IChannelRoutingManager); StatsPlugin-совместим   |
| Дублирование    | 9      | _metric_key дублируется в core/ — приемлемо (изолированные слои)             |
| Работоспособность | 9    | Корпус модуля зелёный (см. команду выше); broadcast, теги, flush работают корректно |

## Чеклист рефакторинга

- [x] Этап 0: Критические баги исправлены
  - [x] Баг N-кратного счёта (enqueue per channel → sentinel _STATS_SENTINEL)
  - [x] Баг _managers (getattr → get_manager("logger"))
  - [x] Несогласованный merge тегов
  - [x] Дублирование buffer.start() / is_initialized в initialize()
- [x] Этап 1: Архитектура — IStatsManager(IChannelRoutingManager), StatsManagerConfig
- [x] Этап 2: Ядро — StatsManager(ChannelRoutingManager), AggregationWindow, MetricRecord
- [x] Этап 3: Каналы — LogStatsChannel, FileStatsChannel, HubStatsChannel (2.1, ADR-SM-010)
- [x] Этап 4: Адаптер — StatsAdapter (get_metrics, reset_metrics, stats_snapshot, flush_stats)
- [x] Этап 5: Формализация — DECISIONS.md (ADR-SM-001…006), ARCHITECTURE.md §6.15, тесты integration/adapter/thread-safety
- [ ] Этап 6: Интеграция — добавить StatsManager в process_managers.py
- [ ] Этап 7: Graceful shutdown — тест flush перед остановкой в реальном процессе
- [ ] Этап 8: Стресс-тест — concurrent writes, высокая нагрузка, tag cardinality; полная интеграция с process_manager_module

## Обновление 2026-04-01

- Пути файлов метрик по умолчанию резолвятся через **`logger_module.core.log_paths.resolve_log_file_path`** (не в дереве `modules/` при pytest; ADR-111).

## Обновление 2026-04-03

- **`StatsManagerConfig`**: **`ChannelRoutingConfig`** импортируется из публичного **`channel_routing_module`** (глобальный ADR-108 / ADR-CRM-005, единый стиль с логгером).

## Обновление 2026-08-13 — задача 2.2 «Пределы до доставки» (ADR-SM-011)

- **`timing` и `histogram` переведены на фиксированные бакеты** (`count`/`sum`/`min`/`max`/
  `bucket_counts`, границы `DEFAULT_DURATION_BUCKETS_SEC` в СЕКУНДАХ, семантика `le`).
  Списков наблюдений не осталось ни у одной из двух дорог. Форма агрегата сохранена
  ключ-в-ключ (`count`/`min`/`max`/`avg`/`p95`), добавлены `sum` и `buckets`; границы едут
  один раз на снапшот ключом `bucket_bounds`. `p95` стал ОЦЕНКОЙ по бакету — цена названа.
- **Потолок кардинальности `observability.stats.max_series`** (дефолт 1000, `0` — без
  предела) на ОБЕИХ накопительных позициях: окно агрегации и живой слой `_metrics`. Один
  страж `core/cardinality_guard.py`, два экземпляра. Голос — раз на условие, на такте окна,
  с числом, первыми 5 именами и адресом ручки. **На позиции ОКНА это стало правдой только
  2026-08-17** (поправка в ADR-SM-011, решения 5 и 5б): до неё голос окна говорил «опущено
  серий 0» при верном машинном числе, называл имена первого эпизода и звучал каждое окно.
  Отчёт закрытия передаётся в `speak(report)` аргументом и несёт вместе с числами право на
  голос; условие снимает такт, в котором серии ЗАВОДИЛИСЬ и ни одна не отказана, либо явное
  освобождение места (`reset_metrics` → `lift()`, `set_limit`). Промежуточная редакция той
  же правки снимала условие любым тактом без отказов и **сломала обе позиции** (живой слой:
  1 голос за срок процесса → 6; окно: второй голос на каждой смене темпа) — поймано ревью,
  воспроизведено, закрыто требованием «пустой такт не доказывает ничего». Счётчики публикуются через
  `PLANE_COUNTER_KEYS` (не через `LOSS_COUNTER_KEYS` — довод в ADR).
- **Слияние записей** (`MetricRecord.merged_with`) — чистая функция; ассоциативна у counter
  и распределений, у gauge ассоциативности НЕТ по природе типа (названо в докстринге).
- Измерено: память записи +208 Б против +646 584 Б у прежней модели на тех же 20 000
  наблюдений; наблюдение подорожало на +0.27 мкс (0.40 против 0.13), `aggregate` на 5 000
  наблюдений подешевел с ~62 до ~1.3 мкс; `buckets` стоят +84 Б на метрику в строке
  `performance.log` (из 40 метрик в 2048 Б влезает 8 вместо 12).
- **Ревью 2-й итерации (7.5/10) закрыто двумя правками существа.** (1) `series_dropped`
  считал ОТКАЗАННЫЕ ЭМИССИИ, а не серии, из-за чего `total_count` завышался и запись
  противоречила сама себе; теперь считаются различные ключи (множество ограничено тем же
  `max_series`, при насыщении — признак `series_dropped_is_lower_bound`), а счётчик эмиссий
  остался под именем `observations_dropped`. (2) Сетка бакетов расширена тремя
  под-миллисекундными границами: 99.28 % боевых наблюдений лежали в первом бакете прежней
  сетки, `p95 == max` был у 63.6 % агрегатов. Доля `p95 == max` на общем корпусе
  39.2 % → 24.0 %, занято бакетов на боевых величинах 2 → 5.

## Известные проблемы

- `_metric_key` дублируется в `stats_manager.py` и `aggregation_window.py` —
  оба работают корректно, но при изменении логики нужно менять в двух местах.
- `FileStatsChannel` пишет в режиме append без ротации файлов.
  Для production нужно добавить RotatingFileHandler или ограничение размера.
- `retention_seconds` в `StatsManagerConfig` **объявлен и мёртв** — не читает никто.
  Задача 2.2 его намеренно не подключает (ту же тревогу закрывает `max_series` счётом, а не
  временем; две дороги к одной цели разошлись бы). Решение — ADR-SM-011, п. 8.
- `buckets` и `sum` в строке `performance.log` сокращают число метрик, влезающих в предел
  2048 байт, с 12 до 8. Формат этого приёмника 2.2 не меняет; потеря видна голосом предела
  в самой строке.
- При `shutdown()` двойной flush: `flush()` + `buffer.stop()` (который тоже flush).
  Второй отправляет ПУСТОЙ снапшот, и с задачи 3.2 это **намеренно** (ADR-SM-008):
  периодические пустые снапшоты подавляются, а финальный — единственная запись, по
  которой снаружи видно, что плоскость дошла до останова живой (`probe_b3` S4).
  «Неэлегантно» — прежняя оценка; теперь у второго flush есть работа.
- **Объём непустого снапшота не ограничен ничем.** Он дампит весь список метрик
  питоновским `repr` в ОДНУ строку лога: замер на живых прогонах — средняя строка
  3089 и 9794 байт, максимум **40 128 байт** при `count=306`. Отсюда 2.6–5.5 МиБ/ч на
  8 процессов, то есть непустые снапшоты дают 92–97 % объёма плоскости, а пустые —
  3–8 %. Это НЕ закрыто задачей 3.2 (она про пустые) и передано владельцу: пересмотр
  объёма снапшотов — вход этапа 6 плана `observability-roadmap`.
- Нет MetricsRetention — старые метрики не вычищаются автоматически
  (поле `retention_seconds` в конфиге существует, но логика не реализована).
- RouterManager-интеграция (отправка снапшотов в другой процесс) не реализована.

## История изменений

| Дата | Что сделано |
|------|-------------|
| 2026-03-31 | ADR-108: убран избыточный `build()` у `StatsManagerConfig` (наследует `SchemaMixin.build`) |
| 2026-04-03 | Импорт `ChannelRoutingConfig` из публичного `channel_routing_module` (ADR-114) |
| 2026-04-10 | DECISIONS.md (ADR-SM-001…006), ARCHITECTURE.md §6.15, тесты integration/adapter/thread-safety, README fix; этап 4→5 |
| 2026-07-26 | **Ф0.6:** StatsManager получил симметрию с логгером — `set_sink_enabled` / `add_tap` / `remove_tap` / `_fallback_log` (наследуются из CRM) + собственный `_recreate_channel`. `_setup_channels` разложен на сборщики по одному имени (`_build_log_channel` / `_build_file_channel` / `_build_fallback_channel`), служебные имена каналов названы константами `STATS_LOG_CHANNEL` / `STATS_FALLBACK_CHANNEL`. Адресуется командой `logger.sink.*` с `manager="stats"`. Анти-дубль-счёт (`_STATS_SENTINEL` + broadcast в `_do_flush`) НЕ тронут — закреплён характеризационным тестом | Ф0.6 |
| 2026-08-11 | **3.4:** объём строки снапшота ограничен ручкой `log_line_max_bytes` (дефолт 2048 байт, `0` — без предела); опущенные метрики названы числом в самой записи. Потолок фона 1.24 МиБ/ч против прежних 2.6–5.5 (замер по 416 живым строкам: медиана 2582, максимум 53 900 байт). Компактная запись вместо `repr` отвергнута замером — 56.8 % объёма, гейт не закрывает, а смена формата принадлежит этапу 6. **ADR-SM-009** | 12 тестов, 7 инъекций |
| 2026-08-24 | **Ф3/3.1 «порт наблюдений»:** модуль получил ВТОРОГО жителя — `observation/observation_manager.py` (`ObservationManager(ChannelRoutingManager, ObservationPort)`), четвёртый канонический слот `observation` рядом с logger/stats/error. Порт **оборачивает** существующее хранилище уровней `PluginLevels` (живёт в `process_module/heartbeat/telemetry.py`, не переезжает), резолвя его на каждом обращении — держатель остаётся один, атрибут процесса. Клиенты: `ProcessHeartbeat` (три шага тика, `PLUGIN_LEVELS_ATTR` из него ушёл целиком) и `PluginContext` (объявление/публикация/снятие через `for_plugin(...)`-хендл). Ленивый фолбэк сохранён и назван: публикация идёт из `configure()`, раньше `start()`. **ADR-SM-012** | 6 приёмочных (независимый тестер, вслепую) + 24 hazard автора, 8 инъекций |
| 2026-08-25 | **Ф3/3.1, правка по ревью:** флаг `create` доведён до конца дороги — `ObservationManager.levels(create=…)`, а не безусловный `get_or_create_plugin_levels`. До правки один вызов `ProcessHeartbeat._level_names()` на настоящем `ProcessModule` поднимал `plugin_levels` из `None`: обещание «читатель не заводит хранилище» держалось везде, КРОМЕ боевой сборки. Цена названа — читательские дороги переживают отсутствие хранилища пустой проекцией (`set()`/`{}`/`()`/no-op), заводит его РОВНО `publish`. Прежний сторож флага был вакуумен (звал резолвер по хосту без слота, то есть проверял ступень 2, а не читателя) — заменён парой на ДВУХ раскладках через настоящий `ProcessHeartbeat`. **ADR-SM-012** | 28 hazard автора (+4), 6 инъекций, совпало 5/6 |
| 2026-08-25 | **Ф3/3.2 «записи порта в хабе»:** уровни плагинов, публикуемые тиком в дерево, теперь ВТОРЫМ адресатом дублируются записями `kind=observation` в `ObservabilityHub` процесса — четвёртый канал рядом с `log`/`error`/`stats`, под ТЕМ ЖЕ publisher-гейтом (второго гейта нет). Хвост и стор видят уровни существующим дренажом, тем же путём, что `stats` (`drain_process_observability`); адаптер этот ключ не переигрывает — петли нет. `introspect.observability` называет плоскость секцией `"observation"` (`effective`/`provenance`/`counters`) БЕЗ новой команды в словаре; `writers` строится независимо от hub'а. Форма записи — `ObservationRecord(SchemaBase)` (`observation/observation_manager.py`), Dict at Boundary через `to_dict()`. Закрывает долг `docs/OBSERVABILITY_MAP.md` §5.1/C1 («доставка метрик плагина в стор») — другой дорогой, чем предполагала запись (не `kind=stats`, а `kind=observation`); отмечено в карте §5.4. **ADR-SM-013** | 8/8 приёмки (независимый тестер, вслепую) + 6 hazard автора; самопроверка автора (отключение вызова) красит 7/8 приёмки + 3/6 hazard как предсказано |
| 2026-08-26 | **Ф5, доработка по синхронному ревью — три блокера + два значительных.** B1: `ObservationPort._deliver_number` у голого вида (ступень 2 резолвера) больше не тихий `return` — считает потерю (`WeakKeyDictionary`, ключ — хранилище `PluginLevels`, `__weakref__` добавлен слотом) и говорит один раз (`bare_port_number_losses(store)`). B2: `attach_observation_port` отказывает (`False`, без подмены `_observation_port`), если у порта нет `add_tap` — до правки `bare = ObservationPort(...)`; `attach(bare) -> True` докладывал успех без единой доставки обратно; `test_f5_single_writer_acceptance.py::test_m5_...` правлен ТРЕТЬЕЙ записью (муте для attach — теперь `ObservationManager`-наследник, а не голый порт). B3: `_emit_to_taps` (БАЗОВЫЙ `ChannelRoutingManager`, все четыре наследника) получил ПЯТЫЙ класс `LOSS_COUNTER_KEYS` — `tap_write_errors`; `ObservationManager.get_stats()` — три собственных счётчика (`numbers_delivered`/`numbers_dropped_by_sink_error`/`numbers_suppressed_reentrant`); первая редакция `numbers_delivered` (дифф общего счётчика до/после) давала `0` вместо `5` под реентерабельной нагрузкой — найдено СОБСТВЕННЫМ тестом, исправлено проверкой `_tap_depth.active` до вызова; ЭТА же редакция брала `_miss_lock` на КАЖДОЙ доставке (лок на ЗДОРОВОМ пути — нарушение собственного инварианта `_miss_lock`), что покрасило `test_plugin_stats_road.py::TestTheCostOfTheHotPath` (бюджет 5.0 мкс) в ПОЛНОМ гейте (не в модульном) — снят лок, счётчик заявлен неатомарным под конкуренцией. S1: `_MockObservationPort` (`process_module/plugins/testing.py`) стал наследником `ObservationPort` над реальным приватным `PluginLevels()` — `for_plugin`/`declare`/`publish`/`retract` больше не роняют `AttributeError`. S2: `observability_counters()` получил `observation=` (рядом с `logger`/`error`/`stats`); `_safe_get_manager()` защищает вызов от латентного дефекта `ProcessManagerProcess.get_manager` (соседний процесс, не в скоупе задачи) — вскрыто ПОЛНЫМ гейтом, не модульным. **ADR-SM-014**, раздел «Доработка по синхронному ревью Ф5». | 12 новых тестов (`test_f5_review_blockers.py`, включая 2 break-injection) + 5 новых (`test_mock_observation_port_levels.py`, включая break-injection). Полный гейт: 8928 passed / 8 skipped / 1 xfailed / 0 failed |
| 2026-08-26 | **Ф5/Task 5.2+5.3 «один писатель чисел — StatsManager как вид поверх порта».** Итерация 1: `ObservationPort` получил числовой фасад (`record_metric`/`increment`/`record_timing`/`gauge`/`histogram`, один диспетчер `_route_number`/`_deliver_number` — образец `ErrorManager._route()`); `ObservationManager` доставляет числа CRM-tap'ом (`_emit_to_taps`), НЕ через `ObservabilityHub` (потеря на `drop_oldest` + петля через `drain_adapter.apply_stat`, обе причины проверены). `StatsManager.attach_observation_port(port)` — после вызова четыре пишущих метода форвардят порту, `_on_port_record` (tap-колбэк) — единственная точка входа в `_ensure_record`/буфер для ЛЮБОГО источника. Без attach — старый прямой путь: фолбэк для менеджера, **построенного ВНЕ сборки** (standalone, тесты соседних модулей) — НЕ для 57 боевых вызывающих дороги 3 (те в боевой сборке приходят на уже подключённый экземпляр; первая редакция этого пункта объясняла причину неверно, поправлено итерацией 2). `PluginContext._stats_call` резолвит порт вместо `services.stats_manager` — дорога 1 идёт через порт буквально. Боевая проводка — `ProcessManagers.create_all` зовёт attach сразу после создания обоих менеджеров. **Итерация 2 (владелец, разбор спора):** обход фолбэка стал НАБЛЮДАЕМЫМ — `StatsManager.observation_bypasses: Dict[str, int]` (счётчик по методу) + WARNING один раз на метод (`_note_observation_bypass`, образец `ObservableMixin._note_manager_call_failure`); в боевой сборке обязан быть пустым словарём — теперь проверяемый факт. Приёмочный тест М5 (`test_f5_single_writer_acceptance.py`) ПОЧИНЕН — конструкция была неверна (структурно противоречила S-4 без чужого архитектуре синглтона), правка не «под реализацию», а под БОЕВУЮ ПРОВОДКУ: явный `attach_observation_port` в обоих плечах, СВОЙ порт на каждого писателя, `_MutedObservationPort` теперь глушит и `_deliver_number`; побутно найден и исправлен разрушающий двойной дренаж `hub.drain_stats()` в харнессе теста. Новый файл `process_module/tests/test_observation_port_boot_wiring_acceptance.py` — `ProcessManagers.create_all()` НАСТОЯЩИМИ объектами (не двойниками): break-injection (`del attach_observation_port`) роняет 3 из 4 тестов немедленно, доказывая, что двойник `_MockObservationPort` этого не поймал бы. **ADR-SM-014** (раздел «Спор разобран», решение окончательное). | Итерация 1: 8 hazard автора (`test_observation_port_aggregation_hazards.py`). Итерация 2: +4 hazard/приёмки (`test_observation_port_boot_wiring_acceptance.py`, включая break-injection на переименование). Независимая приёмка: S-4 и М5 **оба зелёные**. Полный гейт: 8898 passed / 8 skipped / 1 xfailed / 0 failed |
| 2026-08-26 | **Ф5-добор по синхронному ревью — блокер Б1 (второй заход) + блокер З3.** ADR-SM-014/B3 уже вводил `numbers_delivered`, но объявленный там различитель («число > 0 отличает живую плоскость от мёртвой») оказался ложным — воспроизведено дважды (5 записей при нуле tap'ов давали тот же `delivered=5`, что и при живом приёмнике; `attach → 1 → remove_tap → 4` растил `delivered` на все 4 «потерянных»). Причина: `_deliver_number` инкрементил счётчик, не зная исхода `_emit_to_taps` (тогда `-> None`). **Б1:** `_emit_to_taps` теперь возвращает `int` (ADR-CRM-016, правка БАЗЫ), ноль принявших идёт в новый `numbers_dropped_no_sink`, а не в `numbers_delivered`; различитель — ПАРА (`numbers_delivered > 0` И `numbers_dropped_no_sink == 0`), прежняя ложная формулировка убрана из докстринга `get_stats()`, а не смягчена. **З3:** `attach_observation_port` докладывал `True` по форме (тождество объекта / `callable(add_tap)` / присвоение поля ДО подписки) — теперь спрашивает факт через `has_tap()` (ADR-CRM-016) ПОСЛЕ `add_tap`, порядок операций развёрнут («новый → старый»: подписаться на новый раньше, чем снять со старого — иначе отказ новой подписки оставлял менеджера при уже отвязанном старом). Побочная находка сквозного теста — **З6**: `observation_port()` глотал исключение ступени 1 резолвера (`get_manager` бросает у `ProcessManagerProcess`) в `None`, из-за чего плоскость УРОВНЕЙ (не только счётчиков, для которых это уже чинил S2 в ADR-SM-014) молча теряла диагностику; закрыто в `process_module` (см. `process_module/DECISIONS.md`, ADR-PM-043). **ADR-SM-015.** | 25 новых (19 `test_f5_followup_delivery_and_attach.py` + 6 `process_module/tests/test_f5_followup_manager_lookup.py`); соседний `test_f5_review_blockers.py` (12, прошлый круг) остаётся зелёным — 37 passed в этом срезе; полный гейт этой правкой документации не гонялся |
| 2026-09-01 | **Ф2/2.1 «одна политика на плоскость чисел».** Метрики (`record_metric`/`increment`/`gauge`/`record_timing`/`histogram`) теперь решаются ТЕМ ЖЕ glob-правилом `observation.rules`, что и уровни, по пути `processes.<P>.stats.<имя>` (Р-2а; теги в путь не входят). Гейт — `NumbersGate` в новом `observation/numbers_gate.py`, стоит в `ObservationPort._route_number` ДО сборки записи, то есть в единственном шве всех трёх входных дорог (фасад, слот-дорога `ObservableMixin`, дорога плагина мимо менеджера); М5 цел — фильтр ВНУТРИ пути доставки, `observation_bypasses` пуст. Расписание вынесено в ОБЩИЙ с уровнями класс `PathSchedule` (`TelemetryGate._next_due` остался живым видом на него) — второй машины расписания нет. `stats.enabled` сменил смысл на ПЛОСКОСТЬ (Р-3а, **ADR-PM-046**): `false` — числа не собираются вовсе, гейт плоскости в шве `_apply_metric`; прежний смысл переехал в `stats.log_snapshots` (дефолт `true`). Наружу: `introspect.observability` → `stats.policy` (правила/попадания/`dropped_by_rule`), `effective.stats.plane_disabled`, счётчики `numbers_policy_dropped` / `numbers_policy_throttled` (один адрес чтения — `StatsManager.get_stats()`). **Бенч шага 5 НЕ взят** — цену задаёт `ObservationPolicy.resolve`, лечится задачей 2.4 (числа в ADR-PM-046). | 9/9 приёмки независимого тестера (написана до реализации) + 20 hazard/паритет автора (`test_f2_numbers_policy_hazards.py`, паритет на БОЕВОМ `system.yaml` с живым контролем) + 4 теста проводки (`process_module/tests/test_f2_numbers_policy_wiring.py`). Регрессия трёх модулей: 3806 passed |
| 2026-09-05 | **Ф3/3.1 «одна форма числа».** Заведён `NumberRecord(SchemaBase)` (**добор того же дня, вердикт CTO: файл живёт в `channel_routing_module/observability/number_record.py`, не в `statistics_module/core/` — ADR-CRM-017**) (`name/kind/value|aggregate/tags/unit/ts/writer`, `to_dict()`), и ЕДИНСТВЕННАЯ точка чтения трёх диалектов числа `NumberRecord.from_hub_record()` (агрегат одной метрики, hub-запись `metric/value/metric_type`, запись порта `writer/metric/value`); снапшот окна числом не является и читается как `None`. `LogStatsChannel` помечает строку снапшота `origin=stats_snapshot`, и store-tap её больше не берёт — человеческая копия остаётся в `performance.log`, вторая дорога в стор срезана (19 % строк / 39 % байтов стора по замеру живого файла). Форма ПРОВОДА не менялась: три dict'а между процессами прежние, `NumberRecord` — форма внутри процесса. | 36/38 приёмки независимого тестера (2 упираются в противоречия внутри самого набора, см. отчёт) + 21 hazard автора (`channel_routing_module/tests/test_task_3_1_hazards.py`, включая golden-path на ЖИВОЙ проводке LoggerManager+tap+store); инъекции автора И1/И2/И3 красят ровно предсказанное. Гейт фреймворка: 9734 passed |
