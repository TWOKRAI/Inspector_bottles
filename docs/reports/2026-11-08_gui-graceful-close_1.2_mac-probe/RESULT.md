# Проба Task 1.2 (Mac, Darwin): stop_outcome / stop_deadline_at / stop_wave в supervision.status

Дата: 2026-11-08. Дерево: worktree `op-1.2`, ветка `feat/gui-close-1.2`, HEAD `4c5f77116`. Интерпретатор: main `.venv/bin/python`,
`PYTHONPATH=<worktree>:<этот каталог>/slowapp`, без uv. Прогон через `machine_gate.sh medium op-gui-close-probe`.
`kern.posix.sem.max = 10000`; ENOSPC не встретился, чужих прогонов пробы в `ps` не было.

## Что запускалось

Образец — `docs/reports/2026-11-07_gui-graceful-close_1.1a_mac-probe/probe_slow.py` (+ `slowapp/` без изменений).
Приложение: `ticker` (обычный ребёнок) и `console_sink` (shutdown 4 с, `SlowConsumerPlugin`). Упрямого ребёнка (`stubborn`)
в `slowapp` нет — это ребёнок другой пробы; здесь только медленный.
Проба шлёт `system.shutdown` через `backend_ctl`, а поток опроса зовёт `supervision_status` каждые 0,05 с и читает
`r["result"]["processes"]` по каждой записи: `stop_outcome`, `stop_deadline_at`, `stop_wave`, `alive`.

Команда (R — корень worktree, D — этот каталог, PY — main `.venv/bin/python`):

```
PYTHONPATH=$R:$D/slowapp $PY $D/probe_slow.py 3 8799          # основной: 3 прогона, пауза опроса 0,05 с
PYTHONPATH=$R:$D/slowapp $PY $D/probe_slow.py 3 8799 0.005    # дополнительный: пауза 0,005 с (поймать конец стопа)
```

Окно и `infra_s` для проверки (г): окно имени `g = 5,0 с`, `infra_s = 1,0 с`. Источник: `app.yaml` не задаёт
`shutdown_timeout` и `stop_window_s`, значит `g = DEFAULT_SHUTDOWN_TIMEOUT_S = 5.0` (`core/stop_budget.py:46`,
`ProcessRegistry._system_window_s`), `infra_s = min(INFRA_STOP_S = 1.0, 0.8 * 5.0 / 4 = 1.0) = 1.0` (`stop_budget.py:95`).
В пробе это литералы `WINDOW_S`/`INFRA_S`, не импорт. Допуск: `stop_deadline_at` в `[t_cmd; t_cmd + 6,0]`, `t_cmd` =
`time.time()` перед `system_shutdown`.

Определения пунктов: (а) ответов после команды, где `ticker.stop_outcome == "exited"` и `console_sink.alive is True`;
(б) записей PM (`ProcessManager`) со `stop_outcome != None`; (в) записей любого процесса со `stop_wave != "main"`;
(г) нарушения: запись PM с `stop_deadline_at != None`; запись ребёнка с числом в ответе, завершённом до `t_cmd`; живой
(`alive is True`) ребёнок с числом вне `[0; 6]` от `t_cmd`; (д) `stop_outcome` детей в последнем ответе.

## Сводка

Основной запуск (пауза 0,05 с), три прогона:

| прогон | shutdown, с | ответов после команды | (а) порог >= 5 | (б) нарушений | (в) нарушений | (г) нарушений | (г) число у живых: n, смещение от t_cmd, с | (д) ticker | (д) console_sink |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4,37 | 68 | 65 | 0 (85 записей PM) | 0 (255 записей) | 0 | 71, +5,019 | exited | None |
| 2 | 4,27 | 68 | 65 | 0 (85) | 0 (255) | 0 | 67, +5,110 | exited | None |
| 3 | 4,36 | 68 | 64 | 0 (85) | 0 (255) | 0 | 67, +5,116 | exited | None |

Дополнительный запуск (пауза 0,005 с), три прогона:

