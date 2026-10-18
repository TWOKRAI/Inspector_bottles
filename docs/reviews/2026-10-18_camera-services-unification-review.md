# Ревью: объединение сервисов камер (code_reader SDK + hikvision_camera), 2026-10-18

Reviewer (Opus), только чтение. Ветка `feat/code-reader-gui`, HEAD `078b96ff3`. Чужие грязные файлы не трогал.
Раунд 1 — текст, как он был отправлен лидеру. Раунд 2 (перепроверка через graphify, qex и трёх Haiku-агентов) внёс правки на месте; каждая помечена **ИСПРАВЛЕНО в раунде 2** или **ПОДТВЕРЖДЕНО в раунде 2**. Сводка правок — раздел 5 в конце.
Продолжение (схемы «как есть» и «после плана», оценка): `docs/design/camera-device-architecture.md`.

qex в раунде 1 был недоступен, поэтому поиск шёл через `git grep` / Read. Все числа взяты из grep. В раунде 2 qex ответил: индекс от 2026-10-15, на 3 дня старше HEAD; числа по-прежнему из grep.
memory hits: `scripts/memory/search.py camera sdk session multi-camera` -> `project_camera_settings_feature.md`, `project_hikvision_aspect_ratio.md` (+ 6 процессных уроков, к теме не относятся).
Повторы я запускал через `machine_gate.sh light camera-arch-review`. Скрипты лежат в scratchpad сессии (`.../scratchpad/rev1018/repro_hik.py`, `repro_cr.py`, `graph_q.py`); в репозиторий они не входят.

## 0. Вердикт в 10 строк

1. Рекомендую **два сервиса над общим ядром**. Ядро — новый пакет `Services/camera_device/`: порт, сеанс, план параметров, база плагина и register'а, общий набор команд и наблюдаемость. Вендорские пакеты становятся тонкими драйверами. Один «сервис с двумя драйверами» не беру: он убивает живые публичные пути hikvision (4 рецепта, вкладка GUI, `camera_service`, `device_hub`).
2. Ядро проекта `camera-device-service.md` верное: поток-владелец, профиль работы при каждом старте, покой best-effort, проверка чтением. Оставляю его. Вердикт по документу — **AMEND**, 11 правок (Q8).
3. Главная дыра проекта — модель параметров. Таблица `NodeSpec` описывает поле второй раз, рядом с register'ом. Нужно одно описание: тип и `FieldMeta` поля register'а плюс таблица привязки к узлам в драйвере. Привязку сверяет контрактный тест.
4. В `FieldMeta` нет двух общих понятий: «когда правка вступает в силу» (`live`) и «поле активно, если…» (`depends-on`). Это fix-forward во framework, а не адаптер. Цена — около 150 строк framework + GUI и один ADR.
5. В проекте неверна таблица порта MVS (§3.2). `MV_CC_GetIntValue`, `GetEnumValue`, `GetBoolValue`, `SetEnumValueByString` в `Services/hikvision_camera` не обёрнуты: grep дал 0 совпадений на каждое имя.
6. Многокамерность: **процесс на камеру**. Нужна обязательная идентичность прибора (serial или ip, не индекс) и пауза перед перезапуском не меньше времени отпускания прибора (~10 с).
7. Наблюдаемость сейчас идёт мимо framework. `code_reader_sdk` пишет счётчики прямым `state_proxy.merge` (этот анти-паттерн описан в докстринге `publish_metric`). Инциденты идут через `ctx.log_error` вместо `ctx.health.report_error`. `hikvision` не публикует ничего.
8. 19 находок, 9 из них воспроизведены. Четыре дефекта Hikvision доказаны запуском: `HikvisionDriver.connect()` отвечает `True` при отказе; `get_params`/`set_params` падают на `AttributeError`; `open()` игнорирует коды записи; кадр RGB8 теряется всегда. (Раунд 2 добавил F20–F22, раздел 2.)
9. Новый план: 17 задач. 13 из них делаются на фейке без камер. Камеры нужны только для T15 (опыты H1–H6), T16 (стенд N=2) и приёмки MVS (T9/T10).
10. Владельцу — 5 вопросов (Q9). По каждому есть рекомендованный ответ, поэтому план можно писать сейчас.

## 1. Ответы

### Q1. Один сервис, два над ядром или как сейчас

**Вердикт: два сервиса над общим ядром, с общей базой плагина.**

| Вариант | За | Против | Итог |
|---|---|---|---|
| (A) один `Services/camera/` с `drivers/{mvcr,mvs}` | один пакет | удаляет или переносит живые пути `Services.hikvision_camera.*`: 4 рецепта (`hikvision_inspect`, `hikvision_letter_robot`, `camera_robot_calibration`, `dataset_circle_capture`), `Plugins/sources/camera_service/backends/hikvision.py:17`, `Plugins/hub/device_hub/plugin.py:137-142`, вкладка `frontend/widgets/tabs/services/hikvision/`. Нарушает «FREEZE not KILL». TCP-путь и разбор кодов (`code_reader/core/sink.py`, `result.py`) — это домен считывателя, не камеры | нет |
| (B) ядро + два вендорских сервиса | слоёв столько же (всё в Services); старые пути живут; DLL одного вендора не грузится в процесс другого | один новый пакет | **да** |
| (C) как сейчас | — | 4 открывателя MVS-камеры без владельца (F14), два разных API, два формата item, ноль общих тестов | нет |

Раскладка (B). Направление импорта везде: Services → framework, Services → `Services/camera_device`.

