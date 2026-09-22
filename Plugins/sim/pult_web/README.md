# Plugins/sim/pult_web — веб-пульт ленты

Task 2.3b плана [`plans/line-sim/phase-2-belt-truth.md`](../../../plans/line-sim/phase-2-belt-truth.md).
Зависит от Task 2.3a (командная поверхность `belt.*` в процессе `robot`).

## Назначение

Процесс `pult` в одиночку: `PultWebPlugin` держит HTTP-страницу на
`127.0.0.1:8092` с картинкой из MJPEG-двери (`127.0.0.1:8091`) и ручками
ленты. Своей логики ленты у пульта нет — каждая ручка форвардит те же
команды `belt.*`, что и `backend_ctl`/прототип, процессу `robot` через
`Plugins.hub.device_hub.client.DeviceHubClient`. Пульт — третий клиент
одной командной поверхности (решение владельца 2026-09-22, Task 2.3).

## Конфиг (`pipeline.yaml`)

| Ключ | Дефолт | Смысл |
|---|---|---|
| `host` | `127.0.0.1` | адрес HTTP-сервера пульта. Только loopback: localhost-страж пропускает запросы лишь с `Host: 127.0.0.1:<port>` или `localhost:<port>`, при другом адресе сервер поднимется, но ответит 403 на всё |
| `port` | `8092` | порт пульта |
| `mjpeg_url` | `http://127.0.0.1:8091/` | адрес двери кадров (`<img src=...>` на странице) |
| `robot_process` | `robot` | имя процесса-адресата `DeviceHubClient` |
| `timeout_s` | `1.0` | таймаут `DeviceHubClient.request` на каждую ручку |

## HTTP API

| Метод, путь | Тело | Команда `robot` | Ответ |
|---|---|---|---|
| `GET /` | — | — | страница (`text/html`) |
| `GET /api/status` | — | `belt.status` | результат команды как есть |
| `POST /api/run` | `{freq_hz, reverse}` | `belt.run` | результат команды как есть |
| `POST /api/stop` | `{}` | `belt.stop` | результат команды как есть |
| `POST /api/jog` | `{direction, freq_hz?}` | `belt.jog` | результат команды как есть |
| `POST /api/calibrate` | `{mm_s_at_max_freq}` | `belt.calibrate` | результат команды как есть |

Путь **не валидирует** поля тела — форвардит их в `robot` как есть, валидация
(`bad_args` и т.п.) целиком на стороне Task 2.3a. Отказы ДО обращения к
`robot`: чужой `Host` (не `127.0.0.1:<port>`/`localhost:<port>`, в том числе
без порта, `[::1]` и HTTP/1.0 без `Host`) → `403 {ok: false, error:
"forbidden_host"}` на `GET` и `POST` (защита от DNS rebinding); неизвестный путь
→ `404`; `POST` с `Content-Type` не `application/json…` (в том числе без него,
как у голого `curl -X POST`) → `415 {ok: false, error: "unsupported_media_type"}`;
кривой JSON тела → `400 {ok: false, error: "bad_json"}`; тело > 4 КБ
(`Content-Length`, до чтения) → `413`. Ответ `robot` со `status: "error"` →
`504 {ok: false, error: <message клиента>}`. Ответ `robot` с `ok: false` при
`status: "ok"` (например, `server_not_running`) уходит как есть с кодом 200 —
страница различает его по `ok`.

## Поток вызова — HTTP-обработчик, не приёмный цикл

`ThreadingHTTPServer` создаёт поток на каждое соединение; ни один из них не
приёмный цикл процесса `pult`, поэтому блокирующий
`DeviceHubClient.request()` из обработчика легален (см. разведку плана,
Task 2.3, п.1). `do_POST` читает **ровно** `Content-Length` байт, не
`rfile.read()` до EOF — иначе завис бы на keep-alive-подобном соединении.

### Accept-backlog расширен до 32

Дефолт `socketserver.TCPServer.request_queue_size` — 5. Всплеск конкурентных
подключений (несколько вкладок, зажатая jog-кнопка + опрос статуса + открытая
`GET /`) на этом дефолте ловит `ECONNRESET` на уровне TCP accept ещё до
обработчика — замерено hazard-тестом (20 параллельных `POST /api/jog`).
`_PultHTTPServer.request_queue_size = 32` — с запасом под этот стенд, не
тюнинг под нагрузку.

## Отказ старта — состояние, а не падение процесса

