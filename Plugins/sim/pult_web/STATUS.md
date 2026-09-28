# Plugins/sim/pult_web — STATUS

**Состояние: сделано (Task 1.2h плана `line-sim-layer-editor` — HTML-редактор слоёв).**

**Обновлено:** 2026-09-28 — Task 1.2h, ветка `feat/line-sim-layer-editor`.

| Что | Состояние |
|---|---|
| `plugin.py` — `PultWebPlugin` | есть: `configure`/`start`/`shutdown`, HTTP API (`GET /`, `GET /api/status`, `POST /api/run|stop|jog|calibrate`), форвард через `DeviceHubClient` |
| `GET /api/journal` / `POST /api/journal/reset` (Task 5.1) | есть: форвард `sim_robot.journal`/`sim_robot.journal_reset` как есть; страница — блок «Задания от прототипа», опрос 1 с, без логики подсчёта; 2/2 REDS `tests/test_pult_journal_routes.py` зелёные |
| Блок «Что дошло до робота» (line-sim Task 6.2) | есть: поле `wire` ответа журнала, свежие сверху, «×N», журнал недоступен → «журнал недоступен»; `tests/test_pult_wire.py` — 3 авторских, `tests/test_acceptance_wire.py` — независимого тестера |
| `GET /api/truth` / `POST /api/truth/reset` (Task 5.3a) | есть: второй `DeviceHubClient(target_process=scene_process)`, форвард `truth.status`/`truth.reset` как есть; страница — блок «Правда сцены», опрос 1 с; `tests/test_acceptance_5_3a.py` зелёный целиком |
| Занятый порт | есть: `_PultHTTPServer.__init__` биндит синхронно, `OSError` → `report_error`, `state="error"`, процесс живёт |
| bad_json/404/413 | есть: три отказа ДО обращения к `robot`, `robot` не вызывается ни разу |
| `status: "error"` от `robot` → 504 | есть |
| Accept-backlog 20 конкурентных запросов | есть: `request_queue_size = 32` (дефолт stdlib 5 ронял часть соединений на TCP-уровне, замерено) |
| `shutdown()` при живом сервере, даже с реальным медленным запросом | есть: `join(timeout=5.0)`, не виснет (hazard-тест с daemon-потоком + join-дедлайном, реально висящий двойник 3 с) |
| Медленный `robot` не блокирует соседний `GET /` | есть: `ThreadingHTTPServer` — поток на соединение |
| Localhost-страж (`Host` не 127.0.0.1/localhost:port) | есть: 403 на `GET`/`POST`, DNS-rebinding отбит |
| Content-Type-страж на `POST` (не `application/json`) | есть: 415 до чтения тела, двойник не вызван |
| Страница: `pollStatus` на отказ (`ok: false`/не-2xx) | есть: «robot не отвечает», не `undefined`-поля |
| Страница: `jogStop` без активного jog | есть: no-op, не шлёт лишний `/api/stop` чужой ленте |
| Страница: повторный `pointerdown` во время jog | есть: игнорируется, осиротевшего таймера нет |
| Страница: порядок jog→stop | есть: `jogStop` дожидается промиса последнего `/api/jog` |
| `GET /api/preset` / `POST /api/preset/commit|preview` (Task 1.2h) | есть: третий `DeviceHubClient(target_process=layers_process)`, отдельная таблица `_PRESET_ROUTES` под `_SCENE_COMMAND_BY_PATH`, потолок тела `/api/preset/commit` — 256 КБ, таймаут `/api/preset/preview` — 5.0 с; `_dispatch()` теперь читает `code` из ответа команды (`invalid`/`bad_request`/`overloaded`→400, `conflict`→409, `io_error`→500, код вне таблицы→400, без `code`→504 как раньше) |
| Раздел «Редактор слоёв» на странице (Task 1.2h) | есть: `_PRESET_SECTION`/`_PRESET_SCRIPT`, форма из `preset.get` по типу значения поля, `offset_px`→`layer<i>_offset_x/_y`, превью в `#presetPreviewImg`, «Сохранить» с `base_rev`, конфликт не стирает правку, undo — стек в браузере |
| Тесты | `tests/test_pult_web.py` — 7 слепых приёмочных независимого тестера (в worktree на коммите 2.3a); `tests/test_acceptance_5_3a.py` — 11 слепых приёмочных (§1 маршруты + §2 страница, Task 5.3a, в worktree на коммите 6f94201f) + тесты лида после break-injection и ревью (повторный опрос после сброса, 200 со `status` не `ok`, переход ok → отказ, разметка раздела, отрицательный `Content-Length`, подпись `scene_error`); `tests/test_pult_web_hazards.py` — 14 авторских (12 из 2.3b/5.1 + 2 новых Task 5.3a: медленная правда не блокирует status/journal, конкурентный сброс+опрос правды доходит ровно N раз каждый); `tests/test_acceptance_6_1.py` — 16 слепых приёмочных Task 6.1b, 4 из них обновлены здесь под новую форму `_dispatch()` (Находка 2, Task 1.2h — код ошибки теперь виден в HTTP-теле, было документировано этим же файлом как «правит соседняя сессия 1.2h»); `tests/test_acceptance_1_2h_preset.py` — 10 слепых приёмочных независимого тестера (H1-H8, в worktree на коммите 0c7140d0, ДО реализации); `tests/test_hazards_1_2h_preset.py` — 6 авторских (неизвестный `code`→400, `preset.commit` без `code`→504, точная граница потолка тела маршрута, `layers_process` не захардкожен, старые маршруты не получают чужой таймаут, Content-Type-страж действует и на новых маршрутах) |