| Каталог | Что | Импортирует |
|---|---|---|
| `Services/camera_device/interface.py` | `DevicePort`, `DeviceSdk`, `DeviceIdentity`, `RawFrame`, `PortError(kind)`, `Capabilities` (Protocol / dataclass) | только stdlib |
| `Services/camera_device/params.py` | план записи из класса register'а + таблицы привязки (чистая логика) | `data_schema_module` |
| `Services/camera_device/session.py` | поток-владелец, жизненный цикл, профили run/rest, проверка чтением, очередь команд | `interface`, `params`, `logger_module` |
| `Services/camera_device/plugin_base.py` | `CameraDevicePlugin(ProcessModulePlugin)`: команды, публикация, health, контракты команд | framework `process_module.plugins` |
| `Services/camera_device/registers_base.py` | `CameraDeviceRegisters(SchemaBase)`: идентичность, auto_start, timeout, readonly-состояние | `data_schema_module` |
| `Services/camera_device/testing/fake_port.py` | честный фейк (Q8, A2) | `interface` |
| `Services/code_reader/sdk/` | без изменений; `driver.py` — адаптер `MvCodeReaderApi` -> `DevicePort` и таблица узлов | `camera_device` |
| `Services/code_reader/plugin/sdk_plugin.py` | наследник `CameraDevicePlugin`: поля кодов, overlay, labels | `camera_device`, свой `core/` |
| `Services/hikvision_camera/sdk/` | добавить привязки (Q8, A3) | — |
| `Services/hikvision_camera/driver.py` | адаптер `MvCamera` -> `DevicePort` и таблица узлов | `camera_device` |
| `Services/hikvision_camera/plugin/plugin.py` | на ядре; старые команды — алиасы (FREEZE) | `camera_device` |

Проверка слоёв. Правило `.sentrux/rules.toml:13`: «app → Plugins → Services → framework». Прямого запрета Services → Services в прочитанных строках нет. Прецедент уже есть: `Services/device_hub/drivers/hikvision_driver.py` лениво импортирует `Services.hikvision_camera`. Полный вердикт даёт только CLI `sentrux check .`, и я его не запускал (раздел 4).
**ПОДТВЕРЖДЕНО в раунде 2:** `.sentrux/rules.toml` прочитан целиком (Haiku `a0493933119852a84`, выборочно перепроверено). Границы работают как deny-список: «отсутствие boundary = разрешено» (`:270-271`). Запрещены только 4 пары Services → Services (`:159-177`: `layer_render` -> `line_sim`, `dataset_gen`, `ml_train`; `dataset_gen` -> `line_sim`). `code_reader` -> `camera_device` и `hikvision_camera` -> `camera_device` не запрещены. CLI `sentrux check .` по-прежнему не запускался.

### Q2. Общий порт

Проект даёт 8 методов: `enum_devices, open, get_node, set_node, start_grabbing, get_frame, stop_grabbing, close`. Их достаточно для минимума, но для двух SDK и третьего вендора этого мало. Предлагаю так:

```
class DeviceSdk(Protocol):      # одно на процесс, счётчик ссылок
    def acquire(self) -> None   # загрузка DLL; MV_CC_Initialize, если SDK его требует
    def release(self) -> None
    def enum_devices(self) -> list[DeviceIdentity]   # ip, serial, model, mac, user_name, transport

class DevicePort(Protocol):     # один открытый прибор; ВСЕ вызовы — из потока-владельца
    capabilities: frozenset[str]   # "codes","self_trigger","software_trigger","node_describe","exception_cb","user_sets"
    def open(self, ident: DeviceIdentity) -> None          # PortError(kind="busy"|"not_found"|"network")
    def get_node(self, node: str, kind: NodeKind) -> Any   # значение в каноне: enum — символьное имя
    def set_node(self, node: str, kind: NodeKind, value: Any) -> None
    def describe_node(self, node: str) -> NodeInfo | None  # min/max/inc/entries/access; None без "node_describe"
    def execute(self, node: str) -> None                   # TriggerSoftware; только при "software_trigger"
    def start_grabbing(self) -> None
    def get_frame(self, timeout_ms: int) -> RawFrame | None  # копия; буфер SDK освобождён ДО возврата
    def stop_grabbing(self) -> None
    def close(self) -> None
```

Где живут различия вендоров:
- **Коды ошибок** приходят как `PortError(code, where, kind)`. Код переводит в `kind` адаптер, сеанс знает только `kind`. Пример: ID3013 `E_ACCESS_DENIED=0x80020203` (`code_reader/sdk/errors.py:14`), у MVS свой код. Сейчас `_fail_open` сверяет вендорский код прямо в сеансе (`sdk_reader.py:308`).
- **Кадр.** `RawFrame{data: bytearray, width, height, pixel_format: str, frame_num, extras: dict}`. Коды ID3013 лежат в `extras["codes"]`. `pixel_format` — канонические строки (`mono8`, `bayer_rg8`, `rgb8`, `jpeg`), а не номера SDK. Форму кадра по формату задаёт адаптер (это лечит F4).
- **Выбор прибора** — только по `DeviceIdentity` (serial, затем ip, затем user_name). Индекс остаётся одним из селекторов для старого API `hikvision`, но с WARNING (F13).
- **Глобальное состояние SDK** лежит в `DeviceSdk`, отдельно от прибора. При процессе на камеру это тривиально, но контракт должен быть явным для третьего вендора (GenTL/Harvesters держат один producer на процесс).

### Q3. Модель параметров

Что `data_schema_module` умеет сегодня (`multiprocess_framework/modules/data_schema_module/core/field_meta.py:172-192`, `__slots__`):

| Нужно | Есть | Где |
|---|---|---|
| тип | да, аннотация pydantic | — |
| диапазон | `min`, `max` | `:229-230` |
| шаг | `transfer_k` (шаг = 1/k) | `:203` |
| enum | `Literal[...]` + `widget="literal"`; правило `choices_map` | `:56-75`, `:89-90` |
| единица | `unit` | `:199` |
| группа (визуальная) | `ui_group`, `ui_order` | `:220-221` |
| только чтение | `readonly` | `:209` |
| умолчание | default поля pydantic | — |
| межполевое | только `le_field` | `:85-86` |
| **живая запись (live)** | **нет** | grep `-i` по `live_writable` и слову `live` в `data_schema_module` и `registers_module`: 2 совпадения, оба в комментариях (`schema_base.py:48`, `manager.py:367`) |
| **зависит от (depends-on)** | **нет** | grep `-i` по `visible_if`, `enabled_if`, `depends_on`, `show_if`: 0 совпадений |
| **узел прибора, тип узла** | нет, и во framework быть не должно | — |
| экспорт для GUI | `get_all_fields_meta()`, `to_dict()`/`from_dict()` (IPC-кодек) | `schema_mixin.py:69-90`, `field_meta.py:364-413` |

