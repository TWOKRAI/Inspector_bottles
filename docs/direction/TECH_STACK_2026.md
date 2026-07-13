# Целевой нативный стек 2026+

Стратегический анализ: какие нативные библиотеки (Rust / Go / C / C++) и версии Python
внедрять в `multiprocess_framework` / `multiprocess_prototype` как Services или зависимости,
чтобы ускорить систему и сохранить кроссплатформенность (Windows / Linux x86 / Raspberry Pi / Jetson Orin).

**Дата анализа:** 2026-07-12. Живой документ — статусы пересматриваются по мере решений.
**Горизонт:** 2026 H2 → 2027, с заделом на перспективу.

> Легенда статусов: **✅ внедрить** (близкий кандидат) · **🧪 пилот** (проверить на ветке/стенде) ·
> **👀 наблюдать** (следить, пока не созрело) · **⛔ отклонить** (не для нашего продукта).

---

## 0. TL;DR — таблица решений

| Технология | Роль в системе | Статус | Волна |
|---|---|---|---|
| **Чистка pyproject** (−10 мёртвых deps, +pyarrow) | гигиена зависимостей | ✅ внедрить (первым шагом) | 2026 H2 |
| **Python 3.13** (миграция с 3.12) | базовый рантайм | ✅ внедрить | 2026 H2 |
| **PySide6 6.11** (снять пин `<6.11`) | GUI; пререквизит Python 3.14 | 🧪 пилот | 2026 H2 |
| **Python 3.14 free-threading** | потоки вместо процессов для части нагрузки | 🧪 пилот (тестировать, не деплоить) | 2027 |
| **msgspec** | типизированные payload'ы на границах + socket-канал (транспорт Queue/SHM остаётся) | ✅ внедрить | 2026 H2 |
| **orjson** | быстрый JSON там, где нужен именно JSON | ✅ внедрить | 2026 H2 |
| **Polars** | телеметрия/логи/статистика — greenfield (pandas в коде не используется) | ✅ внедрить (Service `analytics`) | 2026 H2 |
| **PyO3 + maturin** | свои горячие участки на Rust | 🧪 пилот (по профилю) | 2026 H2 |
| **ONNX Runtime + EP по платформам** | инференс (уже основной backend) | ✅ развить (TensorRT/OpenVINO/XNNPACK EP) | 2026 H2 |
| **OpenCV 5** | CV-ядро (обновление с 4.x) | 🧪 пилот — колёса на PyPI с 2026-07-02 | 2026 H2 → 2027 |
| **anomalib (Intel)** | unsupervised-детекция дефектов, Apache-2.0 (без AGPL-рисков) | 🧪 пилот | 2027 |
| **Rerun SDK** | визуальный дебаг мультикамерного пайплайна | 🧪 пилот (dev-extra) | 2026 H2 |
| **TensorRT (Jetson)** | ускоренный инференс на Orin | 🧪 пилот (Service-обёртка EP) | 2027 |
| **Hailo-8L (RPi 5 AI Kit)** | ускоритель для Raspberry Pi | 👀 наблюдать | 2027 |
| **Zenoh** | межмашинный транспорт (без ROS) | 👀 наблюдать (кандидат в `Services/zenoh_bus`) | 2027+ |
| **iceoryx2** | zero-copy IPC (Python-биндинги уже на PyPI; v1.0 к концу 2026) | 👀 наблюдать | 2027 |
| **ROS 2 (полное внедрение)** | оркестрация/IPC/supervision | ⛔ отклонить (дублирует фреймворк) | — |
| **ROS 2 (мост-Service)** | интеграция с ROS-железом (манипуляторы, MoveIt) | 👀 наблюдать (по факту появления железа) | 2027+ |
| **LanceDB / Lance** | версионируемое хранилище ML-датасетов | 👀 наблюдать | 2027 |
| **Numba / Cython** | быстрое ускорение числовых циклов без Rust | 👀 наблюдать (тактически) | по месту |
| **ty (Astral) / pyrefly (Meta)** | замена/дополнение pyright | 👀 ty (0.0.x) · pyrefly 1.0 — вариант второго чекера | 2027 |

---

## 1. Принципы интеграции

Правило одно: **Python — оркестратор, всё тяжёлое живёт в нативном коде, который на время работы
отпускает GIL.** Тогда сама Python-обвязка почти ничего не стоит, а поток данных идёт на скорости C/Rust.

Три способа, которыми чужой код попадает в систему:

1. **Сетевой сервис** — коннект штатным клиентом по протоколу. Язык реализации сервера неважен
   (так мы уже работаем с SQL/PostgreSQL, так бы работали с ROS-мостом или Zenoh-роутером).
2. **Нативный биндинг (pip install → import)** — под капотом скомпилированный C/C++/Rust с released GIL.
   Так уже работают numpy, opencv-python, pydantic-core, onnxruntime, bcrypt. Сюда добавляем Polars, msgspec, Rerun.
3. **Свой Rust через PyO3 + maturin** — выносим горячий участок, зовём как обычную функцию. Наш путь для
   узких мест, которых нет в готовых библиотеках.

**Паттерн Service** (как в `Services/ml_inference`, `Services/modbus`): `Services/<name>/` с `__init__.py`
(публичный API), `interfaces.py` (Protocol-контракты), `STATUS.md`, `README.md`, `tests/`; для крупных —
слои `sdk/ → core/ → service.py` + `plugin/`. **Запрещён импорт `multiprocess_prototype.*`** (enforced sentrux boundaries).

