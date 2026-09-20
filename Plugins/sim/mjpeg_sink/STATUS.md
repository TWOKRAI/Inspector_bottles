# Plugins/sim/mjpeg_sink — STATUS

**Состояние: сделано (Task 1.2b плана line-sim, вертикальный срез).**

**Обновлено:** 2026-09-21 — Task 1.2b, ветка `feat/line-sim-1.2-sink`.

| Что | Состояние |
|---|---|
| `plugin.py` — `MjpegSinkPlugin` | есть: `configure`/`start`/`shutdown`, синхронный `OSError` на занятый порт, multipart-раздача, троттлинг `fps_cap` |
| Занятый порт | есть: `ThreadingHTTPServer.__init__` биндит синхронно, `OSError` → `report_error`, `state="error"`, процесс живёт |
| Повторный `start()` | есть: no-op при живом сервере (`self._server is not None`) |
| Гонка `process()` ↔ чтение сервером | есть: `_last_frame_jpeg`/`_frame_seq` под `threading.Lock` |
| `cv2.imencode` не смог закодировать | есть: пустой кадр (`shape=(0,0,3)`) БРОСАЕТ `cv2.error`, не возвращает `ok=False` — поймано отдельным `try/except cv2.error` |
| Кадра ещё нет — сервер отвечает без границы | есть: заголовки шлются, соединение закрывается штатно без multipart-части |
| Тесты | `tests/test_hazards.py` — 5 авторских (a-e); приёмочные независимого тестера — `apps/line_sim/tests/test_f1_task12_acceptance.py` + `multiprocess_prototype/recipes/tests/test_letter_robot_sim_diff.py` (вне этого пакета) |

## Долг / открытые вопросы

- `shutdown()` не закрывает уже открытые клиентские соединения (см. докстринг
  `plugin.py` и README) — `server.shutdown()`/`server_close()` тушат только
  accept-цикл и слушающий сокет; поток конкретного соединения живёт, пока
  клиент сам не отключится (daemon-поток, процесс не блокирует). Потребовало
  бы отслеживать сокеты каждого соединения отдельно — вне минимального объёма
  Task 1.2b.
- `apps/line_sim/app.yaml` пришлось поправить (`discovery.plugin_paths`:
  `[]` → `["../../Plugins"]`, `auto_discover`: `false` → `true`) — Task 1.1
  предполагал, что все плагины сима лежат под `Plugins/sim` и авто-скан не
  нужен; `CameraServicePlugin` (Task 1.2a) живёт под `Plugins/sources/`, вне
  этого допущения. Файл вне FILES этой задачи — правка эскалирована ведущему
  до коммита, не тихая (см. отчёт разработчика).
- Нет теста на реальную нагрузку двух клиентов + троттлинг `fps_cap` вместе
  (авторские тесты гоняют `fps_cap=0`, дефолт) — приёмочный тест на два
  клиента гоняется независимым тестером без троттлинга.
