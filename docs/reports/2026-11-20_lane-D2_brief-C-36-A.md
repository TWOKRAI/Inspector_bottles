# C-36, вариант A: очередь на воплощение по умолчанию и громкая проба замка чтения — бриф писателю

> **Стадия 0 (ревью 2026-11-21): CHANGES REQUESTED → замечания C36A-1…11 внесены; раунд 2 (итерация 2 из 2): замечания C36Ar-1…7 внесены, третьего полного ревью нет — проверка механическая (`grep` по счётчикам и предусловию, повтор `git apply --check`)** (итерация 1 из 2 — C36A-1…11). Пометки в тексте: «наблюдено ревьюером стадии 0 на копии» — измерено ревьюером; «предсказано, не прогнано» — новые тесты, новый порядок, шаг 0 теста условия отмены и правки diff по ревью не запускались. Числа автора брифа не менялись, кроме опровергнутых ревьюером (хунк дренажа убран; текст ERROR при A исправлен в требованиях и в «Правки к diff», в самом diff — нет).

Брифу нужен слот писателя (после дня №1 с железом) и файл PM строго после Ф; сам по себе код не меняет. Шаг 0 — тест условия отмены (C36A-5): класс — `heavy`; железа не требует (сима); срок — окно стенда после дня №1 (задание полосы), но тест не требует кода и идёт ДО слота писателя (C36Ar-3; согласовано с документом владельца `2026-11-21_lane-D2_owner-questions-and-stand-task.md`, разд. 3).

Полоса Д2, 2026-11-20. Автор — teamlead (Opus), режим diagnose-and-report. Дерево автора — `a15739023` (= `main` `ad3dc7b72` + документы Д2); база слота и ревью стадии 0 — `dc56f14df` (по ревью: `git diff a15739023 HEAD -- multiprocess_framework/` трогает только `registers_module/core/manager.py` и один тест, строки PM-файла и спавнера не сдвинулись), macOS (Darwin 27.2), Python 3.12.13. Опыты — только в одноразовом worktree `/private/tmp/claude-501/d2-c36a-wt` (`--detach a15739023`, после работы удалён). Импорт доказан строкой `IMPORT /private/tmp/claude-501/d2-c36a-wt/multiprocess_framework/__init__.py` перед каждым прогоном. Все прогоны — через `machine_gate.sh light|medium inspector-bottles-d2`. Входы: `docs/reports/2026-11-20_lane-D2_C-36.md` (механизм и числа), `docs/reports/2026-11-20_cto-review-1.0.md:50` (вердикт «A сейчас, с громкой пробой из C; B после тега 1.0»), `plans/queue/defects.md:283`.

memory hits: `python scripts/memory/search.py restart reuse queues rlock incarnation` -> `docs/claude/memory/feedback_mp_queue_is_async_in_tests.md`, `docs/claude/memory/project_switch_routing_stale.md`.

Обозначения команд ниже:
- `G` = `bash /Users/twokrai/Project_code/Inspector_bottles/scripts/machine_gate.sh`.
- `R` = скрипт-обёртка: `cd <worktree>; export PYTHONPATH=<worktree> INSPECTOR_PID_FILE=/tmp/d2_c36a_pid.json PYTHONUTF8=1; <main>/.venv/bin/python -c "import multiprocess_framework as m; print('IMPORT', m.__file__)"; <main>/.venv/bin/python -m pytest -q --tb=short -p no:cacheprovider "$@"`.

## Цель

1. Рестарт процесса по умолчанию даёт новому воплощению свежие очереди (A). Новое воплощение после `kill -9` в любой момент читает свои очереди. Глухих воплощений 0.
2. Замок чтения (`_rlock`), занятый без живого читателя, на рестарте даёт строку лога с именем процесса и типом очереди и +1 к счётчику — в обоих режимах `restart_reuse_queues` (C36A-6, C36A-1). Текст зависит от режима: при `false` очередь брошена и пересоздана, воплощение не глухо — текст без «глухо»; при `true` — ERROR «глухо». Уровень при `false` — Р2 (открыто). Проба стоит перед `_drain_process_queues` и ловит это раньше, чем дренаж глотает `Empty` молча. Свойство на умолчании A (проба молчит при `reuse=false`) прототип не закреплял: инъекция I7 — `4 passed` (наблюдено ревьюером стадии 0 на копии); закрепляет расширенный тест (в), см. «Тесты».
3. Трафик выжившего писателя к перезапущенному потребителю доходит (через hub-relay PM). Если это не так на настоящем PM — решение A отменяется (условие CTO). Тест этого условия — раздел «Живой тест условия отмены»; он идёт шагом 0, до писателя.

## Что значит «A» сегодня (факты path:line)

Пути — от корня репо, строки — на `a15739023`.

1. **Ключ.** `restart_reuse_queues`. Читается один раз на рестарт: `process_manager_process.py:5719-5720`, `self.get_config("restart_reuse_queues")`; `None` → `True`. Уровень — конфиг оркестратора PM: один на всю систему, не на процесс и не на рецепт. В YAML репо ключа нет: `git grep -F restart_reuse_queues -- '*.yaml' '*.yml'` → 0 строк. Сегодня его задаёт только тест: `backend_ctl/tests/test_fencing_live.py:57-63` (`launcher._orchestrator_config["restart_reuse_queues"] = False`).
2. **`restart_process` при `reuse_queues=False` сегодня** (`:5672-5786`, тело — `_restart_process_replace` `:5706`):
   - `stop_process(name, mark_reader_gone=False)` `:5709` → `remove_process` `:5711`;
   - `register_process(name, config, reuse_queues=False)` `:5723` → `shared_resources_manager.py:162-197` (файл `multiprocess_framework/modules/shared_resources_module/core/`): все qtype создаются заново (`create_and_register_queues` → `ReaderGoneQueue`, `queues/core/manager.py:200-205, 244-253`), `add_queue` заменяет старые объекты в PSR PM;
   - `update_state(status="initializing")` `:5728`; `_drain_process_queues` `:5730` — на свежих очередях пусто;
   - id очередей до и после различаются → `_bump_incarnation` `:5739-5740` (`:3868-3880`) ДО `create_and_register`: bundle нового воплощения несёт новую incarnation (fence ADR-PMM-014);
   - `create_and_register` + `start` `:5743-5747`, барьер ready `:5764-5767`, wire re-issue `:5772-5773`;
   - `_bump_routing_epoch` + `_broadcast_routing_refresh("process.restart")` `:5776-5777`: полный снимок `{epoch, hub, processes: {имя: {incarnation}}}` в system-очереди детей (`:3892-3932`).
3. **Как выжившие узнают о новой очереди.** Никак: `mp.Queue` не пиклится вне spawn (ADR-PMM-010, `process_manager_module/DECISIONS.md:100`). Ребёнок в `_cmd_routing_refresh` (`process_module/commands/builtin_commands.py:3979-4052`) видит incarnation ≠ локальной и зовёт `psr.drop_process_queues(name)` (`shared_resources_module/state/process_state_registry.py:126-150`). Дальше его `send_to_process` → `_deliver_by_targets` (`router_module/core/router_manager.py:675`) → `_queue_absent` → `_relay_via_hub` (`:769-783`, `:911-955`): билет едет командой `router.relay` в **system-очередь PM** (maxsize 100 — `process_module/configs/process_launch_config.py:14-15`; never-drop — `queues/core/manager.py:512-530`). PM: `_cmd_router_relay` (`builtin_commands.py:3915-3933`) → `router.send_async` → свежий PSR PM → новая очередь. Хаб по умолчанию `"ProcessManager"` (`router_manager.py:146`).
   - **Это и делает путь A с data-трафиком к перезапущенному:** весь трафик выживших к нему идёт через message-processor PM навсегда — до switch (новые bundle) или перезапуска приложения. ADR-PMM-010 именно это отверг для restart: «Всегда сажать соседей на hub-relay после restart — все кадры через system-очередь PM (бутылочное горло)» (`DECISIONS.md:114`).
   - Наблюдено на настоящем PM (раздел «Живой тест»): после рестарта `preprocessor` 30 из 30 билетов `devices → preprocessor` дошли, все 30 через relay.
   - **Дыра A:** каналы `{target}_{qtype}` (`process_module/communication/process_communication.py:83-100`) у выжившего привязаны к СТАРОЙ очереди; refresh их не снимает. Они работают при явном `channel`, маршруте dispatcher или kind-каналах. Kind-каналы по умолчанию выключены (`router_manager.py:173-179`; включаются env `MULTIPROCESS_USE_KIND_CHANNELS` или `router.use_kind_channels`). Живых `register_route(` вне тестов нет (`git grep -n "register_route(" -- '*.py' ':!**/tests/**'` → только определения). При включённых kind-каналах выживший пишет в брошенную очередь — тихая потеря. Выведено чтением, не проверено.
   - Широковещание выжившего (`ProcessCommunication.broadcast` → `queue_registry.broadcast_message` по своей PSR; `def broadcast` — `process_communication.py:227`, вызов `queue_registry.broadcast_message` — `:250`) после `drop_process_queues` перезапущенного не видит; relay для широковещания нет. Выведено чтением, не проверено.
