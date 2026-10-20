# L-9, остаток: окна стопа PM, ожидание на приёмном потоке, три конечных состояния (Q4, Q5, Q2)

Сессия inspector-bottles-07, полоса F, стадия 1 (только анализ). Код не правил, не коммитил. Дерево main = a5485097a.
qex не использовал (Ollama не работает): git grep / rg по путям, чтение кода.
memory hits: scripts/memory/search.py blocking wait receive thread stop -> feedback_unblocking_signal_at_the_moment_of_fact.md, feedback_poller_misses_submillisecond_window.md (по описанию к вопросу относятся косвенно).
Пути ниже — от multiprocess_framework/modules/, если не указано иное. pm.py = process_manager_module/process/process_manager_process.py.

## Пробы (через machine_gate.sh light inspector-bottles-07)

Скрипт: C:/Users/INNOTECH/AppData/Local/Temp/claude/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/75e22f49-3986-4081-9b95-e2844bfd7ac0/scratchpad/inv07/probe_stop_wait.py.
Настоящие RouterManager, QueueChannel, ChildProcessStop, open_scope("pm/stop", budget 5,0, reserve 2,0) — как в
ProcessRegistry._stop_many; idle = pump_inbound() + сон остатка (как pm.py:3660-3679). Ребёнок — фейк (is_alive), канал —
queue.Queue, не pipe mp.

| Проба | Вход | Наблюдение |
|---|---|---|
| P1 | обработчик probe.stop в receive() ждёт ребёнка, которому нужно 8 с; вторая команда кладётся на +1,0 с | terminate_at = +5,0 с, обработчик вернулся +5,09 с, вторая команда исполнена +5,09 с; WARNING «Process devices did not stop in 5.0s, terminating» |
| P3 | на +1,0 с в канал кладётся type=response с cid ждущего request() | resolved_inside_wait=False, stash_after_wait=2, resolved_after_next_receive=True |
| P2 | поток 2000 сообщ/с в PM_system, ожидание 3 с | буфер полон на 2,09 с, max_stash=4188, после этого pump переносит 0, в канале осталось 1816, один WARNING; следующий receive() отдал 4096 |
| P2 | 600 сообщ/с, 8 с | полон на 6,84 с (прогноз 4096/600 = 6,83 с), max_stash=4108, в канале осталось 701 |
| P2 | 450 сообщ/с, 8 с | не заполнился, max_stash=3580 (прогноз 450 × 8 ≈ 3600) |

## Q4. Окна стопа PM и штатный стоп робота с возвратом домой (секунды)

### Откуда числа 3,0 / 5,0 / 7,0 / 8,5

- Одно число shutdown_timeout (конфиг PM, по умолчанию 5,0) -> stop_budget() (process_manager_module/core/stop_budget.py:73-96):
  work_s 3,0, infra_s 1,0 (ребёнок: 0,8 × g, infra = min(1,0, четверть)), pm_graceful_s 5,0, pm_total_s 7,0 (+ TERMINATE_GRACE_S 1,0 + KILL_CONFIRM_S 1,0, :38-39), outer_s 8,5 (+ PM_TEARDOWN_MARGIN_S 1,5, :41).
- 3,0 с = work_s: бюджет сегмента work корня самого ребёнка (process_module/core/process_module.py:366-380, корень = work_s + infra_s = 4,0 с). Ребёнок получает словарь через конфиг (process_registry.py:172-173, setdefault), раннер принимает его (process_manager_module/runner/process_runner.py:61-80, :407).
- 5,0 с для одиночных стопов — ДРУГОЙ ключ: stop_process_timeout конфига PM (pm.py:3694 process.stop/restart, :1848 откат switch, :4250 стоп топологии). Это не stop_budget. На системном стопе — pm_graceful_s (pm.py:3696, корень PM ADR-PMM-036).
- Эскалация: Scope.close -> join_until(срок) -> kill() = terminate() -> окно 1,0 -> настоящий kill() -> окно 1,0 (child_process_stop.py:172-228, base_manager/core/lifetime.py:568-654).
- Спавнер: launcher/spawner.py:155-186 — внешний join PM = outer_s 8,5 с, потом guard бьёт группу.

