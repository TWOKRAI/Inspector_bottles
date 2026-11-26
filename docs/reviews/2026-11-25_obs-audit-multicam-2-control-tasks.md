# Аудит наблюдаемости и управления: многокамерный инспектор (промышленная надёжность) — Часть 2 из 3: управление MCP/GUI, логи, задачи по волнам, оценка, поправки

Все части: `2026-11-25_obs-audit-multicam.md`, `2026-11-25_obs-audit-multicam-2-control-tasks.md`, `2026-11-25_obs-audit-multicam-3-reliability-cto-map.md`.

Дата: 2026-11-25. Автор аудита: investigator (Opus), только чтение; сводку и сохранение выполнил лид K. Дерево: `main` `743641727` (в нём фаза A gui-frame-path). Стенд: рецепт `hikvision_id3013_quad`, камеры MVS DA1689923 (.20) и DA1689977 (.5), считыватели ID3013 .10/.11.

Пометки доказательств: **[запуск]** — подтверждено живым стендом или логом прогона; **[код]** — выведено из кода, строку автор читал сам; **[помощник]** — строку нашёл помощник автора, сам не перечитывал; **[гипотеза]**.

Цель владельца (2026-11-25): стабильный и надёжный механизм многопроцессного фреймворка-конструктора для инспектора качества: многокамерность (сейчас 4 камеры, число N произвольное) и нейросети в конвейере; надёжность уровня промышленности; управление и наблюдение в реальном времени и через MCP, и из GUI. Требование: без костылей и багов, «как полагается архитектурно».

## 3. Живое управление: MCP против GUI (Q3)

Общий приём: вкладка Hikvision (`presenter.py:117`), `app.py:878-882` и MCP (`backend_ctl/registers.py:147-151`) шлют одну команду `register_update {register, field, value}`; её принимает `plugin_orchestrator.py:855-879`. Второй путь GUI (инспектор, `TopologyBridge`) шлёт `set_<field>` или `set_config` (`command_catalog.py:268-282`).

| Управление | MCP | GUI | Что мешает |
|---|---|---|---|
| exposure, gain, frame_rate камеры | да (граб перезапускается ≈1,7 с) | да, тот же путь | — |
| trigger mode/source/period камеры | да | через инспектор (`set_config`) | дойдёт ли `set_config` до подписки: не проверено |
| packet size/delay | при `packet_managed true` | инспектор | иначе поле пропускается |
| ROI / формат пикселей | нет | нет | привязок нет |
| resolution_width/height | значение register меняется | то же | `apply=config`; эффект вживую не проверен |
| триггер считывателя | register принимает | то же | **до прибора не доходит** (`sdk_plugin.py:153-160`, подписки нет); нужен рестарт |
| exposure/gain/свет считывателя | нет | нет | полей нет |
| пауза одного источника | `process.pause/resume` PM, `release_device/take_device`, `set_enabled` | нет: `freeze_capture`, `start_capture/stop_capture` зашиты на `camera_0` (`robot/presenter.py:162-166`, `command_panel.py:46,49`) | мёртвые кнопки |
| рестарт одного процесса | `process_restart_verified` | да (`process_manager_proxy.py:104`) | — |
| выбор прибора по IP/serial | поля + release/take | вкладка Hikvision | вживую не применяется; детекта дублей нет |
| лимит fps дисплея | **нет** | да: вкладка «Дисплеи» → `set_keys` (`app.py:1159-1162`), потолок 60 (`frame_pump.py:50`) | только GUI |
| метрики вкл/выкл по процессу | `telemetry_set` / `telemetry_reconfigure` | вкладка процессов | по источнику внутри процесса — только правилами порта |
| логи вкл/выкл по источнику | `logger_sink_enable/disable` (процесс) | не найдено | — |

## 4. Логи и MCP (Q4/Q5)

