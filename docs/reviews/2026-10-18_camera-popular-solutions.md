# Камеры: что уже есть готового и популярного, и как вести план агентами (2026-10-18)

- **Роль:** investigator (Opus), только чтение; файлов продукта и плана не менял, не коммитил.
- **База:** ветка `feat/code-reader-gui`, HEAD `078b96ff3`; план `plans/2026-10-18_camera-device-service/` (39 задач, волны W1–W9 в шапках `tasks/*.md`; `wave-protocol.md` нет — `ls` папки плана: `amendments.md decisions.md design.md matrix.md plan.md tasks`).
- **Веб:** три агента `web-researcher` (Haiku), 2026-10-18. Строка без URL или с пометкой «н/п» (не проверено) — не факт.
- **memory hits:** `python scripts/memory/search.py genicam harvesters camera release heartbeat` -> `project_camera_settings_feature.md`, `project_hikvision_aspect_ratio.md` (выводы не меняют).

## 0. Вердикт

1. **GenICam у нас уже есть — внутри обоих SDK.** Рядом с `MvCodeReaderCtrl.dll` лежат `GenApi_MD_VC120_v3_0_MV.dll` и `MVGigEVision.dll`; в рантайме MVS — те же GenApi и GenTL-продюсеры `MvProducerGEV.cti`, `MvProducerU3V.cti` (A2). Имена узлов (`TriggerMode`, `ExposureTime`) — SFNC.
2. **Готовой библиотеки, которая заменит ядро плана, нет.** Ни harvesters, ни вендорские Python-слои, ни драйверы ROS 2 не дают «поток-владелец + профиль run/rest + проверка записи чтением + честные ошибки в дереве». Это наш слой политики, он остаётся.
3. **Форма ядра — общепринятая.** Драйверы ROS 2 держат ту же таблицу «параметр -> узел GenICam + тип» (A1). Наш `BINDINGS` — это она.
4. **harvesters уже в зависимостях (`pyproject.toml:31`) и в `.venv` (1.4.3, `genicam` 1.5.1), но 0 импортов.** Для ID3013 кадров он не даст: кадр по потоку GigE с этого прибора не приходит (`Services/code_reader/docs/GENICAM.md`, 2026-09-29: 0 кадров за 180 с при вспышках). Для MVS он может заменить наши ctypes-привязки — это надо **доказать** опытом, не брать на критический путь.
5. **Рекомендация:** OpenCV — для веб-камер и RTSP (уже стоит). Диапазоны, перечисления, доступ — из прибора через подключённые вендорские SDK (это и есть GenApi). harvesters — опыт на MVS вне пути; по итогу — драйвер `gentl` для будущих GenICam-вендоров или вынос harvesters в extra. ONVIF, PyAV, GStreamer, Aravis, vidgear — не брать сейчас.
6. **Новая находка с риском для Р6:** GenApi кэширует значения узлов. У регистра `TriggerMode_Reg` в XML камеры MVS тега `Cachable` нет (A2), а по умолчанию GenApi кэширует со сквозной записью (WriteThrough — по моему знанию стандарта, **н/п** по документу). Тогда «прочитать после записи» через SDK может вернуть записанное из кэша, а не из прибора. Мера — опыт H7 (A3) и `MV_CC_InvalidateNodes` перед чтением проверки (функция есть в официальной обёртке MVS, A2).
7. **Процесс (B):** режим волн разумен. Слабые места — накопление ошибок внутри волны из 6–7 задач и большой дифф на ревью волны. Дешёвые меры — в B2.

## A1. Кандидаты

Даты и цифры — со страниц, которые открыл `web-researcher` 2026-10-18.