| прогон | shutdown, с | ответов после команды | (а) | (б) | (в) | (г) нарушений | (г) n живых с числом, смещение | (д) ticker | (д) console_sink |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4,46 | 324 | 300 | 0 | 0 | 0 | 323, +5,121 | exited | None |
| 2 | 4,34 | 328 | 305 | 0 | 0 | 0 | 343, +5,014 | exited | None |
| 3 | 4,36 | 327 | 310 | 0 | 0 | 0 | 325, +5,105 | exited | None |

Смещение `stop_deadline_at` в каждом прогоне одно и то же число во всех ответах (min = max): срок не пересчитывается.
Оно = момент сигнала детям (через 0,01–0,12 с после команды) + 5,0. Попадает в допуск `[0; 6]`.
`stop_wave == "main"` у всех записей, включая PM. У PM `stop_deadline_at = None` и `stop_outcome = None` в каждом ответе.
У записей умерших детей `stop_deadline_at` остаётся числом (ADR-PMM-042: «после смерти не пересчитывается»); пункт (г)
этого не запрещает, счёт — «мёртвых с deadline» в выводе ниже.

## Расхождения с ожиданием

1. **(д) не подтверждён по ответам статуса.** `console_sink` — медленный ребёнок — не показал ни разу `stop_outcome` из
   {exited, terminated, killed}: последний ответ любого прогона (как основного, так и дополнительного) даёт
   `console_sink: stop_outcome = None`; `system_stop.phase == "done"` не виден ни в одном ответе (во всех `children`);
   запрос после возврата `system_shutdown` падает `BackendUnavailable` (бэкенд уже закрыт). В дополнительном запуске пойманы
   ответы `console_sink: alive=False out=None` (2, 1 и 1 ответ по прогонам, смещение +4,28…+4,29 с) — окно «умер, но
   группа ещё не наблюдала смерть» из ADR-PMM-042 («Предел контракта», <= `STOP_POLL_S`); после него `message_processor`
   PM останавливается раньше, чем итог записан в реестр. `ticker` показывает `exited` уже со смещения ~+0,24 с.
   Ожидаемый литерал по поведению slowapp для `console_sink` — `exited` (shutdown 4 с укладывается в окно 5 с, `terminate`
   не нужен); по ответам статуса это не проверить. Пробой не подгонял; проверки итога после `done` через опрос нет,
   нужен другой источник (лог PM или тест в процессе). В логах пробы строки с итогом не нашёл.
2. Ответ на (а): порог >= 5 выполнен с большим запасом (64–65 при паузе 0,05 с), но все эти ответы — про `ticker`, у
   которого стоп мгновенный; медленный сосед проверяется только как «ещё жив».

## Вывод прогонов дословно

### Основной запуск (пауза 0,05 с; команда `... probe_slow.py 3 8799`), stdout+stderr целиком