## Долг / открытые вопросы

- **Страница проверяется через `node:vm`, не браузером** — семантика
  pointer-событий на тач-экране и порядок `blur`/`visibilitychange` при
  закрытии вкладки не проверены; без `node` JS-тесты пропускаются (`skipif`).
- **Медленный robot (> ~400 мс на команду) — лента дёргается при удержании
  jog** (подкачка реже `jog_timeout_ms`); сбой в безопасную сторону. Лечится
  досылкой пропущенного тика сразу после ответа — не делали (ревью 2.3b,
  итерация 2, наблюдение A).
- **`no_receive_pump` в первые мгновения после старта процесса `pult`** —
  `router.request` до первого приёмного цикла отдаёт эту ошибку, первые
  запросы страницы могут получить 504. Задокументировано в README, не
  устраняется (грейс сам проходит).
- **`shutdown()` не закрывает уже открытые клиентские соединения** — то же
  известное ограничение, что у `mjpeg_sink` (см. его `STATUS.md`); поток
  конкретного соединения — daemon, процесс не блокирует.
- **Живая приёмка — ведущим, 2026-09-22:** `apps/line_sim/tests` 29/29 при
  `LINE_SIM_LIVE=1`, инъекция B6 (пульт адресует `camera`) → RED (504).
- **Форма ответа `router.request` снята живьём:** `{success, result}` на
  верхнем уровне (конверт `reply_to_request`). Старый `_normalize_response`
  её НЕ разбирал — `/api/status` отдавал голое `{"status": "ok"}`, поля
  терялись. Исправлено в `DeviceHubClient` (коммит «fix(device_hub): …
  result с верхнего уровня»), тест с настоящим клиентом —
  `Plugins/hub/device_hub/tests/test_reply_envelope_acceptance.py`.
- **Редактор слоёв (Task 1.2h) — форма без Pydantic-схемы.** `null`/вложенные
  объекты (`augment`, `color_rgb`) и произвольные массивы в полях слоя
  рендерятся только для чтения (JSON-текстом) — правка таких полей мышью
  недоступна, пока `preset.get` не начнёт отдавать `model_json_schema()`
  (см. README, «Редактор слоёв»). Разбиение поля `<база>_px` на `_x`/`_y` —
  единственная жёстко зашитая эвристика (по имени поля, не по схеме); поле
  с другим суффиксом, но той же формой [x, y], под неё не попадёт.
- **Не проверено живьём.** Все проверки 1.2h — на двойнике `DeviceHubClient`
  (H1-H8 + 6 авторских); против настоящих `scene_source`/`layer_preview`
  (Task 1.2a) прогона не было — это работа лида (стенд/backend_ctl).
- **`docs/scripts` doc-size-guard:** раздел «Страница» README перевалил за
  мягкий бюджет 8 КБ (~8.5 КБ после этой задачи) — не блокирует, но раздел
  стоило бы разбить на подстраницы; не сделано здесь (пришлось бы трогать
  чужие подразделы «Правда сцены»/«Сцена», вне FILES этой задачи).
