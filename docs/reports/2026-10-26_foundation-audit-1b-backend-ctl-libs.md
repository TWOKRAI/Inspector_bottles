# Аудит фундамента — опись 1б: backend_ctl и библиотеки

Дата: 2026-10-26. Полоса А, `inspector-bottles-1a`. HEAD `f63f68403`. Соседние файлы — [Services](2026-10-26_foundation-audit-1b-services.md) и [опись шага 1](2026-10-26_foundation-audit-inventory.md). Только факты, вердикт за CTO.

Источники: 3 агента Explore (Haiku: каталог `backend_ctl`, библиотеки; Sonnet: матрица управляемости). Сверено лидом по коду: отсутствие читателя флагов `FW_*` и инструментов `recipe.*` / `topology.*` в `backend_ctl`, число инструментов, дрейф `STATUS.md`, неиспользуемые зависимости. Тесты не запускались, бэкенд не поднимался.

## 1. backend_ctl — что это и как подключён

- Внешний клиент к живому бэкенду: TCP, newline-JSON. Серверная сторона — `SocketChannel` в ProcessManager (`process_manager_module/process/backend_ctl_endpoint.py:84`, канал `backend_ctl` :25; поднимается в `process_manager_process.py:317–319` при `BACKEND_CTL=1`). Клиент — `transport.py:51` поверх `router_module/channels/socket_client.py:154`.
- Код без `probes/`: 11 805 строк (`driver.py` 2 658, `mcp_tools.py` 1 667, `recorder.py` 949, `protocol.py` 895, `events.py` 690, …). `probes/` — 11 904 строки, тесты — 21 165.
- Framework `backend_ctl` не импортирует. `backend_ctl` импортирует 9 мест framework, включая внутренности: `channel_routing_module.core.channel_routing_manager`, `channel_routing_module.observability.observability_store`, `process_manager_module.launcher.system_launcher`. Из прототипа импортирует 3 места в `harness.py:103–109`, внутри фабрики.
- **MCP-инструментов 53** (`ToolSpec(` в `mcp_tools.py`, сверено). По классам безопасности (`TOOL_SAFETY`, `mcp_tools.py:1507–1603`): read 30, subscribe 9, write 10, escalated 4.
- `record_start` и `record_dump` отнесены к классу read (`mcp_tools.py:1363`), хотя пишут файлы.

**Дрейф документа (сверено):** `backend_ctl/STATUS.md:28` — «47 инструментов», в коде 53; `STATUS.md:18` — `driver.py` «сейчас 1270», в коде 2 658 строк.

**Долг в `backend_ctl`:**
- маркеров `ponytail:` / TODO нет;
- 26 проглоченных `except`, в основном на teardown и в аудите;
- 9 `time.sleep` в коде (в probes — 125), среди них опрос после рестарта `driver.py:1270` и фиксированная пауза `driver.py:1540`;
- back-compat шимы `driver.py:61, 90, 1415–1421`;
- два независимых цикла готовности: `harness.py:440–457` и `mcp_driver_session.py:358–368`;
- для offline-replay свои реализации `system_overview` / `state_get` / `await_condition` (`recorder.py:787–855`) рядом с live-методами.

## 2. Матрица управляемости (третья линза CTO)

«Покрыто» значит, что для команды есть выделенный инструмент или метод драйвера. Любую команду можно послать через `send_command` / `system_command`, но в режимах `--read-only` / `--disable-destructive` `send_command` пропускает только префиксы `introspect.` и `state.get` (`mcp_tools.py:1579, 1641`).

**Команды framework (по исходникам): 102. Покрыто 32, не покрыто 70.**

| группа | всего | покрыто | что не покрыто |
|---|---|---|---|
| introspect.* | 11 | 10 | `introspect.executors` |
| процессы PM (`process.*`, `system.*`, `supervision.status`) | 12 | 3 (`process.restart`, `system.shutdown`, `supervision.status`) | `process.list/create/start/stop/pause/resume/status`, `system.stats`, `process.command` |
| топология и провода (`topology.*`, `wire.*`) | 8 | 0 | `topology.apply/get/diff`, `wire.setup/teardown/status`, `wire.configure/deconfigure` (`driver.py:826`: «обёртки нет») |
| рецепты (`recipe.*`) | 6 | 0 | `recipe.list/get/validate/save/delete/activate` |
| воркеры (`worker.*`) | 9 | 0 | create/remove/update/restart/start/stop/drain/pause_all/resume_all |
| state.* | 8 | 4 | `state.set/merge/delete`, `state.unsubscribe_all` |
| наблюдаемость (config, telemetry, sink, tail, persist) | 16 | 11 | `observability.persist`, `sink.tail` (2), алиасы `observability.sink.*` (2) |
| остальное: `service.*` 5, статистика 5, консоль 5, `frames.*` 3, `ui.tap.*` 3, health/diag 4, routing/relay 4, `catalog.plugins`, `register_update`, `set_enabled` | 32 | 4 (`register_update`, `ui.tap.*`) | `service.list/status/start/stop/restart`, `get_metrics`, `health.status`, `routing.refresh` и др. |

