# Аудит: multiprocess_prototype + Services + Plugins — 2026-06-13

> **Справочник для агентов.** Это снимок состояния кодовой базы на 2026-06-13 (ветка `feat/camera-robot-calibration`).
> Использовать как карту проблем и backlog улучшений. Каждая находка имеет стабильный ID (`H1`, `M-leak-1`, …) — ссылайся на него.
> **Перед действием по находке** — перечитай файл по указанному `file:line`: код мог измениться с даты аудита (правило memory: verify before recommend).

## Как пользоваться

- **Нужна срочная починка** → раздел [P0 / HIGH](#p0--high-2-находки).
- **Планируешь спринт улучшений** → [P1 / MEDIUM по темам](#p1--medium-подтверждённые).
- **Ищешь по файлу/категории** → [Индекс находок](#индекс-находок-карта).
- **Видишь «баг», которого аудит не нашёл** → проверь [Ложные срабатывания](#ложные-срабатывания-отклонены-верификацией) — возможно, его уже разбирали и опровергли.
- **Темы дедуплицированы**: одна корневая причина = одна находка, даже если всплыла в нескольких зонах.

## Методология

16 агентов-аналитиков прошли по подсистемам (frontend ×5, domain, adapters, backend, recipes/registers, Plugins ×3, Services ×3, cross-cutting). Все находки уровня critical/high прошли **состязательную верификацию** отдельным скептиком (задача — опровергнуть). Объективные метрики — `sentrux` (scan всего репозитория, 3788 файлов).

**Итог верификации 16 кандидатов critical/high:** подтверждено как HIGH — **2**; понижено до medium (реальные) — 6; понижено до low (реальные) — 4; **отклонено как ложные — 4** (см. конец документа). Критичных (critical) проблем не обнаружено.

---

## TL;DR

- **Архитектура здоровая в основе:** циклических импортов нет вообще (acyclicity 10000/10000), зависимости текут строго вниз по слоям (DSM below-diagonal=776, above=0), инвариант «плагин не импортирует `multiprocess_prototype.*`» соблюдён.
- **Главная системная слабость — модульность** (sentrux modularity 4488/10000 для prototype, узкое место). Проявляется как god-файлы (`presenter.py` 1818 LOC, `factory.py` 1190, `inspector_panel.py` 1110) и высокая связность (2440 cross-module рёбер по репозиторию).
- **Самый частый класс реальных дефектов — утечки lifecycle:** Qt/EventBus-подписки без отписки (≥6 мест), ведущие к use-after-free QWidget и росту памяти при пересборке вкладок/смене роли.
- **Второй класс — тихое проглатывание ошибок:** ~30 мест `except …: pass` без лога (особенно в hot-path камер и в драйверах device_hub) → невозможна диагностика в проде. Нарушает правило проекта №5/№6.
- **Заметный мёртвый код:** `frontend/actions/` (ActionBus), `Services/Operation_crop` (858 LOC), runtime-расширения `topology_bridge.py` (~200 строк), `controls/` + `topology/editor` виджеты (~700 строк), пустой `webcam_camera`.
- **Покрытие тестами 51.6%** (209 из 432 source-файлов prototype без тестов); самые рискованные дыры — action_log (rotation/recovery/writer), CV-логика атомарных плагинов, миграции рецептов.

---

## Объективные метрики (sentrux, 2026-06-13)

| Метрика | prototype | весь репозиторий | Трактовка |
|---|---|---|---|
| Quality signal | 7090/10000 | 7059/10000 | стабильно vs baseline 2026-05 (7161) |
| **Acyclicity** | 10000 | **10000** | ✅ циклов импорта нет |
| **Modularity** | **4488** ⚠️ | 5143 ⚠️ | 🔴 узкое место — высокая связность |
| Depth | 6667 | 6154 ⚠️ | нарушает min_depth (0.615 < 0.65) |
| Equality | 6541 | 6186 | неравномерные размеры модулей (god-файлы) |
| Redundancy | 9156 | 8950 | ✅ дублирования мало |
| DSM layering | below=776 / above=0 | — | ✅ зависимости текут вниз |
| Test coverage | 51.6% файлов | — | ⚠️ 209/432 без тестов |

> ⚠️ free-версия sentrux проверяет только 3 из 31 правила. Единственное падающее правило — `min_depth`. Инвариант границ слоёв подтверждён grep'ом агента cross-cutting (`import multiprocess_prototype` из Plugins — 0 нарушений; совпадения — комментарии).

**Масштаб:** prototype ~51k LOC прод-кода (frontend доминирует 38.7k), Plugins 12k LOC (~45 плагинов), Services 23.3k LOC (~12 сервисов).

---

## Индекс находок (карта)

### P0 / HIGH

| ID | Категория | Зона | Файл | Заголовок |
|----|-----------|------|------|-----------|
| **H1** ✅ | bug | domain | `domain/entities/project.py:453-508` | ~~RenameProcess не обновляет ссылки `target_process`/`chain_targets`~~ **ЗАКРЫТО 2026-06-14** |
| **H2** ✅ | bug | svc-ml-cam | `Services/hikvision_camera/core/converter.py:97` | ~~Анаморфный resize 4:3→16:9 искажает геометрию~~ **ЗАКРЫТО 2026-06-14** |

### P1 / MEDIUM (по темам)

| ID | Категория | Файл | Заголовок |
|----|-----------|------|-----------|
| M-leak-1 | qt-thread | `adapters/auth/auth_facade.py:75` + `frontend/widgets/access/permission_gate.py:80` | `on_access_changed` без отписки → use-after-free QWidget |
| M-leak-2 | bug | `frontend/app.py:262` | TopologyBridge state-listeners накапливаются при перезапуске UI |
| M-leak-3 | qt-thread | `frontend/widgets/tabs/pipeline/presenter.py:167-177` | EventBus-подписки presenter/tab без unsubscribe |
| M-leak-4 | qt-thread | `frontend/widgets/tabs/processes/tab.py:113` | ProcessesTab не отписывается от TopologyReplaced |
| M-leak-5 | bug | `frontend/widgets/tabs/services/robot/controller.py:114` | robot/vfd fanout-телеметрия без unbind |
| M-leak-6 | bug | `frontend/widgets/displays/preview_window.py:249` | PreviewWindow.unsubscribe затирает всех при мультиокне |
| M-dom-1 | bug | `domain/entities/project.py:754-787` | ConnectWire допускает дубликаты проводов |
| M-dom-2 | bug | `domain/entities/project.py:941-954` | ReplaceTopology оставляет stale `active_recipe` |
| M-dom-3 | test-gap | `domain/entities/recipe.py:82-85` | `Recipe.devices` без round-trip теста (+ shallow copy) |
| M-race-1 | race | `Plugins/hub/device_hub/plugin.py:202,428-435` | Приватный доступ к `_entries`/`_drivers` → RuntimeError итерации |
| M-race-2 | race | `Plugins/runtime/worker_pool/plugin.py:120` | Один sub-plugin в N потоках при items>pool_size |
| M-race-3 | race | `Plugins/io/database/plugin.py:127` | per-row SQLite под `_buffer_lock` + гонка счётчиков |
| M-race-4 | qt-thread | `Services/modbus/core/device.py:92-111` | connect/disconnect держат RLock на блокирующем IO |
| M-perf-1 | perf | `Plugins/control/robot_control/plugin.py:138` | `time.sleep(reject_delay_ms)` в hot-path `process()` |
| M-perf-2 | perf | `Plugins/processing/blob_detector/plugin.py:106` | тащит mask+contours по IPC (vs contour_finder дропает) |
| M-perf-3 | perf | `frontend/forms/factory.py:880` | длинная строка пишет через ActionBus+IPC на каждый символ |
| M-perf-4 | perf | `Services/sql/action_log/log_writer.py:135-159` | ActionLogWriter держит Lock на время записи в БД (фриз GUI) |
| M-err-1 | error-handling | `Plugins/sources/camera_service/plugin.py:152-155` | produce() глушит все исключения backend → чёрный экран без логов |
| M-err-2 | error-handling | `Plugins/sources/capture/plugin.py:122` | голый except в produce() без лога |
| M-err-3 | error-handling | `Services/device_hub/drivers/robot_driver.py` (+vfd, +generic_modbus) | драйверы глушат IO-ошибки без единой строки лога |
| M-err-4 | error-handling | `Services/hikvision_camera/core/parameters.py:74` (+discovery.py) | SDK-ошибки камеры проглатываются |
| M-err-5 | error-handling | `frontend/widgets/topology/editor.py:151` | `load_file` except: pass без лога |
| M-err-6 | error-handling | `Plugins/calibration/camera_robot/store.py:110` | `load_calibration` падает на битом YAML вопреки контракту |
| M-err-7 | error-handling | `Services/auth/audit_writer.py:72,144-154` | мёртвая ветка fallback + неограниченная очередь (рост памяти) |
| M-err-agg | error-handling | ~30 мест (prototype+Plugins) | высокая плотность `except: pass` без лога |
| M-cfg-1 | bug | `multiprocess_framework/.../generic/blueprint.py:343` | GUI вложенный `config:` ломает расчёт SHM кадра |
| M-cfg-2 | duplication | `recipes/dataset_circle_capture.yaml` (+camera_robot_calibration) | два несовместимых формата YAML-рецептов |
| M-lay-1 | layering | `frontend/widgets/tabs/processes/_panels.py:443` | прототип читает приватные `_indicator`/`_metric_labels` EntityCard |
| M-lay-2 | layering | `Services/auth/tests/test_role_update_handler.py:14` | обратный импорт Services→prototype в тесте |
| M-sec-1 | security | `Services/auth/manager.py:303-323` | timing-oracle: user enumeration через пропуск bcrypt |
| M-be-1 | bug | `orchestrator.py:185-198` | рассинхрон DisplayRegistry при debounce apply_topology |
| M-arch-1 | arch | `Services/vfd_comm/core/client.py:97-118` | VfdClient завязан на BRIDGE_MAP при заявленной параметризации |
| M-arch-2 | bug | `Services/modbus/core/device.py:176-193` | transaction() полагается на retries=1; при retries>1 ломается atomicity |
| M-arch-3 | duplication | `Plugins/processing/color_mask/plugin.py:38-40,98-99` | порт `mask`, а пишет в `frame`; расхождение с hsv_mask |
| M-god-1 | god-file | `frontend/widgets/tabs/pipeline/presenter.py:86` | PipelinePresenter 1818 LOC / ~56 методов (коррелирует с min_depth) |
| M-god-3 | duplication | `frontend/forms/factory.py:229` | 9 binding-builder'ов дублируют boilerplate (1190 LOC) |
| M-dead-1 | dead-code | `frontend/app.py:463` + `frontend/actions/` | ActionBus собирается, но без потребителей в проде |
| M-dead-2 | dead-code | `frontend/bridge/topology_bridge.py:381` | runtime-расширения diff/connect_wire/hot_add (~200 строк) мертвы |
| M-dead-3 | dead-code | `frontend/widgets/controls/command_panel.py:42` | controls/ (CommandPanel, ProcessStatusWidget) не подключены |
| M-dead-4 | dead-code | `frontend/widgets/topology/editor.py:26` | topology/editor + дочерние виджеты (~700 строк) не используются |
| M-dead-5 | dead-code | `Services/Operation_crop/preobrazovanie.py:1` | осиротевший модуль 858 LOC, дублирует плагины |
| M-ml-1 | bug | `Services/ml_inference/core/preprocess.py:40` | resize-политика train↔inference не в sidecar (letterbox vs stretch) |

### P2 / LOW + INFO (сжато)

- **L-dead** (low/dead-code): `backend/routing/frame_router_setup.py` (0 вызовов), `backend/displays/blueprint_binding.py` (framework помечает obsolete), `registers/manager.py` `build_rm_from_topology`/`_RawRegisterData` (жив только в тестах), пустой `Services/webcam_camera/`, неиспользуемый `Services/Region_processors/`.
- **L-tx** (low): неатомарность `insert_many`/`update_many` (`Services/sql/core/base_repository.py:80-103`) и ротации action_log (`rotation.py:55-73`) — реальны, но в коде без продакшен-потребителей и с доступной атомарной альтернативой (`unit_of_work`/`adapter.connection()`).
- **L-blob** (low): `blob_detector` рисует контуры в исходный кадр in-place (`Plugins/processing/blob_detector/plugin.py:97-104`) — нарушение конвенции «рисуем на копии» (все остальные рисующие плагины делают `frame.copy()`); SHM-порчи нет (middleware отдаёт приватную копию).
- **L-god** (low): `run_gui()` 627 LOC (`frontend/app.py:55`) — god-функция композиционного корня с ~20 пронумерованными шагами.
- **L-docs** (low/info): drift комментария `app.yaml:21` (описан color_inspect, активен dataset_circle_capture); docstring QueuedConnection vs реальный AutoConnection в `bridge_impl.py` (функционально эквивалентны — см. ложные срабатывания).
- **L-dom** (low): `apply()` без `case _` молча возвращает None на неизвестной команде (`project.py:345-375`) — защищено exhaustive-union + pyright + тестами, но идиоматичный `assert_never` отсутствует.
- **INFO**: shell-сервисы (`sql`/`auth`/`hikvision` service.py) рапортуют «running» без реального подключения.

### Темы тестовых пробелов (test-gap)

| Зона | Что не покрыто |
|------|----------------|
| action_log | rotation (порог/сбой между CREATE-DELETE), recovery (UNDO-пары, max_age), writer (coalescing/auto-flush) |
| CV-плагины | line_filter (гистерезис/cross_line/дедуп), stitcher (offset+clamp), region_split (fan-out), color_convert (3ch-инвариант), renderer_compositor, render_overlay |
| frontend | `managers/theme_presets_manager.py`, `styles/*` (599 LOC без тестов) |
| backend | `_configure_topology_engine`, deepcopy-guard от мутации IPC-рецепта |
| recipes | миграции `format_v1_to_v2`, `displays_to_recipe`, `drop_display_name` |
| Plugins | 9 плагинов без `test_*.py` |

---

## P0 / HIGH (2 находки)

### H1 — RenameProcess не обновляет ссылки `target_process`/`chain_targets`
**Файл:** `multiprocess_prototype/domain/entities/project.py:453-508`
**Подтверждено верификацией (high).**
**✅ ЗАКРЫТО 2026-06-14:** `_apply_rename_process` обновляет `target_process`/`chain_targets` во всех процессах при переименовании (+тест с кросс-ссылками). Инвариант `refs ⊆ имён процессов` в `_validate_topology` **намеренно НЕ добавлен** — `chain_targets: [gui]` легитимно ссылается на base-процесс вне `processes:` рецепта, строгий инвариант сломал бы активацию рецептов через `ReplaceTopology`.

`_apply_rename_process` обновляет `process_name` совпавшего процесса, переписывает `wire.source/target` (`_rename_node`) и `display.node_id`, **но не трогает поля других процессов** `Process.target_process` (`process.py:49-52`) и `Process.chain_targets` (`process.py:53-56`), хранящие имена процессов. Инвариант `_validate_topology` не проверяет эти поля (только `wires`), а `_apply_rename_process` вообще не вызывает валидацию.

`chain_targets` — это default IPC-маршрутизация, потребляется в `PipelineExecutor._send_results` (`pipeline_executor.py:226`) и `SourceProducer` (`source_producer.py:152`). После переименования A→B процесс со stale `chain_targets=['A']` шлёт IPC на несуществующий процесс — **битая маршрутизация, проявляется молча только в runtime**.

**Починка:** в `_apply_rename_process` пройти по всем процессам и заменить старое имя в `target_process`/`chain_targets`; добавить инвариант в `_validate_topology` (target_process/chain_targets ⊆ имён процессов); тест расширить кросс-ссылками (текущий `test_rename_process_ok` проверяет только wires+displays).
**Оговорка:** в текущем GUI `chain_targets` через редактор пока не правятся (`io.py` round-trip'ит только `target_process`), но поле полностью провязано в домене/runtime и уязвимо для импортируемых топологий.

### H2 — Анаморфный resize Hikvision 4:3→16:9 искажает геометрию
**Файл:** `Services/hikvision_camera/core/converter.py:97`
**Подтверждено верификацией (high, конфиг-зависимо).**
**✅ ЗАКРЫТО 2026-06-14:** `FrameConverter.resize` получил `mode` с дефолтом `letterbox` (сохраняет аспект + чёрные поля); `stretch` оставлен явной опцией, неизвестный режим → letterbox (fail-safe). Конфиг-поле `resize_mode`, рецепт `hikvision_inspect` приведён к 4:3 (1440×1080). +6 тестов (letterbox/stretch/fail-safe/2D). Config-дефолт 1920×1080 оставлен — letterbox делает его безопасным.

`cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)` без сохранения пропорций. No-op-guard выше (`converter.py:94-96`) срабатывает только при точном совпадении размеров — при сенсоре 4:3 (2592×1944) и целевом 16:9 кадр растягивается анаморфно (коэффициент 1.33: круги → эллипсы, HoughCircles рисует пересекающиеся круги, ML-классификатор на неискажённых данных сбивается).

Вызов безусловен на каждом кадре (`plugin/plugin.py:169` в `produce()`). Дефолт 16:9 (1920×1080) зашит в `plugin/config.py:33-41` **и в каноническом рецепте** `recipes/hikvision_inspect.yaml:49-50` → опасное значение поставляется по умолчанию. Это документированная грабля проекта (memory `project_hikvision_aspect_ratio.md`); тест `test_converter.py:125-141` даже кодирует анаморфное поведение как ожидаемое.

**Починка:** добавить letterbox-режим (resize с сохранением аспекта + паддинг) или валидацию совпадения аспекта сенсора и целевого разрешения с предупреждением; привести дефолт рецепта к аспекту сенсора (4:3). Заодно пересмотреть тест.

---

## P1 / MEDIUM (подтверждённые)

### Тема: утечки lifecycle (Qt/EventBus-подписки без отписки)
Самый частый класс реальных дефектов. Общий паттерн: подписка на долгоживущий сигнал/шину без симметричной отписки → при пересборке виджетов/смене роли старые callbacks держат разрушаемые объекты (use-after-free `RuntimeError: Internal C++ object already deleted`) и текут память/CPU.

- **M-leak-1** `adapters/auth/auth_facade.py:75` + `frontend/widgets/access/permission_gate.py:80` — `on_access_changed` коннектит новую лямбду к `AuthState.access_context_changed` (долгоживущий QObject) **без метода отписки**. При пересборке gated-виджетов (например `plugins/tab.py:151` → `refresh_catalog` на `catalog_updated`) каждый новый `RegisterView` добавляет вечную подписку; смена роли вызывает `_refresh` поверх удалённого QWidget. → Сделать подписку отзываемой (handle/`Subscription` как у `ConfigStore`) или коннектить через `QObject.destroyed`/weakref.
- **M-leak-2** `frontend/app.py:262` — `_forward_state_delta_to_topology` объявлена локально в `run_gui()` (новое замыкание на каждый запуск); `DataReceiverBridge._state_listeners` переживает перезапуск UI (`_reload_frontend_modules` сохраняет `frontend.bridge`). `remove_state_listener` отсутствует → накопление listener'ов на КАЖДУЮ state-дельту. → Добавить `clear_state_listeners()`, вызывать в начале `run_gui()`.
- **M-leak-3** `frontend/widgets/tabs/pipeline/presenter.py:167-177` — `_topology_sub`/`_recipe_activated_sub`/`_process_added_sub` + `_wire_metrics_controller` без teardown. → `tab.closeEvent`/`teardown()` с unsubscribe + `stop()`.
- **M-leak-4** `frontend/widgets/tabs/processes/tab.py:113` — подписка на `TopologyReplaced` без unsubscribe (DisplaysTab уже делает teardown в closeEvent — взять за образец).
- **M-leak-5** `frontend/widgets/tabs/services/robot/controller.py:114` — `bind_fanout` не возвращает handle и нет `unbind_fanout` → push-телеметрия старого `device_id` остаётся подписанной при `set_device`/`unbind`. → Добавить `GuiStateBindings.unbind_fanout` (или вернуть handle).
- **M-leak-6** `frontend/widgets/displays/preview_window.py:249` — `unsubscribe` перерегистрирует broadcast-маршрут **пустым списком** → при двух окнах одного дисплея закрытие одного гасит кадры второго. → Отписываться адресно (список минус свой `_channel_name`) или `RouterManager.unregister_broadcast_subscriber`.

### Тема: тихое проглатывание ошибок (error-handling)
~30 мест `except …: pass`/`except Exception` без лога. Нарушает правила проекта №5 («логировать ошибки, не подавлять») и №6 (логи через `ObservableMixin`). Особо опасно в hot-path камер и в always-on драйверах.

- **M-err-1** `Plugins/sources/camera_service/plugin.py:152-155` — `produce()` при стабильном сбое backend бесконечно возвращает `[]` без единого лога → чёрный экран, диагностика невозможна. → Логировать первый сбой (throttled) + флаг ошибки в state (good→bad счётчик).
- **M-err-2** `Plugins/sources/capture/plugin.py:122` — голый `except Exception` в `produce()` без лога/метрики/reconnect. → Ловить узко (`cv2.error`/`OSError`), троттлить лог, инкрементить drops, при устойчивом потоке — `status=error`.
- **M-err-3** `Services/device_hub/drivers/robot_driver.py` (151,166,208,229,248,289,313,383,653) + `vfd_driver.py` + `generic_modbus_driver.py` — все IO-ошибки → только `_record_err()` или `pass`, **ни одного** `log_error`/`log_warning`, хотя `BaseDeviceDriver` наследует `ObservableMixin`. Глухая зона — автономный `tick()` (обрыв TCP при подаче/рисовании): исключение гасится внутри драйвера и НЕ доходит до супервизора. → Логировать в драйверах через ObservableMixin.
- **M-err-4** `Services/hikvision_camera/core/parameters.py:74` + `discovery.py` — SDK-ошибки set/get параметров проглатываются → оператор не видит причину (нет прав/вне диапазона/таймаут GenICam). → `logger.warning(SdkError.description)` перед return None/False.
- **M-err-5** `frontend/widgets/topology/editor.py:151` — `load_file` `except: pass` (но виджет мёртвый, см. M-dead-4).
- **M-err-6** `Plugins/calibration/camera_robot/store.py:110` — `load_calibration` падает на битом YAML вместо обещанного контрактом `None` → прод-рецепт с калибровкой камера↔робот упадёт при старте на повреждённом файле. → `try/except (yaml.YAMLError, OSError)` → лог + None + тест.
- **M-err-7** `Services/auth/audit_writer.py:72,144-154` — очередь без `maxsize` (docstring обещает fallback при переполнении, но `put_nowait` на неограниченной Queue никогда не бросит `Full` → ветка fallback мертва); риск роста памяти без back-pressure. NB: fallback при СБОЕ SQLite работает (`_write_batch` per-entry try/except). → Ограничить очередь + реальный overflow→JSONL.

### Тема: concurrency / races
- **M-race-1** `Plugins/hub/device_hub/plugin.py:202,428-435` — читает приватные `_manager._entries/_drivers` из supervisor-потока без `_registry_lock`. Реальная гонка: `_update_counters` (`plugin.py:434`) живо итерирует `_drivers.values()` на supervisor-тике (0.2с), а командный поток через `manager.remove` делает `_drivers.pop` → `RuntimeError: dictionary changed size during iteration`. Хуже — вызов вне per-item try/except (`plugin.py:286`) → роняет supervisor-воркер always-on хаба. Плюс нарушение инкапсуляции границы Plugins→Services (10 мест). → Публичные потокобезопасные снапшоты в `DeviceManager` (`snapshot_entries()`/`count_connected()`), плагин не лезет в приватное.
- **M-race-2** `Plugins/runtime/worker_pool/plugin.py:120` — при items>pool_size round-robin привязывает item к экземпляру sub-plugin, а не к потоку → один экземпляр `process()` вызывается из 2+ потоков (инвариант изоляции из docstring ложен). Плагин **игнорирует существующий контракт** `thread_safe` (framework `base.py:201-204`). Сейчас латентно: `worker_pool_size: 0` в `system.yaml:22`, используемые sub-plugin'ы stateless. → Уважать `thread_safe`; при items>pool_size и не-thread-safe sub-plugin — сериализовать или закрепить экземпляр за потоком.
- **M-race-3** `Plugins/io/database/plugin.py:127` — батч SQLite (десятки commit) под `_buffer_lock` блокирует data-worker; `_total_written`/`_total_errors` мутируются из двух потоков без защиты (потеря инкрементов). → Забрать batch под lock, писать вне lock; счётчики под отдельным мелким lock.
- **M-race-4** `Services/modbus/core/device.py:92-111` — `connect`/`disconnect` держат RLock устройства на время блокирующего IO (до timeout_sec; робот 1с). Для bridge-ПЧ реконнект робота заморозит и опрос ПЧ, и публикацию телеметрии (косвенный GUI-фриз). `DeviceManager` сам предупреждает «не держать лок на connect-IO», но в `ModbusDevice` нарушено. → Под локом менять только state/счётчики, `client.connect()/close()` — вне лока (или отдельный `_io_lock`).

### Тема: perf / hot-path
- **M-perf-1** `Plugins/control/robot_control/plugin.py:138` — `time.sleep(reject_delay_ms)` прямо в `process()` (поток обработки кадров) → встаёт ВЕСЬ конвейер, FPS падает, дропы. → Отложенный reject в LOOP-воркер (как `job_forwarder` в robot_io), `process()` неблокирующий.
- **M-perf-2** `Plugins/processing/blob_detector/plugin.py:106` — кладёт `mask` + список `contours` (N ndarray) в item; на границе процессов всё пиклится на каждом кадре. `contour_finder.py:87` осознанно делает `out.pop('mask')`. → Дропать mask/contours, если не нужны downstream (флаг `keep_*`).
- **M-perf-3** `frontend/forms/factory.py:880` — длинная строка пишет через ActionBus+IPC + lookup регистра на КАЖДЫЙ символ. → commit-семантика (`focusOutEvent`/`editingFinished`) или дебаунс.
- **M-perf-4** `Services/sql/action_log/log_writer.py:135-159,78-91` — Timer-поток пишет батч в SQLite, удерживая Lock, разделяемый с GUI-потоком `enqueue()` (движение слайдера) → микро-фризы UI при медленной БД. → Забрать batch под lock, `repository.append` вне критической секции.

### Тема: domain integrity
- **M-dom-1** `domain/entities/project.py:754-787` — `ConnectWire` допускает дубликаты проводов (нет no-dup, в отличие от `BindDisplay`). `DisconnectWire` удаляет только первое совпадение → висящие копии; возможен дубль кадров/команд в runtime. → Проверка отсутствия пары (source,target) + `DomainError` + тест.
- **M-dom-2** `domain/entities/project.py:941-954` — `ReplaceTopology` оставляет stale `active_recipe` (slug рецепта, чей blueprint больше не соответствует topology). → Решить семантику явно: сброс `active_recipe=None` + `RecipeDeactivated`, либо задокументировать намеренность.
- **M-dom-3** `domain/entities/recipe.py:82-85` — новое поле `Recipe.devices` без round-trip теста; `dict(d)` — поверхностная копия, мутация raw-yaml может изменить `devices` внутри Recipe. → round-trip тест с непустыми `devices` + вложенным `transport`; рассмотреть `deepcopy`.

### Тема: config / recipes
- **M-cfg-1** `multiprocess_framework/.../generic/blueprint.py:343` — при активации GUI-сохранённого рецепта SHM ring-buffer кадра выделяется под дефолтное разрешение плагина, не рецептное. Спасает только grow-only переаллокация `FrameShmMiddleware` (commit 7b007dcf) ценой churn на старте. → В `_restore_plugin_configs` разворачивать вложенный `config:` поверх плоских полей (как `PluginOrchestrator._extract_plugin_config`).
- **M-cfg-2** `recipes/dataset_circle_capture.yaml`, `camera_robot_calibration.yaml` — два несовместимых формата (плоский рукописный vs GUI-нормализованный с вложенным `config:` и встроенными base-процессами gui/devices, которые `merge_topologies` молча выбрасывает). → Зафиксировать ОДИН канонический формат (плоский) либо нормализовать оба в одной точке + задокументировать.

### Тема: layering / encapsulation
- **M-lay-1** `frontend/widgets/tabs/processes/_panels.py:443` — прототип читает приватные `_indicator`/`_metric_labels` фреймворкового `EntityCard` (7 раз) → рефактор примитива молча сломает Processes в runtime. → Публичные аксессоры `indicator_widget()`/`metric_label(key)` во фреймворке.
- **M-lay-2** `Services/auth/tests/test_role_update_handler.py:14` — обратный импорт Services→prototype в тесте (sentrux исключает тесты → проходит CI). → Перенести тест в prototype либо расширить sentrux-правило на тестовые пути.

### Прочее (medium)
- **M-sec-1** `Services/auth/manager.py:303-323` — `login()` пропускает bcrypt для несуществующего пользователя → timing-oracle для user enumeration. → Холостая bcrypt-верификация против dummy-хеша.
- **M-be-1** `orchestrator.py:185-198` — при повторном «Загрузить/Запустить» в пределах cooldown (1.0s) DisplayRegistry переписывается новым рецептом, хотя топология процессов осталась старой → метаданные дисплеев расходятся с реальными продюсерами кадров. → reload реестра только если замена реально произошла (`if result.get("debounced"): skip`).
- **M-arch-1** `Services/vfd_comm/core/client.py:97-118` — `poll()`/`read_status()` жёстко завязаны на `BRIDGE_MAP`, хотя `register_map` принимается параметром; передача `DIRECT_MAP` (предлагается в `__init__`) → KeyError. → Убрать `register_map` из публичного конструктора bridge-клиента или вынести bridge-специфику в подкласс.
- **M-arch-2** `Services/modbus/core/device.py:176-193` — `transaction()` обходит `write_register`, полагаясь на retries=1; при дефолтном `ModbusConfig(retries=3)` pymodbus молча повторит частично-применённую запись → нарушение atomicity-инварианта. → Форсировать retries<=1 для transaction-пути + валидация в `__init__`.
- **M-arch-3** `Plugins/processing/color_mask/plugin.py:38-40,98-99` — объявленный порт `mask`, а пишет 3ch BGR в `frame` (затирая кадр); расходится с `hsv_mask` (пишет в `item['mask']`). Дублирование с тонкой семантической разницей. → Выровнять с hsv_mask или исправить контракт порта; убрать неиспользуемый импорт `Any`.
- **M-ml-1** `Services/ml_inference/core/preprocess.py:40` — resize-политика train↔inference не записана в sidecar (инференс паддит letterbox, обучение растягивало) → distribution shift для неквадратных входов. → Писать `resize_mode` в sidecar при экспорте из ml_train, читать в ModelSpec.

### God-files (медиана)
- **M-god-1** `frontend/widgets/tabs/pipeline/presenter.py:86` — 1818 LOC / ~56 методов: загрузка графа + EventBus-реакции + IPC-команды + редактирование нод + drag/inspector + live-control + legacy `self._topo`. Коррелирует с просадкой sentrux min_depth. → Декомпозировать: `TopologyGraphMapper`, `LayoutPersistService`, `BackendControlFacade`, под-презентеры по ответственности; удалить legacy self._topo.
- **M-god-3** `frontend/forms/factory.py:229` — 9 binding-builder'ов дублируют `BindingConfig/create/FieldEditor` boilerplate (1190 LOC). → Helper `_make_binding_control(...)`.

### Dead code (medium)
- **M-dead-1** `frontend/app.py:463` + вся `frontend/actions/` — `create_action_bus` инстанцирует ActionBus + 8 handlers + guards впустую (undo переведён на domain `CommandDispatcher`, G.4.4). Два конкурирующих undo-механизма путают. → Удалить `frontend/actions/` + вызов, либо `@deprecated` + явный план.
- **M-dead-2** `frontend/bridge/topology_bridge.py:381` — `apply_topology_diff`/`connect_wire`/`hot_add_process`/`get_capabilities` + `TopologyApplyResult` (~200 строк, «Phase 12.6 v2») мертвы; живой путь — recipe-driven full-replace. Используется только `hot_remove_process`. → Вырезать, оставив `on_field_set`/`on_action_command`/`on_state_delta`/lifecycle/`hot_remove_process`.
- **M-dead-3** `frontend/widgets/controls/command_panel.py:42` — `CommandPanel`/`ProcessStatusWidget` не подключены (хардкод `camera_0` вводит в заблуждение). → Удалить controls/.
- **M-dead-4** `frontend/widgets/topology/editor.py:26` — editor + plugin_selector/wire_list/process_list/validation_panel (~700 строк) живут только под тестами, дублируют Pipeline-таб. → Подтвердить с владельцем и удалить UI, оставив `TopologyPresenter`.
- **M-dead-5** `Services/Operation_crop/preobrazovanie.py:1` — 858 LOC, дублирует vocabulary плагинов (дрейф от ADR-120). → Удалить или мигрировать в Plugins/processing.

---

## Ложные срабатывания (отклонены верификацией)

Эти находки были выдвинуты аналитиками как critical/high, но **состязательная проверка их опровергла**. Не тратить время на «починку» — здесь проблемы нет.

1. **❌ Мост доставляет state через AutoConnection вместо QueuedConnection** (`frontend/state/bridge_impl.py:41`) — расхождение docstring↔код реально, но функционально безопасно: `DataReceiverBridge` — QObject в main-thread, `dispatch()` зовётся из нативного `threading.Thread`, для которого Qt детерминированно выбирает QueuedConnection. Краша нет. **Остаток: только устаревший docstring (info).**

2. **❌ Расхождение порядка резолвинга register-классов runtime vs GUI** (`base.py:250-258` / `registry.py:43-50`) — порядок реально разный, НО `config_class()` нигде не переопределён (всегда None) → ветка мертва, оба пути всегда резолвят один класс; `register_bindings` == `[register_class]` у обоих использующих плагинов. Расхождения результата нет. **Инертная ловушка (low), не баг.**

3. **❌ TOCTOU-гонка `produce()` читает `self._backend` вне lock** (`Plugins/sources/camera_service/plugin.py:149-153`) — окно есть, но defense-in-depth (broad except + per-backend guard `_running`/`_cap is None` + ранний сброс `_is_capturing`) сводит worst-case к редкому тихому дропу 1-2 кадров при переключении камеры. **Не крэш, не потеря данных (low).**

4. **❌ TOCTOU-race `DeviceManager.upsert`** (`Services/device_hub/manager.py:159-178`) — read-modify-merge вне лока реален, НО все `upsert` идут через единственный поток `message_processor` (команды диспатчатся синхронно последовательно), supervisor `upsert` не вызывает, `thread_safe=False`. Второго конкурентного писателя нет. **Несостоятельна (invalid).**

---

## Связанные документы
- Метрики baseline: memory `project_sentrux_baseline_2026_05.md`
- Hikvision аспект: memory `project_hikvision_aspect_ratio.md` (H2)
- Конвенция слоёв: корневой `CLAUDE.md` правило №9, ADR-120
- Правила логирования: memory `feedback_logger_error_stats_managers.md` (тема M-err-*)
- Dict at Boundary: memory `feedback_dict_at_boundary_gui.md`

---
*Сгенерировано многоагентным аудитом (16 аналитиков + состязательная верификация, 32 агента, ~3.3M токенов). Каждая HIGH-находка перепроверена скептиком. Перед действием — перечитай актуальный код по `file:line`.*