| Кандидат | Роль | Зрелость (URL, дата) | Лицензия | Windows | Вердикт |
|---|---|---|---|---|---|
| GenICam / GenTL / SFNC (EMVA) | стандарт: XML узлов, транспорт, имена | SFNC 2.8, GenTL 1.6, GenApi 3.5.1 в пакете 2026.07 — https://www.emva.org/standards-technology/genicam/genicam-downloads/ ; SFNC 2.8 — 2026-04-28, https://www.emva.org/press/wrap-up-ivsm-spring-meeting-prague/ | GenICam License v1.0 (PDF не прочитан, н/п) | да | **взять как словарь**: ключ `Binding` = имя SFNC |
| `harvesters` | клиент GenTL: node map + буферы | 1.4.3 от 2024-05-16 — https://pypi.org/project/harvesters/ ; 614 звёзд, 106 issues, push 2026-04-01 — https://api.github.com/repos/genicam/harvesters | Apache-2.0 | да; на 3.12 импортируется у нас (A2) | **опыт, не путь**; релизов нет 2,4 года |
| `genicam` | привязка GenApi | 1.6.0 от 2026-09-01, колёса Windows cp310–cp314 — https://pypi.org/project/genicam/ (у нас 1.5.1) | EMVA (н/п) | да | идёт с harvesters |
| Aravis | GigE Vision/U3V на C, Python через GObject | LGPL-2.1+, ~1,3k звёзд; на Windows — сборка MSYS2 (форум 2025-07) — https://aravis-project.discourse.group/t/how-to-install-on-windows-11/936 ; дата релиза н/п | LGPL-2.1+ | практически нет | **не брать** |
| `pypylon` (Basler) | вендорский слой | 26.8 от 2026-09-07, 714 звёзд — https://pypi.org/project/pypylon/ , https://github.com/basler/pypylon | конфликт: PyPI «Proprietary», GitHub BSD-3 | да | образец; только при камере Basler |
| `vmbpy` (Allied) | вендорский слой | 1.2.3 от 2026-10-06, 55 звёзд — https://pypi.org/pypi/vmbpy/json | BSD-2-Clause | да | то же |
| PySpin (FLIR) | вендорский слой | страница за логином — н/п | н/п | н/п | то же |
| OpenCV `VideoCapture` | веб-камера (MSMF/DSHOW), RTSP/HTTP (FFMPEG) | ~5,4k звёзд — https://github.com/opencv/opencv-python ; `CAP_PROP_OPEN/READ_TIMEOUT_MSEC` — PR от 2021-08-12, только FFMPEG — https://github.com/opencv/opencv/pull/20541 ; в Python с 4.8.0 — https://github.com/opencv/opencv-python/issues/788 | Apache-2.0; FFmpeg в колесе — LGPL-2.1 | да; у нас 5.0.0: MSMF, DSHOW, FFMPEG, без GStreamer (A2) | **взять** (уже стоит) — 5.2 |
| PyAV (`av`) | FFmpeg-декодер для RTSP | BSD-3, ~3,3k звёзд, колёса с FFmpeg — https://github.com/PyAV-Org/PyAV ; последняя версия н/п | BSD-3-Clause | да | **не сейчас**; запасной, если замер покажет задержку/обрывы RTSP |
| GStreamer + PyGObject | конвейер RTSP | офиц. страница Windows — только MSI, о Python нет — https://gstreamer.freedesktop.org/documentation/installing/on-windows.html | LGPL | тяжело | **не брать** |
| `onvif-zeep-async` | ONVIF: GetStreamUri, PTZ, Imaging | 4.3.0 от 2026-09-28, 52 звезды — https://pypi.org/pypi/onvif-zeep-async/json , https://github.com/openvideolibs/python-onvif-zeep-async ; Imaging/GetStreamUri в доках не описаны — н/п | MIT | да | **не сейчас** (ONVIF вне объёма); потом — только он |
| `onvif-zeep` | то же | 0.2.12 от 2018-08-20 — https://pypi.org/pypi/onvif-zeep/json | MIT | да | **не брать** (заброшен) |
| `python-onvif` | то же | PyPI не открылся — н/п | н/п | н/п | не брать |
| `imageio`/`imageio-ffmpeg` | чтение видео | не исследовано — н/п | н/п | н/п | не брать для живого захвата (моё мнение, без источника) |
| `vidgear` (CamGear) | обёртка над OpenCV с потоками | 0.3.5 от 2026-05-17 — https://pypi.org/project/vidgear/ | Apache-2.0 | да | **не брать**: свой поток чтения спорит с потоком-владельцем |
| `pylablib` | научные камеры | 1.4.5 от 2026-05-02 — https://pypi.org/project/pylablib/ | GPLv3 | да | **не брать**: GPL, не наш класс камер |
| `pymmcore` | Micro-Manager | 12.5.1.75.0 от 2026-10-15 — https://pypi.org/project/pymmcore/ | LGPL-2.1 | да | не брать: другой домен |
| ROS 2 `flir_camera_driver` | образец архитектуры | YAML на модель: `name`, `type`, `node` (`AnalogControl/Gain`) — https://github.com/ros-drivers/flir_camera_driver/blob/master/spinnaker_camera_driver/config/blackfly_s.yaml | н/п | — | **образец**: та же таблица, что `BINDINGS` |
| ROS 2 `camera_aravis2` | образец архитектуры | параметры по категориям SFNC; пропущенный узел сохраняет значение прибора; отдельный YAML с Min/Max — https://github.com/FraunhoferIOSB/camera_aravis2 | BSD-3-Clause | — | **образец**: «узлы вне таблицы не трогаем» = Р6 |