4. **Накопленное в старой очереди.** Выбрасывается вместе с объектом: PM заменяет его в PSR, читателя у старой очереди больше нет. Сегодня при `reuse=True` то же выбрасывает `_drain_process_queues` (`:4886-4911`). Положенное выжившими по старой ссылке до применения refresh теряется (окно ADR-PMM-010, `DECISIONS.md:106`). **Метку «читатель ушёл» брошенные очереди сегодня не получают:** `mark_reader_gone=False` `:5709`; `plans/lifecycle-stop-ownership.md:127` («не проверено»). Без метки писатель с кадром крупнее pipe висит на выходе (ADR-PMM-030, `DECISIONS.md:1252-1258`: 0/5 без метки). Причина «рестарт не маркирует» (`DECISIONS.md:1295-1299`) — переиспользование; при A её нет.
5. **Relay-классы T/L.** `process.relay` (класс T, `:1697`, `:1747`) идёт GUI → PM → свежий PSR PM; при A работает как сегодня. L не задет. Это из отчёта расследования (`2026-11-20_lane-D2_C-36.md:54`); сам я T/L не проверял.
6. **Что уже покрыто тестами при `reuse=False`.** `git grep -n -F restart_reuse_queues -- '*.py'`: тест с ключом — только `backend_ctl/tests/test_fencing_live.py` (живой: incarnation, epoch, fence старого инстанса); после смены умолчания его monkeypatch `restart_reuse_queues=False` (`:57-66`) станет холостым и тест перестанет ловить откат умолчания (I1 его не уронит). Умолчание `True` закрепляют `test_routing_epoch_live.py`, `test_pm_marks_gone_*` (`TestRestartProcessDoesNotMark`, пин `mark_reader_gone=False`) и докстринги `test_writer_outlives_*`. На прототипе `test_pm_marks_gone_*` зелёные (`20 passed in 11.54s`, наблюдено ревьюером стадии 0 на копии), потому что `pm.shared_resources = None` обходит новую ветку: новый путь A они не проверяют, а докстринги станут ложью. Поток данных к перезапущенному, глухота, метка на брошенных очередях — не покрыты нигде. Обратный контракт закреплён: `backend_ctl/tests/test_routing_epoch_live.py:140-170` требует прямой доставки после restart (`relayed_to_hub` не растёт). При A этот тест красный (наблюдено, ниже).
7. **Вывод.** A «за флагом» рабочий: при `false` путь доставляет (30/30 через relay на настоящем PM). Чего не хватает:
   - (а) умолчание `True`;
   - (б) метки «читатель ушёл» на брошенных очередях;
   - (в) пробы замка; `_drain_process_queues` глотает `Empty` от занятого замка молча (`:4908`);
   - (г) счётчика.

## Решения для владельца/CTO

- **Р1. Умолчание.** Варианты:
  - O1 — в коде PM `None → False` (прототип ниже); `true` остаётся откатом.
  - O2 — код не трогать, ключ `restart_reuse_queues: false` в конфиге оркестратора прототипа. Место ключа (найдено ревьюером стадии 0; автор не искал) — одна строка в dict `orchestrator_config`, `multiprocess_prototype/backend/launch.py:759`: ключи плоские и склеиваются в конфиг PM как есть (`launcher/spawner.py:95-96`); файл Ф не трогается.
  - O3 — оставить `True` и лечить только пробой с пересозданием (это вариант C, не A).
  
  **Рекомендация — O1.** Дефект во framework, не в прототипе (принцип владельца 2: чинить framework вперёд). O2 оставляет глухим любого другого пользователя framework. O3 противоречит правилу владельца 2026-10-26 («очереди убитого ребёнка не переиспользуются»). Без правки транспорта C-36 в продукте закрывает O1 + метка (б) + проба (в, г). O1 меняет решение B ADR-PMM-010 для restart и горячий путь (relay) — **это решение CTO**. Условие отмены CTO написано как раз для этого шага.

  Оценка ревьюера стадии 0: согласен с O1 после зелёного шага 0 теста условия отмены (раздел ниже). O2 — только временный мост, если владелец хочет A до слияния Ф. O3 не берётся.
- **Р2. Уровень голоса при A.** При `reuse=false` занятый замок вреда не делает: очередь брошена. При этом ERROR будет почти на каждом рестарте после `kill` простаивающего потребителя (расследование: data 142/142). Рекомендация — оставить ERROR, как сказал CTO: строка и есть счёт событий C-36. Альтернатива — WARNING при `false`, ERROR при `true`. Решает CTO.

  Оценка ревьюера стадии 0: не согласен с «оставить ERROR». Предлагает WARNING + счётчик при `reuse=false` (текст без «глухо»), ERROR при `reuse=true` (C36A-6): при A ERROR — ложная тревога почти на каждом рестарте после kill, строка идёт в лог и хвост наблюдаемости (в `health.errors` не попадает: `_log_error` только пишет в логгер, `observable_mixin.py:221-241` — по чтению, не прогнано; довод «health.errors» из раунда 1 снят, C36Ar-5); счёт событий всё равно держит `orphaned_read_locks`; прежний текст «новое воплощение глухо» при `false` неверен (воплощение получает свежую очередь).

  **Открытый вопрос владельцу/CTO (не решён автором и ревьюером за них):** автор — ERROR в обоих режимах; ревьюер — WARNING при `false`, ERROR при `true`. Пока не решено, tester фиксирует «≥ WARNING», не точный уровень. Текст при `false` без «глухо» — независимо от выбора уровня.
- **Р3. `reuse=true` + занятый замок.** В прототипе тогда весь процесс уходит на свежие очереди (откат C) и даёт отдельный ERROR. Иначе путь отката оставляет воплощение глухим. Это шире «громкой пробы»; нужно подтверждение CTO.

  Оценка ревьюера стадии 0: согласен — откат всего процесса на свежие очереди нужен, incarnation одна на процесс; при `true` + занятый замок — своя ERROR. Откат работает: инъекция I10 (убрать `reuse_queues = False`) роняет (г) (`1 failed 3 passed`, наблюдено ревьюером стадии 0 на копии).
- **Р4. Kind-каналы при A** (п. 3, «дыра A»). Варианты:
  - снимать каналы `{name}_*` в `routing.refresh` — правка `builtin_commands.py`, вне файла PM;
  - отказ на старте при kind ON и `reuse=false`.
  
  До решения это строка рисков. Решает CTO.

  Оценка ревьюера стадии 0: сейчас ни снимать каналы, ни отказывать на старте — kind-каналы выключены по умолчанию, `register_route(` вне тестов нет. Предусловие слота (C36Ar-6): `git grep -n -i -F "use_kind_channels" -- . ':!docs' ':!plans'` — включающими считаются только строки вне комментариев и тестов (на `dc56f14df` по чтению ревьюера: `feature_flags.py:139` с `default=False` и alias `MULTIPROCESS_USE_KIND_CHANNELS`, `router_manager.py`, `process_managers.py:364`, пробы `backend_ctl/probes/g7_*` и комментарий запуска `recipes/dualcam_webcam.yaml:16`); в env стенда `FW_USE_KIND_CHANNELS` и `MULTIPROCESS_USE_KIND_CHANNELS` не заданы (команда не прогнана; прежняя `git grep use_kind_channels` ловила только конфиг-ключ). Строка риска для `defects.md`: «A несовместим с включёнными kind-каналами до снятия каналов в `routing.refresh`; `g7_fault_probe kill_reader` (SIGKILL читателя под нагрузкой — ровно «дыра A»), `g7_dualcam_probe` и soak по `dualcam_webcam.yaml` запускают их включёнными — до решения Р4 их с A не гонять (или гонять на `restart_reuse_queues=true`)». Снятие каналов — в слоте владельца `builtin_commands.py`. Как `FW_USE_KIND_CHANNELS` доходит до роутера (`router_manager.py:2093` читает `MULTIPROCESS_USE_KIND_CHANNELS`, затем `is_enabled("FW_USE_KIND_CHANNELS")`), не выяснено.
- **Р5. Потолок relay на data-линии.** Порог кадров в секунду через system-очередь PM не измерен. Числа в тесте условия отмены (ниже) — мои предложения; утверждает CTO.

  Оценка ревьюера стадии 0: пороги CTO утверждает ДО прогона и относительно контроля на `main` при той же частоте F (шаг 0 теста), не абсолютными числами; запас — 2× от производственного fps.

## Файлы

