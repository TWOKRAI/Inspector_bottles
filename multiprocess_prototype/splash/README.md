# splash — заставка загрузки отдельным процессом

Окно со шкалой 0–100 % от запуска до первого окна GUI (задача 2.6, `plans/2026-10-27_system-run-state/tasks/2.6.md`).
Заставку запускает только лончер, один раз; сбой заставки не роняет и не задерживает приложение.

## Модули

| модуль | кто грузит | что делает |
|---|---|---|
| `interface.py` | все | `SplashLinkProtocol`, `SplashControllerProtocol`, `LeafSender` (только `typing`) |
| `protocol.py` | все | env-имена, посылка, веса, `SplashScale` (только stdlib) |
| `window.py` | процесс заставки | окно, `SplashController`, `main()` (stdlib + PySide6 + `protocol`) |
| `launcher.py` | лончер | `start_splash` / `stop_splash`, `SplashLink` |
| `mirror.py` | процесс PM | `ProgressMirror`, `install_if_enabled` |

## Переменные окружения

| имя | смысл |
|---|---|
| `INSPECTOR_SPLASH` | `0` — нет процесса заставки, нет порта, PM без зеркала. Иначе включена |
| `INSPECTOR_SPLASH_PORT` | порт заставки. Ставит только `publish_port`; `main()` снимает унаследованный |

Заставки нет и при headless-запуске, и когда топология не даёт окна (`presentation_window_expected`).

## Посылка

UDP 127.0.0.1, JSON `{"id", "percent", "label", "done"}`; `percent` 0..100 целое, `label` до 200 символов.
Источники: `launch` — лончер; `boot` и `gui` — листья `system.progress.<id>` стора PM через `ProgressMirror`.

Порт выбирает сама заставка и пишет его первой строкой в stdout (до импорта PySide6).
stdin заставки — «верёвка жизни»: EOF означает, что лончера нет.

## Шкала

Веса: `launch` 10, `boot` 50, `gui` 40. Итог = `round(Σ вес × percent/100)`, не убывает.
Неизвестный `id` шкалу не двигает, его подпись видна второй строкой.

## Причины закрытия

`gui_done` (лист `gui` с `done`), `timeout` (60 с), `parent_gone` (EOF stdin), `sigint`,
`window_closed` (окно закрыл пользователь). В stderr две строки: `[splash] shown` и
`[splash] closed reason=<r> after <с> s percent=<p>`.

## Пред- и постусловия

- `start_splash`: Post — `SplashLink` или `None`; не бросает. `None` -> вызывающий к ссылке не обращается.
  Живой держатель + заставка нужна -> тот же объект, env не тронут; иначе порт из env снят.
- `SplashLink.report`: не бросает; до прихода порта хранит только последний лист.
- `SplashLink.publish_port`: звать из главного потока до spawn. `True` -> порт в env; `False` -> env не тронут
  (порта не дождались -> заставка закрыта).
- `SplashLink.close`: идемпотентно; stdin -> ждать 1 с -> `kill` -> stdout.
- `SplashController`: делает сокет неблокирующим; `request_close` — любой поток; `poll` — только Qt-поток.
- `send_leaf`, `install_if_enabled`, `ProgressMirror.after_set`: не бросают.

## Замеры (Windows 10, main `.venv`, 2026-11-26, из DESIGN задачи)

- строка порта — 48,6–70,1 мс после `Popen` (n=7, через трамплин uv);
- окно заставки с первым оборотом цикла — 0,19–0,32 с без импорта фреймворка (с ним +0,77–1,26 с);
- `build()` системы — 3,6–8,3 с (n=3): всё это время шкала стоит на 5 %.

Известная цена: падение GUI до первого окна держит заставку до `timeout`.
