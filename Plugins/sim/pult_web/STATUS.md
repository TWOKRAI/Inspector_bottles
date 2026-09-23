# Plugins/sim/pult_web — STATUS

**Состояние: сделано (Task 5.3a плана line-sim — правда сцены на пульте).**

**Обновлено:** 2026-09-23 — Task 5.3a, ветка `feat/line-sim-5.3a`.

| Что | Состояние |
|---|---|
| `plugin.py` — `PultWebPlugin` | есть: `configure`/`start`/`shutdown`, HTTP API (`GET /`, `GET /api/status`, `POST /api/run|stop|jog|calibrate`), форвард через `DeviceHubClient` |
| `GET /api/journal` / `POST /api/journal/reset` (Task 5.1) | есть: форвард `sim_robot.journal`/`sim_robot.journal_reset` как есть; страница — блок «Задания от прототипа», опрос 1 с, без логики подсчёта; 2/2 REDS `tests/test_pult_journal_routes.py` зелёные |
| `GET /api/truth` / `POST /api/truth/reset` (Task 5.3a) | есть: второй `DeviceHubClient(target_process=scene_process)`, форвард `truth.status`/`truth.reset` как есть; страница — блок «Правда сцены», опрос 1 с; 11/11 REDS `tests/test_acceptance_5_3a.py` зелёные |
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
| Тесты | `tests/test_pult_web.py` — 7 слепых приёмочных независимого тестера (в worktree на коммите 2.3a); `tests/test_acceptance_5_3a.py` — 11 слепых приёмочных (§1 маршруты + §2 страница, Task 5.3a, в worktree на коммите 6f94201f); `tests/test_pult_web_hazards.py` — 14 авторских (12 из 2.3b/5.1 + 2 новых Task 5.3a: медленная правда не блокирует status/journal, конкурентный сброс+опрос правды доходит ровно N раз каждый) |

## Долг / открытые вопросы

- **Task 5.3a сломала 5 тестов вне своих `FILES`** (`tests/test_pult_web.py` —
  3, `tests/test_pult_journal_routes.py` — 2): их фикстуры берут
  `_FakeDeviceHubClient.instances[-1]`, полагая, что плагин создаёт РОВНО один
  `DeviceHubClient`. Второй клиент (`_scene_client`, Task 5.3a) теперь
  создаётся ВТОРЫМ в `configure()` — `instances[-1]` стал сценой, а не
  `robot`. `tests/test_acceptance_5_3a.py` эту ловушку обошёл заранее
  (`_client_for(target_process)`, см. его докстринг). Разработчик не правил
  два сломанных файла — они вне списка `FILES` задачи; чинит либо ведущий,
  либо отдельная задача (перевести обе фикстуры на выбор по
  `target_process`, как в `test_acceptance_5_3a.py`).

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
