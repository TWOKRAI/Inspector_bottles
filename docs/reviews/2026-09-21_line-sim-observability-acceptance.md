# line-sim Task 1.4 — приёмка наблюдаемости второго приложения тем же зондом

Дата: 2026-09-21. Ветка `feat/line-sim`. Зонд `backend_ctl/probes/probe_observability_consumer_acceptance.py`
(параметризован коммитом `94fd0eb1`: `--app {prototype,line_sim}`, `--port`, `--log-dir`). Стенды поднимал
ведущий; без флага `FW_SHM_OWNER_INCARNATION` (как и baseline — условия одинаковые до и после).

## 1. Прототип без аргументов — поведение не изменилось

| прогон | строк | PASS | FAIL | PARTIAL | NOT_REACHED | UNVERIFIED |
|---|---|---|---|---|---|---|
| baseline ДО правки (`620be628`, env-каталог) | 51 | 41 | 1 | 3 | 5 | 1 |
| после правки, без аргументов (env-каталог) | 51 | 41 | 1 | 3 | 5 | 1 |
| после правки, `--log-dir` | 51 | 41 | 1 | 3 | 5 | 1 |

Сверка скриптом по id: порядок id совпадает, расхождений вердиктов по строкам — 0 (оба прогона после).

## 2. Сим `--app line_sim` (порт 8766)

Итерация 1 (два прогона, `LINE_SIM_LIVE=1`): 52 строки, id и вердикты совпали построчно — PASS 33 · FAIL 3 ·
PARTIAL 5 · NOT_REACHED 6 · UNVERIFIED 1 · N/A 4. **Итерация 2 (после ревью, `d2f64a75`, роль `register`):
PASS 35 · FAIL 3 · PARTIAL 5 · NOT_REACHED 6 · UNVERIFIED 1 · N/A 2** — K10/L5 стали измеримы: `set_register_verified
(camera, camera_service, gain, 1)` → `verified=True actual=1` за 26 мс, возврат 0 подтверждён; L5 медиана 26.16 мс (n=5).
Таблица ниже — итерация 2. Прогон ~98 с, после выхода порты
8766/5021/8091 свободны. Состав процессов (S1): ProcessManager, camera, mjpeg, robot — 4 из 4.

Роли зонда (prototype → line_sim): camera `camera_0→camera`; neighbor `processor→robot`; fault `renderer→mjpeg`;
ring `inspector→camera`; register `inspector/robot_control.reject_delay_ms → camera/camera_service.gain` (K10/L5);
inspector `inspector→нет` (R9/K11 → N/A); путь кадра `camera_0→processor→inspector`
→ `camera→mjpeg`. T1 — новая строка, есть только у профиля сима (у прототипа её роль играет S6, 51 строка сохранена).

## 3. Таблица вердиктов (все строки сима против прототипа)