### На ребёнка или нет

- Окно PM — НЕ на ребёнка: stop_process_timeout и shutdown_timeout читаются из конфига PM (get_config PM), одно число на всех.
- Ребёнок может иметь свой stop_budget в своём конфиге процесса (явный ключ сильнее, process_registry.py:173). Это меняет только сегменты внутри ребёнка; PM всё равно бьёт terminate() по своему окну. Больший work_s у ребёнка, чем окно PM, бессмыслен.
- Путь «ключ stop_budget из рецепта/топологии до конфига ребёнка» не проверял. ADR-PMM-035 (г): типизированный GenericProcessConfig ключ отбрасывает, раннер читает сырой конфиг.
- Чтобы 8 с поместились в work_s при системном стопе: shutdown_timeout не меньше (8 + 1) / 0,8 = 11,3 с. Тогда pm_total_s около 13,3 с, outer_s около 14,8 с — для ВСЕХ детей системы.

### Ребёнок, чей стоп длится 8 с

(a) process.stop — исполняется на message_processor (pm.py:631-636 -> stop_process :3681-3695 -> stop_one -> _stop_many process_registry.py:446-476).
- По чтению: корень ребёнка ограничивает сегмент work сроком ~3,0 с; поток, который не успел, — выживший, код 76 (ADR-PMM-036). Где именно пойдёт возврат домой T5.3e (поток work, daemon или нет) — не проверял.
- Если ребёнок не вышел сам: PM шлёт terminate() на 5,0 с (P1). На Windows это TerminateProcess, exitcode -15: возврат домой обрывается посреди движения.
- Ответ команды — success: True: смерть подтверждена (process_registry.py:470-472). Ответ не различает «вышел сам» и «убит»; разница — только WARNING в логе.

(b) system.shutdown — обработчик только взводит system_stop_event + свой stop_event и сразу отвечает (pm.py:666-681).
- Дети гаснут параллельно. Раннер PM закрывает корень: сначала workers (с message_processor), потом children со сроком pm_graceful_s 5,0 + резерв 2,0 (ADR-PMM-036). Ребёнку 8 с: terminate() на ~5,0 с от PM, раньше внешних 8,5 с спавнера.
- pump_inbound здесь не работает: message_processor уже закрыт, depth = 0 (ADR-PMM-037, «Не покрыто»). Защиты от L-9 на этом пути нет.

(c) process.restart — pm.py:3700-3789, всё на message_processor:
- stop_process(mark_reader_gone=False) (то же окно 5,0 + эскалация);
- remove_process, register_process(reuse_queues), _drain_process_queues (:3733);
- create_and_register, start;
- apply_priority со time.sleep(0.1) (core/process_priority.py:144);
- _wait_processes_ready до start_ready_timeout_s, по умолчанию 0,5 с (:3767-3770).
Ответ — после всего этого: примерно 5,1 с + спавн + до 0,5 с.

### Чего PM не делает во время ожидания и сколько

Длительность одного ожидания — до stop_process_timeout + 2,0 = 7,0 с. topology.apply стопит группу в одном окне, затем ждёт барьеры готовности. Во время ожидания (router_manager.py:1625-1673 переносит, не исполняет):