Логи:
- Строки плагинов теряют процесс: `[INFO] [-] hikvision: ...` в `camera_1/messages.log` (#14–#27) и `reader_1` (#12); heartbeat несёт `[camera_1]`. Причина: `log_channel.py:1057` (`proc_name or "-"`). Фильтр «Источник» в панели «Логи» работает по `module` (`record_history_presenter.py:155-157`) — камеры в общем виде не различить [код].
- Строки применения хорошие: `value_written=23.0 value_read=23.0119... verified=True` (`profiles.py:142-145`) [запуск]. Нет IP, карты, модели, формата, разрешения, packet_size. `session state=idle->opening` с пустым `device_id=`.
- WARNING «Частота метрик ограничена телеметрийным тиком 5.0с» в каждом процессе: противоречие конфига приложения (`system.yaml:319-321` просит `interval_sec 1.0`, `tick_sec` не задан → тик = `heartbeat_interval` 5.0; `process_heartbeat.py:177,557-575`, `telemetry.py:921`). Исправление: `telemetry.publish.tick_sec: 1.0`; глушить предупреждение нельзя.
- Итога прогона нет: разбор после остановки собирали руками.

MCP:
- `telemetry.fps` в overview пуст по двум причинам: (1) `overview.py:404-444` читает локальную read-model драйвера, наполняется только push-подпиской; `telemetry_snapshot` → `count 0, ingest_active false` [запуск]; (2) `fps` framework = частота цикла (`_panels.py:115-117`): у считывателя 20 Гц при ≈55 кадров/с прибора; у gui `fps: null` [запуск]. fps по камерам в gui считается внутри gui (`main_window.py:734`).
- fps камеры доступен: `introspect_telemetry` → `levels.state.plugins.hikvision.fps` (25.0) [запуск].
- `set_register_verified` проверяет образ register, а не прибор (`registers.py:163-193`).
- Регистр камеры показывает `driver: "fake"` на настоящей камере [запуск]; вендор это поле не читает (`plugin.py:41-48`).
- Инструмента для содержимого кадра (яркость, формат) нет. Ложные `hz_degraded` не воспроизведены.

## 5. Задачи по волнам (12)

| # | Задача | Слой, файлы | Приёмка | Разм. | Зависит |
|---|---|---|---|---|---|
| T0 | `tick_sec: 1.0` (или `interval 5.0`) + пауза рестарта, согласованная с прибором (в `hikvision_dual` `backoff_sec: 10.0`) | prototype: `backend/config/system.yaml`, `recipes/hikvision_id3013_quad*.yaml` | при старте нет WARNING «ограничена»; `tick_effective_sec 1.0`; CPU до/после | S | — |
| T1 | Личность и перечисление: ip/mask/host_ip/mac в `device`; дубль → WARNING, `enum_matches`, выбор записи из подсети камеры, иначе отказ со списком | Services: `hikvision_camera/driver.py`, `camera_device/interface.py`, `plugin_base.py` | фейк-порт: serial дважды с двумя host_ip → `enum_matches 2`, выбрана запись из подсети, WARNING | S | — |
| T2 | Здоровье потока: `incomplete` (`nLostPacket`), `lost_frames` (разрывы `frame_num`), разрывы триггера, блок `stream` | Services: `camera_device/plugin_base.py`, `interface.py`, `driver.py:get_frame` | фейк: номера 1,2,5 и lost 3 → `lost_frames 2`, `incomplete 1` | S | — |
| T3 | Яркость и насыщение по прореженному кадру, поле register `image_stats_every_n`, 0 = выключено | Services: ядро `camera_device` | чёрный кадр → luma 0, dark 1.0; при 0 функция не вызывается (spy) | M | T2 |
| T4 | События прибора и медленный опрос: разбор `port.exceptions`, `link`, температура, packet_size факт | Services: `hikvision_camera/driver.py`, `camera_device/session.py` | фейк кладёт код разрыва → лог + `link=lost` + счётчик | M | T1 |
| T5 | Считыватель честно: шаг 1 — `apply=restart` и отказ живой записи с причиной; шаг 2 — подписка + read-back в state + метрики темпа | Services: `code_reader/plugin/sdk_plugin.py`, `sdk_registers.py`, `core/sdk_reader.py` | шаг 1: `register_update trigger_mode` → отказ с причиной; шаг 2: фейк-прибор → `params.trigger_mode` прочитан | M | — |
| T6 | Личность процесса в каждой строке лога плагина: `proc_name` ставит framework в одном логгере | framework: `logger_module` / `ctx.log_*` в `process_module` | настоящий дочерний процесс, `ctx.log_info` → в строке `[camera_1]` | S–M | — |
| T7 | Метрика `mem` (rss, private, handles, threads), гейт по умолчанию выключен; `cpu` у gui | framework: `process_module/heartbeat/` | гейт вкл → `state.mem.rss > 0`; выкл → ключа нет, psutil не зовётся (spy) | S–M | — |
| T8 | Статистика FrameIntake по sender + `restore_dropped` через `declare_metric` | framework `frontend_module` + prototype `frame_intake.py` | два sender → литералы по каждому; 10 ключей `get_cycle_metrics` не тронуты | S | — |
| T9 | backend_ctl: overview берёт fps по камерам из levels; аномалии `fps_below_configured`, `enum_duplicates`, `lost_frames`, `dark`, `not_verified`; в `set_register_verified` — `device_verified` | `backend_ctl/overview.py`, `registers.py` | fake-драйвер, литеральные ответы → аномалии есть/нет | M | T1–T3, T5 |
| T10 | GUI: общая панель камеры по контракту state (не по именам плагинов); правильное имя fps; фильтр логов по процессу; мёртвые кнопки — решение владельца | prototype: `frontend/widgets/tabs/pipeline/inspector/*`, `observability/record_history_*` | qt-тест: state с литералами → подписи; фильтр процесса | M | T1–T3, T6 |
| T11 | Итог прогона: PM собирает счётчики процессов при `run_stop`/закрытии → одна строка лога + документ | framework: `process_manager_module` | фейк-топология из 3 процессов → один документ | M | T2, T5 |

Порядок: волна 1 = T0, T1, T2, T5 (шаг 1), T6, T7. Волна 2 = T3, T4, T5 (шаг 2), T8. Волна 3 = T9, T10, T11. Обратных импортов нет: Services не импортируют prototype, backend_ctl только читает контракт.

## 6. Оценка и советы

Оценки (1–5): полнота измерений **2** (поток прибора пуст); единый путь управления **3** (`register_update` общий, но у инспектора `set_config`; fps дисплея только из GUI; триггер считывателя не работает вживую); качество логов **3**; устойчивость к сбою одной камеры **3** (в quad2 рост gui уронил соседей: MemoryError у камер, падение `reader_2`); расширяемость на N **3** (`camera_0` зашит в GUI; метрики gui не по sender); стоимость выключенной наблюдаемости **3** (плагин камеры зовёт `publish_metric` на каждом такте); тестируемость **3** (сильный фейк-порт, но `test_plugin_observability` красный на main, сквозной путь считывателя не покрыт); слои **4** (`generic_process.py:35` `_COPY_OUT_TARGETS = {"gui"}` [помощник]; тесты framework считают рецепты prototype); **промышленная надёжность 2** (раздел 9).

Сделано правильно, не ломать: read-back с допуском и `params_status` (`profiles.py:114-145`); один поток-владелец сеанса камеры, фейк-порт, записи узлов; гейт телеметрии + `levels` по запросу + `provenance`; фаза A (LatestMailbox + FramePump: `bytes_held 0`, вытеснения считаются); единый `register_update` у GUI и MCP; процесс на прибор + supervision.

Костыли, дубли, скрытые дефекты:
- Триггер считывателя: register принимает, прибор прежний [код]. Должно: подписка → применение → read-back (как camera_device) или честный отказ.
- «verified» в MCP = образ register, а не прибор [код].
- `driver: "fake"` на настоящей камере [запуск].
- `[-]` вместо процесса в строках плагинов [запуск].
- `port.exceptions` никто не читает; молчаливый `found[0]` при дубле [код].
- Два мира камер в GUI: `_CAMERA_PLUGINS = {"camera_service","capture"}` и `capture_fps` против `fps` у camera_device [код+запуск].
- Два пути записи: `register_update` и `set_config` [код]; должен остаться один.
- Третий путь к Hikvision: процесс `devices` с `hik_enum/hik_open/hik_set_params` [запуск, capabilities]: риск двух владельцев одного GigE-прибора.
- Мёртвые кнопки на `camera_0` [код]; по принципу «замораживать» их не удаляют, но оператора вводить в заблуждение они не должны.
- Заглушка PM: `register_update` отвечает `success: True` и ничего не делает (`topology_manager.py:422-429`) [код].
- `cpu.cores: null` у gui [запуск]. Наследие `hikvision_camera/core/` (`discovery.py` кладёт IP в `serial`) рядом с `driver.py` [помощник].

Альтернативы и рекомендации (кратко):
- Здоровье потока (T2): поля `stFrameInfo` на каждый кадр без лишних вызовов SDK — **рекомендую**; `GetAllMatchInfo` позже в T4; внешний `mvs_probe` не вживую.
- Яркость (T3): в ядре camera_device по прореженному кадру, выключаемая полем — **рекомендую**; отдельный плагин `frame_stats` только если понадобится статистика по ROI; в GUI неверно (видит только показанные кадры).
- Дубли (T1): детект + выбор по подсети + поле `device_host_ip` для явного выбора, отказ при неоднозначности — **рекомендую**.
- Считыватель (T5): сначала `apply=restart` и отказ живой записи, затем подписка + read-back; объединять ядра камеры и считывателя — когда появится третий тип прибора.
- Личность в логе (T6): один логгер framework — **рекомендую**.
- Ресурсы (T7): метрика в heartbeat под гейтом — **рекомендую**; `introspect_memory` + сэмплер остаётся.
- Потребители (T9): `levels` через `introspect_telemetry` — **рекомендую**; автоподписка в overview — побочный эффект.
- Итог прогона (T11): собирает PM — **рекомендую**.
- Тик (T0): `tick_sec 1.0` после замера CPU; если CPU заметно растёт — `interval 5.0`; глушить WARNING нельзя.

Не делать сейчас: не считать факты бэкенда в GUI; не добавлять registers в gui ради fps дисплея; не звать `GetAllMatchInfo` в цикле кадра, не логировать каждый кадр, не считать статистику по полному кадру; не объединять ядра камеры и считывателя; не строить подсистему аварий PackML; не переименовывать `fps` framework (чинить подписи у потребителей); не удалять наследие `core/`, только пометить.

Риски для фазы A и проверка до слияния:
- У окна FramePump один сбрасывающий читатель (`app.py:1049`, предупреждение в `frame_intake.py:91`): второй `stats(reset_window=True)` (T8) украдёт окно. Публиковать только из снимка FrameIntake. Тест: два читателя, окно не меняется.
- Слепой тест T4 требует ровно 10 ключей `get_cycle_metrics` (`T4.md:73`): T8 — отдельный метод.
- Отложенная копия SHM (T5): статистика яркости в GUI заставила бы копировать вытесненные кадры → T3 на стороне камеры. Проверка: `bytes_read` на показанный кадр не растёт.
- T0 увеличит поток `state.changed` в gui: проверка `pump_busy_share` и `qt_pending` до/после.
- T2/T3 нагружают поток-владелец камеры: проверка `pacer_late`, `effective_hz` на фейке при 25 и 60 Гц.
- T6 трогает горячий путь логгера (`log_channel.py:1040-1041`): тест пропускной способности.
- Порядок проверки: тесты радиуса (`frontend_module/bridge`, тесты кадров prototype, слепые T4/T5/T10), затем A/B на стенде 20 мин.

## 7. Поправки автора

1. Авторестарт в quad есть: `FW_AUTORESTART` по умолчанию `True` (`config_module/feature_flags.py:172-174`); без `restart_policy` PM собирает `RestartPolicy(enabled=True)` (`process_manager_process.py:383-386`): 3 попытки за 60 с, пауза 2 с (`restart_policy.py:68-82`) [код]; в quad2 `reader_2` упал и поднят через 38 мс «1/3» [запуск]. Значит, в T0 нужна не сама политика, а пауза, согласованная с прибором.
2. `cache_size: 32` у gui — число открытых дескрипторов SHM без предела (`shm_frame_reader.py:91-96`): 4 sender × 8 слотов, растёт линейно с N [код].
