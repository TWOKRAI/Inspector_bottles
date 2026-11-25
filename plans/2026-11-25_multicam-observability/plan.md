# Plan: наблюдаемость многокамерного инспектора — волна 1 (личность прибора, здоровье потока, триггер считывателя, имя процесса в логе)

- **Slug:** multicam-observability
- **Дата:** 2026-11-25
- **Статус:** DRAFT
- **Ветка:** (заполняет лид; база — `integ/multicam-obs`, `85a7906d1`)
- **Ревью стадии 0:** итерация 1 — CHANGES REQUESTED по W1-a, W1-b, W1-c; правки внесены (ред. 2)
- **Основание:** аудит `docs/reviews/2026-11-25_obs-audit-multicam.md` (ч.1), `…-2-control-tasks.md` (ч.2, T0-T11), `…-3-reliability-cto-map.md` (ч.3, инварианты 9.5).

## Цель

Закрыть причины, которые показал стенд 2026-11-25, а система не увидела: двойное перечисление камеры (второй IPv4 на адаптере, молчаливый `found[0]` в `driver.py:262-277`); невидимое здоровье потока; запись триггера считывателя, которая не доходит до прибора (`sdk_plugin.py:153-160`); строки плагинов без имени процесса (`[-]`). Слои: framework -> Services -> Plugins -> prototype, обратных импортов нет; prototype и frontend не меняются.

1. Перечисление по политике подсети (ниже); `identity.enum_matches` в state; WARNING на каждый неочевидный выбор; отказ со списком, если ни одна запись не в подсети.
2. `incomplete`, `lost_packets`, `lost_frames`, `trigger_lost` — уровни плагина камеры (`introspect_telemetry` -> `levels.state.plugins.<plugin>`); события `identity` и `stream`; одна INFO при входе в захват.
3. Живая запись `trigger_mode`/`trigger_source`/`trigger_period_ms` применяется перезапуском захвата. `register_update` всегда отвечает `success True` (значение в регистре), а `set_register_verified` сверяет только регистр до и после. Поэтому отказ прибора громкий в логе ERROR, health и `last_error`; «verified» не значит «прибор изменился» до read-back (T5 шаг 2).
4. Строки плагина из `configure` и `start` несут `[<имя процесса>]`.

## Решения лида (2026-11-25)

- **Политика подсети (W1-a, уровень владельца).** Записи = все перечисления нужного serial/ip. Одна запись — взять; вне подсети камеры — WARNING. В подсети одна и больше — наименьший `host_ip`; WARNING со списком — при `enum_matches > 1` (всего совпадений serial/ip, не записей в подсети) (машина с двумя адресами в одной подсети работает; запрещён молчаливый выбор). Несколько и ни одной в подсети — отказ `PortError` kind `not_found` со списком (ip, mask, host_ip, mac). Имя состояния — Р6.
- **W1-b отклоняется от текста аудита.** Аудит (ч.2, T5 шаг 1) просил «отказ живой записи». Делаем применение перезапуском захвата (`apply="restart"`, как у камеры). Отказ некуда встроить: в framework есть только статическое вето (`readonly` и уровень доступа: `manager.py:202` -> `field_meta.py:371-373,407-408`), динамического вето по политике поля нет, колбэк подписки зовётся после записи. Новый хук вето — правка framework для всех плагинов. `readonly` скрыл бы поля от правки в инспекторе. Лид сообщает владельцу.
- **W1-c, вариант (а).** Строка `start` плагина тоже красная до правки: `boot()` (`plugin_orchestrator.py:237,262`) идёт на шаге 6 (`process_module.py:1060-1061`), до шага 9. Оба теста — в REDS; охранный — строка из `shutdown`.
- **База красных** — `baseline-red.md` (шаблон в каталоге плана; лид заполняет на `85a7906d1` до старта developer-ов: радиусы задач, красный на `main` `test_plugin_observability`).
- **W1-a и W1-a2 сливаются одним шагом.** W1-a добавляет член `device_info` в `@runtime_checkable DevicePort`, `MvsPort` получает его только в W1-a2; между ними красные `test_driver_mvs.py::test_isinstance_device_port_mvs` (`:332-333`) и `TestMvsContract::test_isinstance_device_port` (`:319`, `port_contract.py:98`). Обе задачи делаются по порядку на одной интеграционной ветке, слияние — один шаг.