- Не исполняет НИ ОДНОЙ команды: backend_ctl, GUI, process.relay, рестарт супервизора (команда в свою очередь, process_monitor.py:1476-1481), команду system.shutdown.
- Не разбирает heartbeat, state.changed, записи observability: всё уходит в буфер.
- Не отвечает на запросы. backend_ctl: SocketBridgeAdapter.on_inbound ждёт router.request(timeout=5.0) по умолчанию (router_module/adapters/socket_bridge_adapter.py:51, :85, :98). Любая команда backend_ctl, пришедшая во время стопа, получает таймаут через 5 с; сам process.stop дольше 5 с тоже возвращает таймаут, хотя исполнен.
- Продолжают работать:
  - поток ProcessMonitor (свой цикл, process_monitor.py:676-684): is_alive, сроки heartbeat (heartbeat_timeout 15 с, pm.py:171). Heartbeat не разбираются, их возраст растёт; при цепочке ожиданий больше 15 с возможен ложный таймаут heartbeat (не проверял);
  - read-потоки сокета backend_ctl: принимают и отправляют;
  - поток раннера PM: опрашивает стоп-события. Закрытие окна GUI и harness.stop() взводят system_stop_event мимо очереди и не ждут.

### Что PM обязан обслужить во время стопа ребёнка

- Команды GUI любому процессу, кроме GUI и PM, идут через process.relay PM (frontend_module/bridge/command_sender.py:97-110). Во время стопа одного процесса GUI не может доставить команду другому процессу до 7 с — например, стоп робота в devices, когда стопится не devices. Использует ли кнопка стопа робота в GUI именно этот путь — на уровне виджета не проверял. Это главный довод, что PM не должен быть слепым на время стопа.
- Команда system.shutdown во время process.stop исполняется ТОЛЬКО после возврата ожидания. P1: положена на +1,0 с, исполнена на +5,09 с. Код: pump_inbound не диспетчеризует; следующий receive() берёт буфер раньше pipe (router_manager.py:1598-1603).
- Взвод system_stop_event из GUI или спавнера очередь не ждёт.
- По чтению: если раннер PM закроет workers, пока message_processor ещё внутри стопа, корень и обработчик стопят одного и того же ребёнка с двух потоков (два ChildProcessStop). Не воспроизводил.

## Q2. Когда pump_inbound перестаёт вычерпывать (рассуждение + P2)

- Условие: перед каждым poll канала stash >= POLL_DRAIN_CEILING (4096) -> канал пропускается, один WARNING (router_manager.py:1653-1658).
- Один poll(0.0) вынимает до 4096 (router_module/channels/queue_channel.py:101-134), поэтому граница — 2 × 4096 − 1 на канал; в P2 max_stash = 4188 и 4108.
- Во время ожидания буфер НЕ убывает никогда. Забирает его только _take_stashed из _poll_all_channels (:1599-1623), то есть следующий receive(), а поток внутри обработчика; вложенного receive в PM нет. После заполнения вычерпывание стоит до конца обработчика (P2 pump_moved_zero_after_full=True).
- Потолок — на канал: system, state, observability по 4096 каждый.
- Разбор после возврата: не больше 4096 на канал за такт, такт message_processor + 10 мс сна (process_module/threads/system_threads.py:81-89).

Формула. Обозначения: r — суммарный темп записей в ProcessManager.system от всех писателей (сообщ/с); m — средний размер сообщения; B около 8 КБ — pipe Windows (по CPython не сверял); T — время от начала ожидания до момента, когда хвост останавливаемого ребёнка целиком лёг в pipe.
- Буфер полон в t_full = 4096 / r (P2: 2,09 с при 2000/с; 6,84 с при 600/с).
- Затем pipe заполняется за t_pipe = B / (r × m).
- Зависание возможно, если T > t_full + t_pipe. Порог по темпу: r* = 4096 / T (t_pipe мал при большом r).

| T | r* |
|---|---|
| 0,75 с (devices сегодня, +0,58 - 0,74 с до хука) | около 5 500 сообщ/с |
| 3 с | около 1 370 сообщ/с |
| 7 с (весь бюджет PM) | около 585 сообщ/с |
| 8 с (возврат домой, если окна поднять) | около 510 сообщ/с |

