# Библиотеки на Rust / Go / C++ для ускорения или замены частей фреймворка (состояние на 2026-11-22)

Исполнитель: web-researcher (Haiku). Вызовов инструментов: 38 из 40. Каждое фактическое утверждение
снабжено номером источника [S#] с датой со страницы; список открытых страниц — в разделе «Источники».
Дата «без года» означает, что год на странице не виден; такие даты помечены явно.

Шкала: **mature** (стабильный релиз, используется в проде, Windows подтверждён), **usable** (рабочий,
но есть ограничения или pre-1.0), **experimental** (ранняя стадия, API/Windows не подтверждены),
**hype** (заявлено много, подтверждения нет). «не нашёл» / «не проверено» — честная метка, не факт.

## 0. Короткий вывод

- Для shared-memory кадров самый близкий кандидат — **iceoryx2** (Rust core, Python-биндинги,
  Windows tier 2): **usable**, но pre-1.0 и с ограниченным набором safety-функций на Windows [S1][S2].
- Для брокера сообщений и pub/sub — **Zenoh** (Python-пакет на PyPI, Windows wheel) [S3] и
  **NATS** (сервер зрелый; Windows-бинарники не видны в ассетах) [S11][S12]; оба — **usable**.
- **eCAL** (C++ core, shared-memory транспорт, Windows «stable») с Python-биндингом через nanobind
  — самый «готовый» вариант C++ под Windows [S13][S14].
- Полную замену фреймворка (dora-rs, Rust actor-фреймворки) я не рекомендую как «ускорение»:
  это другая архитектура, а не библиотека. Оценка — **usable/experimental**, не замена.
- Supervision на Windows: зрелого «современного» Python-нативного варианта я **не нашёл**;
  единственный свежий вендорский кандидат — Servy, и его описание не подтверждено независимо [S24].

## 1. Rust-библиотеки с Python-биндингами

| Библиотека | Задача | Windows-wheel / платформа | Версия, дата | Оценка | Источник |
|---|---|---|---|---|---|
| iceoryx2 | zero-copy shared memory, pub/sub | win_amd64 cp38-abi3 и cp314t; Windows «tier 2», «с ограниченным набором безопасности» | 0.10.1, 20 нояб 2026 (PyPI) | **usable** (pre-1.0; v1.0 запланирован) | [S1], [S2] (блог 18/05/2026) |
| eclipse-zenoh | pub/sub, маршрутизация | win_amd64 cp39-abi3; классификатор «4 - Beta»; EPL-2.0/Apache | 1.10.2, 28 окт 2026 | **usable** | [S3] |
| dora-rs | полный dataflow-рантайм: узлы Python/Rust | только win_amd64 cp311-abi3 (22.9 МБ) | 1.1.0, 8 окт 2026 | **usable/experimental**; это рантайм, а не библиотека | [S4] |
| ractor | акторы в одном процессе (модель gen_server) | не связано с Windows-wheel (чистый Rust) | версия 0.16 (из сниппета установки); дата не видна | **usable** (MIT, 2.1k звёзд); `ractor_cluster` «не production ready» | [S5] |
| kameo | акторы, distributed через libp2p | не связано с Windows-wheel | 0.22 (из сниппета установки); дата не видна | **experimental** (0.x, стабильность не заявлена) | [S6] |
| PyO3 / maturin | сборка Rust-расширений для Python | инструмент сборки; win_amd64 wheel у maturin | PyO3 0.30.1 (14 окт 2026); maturin 1.16.0 (29 окт 2026) | **mature** (инструмент сборки, не runtime) | [S7], [S8], [S17] |
| pyarrow | колоночный формат, IPC, Flight | 7 win_amd64 wheel у 26.0.1; требует Python >=3.11 | 26.0.1 (ноябрь 2026, точная дата не разобрана) | **mature** | [S16] |
| Polars | dataframe | PyPI 2.1.0 показывает **только** py3-none-any wheel и sdist | 2.1.0, 25 окт 2026 | **не проверено** (аномалия метаданных, см. §7) | [S9], [S10] |
| PyAV (av) | декодирование видео (FFmpeg, встроен) | win_amd64 cp312-abi3 и cp314t; классификатор «5 - Production/Stable» | 19.0.2, 21 окт 2026 | **mature** для декодирования (см. §7 про даты) | [S18] |
| Halide | DSL для ядер обработки изображений (C++ с Python-биндингами) | в последних notes Windows не упомянут | 22.1.0, 31 окт 2026 | **experimental** для нас | [S22] |

Кандидаты из поиска, **страницы PyPI не открылись** (не проверено): `cykooz.resizer` (Python-обёртка
над Rust-крейтом fast_image_resize, SIMD SSE4.1/AVX2/Neon) и `kornia-rs` (Rust CV с PyO3, декодирование
libjpeg-turbo). Оценка: **не проверено**, по сниппетам — «usable», не более [S19-поиск, см. §7].
Сериализация (msgspec, orjson, serde-биндинги) в этом прогоне **не исследована**.

## 2. Go и C++ (используемые из Python)

| Библиотека | Задача | Windows | Версия, дата | Оценка | Источник |
|---|---|---|---|---|---|
| NATS server (Go) | брокер сообщений | бинарники Windows в видимых ассетах не видны (список обрезан) | v2.15.3, 11 нояб 2026 | **mature** (сервер); Windows **не проверено** | [S12] |
| nats-py | Python-клиент NATS | не указано (Windows не упомянут) | 2.17.0, 17 нояб 2026; классификатор статуса не указан | **usable** | [S11] |
| Redpanda Connect (бывший Benthos) | ETL/стриминг, конфигурация YAML | Windows-ассеты не видны (v4.119.0, 20 нояб 2026) | v4.119.0 | **usable**, но плохо подходит для передачи кадров внутри хоста (мой вывод) | [S21] |
| eCAL (C++ core) | pub/sub, shared memory на локальной машине | Windows и Linux «stable»; macOS/QNX experimental; Apache-2.0; 1.1k звёзд | release-страница без даты в выдаче | **mature** под Windows (по заявлению проекта) | [S13] |
| eCAL Python-биндинг | Python поверх eCAL | Python core через nanobind в 6.1.0 (24 фев 2026); в ассетах 6.1.1 (2 апр) есть `eclipse_ecal-6.1.1-cp310-cp310-win_amd64.whl` | 6.1.1 | **usable** | [S14] |
| Apache Arrow Plasma | shared-memory object store | **deprecated, удалён по плану в 12.0.0** (по dev-list; страница docs 404) | — | **hype/мёртвый** для нас; замену не нашёл | [S30], поиск (см. §7) |

Замечание: на PyPI пакет с именем `ecal` — **другой проект** (календарь доходности, 2018, [S15]).
Ставить нужно `eclipse-ecal`/пакет из релизов eCAL, не `ecal`.

## 3. Process supervision, работающий на Windows

| Инструмент | Что делает | Статус | Оценка | Источник |
|---|---|---|---|---|
| WinSW | обёртка .exe в Windows-службу (XML-конфиг) | релиз v2.13.0, 15 нояб (год не виден); release notes про версии Windows нет | **usable**, свежесть не подтверждена годом | [S23] |
| Servy | обёртка любого .exe в службу, MIT, .NET Framework 4.8 | страница без даты релиза; «Enterprise-Grade» — самоописание проекта | **experimental**, независимой проверки нет | [S24] |
| NSSM | служба из .exe | не проверено (страница не открыта) | не проверено | — |
| supervisor-win, pywin32supervisor | Python-порт supervisor для Windows | найдены только в поиске; страницы не открыты | **не проверено** | — |

Вывод: для Windows-служб практичны WinSW (wrapper) или собственная служба через pywin32 (последнее —
мой вывод по ландшафту, pywin32 не открыт в этом прогоне). Если фреймворк сам держит процессы, внешний
supervisor нужен только как служба-обёртка.

## 4. Архитектура «Python-оркестрация + native hot nodes» в 2026

- Подтверждённые примеры с открытыми страницами:
  - **eCAL**: C++ core с shared-memory транспортом и Python-биндингом [S13][S14] — паттерн «горячий
    транспорт нативный, оркестрация в Python» реализуем.
  - **iceoryx2**: Python-биндинги поверх Rust zero-copy слоя [S1][S2].
  - **dora-rs**: Python-пакет на PyPI, версия 1.1.0 (8 окт 2026) [S4]. Утверждение «узлы на Rust и
    Python в одном графе» взято из поиска, README не открыт — **не проверено**.
- Частота паттерна в 2026 (число проектов/доля рынка): **не нашёл** — честного числа нет.
- Вывод по паттерну: инфраструктурные библиотеки (транспорт, pub/sub) идут в native-слой охотно;
  полные рантаймы (dora, ros-подобные) — это замена, а не ускорение частей.

## 5. Rust-инструменты для Python (короткая сводка)

| Инструмент | Версия, дата | Статус по странице | Оценка | Источник |
|---|---|---|---|---|
| uv | 0.13.9, 17 нояб 2026 | Production/Stable; «uv is stable and widely used in production» (версия < 1.0) | **mature** по заявлению, pre-1.0 по номеру | [S27] |
| ruff | 0.17.6, 19 нояб 2026 | Production/Stable; win_amd64 wheel | **mature** | [S28] |
| pyrefly | 1.5.0, 19 нояб 2026 | Production/Stable; «stable»; минорные версии ежемесячно, возможны новые ошибки типов и breaking changes | **usable** (частые изменения) | [S26] |
| ty | 0.0.107, 18 нояб 2026 | Beta; «ty is currently in beta», нет стабильного API | **experimental** | [S25] |

## 6. Рекомендации к решению (без выбора за владельца)

1. Для shared-memory кадров: проверить iceoryx2 (Windows tier 2) против текущего слоя на Windows-бенчмарке;
   взять как «usable», не как замену без теста.
2. Для Windows-служб: WinSW как обёртка; Servy — только после проверки лицензии и поведения на стенде.
3. Не переписывать routing/actor-слой на ractor/kameo: это решает задачи в одном процессе, не между
   процессами (мой вывод по документации, не отдельный эксперимент).
4. Video decode: PyAV (wheels для Windows есть) — кандидат на замену своего декодера; GStreamer на
   Windows — через MSI MSVC x86_64 [S19], Python-bindings на Windows **не подтверждены**.

## 7. Что я оставил открытым или ненадёжным

- **Polars 2.1.0**: PyPI JSON показывает только `py3-none-any` wheel и sdist [S10]. Для Rust-расширения это
  странно; возможна новая схема упаковки. Не проверено; нужна страница установки Polars или 1.x wheels.
- **PyAV**: страница противоречит себе — версия 18.1.1 датирована 21 нояб 2026, позже 19.0.2 (21 окт) [S18].
  Дату 19.0.2 не подтвердил вторым источником.
- **iceoryx2**: на PyPI нет arm64-wheel для Windows; версия Python-пакета и Rust-крейта различаются (0.10.1 и
  0.10.0 из поиска). Windows-поведение на нашей машине не тестировалось.
- **eCAL release-страница**: года не видно, даты 6.1.x — «2026» по косвенным признакам (footer/asset timestamps).
- **Ractor/Kameo**: даты релизов не получены; версии из сниппетов установки. Сравнение 2026 из поиска
  (pistack, segmentfault) не открыл, использую только официальные GitHub-страницы.
- **NATS server** и **Redpanda Connect**: Windows-бинарники не видны в обрезанном списке ассетов; не подтверждено.
  Утверждение «Redpanda Connect — преемник Benthos» не подтверждено (страница говорит только о зависимости).
- **Plasma**: статус «удалён» основан на dev-list-письме из поиска и 404 на docs-странице [S30]; release notes
  Arrow не открыл. Замену не нашёл.
- **Не проверено (страницы не открылись)**: `cykooz.resizer`, `kornia-rs` на PyPI; NSSM; pywin32;
  supervisor-win; pywin32supervisor; GStreamer Python-bindings на Windows (gi/PyGObject не упомянуты на
  странице установки [S19]).
- **Не исследовано**: сериализация (msgspec, orjson, serde), Halide Windows-wheels, данные рынка по частоте паттерна.
- Цифры скорости (fast_image_resize vs Pillow, kornia-rs 3–5x) в отчёт не вошли: источники не открыты,
  бенчмарков на наших данных нет. Любая «ускорение в N раз» требует собственного замера.
- Оценки mature/usable/experimental — моя классификация по заявлениям страниц (классификатор PyPI, release
  notes, описание), а не независимые тесты. Проверка на Windows на нашем стенде не выполнялась.

## Источники (открыто и прочитано в этом прогоне)

- [S1] https://pypi.org/project/iceoryx2/ — 0.10.1, 20 нояб 2026; win_amd64 wheels; Windows tier 2.
- [S2] https://ekxide.io/blog/iceoryx2-0.9-release/ — пост от 18/05/2026; GIL, Windows в списке платформ.
- [S3] https://pypi.org/project/eclipse-zenoh/ — 1.10.2, 28 окт 2026; win_amd64 abi3; «4 - Beta».
- [S4] https://pypi.org/project/dora-rs/ — 1.1.0, 8 окт 2026; только win_amd64 cp311-abi3.
- [S5] https://github.com/slawlor/ractor — MIT, 2.1k звёзд; cluster «не production ready».
- [S6] https://github.com/tqwewe/kameo — MIT/Apache-2.0; distributed через libp2p; дат нет.
- [S7] https://github.com/PyO3/maturin/releases — v1.16.0 (29 окт), v1.15.0 (24 авг), v1.14.1 (19 июн); Windows-правки.
- [S8] https://github.com/PyO3/pyo3/releases — v0.30.1 (14 окт), v0.30.0 (13 окт); Python 3.15 тестирование.
- [S9] https://pypi.org/project/polars/ — 2.1.0, 25 окт 2026; Production/Stable.
- [S10] https://pypi.org/pypi/polars/2.1.0/json — только py3-none-any wheel и sdist; upload 2026-10-25.
- [S11] https://pypi.org/project/nats-py/ — 2.17.0, 17 нояб 2026.
- [S12] https://github.com/nats-io/nats-server/releases — v2.15.3 (11 нояб 2026); Windows не виден.
- [S13] https://github.com/eclipse-ecal/ecal — Windows/Linux «stable», Apache-2.0, shared memory.
- [S14] https://github.com/Eclipse-eCAL/eCAL/releases — 6.1.0 (24 фев, nanobind), 6.1.1 (2 апр), win_amd64 wheel в ассетах.
- [S15] https://pypi.org/pypi/ecal/json — пакет `ecal` 1.0.2 (2018), не eCAL.
- [S16] https://pypi.org/pypi/pyarrow/26.0.1/json — 7 win_amd64 wheels; Python >=3.11.
- [S17] https://pypi.org/pypi/maturin/1.16.0/json — win_amd64 wheel; первый файл 2026-10-29.
- [S18] https://pypi.org/project/av/ — 19.0.2, 21 окт 2026; Production/Stable; win_amd64 wheels; FFmpeg bundled.
- [S19] https://gstreamer.freedesktop.org/documentation/installing/on-windows.html — MSVC x86_64 MSI; Python на Windows не упомянут.
- [S20] https://pypi.org/project/gstreamer-bundle/ — 1.28.9, 9 нояб 2026; «installers on macOS and Windows».
- [S21] https://github.com/redpanda-data/connect/releases — v4.119.0 (20 нояб 2026); Windows-ассеты не видны.
- [S22] https://github.com/halide/Halide/releases — 22.1.0 (31 окт 2026); Python Buffer fixes.
- [S23] https://github.com/winsw/winsw/releases — v2.13.0 (15 нояб, год не виден).
- [S24] https://github.com/aelassas/servy — MIT; «Enterprise-Grade Windows Service Wrapper»; .NET 4.8.
- [S25] https://pypi.org/project/ty/ — 0.0.107, 18 нояб 2026; Beta.
- [S26] https://pypi.org/project/pyrefly/ — 1.5.0, 19 нояб 2026; Production/Stable; ежемесячные минорные релизы.
- [S27] https://pypi.org/project/uv/ — 0.13.9, 17 нояб 2026; Production/Stable.
- [S28] https://pypi.org/project/ruff/ — 0.17.6, 19 нояб 2026; Production/Stable; 1 win_amd64 wheel.
- [S30] https://arrow.apache.org/docs/python/plasma.html — ответ HTTP 404 при запросе сегодня.

Только из поиска (страница не открыта, факты не заявляются): dora-rs README (Tier 1 Python/Rust), kornia-rs и
cykooz.resizer PyPI, supervisor-win, pywin32supervisor, Servy last push, Plasma dev-list, сравнение ractor/kameo 2026.
