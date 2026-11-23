# Ландшафт библиотек и индустриальных стеков на конец 2026 (поддержка решения по архитектуре)

Дата исследования: 2026-11-22. Исполнитель: web-researcher (Haiku). Бюджет: 40 вызовов инструментов, использовано ~39.

Легенда статуса: **active** (релиз в 2026 г.), **slow** (релиз давно или признаки замедления), **stale** (давно без релиза), **abandoned** (не найдено признаков жизни), **не нашёл** / **не verified** (не подтверждено источником, которое я открыл).

Важно про источники: ряд страниц docs.ros.org отдавал «Access Denied» (защита Anubis), поэтому часть утверждений про ROS 2 опирается только на сниппеты поиска. Такие утверждения помечены «сниппет, не открыт». Даты, которые парсер страниц GitHub показывал без года, помечены «год не показан».

---

## 1. ROS 2

- **Lyrical Luth** — текущий дистрибутив, LTS, поддержка до мая 2031. Статус: **active**. Источник: https://discourse.openrobotics.org/t/ros-2-lyrical-luth-released/55021 (пост от 2026-05-22; открыт).
- В том же посте: Windows 11 (VS 2022, amd64) и Ubuntu 26.04 (amd64 и arm64) названы Tier 1. Тот же источник.
- **Kilted Kaiju** — релиз май 2025, EOL указан как ноябрь 2026 в одном источнике и декабрь 2026 в другом. Статус: **slow** (близко к EOL). Конфликт дат — **не verified**. Источник дат: сниппет поиска (https://docs.ros.org/en/humble/Releases.html, не открыт).
- **Следующий дистрибутив** — май 2027, название в источниках расходится («M Turtle» и «Makoa Mata-mata»). **не verified**. Сниппет поиска (https://docs.ros.org/en/lyrical/The-ROS2-Project/Release-Schedule.html, не открыт).
- **Windows-бинарники Lyrical:** по сниппету страницы Windows Install Binary, финальные бинарники не выкладываются, только nightly. Страница закрыта Anubis. **не verified**.
- **Default middleware:** Fast DDS остаётся по умолчанию. Источник: https://discourse.openrobotics.org/t/ros-2-lyrical-luth-and-11-years-of-fast-dds-as-ros-2-default-middleware/55062.md (открыт, пост от мая 2026).
- **rmw_zenoh:** в Kilted назван Tier 1 (сниппет из поста Kilted, https://discourse.ros.org/t/ros-2-kilted-kaiju-release/43902, не открыт). Для Lyrical статус rmw_zenoh **не нашёл**: quality declaration (https://docs.ros.org/en/kilted/p/rmw_zenoh_cpp/QUALITY_DECLARATION.html) и таблица supported platforms закрыты Anubis. Пакет ставится (`ros-lyrical-rmw-zenoh-cpp`), по сниппету.
- **Hiroz** (ZettaScale, Zenoh-стек, не замена rmw_zenoh): сниппет, https://discourse.openrobotics.org/t/introducing-hiroz-by-zettascale/55081 (не открыт). Статус **не verified**.
- **Пригодность для Windows + Python-first команды (вывод, не факт):** Windows числится Tier 1 на Lyrical, но бинарной поставки в docs не видно, а экосистема драйверов и узлов Linux-centric. Для связки камера + робот Modbus + возможно OPC UA ROS 2 выглядит тяжёлым слоем поверх Python-first кода; реалистичнее использовать его как опцию на Jetson (Ubuntu), а не как основу для Windows. Это моё суждение, не проверено замерами.

## 2. dora-rs

- **Версия:** v1.0.0 (стабильный релиз, 02 Sep 2026), v1.0.1 (03 Sep 2026), **v1.1.0 (08 Oct 2026, latest)**. Статус: **active**. Источник: https://github.com/dora-rs/dora/releases (открыт; даты извлечены парсером, год показан только у релизов 2026, перепроверить вручную).
- В README: «dora 1.0 is out». Лицензия **Apache-2.0**. Источник: https://github.com/dora-rs/dora (открыт).
- **Python:** пакет `dora-rs` (не `dora`), `pip install dora-rs`, Python >= 3.11, оценка «First-class». Источник: тот же README.
- **Windows (x86_64):** «Best effort (nightly-gated)» для Rust и Python; сбой не блокирует PR. Есть PowerShell-инсталлятор. Источник: тот же README.
- **Зрелость по README:** ROS2-мост — «Experimental», Node Hub — «unstable», восстановление dataflow после рестарта координатора — «partial». Источник: тот же README.
- Старые зеркала changelog (последняя запись 2025) — устаревший срез, не использовать.

## 3. Savant, DeepStream, Holoscan

**Savant** (Python + Rust, YAML-пайплайны над DeepStream):
- Последний релиз в списке GitHub — **v0.6.0**, «08 Dec», год не показан (по контексту, скорее 2025). Статус: **slow / возможно stale**. Источник: https://github.com/insight-platform/Savant/releases (открыт) и https://github.com/insight-platform/Savant/releases/tag/v0.6.0 (открыт).
- v0.6.0: DeepStream 7.1, TensorRT 10.9, минимум JetPack 6.2. В notes Orin NX **не назван**; заявленная поддержка Orin Nano/NX у зеркал — сниппет агрегатора, **не verified**.
- Предыдущие релизы (0.5.x): DeepStream 7.0, JetPack 6.x.
- Лицензия Savant — **не нашёл** (не проверял отдельно).

**NVIDIA DeepStream** (текущая версия 9.2):
- Версия 9.2 — страница release notes, copyright 2026. Источник: https://docs.nvidia.com/deepstream/text/DS_Release_notes.md (открыт, дата явно не указана, год копирайта 2026). Статус: **active**.
- Платформы: dGPU/x86 (Turing–Blackwell) и Jetson Orin и Jetson Thor. В разделе 9.1 указана поддержка Jetson Orin (Nano, NX, AGX). Источник: тот же документ. Значит Orin NX поддерживается, **по документу 9.1**.
- Нативный Windows в notes не упомянут, есть только WSL с пониженной производительностью. Источник: тот же документ.
- Лицензия: на странице не указана. Упомянуты open-sourced компоненты (nvdsmetainsert, nvdsmetaextract) и GitHub mono-repo. Условия лицензии SDK — **не verified**.

**NVIDIA Holoscan SDK** (Python, GXF-based):
- Holoscan 4.2 — блог от 2026-05-13, `pip install holoscan==4.2.0` (CUDA 12) и `holoscan-cu13` (CUDA 13). Статус: **active**. Источник: https://nvidia-holoscan.github.io/blog/2026-05-13-holoscan-sdk-4.2/ (открыт).
- На Jetson в блоге упомянуты только Jetson Orin iGPU (известная проблема) и IGX Thor. Jetson AGX и NX **не упомянуты**, поддержка Orin NX — **не нашёл**. Источник: тот же блог.
- Windows — блог ничего не говорит, **не нашёл**. Лицензия — блог не указывает, **не нашёл**.
- Версии 4.3 (28 May 2026) и 4.6.0 (31 Aug 2026, по redistrib JSON) — сниппеты поиска (https://nvidia-holoscan.github.io/blog/2026-05-28-holoscan-sdk-4.3/, https://developer.download.nvidia.com/compute/holoscan/redist/redistrib_4.6.0.json), не открыты, **не verified**.

## 4. Камеры: Harvesters / GenICam, pypylon, новые открытые библиотеки

- **pypylon 26.10** — 2026-11-06, Basler, **Proprietary/Other**. Колёса: Windows x86-64 (cp39-abi3), Linux x86-64 и **aarch64** (manylinux_2_31), macOS. Windows ARM колёс нет. Статус: **active**. Источник: https://pypi.org/project/pypylon/ (открыт).
- **Harvesters 1.4.3** — лицензия Apache Software License 2.0, классификатор «5 - Production/Stable». Дата релиза 1.4.3 **не прочитана** (ответ обрезан). Источник: https://pypi.org/pypi/harvesters/json (открыт). Репозиторий: Apache-2.0, раздел Releases пуст, 1 387 коммитов, даты последнего коммита не видно. Источник: https://github.com/genicam/harvesters (открыт). Статус: **не verified** (ориентировочно slow; нужна дата).
- **viva-genicam 0.12.0** — 2026-11-14, MIT, Python >= 3.10, классификатор «4 - Beta». Pure-Rust GenICam с Python-биндингами для GigE Vision и USB3 Vision. Колёса: Windows x86-64, Linux x86-64, macOS ARM64. **Linux aarch64 колеса нет** (Jetson потребует сборку из исходников — вывод из списка колёс). Статус: **active, Beta**. Источник: https://pypi.org/project/viva-genicam/ (открыт). Версия 0.2.4 раньше, рост до 0.12 за короткий срок — сниппет, не объяснял.
- **pyGigEVision** (чистый Python GVCP/GVSP), **rc_genicam_api** (Roboception) — сниппеты поиска, статус и лицензия **не verified**.

## 5. OPC UA и Modbus

- **asyncua 2.1.0** — 2026-10-06, LGPLv3+, Python >= 3.10, классификатор «4 - Beta». Статус: **active** (с оговоркой Beta). Источник: https://pypi.org/project/asyncua/ (открыт).
- **pymodbus 3.16.2** — 2026-11-03, BSD-3-Clause, Python >= 3.10, «5 - Production/Stable». Статус: **active**. Источник: https://pypi.org/project/pymodbus/ (открыт).

## 6. Инференс и дефектоскопия

- **ONNX Runtime 1.32.0** — MIT, Python >= 3.11. Дата файлов **не прочитана**. Статус: **active** (по номеру версии). Источник: https://pypi.org/pypi/onnxruntime/json (открыт, ответ обрезан).
- **OpenVINO 2026.4.1** — Apache-2.0 (license_expression), Python >= 3.10. Дата **не прочитана**. Статус: **active**. Источник: https://pypi.org/pypi/openvino/json (открыт, ответ обрезан).
- **TensorRT** — по сниппетам release notes (docs.nvidia.com, не открыты): TensorRT 11 вышел (ветка 11.x, 11.4.1 — DLA на AGX Orin с JetPack 7.2.2+); на JetPack 6 (Orin) остаётся ветка 10.x; API TensorRT 10.14 сохраняются до 10/2026; Windows 10 после 10/2026 не поддерживается; Python 3.8/3.9 deprecated. Статус: **active**, все пункты — **не verified** по открытому источнику.
- **anomalib 2.7.1** — Apache-2.0 (поле license, полный текст), Python >= 3.10, «5 - Production/Stable». Статус: **active**. Источники: https://pypi.org/pypi/anomalib/json, https://github.com/open-edge-platform/anomalib/releases (оба открыты).
  - lib/v2.7.1 (17 Nov, год не показан): автозагрузка датасета MVTec отключена, т.к. upstream URL не работают.
  - lib/v2.7.0 (06 Oct, год не показан): удалён legacy ONNX exporter, PyTorch < 2.10 не поддерживается, загрузка чекпоинтов по умолчанию weights-only, добавлены MHPatchcore, Rad, FoundAD.
- **Лицензии семейств детекторов:**
  - **Ultralytics (YOLOv8/YOLO11 и др.)** — AGPL-3.0 или коммерческая Enterprise License. Источник: https://github.com/ultralytics/ultralytics (открыт; дата последнего релиза не видна). Статус: **active**. Для закрытого коммерческого продукта — риск, нужна лицензия.
  - **YOLOX** — Apache-2.0 (репо). Дата релиза не видна. Статус **не verified**. Источник: https://github.com/Megvii-BaseDetection/YOLOX (открыт).
  - **RT-DETR (lyuwenyu)** — код Apache-2.0. Лицензия весов на странице **не указана**. Статус **не verified**. Источник: https://github.com/lyuwenyu/RT-DETR (открыт).
  - Лицензии весов PatchCore/EfficientAD/PaDiM и ImageNet-бэкбонов — **не нашёл** (не проверял).

## 7. Новые проекты 2025–2026 (цель была 3–5; проверено 1 полностью)

1. **viva-genicam** (см. п. 4) — Pure-Rust GenICam для Python. Лицензия MIT. Зрелость: Beta. Статус: active. URL: https://pypi.org/project/viva-genicam/ (открыт).
2. **dora-rs 1.0** (см. п. 2) — не новый проект, но переход к 1.x в 2026 году. Лицензия Apache-2.0. Зрелость: stable core, часть компонентов experimental/unstable. Статус: active. URL: https://github.com/dora-rs/dora/releases (открыт).
3. **mvkit** (PyPI) — фреймворк для инспекции на производственной линии: триггер, захват, инспекция, отчёт; плагины камер и приёмников; стек onnxruntime + numpy + opencv. По сниппету поиска, https://pypi.org/project/mvkit/ — страница не открылась (ошибка загрузки). Лицензия, дата и зрелость **не verified**, кандидат для проверки.
4. **CVC Inspect (PreML GmbH)** — Python-фреймворк для визуальной инспекции, только open-source зависимости. Сниппет поиска, без даты, лицензии и репозитория. **не verified**.
- Hiroz (ZettaScale) см. п. 1, сниппет, **не verified**.
- Euresys Open eVision (версия 25.10, 1 декабря 2025) — Python-биндинги, но коммерческий SDK по сниппету. Не открыт.

## Сводка по статусам

| Компонент | Версия / дата | Статус | Лицензия |
|---|---|---|---|
| ROS 2 Lyrical | LTS, 2026-05-22, до 05/2031 | active | Apache-2.0 (не проверено) |
| ROS 2 Kilted | май 2025, EOL конфликт (ноя/дек 2026) | slow | не проверено |
| dora-rs | 1.1.0, 2026-10-08 | active | Apache-2.0 |
| Savant | 0.6.0, 08 Dec (год не показан) | slow / stale? | не нашёл |
| DeepStream | 9.2 (2026) | active | не verified (NVIDIA EULA, не проверено) |
| Holoscan | 4.2 (2026-05-13) | active | не нашёл |
| TensorRT | 11.x, 10.16.x | active | не verified |
| ONNX Runtime | 1.32.0 | active | MIT |
| OpenVINO | 2026.4.1 | active | Apache-2.0 |
| pypylon | 26.10, 2026-11-06 | active | proprietary |
| Harvesters | 1.4.3 (дата не прочитана) | не verified | Apache-2.0 |
| viva-genicam | 0.12.0, 2026-11-14 | active (Beta) | MIT |
| asyncua | 2.1.0, 2026-10-06 | active (Beta) | LGPLv3+ |
| pymodbus | 3.16.2, 2026-11-03 | active | BSD-3-Clause |
| anomalib | 2.7.1 | active | Apache-2.0 |
| Ultralytics | не видна | active | AGPL-3.0 / Enterprise |

## Что я оставил открытым или ненадёжным

- **ROS 2 официальные docs закрыты Anubis** (docs.ros.org: Lyrical release, release schedule, supported platforms, Windows binary, rmw_zenoh quality declaration). Всё про tier rmw_zenoh для Lyrical, Windows binary и EOL Kilted — не verified. Нужен прямой доступ к REP-2000 или GitHub ros2/ros2 (не открывал).
- **Конфликты дат:** EOL Kilted (ноябрь vs декабрь 2026), название следующего дистрибутива (M Turtle vs Makoa Mata-mata).
- **Парсинг GitHub-страниц:** даты dora-rs и Savant извлечены из страниц, где год не показан. Даты dora-rs (сентябрь–октябрь 2026) надо перепроверить вручную по записям релизов. Год для Savant v0.6.0 не подтверждён.
- **Дата релиза Harvesters 1.4.3 и ONNX Runtime 1.32.0 не прочитана** (ответ обрезан, >100k символов). Зрелость этих библиотек оценена по классификатору и номеру версии, а не по дате.
- **Holoscan:** поддержка Jetson Orin NX и Windows не найдена; версии 4.3 и 4.6.0 — только сниппеты. Лицензия Holoscan не найдена.
- **Savant:** лицензия не найдена; заявленная поддержка Orin NX у зеркал не подтверждена официальными notes.
- **TensorRT:** все утверждения по сниппетам release notes, страницы не открывал.
- **Лицензии весов моделей** (RT-DETR, PatchCore, EfficientAD, backbone ImageNet) не проверены. Ultralytics-лицензия подтверждена только по странице репозитория, не по LICENSE-файлу.
- **Новые проекты:** полностью проверен только viva-genicam. mvkit и CVC Inspect — сниппеты, страница mvkit не открылась. Цель «3–5 проектов с лицензией и зрелостью» выполнена частично.
- **Инструмент-суммаризатор:** содержимое страниц было пересказано малой моделью. Все числа (версии, даты, колёса) подлежат выборочной сверке по указанным URL перед решением.
- **Вопросы, которые переживут задачу (для docs/claude/OPEN_QUESTIONS.md, записывает лид):** (1) реальна ли поддержка Jetson Orin NX в Holoscan и Savant; (2) есть ли Linux aarch64 wheel у viva-genicam или нужна сборка на Jetson; (3) статус rmw_zenoh tier для Lyrical; (4) лицензия весов выбранной детекторной модели.
- Ни одного коммита, ни одного изменения вне этого файла не сделано.

## Sources (открытые в этом прогоне)

- https://discourse.openrobotics.org/t/ros-2-lyrical-luth-released/55021
- https://discourse.openrobotics.org/t/ros-2-lyrical-luth-and-11-years-of-fast-dds-as-ros-2-default-middleware/55062.md
- https://github.com/dora-rs/dora
- https://github.com/dora-rs/dora/releases
- https://github.com/insight-platform/Savant/releases
- https://github.com/insight-platform/Savant/releases/tag/v0.6.0
- https://docs.nvidia.com/deepstream/text/DS_Release_notes.md
- https://nvidia-holoscan.github.io/blog/2026-05-13-holoscan-sdk-4.2/
- https://pypi.org/project/pypylon/
- https://pypi.org/pypi/harvesters/json
- https://github.com/genicam/harvesters
- https://pypi.org/project/viva-genicam/
- https://pypi.org/project/asyncua/
- https://pypi.org/project/pymodbus/
- https://pypi.org/pypi/onnxruntime/json
- https://pypi.org/pypi/openvino/json
- https://pypi.org/pypi/anomalib/json
- https://github.com/open-edge-platform/anomalib/releases
- https://github.com/ultralytics/ultralytics
- https://github.com/Megvii-BaseDetection/YOLOX
- https://github.com/lyuwenyu/RT-DETR

Не открыты (только сниппеты поиска, не использовать как подтверждённые): docs.ros.org (Releases, Release-Schedule, Lyrical Windows binary, supported platforms, rmw_zenoh quality declaration), discourse.ros.org Kilted, openrobotics Kilted blog, Holoscan 4.3 и redistrib 4.6.0, docs.nvidia.com TensorRT release notes, pypi.org/project/mvkit (ошибка загрузки), Hiroz discourse post.