**Ключевое состояние: 15 пунктов. Видно 8, частично 2, не видно 5.**

| состояние | видно через backend_ctl | где |
|---|---|---|
| `incarnation`, `instance_restarts`, `restart_count` монитора | да | `supervision_status` → `processes.<p>.*` |
| `restart_count` воркера | да, сырым полем | `get_status` → `workers.<name>.restart_count` |
| глубины очередей, дропы роутера, потери логгера, `errors_to_floor` | да | `introspect_queues`, `introspect_router_stats`, `introspect_observability` |
| топология | частично (список процессов из `capabilities`) | живого `topology.get` нет |
| готовность процессов | частично (статус в дереве состояния) | событие готовности не читается |
| **своё `stop_event` процесса и общее `system_stop_event`** | **нет** | ни одна команда не отдаёт `is_set()` |
| **значения и источники 17 флагов `FW_*`** | **нет** (сверено: `FW_` в коде `backend_ctl` — 0) | есть только boot-лог PM (`process_manager_process.py:244–266`), команды-читателя нет |
| **активный рецепт** | **нет выделенного пути** (сверено: `recipe.*` в коде `backend_ctl` — 0) | только `send_command("ProcessManager", "recipe.list")`, в read-only закрыт |

**Обходы (инструменты не через команды framework):**
- `history_query` читает sqlite напрямую (`driver.py:1015`, `mode=ro`);
- `harness` использует psutil и `os.kill` для запуска и остановки системы (`harness.py:148–302`);
- `record_*`, `events*`, `await_condition`, `telemetry_snapshot/history` работают локально на клиенте.

Память `project_backend_ctl_socket_bypasses_mw.md` («сокет мимо middleware») подтверждена частично. `_recv_mw` применяется только в `receive()` (`router_manager.py:1471`), а канал `backend_ctl` не проходит фильтр `_selected_channels` (:1582). Но `SocketBridgeAdapter.on_inbound` → `router.request` → `send()` кладёт сообщение в очередь адресата, где `_recv_mw` может отработать. Живьём не проверялось.

## 3. Библиотеки

### 3.1 Сторонние (`pyproject.toml` / `uv.lock`)

**Объявлены, но не импортируются нигде в репозитории (сверено `git grep` по всем `*.py`, включая тесты и скрипты):** NodeGraphQt, pandas, plotly, seaborn, pygame, harvesters (вместе с транзитивным genicam), environs, QDarkStyle, pydantic-settings. Отчёт агента добавляет Qt.py, greenlet, setuptools и `pytest-asyncio`, причём последний стоит в основной группе зависимостей; их я не сверял. Из extra `ml`: `onnx` — 0 импортов в коде. `matplotlib` используется только в `Services/line_sim/tools/build_stand_assets.py:77`.

**Импортируются, но не объявлены:**

| пакет | где | защищён `ImportError` |
|---|---|---|
| segno | `Services/phone_gateway/qr.py:14`, `Services/code_reader/tools/qr_test_sheet.py:26` | в `qr.py` внутри try (except не прочитан); в tools — нет |
| pyarrow | `Services/dataset_gen/export.py:170` | да |
| scikit-image | `Plugins/processing/strokes_to_points/geometry.py:64` | `except Exception` |
| mediapipe | `Plugins/processing/segmentation/plugin.py:101` | да |
| транзитивные: typing_extensions, pydantic_core, anyio, starlette, uvicorn | framework, прототип, `backend_ctl/mcp_server_sdk.py:305–357` | частично |

**Dev-группа нужна в рантайме:**
- `aiosqlite` — URL `sqlite+aiosqlite` в `Services/sql/adapters/async_adapter.py:25`;
- `qt-mcp` — `multiprocess_prototype/frontend/app.py:142` при `QT_MCP_PROBE=1`, защищён.

