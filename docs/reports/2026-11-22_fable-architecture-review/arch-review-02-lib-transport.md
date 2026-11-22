# Транспорт межпроцессного обмена для Python (камера, кадры 1–6 МБ, 30–60 fps): состояние на 2026-11-22

Дата доступа ко всем страницам: 2026-11-22. Даты в тексте — даты публикации, как они показаны в источнике.
Метки: stable / beta / experimental / abandoned. «не нашёл» — не найдено в проверенных источниках.
Источники помечены: [F] — страница открыта и прочитана в этом запуске; [S] — только текст поисковой выдачи, страница не открыта.

## 0. Итог в четырёх строках

- Zenoh Python: eclipse-zenoh 1.10.2 (28 окт 2026), классификатор PyPI «4 - Beta». SHM в Zenoh сам Zenoh называет unstable API.
- iceoryx2: последняя версия 0.10.1 (20 ноя 2026), релиза 1.0 не нашёл. Windows заявлен (tier 2), Python-биндинги заявлены, всё помечено pre-release.
- Опубликованного сравнения p99 для Zenoh SHM против iceoryx2 на payload 1–6 МБ из Python не нашёл. Есть два ROS-бенчмарка, оба со средним временем или p50 на другом железе.
- Из Python для 1–6 МБ zero-copy кандидаты только два (Zenoh SHM, iceoryx2), оба ниже stable по собственным меткам авторов.

## 1. Zenoh (eclipse-zenoh)

- Версия: eclipse-zenoh **1.10.2**, «Oct 28, 2026» [F] https://pypi.org/project/eclipse-zenoh/ ; совпадает с GitHub releases: тег 1.10.2, «28 Oct» [F] https://github.com/eclipse-zenoh/zenoh-python/releases (год на странице не показан). Предыдущая: 1.10.0, 14 Aug 2026 (там же).
- Статус Python API: классификатор «4 - Beta» [F] https://pypi.org/project/eclipse-zenoh/ . Метка: **beta**. Оговорка: классификаторы PyPI перечисляют Python 3.8–3.12, а wheels abi3 под CPython 3.9+ (там же). README: «tested with Python 3.8 ... 3.12» [F] https://github.com/eclipse-zenoh/zenoh-python .
- Zenoh 1.10 (блог, 2026-08-17; релиз 18 Aug 2026) [F] https://zenoh.io/blog/2026-08-17-zenoh-1.10/ :
  - транспортный SHM-провайдер «remains part of Zenoh's unstable shared-memory API»;
  - выбор типов сообщений для SHM-оптимизации (put/query/reply) — стабильность не указана;
  - timestamp instrumentation в Python: «part of Zenoh's unstable API».
  Метка SHM: **experimental** (unstable по собственной формулировке Zenoh).