Проверку чтением после записи у драйверов ROS 2 исследователь не нашёл (н/п). Это не доказательство, что её нет.
GigE heartbeat: у Basler `GevHeartbeatTimeout` по умолчанию 3000 мс, после него камера отпускает соединение — https://docs.baslerweb.com/network-related-parameters . Для Hikrobot значение по умолчанию — н/п.

## A2. Локальные факты (эта машина, 2026-10-18)

Команды Python — через `scripts/machine_gate.sh light camera-popular-solutions …`; камеры и сеть не трогались (без `Harvester.update()`, без перечисления).

| # | Команда | Вывод (дословно или сокращённо) | Что значит |
|---|---|---|---|
| L1 | `env \| grep -i -E "genicam\|gentl\|mvcam"` | `GENICAM_GENTL64_PATH=C:\Program Files (x86)\Common Files\MVS\Runtime\Win64_x64`; `MVCAM_COMMON_RUNENV=C:\Program Files (x86)\MVS\Development`; `MVCAM_GIGE_DEBUG_HEARTBEAT=60000` | установщик MVS зарегистрировал GenTL-продюсер; heartbeat отладки 60 с (см. A3, риски) |
| L2 | `ls *.cti` в `…\MVS\Runtime\Win64_x64` | `MvProducerGEV.cti`, `MvProducerU3V.cti`, `MvFGProducer{GEV,CML,CXP,XoF}.cti` (2023-11-15) | **GenTL-продюсер MVS есть** |
| L3 | `file MvProducerGEV.cti` | `PE32+ executable … (DLL), x86-64` | 64 бит, как `.venv` (`struct.calcsize('P')*8` -> `64 bit`) |
| L4 | `find "/c/Program Files (x86)/IDMVSSTD" -iname "*.cti"` | пусто | **у IDMVS/MvCodeReader своего продюсера нет** |
| L5 | `ls …\IDMVSSTD\Applications\Win64\plugins\mvsidcamctrl` | `GenApi_MD_VC120_v3_0_MV.dll`, `GCBase_…`, `MVGigEVision.dll`, `MvCodeReaderCtrl.dll`, `NodeMapData_…` | MvCodeReader работает поверх GenApi 3.0 и GigE Vision |
| L6 | `ReleaseNote.txt` MVS | `MVS 4.3.0 build20231128`; документы SDK `V4.1.0.chm` | версия MVS |
| L7 | importlib.metadata в `.venv` | `harvesters 1.4.3`, `genicam 1.5.1`, `opencv-python 4.13.0.92`, `opencv-contrib-python 5.0.0.93`, `numpy 2.4.4` | harvesters уже стоит; **две сборки OpenCV** |
| L8 | `import cv2` | `cv2 5.0.0 …\.venv\Lib\site-packages\cv2\__init__.py`; Video I/O: `FFMPEG: YES`, `GStreamer: NO`, `DirectShow: YES`, `Media Foundation: YES`; `CAP_PROP_OPEN_TIMEOUT_MSEC True`, `CAP_PROP_READ_TIMEOUT_MSEC True` | грузится 5.0.0 из `opencv-contrib-python`, которого нет в `uv.lock` (`grep 'name = "opencv' uv.lock` -> только `opencv-python 4.13.0.92`), хотя `pyproject` требует `<5`. Сообщил лидеру |
| L9 | `git grep -n -i -F harvesters -- '*.py'` | пусто | 0 импортов (так же в `docs/direction/TECH_STACK_2026.md:268`) |
| L10 | `genicam.genapi.NodeMap().load_xml_from_file(MV-CA013-20GC.xml)` (XML виртуальной камеры из `C:\ProgramData\MVS\VirtualCamera`, 22 модели) | `loaded in 0.15s, nodes=2562`; `TriggerMode IEnumeration symbolics ['Off','On']`; `ExposureTime.min` -> `AccessException: Node is not available` | node map строится из XML; значения и доступ — только с портом (живой камерой) |
| L11 | разбор того же XML | `ExposureTime`: `pIsLocked=ExposureLocked_Int`, `pMin/pMax` — регистры прибора; `AcquisitionFrameRate`: `pIsAvailable`, `pIsLocked`; всего `pIsLocked 79`, `pIsAvailable 131`, `pInvalidator 508`; `Cachable`: `NoCache 59`, `WriteAround 4`; `TriggerMode_Reg`: `pInvalidator UserSetLoad, TriggerSelector`, `Cachable` нет | зависимости узлов описаны в XML и считаются GenApi внутри SDK; **кэш по умолчанию у регистров триггера** |
| L12 | `load_xml_from_file(C:\ProgramData\IDMVSSTD\Local\Features.xml)` | `Error while parsing XML stream at line 2 … 'unexpected element encountered'` | `Features.xml` IDMVS — не XML GenICam прибора; описание ID3013 офлайн нет |
| L13 | официальная обёртка MVS `Development\Samples\Python\MvImport\MvCameraControl_class.py` | `grep -c "def MV_CC_"` -> `93` (у нас `bindings.py` -> `16`); есть `MV_CC_GetEnumEntrySymbolic` `:312`, `SetEnumValueByString` `:319`, `RegisterExceptionCallBack` `:411`, `GetOptimalPacketSize` `:519`, `InvalidateNodes` `:375`, `MV_XML_GetGenICamXML` `:702`, `MV_XML_GetNodeAccessMode` `:709`; `MV_CC_Initialize` — нет; `grep -c "\.argtype = "` -> `129`, `"\.argtypes = "` -> `0` | у вендора 93 функции; но опечатка `argtype` (без `s`) — типы аргументов **не заданы** ни у одной; копировать её как есть нельзя |
| L14 | `ls …\MVS\Development\ThirdPartyPlatformAdapter` | `DirectShow` (`MvDSS2`), `HalconHDevelop`, `VisionPro`, `DalsaSherlock` | MVS-камера видна и как DirectShow-устройство (запасной путь через OpenCV, без узлов) |
| L15 | `harvesters/core.py` (стоит в `.venv`) | `start(*, run_as_thread: bool = False)` `:2177`; `fetch(*, timeout…)` `:2520`; поток `_event_new_buffer_thread` только при `run_as_thread` `:2264` | без фонового потока все вызовы идут из потока вызывающего — совместимо с потоком-владельцем |