**Паттерн зависимости:** graceful-import (`try: import X; X_AVAILABLE = True`) + `[project.optional-dependencies]`
extra + платформенный маркер (как единственный существующий у нас `harvesters; sys_platform != 'darwin' ...`).
Non-PyPI/нативное — git+sha в `[tool.uv.sources]`. **В core-зависимости тяжёлое не кладём** — только через extra,
чтобы headless-CI и слабое железо ставили минимум.

**Совместимость с «Dict at Boundary»:** любая новая сериализация на границе процессов обязана давать `dict`/bytes,
Pydantic остаётся внутри процесса. msgspec сюда ложится идеально (декодит в `dict` или в `msgspec.Struct`).

---

## 2. Python: версия и рантайм

### Что происходит в 2026
- **Python 3.14** вышел в октябре 2025. Free-threaded-сборка (PEP 779) получила **официально поддерживаемый**
  статус (не дефолт, отдельный бинарь `python3.14t`). Штраф на однопоток упал до **5–10 %** (в 3.13t было ~40 %).
  Решение о GIL-off по умолчанию (фаза 3) официально **не принято** — по плану PEP 703 не раньше ~2028–2030.
- **JIT (PEP 744)** и субинтерпретаторы (PEP 734, `concurrent.interpreters` в 3.14) — дополнительные модели параллелизма.
  **Субинтерпретаторы для нашего стека вычёркиваем:** numpy до сих пор не импортируется в субинтерпретаторах
  (numpy#24755/#27192, single-phase init C-расширений) — с CV-нагрузкой несовместимо.
- **Python 3.12** — наш текущий пин (`>=3.12,<3.13`). **Security-only с апреля 2025** (последний bugfix-бинарь — 3.12.10;
  дальше только source-патчи, актуален 3.12.13). EOL — окт 2028. Актуальные патчи соседних веток: 3.13.14
  (bugfix-окно закрывается 2026-10-07), 3.14.6. **Python 3.15.0 запланирован на 2026-10-01.**

### Вердикт
- **✅ Поднять пин до 3.13** в ближайшую волну (`>=3.13,<3.14`). Причина: 3.12 уже security-only, 3.13 — зрелый и полностью
  покрыт колёсами всех наших зависимостей (PySide6 6.10.3 его поддерживает); риск минимальный. Обновить `target-version` ruff,
  `pythonVersion` pyright, CI-матрицу.
- **Связка Python 3.14 ↔ PySide6 6.11:** PySide6 поддерживает 3.14 только начиная с 6.11 — а наш пин `<6.11` это блокирует
  (6.11.0 вышел 2026-03-23, 6.11.1 — 2026-05-13; Qt 6.11 — не LTS, LTS остаётся 6.8). План: пилот PySide6 6.11 на ветке
  в H2 2026 → bump до 3.14 не позже H1 2027. Задерживаться на 3.13 надолго нет смысла — его bugfix-окно закрывается
  уже 2026-10-07.
- **🧪 Free-threading (3.14t) — только пилот на ветке, НЕ в прод.** Причины держать в пилоте:
  - **Два наших блокера: opencv-python (t-колёс нет; обычные cp314 появились только в 5.0.0.93) и PySide6
    (free-threading у Qt — в стадии research, в трекере совместимости отсутствует).**
    Импорт C-расширения без поддержки нового ABI **молча включает GIL обратно**, и выигрыш испаряется незаметно.
  - Остальная экосистема уже готова (трекер py-free-threading.github.io, июнь 2026): numpy (t-колёса с 2.1),
    PyTorch (с 2.6; актуальный 2.13), Pillow (с 11.0), msgspec (с 0.20, CI-tested), onnxruntime (cp313t/cp314t с 1.27).
- **Что это меняет для нашей multiprocess-архитектуры (перспектива):** как только тяжёлое ушло в нативный код
  с released GIL (OpenCV, numpy, onnxruntime, наш Rust), часть нагрузки можно будет держать **потоками** вместо
  процессов — без межпроцессной сериализации. Но **SHM-архитектура остаётся** для изоляции падений и границ памяти:
  free-threading убирает не необходимость в изоляции, а необходимость платить pickle за параллелизм CPU-bound Python.
  Реалистично: гибрид — процессы как единицы отказоустойчивости, потоки внутри для параллельной обработки.

**Действие:** отдельный план `feat/py313-bump`; free-threading — эксперимент на стенде под метрику, не в релиз.

---

## 3. ROS 2 — честный вердикт

Ключевой вопрос владельца: «мог ли я закрыть всё через ROS 2 вместо своего фреймворка?»
Честный ответ: **переизобретён не ROS 2, а его транспортный слой — осознанно проще и Python-нативно.
Прикладные 2/3 системы пришлось бы писать в любом случае.**

### Что фреймворк уже делает (и что у ROS 2 этому соответствует)

| Наш фреймворк | Аналог в ROS 2 | Комментарий |
|---|---|---|
| Router / каналы / send_message | DDS pub/sub topics | пересекается |
| SharedMemory zero-copy кадры (ADR-019) | loaned messages / iceoryx | у ROS работает с оговорками (POD-типы, не все RMW) |
| supervision, restart_policy, lifecycle | managed nodes + `ros2 launch` | пересекается |
| fencing/epoch (stale-guard) | QoS liveliness/deadline | частично |
| state_store (реактивное дерево, glob-подписки) | — | **нет аналога** |
| chain/DAG-исполнители, registry плагинов, ~50 CV-нод | — | **нет аналога** |
| PySide6 GUI (registers, презентеры) | RViz2 — не продуктовый GUI | **нет аналога** |
| Dict at Boundary + Pydantic v2 | IDL-кодоген `.msg` (жёстче) | наш подход конфиго-центричнее |

Пересечение — примерно **нижняя треть** системы (транспорт + супервизия). Верхние 2/3 (state store, рецепты,
pipeline, vocabulary плагинов, GUI) ROS 2 не закрывает вообще. Июльский аудит
[`docs/audits/2026-07-04_arch-advice-constructor-2026.md`](../audits/2026-07-04_arch-advice-constructor-2026.md)
прямо констатирует: ядро уровня industry-2026, разрыв — в метаданных/супервизии, а не в выборе языка/фреймворка.

### Матрица трёх вариантов

| Вариант | Что даёт | Цена | Вердикт |
|---|---|---|---|
| **A. Полное внедрение ROS 2** | готовый транспорт + экосистема драйверов | переписать оркестрацию под DDS; colcon/ament вместо uv; привязка к конкретной Ubuntu (Lyrical Luth → Ubuntu 26.04); Windows — второсортная платформа (ставится через Pixi/Conda); rclpy медленный на горячем пути → всё равно свой SHM для кадров | **⛔ отклонить** — дублирует уже работающее ядро, ломает Windows-first и uv-деплой |
| **B. Мост-Service `Services/ros2_bridge`** | связь с ROS-железом (манипуляторы, MoveIt 2, Nav2), не трогая ядро | изолированный процесс с rclpy/`zenoh-bridge-ros2dds`; CDR ↔ наш dict; ставится только там, где есть ROS-узлы | **👀 наблюдать** — включать по факту появления ROS-совместимого железа |
| **C. Взять только компоненты** | идеи и отдельные кирпичи без ROS-мира | QoS-словарь (уже в планах как аналог ROS2 QoS), managed-node-хук; **Zenoh** как самостоятельный транспорт для межмашинности | **🧪 частично** — QoS-идеи в фреймворк, Zenoh — отдельным кандидатом (см. §7) |

### Рекомендация
- **Не внедрять ROS 2 целиком.** Причины: Windows у нас первоклассная платформа (у ROS 2 — второсортная,
  через Pixi/Conda); ROS диктует весь деплой (colcon/ament/привязка к дистрибутиву) вместо нашего `uv sync` + `inspector`;
  rclpy медленный на горячем пути — свой SHM всё равно нужен.
- **Держать открытой дверь B (мост).** Если появятся ROS-манипуляторы/сенсоры — `Services/ros2_bridge` как изолированный
  процесс-адаптер. Текущая дельта работает через Modbus (`Services/robot_comm`) и ROS не требует.
- **Заимствовать идеи (C):** формализовать QoS-словарь `{reliability, history_depth, drop_policy, deadline_ms}` в роутере;
  managed-node-подобный lifecycle-хук (уже в дорожной карте конструктора).

> Актуальные ориентиры ROS 2 (2026): **Kilted Kaiju** (standard, EOL конец 2026); **Lyrical Luth** — LTS, вышел 22 мая 2026,
> поддержка до мая 2031, Ubuntu 26.04 / RHEL 10, Windows amd64 (Pixi/Conda), rclpy events-executor до ~10× быстрее.
> На Jetson — Isaac ROS 3.0 (JetPack 6, ROS 2 Humble, NITROS GPU zero-copy). Это подтверждает: полноценный ROS-мир
> тянет за собой свой дистрибутив и деплой — что противоречит нашему кроссплатформенному uv-подходу.

---

## 4. Данные: аналитика и сериализация

### Polars — ✅ внедрить (телеметрия/логи/статистика; pandas в коде не используется — greenfield)
- Текущая версия **1.42.1** (2026-06-30, подтверждено); **2.0 официально не анонсирована** (есть только
  community-запрос roadmap) — закладываться на ветку 1.x. API стабилен по SemVer, ARM64-колёса есть.
- Ядро на Rust, ленивое выполнение, отпускает GIL — на порядок быстрее pandas на агрегации/группировке.
- **Куда:** телеметрия/статистика, обработка логов, отчёты по дефектам — оформить как `Services/analytics` + extra `data`.
- **Факт аудита 2026-07-12:** pandas объявлен в core-deps (и залочен на 3.0.2), но **не импортируется нигде в репо** —
  ни framework, ни prototype, ни Services/Plugins. Мигрировать нечего: pandas удалить из зависимостей, Polars брать
  с чистого листа. (Если pandas когда-нибудь вернётся — помнить: ветка 3.0 ломающая — CoW по умолчанию, str-dtype
  на PyArrow, а релиз 3.0.4 отозван (yanked) из-за сегфолтов, безопасный патч — 3.0.3.)
- **Осторожно на ARM:** редкие проблемы сборки из исходников на экзотических ARM (Snapdragon X) — на RPi/Jetson
  aarch64 колёса `manylinux_2_17_aarch64` есть, ставить через них.

### msgspec — ✅ внедрить (сериализация на границах процессов)
- **0.21.1** (2026-04-12); проект здоров: репозиторий переехал в организацию msgspec/msgspec, каденс стабильный
  (0.20 — ноя 2025, 0.21 — апр 2026), поддержка Python 3.14 + free-threaded (t-колёса с 0.20, CI-tested).
- Быстрее orjson при декодировании в структуры; JSON/MessagePack/YAML/TOML в одном пакете; C-расширение.
- **Куда (уточнено аудитом 2026-07-12):** json'а на межпроцессном пути **нет** — транспорт это `Message.to_dict()`
  → `mp.Queue` (неявный pickle), а кадры идут SHM claim-check'ом мимо очереди (ADR-COMM-003). Поэтому msgspec целим в:
  1. **типизированные payload'ы сообщений** — `msgspec.Struct`, валидация на границе «бесплатно», Dict at Boundary соблюдается;
  2. **socket-канал backend_ctl** (`router_module/channels/socket_channel.py`, NDJSON) — прямая замена `json.dumps/loads`;
  3. **бенч msgspec-vs-pickle** для known-schema сообщений в Queue — менять только по замеру: pickle маленьких
     dict'ов быстр, а тяжёлые данные и так не в очереди благодаря SHM.
- **Оговорка:** pickle через `multiprocessing.Queue` для произвольных Python-объектов не заменяем целиком —
  msgspec для **типизированных payload'ов сообщений**, где схема известна.

### orjson — ✅ внедрить (там, где нужен именно JSON)
- Самый быстрый JSON-сериализатор для Python (Rust). Для конфигов/API/логов в JSON. Лёгкая замена `json`.

### DuckDB — 👀 дополнение/альтернатива Polars для отчётов
- **1.5.4** (2026-06-17), MIT, production/stable; встраиваемый SQL-движок по Parquet/Arrow/CSV без сервера.
- Брать, если аналитике нужнее SQL-интерфейс (ad-hoc отчёты по дефектам, интеграция с BI), чем DataFrame-API Polars.
  Они дополняют друг друга через общий Arrow/Parquet-слой; для отчётной части может заменить SQLite-путь.

### LanceDB / Lance — 👀 наблюдать
- Колоночный формат для ML/датасетов на Rust, встраиваемый (serverless), версионирование, векторный индекс.
- **Куда потенциально:** хранилище датасетов `Services/dataset_gen` / `Services/ml_train` с версионированием.
  Пока файловый пайплайн (+ parquet через pyarrow в `dataset_gen`) покрывает — брать, когда датасеты перерастут файловую схему.

---

## 5. CV / ML-инференс

### ONNX Runtime — ✅ развивать (уже основной backend)
- У нас `Services/ml_inference/backends/onnx_backend.py` — ORT основной. Правильно: кросс-форматный, EP по платформам.
- **Execution Providers по платформам** (главный рычаг ускорения без смены кода):
  - Windows/Linux x86 + NVIDIA → **CUDA EP** / **TensorRT EP**; Intel → **OpenVINO EP**.
  - Raspberry Pi (aarch64) → **XNNPACK EP** (CPU-оптимизация); официальные aarch64 CPU-колёса есть.
  - Jetson Orin → **TensorRT EP** (см. §6); **нет официальных PyPI aarch64 GPU-колёс** — сборка/community-wheel.
- **Действие:** в `ml_inference` довести провайдер-селектор (уже задел под TensorRT/OpenVINO в README) до автодетекта EP
  по платформе; extra `ml-cuda` / `jetson` / `openvino`.

### OpenCV 5 — 🧪 пилот (обновление с 4.x)
- **OpenCV 5.0 вышел**: C++-релиз 2026-06-08 (к CVPR), **`opencv-python` 5.0.0.93 на PyPI с 2026-07-02**
  (наш лок 4.13.0.92 — последний релиз ветки 4.x). Переписанный DNN-движок (ONNX-покрытие 22 % → 80 %),
  встроенная поддержка LLM/VLM, first-class FP16/BF16, ARM **KleidiCV**, RISC-V vector, Intel IPP.
  До 2× на матчисле, 3–4× на ARM для resize/warp. Минимум C++17.
- **Куда:** апгрейд `opencv-python>=4.13` → 5.x. Выигрыш особенно на ARM (KleidiCV) — прямо под RPi/Jetson.
- **Осторожно:** мажор (legacy C-API удалён), возможны breaking changes в API нод; free-threaded-колёс пока нет. Пилот на ветке с прогоном
  всех ~50 CV-плагинов из `Plugins/processing/`.
- **Миграция 4→5 (по официальному wiki):** cv2.ml / Haar / HOG / SURF / G-API уехали в `opencv-contrib-python`;
  выводы `std::vector` теперь 1D-массив (не N×1); `get()` несуществующего свойства → −1; новый DNN-движок в 5.0 —
  CPU-only (GPU лишь через classic-fallback). Нам cv2.dnn не критичен — инференс на ONNX Runtime.

### Rerun SDK — 🧪 пилот (визуальный дебаг мультикамерного пайплайна)
- `pip install rerun-sdk` (Python/Rust/C++), ядро на Rust; актуальная **0.34.1** (2026-07-07), 1.0 нет и roadmap 1.0
  не опубликован — API между 0.x двигается, закладывать мелкие миграции. Единый data-layer: изображения, тензоры,
  облака точек, временные ряды, синхронный realtime-viewer. HuggingFace robotics использует как инструмент дебага.
- **Куда:** **dev-extra `viz-debug`** — отладка мультикамерных источников (`Plugins/sources/camera_service`),
  инспекция кадров/оверлеев/таймингов пайплайна вместо `cv2.imshow`/matplotlib. Заменяет ad-hoc дебаг, не прод-GUI (PySide6 остаётся).
- **Осторожно на embedded:** viewer тяжеловат — на Jetson/RPi гонять как удалённый (SDK пишет, viewer на десктопе).

### Модели детекции: лицензии — ⚠️ зафиксировать политику (ADR)
- **ultralytics (YOLO) — AGPL-3.0** (8.4.x, июль 2026; флагман YOLO26, янв 2026 — NMS-free, edge-first, до −43 %
  CPU-латентности): для проприетарного продукта — только с платной Enterprise-лицензией. В коде **не используется**
  (аудит 2026-07-12; упоминание в CLAUDE.md — устаревшее) — и не вводить без решения по лицензии.
- **Пермиссивные альтернативы (Apache-2.0):** **RF-DETR** (Roboflow, `rfdetr` 1.8.3, ICLR 2026; первый realtime-детектор
  60+ mAP COCO; ⚠️ Apache — только веса Nano…Large, XL/2XL/plus — платная PML 1.0), **D-FINE** (ICLR 2025), **RT-DETR** (Baidu).
- **anomalib 2.5.0** (Intel, Apache-2.0, 2026-05-29) — unsupervised anomaly detection для дефектоскопии (INP-Former,
  GLASS, AnomalyVFM), нативный экспорт в OpenVINO. Прямо наш профиль — дефекты без большой разметки.
  🧪 кандидат в пилот `ml_train`/`ml_inference`.

---

## 6. Аппаратное ускорение по платформам

### Jetson Orin — 🧪 пилот
- **JetPack 6.x:** CUDA 12.2, TensorRT 8.6; **JetPack 7.2:** CUDA 13.2, TensorRT 10.16 (L4T r39.2). Python в образе — 3.10/3.12.
- **TensorRT EP в ORT** предпочтительнее standalone TensorRT API — единый код инференса, TRT только как EP.
- **Грабли:** официальных PyPI `onnxruntime-gpu` aarch64-колёс под конкретный JetPack **нет** — сборка из исходников
  или community-wheel (jetson-ai-lab). Пиновать под версию JetPack стенда; extra `jetson` с git-source колеса.
- Isaac ROS (NITROS) — только если пойдём в ROS-мост (§3, вариант B).

### Intel x86 (промышленные ПК без NVIDIA) — ✅ развивать через OpenVINO EP
- **OpenVINO 2026.2** (поезд релизов жив: 2026.0 фев → 2026.2 июль) — CPU/iGPU/NPU; на типичном стенде без дискретного
  GPU часто быстрее CPU-only ORT. Путь без смены кода — **OpenVINO EP** в ONNX Runtime (`onnxruntime-openvino`,
  отстаёт от core ORT: 1.24.1 при core 1.27 — это нормально). Бонус: anomalib экспортирует в OpenVINO нативно.

### NVIDIA GPU-препроцессинг — 👀 CV-CUDA
- **CV-CUDA** (`cvcuda-cu12`, линия v0.16; CUDA 12/13): 45+ GPU-операторов пре/постобработки, zero-copy пайплайн на GPU
  до/после инференса. Триггер: стенд с NVIDIA GPU + профиль показывает CPU-препроцессинг узким местом.
- **Holoscan SDK 4.x** (NVIDIA, low-latency сенсорные пайплайны, Python-колёса) — смотреть только если Jetson-деплой
  станет основным: дублирует наш chain/DAG-исполнитель.

### Raspberry Pi 5 — 👀 наблюдать (ускоритель)
- CPU-инференс: ORT + **XNNPACK EP**; OpenCV 5 c KleidiCV.
- **AI Kit = Hailo-8L** (13 TOPS, M.2 HAT+): свой тулчейн — ONNX → Hailo Dataflow Compiler → `.hef`, рантайм
  `hailo_platform` / picamera2. **Не drop-in:** отдельная компиляция и квантизация. Брать, если CPU-инференса не хватит;
  оформить как `Services/hailo_inference` с graceful-import.

### GigE Vision / камеры
- **harvesters** — **факт аудита: не импортируется нигде в репо.** Камера Hikvision работает через собственную
  ctypes-обёртку (`Services/hikvision_camera/sdk/bindings.py` → `MvCameraControl.dll`/`.so`), harvesters/genicam
  не задействованы. Проект вялый: релизов нет с 2024-05 (1.4.3), ~105 открытых issues. Вынести из core в extra `gige`
  (включать при появлении реальной GigE/GenICam-камеры) или удалить до появления железа.
- **Aravis** (C/GObject, активен, обновления янв 2026) — альтернатива для Linux/ARM, где нет GenTL-producer вендора;
  через PyGObject. **👀 наблюдать** как запасной путь для GigE на Jetson/RPi.
- **Modbus** (`Services/robot_comm`, `Services/modbus`, pymodbus) — остаётся, ROS не требует.

---

## 7. Транспорт и межмашинность (без ROS)

Если система вырастет в **несколько машин** (стенд + сервер, или несколько инспекционных постов):

- **Zenoh — 👀 наблюдать** (главный кандидат). Rust pub/sub + распределённые запросы, `eclipse-zenoh` **1.9.0**
  (2026-04-10; PyPI-classifier формально ещё Beta), SHM-транспорт, location-transparent. Используется как RMW в ROS 2 (`rmw_zenoh`, tier-1), но **работает и без ROS** —
  можно взять как самостоятельный межпроцессный/межмашинный шину. Кандидат в `Services/zenoh_bus` для распределённого IPC.
- **iceoryx2 — 👀 наблюдать (созрел быстрее ожиданий).** Rust zero-copy IPC (Linux/Windows/macOS), Apache-2.0/MIT.
  **Официальные Python-биндинги уже на PyPI**: пакет `iceoryx2` **0.9.3** (2026-07-08); появились с v0.7 (сен 2025),
  с v0.9 blocking-вызовы отпускают GIL. **v1.0 обещают до конца 2026.** Для **внутримашинного** zero-copy — конкурент
  нашему SHM-слою; триггер пилота: потолок MemoryManager ИЛИ релиз v1.0 (тогда замер против нашего ring-buffer).
- **NATS / gRPC — 👀 по месту.** Если понадобится сетевой обмен командами/событиями с внешними сервисами (Go/облако).

Наш текущий SHM + Queue закрывает одномашинный случай. Эти технологии — **на случай распределённости**, не сейчас.

---

## 8. Свои горячие участки: Rust через PyO3

- **PyO3 0.29.0** (2026-06-11): поддержка **PEP 803 abi3t** (принят 2026-03-30, target Python 3.15) — стабильный ABI
  для free-threaded; **maturin 1.14.1** (2026-06-19) собирает колёса, в т.ч. `cp314t`/abi3t. Расширения thread-safe
  by construction — Rust здесь в лучшем положении, чем C.
- **Критерий «когда выносить в Rust»:** **сначала профилировать.** Выносим, только если:
  (1) участок — доказанное узкое место в чистом Python; (2) в готовых нативных библиотеках (numpy/OpenCV/Polars/ORT)
  этого нет; (3) участок стабилен по API (не переписывается каждую неделю).
- **Кандидаты по нашему коду:** пиксельная пред/постобработка вне OpenCV, хитрая упаковка кадров в SHM, парсинг
  бинарных протоколов оборудования — если профиль покажет, что Python там боттлнек.
- **Быстрая альтернатива без Rust — 👀:** **Numba 0.66** (июль 2026; Python 3.14 — с 0.63, 3.14t — экспериментально
  с 0.65) — JIT для числовых циклов прямо в Python; или **Cython 3.2.8** (free-threading — experimental с 3.1,
  `freethreading_compatible = True`) — когда участок числовой и не хочется тащить Rust-тулчейн. Тактически, по месту.

---

## 9. Тулинг

- **uv / ruff** — оставляем, обновляем (актуальны, Rust, наш стандарт).
- **pyright** — **оставить дефолтом.** `ty` (Astral) — beta с 2025-12-16, текущая 0.0.58 (июль 2026), стабильный API
  не гарантирован, 1.0 «в 2026» без даты. **👀 наблюдать**: перейти, когда выйдет стабильный и покроет наши
  PySide6-паттерны. Скорость (10–100×) соблазнительна, но зрелость pyright для градуального чекинга сейчас важнее.
- **pyrefly (Meta) — новое: 1.0 stable с 2026-05-12** (прод на Instagram ~20M LOC, PyTorch; conformance выше mypy/ty,
  но ниже pyright). Вариант: гонять **вторым чекером в CI** ради скорости, не меняя pyright как эталон.

### Упаковка/деплой (пропуск первой версии документа — добавлено 2026-07-12)
- **Windows-стенд:** **Nuitka 4.1.3** standalone — ⚠️ **лицензия сменилась на AGPLv3 + исключение для собираемых
  бинарей** (собранный продукт остаётся проприетарным, но условия показать юристу; commercial-издание — IP-protection,
  container builds). Альтернатива без юр-вопросов: **PyInstaller 6.21** (Python 3.8–3.15).
- **Jetson / RPi / Linux:** uv-деплой (`uv sync --frozen` + python-build-standalone) или **PyApp** (Rust-лаунчер поверх
  uv/standalone-python). Onefile-магия на aarch64 наименее зрелая — не строить на ней деплой.

---

## 10. Платформенная матрица

| Технология | Windows x86 | Linux x86 | Raspberry Pi (aarch64) | Jetson Orin (aarch64) |
|---|---|---|---|---|
| Python 3.13 | ✅ | ✅ | ✅ | ✅ (в образе часто 3.10/3.12 — проверить) |
| Polars | ✅ | ✅ | ✅ (manylinux aarch64) | ✅ |
| msgspec / orjson | ✅ | ✅ | ✅ | ✅ |
| OpenCV 5 | ✅ | ✅ | ✅ (+KleidiCV) | ✅ (+KleidiCV) |
| ONNX Runtime CPU/XNNPACK | ✅ | ✅ | ✅ | ✅ |
| ONNX Runtime CUDA/TensorRT EP | ✅ (NVIDIA) | ✅ (NVIDIA) | — | ⚠️ сборка/community-wheel |
| ONNX Runtime OpenVINO EP (Intel CPU/iGPU/NPU) | ✅ | ✅ | — | — |
| Rerun SDK | ✅ | ✅ | ⚠️ SDK-only (viewer удалённо) | ⚠️ SDK-only |
| harvesters (GigE) | ✅ | ✅ | ⚠️ зависит от GenTL-producer | ⚠️ зависит от GenTL-producer |
| Hailo-8L | — | — | ✅ (AI Kit) | — |
| PyO3-расширения | ✅ | ✅ | ✅ | ✅ |

---

## 11. Аудит pyproject (2026-07-12) и предлагаемые изменения

### Аудит: расхождения кода и зависимостей

Инвентаризация импортов по framework / prototype / Services / Plugins (2026-07-12):

| Категория | Пакеты | Действие |
|---|---|---|
| **Мёртвые core-deps** (0 импортов в репо) | pandas (залочен 3.0.2!), matplotlib, plotly, seaborn, pygame, environs, QDarkStyle, NodeGraphQt (git-форк C3RV1 мёртв с 2023-01; в коде свой node-editor на QGraphicsScene), Qt.py (транзитивка NodeGraphQt), harvesters (см. §6) | удалить из `[project.dependencies]` + запись NodeGraphQt из `[tool.uv.sources]` |
| **Используется, но не объявлено** | pyarrow (lazy, `Services/dataset_gen/export.py` — parquet; актуальная 25.0.0), scikit-image (lazy + numpy-fallback, `Plugins/.../strokes_to_points`) | pyarrow → extra `data`; skimage → extra или оставить fallback-путь |
| **Незащищённый импорт** | `import torch` на уровне модуля в вендоренном TEED (`Plugins/processing/edge_detection/_vendor/teed/`) — сработает при загрузке ноды без extra `ml-torch` | обернуть graceful-import или задокументировать требование |
| **Устаревшие упоминания в доках** | Ultralytics и Ollama в CLAUDE.md («Стек»); там же «PyTorch 2.11» (в локе 2.13.0) | поправить CLAUDE.md |

### Предлагаемые изменения (набросок, внедрять отдельными планами)

> Это эскиз, а не готовый дифф. Каждый пункт — отдельный план с тестами. **В core не добавляем тяжёлое.**

```toml
# requires-python = ">=3.13,<3.14"   # волна 1: bump с 3.12; связка 3.14 + PySide6 6.11 — следующим шагом (§2)

[project.optional-dependencies]
# Аналитика на Rust-ядре (Services/analytics)
data = [
    "polars>=1.42",
    "msgspec>=0.21",
    "orjson>=3.11",
    "pyarrow>=25",   # уже используется lazy в Services/dataset_gen/export.py (parquet-экспорт)
]
# Визуальный дебаг пайплайна (dev-only)
viz-debug = [
    "rerun-sdk>=0.32",
]
# Инференс на NVIDIA (x86 + Jetson через свой EP)
ml-cuda = [
    "onnxruntime-gpu>=1.27",   # выходит синхронно с core ORT (1.27.0 — 2026-06-15); на Jetson — git-source колесо под JetPack
]
# Intel-ускорение (стенды без дискретного GPU — см. §6)
ml-openvino = [
    "onnxruntime-openvino>=1.24",  # отстаёт от core ORT (1.24.1 — фев 2026) — нормальный лаг этого пакета
]
# Raspberry Pi AI Kit
hailo = [
    # hailo_platform ставится из вендорского индекса, не PyPI — см. Services/hailo_inference/README
]

# Не в core: opencv-python остаётся 4.13 до пилота OpenCV 5 на ветке.
```

Non-PyPI/платформенное — через `[tool.uv.sources]` (git+sha), как сделано для `qt-mcp`. Запись `NodeGraphQt`
удаляется вместе с самой зависимостью (форк мёртв с 2023-01, в коде — свой node-editor на QGraphicsScene).

---

## 12. Дорожная карта волнами и критерии пересмотра

### Волна 1 — 2026 H2 (низкий риск, высокая отдача)
0. **Чистка pyproject** (`chore/deps-cleanup`) — удалить 10 мёртвых core-deps (§11), добавить pyarrow в extra `data`,
   убрать NodeGraphQt из `[tool.uv.sources]`; заодно поправить «Стек» в CLAUDE.md (Ultralytics/Ollama/версии).
1. **Bump Python 3.12 → 3.13** (`feat/py313-bump`) — обновить пин, ruff/pyright target, CI.
2. **`Services/analytics` на Polars** + extra `data` (Polars/msgspec/orjson/pyarrow) — начать с телеметрии/статистики.
3. **msgspec на границах** — типизированные payload'ы + socket-канал backend_ctl; бенч msgspec-vs-pickle для Queue (§4).
4. **ORT: автодетект EP по платформе** в `ml_inference` (CUDA/TensorRT/OpenVINO/XNNPACK).
5. **Rerun как dev-extra `viz-debug`** — дебаг мультикамерного источника.
6. **Пилот PySide6 6.11** на ветке — снять пин `<6.11`, прогнать pytest-qt/GUI-смоуки (пререквизит Python 3.14, §2).
7. **ADR по лицензиям моделей** — без AGPL: RF-DETR (Apache-веса) / D-FINE / anomalib; ultralytics только с Enterprise (§5).

### Волна 2 — конец 2026 → 2027 (мажоры и железо)
8. **Пилот OpenCV 5** на ветке (колёса на PyPI уже с 2026-07-02 — можно не ждать 2027) — прогон всех ~50 CV-плагинов,
   чек-лист миграции из §5, замер ARM-выигрыша (KleidiCV).
9. **Bump Python 3.14 + PySide6 6.11 в main** — после пилотов, не позже H1 2027 (§2).
10. **Пилот anomalib** (unsupervised-дефекты) в `ml_train`/`ml_inference` — с экспортом в ONNX/OpenVINO.
11. **TensorRT EP на Jetson** — `Services`-обёртка + git-source колесо под JetPack стенда.
12. **PyO3-эксперимент** на доказанном профилем узком месте.

### Наблюдение (перевод в «пилот» по триггеру)
- **Free-threading (3.14t/3.15t):** триггер — t-колёса у **opencv-python и PySide6/Qt** (numpy/PyTorch/ORT/msgspec
  уже готовы, §2). Тогда пилот «процессы → потоки» для CPU-bound Python.
- **Zenoh:** триггер — вторая машина в системе (межмашинная распределённость).
- **iceoryx2:** триггер — релиз v1.0 (обещан до конца 2026) ИЛИ потолок нашего SHM/MemoryManager — тогда бенч
  против своего ring-buffer (Python-биндинги уже на PyPI, §7).
- **CV-CUDA:** триггер — NVIDIA-стенд + профиль упирается в CPU-препроцессинг (§6).
- **Субинтерпретаторы (PEP 734):** сняты с наблюдения — numpy в субинтерпретаторах не работает (§2).
- **ROS 2 мост (`Services/ros2_bridge`):** триггер — закупка ROS-совместимого манипулятора/сенсора (нужен MoveIt/Nav2).
- **Hailo-8L:** триггер — CPU-инференса RPi перестаёт хватать по FPS.
- **LanceDB:** триггер — датасеты `ml_train` перерастают файловую схему (нужно версионирование/векторный поиск).
- **ty:** триггер — стабильный 1.0 + покрытие наших PySide6-паттернов.

---

## Источники (проверено 2026-07-12)

- Python 3.14 / PEP 779 free-threading — [peps.python.org/pep-0779](https://peps.python.org/pep-0779/), [Phoronix](https://www.phoronix.com/news/Python-3.14), [py-free-threading.github.io](https://py-free-threading.github.io/tracking/)
- Free-threaded колёса (Pillow 12.3, PyTorch 2.10, OpenCV статус) — [py-free-threading tracking](https://py-free-threading.github.io/tracking/), [opencv-python#1155](https://github.com/opencv/opencv-python/issues/1155)
- ty / ruff / uv — [pydevtools ty-beta](https://pydevtools.com/blog/ty-beta/), [astral.sh/blog](https://astral.sh/blog), [github.com/astral-sh/ty](https://github.com/astral-sh/ty)
- Polars — [pypi.org/project/polars](https://pypi.org/project/polars/), [Polars 2.0 roadmap #26148](https://github.com/pola-rs/polars/issues/26148)
- msgspec / orjson — [github.com/msgspec/msgspec](https://github.com/msgspec/msgspec), [msgspec.dev](https://msgspec.dev/)
- OpenCV 5 — [opencv.org/opencv-5](https://opencv.org/opencv-5/), [Phoronix OpenCV 5.0](https://www.phoronix.com/news/OpenCV-5.0-Released), [CNX Software](https://www.cnx-software.com/2026/06/10/opencv-5-release-new-dnn-engine-with-enhanced-onnx-and-llm-vlm-support-intel-arm-and-risc-v-hardware-optimizations/)
- ONNX Runtime / Jetson — [ORT build EPs](https://onnxruntime.ai/docs/build/eps.html), [Torch-TensorRT JetPack](https://docs.pytorch.org/TensorRT/getting_started/jetpack.html), [NVIDIA forums onnxruntime-gpu Jetson](https://forums.developer.nvidia.com/t/jetpack-6-0-onnxruntime-gpu/307053)
- Raspberry Pi AI Kit / Hailo — [raspberrypi.com/products/ai-kit](https://www.raspberrypi.com/products/ai-kit/), [hailo-rpi5-examples](https://github.com/hailo-ai/hailo-rpi5-examples)
- Rerun — [rerun.io](https://rerun.io/), [github.com/rerun-io/rerun](https://github.com/rerun-io/rerun)
- ROS 2 Kilted / Lyrical Luth — [Kilted release](https://www.openrobotics.org/blog/2025/5/23/ros-2-kilted-kaiju-released), [Lyrical Luth timeline](https://docs.ros.org/en/jazzy/Releases/lyrical/release-timeline.html), [endoflife.date/ros-2](https://endoflife.date/ros-2)
- Zenoh / iceoryx2 / Isaac ROS — [rmw_zenoh](https://github.com/ros2/rmw_zenoh), [rmw_iceoryx2](https://github.com/ekxide/rmw_iceoryx2), [Isaac ROS releases](https://nvidia-isaac-ros.github.io/releases/index.html)
- PyO3 / maturin — [pyo3.rs free-threading](https://pyo3.rs/main/free-threading.html), [maturin releases](https://github.com/pyo3/maturin/releases)
- pyrefly 1.0 / ty — [pyrefly 1.0.0](https://github.com/facebook/pyrefly/releases/tag/1.0.0), [astral.sh/blog/ty](https://astral.sh/blog/ty)
- iceoryx2 Python-биндинги — [pypi.org/project/iceoryx2](https://pypi.org/project/iceoryx2/), [ekxide blog 0.9](https://ekxide.io/blog/iceoryx2-0.9-release)
- Лицензии моделей — [ultralytics license](https://www.ultralytics.com/license), [roboflow/rf-detr](https://github.com/roboflow/rf-detr), [anomalib](https://github.com/open-edge-platform/anomalib)
- OpenVINO / CV-CUDA / Nuitka-лицензия — [docs.openvino.ai](https://docs.openvino.ai), [developer.nvidia.com/cv-cuda](https://developer.nvidia.com/cv-cuda), [Nuitka LICENSE](https://github.com/Nuitka/Nuitka/blob/main/LICENSE.txt)
- **Аудит репо 2026-07-12:** инвентаризация импортов framework/prototype/Services/Plugins + сверка uv.lock ↔ PyPI.
  Ключевые находки: 10 неиспользуемых core-deps; pyarrow/scikit-image используются без объявления; json на IPC-пути
  отсутствует (транспорт — pickle-в-Queue + SHM claim-check); PySide6 6.11 отсечён пином; Hikvision — ctypes, не harvesters.
