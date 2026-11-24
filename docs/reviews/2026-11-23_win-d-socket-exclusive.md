# Win-D: `SocketChannel.start` на Windows занимал занятый порт — отчёт исполнителя

Дата: 2026-11-23. Роль: teamlead (исполнитель). Заявка: `plans/queue/inbox/2026-11-23_lane-T-py314_14.md`.
Дерево: `D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles--wf-a` (detached, c7a2ccca7). Коммита нет.
Патч: `C:/Users/INNOTECH/AppData/Local/Temp/claude/65f734dde6ea3dc7/ad054591-efb3-40e2-a684-2e0d7b7b2962/scratchpad/patches/wf-d1.patch`.

## Итог

Причина подтверждена: `socket_channel.py` ставил `SO_REUSEADDR` до `bind`. На Windows этот флаг
разрешает второго живого слушателя на том же порту. Исправление по DESIGN: приватная функция
`_set_exclusive_bind` (`SO_EXCLUSIVEADDRUSE`, если он есть у модуля `socket`, иначе `SO_REUSEADDR`),
её вызов стоит вместо прямого `setsockopt`. Публичный API не изменился, импорта из Services нет.

## Доказательство импорта (cwd framework-тестов и корень worktree)

```
D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles--wf-a\multiprocess_framework\__init__.py
```

## Красный тест до правки

`backend_ctl/tests/test_token_handshake.py` (через гейт, light):
`1 failed, 10 passed, 1 skipped`; `G3 unclosed roots: 0`; `G4 threads without scope path: 1`
(`test_failed_bind_leaves_other_token_intact :: socket-ch-accept-backend_ctl`); падение `:182 assert ch_b is None`.

## Приёмка после правки (каждый файл — отдельный вызов гейта)

| Файл | Результат | G3 | G4 |
|---|---|---|---|
| backend_ctl/tests/test_token_handshake.py | 11 passed, 1 skipped | 0 | 0 |
| router_module/tests/test_socket_channel_exclusive_bind.py (новый) | 3 passed | 0 | 0 |
| router_module/tests/test_socket_channel.py | 29 passed | 0 | 0 |
| router_module/tests/test_socket_channel_auth.py | 44 passed, 1 skipped | 0 | 0 |
| router_module/tests/test_socket_channel_auth_hazards.py | 12 passed | 0 | 0 |
| router_module/tests/test_socket_channel_hol_acceptance.py | 6 passed | 0 | 0 |
| router_module/tests/test_socket_channel_hol_hazards.py | 10 passed | 0 | 0 |
| router_module/tests/test_socket_client.py | 3 passed | 0 | 1 (до правки тоже 1) |
| router_module/tests/test_socket_client_hazards.py | 11 passed | 0 | 0 |
| router_module/tests/test_socket_client_max_line_acceptance.py | 3 passed | 0 | 0 |
| router_module/tests/test_router_manager.py | 137 passed | 0 | 5 (до правки тоже 5) |

G4 в `test_socket_client.py` (`test_drop_during_request_errors_within_timeout :: socket-ch-inbound-backend_ctl`)
и в `test_router_manager.py` (5 потоков `router-sender-rr_cmd` / `router-sender-rr_nocm`) есть и с поведением
до правки: прогон под INJ-1 (флаг как до правки) дал те же числа. Эти утечки к задаче не относятся.

`ruff check -q` на два файла: exit 0.

## Переоткрытие порта после close на Windows (гарантия 2) — воспроизведение сырыми сокетами

Скрипт `scratchpad/repro_rebind.py`: слушатель на 127.0.0.1, close, повторный bind в том же процессе.
Windows 10 Pro 19045, Python 3.12.12:

```
reuseaddr  dual                                 OK
none       dual                                 OSError 10048
exclusive  dual                                 OSError 10048
exclusive  idle                                 OK
exclusive  accepted_still_open                  OK
exclusive  client_closes_first                  OK
exclusive  server_closes_first_client_open      OK
exclusive  server_closes_first_client_closes    OK
```

(Строки `reuseaddr` и `none` для остальных сценариев — тоже `OK`.) Вывод: на этой сборке Windows
`SO_EXCLUSIVEADDRUSE` не мешает переоткрыть порт сразу после close — ни в TIME_WAIT, ни при ещё
открытом принятом соединении. Документация Microsoft описывает оговорку про активные принятые
соединения; на loopback в Win10 19045 она не воспроизвелась.

## Инъекции (предсказания записаны ДО прогонов: `scratchpad/patches/wf-d1-injection-predictions.md`)