## Порядок выполнения

- Task W1-a: контракт личности, выбор по подсети, здоровье потока в ядре камеры и фейке [PENDING]
- Task W1-a2: порт `mvs` заполняет контракт из полей SDK (после W1-a) [PENDING]
- Task W1-b: живая запись триггера считывателя через перезапуск захвата [PENDING]
- Task W1-c: база контекста логгера до загрузки плагинов [PENDING]

W1-a2 отделена от W1-a: вместе 8 файлов при пределе брифа 6. Граф: W1-a -> W1-a2; W1-b и W1-c независимы. Волна писателей: W1-a, W1-b, W1-c параллельно (3 worktree); W1-a2 — сразу после W1-a на той же ветке, слияние пары W1-a + W1-a2 — одним шагом.

### Непересечение файлов (проверено на `85a7906d1`)

- W1-a: `Services/camera_device/{interface.py, __init__.py, plugin_base.py, testing/fake_port.py, tests/test_stream_health_hazards.py}`; tester `Services/camera_device/tests/test_identity_stream_contract.py`.
- W1-a2: `Services/hikvision_camera/{driver.py, tests/test_driver_mvs.py, tests/test_driver_identity_stream.py}`.
- W1-b: `Services/code_reader/{plugin/sdk_registers.py, plugin/sdk_plugin.py, core/sdk_reader.py, tests/test_sdk_trigger_live_hazards.py}`; tester `…/tests/test_sdk_trigger_live_contract.py`.
- W1-c: `multiprocess_framework/modules/process_module/{core/process_module.py, tests/test_log_base_context_order.py}`; tester `…/tests/test_plugin_log_proc_name_mp.py`.
- Пути не совпадают. `git grep -l "camera_device" -- Services/code_reader` -> пусто. `git grep -l "code_reader" -- Services/camera_device Services/hikvision_camera` -> только тексты (`DECISIONS.md`, `README.md`) и сторож `tests/test_fake_port_hazards.py:159` (запрет такого импорта), импортов нет.

## Цепочка

Стадия 0: `reviewer` (sonnet) -> слепой `tester` (W1-a, W1-b, W1-c; worktree на коммите ДО реализации) -> `developer` (один на задачу) -> инъекции (предсказания лида ДО прогона) -> стадия 5: `reviewer` (opus для W1-a, W1-c; sonnet для W1-a2, W1-b). W1-a2 — без tester-а: developer с REDS в брифе. Спавн: `python scripts/plans_ledger.py brief <id> --plan plans/2026-11-25_multicam-observability` (`<id>` и `<id>.tester`).

## Приёмка (литералы — в брифах)

- **W1-a.** Фейк: записи `host_ip` 169.254.49.100 и 192.168.1.100 при ip 192.168.1.20/24 -> выбрана .100, `enum_matches 2`, WARNING; 192.168.1.101 и .100 -> выбрана .100; обе вне подсети -> `not_found` со списком; номера 1, 2, 5 и потерянные пакеты 3 -> `lost_frames 2`, `incomplete 1`, `lost_packets 3`; индексы 10, 11, 14 -> `trigger_lost 2`.
- **W1-a2.** Две структуры GigE одного serial -> в `MV_CC_CreateHandle` ушла структура с `nNetExport` 192.168.1.100.
- **W1-b.** `register_update trigger_mode On` при захвате -> второе открытие и `TriggerMode=On`; отказ узла -> `applied=False` ERROR; неудачный перезапуск -> откат на прежний режим; то же значение -> без перезапуска.
- **W1-c.** Процесс spawn: строки `configure`/`start` плагина с `[w1c_child]`.