Опорный факт из репо: ID3013 управляется обычным MVS SDK (`MV_CC_OpenDevice` -> `0x0`, запись `TriggerSource`, `TriggerSoftware` даёт вспышки), но **кадр в поток GigE не приходит** — 0 кадров за 180 с (`Services/code_reader/docs/GENICAM.md`, 2026-09-29; там же: параметры GVSP не перебирались, «до конца не исключено»). Запись триггера при захвате -> `0x80000106`.

## A3. Решение по классам приборов

### (1) GenICam-приборы: MVS, ID3013, будущие GigE/U3V

| Что | Взять | Оставить своим (тонко) | Не брать |
|---|---|---|---|
| Имена узлов | SFNC как ключ `Binding` (`TriggerMode`, `ExposureTime`) | — | свои псевдонимы узлов |
| Диапазоны, шаг, перечисления, доступ | из прибора: `MV_CC_Get{Float,Int,Enum}Value` уже отдают min/max/inc/список, `MV_XML_GetNodeAccessMode` — доступ (L13); у MvCodeReader — те же `Get*Value` (`Services/code_reader/sdk/api.py:106-125`) | `describe_param` — тонкая обёртка над этим (уже в 1.5) | ручные таблицы диапазонов |
| Зависимости узлов (`pIsAvailable`, `pIsLocked`, инвалидаторы) | считает GenApi внутри SDK (L5, L11) | `enabled_if` в register'е — нужен GUI без камеры; во время записи — проверка доступа прибора: не RW -> `skip="недоступен на приборе"` | своё дерево зависимостей вместо прибора |
| Проверка чтением (Р6) | — | своя: ни одна найденная библиотека её не делает; допуск = `inc` прибора + пол `eps_abs` (уже в 2.2) | — |
| Поток-владелец, run/rest, ошибки, дерево | — | своё ядро (Р1, Р6, Р12) | — |
| Транспорт MVS | сейчас — наши ctypes (`bindings.py`, 16 функций) + 0.3; сигнатуры сверять с официальной `MvImport` (L13) | — | копировать `MvImport` в репо: опечатка `argtype` ×129, лицензия кода примеров не проверена |
| Транспорт ID3013 | `MvCodeReaderCtrl.dll` — единственный путь к кадру и кодам | драйвер `mvcr` (3.1) | harvesters для ID3013 (кадров нет, L4 + GENICAM.md) |
| Будущий вендор GenICam | harvesters + `.cti` вендора — **после опыта** | драйвер `gentl` (один файл) | писать ctypes под каждого вендора |