| Инъекция | Ожидалось красных | Получилось красных | Совпало |
|---|---|---|---|
| INJ-1: в `_set_exclusive_bind` всегда `SO_REUSEADDR` | `test_failed_bind_leaves_other_token_intact`; `test_second_start_on_busy_port_fails_and_first_keeps_serving` | те же два (backend_ctl 1 failed, 10 passed, 1 skipped; новый файл 1 failed, 2 passed) | да |
| INJ-2: `close()` не закрывает серверный сокет | `test_new_channel_reopens_port_after_close_with_live_connection`; тест «тот же объект» — зелёный (предсказано: GC закрывает старый сокет при перезаписи `_server_sock`) | `test_new_channel_reopens_port_after_close_with_live_connection` **и** `backend_ctl::test_teardown_closes_port_even_if_token_check_fails` | нет: лишний красный |
| INJ-2b: `close()` не закрывает принятые клиентские сокеты | ни одного | ни одного (11 passed, 1 skipped; 3 passed) | да |

Расхождение INJ-2 (находка): существующий `test_teardown_closes_port_even_if_token_check_fails`
уже сторожит «teardown освобождает порт»; я его не предсказал. Это не дефект: у гарантии 2 два
независимых сторожа. Тест «тот же объект перезапускается» под INJ-2 зелёный, как предсказано:
он проверяет повторный `start()` того же объекта, но не сторожит освобождение порта в `close()`.

INJ-2b — вариант из заявки «exclusive + не закрывать сокет». На этой Windows он не может
сделать тест красным: сырой repro (`exclusive accepted_still_open OK`) это показывает. Поэтому
сторож гарантии 2 — INJ-2 (порт не освобождён).

Патчи инъекций (относительно исправленного файла): `scratchpad/patches/wf-d1-inj1.patch`,
`wf-d1-inj2.patch`, `wf-d1-inj2b.patch`. В итоговый патч они не входят; файл восстановлен,
`git diff --no-index --stat` против копии исправленного файла пуст (exit 0).

## Изменённые файлы

- `multiprocess_framework/modules/router_module/channels/socket_channel.py:60` — `_set_exclusive_bind`;
  `:196` — вызов вместо `setsockopt(SO_REUSEADDR)`.
- `multiprocess_framework/modules/router_module/tests/test_socket_channel_exclusive_bind.py` — новый, 3 теста.

## Что я истолковал, а не выполнил буквально

- Тест на класс ошибки — новый файл, а не дополнение `test_socket_channel.py`: тот файл про I/O,
  новый держит обе гарантии Win-D вместе.
- «Переоткрытие тем же процессом» проверено двумя тестами: новый канал при живом соединении (так
  делает PM: `setup_backend_ctl_channel` создаёт новый `SocketChannel`) и повторный `start()` того же объекта.
- Инъекцию гарантии 2 выбрал «close() не закрывает серверный сокет»: вариант из заявки
  («exclusive + не закрывать принятый сокет») на Windows не краснеет, доказано запуском.

## Что осталось открытым / ненадёжным

- Не проверено на macOS/Linux, кроме логики по коду: там работает ветка `SO_REUSEADDR`;
  на Windows эту ветку не воспроизвести (там `SO_REUSEADDR` даёт двойного слушателя).
- Не проверено: чужой слушатель на `0.0.0.0:<порт>` против нашего на `127.0.0.1:<порт>` (смешанные адреса).
- `multiprocess_framework/modules/process_manager_module/DECISIONS.md:2920` пишет «на Windows при
  безусловном `SO_REUSEADDR` не проверено, `OPEN_QUESTIONS`». Теперь проверено и исправлено; текст ADR
  и пункт `docs/claude/OPEN_QUESTIONS.md` надо обновить. Это вне FILES — решает lead.
- Порядок «bind → write_token» в `backend_ctl_endpoint.py` менять не нужно: теперь bind на занятом
  порту падает до `write_token`, красный тест это подтверждает.
- Кандидаты на общий helper (отдельная задача; слои не дают импортировать из Services во framework):
  `Services/code_reader/core/sink.py:35`, `Services/code_reader/tools/id3000_tcp_sink.py:87`,
  `Services/robot_comm/server/sim_robot.py:70`, `Plugins/sim/robot_host/plugin.py:557-565`.
  `Services/code_reader/tools/reader_sim.py:89` ставит безусловный `SO_REUSEADDR` (dev-инструмент,
  на Windows та же ловушка) — не трогал.
- Предсказание INJ-2 было неполным (см. расхождение выше).

memory hits: `scripts/memory/search.py SO_REUSEADDR exclusive bind port windows` ->
`docs/claude/memory/feedback_a_diff_based_rescue_omits_untracked_files.md` (учтён: `git add -N` перед `git diff`);
остальные совпадения не по теме. Поиск выполнен после первой правки, а не до неё (нарушение порядка §8).