- Стенд около 100 сообщ/с (оценка отчёта Task 1.8) — далеко ниже. Порог падает обратно пропорционально длине стопа: для T5.3e с окнами в секунды (в) теряет запас линейно.
- Pipe ProcessManager.system ОБЩИЙ для всех писателей: это одна очередь PM (PM регистрирует свои HUB_QUEUES под своим именем, pm.py:262; дети пишут в неё через карту маршрутов). Замер стенда (plans/lifecycle-stop-ownership.md:367-370, отчёт Task 1.8 :17): непрочитанное в pipe — сумма всех отправителей. Внутреннюю сериализацию записи mp.Queue на Windows не сверял.

## Q5. Три конечных состояния

### (в) «ждать, вычерпывая» как политика фреймворка, request() переписать на неё

- Безопасно ли для request(). Сегодня — нет: P3 показал, что ответ, ушедший в буфер, не разрешает pending до следующего receive(). Нужен новый путь «вычерпать и сопоставить»: искать в буфере type=response с cid из _pending_requests и вынимать не по порядку FIFO. Сопоставление шло бы мимо recv-middleware (receive зовёт _recv_mw.apply раньше резолва, :1451, :1477-1481); прецедент обхода — самоответ ADR-RTR-013.
- Реентерабельности нет (команды не исполняются), но это меняет только «не дедлок» на «простой»: приёмный поток стоит до таймаута request() (5 с), вся почта процесса не разбирается. Именно это запрещает ADR-RTR-011 (замер: 5 с простоя на каждый resync, ADR-SS-022).
- Принципиальный предел: (в) разрывает цикл, только если ожидаемому нужно, чтобы мы ПРОЧИТАЛИ (feeder ребёнка). Если ожидаемому нужно, чтобы мы ИСПОЛНИЛИ (его ответ зависит от нашей команды), (в) не помогает.
- Файлы:
  - router_module/core/router_manager.py: _assert_not_receive_thread (:1023-1046) снять или сделать опцией; цикл «pump + match» в request() (:1048-1137); около 80-120 строк.
  - Тесты: router_module/tests/test_request_contract_guard.py (C3: отказ быстрее 0,001 с) переписать; state_store_module/tests/test_resync_starvation_acceptance.py (C3/C4/C5) меняет смысл.
  - ADR: ADR-RTR-011 отменяется, ADR-RTR-014 расширяется, срабатывает предупреждение ADR-SS-022.
- Риск высокий: громкий отказ превращается в тихий простой; потолок 4096 становится пределом для любого ожидателя.

### (б) ожидание вне message_processor + отложенный ответ

- Механизм отложенного ответа ЕСТЬ:
  - manages_own_reply в metadata команды: авто-ответ пропускается (router_manager.py:1362);
  - reply_to_request(request_msg, result) можно звать с любого потока. Корреляция по request_id / data.correlation_id (:1293-1298), адресат data.reply_to / reply_to / sender. Самоответ (backend_ctl ставит reply_to = имя хоста, socket_bridge_adapter.py:93-95) разрешается под _pending_lock (:1319, :1248-1272); чужой адресат — send() в его system-очередь;
  - прецедент: обёртка process.command отвечает сама (pm.py:285-291, :3319-3331).
- Оговорка: команды стопа приходят двумя дверями — прямо (process.stop от backend_ctl, _dispatch_command) и вложенно в process.command (pm.py:3296, handle_command внутри обёртки). Отложенный результат нужен обеим; обёртке нужен признак «ответ позже».
- Кто зависит от «ответ после смерти»:
  - backend_ctl process.stop/restart ждёт ответ не дольше 5 с; отложенный ответ ничего не ломает — сегодня ответ дольше 5 с уже таймаут;
  - process_restart_verified (backend_ctl/driver.py:1065-1130) таймаут ответа терпит и подтверждает опросом supervision.status по pid + instance_restarts — от момента ответа не зависит;
  - GUI: stop_process/restart_process без ответа (multiprocess_prototype/frontend/bridge/process_manager_proxy.py:140-144); варианты _async — запрос с таймаутом 30 с (frontend_module/bridge/command_sender.py:31, :253), результат в колбэк (process_manager_proxy.py:126-134, topology.apply :97); отложенный ответ с тем же содержимым совместим;
  - recipe.activate (recipe/service.py, apply_topology синхронно, разбирает success): исполнять внутри той же FIFO или тоже отложить;
  - супервизор: команда в свою очередь без ответа;
  - harness: не проверял (по плану Task 1.1 — system_stop_event).
