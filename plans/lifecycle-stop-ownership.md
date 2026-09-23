# lifecycle-stop-ownership — остановкой и сиротами владеет PM (L-5 + долги приёмки L-2)

- **Slug:** `lifecycle-stop-ownership` · **Ветка:** `fix/lifecycle-stop-ownership` (создать при старте Ф1) · **Дата:** 2026-09-24
- **Статус:** DRAFT — ждёт одобрения владельца
- **Полоса:** B (фреймворк). **Срок-якорь:** Ф1 закрыть **до gui-service Task 1.3a** (у Пульта появится кнопка
  «стоп» по сокету — сегодня она идёт незащищённым путём, см. Task 1.1).
- **Слой:** framework (`process_manager_module`, `shared_resources_module`), `backend_ctl` (harness)
- **Основание:** приёмка CTO плана `lifecycle-graceful-stop` —
  [`docs/reviews/2026-09-24_lifecycle-graceful-stop-cto.md`](../docs/reviews/2026-09-24_lifecycle-graceful-stop-cto.md)
  (ACCEPT_WITH_DEBT), строки L-5 и L-6 в [`QUEUE.md`](QUEUE.md), долги в
  [`lifecycle-graceful-stop.md`](lifecycle-graceful-stop.md) (раздел «Долги», пункты 1–6).

## Зачем — одной фразой

Знание «этот процесс остановлен/убит навсегда» есть только у PM, а пользуются им сейчас сами дети и только на
одном из путей останова. Отсюда три живых дефекта: команда `system.shutdown` возвращает 5.8 с и `terminate`
(1 из 3 прогонов), убитый читатель вешает писателя навсегда, сироты переживают стенд. План переносит власть над
остановкой туда, где знание: в PM.

## Целевое состояние (вердикт CTO, «Как правильно»)

- **Один путь останова.** Любой стоп системы — окно GUI, `harness.stop()`, команда `system.shutdown` (backend_ctl,
  `process_manager_proxy.shutdown_system`, будущий Пульт) — взводит `system_stop_event`. Разных «системных стопов» нет.
- **Метку «читатель ушёл» ставит владелец жизненного цикла.** PM после join/terminate/kill ребёнка, которого не
  собирается перезапускать, взводит метку на его очередях. Самопометка детей на системном стопе остаётся быстрым
  путём. Рестарт — как сейчас: метки нет, очередь переиспользуется.
- **Строка потерь — сигнал, а не шум.** Печатается только при реальной потере (`buffered_dropped > 0`).
- **Сирот нет по построению.** Страховка уничтожения дерева работает на штатном пути; бюджеты вложены
  (внешний > внутреннего); harness знает всё дерево.
- **Оставить:** ADR-SRM-015, `ReaderGoneQueue` как транспорт метки, правило «немаркированную очередь ждать до слива»
  (защищает медленного живого читателя).
- **Не делать** (отвергнуто CTO): закрывать read-конец у не-читателей (несовместимо с `restart_reuse_queues`),
  порядок «источники → приёмники», двухфазный стоп — после Ф1 и L-6 не нужны.

## Соседи — кто чем владеет

| План | Что там про это | Что берём | Что отдаём | Граница / конфликт |
|---|---|---|---|---|
| [`lifecycle-graceful-stop`](lifecycle-graceful-stop.md) (DONE) | ReaderGoneQueue, хук выхода, ADR-SRM-015/016, долги 1–6 | долги 4–6 и L-5 (1)–(3) | ADR-SRM-016 дополняется, не переписывается | закрыт — сюда только ссылки |
| [`transport-single-policy`](transport-single-policy.md) (не начат) | двери транспорта кадров, loan/reclaim, `frame_shm_middleware` | — | **L-6 (кадры и маски 0.3–1.2 МБ через pipe) — туда, не сюда**: это корень окна зависания, но домен — транспорт кадров | этот план не трогает `frame_shm_middleware`, `loan_ledger`, `router_manager` |
| [`2026-09-22_gui-service`](2026-09-22_gui-service/plan.md) (APPROVED ред. 2) | Task 1.3a — серверный `SocketChannel`; кнопка «стоп» Пульта | — | чистый путь `system.shutdown` к старту 1.3a | срок-якорь Ф1 |
| [`observability-closure`](observability-closure/plan.md) (в работе, сессия A) | 4.3b и дальше правят `process_manager_process.py` (форвардеры, хаб); 4.8 — «останов стенда через terminate» | — | закрываем «terminate на `system.shutdown`» | **общий файл `process_manager_process.py`**: правка Ф1 — одна функция `_cmd_system_shutdown` + вызов метки в `stop_many`; мержить маленькими коммитами, перед мержем — `git log main..` соседа |
| [`otel-export`](otel-export.md) (сессия B) | числа останова `otel flush` | — | после Ф1 путь через команду тоже чистый | их числа через команду сдвинутся — предупредить в handoff |
| [`framework-architecture-rework`](framework-architecture-rework/plan.md) (DRAFT ред. 3) | одно окно codemod (Р-9), перенос файлов | — | — | Ф1 файлов не переносит; если окно codemod откроется раньше — Ф1 ждёт или идёт первой |
| `line-sim` (сессия line-sim-5.4, стенд 8765/8766) | живой стенд двух приложений | — | более чистый останов их стенда | порты не пересекаются (наши 8850–8859) |

## Ф1 — PM владеет остановкой (цена S–M, до gui-service 1.3a)

### Task 1.1 — `system.shutdown` = системный стоп