| id | функция | прототип | сим |
|---|---|---|---|
| S1 | system_overview: состав процессов | PASS | PASS |
| S2 | capabilities: команды наблюдаемости у процесса объявлены | FAIL | FAIL |
| S3 | introspect.observability: семь секций документированного ответа | PASS | PASS |
| S4 | history.db_path из readback совпадает с файлом на диске | PASS | PASS |
| S5 | effective.log_directory ↔ каталоги журналов на диске | PARTIAL | PARTIAL |
| S6 | introspect.telemetry: gate/resolved/levels/tick | PASS | PARTIAL |
| T1 | introspect.telemetry → levels: уровень плагина приложения (ctx.publish | — | FAIL |
| S7 | supervision_status: pid и instance_restarts на старте | PASS | PASS |
| R1 | журналы процессов на диске: messages.log / system.log | PARTIAL | PARTIAL |
| R2 | SQLite-стор напрямую: схема и состав | PASS | PASS |
| R3 | history_query(kind=log, process=camera) ↔ те же строки в sqlite | PASS | PASS |
| R4 | log_tail(INFO) → пуш log.record + строка в messages.log | PASS | PASS |
| R5 | observability_tail(INFO) → пуш observability.record (kind) + файлы | PASS | PASS |
| R6 | events_page(plane=logs/errors): курсорное чтение без потери | PASS | PASS |
| R7 | watch_like_gui → telemetry_snapshot / telemetry_history (read-model) | PASS | PARTIAL |
| R8 | record_start/stop/status (flight recorder драйвера) | NOT_REACHED | NOT_REACHED |
| R9 | широкие записи (ctx.write_event) → стор; поиск по trace_id (FTS) | PASS | N/A |
| R10 | observability.sink.tail: ретроспективный хвост memory-кольца (flight_r | PASS | FAIL |
| R12 | history_query(metric=…): идентичность числа в сторе на inspection_full | PASS | PASS |
| K1a | log_level=DEBUG одному процессу (L3) — включение | PASS | PASS |
| K1b | log_level — возврат к нижнему слою (observability_reset) | PASS | PASS |
| K2 | уровень по ИМЕНИ ИСТОЧНИКА (loggers.<источник>.level) — один источник, | PASS | PASS |
| K3 | приёмник (sink) выключить/включить на лету: messages_file | PASS | PASS |
| K4 | срок правки (ttl) — авто-возврат с голосом в журнале | PASS | PASS |
| K5 | телеметрия: publisher-gate fps/latency_ms выкл/вкл | PASS | NOT_REACHED |
| K6 | плоскость чисел: правило glob по пути выключает метрику | NOT_REACHED | NOT_REACHED |
| K7 | history.level — порог записи в СТОР действует на лету (файл журнала не | PASS | PASS |
| K8 | опечатка в имени ключа (log_levl) — отказ, а не тихий успех | PASS | PASS |
| K9 | окно голоса (voices.default_window_sec) — readback | PASS | PASS |
| K10 | регистр плагина: запись с readback (set_register_verified) + аудит сес | PASS | PASS |
| K11 | ответ config.reload: `applied` называет применённую секцию events? | PASS | N/A |
| K12 | observability.persist — сделать правку постоянной (L3 → L2 спутник рец | NOT_REACHED | NOT_REACHED |
| K13 | history.purge_interval_sec — укороченный период ждёт старый срок (298  | UNVERIFIED | UNVERIFIED |
| K14 | telemetry_reconfigure(mode=replace) — оптовая секция publisher/throttl | NOT_REACHED | NOT_REACHED |
| L0 | разрешение часов на этой машине (что лежит на сетке) | PASS | PASS |
| L1 | RTT команда→ответ через роутер (introspect.status), 20 повторов × 3 ад | PASS | PASS |
| L2 | эмиссия в camera → видно в SQLite-сторе (арбитр sqlite3, опрос 5 мс),  | PASS | PASS |
| L3 | эмиссия в camera → пуш живого хвоста у потребителя (reader-поток драйв | PASS | PASS |
| L4 | state.set → пуш state.changed подписчику (qa.**), 7 повторов | PASS | PASS |
| L5 | запись регистра → readback подтверждён (set_register_verified), 5 повт | PASS | PASS |
| L6 | путь кадра camera → mjpeg: хоп-лаг между модулями | NOT_REACHED | NOT_REACHED |
| E1 | инъекция ERROR в robot → errors.log, стор kind=error, пуш, anomalies | PASS | PASS |
| E2 | необработанное исключение в потоке (threading.excepthook) → плоскость  | PASS | PASS |
| E3 | warnings.warn (captureWarnings) → журнал/плоскость ошибок | PASS | PASS |
| E4 | пол ошибок errors_floor.jsonl — пишется ТОЛЬКО когда штатный маршрут з | PASS | PASS |
| E5 | счётчики потерь у трёх плоскостей + стор (видимость, НЕ под нагрузкой) | PARTIAL | PARTIAL |
| E6 | диагностика «нет приёмника»: introspect_handlers + неизвестная команда | PASS | PASS |
| LC1 | config.reload всем процессам под нагрузкой — цена окна пересборки кана | PASS | PASS |
| LC2 | process_restart_verified(mjpeg): pid, L3, счётчики, авто-переподписка  | PASS | PASS |
| LC3 | срок сессии по умолчанию (session_ttl_sec) в readback | PASS | PASS |
| LC4 | останов: строка «store flush: N записано, M потеряно» у каждого процес | PASS | PASS |
| LC5 | порт 8766 освобождён после останова | PASS | PASS |

## 4. Разбор расхождений — куда чинить

| строка | прототип → сим | причина (наблюдение) | куда |
|---|---|---|---|
| S6, R7, K5 | PASS → PARTIAL / PARTIAL / NOT_REACHED | `gate_active=False; resolved keys=[]` — гейт телеметрии у generic-приложения не активен; K5: «0 дельт за 12 с до ручки — ось мертва». Корень двухчастный (ревью): `app_module/builder.py` — 0 упоминаний `telemetry` (проводка), **и** `apps/line_sim/system.yaml` без секции `telemetry:` (у прототипа `backend/config/system.yaml:287` `telemetry.publish`) | **carve-out во фреймворк + конфиг сима** → Task 1.5 (обе половины) |
| T1 | — → FAIL | у `camera` в `levels.state` есть `fps`/`latency_ms`/`shm`, но ключа `plugins` нет вовсе (зонд ушёл в фолбэк); ни один из трёх писателей сима — `sim_robot_host`, `mjpeg_sink` (`Plugins/sim`), `camera_service` (`Plugins/sources`) — не зовёт `ctx.publish_metric` (grep: 0); robot_host пишет только `record_metric("sim_robot.writes")` — плоскость stats. Уровни плагинов идут под publisher-гейтом (`plugins/base.py:819-822`) | два дефекта: гейт (Task 1.5) + уровни сима — Task 5.1 (счётчики наружу), не правка ради строки |
| R10 | PASS → FAIL | `observability.sink.tail flight_ring` → `success=False, записей=0`; синк `flight_ring` объявлен только в `multiprocess_prototype/backend/topology/inspection_full.yaml`, в конфиге сима его нет | **конфиг сима** → Task 1.6 (заведена в план). Зонд не пишет `reason` отказа в observed — мелкий дефект зонда, там же |
| R9, K11 | PASS → N/A | ни один процесс сима не пишет широкие записи kind=inspection (`ctx.write_event`) | N/A по построению. Итерация 1 держала N/A ещё и на K10/L5 с ложной причиной «у плагинов сима регистров нет» — ревью Fable нашло регистры `camera_service`; исправлено ролью `register` |
| S2 FAIL, S5/R1/E5 PARTIAL, R8/K6/K12/K14/L6 NOT_REACHED, K13 UNVERIFIED | одинаково | общие для обоих приложений, к симу не относятся | полоса `observability-closure`, не этот план |

## 5. Разведка: имя сервиса у `otel_export`

`service.name` = имя процесса (`Services/otel_export/resources.py:60`, `proc_name → service.name`). У двух
приложений в одном коллекторе склеится как минимум `ProcessManager`. Различитель уже есть:
`OtelExportConfig.service_namespace` (`Services/otel_export/config.py:132`, «различает ДВА приложения»),
по умолчанию пустой. У сима `otel_export` сейчас не подключён. Правило: когда подключат — `service_namespace:
line_sim` (и `inspector` у прототипа), иначе трассы двух стендов смешаются.

## 6. Break-injection (ведущий, предсказания записаны до запуска)

Тесты: T = `test_probe_acceptance_app_param.py` (независимый тестер), P = `test_probe_acceptance_profiles.py` (автор).

| инъекция | предсказание | умерло | вердикт |
|---|---|---|---|
| I1 `--app` без `choices` | T::invalid_app | ничего (под серией — флак ниже) | расхождение объяснено: неверный `--app` всё равно отбит `profile_for` → ValueError, ненулевой код, стенд не поднят. Свойство «отказ» держится другой дорогой; «отказ именно argparse'ом (код 2)» не закреплено |
| I2 дефолт порта сима 8765 | T::line_sim_default | T::line_sim_default, P::line_sim_profile_literals, P::na_row_… | ✅ |
| I3 `--port` игнорируется | T::port_override | T::port_override | ✅ |
| I4 абортная проверка на литерал 8765 | T::line_sim_default, T::port_override | **ничего** | дыра итерации 1: тестер держит 8765 занятым всегда, литерал тоже абортит. Моё утверждение «закрыть можно только живым прогоном» было **неверным** — ревью показало офлайн-пин (подмена `port_free`/`make_harness`). Закрыто тестом `test_abort_checks_the_resolved_port` (итерация 2, J2) |
| I5 прототип без `storage` | P | P::prototype_profile_equals_old_constants | ✅ |
| I6 роль camera прототипа → `camera` | P | P::prototype_profile…, P::prototype_roles_cover… | ✅ |
| I7 `na()` пишет PASS | только live (skip) | P::na_row_carries_reason… | ✅ автор закрыл то, что тестер оставил live-only |

Итерация 2 (после `d2f64a75`), предсказания записаны до запуска:

| инъекция | предсказание | умерло | вердикт |
|---|---|---|---|
| J1 роль register сима → процесс `gui` | P::register-hazard | P::test_register_role_prototype_literals_and_sim_target | ✅ |
| J2 абортная проверка `port_free(8765)` | P::abort_checks_resolved_port | P::test_abort_checks_the_resolved_port | ✅ (I4 закрыта) |
| J3 E1 — обратно литерал `'{NB}'` в f-строке | офлайн ничего | ничего | ✅ как предсказано; ловит только сверка текста — после правки E1 снова `'processor'=True`, как в baseline |
| J4 прототип register field → `gain` | P::register literals | P::test_register_role_prototype_literals_and_sim_target | ✅ |

Прототип после итерации 2 без аргументов: 51 строка, вердикты по id совпали, текстовые поля
(`family/function/control/consumer/expected/doc`, путь каталога нормализован) — **0 расхождений**.

## 7. Дефекты тестов, найденные по ходу (исправлены ведущим)

- **Флак** `test_port_override_busy_aborts`: 1 из 15 на чистом коде. Держатель порта `listen(1)` без `accept()`;
  проверка порта зондом занимала очередь, и connect «держатель жив» получал отказ. `listen(16)` → 30/30 (`bd70812d`,
  «очередь listen 1 → 16»).
- **Ложный красный live-теста**: имя `gui` искалось подстрокой и нашлось в тексте аномалии `watch_like_gui`
  (строка S1). Поиск токеном → 13 passed живьём.
- **Модель тестера по словарю вердиктов** была {PASS, FAIL, PARTIAL, N/A} — ошибка брифа ведущего, в baseline
  уже есть NOT_REACHED/UNVERIFIED. Исправлено до коммита RED-спеки.

## 8. Инцидент

Первая версия теста тестера заняла только 8766, а тогдашний зонд проверял захардкоженный 8765 → поднялся
полный стенд прототипа (7 процессов), `subprocess.run(timeout)` убил только лист, 7 детей осиротели. Погашены
ведущим (дерево 11898, старт 13:29:01, совпадает с отчётом тестера). Baseline не задет: он шёл 13:23–13:26.
Отдельно: осиротевший сим прошлой сессии (pid 5303, 12:52) погашен SIGTERM по решению владельца.

## Что осталось открытым / ненадёжно

- K10/L5 на симе мерят `gain` на бэкенде-симуляторе `camera_service` — это доказывает дорогу регистра, но не
  влияние `gain` на кадр.
- Отчёт teamlead `2026-09-21_task-1.4-teamlead.md` описывает итерацию 1 (K10/L5 как N/A) — устарел, этот отчёт главнее.
- Прогоны без `FW_SHM_OWNER_INCARNATION=1`: строки про кадры могли бы отличаться с флагом; для сравнения
  «до/после» условия выбраны одинаковыми, для абсолютных чисел сима — нет.
- Импорт зонда создаёт пустой каталог `logs_live/…` даже при `--help` (поведение до задачи, не менялось).
- Исходник команды в плагине синхронизирован с материализованной копией ведущим (до правки они совпадали).
- K10/L5 возвращают регистр не в `finally`: исключение из `set_register_verified` посреди строки оставит
  значение записанным. Для сима без эффекта (бэкенд-симулятор `gain` не применяет, прогон закончил на 0 —
  `camera/system.log`: 8 `register_update`, последняя 0); для боевой камеры — follow-up (ревью Fable, итерация 2).

## Ревью

Fable (`reviewer`, синхронно): итерация 1 — CHANGES_REQUESTED (блокер: K10/L5 прятались за N/A при живых
регистрах `camera_service`; I4 закрывается офлайн; мёртвая диагностика E1), итерация 2 — **APPROVED**.