- Неявная сериализация сегодня (всё на одном message_processor, в порядке прихода):
  - жизненный цикл: process.start/stop/restart/pause/resume/create, topology.apply, recipe.activate, wire.setup/teardown, system.shutdown, рестарт супервизора (на это опирается докстринг process_monitor.py:1476-1481);
  - прочее: process.relay, telemetry.broadcast, брокер observability.tail.*_all (намерение переживает рестарт), supervision.status, heartbeat и state.changed.
- Одна FIFO жизненного цикла СОХРАНЯЕТ порядок жизненных команд между собой (stop / restart / topology / рестарт супервизора).
- ТЕРЯЕТ порядок жизненных команд относительно всего остального. Конкретная гонка по чтению: process.relay в ребёнка, которого FIFO сейчас перезапускает. Очередь переиспользуется (reuse_queues по умолчанию True, pm.py:3727-3733), команда ляжет в неё и будет ВЫЧЕРПАНА _drain_process_queues; сегодня relay ждёт конца рестарта и доходит. Значит, через FIFO должны идти и relay в цель, которая сейчас в работе, и все команды, меняющие _process_configs, реестр, _routing_epoch, провода, журнал телеметрии; читатели (supervision.status, process.list) — под локом.
- system.shutdown обязан обходить FIFO: взвести события сразу, снять очередь. Иначе он встанет за стопом, как сегодня.
- Отдельная FIFO на ребёнка (_run_when_child_ready, pm.py:1499-1587): topology.apply трогает многих детей, нужен общий барьер — на деле та же одна FIFO, только сложнее. Не советую.
- Поток FIFO живёт в work корня PM (ADR-PMM-036); порядок закрытия: FIFO, потом дети.
- Цена:
  - код: новый process_manager_module/core/lifecycle_executor.py около 150-200 строк; pm.py около 150-250 строк (обработчики жизненного цикла, отложенный ответ, обёртка process.command, system.shutdown, relay); recipe/service.py около 30-60; process_monitor.py около 10-30;
  - тесты: новые около 400-600 строк; переписать синхронные проверки _cmd_* в test_process_manager_process.py, тесты топологии на возврат apply_topology, R10/R11 test_pm_stop_drains_own_queue_acceptance.py;
  - ADR: новый ADR-PMM-038; ADR-PMM-037 заменяется; pump_inbound (ADR-RTR-014) остаётся публичным контрактом без живого вызывающего — заморозить, не удалять (принцип 3); ADR-RTR-011 не меняется и становится единственной политикой.
- Риски: гонки команд вне FIFO с её мутациями (выше). Опись всех команд PM, что читают или пишут состояние жизненного цикла, — обязательный шаг 0; я её не делал.

### Task 3.1 — quiesce -> ack -> exit

- Убирает: поток записей от останавливаемых детей на системном стопе (все замолкают до выхода) и гонку «свой хвост против соседей» для тех, кто получил quiesce.
- Не убирает:
  - на одиночном process.stop соседи не замолкают — именно они в L-9 забивали pipe (R10b, region_splitter / preprocessor / camera_0);
  - PM всё равно ждёт: сначала ack, потом выход. ack приходит в ProcessManager.system — его кто-то должен прочитать; ждать ack на message_processor — тот же класс дефекта.
- Поэтому Task 3.1 — слой поверх (б) или (в), не альтернатива им. Долгий стоп ребёнка (возврат домой) остаётся вопросом окна на ребёнка.

### Другие места того же класса (обработчик на приёмном потоке ждёт другой процесс)