- Stable-статус SHM в Python API: не нашёл. Документация zenoh-python [F] https://zenoh-python.readthedocs.io/en/latest/ не называет ни стабильность, ни версию, ни требования feature-флагов для SHM; сказано только, что Python — binding над Rust API.
- Windows: wheel «Windows x86-64» есть [F] https://pypi.org/project/eclipse-zenoh/ . Zenoh-cpp собирается под MSVC 2022 [F] блог 1.10 (см. выше). Отдельного Windows-статуса для SHM не нашёл. По поисковой выдаче [S] в исходниках zenoh-shm 1.4.0 есть Windows-модуль (docs.rs, страница не открыта).
- Известные проблемы: открытый баг Windows по SHM не нашёл. По выдаче [S] виден только баг zenoh-c «DLL panics in libc::atexit handler on Windows» (#973), к SHM не относится; страница не открыта.
- rmw_zenoh: README [F] https://github.com/ros2/rmw_zenoh — «scope of rmw_zenoh is limited to ROS 2 nodes on Tier-1 supported platforms»; Windows в README не упомянут; примеры Linux-only (/dev/shm); известная проблема: несовместимость Humble с новыми дистрибутивами. Страница quality declaration закрыта защитой Anubis [F] (две попытки, см. «открытое»). Из поисковой выдачи [S]: в докладе RosCon 2024 Windows упоминался как пункт пути к Tier-1; CI-статус Windows в мартовских минутах ROS PMC 2025 [S]. Метка rmw_zenoh для Windows: **не подтверждено**.

## 2. iceoryx2

- Версия: **0.10.1**, «Nov 20, 2026», классификатор «4 - Beta» [F] https://pypi.org/project/iceoryx2/ . Wheels: Windows x86-64, Linux glibc 2.34+ x86-64, macOS 11+ ARM64; sdist есть.
- Релизы GitHub [F] https://github.com/eclipse-iceoryx/iceoryx2/releases : все последние 8 помечены pre-release; v0.10.1 — 20 Nov; v0.10.0 — 18 Sep; v0.9.3 — 08 Jul; v0.9.0 — 18 May (год на странице не показан, 2026 по PyPI для 0.10.1).
- 1.0: не нашёл. Поиск «iceoryx2 1.0» [S] выдал только Eclipse iceoryx 1.0 «Almond» (2021) — другой проект. Метка проекта: **experimental** (pre-1.0, pre-release), на PyPI — beta.
- Windows: таблица поддержки платформ в README [F] https://github.com/eclipse-iceoryx/iceoryx2 : Windows — «done», tier 2, определение tier 2: «Works with a restricted security and safety feature set». Метка: **beta** (заявлено, с ограничениями tier 2).
- Python: README [F] указывает Python «done» и ссылку на API reference [F] https://eclipse-iceoryx.github.io/iceoryx2/python/main . В API reference: полезная нагрузка — «a Slice when the payload type is a Slice, otherwise a ctypes.POINTER to the payload type». Значит для кадра возможен срез байт; на практике не проверял. Версия API reference на странице не указана.
- Предупреждение о неопределённом поведении для не-ctypes типов Python: найдено только в стороннем форке [S], не в официальной доке. Не проверено.
- Публичные заявления производительности: FOSDEM 2026 (слайды, [S]) — «sub-microsecond, independent of message size» для статического размера; в ROS-бенчмарке ниже видно, что результаты зависят от стека.

## 3. Альтернативы и стдлиб

| Библиотека | Версия / дата | Python | Windows | Метка | Источник |
|---|---|---|---|---|---|
| dora-rs | 1.1.0, 8 Oct 2026 | wheels abi3 (CPython 3.11+) | wheel x86-64 есть | не определено (классификатора нет) | [F] https://pypi.org/project/dora-rs/ |
| eCAL | 6.1.1, 2 Apr 2026 (pip с 6.0.1) | wheels 3.8–3.14, в т.ч. free-threaded | Python-wheel x64 есть | не определено; SHM-монитор в 5.11 помечен experimental | [F] https://eclipse-ecal.github.io/ecal/releases/ecal_6_1_1.html ; SHM-monitor в 5.11 — [S] |
| NATS | nats-py 2.17.0, 17 Nov 2026; сервер доки «2.15 (latest)» | nats-py есть | не проверено | stable (клиент и сервер, без классификатора) | [F] https://pypi.org/project/nats-py/ , https://docs.nats.io/running-a-nats-service/configuration |
| ZeroMQ (pyzmq) | 27.3.0, 4 Nov 2026 | да | wheel cp312 win_amd64 | stable («5 - Production/Stable») | [F] https://pypi.org/project/pyzmq/ |
| Cyclone DDS (cyclonedds) | 11.1.0, 9 Nov 2026 | wheels cp310–cp313 | win_amd64 wheels есть | stable («5 - Production/Stable») для Python-пакета | [F] https://pypi.org/project/cyclonedds/ |
| Fast DDS | официального PyPI-пакета не нашёл | сборка из исходников через colcon | не проверено | experimental (для Python) | [S] github.com/eProsima/Fast-DDS-python; C++ 3.2.4 по ROS index [S] |
| Aeron | официального Python-клиента не нашёл | сторонний pyaeron (CPython 3.12–3.15) | не проверено | experimental (не подтверждено; страница pyaeron не открылась) | [S] https://pypi.org/project/pyaeron/ |
| multiprocessing.shared_memory | stdlib; 3.13 добавил track | да | track игнорируется; unlink без эффекта, память удаляется при закрытии всех дескрипторов | stable | [F] https://docs.python.org/3.14/library/multiprocessing.shared_memory.html |
| concurrent.interpreters (PEP 734), InterpreterPoolExecutor | Python 3.14 | да | не проверено | beta (новое в 3.14; «there aren't many options yet for truly sharing objects», кроме memoryview) | [F] https://docs.python.org/3/whatsnew/3.14.html |
| Python 3.15.0 | 9 Oct 2026, «stable release»; заменён 3.15.2 | — | — | stable | [F] https://www.python.org/downloads/release/python-3150/ ; [F] https://docs.python.org/3/whatsnew/3.15.html (читал первые 100k символов из ~216k) |

Дополнительно по Python 3.14/3.15:
- 3.14 (forkserver по умолчанию на Unix, кроме macOS; на Windows и macOS остаётся spawn) [F] https://docs.python.org/3/whatsnew/3.14.html . Для Windows-кадров это не меняет схему.
- В видимом тексте 3.14 и 3.15 не нашёл изменений multiprocessing.shared_memory. Полный текст 3.15 не прочитан.

## 4. Опубликованные бенчмарки

Важно: ни один из найденных бенчмарков не делает ровно то, что нужно (Python, 1–6 МБ, межпроцессно, p99, Zenoh SHM против iceoryx2).

1. rmw_iceoryx2, PR #87 (открыт 2 Oct 2026, merged 8 Oct 2026) [F] https://github.com/ekxide/rmw_iceoryx2/pull/87 . Железо: Apple M5 Pro, в контейнере Ubuntu 26.04 с ограничением 2 CPU, Colima VM aarch64. ROS 2 Rolling, C++. Publisher и subscriber в одном процессе. Статистика: среднее (mean) и частота, без p50/p99. Число запусков в таблице — медиана из 3 (для части таблиц). Конфигурация Zenoh SHM не указана.
   Таблица 2, mean latency (1 KB / 64 KB / 1 MB / 4 MB):
   - iceoryx2: 12.4 / 12.1 / 12.3 / 12.6 µs
   - Zenoh: 27.6 / 27.8 / 127.2 / 464.1 µs
   - Cyclone DDS: 23.6 / 28.2 / 85.3 / 256.4 µs
   - Fast DDS: 39.7 / 72.3 / 35.6 / 96.0 µs
   (Скорость приёма: iceoryx2 ~315 k/s на всех размерах; Zenoh 223 k/s на 1 KB, 5 k/s на 4 MB.)
   В PR есть поправка: первый прогон не выставлял ROS_DISABLE_LOANED_MESSAGES=0, и iceoryx2 копировал данные; таблица — исправленный прогон.
2. ros2-macos-rmw-bench [F] https://github.com/idesign0/ros2-macos-rmw-bench . Железо: «M2 Mac» (модель, RAM, macOS не указаны), 2 процесса, дата результатов не указана. Статистика: в основном p50 при 2 kHz; для больших сообщений статистика не указана. iceoryx2 не включён (есть Cyclone + iceoryx1-вариант).
   - Zenoh + SHM, 4 MB @ 1961 Hz: 296 µs (статистика не указана)
   - Zenoh без SHM, 2 kHz, p50: ~150 µs
   - Cyclone + iceoryx (не iceoryx2), 1 MB @ 1982 Hz: 100 µs; 4 MB требует больший пул RouDi
   - Cyclone DDS (без SHM), 1 MB @ 1964 Hz; 4 MB — отказ
3. iceoryx2, обсуждение #435 [F] https://github.com/eclipse-iceoryx/iceoryx2/discussions/435 (5 Oct 2024 — 29 May 2025). Ping-pong двух процессов, один байт, оценка одного направления ~700 ns. Zenoh не участвует; железо в тексте не указано; большие payload не измерены.

Вывод: опубликованного p99-сравнения для 1–6 МБ (Zenoh SHM против iceoryx2, Python или C++) не нашёл. Нужен собственный стенд с одинаковым harness.

## 5. Что это значит для выбора (без решения)

- Нагрузка 1–6 МБ при 30–60 fps — порядка 30–360 МБ/с. По mean-данным из PR #87 iceoryx2 стабилен на размерах 1–4 МБ, Zenoh без SHM заметно растёт с размером (127 µs при 1 МБ, 464 µs при 4 МБ), но это ROS 2 C++ в одном процессе.
- ZeroMQ, NATS, Cyclone DDS (без iceoryx) — копирующие транспорты по своим данным; для 1–6 МБ их стоимость на копирование стоит мерить отдельно.
- Оба zero-copy кандидата (Zenoh SHM, iceoryx2) по собственным меткам авторов не stable.

## Что я оставил открытым или ненадёжным

- Не проверено: Windows-статус rmw_zenoh (страница quality declaration закрыта Anubis, две попытки; README не упоминает Windows).
- Не проверено: Windows-поведение Zenoh SHM; Windows-модуль zenoh-shm известен только по выдаче [S].
- Не проверено: Python SHM API в Zenoh — стабильность и требования feature-флагов; zenoh-python docs их не описывают.
- Не проверено: версии и даты Zenoh 1.10.2 и 1.10.0 — проверены по PyPI (через сводку страницы) и GitHub releases; год в GitHub не показан.
- Не проверено: iceoryx2 Python — undefined behaviour для не-ctypes типов (предупреждение только в стороннем форке [S]); поведение на кадрах 1–6 МБ не измерялось.
- Не нашёл: релиз iceoryx2 1.0; опубликованный p99-бенчмарк для больших payload из Python; официальный Aeron Python-клиент; официальный Fast DDS Python-пакет на PyPI.
- Метки dora-rs, eCAL, NATS (как клиента) и Cyclone DDS (Windows) не подтверждены классификатором или статусом проекта в открытых страницах; ставить их как stable без проверки нельзя.
- pyaeron (PyPI) не открылся; описание по выдаче [S] не проверено.
- Бенчмарки PR #87 — ROS 2 C++ в одном процессе; idesign0 — macOS и ROS 2; ни один не измеряет Python.
- Агнокаст (arXiv 2506.16882) и FOSDEM-слайды iceoryx2 найдены только в выдаче [S], не открыты.
- Поиск не покрывал: Zenoh SHM в Windows-issue трекере (не открыт), iceoryx2 Windows issues, форум Jetson/Linux ARM.

## Источники (открыты в этом запуске, [F])

- https://pypi.org/project/eclipse-zenoh/ (2026-11-22)
- https://github.com/eclipse-zenoh/zenoh-python/releases (2026-11-22)
- https://github.com/eclipse-zenoh/zenoh-python (2026-11-22)
- https://zenoh-python.readthedocs.io/en/latest/ (2026-11-22)
- https://zenoh.io/blog/2026-08-17-zenoh-1.10/ (2026-08-17)
- https://github.com/eclipse-zenoh/zenoh/releases/tag/1.10.0 (2026-11-22)
- https://pypi.org/project/iceoryx2/ (2026-11-22)
- https://github.com/eclipse-iceoryx/iceoryx2/releases (2026-11-22)
- https://github.com/eclipse-iceoryx/iceoryx2 (2026-11-22)
- https://eclipse-iceoryx.github.io/iceoryx2/python/main (2026-11-22)
- https://github.com/ros2/rmw_zenoh (2026-11-22)
- https://github.com/ekxide/rmw_iceoryx2/pull/87 (2026-11-22; PR от 2–8 Oct 2026)
- https://github.com/idesign0/ros2-macos-rmw-bench (2026-11-22)
- https://github.com/eclipse-iceoryx/iceoryx2/discussions/435 (2026-11-22; последний комментарий 29 May 2025)
- https://pypi.org/project/dora-rs/ (2026-11-22)
- https://pypi.org/project/pyzmq/ (2026-11-22)
- https://pypi.org/project/cyclonedds/ (2026-11-22)
- https://pypi.org/project/nats-py/ (2026-11-22)
- https://docs.nats.io/running-a-nats-service/configuration (2026-11-22; версия «2.15 latest»)
- https://eclipse-ecal.github.io/ecal/releases/ecal_6_1_1.html (2026-11-22)
- https://docs.python.org/3.14/library/multiprocessing.shared_memory.html (2026-11-22)
- https://docs.python.org/3/whatsnew/3.14.html (2026-11-22)
- https://docs.python.org/3/whatsnew/3.15.html (2026-11-22; прочитано до ~100k символов)
- https://www.python.org/downloads/release/python-3150/ (2026-11-22)
- https://docs.ros.org/en/rolling/p/rmw_zenoh_cpp/_sources/QUALITY_DECLARATION.md.txt (2026-11-22; Anubis, без содержимого)
- https://docs.ros.org/en/kilted/p/rmw_zenoh_cpp/QUALITY_DECLARATION.html (2026-11-22; Anubis, без содержимого)
- https://docs.nats.io/reference/faq (2026-11-22; без данных о max_payload)
- https://pypi.org/project/pyaeron/ (2026-11-22; страница не загрузилась)

Только поисковая выдача [S], не открыто: fosdem.org слайды iceoryx2 (2026-01-31), arxiv.org/pdf/2506.16882 (Agnocast), github.com/eProsima/Fast-DDS-python, discourse.openrobotics.org (RosCon 2024 слайды), docs.rs/zenoh-shm.