## Матрица инъекций (имена; предсказания пишет лид)

- W1-a: `select_first_match`, `subnet_check_inverted`, `lowest_host_ip_ignored` (первая из подсети вместо наименьшей), `ambiguous_returns_first`, `no_enum_warning`, `no_outside_subnet_warning`, `fake_selects_without_entries` (фейк зовёт `select_device` при `enum_entries=None`), `device_info_not_reset_on_close`, `open_logged_not_atomic`, `lost_frames_counts_wrap`, `lost_frames_off_by_one`, `incomplete_counts_packets`, `baseline_not_reset_on_opening`, `levels_not_published`, `stream_from_identity`, `identity_none_during_regrab`, `identity_stale_after_refusal` (`_identity_last` не сброшен на `opening`).
- W1-a2: `driver_select_takes_first`, `driver_select_ignores_index`, `driver_ignores_nLostPacket`, `driver_mask_from_ip`, `driver_trigger_zero_not_none`, `driver_reads_in_get_frame`.
- W1-b: `apply_meta_missing`, `no_subscription`, `restart_skipped_when_held`, `set_trigger_while_running_allowed`, `param_errors_ignored` (`applied=True` при отказе узла), `no_rollback_after_node_refusal`, `no_fallback_to_old`, `same_value_restarts`, `except_without_last_error`, `no_take_after_exception`, `lock_not_held_by_commands` (убивает только `test_concurrent_take_device_waits_for_callback`), `reconfigure_doubles_subscriptions`, `unsubscribe_missing_in_shutdown`.
- W1-c: `base_context_back_to_step9`, `base_context_without_proc_name`, `proc_name_via_push_context` (потоковый контекст: убивает тест потока шага 6). Мутант «второй вызов затирает базу» снят: вызов после переноса один, а merge живёт в `logger_core.py` вне FILES.

## Лестница проверки

1. Юнит на фейк-порте / фейк-приборе (tester + опасности developer-а), `machine_gate.sh light`.
2. Проводка настоящих объектов: W1-a — плагин + `DeviceSession` + `WorkerManager`; W1-b — `RegistersManager` + `PluginOrchestrator`; W1-c — процесс spawn.
3. Радиус (medium, по каталогу): `Services/camera_device/tests`, `Services/hikvision_camera/tests`, `Services/code_reader/tests`, `process_module/tests`, `logger_module/tests` — против снимка лида.
4. Стенд — позже, по слову владельца, в окне `stand`: временно вернуть второй IPv4 -> WARNING, `enum_matches 2`, картинка есть; A/B 20 мин по 9.5; нагрузка потока-владельца (`effective_hz`, `pacer_late`) — там же.

## Откат

Задача — один коммит; откат — `git revert <sha>`. W1-a2 откатывается раньше W1-a. Миграций и новых полей конфига нет.

## Риски и фаза A gui-frame-path

- Frontend не трогается. Инварианты ч.3, 9.5: `LatestMailbox` — один кадр на ключ, учёт `bytes_held`; `dispatch` кладёт ссылки SHM без копии, копия только в `restore_for_show` в Qt-потоке; один читатель окна `FramePump.stats(reset_window=True)` (`app.py:1049`); `FrameIntake.get_cycle_metrics()` — ровно 10 ключей; кадр пишется в SHM один раз; глубина кольца 8 связана с бюджетом «в полёте»; read-back `profiles.py:114-145` не меняется.
- W1-a: в `_on_frame` четыре сравнения целых под уже взятым замком; вызовов SDK в `get_frame` не добавляется. W1-a2 добавляет три чтения SDK при открытии (литерал `test_driver_mvs.py:112` меняется в той же задаче).
- W1-b: перезапуск держит системный поток процесса до `timeout + timeout_ms` (2,5 с при умолчаниях) плюс открытие. Не проверено: инспектор GUI может слать запись на каждый шаг спинбокса `trigger_period_ms` — серия перезахватов; дребезг гасить отдельной задачей (debounce), не здесь.
- W1-c: горячий путь логгера не меняется (база уже сливается в каждую запись, `logger_core.py:1923-1928`).