```
======================================================
 Slow Probe App
======================================================
 manifest : /Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/op-1.2/docs/reports/2026-11-08_gui-graceful-close_1.2_mac-probe/slowapp/app.yaml
 pipeline : pipeline.yaml
 plugins  : 0
 services : 0
 processes: 2
======================================================
2026-11-08 12:35:30,022 [WARNING] [-] stats_ProcessManager: [stats_ProcessManager] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
2026-11-08 12:35:30,027 [WARNING] [-] observability: Process 'ProcessManager': у ПЛОСКОСТИ ОШИБОК нет своего store-tap (ErrorManager не создан или не поддержал add_tap) — владение маркированными записями взял на себя логгер-tap. Инциденты в сторе будут, но приедут дорогой ГОЛОСА, а не дорогой факта: без трассы и без полей track_error
2026-11-08 12:35:30,590 [WARNING] [-] stats_ticker: [stats_ticker] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
2026-11-08 12:35:30,708 [WARNING] [-] stats_console_sink: [stats_console_sink] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
[WARNING] [error_ticker] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
[WARNING] [error_console_sink] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
2026-11-08 12:35:36,142 [WARNING] [-] m.m.r.c.socket_client: backend-ctl-reader: сервер закрыл соединение
  post-запрос после shutdown не дал ответа: BackendUnavailable: соединение с бэкендом на 127.0.0.1:8799 оборвано: сервер закрыл соединение. Драйвер будет пересоздан на следующем вызове (durable-подписки и watch-профиль восстанавливаются автоматически); если бэкенд упал — подними его с BACKEND_CTL=1.
[WARNING] [error_launcher] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
[WARNING] [logger_launcher] [system] приёмники не приняли ни одной записи за прогон: performance_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
run 1: shutdown=4.37s answers_after=68 max=0.015s did_not_stop=0 accepted=True
  t_cmd(wall)=1794130531.826; окно g=5s infra_s=1s; ответы без processes: 0
  t=+0.05s phase=children | ticker: alive=True out=None wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.11s phase=children | ticker: alive=True out=None wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.17s phase=children | ticker: alive=True out=None wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.24s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.30s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.36s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.42s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.48s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.55s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.61s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.67s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.74s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.79s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.86s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.92s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.98s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.05s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.11s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.17s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.24s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.30s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.36s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.42s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.48s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.54s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.60s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.66s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.73s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.79s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.85s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.91s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.97s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.04s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.10s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.17s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.23s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.28s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.35s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.41s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.47s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.53s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.60s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.66s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.72s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.78s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.84s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.91s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.96s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.03s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.09s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.16s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.21s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.27s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.34s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.40s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.46s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.52s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.58s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.64s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.70s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.77s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.83s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.89s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.96s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.02s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.07s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.14s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.21s phase=children | ticker: alive=False out=exited wave=main dl=+5.02 | console_sink: alive=True out=None wave=main dl=+5.02 | ProcessManager: alive=True out=None wave=main dl=None
  --- сводка прогона 1
  имена в processes: ['ProcessManager', 'console_sink', 'ticker']; ответов всего=85, после команды=68
  (а) ответов, где ticker.stop_outcome=='exited' при console_sink.alive==True: 65 (порог >= 5)
  (б) записей PM=85, из них stop_outcome != None: 0 (ожидается 0)
  (в) записей=255, stop_wave != 'main': 0 (ожидается 0)
  (г) живых записей с deadline=71 (min=5.018896818161011 max=5.018896818161011 относительно t_cmd; допустимо [0; 6]); мёртвых с deadline=65; нарушений=0 []
  (д) финал (последний ответ опроса, phase=children): {'ticker': 'exited', 'console_sink': None}; ответов с phase=='done': 0, последний из них: None
======================================================
 Slow Probe App
======================================================
 manifest : /Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/op-1.2/docs/reports/2026-11-08_gui-graceful-close_1.2_mac-probe/slowapp/app.yaml
 pipeline : pipeline.yaml
 plugins  : 0
 services : 0
 processes: 2
======================================================
2026-11-08 12:35:36,765 [WARNING] [-] stats_ProcessManager: [stats_ProcessManager] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
2026-11-08 12:35:36,770 [WARNING] [-] observability: Process 'ProcessManager': у ПЛОСКОСТИ ОШИБОК нет своего store-tap (ErrorManager не создан или не поддержал add_tap) — владение маркированными записями взял на себя логгер-tap. Инциденты в сторе будут, но приедут дорогой ГОЛОСА, а не дорогой факта: без трассы и без полей track_error
2026-11-08 12:35:37,320 [WARNING] [-] stats_ticker: [stats_ticker] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
2026-11-08 12:35:37,428 [WARNING] [-] stats_console_sink: [stats_console_sink] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
[WARNING] [error_ticker] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
[WARNING] [error_console_sink] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
2026-11-08 12:35:42,787 [WARNING] [-] m.m.r.c.socket_client: backend-ctl-reader: сервер закрыл соединение
  post-запрос после shutdown не дал ответа: BackendUnavailable: соединение с бэкендом на 127.0.0.1:8799 оборвано: сервер закрыл соединение. Драйвер будет пересоздан на следующем вызове (durable-подписки и watch-профиль восстанавливаются автоматически); если бэкенд упал — подними его с BACKEND_CTL=1.
[WARNING] [error_launcher] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
[WARNING] [logger_launcher] [system] приёмники не приняли ни одной записи за прогон: performance_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
run 2: shutdown=4.27s answers_after=68 max=0.013s did_not_stop=0 accepted=True
  t_cmd(wall)=1794130538.563; окно g=5s infra_s=1s; ответы без processes: 0
  t=+0.04s phase=children | ticker: alive=True out=None wave=main dl=None | console_sink: alive=True out=None wave=main dl=None | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.10s phase=children | ticker: alive=True out=None wave=main dl=None | console_sink: alive=True out=None wave=main dl=None | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.16s phase=children | ticker: alive=True out=None wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.22s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.29s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.35s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.41s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.47s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.53s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.59s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.65s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.72s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.77s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.84s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.90s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.96s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.02s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.08s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.14s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.20s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.27s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.33s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.39s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.45s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.51s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.57s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.63s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.69s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.76s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.82s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.87s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.94s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.00s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.06s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.12s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.18s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.24s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.30s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.37s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.43s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.49s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.55s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.61s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.67s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.73s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.80s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.86s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.92s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.98s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.05s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.10s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.17s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.22s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.29s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.35s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.41s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.48s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.54s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.60s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.66s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.72s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.77s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.84s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.90s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.97s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.03s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.09s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.15s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  --- сводка прогона 2
  имена в processes: ['ProcessManager', 'console_sink', 'ticker']; ответов всего=85, после команды=68
  (а) ответов, где ticker.stop_outcome=='exited' при console_sink.alive==True: 65 (порог >= 5)
  (б) записей PM=85, из них stop_outcome != None: 0 (ожидается 0)
  (в) записей=255, stop_wave != 'main': 0 (ожидается 0)
  (г) живых записей с deadline=67 (min=5.10987401008606 max=5.10987401008606 относительно t_cmd; допустимо [0; 6]); мёртвых с deadline=65; нарушений=0 []
  (д) финал (последний ответ опроса, phase=children): {'ticker': 'exited', 'console_sink': None}; ответов с phase=='done': 0, последний из них: None
======================================================
 Slow Probe App
======================================================
 manifest : /Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/op-1.2/docs/reports/2026-11-08_gui-graceful-close_1.2_mac-probe/slowapp/app.yaml
 pipeline : pipeline.yaml
 plugins  : 0
 services : 0
 processes: 2
======================================================
2026-11-08 12:35:43,399 [WARNING] [-] stats_ProcessManager: [stats_ProcessManager] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
2026-11-08 12:35:43,405 [WARNING] [-] observability: Process 'ProcessManager': у ПЛОСКОСТИ ОШИБОК нет своего store-tap (ErrorManager не создан или не поддержал add_tap) — владение маркированными записями взял на себя логгер-tap. Инциденты в сторе будут, но приедут дорогой ГОЛОСА, а не дорогой факта: без трассы и без полей track_error
2026-11-08 12:35:43,964 [WARNING] [-] stats_ticker: [stats_ticker] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
2026-11-08 12:35:44,076 [WARNING] [-] stats_console_sink: [stats_console_sink] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
[WARNING] [error_ticker] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
[WARNING] [error_console_sink] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
2026-11-08 12:35:49,508 [WARNING] [-] m.m.r.c.socket_client: backend-ctl-reader: сервер закрыл соединение
  post-запрос после shutdown не дал ответа: BackendUnavailable: соединение с бэкендом на 127.0.0.1:8799 оборвано: сервер закрыл соединение. Драйвер будет пересоздан на следующем вызове (durable-подписки и watch-профиль восстанавливаются автоматически); если бэкенд упал — подними его с BACKEND_CTL=1.
[WARNING] [error_launcher] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
[WARNING] [logger_launcher] [system] приёмники не приняли ни одной записи за прогон: performance_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
run 3: shutdown=4.36s answers_after=68 max=0.015s did_not_stop=0 accepted=True
  t_cmd(wall)=1794130545.192; окно g=5s infra_s=1s; ответы без processes: 0
  t=+0.04s phase=children | ticker: alive=True out=None wave=main dl=None | console_sink: alive=True out=None wave=main dl=None | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.10s phase=children | ticker: alive=True out=None wave=main dl=None | console_sink: alive=True out=None wave=main dl=None | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.16s phase=children | ticker: alive=True out=None wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.22s phase=children | ticker: alive=False out=None wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.28s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.34s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.40s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.46s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.52s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.58s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.64s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.70s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.76s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.83s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.89s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+0.95s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.01s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.08s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.14s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.20s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.26s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.32s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.39s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.45s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.51s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.57s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.63s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.70s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.76s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.82s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.88s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+1.95s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.00s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.07s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.12s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.19s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.25s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.31s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.37s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.43s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.50s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.56s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.62s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.68s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.75s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.81s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.87s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+2.93s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.00s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.06s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.12s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.18s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.24s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.30s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.37s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.43s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.49s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.55s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.61s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.67s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.73s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.80s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.85s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.92s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+3.99s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.05s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.11s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.17s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  --- сводка прогона 3
  имена в processes: ['ProcessManager', 'console_sink', 'ticker']; ответов всего=85, после команды=68
  (а) ответов, где ticker.stop_outcome=='exited' при console_sink.alive==True: 64 (порог >= 5)
  (б) записей PM=85, из них stop_outcome != None: 0 (ожидается 0)
  (в) записей=255, stop_wave != 'main': 0 (ожидается 0)
  (г) живых записей с deadline=67 (min=5.116397857666016 max=5.116397857666016 относительно t_cmd; допустимо [0; 6]); мёртвых с deadline=65; нарушений=0 []
  (д) финал (последний ответ опроса, phase=children): {'ticker': 'exited', 'console_sink': None}; ответов с phase=='done': 0, последний из них: None
min answers_after: 68 max shutdown: 4.37s
```

