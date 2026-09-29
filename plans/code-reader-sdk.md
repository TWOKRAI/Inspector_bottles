# План: MvCodeReader SDK в `Services/code_reader` — кадр + коды + качество

**Родитель:** [`qr-code-reader.md`](qr-code-reader.md), трек B (Ф6 — новая фаза, вынесена в
отдельный файл: родительский план 88 КБ). Ветка `feat/qr-code-reader`.
**Решение владельца 2026-09-29:** SDK — слоями внутри `Services/code_reader/` (вариант «а»), не
отдельный сервис. TCP-приём (`core/sink.py`) остаётся запасным каналом.

## Контекст — что снято с прибора (2026-09-29, зонд на заголовках SDK V1.5.3)

- SDK лежит в `C:\Program Files (x86)\IDMVSSTD\Development\Development.zip` →
  `Modules/MvCodeReaderSDK/`: `Include/*.h`, `Doc/*Developer Guide_V1.5.3*.PDF`, `SDK/win64/*.dll`
  (34 файла зависимостей рядом с `MvCodeReaderCtrl.dll`). Та же DLL с зависимостями стоит в
  `C:\Program Files (x86)\IDMVSSTD\Applications\Win64\plugins\mvsidcamctrl\`.
- Последовательность: `EnumDevices(list*, GIGE=1)` → `CreateHandle(void**, DEVICE_INFO*)` →
  `OpenDevice(h)` → `StartGrabbing(h)` → цикл `GetOneFrameTimeoutEx2(h, uchar**, IMAGE_OUT_INFO_EX2*, ms)`
  → `StopGrabbing` → `CloseDevice` → `DestroyHandle`. Всё `__stdcall` (`ctypes.WinDLL`).
- Живой прогон, 5 нажатий кнопки — **все поля осмысленны, раскладка структур подтверждена**:

  | # | `chCode` / `nLen` | `nBarType` | прочее |
  |---|---|---|---|
  | 1–3 | `QR-15MM`/7, `QR-20MM`/7 ×2 — длина совпала | 2 | 4 угла ровно на коде (проверено глазом на PNG), угол ×10, PPM ×10, `sAlgoCost` 25 мс |
  | 4 | `""` / 0, **`nNoReadNum = 1`** | **1001** | код прикрыт бумагой: 4 угла на месте кода — «код есть, не читается» |
  | 5 | список пуст, `bIsGetCode = false` | — | «кода нет» |

  Кадр — **JPEG** (`enPixelType = 0x80180001`), 1280×1024, 21–33 КБ. `bIsGetQuality = false`, все
  оценки 0 — в приборе выключен `2D Code Quality Enable`. **Нули при `bIsGetQuality = false` — не
  оценка F, а «оценки нет».** Шкала `nOverQuality` (какое число = какая буква) **не снята**.
- Доступ **эксклюзивный**: пока прибор открыт SDK, IDMVS его не получит, и наоборот
  (`MV_CODEREADER_E_ACCESS_DENIED = 0x80020203`). `MV_CODEREADER_E_NODATA = 0x80020006` — нормальный
  «кадра за таймаут не было».
- Черновик-зонд, с которого снята таблица: `mvcr_probe.py` (scratchpad сессии; переедет в `tools/`).
- Ловушка стенда: включённый VPN (WireGuard) прячет прибор от `EnumDevices` — 0 устройств при живом линке.

## Решения

1. **SDK в репозиторий не кладём** (32 МБ вендорских бинарников). Каталог ищется: аргумент →
   env `MVCR_SDK_DIR` → каталог плагина установленного IDMVS (путь выше). DLL грузится **лениво**
   (при первом вызове), не при импорте — иначе тесты и машины без IDMVS падают на импорте.
   `hikvision_camera` грузит при импорте; здесь сознательно иначе.
2. **Один класс сессии, без Protocol-обёрток над SDK.** Для тестов сессия принимает `api=` —
   объект с методами тонкой обёртки; по умолчанию настоящая. Фейк живёт в тестах.
3. **Статус кадра выводится из списка кодов**, не из `bIsGetCode` в одиночку: любой код с
   `nLen > 0` → `ok`; иначе есть хоть одна запись → `bad_code`; иначе → `no_code`.
4. **Качество — `None`, когда прибор его не посчитал** (`bIsGetQuality = false`). Сырые числа
   оценок отдаются как есть; перевод в буквы — после снятия шкалы на приборе (вне объёма).
5. **Картинка не декодируется в SDK-слое.** Кадр несёт байты и формат; декод в numpy — отдельной
   функцией, которую зовёт потребитель (плагин). Сессия не платит за декод, если кадр не нужен.
6. **Автопереподключения в первом цикле нет** (named ceiling): после устойчивой ошибки сессия
   переходит в `error` и ждёт `stop()`/`start()`. Триггер вернуться — первый обрыв на стенде.

## Уточнения контракта после RED-прогона (2026-09-29, решения лидера)

Два независимых тестировщика угадали разное там, где контракт молчал. Решено:

1. **`RawFrame` — плоский frozen dataclass, по ключевым словам:** `image: bytes`, `width`, `height`,
   `pixel_type`, `trigger_index`, `frame_num`, `no_read_num` (все `int`; `no_read_num` — из
   `RESULT_BCR_EX2.nNoReadNum`), `codes: tuple[BCR_INFO_EX2, ...]` — **копии** записей, не ссылки в
   буфер SDK. Нулевой указатель списка кодов → `codes = ()`.
2. **`DeviceEntry`:** `ip`, `model`, `serial` (`str`) + `info` — копия `DEVICE_INFO`, из которой
   `open()` делает `CreateHandle`.
3. **`open()` при ошибке `OpenDevice` сам зовёт `DestroyHandle`** и поднимает `SdkError`: у
   вызывающего handle ещё нет. «busy → close для созданного handle» относится к отказу на
   `start_grabbing` (handle уже есть).
4. **`sdk.loader.IDMVS_PLUGIN_DIR: Path`** — модульная константа пути по умолчанию.
5. **Ключи `CodeQuality.grades` → поля `CODE_INFO`:** `decode`→`nDeCode`, `contrast`→`nSCGrade`,
   `modulation`→`nModGrade`, `fixed_pattern_damage`→`nFPDGrade`, `axial_nonuniformity`→`nANGrade`,
   `grid_nonuniformity`→`nGNGrade`, `unused_error_correction`→`nUECGrade`; `overall`→`nOverQuality`;
   `score`→`nIDRScore` **записи кода** (не `CODE_INFO`). Флаг `bIsGetQuality` — на запись кода.
6. **`E_NODATA` — успешный вызов:** сбрасывает счётчик «ошибок подряд». Ошибки `get_frame` идут и в
   `errors`. `start()` из `error` разрешён (после внутреннего закрытия прибора).
7. Раскладка структур сверена дважды независимо: тестировщик посчитал смещения по заголовку вручную
   (`bIsGetQuality` @4360, `nReserved` @4400, `BCR_INFO_EX2` = 4628, `RESULT_BCR_EX2` = 1 388 436,
   `IMAGE_OUT_INFO_EX2` = 200), зонд лидера прочитал живой прибор с `len_ok` на каждом коде.

## Ф6 — задачи

### Task 6.1 — Слой `sdk/`: загрузка, структуры, тонкая обёртка
**Level:** Senior (ctypes, раскладка структур) · **Assignee:** `teamlead` · **Layer:** services
**Goal:** Python-доступ к `MvCodeReaderCtrl.dll` без правок и без копий вендорских файлов.
**Files:** `Services/code_reader/sdk/__init__.py`, `sdk/loader.py`, `sdk/structures.py`,
`sdk/errors.py`, `sdk/api.py`; `Services/code_reader/tools/mvcr_probe.py` (перенос зонда на `sdk/`).
**Contract:**
- `sdk.loader.find_sdk_dir(explicit: str | Path | None = None) -> Path | None` — первый
  существующий каталог, где лежит `MvCodeReaderCtrl.dll`, в порядке: `explicit` → env
  `MVCR_SDK_DIR` → каталог плагина IDMVS. Никаких побочных эффектов (DLL не грузит).
- `sdk.loader.load_library(explicit=None)` → `ctypes.WinDLL`; каталог добавляется через
  `os.add_dll_directory`. Не нашлось → `sdk.errors.SdkNotFoundError`, в тексте перечислены **все**
  проверенные пути. Не Windows → тот же `SdkNotFoundError` с причиной.
- `sdk.errors`: `MV_OK = 0`, `E_NODATA = 0x80020006`, `E_ACCESS_DENIED = 0x80020203`;
  `SdkError(code: int, where: str)` — `code` беззнаковый 32-бит, `str()` содержит имя вызова и
  код в hex `0x8002...`.
- `sdk.structures`: `DEVICE_INFO`, `DEVICE_INFO_LIST`, `POINT_I`, `CODE_INFO`, `BCR_INFO_EX2`,
  `RESULT_BCR_EX2`, `IMAGE_OUT_INFO_EX2` — поля и порядок **строго по** `MvCodeReaderParams.h`
  (V1.5.3). Константы `GIGE_DEVICE = 1`, `PIXEL_MONO8 = 0x01080001`, `PIXEL_JPEG = 0x80180001`,
  `BAR_TYPE_NOREAD = 1001` (наблюдённое значение, помечено как снятое с прибора).
- `sdk.api.MvCodeReaderApi(lib=None)` — тонкая обёртка, lib грузится лениво:
  `enum_devices() -> list[DeviceEntry]` (`ip: str`, `model: str`, `serial: str`, `info` — указатель
  для `open`); `open(entry) -> handle`; `start_grabbing(h)`; `get_frame(h, timeout_ms) ->
  RawFrame | None` (`None` ровно на `E_NODATA`, иначе ненулевой код → `SdkError`);
  `stop_grabbing(h)`; `close(h)` (`CloseDevice` + `DestroyHandle`, оба зовутся, даже если первый
  вернул ошибку). `RawFrame` — копия данных кадра (байты изображения + разобранный список кодов),
  **не** ссылки в буфер SDK: буфер живёт до следующего `GetOneFrame`.
**Acceptance criteria:**
- [x] `find_sdk_dir` уважает порядок источников; несуществующий `explicit` пропускается; каталог
      без `MvCodeReaderCtrl.dll` не считается найденным.
- [x] `load_library` без SDK → `SdkNotFoundError`, в сообщении каждый проверенный путь.
- [x] `import Services.code_reader.sdk` на машине без IDMVS не грузит DLL и не падает.
- [x] Структуры: `chCode` — 4096 байт, массив `stBcrInfoEx2` — 300 записей, `pt` — 4 точки;
      смещения `nCodeNum`, `chCode`, `nLen`, `pt`, `stCodeQuality`, `nNoReadNum` в структурах
      совпадают с раскладкой C по заголовку (тест считает ожидаемое смещение по правилам
      выравнивания MSVC x64 **вручную, литералом**, а не через тот же ctypes).
- [x] `get_frame` на `E_NODATA` → `None`; на `0x80020203` → `SdkError` с этим кодом.
- [x] `RawFrame` остаётся корректным после того, как исходный буфер перезаписан (копия, а не вид).
- [ ] `tools/mvcr_probe.py --selfcheck` без прибора отрабатывает (разбор синтетического кадра),
      с прибором — печатает `len_ok` по каждому коду. **Частично:** selfcheck OK; на приборе
      гонялся черновик-предшественник и настоящий `SdkCodeReader`, сам `tools/mvcr_probe.py` — нет.
**Out of scope:** настройка параметров прибора (`SetEnumValue` и т.п.), OCR, waybill, MSC-каналы.

### Task 6.2 — Модель кадра и сессия прибора (`core/`)
**Level:** Senior (поток захвата, остановка, эксклюзивный доступ) · **Assignee:** `teamlead` · **Layer:** services
**Goal:** один объект, который держит прибор, крутит захват в потоке и отдаёт кадр с кодами наружу.
**Files:** `Services/code_reader/core/sdk_frame.py`, `core/sdk_reader.py`, `interfaces.py` (экспорт).
**Contract — `core.sdk_frame`:**
- `CodeQuality` (frozen): `overall: int`, `grades: dict[str, int]` (ключи `decode`, `contrast`,
  `modulation`, `fixed_pattern_damage`, `axial_nonuniformity`, `grid_nonuniformity`,
  `unused_error_correction`), `score: int` (`nIDRScore`).
- `CodeRead` (frozen): `text: str`, `status: ReadStatus` (`OK` при `nLen > 0`, иначе `BAD_CODE`),
  `bar_type: int`, `corners: tuple[tuple[int, int], ...]` (ровно 4), `angle_deg: float`
  (`nAngle / 10`), `ppm: float` (`sPPM / 10`), `algo_ms: int`, `quality: CodeQuality | None`
  (`None`, если `bIsGetQuality` ложно — **даже когда числа нулевые**).
- `SdkFrame` (frozen): `trigger_index: int`, `frame_num: int`, `width: int`, `height: int`,
  `pixel_format: str` (`"jpeg"` | `"mono8"` | `"unknown:0x…"`), `image: bytes`,
  `codes: tuple[CodeRead, ...]`, `no_read_num: int`, `status: ReadStatus` (решение 3).
  `to_dict()` — Dict at Boundary: **без** `image`, с `image_len`; `status`/`codes[].status` — строки.
- `decode_image(frame: SdkFrame) -> numpy.ndarray` — серое `uint8` `height×width`;
  JPEG → `cv2.imdecode`; mono8 → reshape; иначе `ValueError` с форматом в тексте.
- `frame_from_raw(raw: RawFrame) -> SdkFrame` — чистая функция, без DLL.
**Contract — `core.sdk_reader.SdkCodeReader`:**
- `SdkCodeReader(on_frame: Callable[[SdkFrame], None], on_error: Callable[[str], None] | None = None,
  *, device_ip: str | None = None, timeout_ms: int = 500, api=None)`.
- `start() -> bool`: найти прибор (по `device_ip`, иначе первый), открыть, запустить захват и поток.
  Прибор не найден → `False`, `state == "not_found"`. Занят (`E_ACCESS_DENIED`) → `False`,
  `state == "busy"`, в `on_error` текст с подсказкой про IDMVS. Успех → `True`, `state == "running"`.
  Повторный `start()` при `running` — `True` без второго открытия.
- `stop(timeout: float = 2.0) -> None`: остановить поток, `StopGrabbing`, закрыть прибор;
  идемпотентен; укладывается в `timeout` (+ один `timeout_ms` захвата); после него прибор свободен
  (`close` вызван ровно один раз на одно открытие). `state == "stopped"`.
- Исключение из `on_frame` не убивает поток захвата: считается в `errors`, текст уходит в
  `on_error`, следующий кадр доставляется.
- Ненулевая ошибка `get_frame` (не `E_NODATA`) три раза подряд → `state == "error"`, поток
  завершается, `on_error` получает код; прибор **закрыт** (не остаётся захваченным).
- `stats() -> dict`: `frames`, `ok`, `no_code`, `bad_code`, `errors`, `state`, `last_error`,
  `device` (`ip`, `model`, `serial` или `None`). Счётчики — по `SdkFrame.status`.
**Acceptance criteria:**
- [x] `frame_from_raw` на синтетике по таблице контекста: коды 1–3 → `ok` + текст; запись с
      `nLen = 0`, `bar_type = 1001` → `bad_code`, 4 угла сохранены; пустой список → `no_code`.
- [x] Кадр с одним читаемым и одним нечитаемым кодом → `status == ok`, в `codes` оба.
- [x] `bIsGetQuality = false` при ненулевых числах и при нулевых → `quality is None`;
      `true` → `CodeQuality` с числами из структуры.
- [x] `to_dict()` проходит `json.dumps`, не содержит байтов изображения, содержит `image_len`.
- [x] `decode_image`: JPEG-байты (сгенерированные `cv2.imencode` в тесте) → массив нужной формы;
      mono8 → reshape; неизвестный формат → `ValueError`.
- [x] С фейковым `api`: `start()` → кадры доходят до `on_frame` в порядке выдачи; `stop()` зовёт
      `stop_grabbing` и `close` ровно по разу; второй `stop()` ничего не зовёт.
- [x] `stop()` возвращает управление за ≤ `timeout + timeout_ms` при фейке, который **блокирует**
      `get_frame` на весь `timeout_ms` (тест с дедлайном в отдельном потоке — `pytest-timeout` в
      этом venv не активен).
- [x] Access denied → `busy`, `close` вызван для созданного handle, `on_error` упоминает IDMVS.
- [x] Три ошибки `get_frame` подряд → `error`, прибор закрыт; одна ошибка между удачными — нет.
- [x] Исключение в `on_frame` на кадре N → кадр N+1 доставлен, `errors == 1`.
**Out of scope:** плагин и рецепт (Task 6.3), автопереподключение (решение 6), запись параметров.

### Task 6.3 — Плагин `code_reader_sdk` + рецепт (следующий цикл, спецификация после 6.1–6.2)
Порт `code` (dict, как у TCP-плагина + `corners`, `quality`, `trigger_index`) и порт `frame`
(SHM, образец `hikvision_camera/plugin/config.py`); команды `take_device` / `release_device`;
рецепт `qr_reader_sdk_demo`. Живой стенд: 20 срабатываний, задержка «триггер → кадр в прототипе»,
идут ли коды по TCP, пока прибор открыт SDK.

## Итог 6.1–6.2 (2026-09-29)

267 тестов в `Services/code_reader/tests` (195 слепых + 2 hazard teamlead + 8 hazard итерации 2 и правок ревью);
инъекции лидера 27/27 (6.1: 10, 6.2: 12 — одна дыра K5 закрыта тестом, итерация 2: 4 + 1);
ревью 6.1 APPROVE, 6.2 APPROVE (2 итерации). Живой стенд: см. `Services/code_reader/STATUS.md`, раздел Ф6.
Отступление от DESIGN 6.2, принятое лидером: прибор отпускает только поток захвата (в `finally`), `stop()`
не закрывает под идущим `get_frame`. Вход в 6.3: ADVISORY ревью — `stats()` не отличает «поздний stop,
прибор ещё занят» от «закрыт»; `start()` из `on_error` на финальном сбое всегда False — перезапуск снаружи.

## Порядок работы (конвенция проекта)

1. `tester` — один прогон на оба механизма (6.1 + 6.2), **до** кода, в worktree на коммите этого
   плана; только критерии выше; тесты ожидаются красными.
2. `teamlead` — реализация 6.1 → 6.2 по красным тестам; не коммитит.
3. Лидер — инъекции поломок по каждому заявленному свойству, против обоих наборов тестов.
4. Лидер — живой стенд: `tools/mvcr_probe.py` на приборе, `len_ok` по каждому коду.
5. `reviewer` — синхронно, с воспроизведением.