## Позже (вне волны 1)

T0 (замер CPU), T3 (после W1-a), T4 (`port.exceptions`, link, температура), T5 шаг 2 (read-back), T7, T8, T9, T10, T11; масштаб на N и нейросети; мёртвые кнопки `camera_0`, путь `devices hik_*`, объединение `set_config`/`register_update` — по решениям ниже. Строки #1-#7 каждого процесса (до шага 3) остаются `[-]` (W1-c, OUT OF SCOPE).

## Открытые решения (владелец / CTO)

| № | вопрос | кому | рекомендация |
|---|---|---|---|
| Р1 | Контракт «здоровье потока источника» — в `camera_device` или общий в framework? | CTO | Сейчас `camera_device`; перенос после второго потребителя (T5 шаг 2) |
| Р2 | Один путь записи: `set_config` для полей register заморозить? Сегодня `cmd_set_config` (`base.py:1918-1931`) подписчиков не будит — правка триггера/камеры из инспектора отвечает `ok applied`, прибор прежний | CTO | Да, заморозить, не удалять |
| Р3 | Мёртвые кнопки `camera_0` | владелец | Заморозить и скрыть до T10 |
| Р4 | Путь `devices hik_*` | владелец | Заморозить |
| Р5 | T0: `tick_sec 1.0` или `interval 5.0` | владелец | После замера CPU |
| Р6 | Неоднозначное перечисление — `not_found` или новое `ambiguous` | CTO | `not_found` + текст со списком; новое состояние меняет NE 107 и readiness |
| Р7 | `publish_metric` на такт под закрытым гейтом допустим? | CTO | Окно `_TICK_S` (раз в 1 с), не на кадр |

## Бюджет

- 4 задачи, писателей одновременно до 3; developer (sonnet) до 250k на задачу, tester (sonnet) до 150k; reviewer стадии 0 — 3 × sonnet (+1 на W1-a2), стадии 5 — opus × 2, sonnet × 2.
- Машина: `light` и `medium`; стенд не входит.

## После слияния

- ADR в `Services/camera_device/DECISIONS.md` (`DeviceInfo`, политика подсети, `AmbiguousDeviceError`) и таблица контракта в `README.md` — `tech-writer`.
- DECISIONS `data_schema_module` и `code_reader`: смысл `apply=restart` у второго потребителя («перезапуск захвата источника»; комментарий framework говорит «после перезапуска процесса-владельца», `field_meta.py:105-109`) — `tech-writer`.
- `docs/claude/OPEN_QUESTIONS.md`: общий помощник подписки на поля (камера и считыватель повторяют `subscribe/unsubscribe`) — вынести при третьем потребителе или в T5 шаг 2.
- STATUS `code_reader` и `logger_module` — `docs-writer`; `python -m scripts.sync` — лид.

## Что оставил открытым / ненадёжно

- `nTriggerIndex = 0` без chunk и обнуление `nFrameNum` на `StartGrabbing` по документации SDK не проверены; правила брифов (0 -> `None`, «номер не больше прежнего = новая база») безопасны в обоих случаях, но первый настоящий разрыв после 0 может не посчитаться.
- Путь ключа `config.managers.logger.log_directory` в `bundle` процесса spawn и сериализуемость `bundle` при spawn — взяты у ревьюера, проверена только строка схемы `logger_manager_config.py:298`; бриф tester-а велит остановиться, если файл лога не появился.
- Умеет ли `FakeNodeApi` отказать во втором открытии и разрешить третье (W1-b, откат) — не проверял; бриф tester-а велит остановиться.
- Литерал WARNING «перечислен 2 раз» грамматически неровный; оставлен ради простого шаблона.
