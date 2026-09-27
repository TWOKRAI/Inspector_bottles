# T2.3b — RED-тесты sim v2: CVT_JOB, watchdog, мост ПЧ, TCP-сервер `--protocol v2`

Роль: tester (независимый, до реализации). Ворктри: `.claude/worktrees/team-t23b-tester`
на коммите `c2a5c28f`. Не коммичено (по инструкции брифа).

## Файлы

- `Services/robot_comm/tests/test_sim_v2_cvt_wdg_vfd.py` — 8 тестов, core-level (`core.tick()`, без wall-clock).
- `Services/robot_comm/tests/test_sim_v2_tcp.py` — 2 теста, e2e через TCP (subprocess CLI).

## Прогон (команда из брифа)

```
PYTHONPATH=$PWD .venv/bin/python -m pytest -q --tb=line \
  Services/robot_comm/tests/test_sim_v2_cvt_wdg_vfd.py Services/robot_comm/tests/test_sim_v2_tcp.py
```

Итог: **8 failed, 1 passed, 1 error** = 9 RED + 1 GREEN (`test_v1_server_still_default`) — ровно
как требует приёмка.

## RED-причины (дословно из вывода)

| Тест | Причина |
|---|---|
| `test_cvt_job_on_moving_belt_done` | `TypeError: RobotSimCoreV2.__init__() got an unexpected keyword argument 'belt'` |
| `test_cvt_job_flags_pick_z_place` | `AssertionError: ... {'status': 2, 'errno': 14, ...}` — NAK E_INTERNAL (CVT_JOB в `_UNIMPLEMENTED_OPS`) |
| `test_wdg_trips_on_battle_timeout_3000ms` | `assert 0 == 2` — TLM_WDG_STATE никогда не становится 2 (watchdog не реализован) |
| `test_wdg_heartbeat_inside_window_prevents_trip` | тот же контроль: `AssertionError: контроль: таймер должен был сработать` |
| `test_wdg_disabled_when_zero` | тот же контроль |
| `test_halt_really_stops_belt` | `TypeError: ... unexpected keyword argument 'belt'` |
| `test_vfd_link_failure_async_e_vfd_link` | `TypeError: ... unexpected keyword argument 'belt'` (до вызова `inject_vfd_link_fault()` даже не дошло) |
| `test_tlm_spd_pct_written_during_motion` | `assert 0 == 60` — TLM_SPD_PCT никогда не пишется |
| `test_v2_server_ping_and_move_over_tcp` | ERROR в фикстуре: `argparse: unrecognized arguments: --protocol v2` (код 2) |

Все девять — по существу отсутствующей функциональности, ни одна не падает из-за бага хелпера
(`u16`/`mm`/`cmd`/`read_res`/`run_to_done`/`_write_cmd`/`_wait_res` — общая логика проверена
косвенно: `test_v1_server_still_default` прошёл по такой же по духу инфраструктуре (real TCP
round-trip), и внутри `test_sim_v2_cvt_wdg_vfd.py` `cmd()`/`PARAM_SET` уже реально ACK'ают там, где
опкод существует — т.е. хелперы сами по себе рабочие).

`test_v1_server_still_default` — **GREEN уже сегодня**: реальный TCP-раунд-трип к
`python -m Services.robot_comm.server` без `--protocol` (флага, которого ещё нет) через
`RobotClient`, `telemetry.spd_pct == 50` (дефолт v1 sim-ядра).

## ASSUMPTIONS (нет formal interface.py у CVT/WDG/VFD)

- **A1** — хук инъекции обрыва связи ПЧ называется `core.inject_vfd_link_fault()`, по аналогии с
  уже принятым `core.inject_motion_fault()` (тот же файл/паттерн). protocol-spec §10.5 не называет
  механизм для симулятора явно. Тест даже не дошёл до вызова (упал раньше на `belt=` kwarg) — сам
  хук НЕ проверен ни разу за время работы, это чистое предположение по неймингу.
- **A2** — `RobotSimCoreV2(..., belt=BeltDrive(...))` — конструктор принимает готовый `BeltDrive`
  по инструкции design "reuse server/belt.py BeltDrive" и по паттерну v1
  (`core_kwargs["belt"] = BeltDrive(...)` в `server/__main__.py`).
- **A3** — регистр FREQ моста ПЧ (0x1202) — Гц×100. Подтверждено **фактом**, не домыслом: живой
  v1-тест `test_sim_e2e.py::test_vfd_mirror_over_bridge` пишет `("w", 0x1202, 5000)` == 50.00 Гц.