Решение — описать параметр **один раз**, в поле register'а:
- (a) валидация конфига, (b) поле register'а, (c) карточка GUI, (e) рецепт YAML уже выводятся из `Annotated[T, FieldMeta]`. Рецепт ложится в register через `_init_register` (`process_module/plugins/base.py:1484-1487`).
- (d) `backend_ctl`: ~~`introspect_registers` берёт метаданные оттуда же~~. **ИСПРАВЛЕНО в раунде 2:** `introspect.registers` отдаёт **только значения** (`rm.model_dump_all()`, `process_module/commands/builtin_commands.py:780-783`), `introspect.capabilities` — только **имена** полей (`:896-897`). Ни `min/max`, ни `unit`, ни `readonly` агент через backend_ctl не видит. Это дыра framework: нужен ответ с метаданными (`FieldMeta.to_dict()` уже есть, `field_meta.py:364`); вынесено в совет №1 файла архитектуры. Плюс в снимке состояния публикуется `params_meta` — диапазон, который сообщил прибор (`describe_node`). Он может быть уже статического диапазона схемы.
- **Fix-forward во framework** (общие понятия, не про камеры):
  1. `FieldMeta(apply="live"|"restart"|"config")` — когда правка вступает в силу. Пригодится и `camera_service` (разрешение требует перезапуска).
  2. `FieldMeta(enabled_if={"trigger_mode": ["On"]})` — GUI гасит поле, валидация не требует его значения.

  Цена: `__slots__` + `to_dict`/`from_dict` + фабрика форм + снимок каталога + тесты. Оценка ~100–150 строк, ADR-DS. Значения по умолчанию аддитивные, 130 наследников `SchemaBase` (число из докстринга `field_meta.py:269`) ничего не платят.
- **В драйвере** остаётся только привязка: `NODES = {"trigger_mode": ("TriggerMode", "enum_str"), …}`. Контрактный тест: `set(NODES) == {вендорские поля register'а}`, и тип узла совместим с типом поля. Группа «целиком» = поля с общим `ui_group` и связью `enabled_if`. Отдельного `group` в `NodeSpec` не нужно.
- **«Не управлять»** = `None`, а не `0`/`""`. Сейчас `trigger_period_ms` держит `min=0` только потому, что умолчание 0 ниже минимума прибора 32 (`sdk_registers.py:77-79`), а `_parse_trigger` считает `0` и `""` за «не трогать» (`sdk_reader.py:122`). Нужно `int | None = None`, `min=32`. ~~Пропускает ли фабрика форм GUI `Optional` — не проверял.~~ **ИСПРАВЛЕНО в раунде 2:** фабрика форм снимает `Optional` с одним типом (`int | None` -> `int`, `multiprocess_prototype/frontend/forms/factory/kinds.py:76-81`; тесты `test_factory.py:173`, `test_factory_characterization.py:85`), то есть поле рисуется спинбоксом. Как спинбокс показывает `None`, не проверено. Для «не управлять» надёжнее явный флаг группы (`trigger_managed: bool`) + `enabled_if`, а не `None` в числе. `Literal[...]` рисуется как combo (`kinds.py:145-146`, тест `test_factory.py:116`); `ui_group` группирует поля (`form_builder.py:174`).
- Если владелец откажет во framework-правке, запасной путь — `live` и `enabled_if` в таблице драйвера. Тогда GUI не узнает о зависимости полей, и это неполное решение цели 3.

### Q4. Контракт данных

Сейчас форматы расходятся:

| Ключ | `code_reader_sdk` (`sdk_plugin.py:210-224`) | `hikvision` (`plugin/plugin.py:185-198`) |
|---|---|---|
| кто | `reader_id: str` | `camera_id: int` |
| номер | `seq_id`, без переполнения | `seq_id` = `frame_id`, по модулю 121 (`:35`, `:183`) |
| время | `ts = time.time()` (`:248`) | `timestamp = time.monotonic()` (`:192`) |
| кадр | `frame` серый uint8 (H,W) | `frame` BGR, уже ресайз |
| формат | `pixel_format: "jpeg"/"mono8"` | `camera_type`, `channels`, `dtype` |