**Править (в слоте, после слияния Ф):**
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` — умолчание, проба, метка, счётчик (diff ниже). Хунк «дренаж только при reuse» убран (C36A-2): на свежих очередях дренаж ничего не делает, правка ненаблюдаема (инъекция I8 — безусловный дренаж — `4 passed`, наблюдено ревьюером стадии 0 на копии), а хунков в файле зоны Ф должно быть меньше. Плюс правки по ревью (обвязка метки в daemon-потоке, текст лога по режиму, счётчик в `__init__`) — в «Как это работает». Заодно устаревшие тексты в этом же файле: докстринг `restart_process` `:5675-5680`, комментарии `:5708`, `:5729`, `:5774-5775`, докстринг `_drain_process_queues` `:4889-4892`, комментарий `:2944`; докстринг `_cmd_supervision_status` `:2406-2412` («incarnation растёт только при смене identity») при A неверен: растёт на каждый рестарт.
- `backend_ctl/tests/test_routing_epoch_live.py:140-170` — ожидание B («relay не растёт») сменить на A («доставлено и через relay»). Это смена контракта: только вместе с ADR.
- `backend_ctl/tests/test_fencing_live.py:57-66` — убрать monkeypatch `restart_reuse_queues=False` (после смены умолчания он холостой), обновить докстринги `:34`, `:56`. Иначе тест не ловит откат умолчания.
- `process_manager_module/tests/test_pm_marks_gone_reader_acceptance.py:393-430` (`TestRestartProcessDoesNotMark`) и `test_pm_marks_gone_reader_hazards.py:273-326` — докстринги: «рестарт не маркирует» верно только при `true` и свободном замке; при A маркирует. Новый путь A эти тесты не проверяют (стоит `pm.shared_resources = None`).
- `shared_resources_module/tests/test_writer_outlives_reader_acceptance.py:172, 502` — докстринги «по умолчанию переиспользует».
- новые тесты: `process_manager_module/tests/test_c36_restart_fresh_queues.py` (+ помощник spawn только на stdlib), `backend_ctl/tests/test_c36_relay_flow_live.py`, живой тест data-линии (ниже). Пишет слепой tester по разделу «Тесты»; прототипы — в приложении.
- `process_manager_module/DECISIONS.md` — **новый ADR** (номер по `main` в момент слияния Ф; ранее была коллизия номеров 046/047): «умолчание A» со ссылкой на отмену ADR-PMM-010 (ветка B для restart; `true` — откат, цена: relay навсегда) и ADR-PMM-030 («Почему рестарт не маркирует» → при `reuse=false` маркирует), не «поправкой». Плюс устаревшие места: ADR-PMM-014 `:346-350` («restart-reuse incarnation НЕ меняется») и `:368-372` («Restart с reuse_queues=True (дефолт)»), `:1295-1299`; затем `python -m scripts.sync`.
- `shared_resources_module/DECISIONS.md:476-479` (ADR-SRM-016, п.2) — «по умолчанию переиспользует».
- `process_manager_module/STATUS.md` — ключ, умолчание, поле `orphaned_read_locks`. `README.md` PM не растить (46 КБ при бюджете 32 КБ, `infra:validate`): ключ писать в STATUS/DECISIONS. Ключ в README/STATUS сегодня не назван — «добавить», не «поправить».
- Контракт нового поля `orphaned_read_locks` — те же места, где описан `instance_restarts`: описание команды `process_manager_process.py:1733-1737`, `backend_ctl/driver.py:1238-1245`, `backend_ctl/mcp_tools.py:794-795` (там «дефолт reuse»), `backend_ctl/AGENTS.md:145` (найдено ревьюером стадии 0; закрывает прежнее «я не проверял»).
- `queues/core/reader_gone.py:22-25` («Рестарт метку НЕ взводит») при A станет ложью; файл в «Не трогать» — разрешить правку только докстринга или записать долгом (решение владельца, см. «открытое»).
- `plans/queue/defects.md:283` — статус C-36.

**Не трогать:** `shared_resources_module/core/shared_resources_manager.py`, `queues/core/manager.py`, `queues/core/reader_gone.py`, `router_module/**`, `process_module/commands/builtin_commands.py` (если Р4 не решён иначе), `process_manager_module/launcher/spawner.py`, `queue_channel.py`, `data_receiver.py`.

**Конфликтные зоны:**
- `process_manager_process.py` и `launcher/spawner.py` сейчас у полосы Ф: правка PM-файла строго после слияния Ф и rebase на свежий `main`. Строки этого брифа после Ф сдвинутся: якоря — имена функций. Дополнительно Ф трогает (по handoff Ф `docs/handoffs/2026-11-20_system-run-state_lane-f-continue.md`; ветку Ф ревьюер не нашёл): `process_manager_module/DECISIONS.md` (ADR-PMM-049 «Известная цена»), PM `README.md` (п.6 handoff Ф) и `process_manager_process.py:1723` (run-state, `system.run.*`). Значит, `DECISIONS.md`, `README.md`, `STATUS.md` PM-модуля — тоже конфликтные зоны; ADR писать после слияния Ф. Хунки diff — импорт; `_cmd_supervision_status`; блок методов после `_drain_process_queues`; `_restart_process_replace` — с хунками Ф не пересекаются, конфликт возможен только на соседних строках. PM-файл правит один писатель, после слияния Ф. Диагностику, шаг 0 теста условия отмены и тесты можно вести до слияния Ф: PM-файла они не требуют.
- К (`camera_device`) и Р2 (визит) по их планам PM-файл не трогают. Их ветки я не открывал (запрещено брифом) — не проверено.

**Последовательность:**
0. **Тест условия отмены (шаг 0)** — класс `heavy`, сима, флаг через monkeypatch; срок — окно стенда после дня №1 (задание полосы), но тест не требует кода и идёт ДО слота писателя; исполнитель — одноразовый стендовый скрипт (см. раздел «Живой тест»); PM-файла не требует, слияния Ф и железа не ждёт. Красный → умолчание остаётся `True`, остальные шаги идут по ветке C (раздел «Живой тест»). Предсказано, не прогнано.
1. Слияние Ф → rebase на свежий `main`. Предусловие, обязательное до правок: `git merge-base --is-ancestor <SHA слияния Ф> HEAD && git apply --check <diff>` (якоря diff — имена функций).
2. Слепой tester (тесты по разделу ниже, ДО кода) → writer (diff) → инъекции I1–I11 → Opus-ревью (concurrency/IPC — обязательно) → живой тест data-линии (б) на стенде → слияние → `defects.md`, ADR (номер по `main` в момент слияния), `scripts.sync`.

## Правка (diff прототипа)

Проверен на одноразовом worktree: `ruff check -q` → `rc=0`. `git apply --check` на прежнем diff → `APPLY-CHECK OK` (+93/−2; наблюдено ревьюером стадии 0 на копии). Diff ниже уже без хунка дренажа: на `dc56f14df` `git apply --check` → rc=0, `+90/−1`, строка `index` устарела и на применение не влияет; 4 теста прототипа → `4 passed in 7.89s`; радиус 9 файлов + `test_pm_marks_gone_*` → `115 passed in 56.28s` (наблюдено ревьюером раунда 2 на копии). Правки по ревью (обвязка метки, текст по режиму, счётчик в `__init__`) в этот diff не внесены. Радиус автора (на прежнем diff): 9 файлов рестарта и PM → `95 passed in 45.08s` (`G medium inspector-bottles-d2 bash R test_routing_epoch.py test_restart_process_failure_unmarks.py test_supervisor_restart_incarnation.py test_supervisor_restart_incarnation_hazards.py test_lifecycle_restart_reply.py test_run_restart_incarnation.py test_run_restart_incarnation_hazards.py test_process_manager_process.py shared_resources_module/tests/test_writer_outlives_reader_acceptance.py`). В ветку не коммитился.

```diff
diff --git a/multiprocess_framework/modules/process_manager_module/process/process_manager_process.py b/multiprocess_framework/modules/process_manager_module/process/process_manager_process.py
index b5bb0a178..79d142e0d 100644
--- a/multiprocess_framework/modules/process_manager_module/process/process_manager_process.py
+++ b/multiprocess_framework/modules/process_manager_module/process/process_manager_process.py
@@ -34,4 +34,5 @@ from ...process_module.progress import ProgressTracker, progress_path
 from ...shared_resources_module import QueueRegistry
 from ...shared_resources_module.qos import DEFAULT_FRAME_RING_DEPTH
+from ...shared_resources_module.queues.core.reader_gone import set_reader_gone
 from ..core.process_priority import ProcessPriority
 from ..core.process_registry import ProcessRegistry
@@ -2421,4 +2422,5 @@ class ProcessManagerProcess(ProcessModule):
         # D3: снимки без лока — писатели класса L мутируют словари на потоке исполнителя.
         instance_restarts = dict(getattr(self, "_instance_restarts", None) or {})
+        orphaned_read_locks = dict(self.__dict__.get("_orphaned_read_locks") or {})
         started_at = dict(getattr(self, "_instance_started_at", None) or {})
         registry = getattr(self, "_process_registry", None)
@@ -2467,4 +2469,5 @@ class ProcessManagerProcess(ProcessModule):
                 "started_at": started_at.get(name),
                 "instance_restarts": instance_restarts.get(name, 0),
+                "orphaned_read_locks": orphaned_read_locks.get(name, 0),
                 # Task 1.10: как умер ребёнок при последнем стопе текущего воплощения (D1); None — не стопался.
                 "stop_outcome": registry.stop_outcome(name) if registry is not None else None,
@@ -4911,4 +4914,74 @@ class ProcessManagerProcess(ProcessModule):
             pass
 
+    #: C-36: сколько раз пробовать замок чтения и пауза между пробами. Живой писатель,
+    #: вытесняющий старейший элемент (``QueueRegistry.remove_old_if_full`` → ``get_nowait``),
+    #: держит замок микросекунды; 5 × 10 мс отличают его от замка убитого читателя.
+    _RLOCK_PROBE_ATTEMPTS = 5
+    _RLOCK_PROBE_PAUSE_S = 0.01
+
+    def _probe_orphaned_read_locks(self, name: str) -> list[str]:
+        """Найти очереди процесса с замком чтения, занятым без живого читателя (C-36).
+
+        Зовётся из рестарта ПОСЛЕ подтверждённой смерти воплощения и ДО ``register_process``:
+        в PSR ещё очереди убитого. Читатель ``mp.Queue`` держит межпроцессный ``_rlock`` всё
+        время ``get(timeout)``; убитый внутри, он оставляет замок занятым навсегда (ядро
+        семафор не освобождает). На каждую такую очередь — ERROR с процессом и типом
+        очереди и +1 к счётчику ``orphaned_read_locks`` (``supervision.status``).
+
+        Returns:
+            Отсортированные типы очередей с занятым замком.
+        """
+        sr = getattr(self, "shared_resources", None)
+        if sr is None:
+            return []
+        try:
+            pd = sr.get_process_data(name)
+            queues = dict(getattr(pd, "queues", None) or {}) if pd is not None else {}
+        except Exception as exc:  # noqa: BLE001 — проба не роняет рестарт
+            self._log_warning(f"restart '{name}': проба замков чтения не выполнена: {exc!r}")
+            return []
+        stuck: list[str] = []
+        for qtype, q in sorted(queues.items()):
+            lock = getattr(q, "_rlock", None)
+            if lock is None:  # не mp.Queue (тестовый двойник, queue.Queue) — проверять нечего
+                continue
+            if not self._read_lock_free(lock):
+                stuck.append(qtype)
+        if stuck:
+            counters = self.__dict__.setdefault("_orphaned_read_locks", {})
+            counters[name] = counters.get(name, 0) + len(stuck)
+            for qtype in stuck:
+                self._log_error(
+                    f"C-36: очередь '{qtype}' процесса '{name}': замок чтения занят без живого читателя "
+                    f"(воплощение убито внутри get) — на этой очереди новое воплощение глухо; "
+                    f"orphaned_read_locks[{name}]={counters[name]}"
+                )
+        return stuck
+
+    def _read_lock_free(self, lock: Any) -> bool:
+        """Свободен ли замок: ``acquire(False)`` с повтором (см. ``_RLOCK_PROBE_ATTEMPTS``)."""
+        for attempt in range(self._RLOCK_PROBE_ATTEMPTS):
+            try:
+                if lock.acquire(False):
+                    lock.release()
+                    return True
+            except Exception:  # noqa: BLE001 — сломанный семафор = не свободен
+                return False
+            if attempt + 1 < self._RLOCK_PROBE_ATTEMPTS:
+                time.sleep(self._RLOCK_PROBE_PAUSE_S)
+        return False
+
+    def _mark_abandoned_queues_gone(self, name: str) -> None:
+        """Взвести метку «читатель ушёл» на очередях, которые рестарт бросает (ADR-PMM-030)."""
+        sr = getattr(self, "shared_resources", None)
+        if sr is None:
+            return
+        try:
+            pd = sr.get_process_data(name)
+            queues = list((getattr(pd, "queues", None) or {}).values()) if pd is not None else []
+            set_reader_gone(queues, True)
+        except Exception as exc:  # noqa: BLE001 — метка вторична, рестарт продолжается
+            self._log_warning(f"restart '{name}': метка «читатель ушёл» на брошенных очередях не взведена: {exc!r}")
+
     def _process_queue_ids(self, name: str) -> dict[str, int]:
         """id() очередей процесса из PSR — для сверки identity до/после рестарта."""
@@ -5717,6 +5790,22 @@ class ProcessManagerProcess(ProcessModule):
             self._mark_wires_broken_for(process_name)
 
+        # C-36 (вариант A): дефолт False — очереди убитого воплощения не переиспользуются
+        # (решение владельца 2026-10-26, 2026-11-20). ``true`` — откат к поведению Ф3.1.
         reuse_cfg = self.get_config("restart_reuse_queues")
-        reuse_queues = True if reuse_cfg is None else bool(reuse_cfg)  # дефолт True
+        reuse_queues = False if reuse_cfg is None else bool(reuse_cfg)
+        # Громкая проба (C-36, из варианта C): замок чтения очереди, занятый без живого
+        # читателя, — ERROR + счётчик. При reuse такая очередь глуха навсегда, поэтому
+        # рестарт уходит на свежие очереди всего процесса.
+        stuck = self._probe_orphaned_read_locks(process_name)
+        if stuck and reuse_queues:
+            self._log_error(
+                f"restart '{process_name}': restart_reuse_queues=true, но замок чтения {stuck} занят — "
+                "очереди пересоздаются (C-36)"
+            )
+            reuse_queues = False
+        if not reuse_queues:
+            # ADR-PMM-030: брошенные очереди больше никто не прочтёт — метка «читатель ушёл»
+            # отпускает feeder'ы выживших писателей, положивших туда до routing.refresh.
+            self._mark_abandoned_queues_gone(process_name)
         ids_before = self._process_queue_ids(process_name)
         if self.shared_resources:
```

Как это работает:
- Проба идёт после подтверждённой смерти и до `register_process`: в PSR ещё очереди убитого. 5 попыток `acquire(False)` с паузой 10 мс: свободный замок отвечает сразу; занятый стоит ≤ 40 мс на очередь.
- Ложное срабатывание от живого вытесняющего писателя (`queues/core/manager.py:532`, `get_nowait` из чужой очереди держит замок микросекунды) отсекает повтор (инъекция I4 ниже).
- Счётчик — `orphaned_read_locks` на процесс в `supervision.status` (рядом с `instance_restarts`). Строка лога (в прототипе — ERROR): `C-36: очередь '<qtype>' процесса '<name>': замок чтения занят без живого читателя …`.

Правки к diff по ревью стадии 0 — в diff выше НЕ отражены (кроме удалённого хунка дренажа); вносит писатель, закрепляют требования к tester; предсказано, не прогнано:
- **Текст по режиму (C36A-6).** Проба получает `reuse_queues` параметром; счётчик растёт в обоих режимах. `reuse=false`: «C-36: очередь '<qtype>' процесса '<name>': замок чтения осиротел, очередь брошена и пересоздана; orphaned_read_locks=N» — без «глухо», уровень по Р2 (WARNING по ревьюеру). `reuse=true`: текущий текст, ERROR. В прототипе строка с «глухо» идёт на любом режиме: при A это ложная ERROR на почти каждом рестарте после kill простаивающего потребителя (data 142/142 по расследованию).
- **`_mark_abandoned_queues_gone` — с дедлайном (C36A-3).** Метка берёт `q._reader_gone._cond` (`Event.is_set()/set()`); убитый процесс может оставить его занятым, и `set_reader_gone` не вернётся. Наблюдено ревьюером стадии 0 на stdlib и настоящем `ReaderGoneQueue` (не на настоящем PM): spawn-помощник берёт `_cond`, получает SIGKILL (`exitcode -9`); `set_reader_gone([q], True)` в daemon-потоке с `join(3)` → `returned: False {} waited=3.0s`. `try/except Exception` в diff от зависания не защищает; раньше рестарт при `reuse` Event не трогал, теперь это новая дорога к бесконечному ожиданию в потоке рестарта PM. Вызов исполняется в daemon-потоке с `join(2.0)`; по таймауту — ERROR «метка не взведена: Event занят убитым процессом», рестарт продолжается. Рекомендация (advisory, C36Ar-7; по рассуждению, не прогнано): не один поток на все очереди, а по одному daemon-потоку на очередь (или метка по очереди с общим дедлайном 2,0 с на всё), при таймауте — ERROR с типом очереди: иначе зависший `Event.set()` первой очереди оставит остальные без метки. «0 из 226» окно «kill внутри `is_set()` в выходном хуке `release_feeders_at_exit`» не снимает (это замеры других kill). Вариант без обвязки — только если CTO принимает риск: тогда в «открытое» как принятый, с «0/226, окно не измерено», и в ADR.
- **Счётчик в `__init__` (C36A-11).** Вместо `self.__dict__.setdefault("_orphaned_read_locks", …)` — инициализация в `__init__` рядом с `_instance_restarts` (`:281`) и включение в кортеж очистки `:3209`; иначе счётчик переживёт удаление процесса.

## Тесты и break-injection

### Прототип (одноразовый worktree, настоящие PM `restart_process`, SRM/PSR, `ReaderGoneQueue`, межпроцессный `_rlock`)

Замок осиротевает настоящим способом: spawn-помощник берёт `q._rlock` и получает `SIGKILL` (`exitcode == -9`, затем `q._rlock.acquire(False) is False`). Двойники — реестр OS-процессов (`MockProcessRegistry`) и `communication` (MagicMock). Каждый `restart_process` — в daemon-потоке с `join(30)`.

| тест | что проверяет | литералы |
|---|---|---|
| (в) `test_system_lock_orphaned_default_restart_reader_gets_command_10_of_10` | 10 раз: осиротить `_rlock` system → `restart_process` (умолчание) → spawn-читатель на новой очереди получает `{"command": "ping", "i": i}` за 1 с | `got_ok == 10` |
| (г) `test_reuse_true_orphaned_data_lock_is_loud_counted_and_recreated` | `restart_reuse_queues=true`, осиротить `_rlock` data | ERROR содержит `очередь 'data' процесса 'cam'`, про `system` строки нет; `orphaned_read_locks == 1`; data и system — новые объекты; старая data `is_reader_gone() is True` |
| ложная тревога | `reuse=true`, поток держит `_rlock` data 15 мс; в момент входа в пробу замок ещё занят (шпион, C36A-7; повторы ×3 убраны — в приложении они остались, приоритет у основного текста) | строк `C-36` 0; счётчик 0; identity data та же |
| метка | умолчание | новые объекты; старые `is_reader_gone` `[True, True]`, новые `[False, False]` |

Команда: `G medium inspector-bottles-d2 bash R multiprocess_framework/modules/process_manager_module/tests/test_c36_restart_queues_prototype.py` → `4 passed, 1 warning in 7.26s`. Ревьюер стадии 0 воспроизвёл прототип на копии: `4 passed in 8.26s` (наблюдено ревьюером стадии 0 на копии). Прототип не закрепляет два свойства: цель №2 на умолчании A (I7) и «дренаж только при reuse» (I8, хунк убран) — см. матрицу.

**Матрица инъекций.** Предсказания I0–I6 записаны автором до прогона; I7–I11 добавлены ревью стадии 0 (I7–I10 — по одному прогону на копии, I11 — не прогонялась). Колонка «наблюдено» заполнена только тем, что реально измерено; I1–I6 ревьюер не перепрогонял. Скрипт подменяет файл PM, гоняет файл тестов и возвращает прототип (`restored: True`). Команда: `G medium inspector-bottles-d2 <python> inject_c36.py`.

| инъекция | предсказано (падают) | наблюдено |
|---|---|---|
| I0 прототип | ничего | `4 passed in 8.27s` |
| I1 умолчание снова `True` (проба и откат C на месте) | метка | метка (`assert False`, identity старая); (в) зелёный — его вытаскивает откат C |
| I2 пробы нет (`stuck = []`) | (г) | (г): `AssertionError: []` |
| I3 ERROR пробы заглушён | (г) | (г): в списке осталась только строка отката |
| I4 проба без повтора (1 попытка) | ложная тревога | ложная тревога: строка `C-36` появилась |
| I5 метки на брошенных нет | метка, (г) | метка `[False, False] == [True, True]`; (г) `assert False is True` |
| I6 исходный `main` | все 4 | все 4: (в) `assert 0 == 10`; (г) `AssertionError: []`; ложная тревога `KeyError: 'orphaned_read_locks'` (поля нет — красный по форме, не по поведению); метка `assert False` |
| I7 проба только при reuse: `stuck = self._probe_orphaned_read_locks(name) if reuse_queues else []` | (в) в расширенной редакции (счётчик и строка лога на умолчании) — предсказано, не прогнано | наблюдено ревьюером стадии 0 на копии: `4 passed` — (в) до расширения недостаточен |
| I8 безусловный `_drain_process_queues` (основание C36A-2; хунк убран, инъекции больше нет) | никто — правка ненаблюдаема | наблюдено ревьюером стадии 0 на копии: `4 passed` |
| I9 счётчик не растёт, ERROR на месте | (г) | наблюдено ревьюером стадии 0 на копии: (г) падает, `1 failed 3 passed` |
| I10 нет перехода на свежие очереди при stuck+`reuse=true` (убрать `reuse_queues = False`) | (г) | наблюдено ревьюером стадии 0 на копии: (г) падает, `1 failed 3 passed` |
| I11 `_mark_abandoned_queues_gone` без дедлайна (без daemon-потока и `join`) | hazard-тест «Event осиротел» — предсказано, не прогнано | — (не прогонялась) |

Честная оговорка по I6: в первом прогоне (в) упал по другой причине — `помощник не взял замок за 20 с`. На `main` очередь переиспользуется, а её замок уже осиротел; помощник второй итерации висел на `acquire()`. Я поправил тест: уже осиротевший замок не берётся повторно. После этого (в) упал с предсказанным `assert 0 == 10`. Остальные строки совпали с предсказанием с первого раза.

### Требования к слепому tester (пишет ДО кода, по этому разделу, не по прототипу)

Основной текст этого раздела приоритетнее прототипов в приложении. Всё ниже — новые требования, не прогнано.

- (в) и (г) — как в таблице. Ожидаемые значения — литералы. Хотя бы один тест на настоящих объектах: spawn-помощник + `SIGKILL`, не мок замка.
- (в) дополнить (C36A-1): после каждого i-го рестарта `orphaned_read_locks[cam] == i+1` (орфаним только system-очередь) и в логе PM есть строка `C-36` с `очередь 'system' процесса 'cam'`. Уровень — по Р2: пока Р2 не решён, фиксировать «≥ WARNING», не точный уровень.
- Наблюдаемые каналы (C36A-11): лог PM — через мок логгера, который даёт `make_pm` (в прототипе `pm._log_error.call_args_list`; для WARNING — `_log_warning`), или перехват записей. Поле — `_cmd_supervision_status({"process": name})["processes"][name]["orphaned_read_locks"]` (int, накопительный). Текст по режиму (C36A-6): по тесту на каждый — `reuse=false` (без «глухо», счётчик растёт), `reuse=true` (ERROR «глухо», счётчик растёт).
- Ложная тревога (C36A-7): в момент входа в пробу замок ещё занят — проверять шпионом на `remove_process`: `q._rlock.acquire(False) is False`; иначе тест помечается inconclusive (skip), а не зелёным. Повторы ×3 убрать. Причина: удержание 15 мс против окна пробы 40 мс — на нагруженной машине I4 не роняет, а задержка потока-вытеснителя даёт красный без дефекта (на тихой машине `I4 → тревога`, ревьюер I4 не перепрогонял).
- Hazard-тест (C36A-3): замок `Event` метки осиротел SIGKILL'ом (spawn-помощник берёт `q._reader_gone._cond`), `restart_process` возвращается ≤ 5 с (daemon-поток + `join`). Инъекция I11 «вызов без дедлайна» → тест падает. Если CTO принимает риск без обвязки — тест не нужен, риск идёт в «открытое» и в ADR.
- Дренаж (C36A-2): хунк убран, теста нет. Если писатель его оставит — добавить требование «`_drain_process_queues` не вызывается при умолчании, вызывается при `true`» и инъекцию I8 → этот тест.
- (б) **data-линия, 30 kill.** Живой стенд (раздел ниже), `preprocessor` (потребитель `camera_0`) простаивает: кадров нет: простой потребителя — `BackendHarness(with_base=True, run_gate=True)` без START (по умолчанию `run_gate=False` гейта нет и кадры идут сразу, `harness.py:108-110`; `run_gate=True` несовместим с `launcher_factory`, `harness.py:359-366`). Авто-рестарт монитора отключить: `FW_AUTORESTART=0` в env стенда или `launcher._orchestrator_config["restart_policy"] = {"enabled": False}` (`process_manager_process.py:376-384`, по чтению ревьюера раунда 2, не прогонялось); иначе `process.restart` после `kill -9` гонится с авто-рестартом, и `instance_restarts` растёт на +2 (по чтению ревьюера, не прогонялось). 30 раз `kill -9` по pid из `supervision.status`, затем `process.restart`. После каждого ready: 3 команды (`introspect.status` → ответ за 1 с) и 3 элемента data (кадры `camera_0` после открытия гейта или `routing.probe` с data-грузом). Наблюдаемый счётчик кадров потребителя (кандидат — `introspect.telemetry`) — дизайнерское решение: его выбирает и проверяет шаг 0 теста условия отмены ДО передачи (б) tester'у, tester его не выбирает. «Глухой» = за 5 с после ready не дошло ни одной из 3 команд или ни одного из 3 элементов. Порог: **0/30**. Контроль на `main` (`reuse=True`): предсказание **≥ 29/30 глухих** (у стенда 55/55, на kill 142/142). Не прогнано: тяжёлый класс (≈ 30 × 4 с + подъём), имя счётчика кадров не проверено.
- (г) по тексту строки: подстроки `очередь 'data'`, `процесса '<name>'`, `C-36`; счётчик через `supervision.status` (путь поля — выше).
- Инъекции для приёмки — I1–I11 (I8 — только если дренаж оставлен). Набор падающих предсказывается до прогона; таблица «предсказано / наблюдено» — в отчёт. После снятия monkeypatch в `test_fencing_live.py` ожидается, что I1 его роняет (предсказано, не прогнано).

## Живой тест условия отмены (настоящий PM)

**Формализация «держит поток».** После `process.restart` потребителя выживший писатель шлёт N билетов обычным peer-путём (`send_to_process`). Держит, если одновременно:
- дошло ≥ N (наблюдаемый эффект у нового воплощения);
- `relayed_to_hub` писателя вырос ровно на N (доказательство, что шли путём A, а не по старой очереди);
- `errors_delivery_failed` писателя вырос на 0.

**Красный отменяет решение A как умолчание** — что именно остаётся, см. шаг 4 полного теста ниже.

**Прогнано (минимум, light, ~12 с на прогон):** стенд — `BackendHarness(with_base=True)` (настоящий PM, настоящие дети base.yaml); писатель `devices`, потребитель `preprocessor`, груз `routing.probe` → `health.report` (command в system-очередь), N = 30, порт 8797.
- Прототип (A по умолчанию): `G light inspector-bottles-d2 bash R -s -rf -m harness_smoke backend_ctl/tests/test_c36_relay_flow_live_prototype.py` → `C36-FLOW N=30 health.errors=30 relayed_delta=30 delivery_failed_delta=0 took=2.00s`, `1 passed, 1 warning in 11.74s`.
- Контроль, исходный PM `main` (тот же тест): `C36-FLOW N=30 health.errors=30 relayed_delta=0 delivery_failed_delta=0 took=2.13s`, `E assert 0 == 30`, `1 failed in 11.95s`. Тест различает путь A и прямой путь: на `main` то же доставляется напрямую.
- Существующий тест контракта B на прототипе: `G light inspector-bottles-d2 bash R -rf -m harness_smoke "backend_ctl/tests/test_routing_epoch_live.py::test_peer_send_after_restart_delivered"` → доставка есть (в логе `probe:post-restart` у `preprocessor`), падение на последнем assert: `relayed_to_hub 0→1`, `1 failed in 15.83s`. Как предсказано: при A этот тест надо переписать (п. «Файлы»).
- Без `-m harness_smoke` живые тесты `backend_ctl` пропускаются (`1 skipped in 0.12s`): не путать skip с зелёным.

**Что минимум НЕ доказывает:**
- груз — command в system-очередь, не data-линия;
- темп задаёт driver (30 билетов за 2 с), это не кадры камеры;
- потолок relay не мерян;
- не доказано, что кадры `camera_0` → `preprocessor` вообще идут через `send_to_process` → `_deliver_by_targets` (`router_manager.py:739-783`): они могут идти по loan/wire-протоколу (`generic_process.py:38-50` `chain_targets`; ADR-PMM-010 `:108` — wire/SHM живут отдельно). Тогда критерий «relayed_to_hub ≈ числу кадров» неприменим — шаг 0 ниже (C36A-5a).

**Полный тест условия отмены (шаг 0, ДО писателя, сима, флаг через monkeypatch как в `test_fencing_live.py:57-63`; предсказано, не прогнано).** Тот же `BackendHarness`. Рестарт **одного** процесса оставляет выжившими всех прочих (protected важен только для switch): писатель — `camera_0`, потребитель — `preprocessor`. Тест не требует кода PM: флаг уже есть, поэтому его делают до слота писателя и не ждут железа; иначе писатель тратит слот до решения о годности A. Класс — `heavy`; железа не требует (сима); срок — окно стенда после дня №1 (задание полосы), но тест не требует кода и идёт ДО слота писателя (C36Ar-3). Если лид полосы хочет именно «после дня №1» — из этого раздела и из «Последовательности» убрать «железа не ждёт» и «ДО слота писателя» (решение лида, не принято).

**Исполнитель и форма (C36Ar-3).** Одноразовый стендовый скрипт (не pytest-тест набора) `backend_ctl/probes/probe_c36_cancel_condition_live.py`; пишет лид полосы Д2 (или `developer`/`tester` по его заказу); результат — таблица «контроль / A» в `docs/reports/`. Регрессионный `test_c36_relay_flow_live.py` пишет слепой tester позже, по «Тестам». Запуск: `G heavy <session> <python> -m backend_ctl.probes.probe_c36_cancel_condition_live` в окне `heavy`/`stand` по `machine.lock`; на Mac без `machine.lock` — только `light`-версия (один рестарт, N кадров, F не 2×). Файла и скрипта пока нет: не написан, не прогнан.

0. Посылка: на контроле (`true`) `relayed_to_hub` у `camera_0` +0; на A растёт. Если на A тоже +0, кадры идут не через relay: критерий relay заменить на «принято/отправлено» и записать это в бриф.
1. F = 2 × максимум суммарного fps линии через перезапускаемый процесс по рецептам 1.0 (число посчитать и записать ДО прогона). Окно T = 60 с после ready, 3 повтора, плюс каскад из 3 рестартов подряд разных процессов. Шаг 0 идёт с `run_gate=False` (умолчание харнесса): гейта нет, кадры идут сразу; авто-рестарт для шага 0 не мешает (kill не используется); он нужен только в (б) и в каскаде с kill (`FW_AUTORESTART=0` или `restart_policy.enabled=false`, см. (б)). Контроль на текущем `main` идёт без патча (умолчание `True`); патч `restart_reuse_queues=False` — это вариант A; после кода писателя контроль требует явного `True`.
2. Метрики, по контролю (`true`, тот же F) и по A: отправлено камерой; принято и обработано `preprocessor` (счётчик выбрать и проверить первым шагом — он же счётчик для (б)); `relayed_to_hub`; `errors_delivery_failed` у `camera_0`; `queue_system_evict_blocked` и `queue_data_evicted` из `drv.introspect_router_stats(proc)["router_stats"]` у `camera_0`, `preprocessor` и `ProcessManager` (ключи `router_manager.py:1949-1950`; чтение с проверкой присутствия `assert key in router_stats`, а не `.get(key, 0)`: проба `g7_soak_probe.py:59-62` уже получала молчаливый 0 на неверном ключе; имена без префикса `queue_` — внутренние счётчики `QueueRegistry._stats` (`queues/core/manager.py:529, 545, 550`), в `router_stats` их нет; relay кладёт билет в system-очередь PM из роутера отправителя, `router_manager.py:937`, поэтому при переполнении растёт `queue_system_evict_blocked` у `camera_0`, а не у PM — по чтению, на настоящем PM не проверено; разбивка вытеснения по жертве `data_evicted.<жертва>` в `router_stats` не выводится, откуда её читать — не выяснено); p95 RTT `introspect.status` PM; свободные слоты кольца SHM `camera_0` до/после. Главный риск — задержка message-loop PM и утечка займов SHM; через «unresponsive» он виден только косвенно, поэтому RTT и слоты SHM измеряются напрямую.
3. Порог (утверждает CTO ДО прогона, Р5): принято_A ≥ 0,95 × принято_контроль; `errors_delivery_failed` +0; `queue_system_evict_blocked` (`camera_0`) +0; `queue_data_evicted` (`camera_0`) ≤ контроля; p95 RTT PM ≤ 2× контроля и < 1 с; ни одного `unresponsive`/`crashed`; свободные слоты SHM к концу окна ≥ значения до рестарта − 1. Вытеснение drop_oldest считается отдельно, не как потеря доставки.
4. Красный по любому пункту: умолчание остаётся `True` (B). В коде остаются проба + откат C (Р3) и метка при `reuse=false`. C-36 закрывается как вариант C. Пересмотр порога — только новым замером у CTO.

## Приёмка

0. **Шаг 0, ДО писателя:** полный тест условия отмены (шаги 0–4 раздела выше) на симе: порог утверждён CTO до прогона, F посчитано и записано до прогона, итог — зелёный (код идёт дальше как A) или красный (умолчание `True`, вариант C). Предсказано, не прогнано.
1. `G medium inspector-bottles-d2 bash R process_manager_module/tests/test_c36_restart_fresh_queues.py` — зелёный. Матрица I1–I11 (I8 — только если дренаж оставлен) — каждая инъекция роняет предсказанный набор (таблица выше — образец).
2. `G medium inspector-bottles-d2 bash R` + радиус рестарта (9 файлов из раздела «Правка») — 0 failed (прототип: `95 passed`). Радиус расширить 8 файлами PM с рестартом: `wire_reissue`, `monitor_foreign_incarnation`, `supervision_instance_truth`, `topology_seeds`, `run_auto_restart`, `stop_outcome_acceptance`, `supervision_strategies`, `lifecycle_fifo_acceptance` — на прототипе `143 passed in 64.39s` (наблюдено ревьюером стадии 0 на копии).
3. `G light inspector-bottles-d2 bash R -m harness_smoke backend_ctl/tests/test_c36_relay_flow_live.py backend_ctl/tests/test_routing_epoch_live.py backend_ctl/tests/test_fencing_live.py` — зелёные (последний — fence при `reuse=false`, не прогонял; после снятия monkeypatch он идёт на умолчании A). Добавить рестартующие живые тесты вне прежней приёмки под `-m harness_smoke`: `backend_ctl/tests/test_autorestart_all_live.py`, `test_fault_injection_live.py`, `test_wire_status_live.py`, `test_g7_soak_probe.py` — не прогнаны (иначе записать в «открытое»).
4. (б) 30 kill — на стенде в окне `stand`/`heavy` по `machine.lock`: глухих 0/30; пороги раздела выше. Условие отмены на data-линии проверяется шагом 0, не здесь.
5. `ruff check -q` на тронутых файлах; `sentrux check .` (новых нарушений слоёв нет: импорт `reader_gone` внутри framework, PM уже импортирует его через `process_registry.py:31`; по чтению, `sentrux check` ревьюер не гонял).
6. Opus-ревью (concurrency/IPC).

## Границы

- Только вариант A + проба. B (очередь без межпроцессного замка чтения, перенос вытеснения и дренажа к читателю) — после тега 1.0, не здесь.
- Аномалия «13/13 на SemLock» и `mp.Event` — не здесь (CTO: слот до железа не тратить). Оговорка: метка `_mark_abandoned_queues_gone` сама берёт `Event.set()`, поэтому обвязка вызова (daemon-поток + `join`) входит в слот (C36A-3).
- `_wlock` убитого писателя проба не ловит и не лечит (расследование: 0/226, не воспроизведено).
- Транспорт (`router_module`, `shared_resources_module`) не меняется (возможное исключение — докстринг `queues/core/reader_gone.py:22-25`, решение владельца, см. «Файлы»). При решении Р4 «снимать каналы» — отдельная правка `builtin_commands.py`.

## Что осталось открытым / ненадёжно

- **Data-линия к перезапущенному на настоящем PM не прогнана.** Прогнан только command-груз через relay (30/30); кадры камеры через system-очередь PM (maxsize 100, never-drop) могут её переполнить и задеть heartbeat всех детей. Потолок не измерен — это и есть главный риск A и условие отмены (шаг 0, не прогнан; F и пороги не заданы).
- Что кадры `camera_0` → `preprocessor` идут через relay-путь — не проверено, по чтению неясно (C36A-5a); проверяет посылка шага 0.
- Живые тесты (`-m harness_smoke`) ревьюер стадии 0 не прогонял: `test_c36_relay_flow_live_prototype`, `test_routing_epoch_live`, `test_fencing_live`, (б) 30 kill и сам тест условия отмены. Числа автора `30/30` через relay и `relayed_delta=30` ревьюером не воспроизводились.
- I1–I6 ревьюер не перепрогонял; свои I7–I10 прогнал по одному разу на копии (файл восстановлен, `cmp` — RESTORED). I11, расширенный (в), hazard-тест Event, текст по режиму — предсказано, не прогнано. Diff после правок (без дренажа, с обвязкой, с параметром режима) не применялся и не тестировался.
- Зависание `Event.set()` воспроизведено на stdlib и настоящем `ReaderGoneQueue`, не на настоящем PM; вероятность окна «kill внутри `is_set()`» не измерена, «0 из 226» его не снимает.
- Счётчики «отправлено `camera_0`» и «принято `preprocessor`» по-прежнему не выбраны; выбор отдан исполнителю шага 0, а порог CTO утверждает до прогона, то есть до выбора. Рекомендация ревьюера раунда 2: назвать кандидатов чтением до утверждения порога и записать в бриф; ревьюер их не искал, я тоже.
- Место счётчика `queue_system_evict_blocked` (у отправителя, а не у PM) — по чтению `router_manager.py:937`, `queues/core/manager.py:529`; на настоящем PM не проверено. Откуда читается разбивка `data_evicted.<жертва>` — не выяснено.
- Применяются ли `FW_USE_KIND_CHANNELS` и `MULTIPROCESS_USE_KIND_CHANNELS` к роутеру так, как кажется по `router_manager.py:2093` (нужна ли пара env), не выяснено; от этого зависит, включены ли kind-каналы в `g7_*`-пробах на самом деле.
- Рычаг авто-рестарта (`FW_AUTORESTART=0`, `restart_policy.enabled=false`) и `run_gate=True` без START — по чтению кода ревьюера, на стенде не проверены. Стендового скрипта `probe_c36_cancel_condition_live.py` нет.
- Расхождение класса и срока шага 0 снято единой строкой (`heavy`, сима, окно стенда после дня №1 по заданию полосы, но до слота писателя C-36/A).
- Ветку/worktree Ф ревьюер не нашёл (`git log --all --since=2026-11-17 -- <PM-файл>` пуст): что «Ф пишет PM-файл параллельно» — из задания, не проверено; хунки Ф оценены по handoff `docs/handoffs/2026-11-20_system-run-state_lane-f-continue.md`.
- `sentrux check` не гонялся ни автором, ни ревьюером; отсутствие новых импортов между слоями — по чтению. qex ревьюер не использовал (искал `git grep`), индекс не проверял.
- (б) 30 kill на живом стенде не прогнан: тяжёлый класс; наблюдаемый счётчик кадров потребителя не выбран и не проверен (выбирает шаг 0). Как отключить авто-рестарт монитора и закрыть run-гейт в (б) — по докстрингам harness, не проверено.
- **Р2 — открытый вопрос владельцу/CTO:** автор — ERROR при обоих режимах, ревьюер — WARNING при `false`, ERROR при `true`; текст при `false` без «глухо» в любом случае.
- **Долг (C36A-11), решение владельца:** (1) `bool(reuse_cfg)` превращает строку `"false"` в `True` — тихий откат умолчания; типизация значения ключа не проверена; нужна ли валидация или строгий разбор — решает владелец. (2) Проба лезет в приватный `q._rlock` из файла PM; публичный метод на `ReaderGoneQueue` был бы чище, но файл в «Не трогать» — записать долгом. (3) `setdefault` → `__init__` внесено в «Как это работает»; проверить, что очистка при удалении процесса закрыта тестом (предсказано, не прогнано).
- Докстринг `queues/core/reader_gone.py:22-25` («Рестарт метку НЕ взводит») станет ложью при A; файл в «Не трогать» — разрешить правку докстринга или записать долгом.
- Живые рестартующие тесты `test_autorestart_all_live`, `test_fault_injection_live`, `test_wire_status_live`, `test_g7_soak_probe` вне прежней приёмки — не прогнаны.
- (в) проверен на spawn-читателе stdlib, а не на `GenericProcess` за настоящим `ProcessRegistry` (это есть у расследования: свежие очереди → 0/57 глухих).
- Дыра A при kind-каналах и потеря широковещания выжившего — выведены чтением, не проверены.
- Окно до применения refresh: билеты выживших в брошенную очередь теряются (ADR-PMM-010), с меткой «читатель ушёл» их feeder отпускается. Счётчик потерь этого окна я не искал.
- Каскад (несколько рестартов подряд): процессы, перезапущенные раньше, держат стейл-ссылки на перезапущенных позже и тоже уходят на relay. Доля трафика через PM растёт до switch. Выведено чтением.
- Займ SHM кадра (`_frame_loan_active`, `on_evict`) при доставке relay'ем из PM — не проверял.
- Проба берёт `_rlock` брошенной очереди на ≤ 40 мс; живой вытесняющий писатель в это время может получить `Empty` в `remove_old_if_full` и потерять один `put` в брошенную очередь — вреда нет, не измерено.
- Windows и Orin не проверены. На Windows у `mp.Queue` `_rlock` есть, `_wlock` нет; проба та же.
- Счётчик живёт в памяти PM (как `instance_restarts`), после перезапуска приложения обнуляется.
- Шумность ERROR при A (почти каждый kill простаивающего потребителя) — оценка по числам расследования и по чтению diff ревьюером (C36A-6), не по прогону PM; после правки текста по режиму оценка шумности при WARNING не делалась.
- Все числа — один прогон на общей машине.

## Приложение: прототипы тестов (одноразовый worktree; для tester — образец механики, не ожидания; **требования к tester в основном тексте приоритетнее** — прототип не проверяет счётчик и строку на умолчании, не требует шпиона на занятость замка, оставляет повторы ×3 и не имеет hazard-теста Event)

`multiprocess_framework/modules/process_manager_module/tests/_c36_helpers.py`:

```python
# -*- coding: utf-8 -*-
"""Помощники C-36 для spawn-детей: только stdlib, чтобы ребёнок не тянул PM."""

import time


def hold_read_lock_forever(q, ready) -> None:
    """Взять межпроцессный замок чтения очереди и ждать убийства (модель «убит внутри get»)."""
    q._rlock.acquire()
    ready.set()
    time.sleep(60)


def read_one(q, conn, timeout_s: float) -> None:
    """Прочитать один элемент очереди и отдать его родителю через pipe ('EMPTY' при таймауте)."""
    try:
        conn.send(q.get(timeout=timeout_s))
    except Exception as exc:  # noqa: BLE001 — Empty и прочее родителю как строка
        conn.send(f"EMPTY:{type(exc).__name__}")
    finally:
        conn.close()
```

`multiprocess_framework/modules/process_manager_module/tests/test_c36_restart_queues_prototype.py`:

```python
# -*- coding: utf-8 -*-
"""C-36 (вариант A + громкая проба) — прототип тестов брифа Д2, не для ветки.

Настоящие: ``ProcessManagerProcess.restart_process``, ``SharedResourcesManager``/PSR, ``ReaderGoneQueue``,
межпроцессный ``_rlock``, осиротевший SIGKILL'ом настоящего spawn-помощника, настоящий spawn-читатель.
Двойники: реестр OS-процессов (``MockProcessRegistry``), ``communication`` (MagicMock).
"""

from __future__ import annotations

import multiprocessing as mp
import os
import signal
import threading
import time

from ...shared_resources_module.core.shared_resources_manager import SharedResourcesManager
from . import _c36_helpers
from .conftest import make_pm

_NAME = "cam"
_QUEUES = {"system": {"maxsize": 100}, "data": {"maxsize": 50}}
_CTX = mp.get_context("spawn")


def _rig(reuse: bool | None):
    cfg = {"class": "pkg.Cam", "queues": dict(_QUEUES)}
    pm = make_pm(process_configs={_NAME: cfg})
    srm = SharedResourcesManager(manager_name="c36_srm")
    assert srm.initialize() is True
    assert srm.register_process(_NAME, dict(cfg)) is True
    pm.shared_resources = srm
    pm.update_config("start_ready_timeout_s", 0)
    if reuse is not None:
        pm.update_config("restart_reuse_queues", reuse)
    return pm, srm


def _orphan_read_lock(q) -> None:
    if not q._rlock.acquire(False):
        return  # уже осиротел прошлой итерацией (рестарт переиспользовал очередь) — состояние то же
    q._rlock.release()
    ready = _CTX.Event()
    helper = _CTX.Process(target=_c36_helpers.hold_read_lock_forever, args=(q, ready), daemon=True)
    helper.start()
    assert ready.wait(20.0), "помощник не взял замок за 20 с"
    os.kill(helper.pid, signal.SIGKILL)
    helper.join(10.0)
    assert helper.exitcode == -9
    assert q._rlock.acquire(False) is False  # замок осиротел (проба точная: читателей нет)


def _read_in_child(q, timeout_s: float):
    parent, child = _CTX.Pipe(duplex=False)
    reader = _CTX.Process(target=_c36_helpers.read_one, args=(q, child, timeout_s), daemon=True)
    reader.start()
    child.close()
    got = parent.recv() if parent.poll(timeout_s + 20.0) else "NO_REPLY"
    reader.join(5.0)
    return got


def _restart(pm) -> bool:
    box: dict = {}
    t = threading.Thread(target=lambda: box.setdefault("ok", pm.restart_process(_NAME)), daemon=True)
    t.start()
    t.join(30.0)
    assert not t.is_alive(), "restart_process завис дольше 30 с"
    return box.get("ok")


def _c36_errors(pm) -> list[str]:
    return [str(c.args[0]) for c in pm._log_error.call_args_list if c.args and "C-36" in str(c.args[0])]


def test_system_lock_orphaned_default_restart_reader_gets_command_10_of_10() -> None:
    """(в): помощник умирает с _rlock system; после restart_process новый читатель получает команду за 1 с."""
    pm, srm = _rig(reuse=None)
    got_ok = 0
    for i in range(10):
        _orphan_read_lock(srm.get_process_data(_NAME).queues["system"])
        assert _restart(pm) is True
        q_new = srm.get_process_data(_NAME).queues["system"]
        q_new.put({"command": "ping", "i": i})
        if _read_in_child(q_new, 1.0) == {"command": "ping", "i": i}:
            got_ok += 1
    assert got_ok == 10


def test_reuse_true_orphaned_data_lock_is_loud_counted_and_recreated() -> None:
    """(г): restart_reuse_queues=true + занятый _rlock data -> ERROR с процессом и типом, счётчик 1, очередь новая."""
    pm, srm = _rig(reuse=True)
    old_data = srm.get_process_data(_NAME).queues["data"]
    old_system = srm.get_process_data(_NAME).queues["system"]
    _orphan_read_lock(old_data)
    assert _restart(pm) is True
    errors = _c36_errors(pm)
    assert any("очередь 'data' процесса 'cam'" in e for e in errors), errors
    assert not any("очередь 'system'" in e for e in errors), errors
    sup = pm._cmd_supervision_status({"process": _NAME})
    assert sup["processes"]["cam"]["orphaned_read_locks"] == 1, sup
    new = srm.get_process_data(_NAME).queues
    assert new["data"] is not old_data
    assert new["system"] is not old_system  # пересоздан весь процесс: incarnation одна на процесс
    assert old_data.is_reader_gone() is True


def test_free_locks_with_live_evicting_writer_no_false_alarm() -> None:
    """Нет ложной тревоги: живой вытесняющий писатель держит _rlock 15 мс в момент пробы — замок не «осиротевший»."""
    pm, srm = _rig(reuse=True)
    q = srm.get_process_data(_NAME).queues["data"]
    for _ in range(3):
        held = threading.Event()

        def _evictor() -> None:
            q._rlock.acquire()
            held.set()
            time.sleep(0.015)
            q._rlock.release()

        t = threading.Thread(target=_evictor, daemon=True)
        t.start()
        assert held.wait(2.0)
        assert _restart(pm) is True
        t.join(2.0)
    assert _c36_errors(pm) == []
    sup = pm._cmd_supervision_status({"process": _NAME})
    assert sup["processes"]["cam"]["orphaned_read_locks"] == 0
    assert srm.get_process_data(_NAME).queues["data"] is q  # reuse=true и свободный замок: identity та же


def test_default_restart_abandons_and_marks_old_queues() -> None:
    """A по умолчанию: новые очереди, старые помечены «читатель ушёл», новые — нет."""
    pm, srm = _rig(reuse=None)
    old = dict(srm.get_process_data(_NAME).queues)
    assert _restart(pm) is True
    new = srm.get_process_data(_NAME).queues
    assert sorted(new) == ["data", "system"]
    assert all(new[k] is not old[k] for k in old)
    assert [old[k].is_reader_gone() for k in sorted(old)] == [True, True]
    assert [new[k].is_reader_gone() for k in sorted(new)] == [False, False]
```

`backend_ctl/tests/test_c36_relay_flow_live_prototype.py`:

```python
# -*- coding: utf-8 -*-
"""C-36 (вариант A), минимальная живая проба условия отмены — прототип брифа Д2, не для ветки.

Настоящий PM (BackendHarness, base.yaml): ``process.restart`` пересоздаёт очереди ``preprocessor`` (A по умолчанию
прототипа), выживший ``devices`` шлёт ему N билетов ``routing.probe`` (peer-путь ``send_to_process``). «Держит поток»:
дошли все N (``health.errors`` нового воплощения >= N), все N ушли через hub-relay, ``errors_delivery_failed``
отправителя не вырос. Груз — command в system-очередь, НЕ data-линия (ограничение прототипа).
"""

from __future__ import annotations

import time

import pytest

from backend_ctl.harness import BackendHarness
from backend_ctl.protocol import unwrap
from backend_ctl.tests.conftest import bookmark_cursor as _bookmark
from backend_ctl.tests.test_routing_epoch_live import _probe, _wait_health_errors

_SENDER = "devices"
_PEER = "preprocessor"
_N = 30
_PORT = 8797


def _router_stat(drv, proc: str, key: str) -> int:
    node = drv.introspect_router_stats(proc, timeout=5.0)
    for _ in range(4):
        if isinstance(node, dict) and "router_stats" in node:
            return int((node.get("router_stats") or {}).get(key, 0) or 0)
        node = node.get("result") if isinstance(node, dict) else None
    return -1


@pytest.mark.harness_smoke
def test_surviving_writer_flow_to_restarted_peer_over_relay() -> None:
    harness = BackendHarness(with_base=True, port=_PORT)
    drv = harness.start()
    try:
        sub = unwrap(drv.state_subscribe(f"processes.{_PEER}.**", timeout=8.0), leaf=True)
        assert sub.get("status") == "ok", sub
        r = unwrap(drv.send_command("ProcessManager", "process.restart", {"process_name": _PEER}, timeout=30.0), leaf=True)
        assert r.get("success") is True, r
        time.sleep(3.0)  # новое воплощение + routing.refresh у выжившего
        cursor = _bookmark(drv)
        relayed0 = _router_stat(drv, _SENDER, "relayed_to_hub")
        failed0 = _router_stat(drv, _SENDER, "errors_delivery_failed")
        t0 = time.time()
        for i in range(_N):
            _probe(drv, _SENDER, _PEER, f"flow-{i}")
        errors, cursor = _wait_health_errors(drv, _PEER, time.time() + 30.0, cursor, min_errors=_N)
        took = time.time() - t0
        relayed = _router_stat(drv, _SENDER, "relayed_to_hub") - relayed0
        failed = _router_stat(drv, _SENDER, "errors_delivery_failed") - failed0
        print(f"C36-FLOW N={_N} health.errors={errors} relayed_delta={relayed} delivery_failed_delta={failed} took={took:.2f}s")
        assert errors is not None and errors >= _N
        assert relayed == _N
        assert failed == 0
    finally:
        harness.stop()
```