**Level:** Middle · **Assignee:** developer · **Layer:** framework
**Факт:** `process_manager_process.py:639 _cmd_system_shutdown` взводит только `self.stop_event`. Живьём (CTO,
8853–8855): 5.83 / 1.39 / 1.28 с, в первом `Process 'renderer' did not stop in 5.0s, terminating...` при PM exitcode 0.
**Acceptance:**
- [ ] Живьём, `inspection_full`, свободный порт, `BackendDriver.system_command({"cmd": "system.shutdown"})`:
  выход дерева < 2.0 с в **10 из 10**, строк `did not stop in` — 0 (и у спавнера, и у PM), PM exitcode 0.
- [ ] Хук выхода у детей идёт с `system_stop=True` (строка итога или счётчик — наблюдаемо, не по чтению кода).
- [ ] Break-injection ведущего: без правки — возврат к ≥ 5.0 с хотя бы в 1 из 10.
- [ ] Строка в ADR-SRM-016 «Границы» про `system.shutdown` снята со ссылкой на эту задачу.

### Task 1.2 — метку за остановленного/убитого ребёнка ставит PM

**Level:** Senior · **Assignee:** teamlead · **Layer:** framework
**Факт:** читатель, убитый `terminate/kill` (`process_registry.py:334-338`, стрэгглер), метку не ставит; хук писателя
без таймера ждёт вечно (репро CTO `sigkill_repro.py`: «STILL BLOCKED after 3.01s», внешняя метка → мгновенно `(1, 0)`).
**Направление (решает исполнитель после тестера):** PM после join/terminate/kill ребёнка **без последующего рестарта**
взводит метку на очередях этого ребёнка (PM держит их в PSR). Рестарт — не метит (очереди переиспользуются).
**Acceptance:**
- [ ] Изолированно: писатель с кадром > pipe в очереди читателя; читатель убит `kill()`; PM-путь остановки → писатель
  выходит < 2.0 с. Тест не виснет (daemon-поток + дедлайн join).
- [ ] Изолированно: `restart_process` по-прежнему не метит; новое воплощение на той же очереди получает сообщение целым
  (страж тестера из L-2 `TestIndividualStopReaderThenQueueReusedByNewIncarnationGetsMessageIntact` — зелёный).
- [ ] Живьём: `process_restart_verified` для `renderer`, `camera_0`, `storage` — проходит.
- [ ] Break-injection: без метки от PM — изолированный тест висит до дедлайна.
- [ ] ADR (дополнение ADR-SRM-016 или ADR-PM-*): кто ставит метку и когда.

### Task 1.3 — строка потерь только при потере

**Level:** Junior+ · **Assignee:** developer · **Layer:** framework
**Факт:** у PM каждый стоп `queues released to gone readers: 7, buffered dropped: 0` — метка проверяется раньше, чем
feeder выходит по sentinel после `close()` (`reader_gone.py:112-119`, репро CTO `false_alarm.py`).
**Acceptance:**
- [ ] Живьём 10 циклов `inspection_full`: строк итога с `buffered dropped: 0` — 0; строка с `M > 0` печатается
  (изолированный тест с N сообщениями в буфере → литерал N в stderr).
- [ ] H8 из `test_reader_gone_hazards.py` пинит **канал** (настоящий погашенный LoggerManager в ребёнке), а не только формат —
  закрывает открытый вопрос ревью L-2.

### Task 1.4 — сирот нет: страховка дерева, вложенные бюджеты, harness видит детей (L-5)

**Level:** Senior · **Assignee:** teamlead · **Layer:** framework + backend_ctl
**Факт (investigator 2026-09-23, три звена):** (1) `ProcessTreeGuard._terminate_posix_group` на штатном пути — no-op:
`os.getpgid` по уже собранному PM → `ProcessLookupError` → `return True` (`process_tree_guard.py:243, 259-260`);
(2) бюджеты спавнера и PM равны (5.0 / 5.0, `spawner.py:37`, `process_manager_process.py:3471`) — спавнер убивает PM раньше,
чем PM добьёт застрявшего ребёнка; (3) `BackendHarness` снимает поддерево сразу после `start()` — только PM (`harness.py:385-386`).
**Acceptance:**
- [ ] Живьём, искусственно зависший ребёнок (тестовый процесс, игнорирующий стоп): после `harness.stop()` процессов
  `spawn_main` с PPID 1 от этого прогона — **0**; сегодня — ≥ 1.
- [ ] Бюджет внешнего ожидания строго больше внутреннего (литералы в тесте, не выведенные из кода).
- [ ] Break-injection по каждому из трёх звеньев отдельно.

**Исполнение Ф1:** тестер в worktree до кода (1.1+1.3 — один заход; 1.2 и 1.4 — свои) → developer/teamlead →
инъекции ведущего → стенд → reviewer синхронно. Порядок: 1.1 → 1.3 → 1.2 → 1.4 (1.1 и 1.3 дешёвые и снимают шум для замеров 1.2/1.4).

## Ф2 — перемерить после L-6 и решить судьбу ReaderGoneQueue

Зависит от L-6 в `transport-single-policy`. Когда сообщения в data-очередях станут ~1 КБ: 20 циклов стопа по всем путям,
число срабатываний отпуска и `buffered_dropped`. Если отпуск не срабатывает ни разу — ReaderGoneQueue остаётся
страховкой (ADR фиксирует это числом), если срабатывает — искать, какой ещё крупный груз едет через pipe.
**Не делать до L-6.**

## Out of scope

Корень L-6 (крупные грузы через pipe) — `transport-single-policy`; прерываемые `cv2.read()` / Hikvision; порядок останова.

## Открыто до старта

- `SHM fallback failed: No such file or directory: '/output_frames_0'` — в каждом прогоне стенда 2026-09-24 у
  `renderer`/`processor`/`inspector`. Похоже на откат отрисованного кадра в pickle (одна из причин 745 КБ в `gui/data`),
  но не исследовано. Входной факт для L-6, не для этого плана.