Предлагаемый единый конверт item (только `dict`; ndarray — только под `frame`, чтобы SHM claim check его видел — `sdk_plugin.py:14-17`):
- общее: `frame`, `device_id` (str из register'а), `seq_id` (int, растёт без переполнения), `ts` (wall `time.time()`, сравнимо между процессами), `device_frame_num`, `pixel_format` (канон), `width`, `height`;
- считыватель добавляет: `code`, `status`, `codes`, `overlay`, `trigger_index`, `no_read_num`;
- старые ключи `hikvision` (`camera_id`, `frame_id`, `timestamp`, `camera_type`) остаются алиасами (FREEZE): у них есть живые потребители. ~~Кто читает `frame_id` по модулю 121, я не искал.~~ **ИСПРАВЛЕНО в раунде 2** (Haiku `a822086259c19e967`, выборочно перепроверено): сравнений `frame_id` по порядку или равенству вне тестов нет. Читатели есть:
  - `Plugins/io/frame_saver/plugin.py:213` — `frame_id` как номер файла, если `index_source == "frame_id"` (по умолчанию `counter`). С модулем 121 файлы перезаписываются каждые 121 кадр (F20);
  - `Plugins/_shared/fanin/join_inspector_manager.py:132`, `inspector_manager.py:63-66` — ключ `(camera_id, seq_id)`. `seq_id` у hikvision тоже по модулю 121 (`plugin.py:189`): ключ повторяется каждые 121 кадр, при 25 к/с это 4,8 с. Окно сборки — около 1 с (по умолчаниям из отчёта Haiku, не мерил), поэтому столкновение маловероятно, но не исключено (F20);
  - `Plugins/io/database/plugin.py:121` пишет `timestamp` как есть, а без ключа берёт `time.time()`: в одной колонке два разных часа (F21).
  Тот же модуль 121 стоит у `Plugins/sources/camera_service/plugin.py:31` и `Services/phone_gateway/plugin/plugin.py:38`; у `capture` — 100 000 (`Plugins/sources/capture/plugin.py:23`).

Каналы:
- **кадры** — порт `frame`;
- **результаты** — порты `code`/`overlay` (уже объявлены, `sdk_plugin.py:81-102`);
- **управление и IO** — общий набор команд (Q6) + `register_update` -> подписка -> очередь владельца;
- **статус** — уровни через `ctx.publish_metric` (`processes.<p>.state.plugins.<плагин>.<имя>`, `base.py:885`), событийное состояние (`state`, `device_held`, `profile`, `param_errors`, `params`) — через `merge` при смене, как у `CapturePlugin` (`Plugins/sources/capture/plugin.py:327-337`).

Жёсткий путь `processes.{p}.state.code_reader_sdk` (`sdk_plugin.py:369`) и register по имени плагина (`base.py:1479`) запрещают два экземпляра в одном процессе. При процессе на камеру это допустимо, но в README ядра это надо записать как инвариант.

### Q5. N камер

**Вердикт: процесс на камеру** (так уже устроены dual-рецепты: `reader_1`, `reader_2`).

| Модель | Изоляция | Глобальное SDK | GIL / декод | Итог |
|---|---|---|---|---|
| процесс на камеру | падение ctypes роняет один процесс, PM его поднимает | своё на процесс, без счётчика | раздельно | **да** |
| поток на камеру в одном процессе | падение DLL роняет все | общее; `_lib` грузится без замка (`code_reader/sdk/api.py:87-88`), `_dll_dir_cookies` глобальный (`loader.py:29`) | общий | нет |
| N сеансов в одном процессе | то же | то же | то же | нет; ещё и столкновение путей (Q4) |

Что ломается при 3 камерах (по коду):
1. `device_ip=""` = «первый найденный». Два читателя открывают один прибор. **Повтор R5** (фейк, 2 прибора): `opened: ['192.168.1.10', '192.168.1.10']`. На железе второй получит `busy`.
2. `hikvision` выбирает прибор по `camera_index` (`camera.py:128-140`; так же `camera_service/backends/hikvision.py:81`, `sdk_app/main_window.py:294`). Порядок GigE-перечисления не обещан. ADVISORY: без камер не воспроизводится.
3. Четыре независимых открывателя MVS-камеры (F14). Нет владельца — значит, `busy` по случайности.
4. Пропускная способность: ID3013 ~33 Мбит/с — факт стенда (handoff §4.1). У MVS-камер на 1 ГбЕ полный кадр может забрать канал целиком. Бюджет (`GevSCPD`, packet size) должен стать параметром таблицы, а не скрытой записью (`camera.py:163-166`).
5. Перезапуск: прибор отпускается через ~10 с после убийства (один замер, handoff §4.1). Значит, пауза перед перезапуском у супервизора ≥ 10 с, иначе цикл `busy`.
6. Одновременный `EnumDevices` из N процессов — шторм broadcast. Для двух процессов прошло (ревью 10-17), для трёх не проверено.

**ПОДТВЕРЖДЕНО в раунде 2 (graphify, граф собран на HEAD `078b96ff3`):** вне пакетов камер на узлы `Services/code_reader` и `Services/hikvision_camera` ссылаются 23 нетестовых файла. Больше всего связей у `Plugins/sources/camera_service/backends/hikvision.py` (20) и `Services/device_hub/drivers/hikvision_driver.py` (7), плюс 3 рецепта и `Plugins/hub/device_hub/plugin.py`. Граф видит импорты, но не связь через имена команд по IPC: вкладка GUI `services/hikvision/presenter.py:80-115` шлёт `open`, `close`, `start_capture`, `stop_capture`, `set_parameters`, `enum_devices`, `get_parameters` — это нашёл только grep. Значит, алиасы старых команд (Q9-3) нужны.

### Q6. Наблюдаемость

Что сеанс и плагин должны отдавать через **существующие** средства:

| Средство | Что | Где во framework |
|---|---|---|
| `ctx.declare_metric` + `ctx.publish_metric` (уровни, под гейтом) | `fps`, `frames`, `errors`, `dropped`, `pending`, `param_errors_count` | `base.py:803`, `:885`; образец `capture/plugin.py:104-106`, `:365-367` |
| `ctx.record_metric` / `gauge` / `record_timing` (stats-плоскость) | `get_frame_ms`, `apply_ms` по узлу, `open_ms`, `stop_grabbing_ms`, `frame_interval_ms` | `base.py:689-731`; образец `capture/plugin.py:246-250` |
| `ctx.health.report_error` (инцидент: одна дверь, ADR-PM-030) | отказ open/busy, 3 ошибки `get_frame`, отказ покоя, неподтверждённая запись | `base.py:204-252` |
| `ctx.health.degraded/set_status` | `busy`, `not_found`, `error` | там же |
| `merge` событийного состояния | `state`, `device`, `device_held`, `profile`, `params`, `params_meta`, `param_errors`, `last_error`, `capabilities` | `capture/plugin.py:327-337` |
| `ctx.log_info` с ключами | `device_id= ip= serial= node= value_written= value_read= rc=0x… ms= thread=` | — |
| `ctx.flight_dump` | смерть потока-владельца | `base.py:592` |
| метрики команд (уже бесплатно) | попытки, ошибки, длительность каждой команды | `command_module/core/command_manager.py:262-317` (`command_manager.command.execution.*`) — **добавлено в раунде 2** |
| контракты параметров команд | `MessageContractRegistry` -> `introspect.capabilities` показывает `params_schema` | ~~в плагинах это зовёт только `Plugins/io/otel_export/plugin.py`~~ — см. исправление ниже |

**ИСПРАВЛЕНО в раунде 2.** В раунде 1 я написал, что контракт своей команды регистрирует `Plugins/io/otel_export/plugin.py`. Это неверно: мой grep совпал с комментарием (`otel_export/plugin.py:119`), вызова `register` там нет. Haiku `a0493933119852a84` нашёл, я перепроверил:
- реестр (`message_module/contracts/registry.py:92`, метод `register(key, schema, …)` `:102`) наполняется только встроенными контрактами (`builtin_commands.py:4137-4143`, и только при наличии router);
- команды плагина регистрируются без метаданных: `ctx.command_manager.register_command(cmd_name, method)` (`process_module/plugins/base.py:1676`). У них в `capabilities` пустое описание и нет `params_schema`;
- grep `registry.register(` / `MessageContractRegistry(` по `Plugins/` — 0 совпадений.
Вывод: дать командам камеры форму параметров сейчас нечем. Нужен fix-forward во framework: атрибут плагина `command_contracts = {"take_device": TakeDeviceParams, …}` и описание из докстринга, которые `_auto_register_commands` передаёт в реестр. Это ~40–60 строк framework + тест; задача T6a в файле архитектуры.

Общий набор команд — одинаковый у обоих сервисов: `take_device`, `release_device`, `get_status`, `reset_stats`, `list_devices` (перечисление без открытия), `read_params` (чтение управляемых узлов), `describe_params` (диапазоны прибора), `apply_params` (живая правка), `trigger_software` (при наличии capability).

Диагноз агентом без исходников: `capabilities` -> `introspect_registers` -> `state_get processes.<p>.state` -> `set_register_verified` + сверка `state…params` -> `telemetry_snapshot` / `introspect_queues` -> `log_tail` / `history_query`.
**ИСПРАВЛЕНО в раунде 2 (уточнение):** `set_register_verified` проверяет **register, а не прибор**: запись, потом одно чтение `introspect.registers` и сравнение (`backend_ctl/registers.py:139-174`). Для камеры «verified» будет `True`, даже если узел в прибор не записался. Проверка прибора — только по `state…params` (например, `await_condition` на путь дерева). Это надо прописать в README ядра и в приёмке T16.

Нарушения сейчас:
- `code_reader_sdk` публикует уровни прямым `proxy.merge` при каждом `produce()` с кадрами и тянет в снимок историю из 20 записей (`sdk_plugin.py:199-207`, `:363-372`). Докстринг `publish_metric` (`base.py:893-899`) называет этот путь дефектом: «ехал мимо гейта, мимо тика и мимо опроса».
- Инциденты идут через `ctx.log_error` (`sdk_plugin.py:292`, `:300`; `hikvision/plugin/plugin.py:150-152`, `:174`).
- `hikvision` не публикует состояние вообще: в `Services/hikvision_camera/plugin/plugin.py` нет ни `state_proxy`, ни `publish_metric`, ни `declare_metric` (файл прочитан целиком).

Чего во framework не хватает: `FieldMeta.apply` и `enabled_if` (Q3). **Добавлено в раунде 2:** метаданные в `introspect.registers` и контракты команд плагинов (выше).

### Q7. Дефекты и костыли сейчас

Полный список — в разделе 2. Главное:
- **Владение потоками** (H2): open и запись идут в потоке вызывающего, возврат и close — в потоке захвата. Повтор R4a: `caller-thread calls: ['enum','get','open','set','start'] | other-thread calls: ['close','restore','stop']`.
- **Код ≠ результат**: `HikvisionCamera.open` игнорирует коды записи (R6). `set_parameters` проверяет коды (`parameters.py:107-131`), но чтением не сверяет.
- **Отравление возврата** (A3 ревью 10-17) подтверждено независимо (R4b/c).
- **Shutdown**: `kill_tree` идёт после выхода PM (`process_manager_module/launcher/spawner.py:200-224`). Дети, поднятые full-replace, по логам стенда не успевают выполнить `shutdown()`. Это унаследовано, код PM я не разбирал (раздел 4).
- **Копии кадра и частота публикации**: оценки проекта §5 перепроверены только чтением (`api.py:203` `string_at`, `sdk_frame.py:157` `bytes(raw.image)` — ещё одна копия, которой нет в проекте, `:182` `.copy()`). Без замера.
- **Throttling**: `cmd_set_*` у hikvision держит `_camera_lock` на `sleep(0.2)` + 5 записей. Всё это время `produce()` стоит (F11).

### Q8. Проект и планы

**`docs/design/camera-device-service.md` — AMEND.** Ядро сохраняется: §2.2 (a)+(c), проверка чтением, §3.1 поток-владелец, §4 «PM и device_hub прибором не владеют». Правки:

- **A1.** §2.4: таблица `NodeSpec(key,node,kind,group,requires,live)` -> поле register'а (тип + `FieldMeta` с `apply`/`enabled_if`/`ui_group`) + таблица привязки `field -> (node, kind)` в драйвере + контрактный тест равенства ключей. «Не задано» — явный флаг группы (уточнено в раунде 2, Q3).
- **A2.** §3.2: добавить `DeviceSdk` (общее на процесс), `PortError.kind`, `DeviceIdentity`, `describe_node`, `execute`, `capabilities`; `get_frame` копирует и освобождает буфер внутри порта. Фейк моделирует: закрытые узлы (`0x80020106`-аналог), H1 (`neter_after_stop`), H5 (`applied_but_error`), коэрцию значения прибором (запись 1234.5 -> чтение 1234.0), `busy` ~10 с после «убийства», журнал id потоков.
- **A3.** §3.2, столбец MVS: имена `MV_CC_Get{Int,Enum,Bool}Value` и `SetEnumValueByString` не обёрнуты (grep по `Services/hikvision_camera`: 0 / 0 / 0 / 0). Есть только `GetFloatValue`, `Set{Enum,Bool,Float,Int}Value` (`sdk/bindings.py:278-379`). Добавить привязки и `RegisterExceptionCallBack`, `SetCommandValue` (тоже 0). Нужен ли `MV_CC_Initialize` — проверить по экспортам DLL (0 совпадений в коде).
- **A4.** §3.4/§5: публикация — `publish_metric` для уровней, `merge` только при смене событийных ключей, `health.report_error` для инцидентов, контракты команд — после framework-правки (Q6, исправлено в раунде 2). `state_publish_hz` не нужен как своё поле: частоту уровней задаёт тик framework.
- **A5.** §4: добавить в ядро `plugin_base.py` и `registers_base.py` (общий API, Q1). Без них «похожий API» держится на дисциплине.
- **A6.** Опись скрытых записей MVS: кроме `TriggerMode=Off`, ещё `AcquisitionFrameRateEnable=True` (`camera.py:170`), `GevSCPSPacketSize` (`:166`), `ExposureAuto=0` + `sleep(0.2)` (`parameters.py:113-118`). Все в таблицу и профиль.
- **A7.** Проверка чтением для float/int: «подтверждено», если `|read − target| ≤ max(inc, eps)`; в `params` писать прочитанное, а не цель. Enum сравнивать по символьному имени.
- **A8.** §3.5: перезахват при живой правке — политика по capability, которую установит опыт H1 (T15). Фейк реализует обе ветки.
- **A9.** Многокамерность явно: процесс на камеру, идентичность обязательна; пустой `device_ip` разрешён только при `select: first`. Пауза перезапуска ≥ время отпускания.
- **A10.** Task 1.10: кроме отказа «камерой владеет процесс X», честные ошибки `connect`/`get_params`/`set_params` (F1, F2). Сейчас они врут.
- **A11.** Срочный fix-forward на живом пути `hikvision`, не дожидаясь сеанса: F4 (RGB8) и F10 (register не применяется при старте). Отдельная маленькая задача T12.

**`plans/code-reader-sdk.md`** — история, Ф6 закрыта (`:286-294`). Оставить, отметить DONE. Правок нет.
**`plans/code-reader-gui.md`** — заголовок `DRAFT` и «Порядок выполнения» (`:76-96`) устарели: везде `[PENDING]`, хотя 2.1 и 2.2a сделаны. Правки: статусы; 2.2b -> «заменена `plans/camera-device-service.md`»; 3.1 зависит от T16 нового плана; 2.3 остаётся и зависит от T6 (форма строится из register'а ядра).
**`plans/code-reader-gui/phase-2.md`** — 46 188 байт при лимите 32 КБ: разделить по `##` (handoff §1 п.7). 2.2b (`:262-328`) — в архив раздела, со ссылкой на новый план.

### Q9. Вопросы владельцу (с рекомендацией)

1. **Раскладка:** ядро `Services/camera_device/` + два вендорских сервиса (рекомендую), или слить всё в один сервис со сносом старых путей?
2. **Framework-правка `FieldMeta`:** добавить `apply` и `enabled_if` (рекомендую, общее понятие, ADR-DS), или держать их в таблице драйвера (GUI не узнает о зависимостях)? Раунд 2 добавил сюда же две малые framework-правки для backend_ctl: метаданные в `introspect.registers` и контракты команд плагинов.
3. **Старое API `hikvision`** (`open/close/start_capture/set_exposure`, `camera_index`): оставить алиасами над общими командами и пометить legacy (рекомендую, FREEZE), или переименовать сразу и поправить 4 рецепта и вкладку?
4. **Остаточный риск убийства:** камера остаётся в профиле работы до следующего старта. Принять и чинить выход во framework (T14)? Рекомендую принять.
5. **Железо и третий вендор:** есть ли MVS-камера для стенда, и планируется ли третий вендор (GenTL/Harvesters, Basler)? Рекомендую: порт проектировать под GenICam в общем виде; MVS-приёмку — когда появится камера.

## 2. Находки

| id | sev | file:line | вход -> наблюдаемый выход | repro |
|---|---|---|---|---|
| F1 | major | `Services/device_hub/drivers/hikvision_driver.py:67-78` -> `Services/hikvision_camera/core/camera.py:128` | serial `"SN1"`, SDK доступен, 2 прибора -> `connect() -> True`, `is_connected -> False`, `_last_quality -> good`, on_error `'>=' not supported between instances of 'str' and 'int'` | да (R1) |
| F2 | major | `hikvision_driver.py:143-159` | `call("get_params", {})` на открытой камере -> `{'status':'error','message':"'CameraParameters' object has no attribute 'get_all'"}`; `set_params` -> `…no attribute 'set'` | да (R2) |
| F3 | major | `Services/hikvision_camera/core/camera.py:161-170` | `SetEnumValue(TriggerMode)` и `SetBoolValue(AcquisitionFrameRateEnable)` отвечают `0x80000106` -> `open(0) -> True`, `state OPEN`, ошибки нет | да (R6, фейк `MvCamera`) |
| F4 | major | `camera.py:318-322`; ветки `converter.py:63-68` недостижимы | кадр RGB8 4×2 (24 байта) -> `(None, 0)`, on_error `cannot reshape array of size 24 into shape (2,4)`; так на каждом кадре любого многобайтного формата | да (R3) |
| F5 | major | `Services/code_reader/core/sdk_reader.py:186-243` vs `:377-402` | start+stop на фейке -> вызовы потока теста: `enum,get,open,set,start`; другого потока: `stop,restore,close` | да (R4a) |
| F6 | major | `sdk_reader.py:262`, `:273`, `:294` | прибор `0/0/300`, рецепт `On/SelfTrigger/40`, возврат отказал -> узлы `1/9/40`, `errors 3`; второй start+stop «возвращает» в `1/9/40` | да (R4b/c) |
| F7 | medium | `sdk_reader.py:204`, `plugin/sdk_registers.py:25-28` | два читателя, `device_ip=""`, 2 прибора -> оба открывают `192.168.1.10` | да (R5, фейк) |
| F8 | major | `Services/code_reader/plugin/sdk_plugin.py:199-207`, `:363-372` | кадры 25 к/с при `produce` 20 Гц -> до 20 `merge`/с с историей 20 записей, мимо гейта телеметрии (`base.py:893-899`) | чтение (частота — оценка) |
| F9 | medium | `sdk_plugin.py:292`, `:300`; `hikvision_camera/plugin/plugin.py:150-152`, `:174` | ошибка захвата -> только строка `ctx.log_error`, нет записи в плоскости ошибок и в health (ADR-PM-030) | чтение |
| F10 | major | `hikvision_camera/plugin/plugin.py:213-228`; fixed-string grep `registers.subscribe(` по `Services/`, `Plugins/`, `process_module` без тестов -> 0 | рецепт `exposure_time: 5000` -> при старте в камеру не пишется; `register_update` из GUI меняет только register | чтение + grep |
| F11 | medium | `parameters.py:101-131`, `plugin.py:243-266`, `:381-390` | `set_exposure` -> 5 записей + `sleep(0.2)` под `_camera_lock`; `produce()` стоит ≥200 мс; `set_frame_rate 12.5` -> `int` -> 12 | чтение |
| F12 | medium | `plugin.py:112-122` | `camera_id/camera_index/fps/auto_start` берутся из `ctx.config.get`, не из register'а -> не валидируются, GUI их не правит, два источника истины | чтение |
| F13 | major | `camera.py:96-140`, `camera_service/backends/hikvision.py:81`, `sdk_app/main_window.py:294` | ≥2 камер, выбор по индексу -> соответствие индекс->прибор не обещано | ADVISORY |
| F14 | major | `plugin.py:400-422` (`open_sdk_app`), `device_hub/plugin.py:137-142`, `camera_service/backends/hikvision.py:67` | 4 открывателя одной MVS-камеры без владельца; `open_sdk_app` запускает процесс, который открывает камеру, уже занятую плагином | чтение |
| F15 | medium | `plugin.py:35`, `:183-197`; `sdk_plugin.py:248` | `seq_id` по модулю 121 и `monotonic` у hikvision против растущего `seq_id` и `time.time` у считывателя -> один потребитель не может их сравнить | чтение |
| F16 | minor | `hikvision_camera/sdk/bindings.py:93` | импорт `Services.hikvision_camera` грузит `MvCameraControl.dll` побочным эффектом (в моём прогоне `SDK_AVAILABLE(real) = True` уже при импорте) | да |
| F17 | minor | `sdk_registers.py:53-81` | `trigger_source: "SelfTriger"` принимается register'ом, отказ виден только после записи в прибор; `0` = «не трогать» при `min=0` | чтение |
| F18 | major (док) | `docs/design/camera-device-service.md` §3.2; `bindings.py:128-379` | таблица порта MVS называет 4 функции, которых нет в обёртке (grep: 0 на каждую) | да (grep) |
| F19 | medium | `sdk_plugin.py:369`, `process_module/plugins/base.py:1479` | два `code_reader_sdk` в одном процессе -> один путь дерева и один register | чтение |
| F20 | medium (раунд 2) | `Services/hikvision_camera/plugin/plugin.py:183-189` -> `Plugins/io/frame_saver/plugin.py:213`, `Plugins/_shared/fanin/join_inspector_manager.py:132` | `index_source: frame_id` -> имя файла повторяется каждые 121 кадр, старый файл перезаписан; ключ fan-in `(camera_id, seq_id)` повторяется каждые 121 кадр (4,8 с при 25 к/с) | чтение (Haiku + выборочно я) |
| F21 | minor (раунд 2) | `Plugins/io/database/plugin.py:121` | item hikvision (`timestamp` = `monotonic`) и item без ключа (`time.time()`) -> в одной колонке два разных часа | чтение |
| F22 | minor (раунд 2) | `Services/hikvision_camera/service.py:1-69` | `HikvisionCameraService.start()` всегда `True`, `get_status()` -> `"running"`, хотя ничего не запущено (shell, TODO Phase 4+) -> ложный статус в `ServiceRegistry` | чтение |

Ещё один костыль, minor: пустой `except: pass` в `plugin.py:436-440`.

Сверка с ревью 10-17 (прочитано после своего прохода). A3 подтверждаю (F6). «HikvisionDriver: серийник в `open(int)`» там было «не воспроизводил» — теперь воспроизведено, и найдены ещё два дефекта того же драйвера (F1: ложное `True`; F2). Риски многокамерности из той таблицы совпадают с Q5. Новое в этом проходе: F3, F4, F8–F15, F18, F19; в раунде 2 — F20–F22.

## 3. Задачи нового плана `plans/camera-device-service.md`

Заменяет Task 2.2b. Task 2.3 остаётся в `code-reader-gui`. «Фейк» = делается без камер.

| T | Суть | Зависит | Исполнитель / ревью | Железо |
|---|---|---|---|---|
| T0 | ADR «ядро camera_device + два драйвера»; `sentrux check .` на правило Services->Services | — | Opus (tech-writer по решению) | нет |
| T1 | framework: `FieldMeta.apply`, `enabled_if`; фабрика форм гасит поле; снимок каталога | T0, Q9-2 | Sonnet; Opus stage 0 (API framework) + ревью | нет |
| T2 | `interface.py` + README (contract) + честный фейк (A2) + контрактный тест порта | T0 | Sonnet; Opus stage 0 | нет |
| T3 | `params.py`: план из register'а + привязка; контрактный тест ключей | T1, T2 | Sonnet; Sonnet-ревью | нет |
| T4 | сеанс: поток-владелец, жизненный цикл, очередь команд, `DeviceSdk` | T2 | Sonnet после Opus stage 0; Opus-ревью кода | нет |
| T5 | профили run/rest, проверка чтением с допуском (A7) | T3, T4 | Sonnet; Opus stage 0 + ревью | нет |
| T6 | `plugin_base` + `registers_base`: общие команды, `publish_metric`, health | T4, T6a | Sonnet; Opus-ревью | нет |
| T6a | **(раунд 2)** framework: контракты и описания команд плагинов в `_auto_register_commands`; метаданные `FieldMeta` в ответе `introspect.registers` | T0 | Sonnet; Opus stage 0 (API framework) | нет |
| T7 | `code_reader_sdk` на ядре; тесты 2.2a перенесены; ключи `stats()` сохранены | T5, T6 | Sonnet; Opus-ревью | нет |
| T8 | живая правка: подписка register'а -> очередь владельца; перезахват по capability | T7 | Sonnet или teamlead; Opus | фейк; политика — после T15 |
| T9 | MVS: новые привязки (A3) + адаптер + фейк MVS; общий контрактный тест | T2 | Sonnet; Opus-ревью | фейк; приёмка — камера |
| T10 | `hikvision` на ядре; старые команды — алиасы; селектор serial/ip; 4 рецепта без правок зелёные | T6, T9 | Sonnet; Opus-ревью | фейк; приёмка — камера |
| T11 | `device_hub` `HikvisionDriver`: отказ «владеет процесс X», честные ошибки (F1, F2) | T10 | Sonnet; Sonnet-ревью | нет |
| T12 | срочно, до T10: F4 (форма по формату пикселя), F10 (register при старте), F3 (коды проверять) | — | Sonnet; Sonnet-ревью | нет |
| T13 | копии кадра (проект 1.7) + `bytes(raw.image)` `sdk_frame.py:157` | T7 | Sonnet | нет; замер — стенд |
| T14 | framework: выход приложения, `INSPECTOR_LOG_DIR` после full-replace (проект 1.8) | — | investigator -> teamlead (Opus) | нет |
| T15 | опыты H1–H6 (проект 1.0) | камеры в сети | лидер; числа — Haiku; вывод — Opus | **да** |
| T16 | стенд N=2 (3, если есть): 5 мин, `telemetry_snapshot`, `introspect_queues`, `dropped=0`, fps ≥ 24; проверка прибора по `state…params`, а не `set_register_verified` | T7, T13, T15 | лидер + Haiku; Opus — вывод | **да** |
| T17 | рецепты (поля и профили) + README/STATUS | T7, T10 | Haiku по точному диффу | нет |

Порядок: T0 -> (T1 ‖ T2 ‖ T6a ‖ T12 ‖ T14) -> T3, T4 -> T5 -> T6 -> T7 -> (T8 ‖ T13 ‖ T9 -> T10 -> T11) -> T17. T15 — как только камеры в сети; T16 — последней.
Параллельно можно только задачи без общих `Files:`: T1 (`data_schema_module`, фабрика форм) и T6a (`process_module`) пересекаются в снимке каталога только косвенно — проверить `Files:` при написании плана.

Стоимость, оценка: в среднем 3,5 запуска агента на задачу × 18 задач ≈ 63 запуска × (~56k старт + ~70k работа) ≈ 8M токенов. Opus-доля — ~20 запусков (stage 0 и ревью). Работа на запуск (~70k) — моя оценка, не замер.

Риски (механизм, не обещание):
- H1 подтвердится -> покой после `stop_grabbing` не пишется -> T5 идёт по ветке `close -> open` в потоке владельца (фейк покрывает обе ветки).
- Спинбокс не показывает `None` -> «не задано» в GUI не видно -> вместо `None` явный флаг группы + `enabled_if` (раунд 2, Q3).
- ~~`sentrux` запрещает Services->Services~~ — **ИСПРАВЛЕНО в раунде 2:** не запрещает (Q1); риск снят, CLI-проверка остаётся в T0.

## 4. Что я оставил открытым / ненадёжным

Состояние после раунда 2: закрытые пункты зачёркнуты, со ссылкой на раздел, где закрыты.

- ~~`sentrux check .` не запускал; вывод о Services->Services держится на одном прецеденте.~~ Правила прочитаны целиком (Q1). CLI `sentrux check .` всё ещё не запускал.
- Нужен ли `MV_CC_Initialize/Finalize` для установленной версии MVS — не знаю. Экспорты DLL не смотрел. Версию SDK не читал.
- ~~Фабрику форм GUI не читал.~~ Закрыто (Q3): `Literal` -> combo, `Optional` с одним типом снимается. Открыто: как спинбокс показывает `None`.
- ~~Кто потребляет `frame_id` и `timestamp` hikvision — не искал.~~ Закрыто (Q4, F20, F21). Открыто: `frame_saver` `_write_sidecar` (`plugin.py:265`) и читатели в `chain_module` (метаданные `seq_id`) не прослежены до источника.
- F8 (частота `merge`), F11 (блокировка `produce()`) и оценки копий кадра — только чтение кода, без замера.
- F13 (порядок перечисления GigE) — механизм ясен, но без камер это ADVISORY.
- Shutdown: код PM (`spawner.py:185-230`) прочитал только частично. Почему дети не успевают выполнить `shutdown()`, не разобрал — это T14. E9 (процесс живёт 4,6 с) не разбирал.
- Повторы R1–R6 идут на фейках `MvCamera`/API, а не на SDK. Они доказывают логику Python-кода, но не поведение прибора (H1–H6 открыты).
- ~~`introspect_registers` не открывал.~~ Закрыто (Q3 d): только значения. Вкладку GUI `services/hikvision` я прочитал только по именам команд.
- ~~`MessageContractRegistry`: API регистрации не читал.~~ Закрыто (Q6): плагины контракты не регистрируют, утверждение раунда 1 про `otel_export` было неверным.
- Подозрения handoff §9 про `overlay_draw` (`float(scale)`, лишняя копия серого кадра) не проверял.
- Оценка стоимости плана — порядок величины, не замер.
- Раунд 2: graphify видит только импорты и вызовы. Связь через имена команд и путей дерева (строки IPC) он не показывает; её искал grep. Метки сообществ в графе местами явно ошибочны (например, `sdk_plugin.py` в сообществе `RobotControlWidget`), я их не использовал.

## 5. Что изменил раунд 2 (сводка)

| Раздел | Было (раунд 1) | Стало | Доказательство |
|---|---|---|---|
| Q1 | Services -> Services «не запрещено в прочитанных строках» | подтверждено: deny-список, запрещены 4 пары, нашей нет | `.sentrux/rules.toml:159-177`, `:270-271` |
| Q3 (d) | `introspect_registers` берёт метаданные | только значения; метаданных агент не видит | `builtin_commands.py:780-783`, `:896-897` |
| Q3 | `Optional` в GUI не проверен | снимается до одного типа; `None` в спинбоксе не проверен; «не задано» — флаг группы | `kinds.py:76-81`, `test_factory.py:173` |
| Q4 | потребители `frame_id`/`timestamp` не искал | `frame_saver`, fan-in, `database`; F20, F21 | `frame_saver/plugin.py:213`, `join_inspector_manager.py:132`, `database/plugin.py:121` |
| Q5 | — | граф: 23 внешних нетестовых файла; GUI-вкладка связана по именам команд | `graphify-out/graph.json` (HEAD `078b96ff3`), `presenter.py:80-115` |
| Q6 | контракт своей команды регистрирует `otel_export` | **неверно**: ни один плагин; нужна framework-правка (T6a) | `otel_export/plugin.py:119` (комментарий), `base.py:1676` |
| Q6 | `set_register_verified` как проверка | проверяет register, не прибор | `backend_ctl/registers.py:139-174` |
| Q6 | — | метрики команд уже есть у `CommandManager` | `command_manager.py:262-317` |
| 2 | 19 находок | + F20, F21, F22 | — |
| 3 | 17 задач | + T6a | — |