**Расхождения со стеком (`.claude/modes/_stack.md`, «Toolchain»):**
- в стеке «PyTorch 2.11», в lock — torch 2.13.0;
- «Ultralytics YOLO» в стеке есть, а в pyproject, lock и коде — 0;
- «PostgreSQL»: драйверов `psycopg` / `asyncpg` нет ни в pyproject, ни в lock;
- комментарий `pyproject.toml:107–108` «pymodbus тянет pyserial» — pyserial в lock нет.

**Верхних границ версий нет** у pandas (`>=2.2`, lock 3.0.2), pydantic и многих других. Есть только у numpy, pyside6, opencv, mcp, opentelemetry.

PySide6 во framework — только `frontend_module` (8 файлов), вне него 0. В Services Qt — 5 файлов: `hikvision_camera/sdk_app`, `robot_comm/gui`, `robot_comm/server/sim_monitor.py`, `sim_robot.py:541`. В Plugins — 0.

### 3.2 Стандартная библиотека: опора на приватные поля CPython

| файл:строка | что читается | дата |
|---|---|---|
| shared_resources_module/queues/core/reader_gone.py:36 | `multiprocessing.queues._sentinel` | 2026-09-24 · 83d0d7ea2 |
| reader_gone.py:92–93 | `q._notempty`, `q._buffer` (буфер feeder) | 2026-09-24 |
| reader_gone.py:132, 156 | `q._thread`, `q._thread.is_alive()` | 2026-09-24 |
| process_module/commands/builtin_commands.py:1382 | `getattr(q, "_maxsize", None)` (там же `ponytail:` :1377) | 2026-09-30 · 7a137db13 |
| builtin_commands.py:1375 | `multiprocessing.synchronize.SEM_VALUE_MAX` | — |
| shared_resources_module/memory/reader/shm_frame_reader.py:142 | `shm._name` + `multiprocessing.resource_tracker.unregister` | 2026-09-24 · 6d9907a95 |
| Services/hikvision_camera/sdk/bindings.py:76 | `ctypes.WinDLL.__init__.__code__.co_varnames` | 2026-05-10 |

Чем опасно: эти поля не входят в публичный API Python и могут измениться в 3.13 или 3.14 без предупреждения. На них держатся отпуск очередей при выходе (C-36, C-50) и отчёт об ёмкости очереди.

Платформенные ветки (`sys.platform` / `os.name`): во framework 10, главные — `process_runner.py:165, 346`, `buffers/cleanup.py:39, 43`, `shm_frame_reader.py:139`, `cpu_clock.py:26`.

### 3.3 Нативный код

| файл:строка | библиотека | как |
|---|---|---|
| Services/hikvision_camera/sdk/bindings.py:77, 97 | MvCameraControl.dll / libMvCameraControl.so | `ctypes.WinDLL` / `CDLL` |
| Services/code_reader/sdk/loader.py:69 | MvCodeReaderCtrl.dll (каталог из env `MVCR_SDK_DIR`) | `ctypes.WinDLL` |
| console_module/platforms/windows.py:33–96; process_module/heartbeat/cpu_clock.py:47; process_manager_module/launcher/process_tree_guard.py:123 | kernel32, user32 | `ctypes` |
| Services/ml_inference/backends/torch_backend.py:51, onnx_backend.py:32–37 | CUDA (torch / onnxruntime providers) | тихий fallback на CPU |

Бинарников (`.dll/.so/.pyd/.cti/.onnx/.pt`) в git нет. GenTL (`.cti`) в коде не используется, хотя `harvesters` объявлен.

## Что я оставил открытым / ненадёжным

- Счёт «102 команды» сделан по исходникам, а не по живому `capabilities`. Часть команд регистрируется только при включённой консоли или указанном манифесте. Динамические команды плагинов (`cmd_*`) не считались.
- Не проверено, лежит ли имя активного рецепта в дереве состояния (тогда оно читается через `state_get`). «Нет» в матрице означает «нет выделенного пути».
- Неиспользуемость Qt.py, greenlet, setuptools и pytest-asyncio я не сверял. Qt.py и greenlet могут быть нужны транзитивно, хотя объявлены прямо.
- Список stdlib агент составил вручную, без `sys.stdlib_module_names`. Возможны ошибки в обе стороны.
- Защиту `ImportError` у psutil, torchvision и части Plugins не проверяли.