### Дополнительный запуск (пауза 0,005 с; `... probe_slow.py 3 8799 0.005`), stdout+stderr; строки-ответы только со смещением >= +4,15 с (полный вывод — 1064 строки, в файл не включён)

```
======================================================
 Slow Probe App
======================================================
 manifest : /Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/op-1.2/docs/reports/2026-11-08_gui-graceful-close_1.2_mac-probe/slowapp/app.yaml
 pipeline : pipeline.yaml
 plugins  : 0
 services : 0
 processes: 2
======================================================
2026-11-08 12:36:12,750 [WARNING] [-] stats_ProcessManager: [stats_ProcessManager] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
2026-11-08 12:36:12,755 [WARNING] [-] observability: Process 'ProcessManager': у ПЛОСКОСТИ ОШИБОК нет своего store-tap (ErrorManager не создан или не поддержал add_tap) — владение маркированными записями взял на себя логгер-tap. Инциденты в сторе будут, но приедут дорогой ГОЛОСА, а не дорогой факта: без трассы и без полей track_error
2026-11-08 12:36:13,291 [WARNING] [-] stats_ticker: [stats_ticker] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
2026-11-08 12:36:13,393 [WARNING] [-] stats_console_sink: [stats_console_sink] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
[WARNING] [error_ticker] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
[WARNING] [error_console_sink] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
2026-11-08 12:36:18,883 [WARNING] [-] m.m.r.c.socket_client: backend-ctl-reader: сервер закрыл соединение
  post-запрос после shutdown не дал ответа: BackendUnavailable: соединение с бэкендом на 127.0.0.1:8799 оборвано: сервер закрыл соединение. Драйвер будет пересоздан на следующем вызове (durable-подписки и watch-профиль восстанавливаются автоматически); если бэкенд упал — подними его с BACKEND_CTL=1.
[WARNING] [error_launcher] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
[WARNING] [logger_launcher] [system] приёмники не приняли ни одной записи за прогон: performance_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
run 1: shutdown=4.46s answers_after=324 max=0.085s did_not_stop=0 accepted=True
  t_cmd(wall)=1794130574.482; окно g=5s infra_s=1s; ответы без processes: 0
  t=+4.20s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.22s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.23s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.24s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.25s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.27s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=True out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.28s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=False out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.29s phase=children | ticker: alive=False out=exited wave=main dl=+5.12 | console_sink: alive=False out=None wave=main dl=+5.12 | ProcessManager: alive=True out=None wave=main dl=None
  --- сводка прогона 1
  имена в processes: ['ProcessManager', 'console_sink', 'ticker']; ответов всего=404, после команды=324
  (а) ответов, где ticker.stop_outcome=='exited' при console_sink.alive==True: 300 (порог >= 5)
  (б) записей PM=404, из них stop_outcome != None: 0 (ожидается 0)
  (в) записей=1212, stop_wave != 'main': 0 (ожидается 0)
  (г) живых записей с deadline=323 (min=5.1206138134002686 max=5.1206138134002686 относительно t_cmd; допустимо [0; 6]); мёртвых с deadline=307; нарушений=0 []
  (д) финал (последний ответ опроса, phase=children): {'ticker': 'exited', 'console_sink': None}; ответов с phase=='done': 0, последний из них: None
======================================================
 Slow Probe App
======================================================
 manifest : /Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/op-1.2/docs/reports/2026-11-08_gui-graceful-close_1.2_mac-probe/slowapp/app.yaml
 pipeline : pipeline.yaml
 plugins  : 0
 services : 0
 processes: 2
======================================================
2026-11-08 12:36:19,527 [WARNING] [-] stats_ProcessManager: [stats_ProcessManager] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
2026-11-08 12:36:19,532 [WARNING] [-] observability: Process 'ProcessManager': у ПЛОСКОСТИ ОШИБОК нет своего store-tap (ErrorManager не создан или не поддержал add_tap) — владение маркированными записями взял на себя логгер-tap. Инциденты в сторе будут, но приедут дорогой ГОЛОСА, а не дорогой факта: без трассы и без полей track_error
2026-11-08 12:36:20,053 [WARNING] [-] stats_ticker: [stats_ticker] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
2026-11-08 12:36:20,163 [WARNING] [-] stats_console_sink: [stats_console_sink] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
[WARNING] [error_ticker] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
[WARNING] [error_console_sink] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
2026-11-08 12:36:25,558 [WARNING] [-] m.m.r.c.socket_client: backend-ctl-reader: сервер закрыл соединение
  post-запрос после shutdown не дал ответа: BackendUnavailable: соединение с бэкендом на 127.0.0.1:8799 оборвано: сервер закрыл соединение. Драйвер будет пересоздан на следующем вызове (durable-подписки и watch-профиль восстанавливаются автоматически); если бэкенд упал — подними его с BACKEND_CTL=1.
[WARNING] [error_launcher] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
[WARNING] [logger_launcher] [system] приёмники не приняли ни одной записи за прогон: performance_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
run 2: shutdown=4.34s answers_after=328 max=0.011s did_not_stop=0 accepted=True
  t_cmd(wall)=1794130581.251; окно g=5s infra_s=1s; ответы без processes: 0
  t=+4.15s phase=children | ticker: alive=False out=exited wave=main dl=+5.01 | console_sink: alive=True out=None wave=main dl=+5.01 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.16s phase=children | ticker: alive=False out=exited wave=main dl=+5.01 | console_sink: alive=True out=None wave=main dl=+5.01 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.17s phase=children | ticker: alive=False out=exited wave=main dl=+5.01 | console_sink: alive=True out=None wave=main dl=+5.01 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.19s phase=children | ticker: alive=False out=exited wave=main dl=+5.01 | console_sink: alive=True out=None wave=main dl=+5.01 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.20s phase=children | ticker: alive=False out=exited wave=main dl=+5.01 | console_sink: alive=True out=None wave=main dl=+5.01 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.21s phase=children | ticker: alive=False out=exited wave=main dl=+5.01 | console_sink: alive=True out=None wave=main dl=+5.01 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.23s phase=children | ticker: alive=False out=exited wave=main dl=+5.01 | console_sink: alive=True out=None wave=main dl=+5.01 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.24s phase=children | ticker: alive=False out=exited wave=main dl=+5.01 | console_sink: alive=True out=None wave=main dl=+5.01 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.25s phase=children | ticker: alive=False out=exited wave=main dl=+5.01 | console_sink: alive=True out=None wave=main dl=+5.01 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.26s phase=children | ticker: alive=False out=exited wave=main dl=+5.01 | console_sink: alive=True out=None wave=main dl=+5.01 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.28s phase=children | ticker: alive=False out=exited wave=main dl=+5.01 | console_sink: alive=False out=None wave=main dl=+5.01 | ProcessManager: alive=True out=None wave=main dl=None
  --- сводка прогона 2
  имена в processes: ['ProcessManager', 'console_sink', 'ticker']; ответов всего=407, после команды=328
  (а) ответов, где ticker.stop_outcome=='exited' при console_sink.alive==True: 305 (порог >= 5)
  (б) записей PM=407, из них stop_outcome != None: 0 (ожидается 0)
  (в) записей=1221, stop_wave != 'main': 0 (ожидается 0)
  (г) живых записей с deadline=343 (min=5.014375925064087 max=5.014375925064087 относительно t_cmd; допустимо [0; 6]); мёртвых с deadline=311; нарушений=0 []
  (д) финал (последний ответ опроса, phase=children): {'ticker': 'exited', 'console_sink': None}; ответов с phase=='done': 0, последний из них: None
======================================================
 Slow Probe App
======================================================
 manifest : /Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/op-1.2/docs/reports/2026-11-08_gui-graceful-close_1.2_mac-probe/slowapp/app.yaml
 pipeline : pipeline.yaml
 plugins  : 0
 services : 0
 processes: 2
======================================================
2026-11-08 12:36:26,194 [WARNING] [-] stats_ProcessManager: [stats_ProcessManager] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
2026-11-08 12:36:26,198 [WARNING] [-] observability: Process 'ProcessManager': у ПЛОСКОСТИ ОШИБОК нет своего store-tap (ErrorManager не создан или не поддержал add_tap) — владение маркированными записями взял на себя логгер-tap. Инциденты в сторе будут, но приедут дорогой ГОЛОСА, а не дорогой факта: без трассы и без полей track_error
2026-11-08 12:36:26,729 [WARNING] [-] stats_ticker: [stats_ticker] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
2026-11-08 12:36:26,850 [WARNING] [-] stats_console_sink: [stats_console_sink] stats.aggregation_interval=5.0 ниже пола stats.flush_interval=10.0 — действует 10.0 с. Темп ниже пола задаётся только уменьшением stats.flush_interval.
[WARNING] [error_ticker] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
[WARNING] [error_console_sink] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
2026-11-08 12:36:32,304 [WARNING] [-] m.m.r.c.socket_client: backend-ctl-reader: сервер закрыл соединение
  post-запрос после shutdown не дал ответа: BackendUnavailable: соединение с бэкендом на 127.0.0.1:8799 оборвано: сервер закрыл соединение. Драйвер будет пересоздан на следующем вызове (durable-подписки и watch-профиль восстанавливаются автоматически); если бэкенд упал — подними его с BACKEND_CTL=1.
[WARNING] [error_launcher] [system] приёмники не приняли ни одной записи за прогон: critical_file, errors_file, warnings_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
[WARNING] [logger_launcher] [system] приёмники не приняли ни одной записи за прогон: performance_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
run 3: shutdown=4.36s answers_after=327 max=0.010s did_not_stop=0 accepted=True
  t_cmd(wall)=1794130587.977; окно g=5s infra_s=1s; ответы без processes: 0
  t=+4.15s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.16s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.17s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.19s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.20s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=True out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  t=+4.21s phase=children | ticker: alive=False out=exited wave=main dl=+5.11 | console_sink: alive=False out=None wave=main dl=+5.11 | ProcessManager: alive=True out=None wave=main dl=None
  --- сводка прогона 3
  имена в processes: ['ProcessManager', 'console_sink', 'ticker']; ответов всего=405, после команды=327
  (а) ответов, где ticker.stop_outcome=='exited' при console_sink.alive==True: 310 (порог >= 5)
  (б) записей PM=405, из них stop_outcome != None: 0 (ожидается 0)
  (в) записей=1215, stop_wave != 'main': 0 (ожидается 0)
  (г) живых записей с deadline=325 (min=5.105149984359741 max=5.105149984359741 относительно t_cmd; допустимо [0; 6]); мёртвых с deadline=315; нарушений=0 []
  (д) финал (последний ответ опроса, phase=children): {'ticker': 'exited', 'console_sink': None}; ответов с phase=='done': 0, последний из них: None
min answers_after: 324 max shutdown: 4.46s
```