1. ChildProcessStop.join_until на message_processor — все пути стопа PM (child_process_stop.py:207-228); закрыто pump_inbound.
2. _wait_processes_ready (pm.py:4065-4123): цикл time.sleep(0.05) по mp.Event, без pump. Вызовы: boot-deps :3396, restart :3770 (0,5 с по умолчанию), boot :4179, switch :4220. Дедлока нет (событие вне почты, докстринг :4080-4083), но PM слеп весь timeout_s. Ребёнок, который до ready делает request() к PM, просидит до своего таймаута; есть ли такие дети — не проверял.
3. ProcessPriority.apply_priority: time.sleep(0.1) на каждый start/restart/create (process_priority.py:144; вызовы pm.py:615, :3422, :3643, :3652, :3763). Не ждёт процесс, но держит поток.
4. Не тот класс, но рядом: monitor.stop(wait=True, infra_s) в _ChildrenStop.request_stop (pm.py:4363) — поток раннера; SocketBridgeAdapter.on_inbound -> request() — daemon-поток, законно; ready-gate event.wait (pm.py:1657) — свой воркер, прецедент (б).
5. request() с приёмного потока — громкий отказ (router_manager.py:1023-1046).
6. В Services/Plugins/модулях rg нашёл только внутрипроцессные ожидания (service_module/host.py:150, chain_module/worker_pool/dispatcher.py:151, chain_module/thread_pool/worker_pool_executor.py:103); на каком потоке они идут — не проверял. Полную опись обработчиков дочерних процессов, ждущих другой процесс, не делал.

## Рекомендация по конечному состоянию

(б) с ОДНОЙ FIFO жизненного цикла PM и отложенным ответом; system.shutdown — мимо FIFO; (в) остаётся до её прихода и потом замораживается.

Почему:
1. (б) — единственный вариант, при котором PM не слеп во время стопа: relay команд GUI (включая устройства), backend_ctl, heartbeat и супервизор идут дальше.
2. Длинный штатный стоп (T5.3e) при (б) стоит дёшево; при (в) порог темпа r* = 4096 / T падает с длиной стопа, и PM слеп на всё окно.
3. Политика фреймворка остаётся одна — ADR-RTR-011 «приёмный поток не ждёт другой процесс».
4. Task 3.1 всё равно требует читателя ack вне ожидания.
5. (в) как политику для request() не принимать: это узаконит простой приёмного потока, который ADR-RTR-011 запретил по замеру.

Отдельно, малой задачей: окно стопа на ребёнка (ключ в конфиге процесса вместо одного stop_process_timeout).
Решение владельца для T5.3e, без правок фреймворка: штатный режим как команда устройству «домой» перед process.stop, а не длинный стоп процесса.

## Что осталось открытым / ненадёжно

- Пробы идут на queue.Queue и фейковом ребёнке; pipe Windows 8 КБ и настоящего feeder в них нет. Формула r* — по модели и P2, на стенде не мерена; t_pipe и межканальный порядок не учитывал.
- Где пойдёт возврат домой в devices (поток work, daemon ли он) и что делает корень ребёнка с 8-секундным стопом (код 76 на 3-4 с или terminate PM на 5 с) — по чтению, не проверено.
- Путь кнопки стопа робота в GUI через process.relay — по коду command_sender, виджет не проверял.
- Двойной стоп одного ребёнка (раннер PM + обработчик на message_processor) при system_stop_event во время process.stop — по чтению, не воспроизведено.
- Опись всех команд PM, мутирующих состояние жизненного цикла (шаг 0 для (б)), не делал; оценки строк для (б) и (в) — порядок, не план.
- Ложный таймаут heartbeat при цепочке ожиданий больше 15 с — гипотеза.
- harness и зависимость от момента ответа process.stop — не проверял.
- Почему system.shutdown с 2 роботами дал 0 зависаний из 9 без защиты — не установлено (как и в отчёте Task 1.8).
