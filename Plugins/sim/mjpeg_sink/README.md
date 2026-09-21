# Plugins/sim/mjpeg_sink — HTTP MJPEG-раздача последнего кадра

Task 1.2b плана [`plans/line-sim/phase-1-vertical-slice.md`](../../../plans/line-sim/phase-1-vertical-slice.md).

## Назначение

Тонкий sink-плагин `ProcessModulePlugin` (форма — как у
[`Plugins/sim/robot_host`](../robot_host/README.md), Task 1.1): последний узел
процесса `camera` в `apps/line_sim` (после `CameraServicePlugin`). Кодирует
принятые кадры в JPEG и раздаёт multipart-поток (`multipart/x-mixed-replace`)
любому числу HTTP-клиентов одновременно — браузер, `cv2.VideoCapture(url)`,
`ffplay`, и сам прототип (`multiprocess_prototype/recipes/letter_robot_sim.yaml`
читает этот же URL как источник `camera_0`).

## Конфиг (`pipeline.yaml`)

| Ключ | Дефолт | Смысл |
|---|---|---|
| `host` | `127.0.0.1` | адрес HTTP-сервера |
| `port` | `8091` | порт (стенд `apps/line_sim` фиксирует именно этот) |
| `jpeg_quality` | `80` | `cv2.IMWRITE_JPEG_QUALITY` |
| `fps_cap` | `0` | максимум кодирований/сек; `0` — без троттлинга |

## Порт (`GET /`)

Ответ — `Content-Type: multipart/x-mixed-replace; boundary=...`, части —
`--boundary\r\nContent-Type: image/jpeg\r\nContent-Length: N\r\n\r\n<JPEG>\r\n`,
раздаётся ПОСЛЕДНИЙ принятый кадр непрерывно, пока клиент подключён. Кадра ещё
нет — соединение закрывается штатно сразу после заголовков (без части, без
исключения); подробности — докстринг `plugin.py`.

## Занятый порт

В отличие от [`SimRobotHostPlugin`](../robot_host/README.md) (Task 1.1,
`pymodbus` биндит в фоновом потоке), здесь `http.server.ThreadingHTTPServer`
биндит порт СИНХРОННО в конструкторе (`socketserver.TCPServer.__init__`) —
`OSError` при занятом порту ловится прямо в `_start_server` без отдельного
пробного сокета. Уходит в `state="error"` + `ctx.health.report_error(...)`,
процесс живёт.

## Поток сервера

`process()` (штатный поток плагина) и HTTP-обработчик (поток на соединение,
`ThreadingMixIn`) — РАЗНЫЕ потоки. Последний кадр и его номер — одно поле,
кортеж `_latest = (jpeg, seq)`: писатель перепривязывает одну ссылку, читатель
берёт её один раз, пара согласована по построению, лока нет. Обработчик доступа к `PluginContext` не
имеет вовсе (замыкание на плагин, не на `ctx`) — `ctx.log_*`/`record_metric` с
чужого потока не зовутся.

## `shutdown()` — известное ограничение

`server.shutdown()`/`server_close()` останавливают только accept-цикл и
слушающий сокет; поток УЖЕ открытого клиентского соединения ими не
закрывается — он живёт, пока клиент сам не отключится (daemon-поток, процесс
не держит). См. `STATUS.md`.

## Границы

Импорт `multiprocess_prototype.*` запрещён (ADR-120, зеркало правила
`examples/*`): плагин — словарь повторного использования между приложениями.

## Out of scope (Task 1.2b)

Объекты/слои/фотометрия, ROI, GUI-дисплей внутри сима (Ф3–Ф4). Принудительное
закрытие уже открытых клиентских соединений при `shutdown()`.