- **A4** — направление ленты по умолчанию (P_BELT_DIR=1) вдоль +Y, как в v1
  (`registers.py: BELT_UX, BELT_UY = 0.0, 1.0`). Использован только для выбора геометрически
  безопасной точки pick в `test_cvt_job_on_moving_belt_done` — тест НЕ проверяет саму ось трекинга.
- **A5** — после срабатывания watchdog следующее изменение HB_PC заново взводит таймер.
  protocol-spec §9.2 говорит про взвод «с момента старта программы», про повторный взвод после
  срабатывания молчит. Использовано в `test_wdg_heartbeat_...`/`test_wdg_disabled_when_zero`
  (обе делают CLEAR_ERR + новый HB_PC после контрольного срабатывания).

## Что я интерпретировал, а не следовал буквально

- **`test_cvt_job_on_moving_belt_done` проверяет только наблюдаемый исход** (DONE_SEQ без промаха,
  итоговая поза == `P_PLACE_*`), а НЕ формулу трекинга `trav=(enc_now-ecap)*FACTOR_MM` — сам
  алгоритм трекинга pick-точки нигде в protocol-spec не описан (это v1-Lua implementation detail,
  см. `core/registers.py` комментарий, который сам v1-only и не переносится буквально в v2-параметры
  один в один). Пин формулы был бы моей собственной моделью, а не контрактом.
- **`test_cvt_job_flags_pick_z_place` не проверяет pick_z напрямую через телеметрию** — в проводе
  нет наблюдаемого сигнала "какой pick_z использован" (робот в итоге стоит у place, не у pick).
  Вместо этого — дифференциальная схема: один и тот же заведомо невалидный аргумент либо
  игнорируется (flags-бит выкл, ACK), либо валится (flags-бит вкл, NAK E_RANGE). Это сильнее прямого
  чтения телеметрии и не требует знать внутренний путь валидации.
- **`test_wdg_heartbeat_inside_window_prevents_trip` и `test_wdg_disabled_when_zero` получили
  контрольную часть** (сначала доказать, что таймер СПОСОБЕН сработать, иначе «не сработал»
  неотличимо от «вообще не реализован» — оба теста были бы vacuous PASS уже сегодня без контроля,
  что нарушило бы «9 RED» приёмки). Добавлено сознательно, не было в исходном REDS-списке дословно.
- **`test_halt_really_stops_belt` проверяет остановку через TLM_BELT_MMS и неподвижность
  TLM_ENC**, а не приватное состояние `BeltDrive` — чёрный ящик, наблюдаемый эффект, не имя API.

## Что осталось открытым / ненадёжным

- **A1 (`inject_vfd_link_fault`) не подтверждён вообще** — тест ни разу не выполнился дальше
  конструктора (`belt=` уже упал раньше). Если разработчик назовёт хук иначе, тест провалится с
  `AttributeError` — тоже валидный RED, но имя в контракте по факту не проверено рантаймом.
- **A4 (ось ленты +Y) непроверяема тестом** — если реальная реализация выберет другую ось по
  умолчанию, `test_cvt_job_on_moving_belt_done` всё ещё может пройти (геометрия с запасом,
  дрейф по любой из осей X/Y останется в пределах кольца зоны для выбранных точек) или потребует
  минимальной правки координат — не отражает реальный риск в контракте, чисто geometрическая
  подстраховка с моей стороны.
- **Скейл FREQ (A3) подтверждён только по v1**; если v2 сознательно сменит масштаб (protocol-spec
  прямо говорит "заморожен как в v1", но не даёт число явно в прочитанном мной куске текста) —
  тест сломается на уровне "лента не поехала" (уже есть явная диагностика `assert enc_mid >
  enc_at_capture`), не тихо.
- **TCP-тест `test_v2_server_ping_and_move_over_tcp` не проверял РЕАЛЬНОЕ поведение сервера ни
  разу** — умер на `--protocol` парсинге раньше любого сетевого обмена, поэтому весь путь
  `ModbusSdkClient`/`_write_cmd`/`_wait_res` для v2-мейлбокса невалидирован рантаймом (только
  синтаксически, через py_compile/collection). Разработчику стоит перепроверить сам провод (byte
  order, FC-коды) при первом реальном прогоне.
- **qex не проверялся** — по брифу «qex is DOWN (Ollama off)», использован только grep/чтение.
- Полный список ASSUMPTION см. выше и докстринг `test_sim_v2_cvt_wdg_vfd.py` (секция ASSUMPTIONS,
  A1–A5) — не дублирую текст.

Boundary: задача закрыта. Дальше — `/dev:implement Task T2.3` от developer/teamlead к этим двум
файлам как к спецификации.