Форма — копия `MjpegSinkPlugin` (`Plugins/sim/mjpeg_sink/plugin.py`): занятый
порт ловится синхронно в конструкторе `ThreadingHTTPServer` (`try/except
OSError`), уходит в `self._state = "error"` + `ctx.health.report_error(...)`,
процесс `pult` живёт. `shutdown()` симметричен: `server.shutdown()` +
`server_close()` + `join(timeout=5.0)` — уже открытые клиентские соединения
(например, вкладка с открытым `GET /`) при этом не закрываются принудительно,
то же известное ограничение, что у `mjpeg_sink`.

## Ответ `robot` не пришёл

`GET /api/status` опрашивается страницей каждые 250 мс. Если `robot` не
ответил (нет маршрута/процесс не поднят, таймаут IPC) — `router.request()`
возвращает `{"success": False, ...}` КАК СЛОВАРЬ, исключение не бросает;
ветка `except Exception` в `DeviceHubClient.request` на этом пути
недостижима — воспроизведено: 20 опросов подряд без `robot` дали
`DeviceHubClient health.report_error calls: 0`. Спам гасит **голосовое окно
самого роутера**: `RouterManager._do_send` на «адресат не найден» зовёт
`_report_send_error("no_route", ...)` → `self.report_error(...,
context="router.send_error:no_route")` (`ObservableMixin.report_error` +
`windowed_voice`, окно — политика процесса
`observability.voices.default_window_sec`) — тот же прогон показал `router
report_error calls: 20 {'router.send_error:no_route'}`, то есть вызван на
каждый опрос, а фактическую запись в `errors.log` глушит окно ВНУТРИ
`report_error`, не число вызовов. Страница в этом случае показывает «robot
не отвечает» и **не блокирует ручки** — ручки остаются активными (DESIGN
п.4 плана).

**Открыто (см. план, «Открыто по 2.3»):** до первого приёмного цикла
процесса `pult` `router.request` отдаёт `no_receive_pump` — первые запросы
страницы сразу после старта процесса могут получить 504 через грейс-период;
это не баг, живёт до первого успешного цикла.

## Страница

Один строковый constant в `plugin.py` (`_PAGE_TEMPLATE`, `str.format` —
не templating-движок, не файл): картинка `mjpeg_url`, ползунок частоты
0–50 Гц (шаг 0.5) + число, переключатель направления (реальный JS boolean),
кнопки «Пуск»/«Стоп», две jog-кнопки (◀/▶), поле калибровки + «Применить»,
живой блок статуса (опрос `GET /api/status` каждые 250 мс).

**Dead-man jog на странице** — своя, более быстрая копия dead-man'а `robot`
(Task 2.3a, 500 мс): `pointerdown` шлёт `/api/jog` сразу и повторяет каждые
200 мс (тик пропускается, пока предыдущий `/api/jog` ещё в пути);
`pointerup`/`pointercancel`/`pointerleave`/`blur` окна/`visibilitychange`
вкладки снимают таймер и шлют `/api/stop` — **только если jog активен** (иначе
no-op, чтобы наведение мыши не остановило ленту, запущенную «Пуском» или
backend_ctl) и **только после возврата последнего `/api/jog`**, чтобы стоп не
обогнал его в пути к `robot`. Это ДВОЙНАЯ защита, не замена серверного
dead-man — закрытие вкладки при зажатой кнопке всё равно останавливается по
watchdog `robot`, если JS не успел выполниться.

Поведение страницы проверяется НАСТОЯЩИМ её `<script>` через `node:vm`
(`tests/page_offline.mjs`) против живого сервера плагина с двойником `robot`:
jog без лишних стопов, без осиротевшего таймера, порядок jog→stop, «robot не
отвечает». Это не браузер: семантика pointer-событий на тач-экране не
проверена. Где нет `node`, эти тесты пропускаются (`skipif`).

Известный предел: если `robot` отвечает на команду дольше ~400 мс, подкачка
jog идёт реже `jog_timeout_ms` (500 мс) и лента дёргается остановками
dead-man'а при удержании (ревью 2.3b, итерация 2, наблюдение A). Сбой в
безопасную сторону — лента стоит, а не едет лишнее.

## Границы

Импорт `Plugins.sim.robot_host` и `multiprocess_prototype.*` запрещён (ADR-120) —
единственный канал к `robot` — `DeviceHubClient`.

## Out of scope (Task 2.3b)

Авторизация и доступ не с `127.0.0.1`; ручки потока/брака/паузы (Ф6.1, после
Ф3); журнал обмена (Ф6.2); WebSocket/SSE вместо опроса; подписка на дерево
`sim.belt.**` в пульте; стили сверх читаемости.