**Удаляет ли node map наши таблицы?** Частично. Удаляет: ручные диапазоны, списки перечислений, «что открыто при каком родителе» во время записи (решает прибор). Не удаляет: `BINDINGS` (поле register'а -> узел) — его держит каждый найденный стек (ROS 2, A1); `enabled_if` для GUI; допуск проверки и политику run/rest.

**Что вендорский SDK делает всегда:** ID3013 — кадр, коды (`extras["codes"]`), режимы `RunningMode`; TCP-настройки и тексты NoRead есть только в IDMVS (`GENICAM.md`: «Коммуникационных настроек … в GenICam нет»). MVS — `MV_CC_GetOptimalPacketSize`, колбэк исключений, преобразование пикселей, `FeatureSave`.

### (2) Веб-камера (UVC)

Взять OpenCV (стоит, L8): `CAP_DSHOW` по умолчанию на Windows (как `Plugins/sources/camera_service/backends/webcam.py:34`), `CAP_MSMF` — полем. `read_back` нет (как в 5.2). Остальное не брать.

### (3) IP-камера (RTSP/ONVIF)

Взять OpenCV FFMPEG + `CAP_PROP_OPEN_TIMEOUT_MSEC`/`READ_TIMEOUT_MSEC` (есть, L8; работают только у FFMPEG — PR 20541) и `OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp"` (формат строки — из сниппетов, н/п). PyAV — только если замер покажет задержку или зависание. ONVIF — вне объёма; позже `onvif-zeep-async` только для `GetStreamUri`/Imaging, кадры всё равно через RTSP.

### Минимальный набор зависимостей

Сейчас — **ни одной новой**. `opencv-python` уже есть (нужно убрать лишний `opencv-contrib-python 5.0.0.93` из `.venv` — решение лидера, L8). `harvesters` уже объявлен: после опыта — либо драйвер `gentl`, либо вынос в extra `gige` (как советует `TECH_STACK_2026.md:270`).

### Честные риски harvesters (если брать)

| Риск | Что известно | Как проверить |
|---|---|---|
| Продюсер MVS с камерой MVS | `.cti` есть, x86-64 (L2, L3); совместимость с harvesters 1.4.3 — н/п (исследователь не нашёл ни отчётов, ни проблем) | опыт S1 |
| Поток | без `run_as_thread` фонового потока нет (L15); потокобезопасность в коде не заявлена — н/п | все вызовы — из потока-владельца, как у SDK |
| Копия кадра | буфер GenTL надо вернуть (`queue`) до следующего; данные — вид на буфер; копия нужна, как сейчас (`RawFrame` — копия, 1.5) | время `fetch` -> копия, p95 |
| Сопровождение | релиз 1.4.3 от 2024-05-16, 106 открытых issues (A1) | держать за портом: замена — один файл драйвера |
| Две DLL GenApi в процессе | `MvCameraControl.dll` и `genicam` несут свои GenApi — конфликт загрузки н/п | не грузить `mvs` и `gentl` в один процесс (Р1: процесс на камеру) |
| Отпускание прибора ~10 с | у GigE это heartbeat; в окружении `MVCAM_GIGE_DEBUG_HEARTBEAT=60000` (L1) — по имени похоже на «heartbeat 60 с в отладке», влияние на `MvCameraControl.dll` и на продюсер — **н/п** | опыт S1, шаг «убить процесс -> через сколько секунд `open` снова `0x0`» |
| Вес установки | harvesters + genicam уже стоят (L7); новых пакетов нет | — |
| Кэш GenApi (L11) | касается и harvesters, и SDK | опыт H7 |

### Опыт S1 (спецификация, 8 строк)

```
Goal: доказать или опровергнуть, что harvesters + MvProducerGEV.cti на этой машине дают для MVS-камеры то же, что наши ctypes: open по serial, чтение/запись 4 узлов с min/max/inc/entries/access, 100 кадров, close; и измерить H7 (кэш) и время повторного open после kill.
Files: Services/hikvision_camera/tools/gentl_probe.py (новый), Services/hikvision_camera/tests/test_gentl_probe.py (новый, на фейковом ImageAcquirer); tasks/0.6.result.md.
Acceptance 1: вывод зонда — таблица `node type value min max inc access` для TriggerMode, TriggerSource, ExposureTime, Gain; те же числа, что даёт 0.4 по ctypes (расхождение = строка в отчёте).
Acceptance 2: 100 кадров `fetch(timeout=1.0)`: fps, p95 `fetch+copy` мс, 0 исключений; все вызовы из одного потока (id потока в логе).
Acceptance 3 (H7): записать ExposureTime = значение не кратное inc (прибор округлит); прочитать без инвалидации и после invalidate_node()/MV_CC_InvalidateNodes — оба числа в отчёт; разные числа = чтение идёт из кэша.
Acceptance 4: kill -9 процесса с открытой камерой -> через сколько секунд новый процесс получает open (ctypes и harvesters), при текущем MVCAM_GIGE_DEBUG_HEARTBEAT и без него.
Gate: light для теста; камера — окно стенда вместе с 0.5 (тот же день, ~1 ч стенда). Без камеры: только тест на фейке и загрузка .cti без update().
Verdict rule: все 4 строки выполнены и числа ≤ ctypes по fps/p95 -> драйвер `gentl` (P2, Ф5); иначе harvesters -> extra `gige`, строка в OPEN_QUESTIONS.
```

H7 без harvesters (дешевле, войдёт в 0.4/0.5): после записи узла сравнить `Get*Value` до и после `MV_CC_InvalidateNodes`; если чтение без инвалидации отличается от чтения с ней хотя бы раз — Р6 обязан инвалидировать перед проверкой.

### Влияние на задачи плана (`plans/2026-10-18_camera-device-service/tasks/`)

| Задача | Изменение | Почему |
|---|---|---|
| 0.3 | **изменить**: в опись добавить `MV_CC_InvalidateNodes`, `MV_XML_GetNodeAccessMode`, `MV_XML_GetGenICamXML`, `MV_CC_GetOptimalPacketSize`; сигнатуры брать из `MvImport` (L13), `argtypes` задавать самим | эти функции нужны 4.1 и H7; образец у вендора есть |
| 0.4 | **изменить**: `--dump` дополнительно сохраняет XML прибора (`MV_XML_GetGenICamXML`) рядом с JSON; `--experiment h7` (кэш, см. выше) | XML прибора = полное дерево с зависимостями офлайн (L10 показал, что структура читается за 0,15 с) |
| 0.5 | **изменить**: прогнать h7 и замер «kill -> повторный open, с»; записать значение `MVCAM_GIGE_DEBUG_HEARTBEAT` в отчёт | риск Р6 и ~10 с отпускания |
| 0.6 | **добавить** (P2, вне пути, W4 рядом с 0.5): опыт S1 | доказать harvesters до любого решения |
| 1.5 | без изменения кода; в README порта: «`Binding.key` для GenICam — имя SFNC; `describe_param` берёт min/max/inc/entries/access из прибора, ручных диапазонов нет» | фиксирует решение |
| 2.2 | **изменить** после h7: если кэш подтвердится — перед `get_param` проверки драйвер инвалидирует узел (capability или правило драйвера); строка ACCEPTANCE на фейке «чтение после записи идёт мимо кэша» | иначе проверка чтением подтверждает сама себя |
| 2.2 / 1.6 | **малое**: шаг с доступом прибора не RW -> `skip="недоступен на приборе"`, не ошибка | зависимости считает GenApi |
| 3.1 | без изменения | MvCodeReader — единственный путь к кадру ID3013 |
| 4.1 | без изменения на пути; ветка «драйвер на harvesters» — только по итогу 0.6 | не рисковать М2 |
| 5.2 | **изменить**: до задачи — привести `.venv` к `uv.lock` (один `cv2`), `OPENCV_FFMPEG_CAPTURE_OPTIONS` для RTSP в README драйвера | L8 |
| 5.5 | **добавить условно** (P2, после 0.6 = да): драйвер `gentl` + строка в реестре Р11 | будущие вендоры без своих ctypes |
| `pyproject.toml` | после 0.6: harvesters — в extra `gige` или остаётся с потребителем | сейчас 0 импортов |
| удалить | ничего | готовая библиотека ядро не заменяет |

### Время до первого результата

Критический путь к М2 (0.1 -> 1.5 -> 1.8 -> 2.1 -> 2.2 -> 2.3 -> 2.4 -> 4.2 -> 4.3/4.4 -> 6.3, ревью плана P6) **не меняется**: 0.6 и 5.5 — вне пути. Добавка на пути — только h7 в 0.4/0.5 (одна функция зонда, ~1 запуск) и, если кэш подтвердится, одна строка в 2.2. Перевод MVS на harvesters сейчас добавил бы на путь переписку 0.3/0.4/4.1 и неизвестные особенности продюсера — не советую.

## B1. Как сейчас принято вести работу агентами

Метка: **E** — исследование, замер или официальный документ; **A** — блог, мнение.

| # | Утверждение | Метка | Источник, дата |
|---|---|---|---|
| 1 | Оркестратор-исполнители и «оценщик-оптимизатор» — базовые шаблоны; агенты меняют цену и задержку на качество, риск — накопление ошибок | E (офиц.) | https://www.anthropic.com/engineering/building-effective-agents , 2024-12-19 |
| 2 | Мульти-агент тратит ~15× токенов чата (агент ~4×); хорош при сильном распараллеливании, плох, когда всем нужен один контекст | E (замер вендора) | https://www.anthropic.com/engineering/multi-agent-research-system , 2025-06-13 |
| 3 | Дать агенту способ проверить работу; шаблон «писатель/ревьюер» в разных сессиях; «один пишет тесты, другой — код под них»; ревьюер склонен перечислять лишние замечания | E (офиц.) | https://code.claude.com/docs/en/best-practices (без даты) |
| 4 | Маршрутизация по моделям: дешёвая на объёмную работу, сильная на сложную | E (офиц.) | https://platform.claude.com/docs/en/about-claude/models/choosing-a-model ; FrugalGPT: до 98 % экономии при качестве GPT-4 — https://arxiv.org/abs/2305.05176 , 2023-05-09 (перенос на код — н/п) |
| 5 | Ревью эффективно до 200–400 строк и 60–90 мин; дальше находок меньше | E (сводка SmartBear по исследованию Cisco; первоисточник не открыт, дата н/п) | https://smartbear.com/learn/code-review/best-practices-for-peer-code-review/ |
| 6 | Малые партии, слияние в trunk ежедневно, CI быстрее на малых изменениях | E (опрос DORA, корреляция) | https://dora.dev/capabilities/trunk-based-development/ , https://dora.dev/capabilities/continuous-integration/ |
| 7 | Стопка малых диффов ревьюится быстрее | A | https://graphite.com/guides/stacked-diffs |
| 8 | LLM-судья: позиционная несогласованность (GPT-4 65 %), предпочтение своих ответов (+10…25 % побед) | E | https://arxiv.org/abs/2306.05685 , 2023-06-09; https://arxiv.org/abs/2404.13076 , 2024-04-15 |
| 9 | Мульти-агентные системы падают в 41–86,7 % трасс; 14 видов отказов; проверка: преждевременное завершение 6,2 %, нет/неполная проверка 8,2 %, неверная проверка 9,1 % | E | https://arxiv.org/abs/2503.13657 , 2025-03-17 (v3 2025-10-26) |
| 10 | LLM-ревьюер в проде: 38,7 % замечаний привели к правке, цикл PR −30,8 % | E (автор — вендор) | https://arxiv.org/abs/2601.01129 , 2026-01-03 |
| 11 | Исполнение тестов агентом — часть интерфейса, повышает решаемость | E | SWE-agent, https://arxiv.org/abs/2405.15793 , 2024-05-06 |
| 12 | Тесты в промпте повышают успех генерации кода | E (эффект н/п) | https://arxiv.org/abs/2402.13521 , 2024-02-21 |

Не подтверждено: медиана размера изменения в Google (страница не дала числа), отдельные исследования «слепого тестировщика до кода», формула накопления ошибок `r^n` с первоисточником, ложные срабатывания LLM-ревью на больших диффах.

**Что из этого следует (мой вывод, не цитата):** (а) независимая проверка исполнением сильнее, чем независимое чтение — п. 9, 11; (б) ревью больших диффов теряет находки — п. 5, у LLM тоже есть основания ждать этого, но прямого замера нет; (в) судья одной модели с автором предпочитает «своё» — п. 8, поэтому ревьюер другого уровня (Opus над Sonnet) разумен; (г) мульти-агент дорог — п. 2, оправдан только где задачи независимы.

## B2. Наш режим (решение владельца 2026-10-18): оценка

Факт по шапкам задач (`grep -H "Wave:" tasks/*.md`): W1 — 6 задач, W2 — 4, W3 — 6, W4 — 7, W5 — 3, W6 — 5, W7 — 6, W8 — 2, W9 — 3. Стадия 0 (Sonnet) — 9 задач (1.1, 1.3, 1.5, 2.1, 2.2, 2.3a, 2.4, 4.2a, 4.6a); тестер до кода — 8 (те же без 4.6a); Opus сразу — 4 (2.1, 2.2, 2.4, 4.2a).

### Где режим прочный

- **Совпадает с практикой:** оркестратор + исполнители (B1 п.1), тесты отдельным агентом до кода (п.3, 12), ревьюер выше уровнем автора (снимает часть «своё лучше», п.8), дешёвая модель на механике (п.4).
- **Проверка исполнением:** break-injection с прогнозом до прогона и стенд числами — сильнее чтения (п.9, 11).
- **Opus сразу на 4 задачах потоков** — там, где ошибка дороже всего и дальше по волне на ней строят.
- **Лестница эскалации** после 2 итераций обрывает бесконечные циклы.

### Где режим слабый (механизм -> цена)

1. **Накопление ошибок внутри волны.** В W3 цепочка `2.3a -> 2.3b -> 2.4` и `3.2` на её базе; ревью — в конце волны. Дефект 2.3a, который тесты автора не ловят, доезжает до трёх задач. Цена — переделка трёх задач, а не одной.
2. **Большой дифф на ревью волны.** W4 = 4.2a, 4.2b, 4.3, 4.4, 6.1, 6.3, 0.5; К4 сам ~18 файлов (`design.md`, риск 3). Это выше 200–400 строк, где ревью ещё находит дефекты (п.5). Прямого замера для LLM нет — это перенос, не факт.
3. **Тестер и исполнитель — одна модель (Sonnet).** Тесты отдельные, но слепые зоны модели общие (моё предположение, первоисточника нет). Смягчает break-injection.
4. **Прогнозы Haiku.** Haiku только исполняет матрицу; риск — неверно прочесть вывод (п.9: «неверная проверка» 9,1 % трасс). Без вставки вывода отчёт — совет, не факт.
5. **Контекст лидера.** Один Opus на 39 задач растёт по контексту; цена — решения по устаревшему состоянию.
6. **Стоимость.** ~13M токенов оценкой (`plan.md:62-64`); мульти-агент дорог (п.2). Замера на этом плане нет.

### Дешёвые улучшения (без ревью Opus на каждой задаче)

1. **Потолок волны:** ≤ ~400 строк изменённого кода продукта (тесты отдельно) или ≤ 4 задач; W3 и W4 — разрезать по цепочкам (W3a: 2.3a, 2.3b, 2.4; W3b: 3.1, 4.1, 3.2; W4a: 4.2a, 4.2b; W4b: 4.3, 4.4 + К4).
2. **Зелёный гейт между задачами внутри волны:** исполнитель сам гонит радиус тестов + `ruff check -q` + `sentrux check .` (если импорты) через `machine_gate.sh light`, вывод — в отчёт; следующая зависимая задача стартует только от зелёного SHA.
3. **Фокус ревью от лидера:** к ревью волны — 3–7 строк «что проверить исполнением» (механизм, файл:строка, ожидаемый вывод). Ревьюер воспроизводит каждую строку запуском; дифф читает по коммитам, а не одним куском.
4. **Break-injection только для перечисленных механизмов** (9 задач с тестером) и для К4; у остальных — радиус тестов.
5. **Haiku-отчёт с выводом команды**; лидер выборочно перезапускает 1 из 5 строк матрицы.
6. **Контекст лидера:** handoff в конце каждой волны (`/core:team:handoff`), новая сессия лидера на следующую волну.
7. **Метрики пилота на W1–W2** (в `amendments.md`): дефектов найдено ревью волны / задачу; дефектов, ушедших в следующую волну; итераций до APPROVED; токенов на задачу; строк диффа на ревью; доля инъекций, которые тест поймал. Решение после W2: если ушедших дефектов > 0 у зависимых цепочек — Opus сразу на голове цепочки (1 задача), а не везде.

## Что я оставил открытым / ненадёжным

- **Кэш GenApi (H7) — гипотеза.** Тега `Cachable` у `TriggerMode_Reg` нет (L11); что по умолчанию это WriteThrough и что SDK читает из кэша — по моему знанию стандарта, документ EMVA не открыт. Проверка — h7 на камере.
- **XML ID3013 офлайн нет** (L12): разбирал XML виртуальной камеры MVS `MV-CA013-20GC`, не ID3013. Перенос выводов о зависимостях на ID3013 — н/п.
- **harvesters с `MvProducerGEV.cti` не запускал** (запрет на сеть и камеру): совместимость, скорость, поведение отпускания — н/п, это опыт S1.
- **`MVCAM_GIGE_DEBUG_HEARTBEAT=60000`** — смысл выведен из имени; читает ли его `MvCameraControl.dll`/`MvCodeReaderCtrl.dll` и связан ли он с «~10 с отпускания» — н/п.
- **Две сборки OpenCV в `.venv`** (L8) — причину установки `opencv-contrib-python` не искал; сообщил лидеру, ничего не менял.
- **Лицензия GenICam (PDF), лицензия кода примеров MVS `MvImport`** — не прочитаны; поэтому совет «сверять сигнатуры, не копировать».
- **PySpin, `python-onvif`, `imageio`, ROS 2 `usb_cam`/`pylon_ros2_camera`** — исследователь не дошёл или страница не открылась.
- **ONVIF Imaging/GetStreamUri у `onvif-zeep-async`** — в документации не описаны, н/п.
- **Ревью-размер для LLM:** порог 200–400 строк — из исследования людей (Cisco через SmartBear); перенос на LLM-ревьюера — моё предположение.
- **Оценки времени и токенов** в B2 — оценки, не замеры.
- Веб-факты собрал Haiku; вторую проверку ключевых дат (PyPI + GitHub) он сделал для harvesters, vmbpy, onvif-zeep-async; для остальных — один источник.
