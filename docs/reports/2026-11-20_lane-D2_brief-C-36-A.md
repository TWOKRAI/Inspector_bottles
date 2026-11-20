# C-36, вариант A: очередь на воплощение по умолчанию и громкая проба замка чтения — бриф писателю

Брифу нужен слот писателя (после дня №1 с железом) и файл PM строго после Ф; сам по себе код не меняет.

Полоса Д2, 2026-11-20. Автор — teamlead (Opus), режим diagnose-and-report. Дерево — `a15739023` (= `main` `ad3dc7b72` + документы Д2), macOS (Darwin 27.2), Python 3.12.13. Опыты — только в одноразовом worktree `/private/tmp/claude-501/d2-c36a-wt` (`--detach a15739023`, после работы удалён). Импорт доказан строкой `IMPORT /private/tmp/claude-501/d2-c36a-wt/multiprocess_framework/__init__.py` перед каждым прогоном. Все прогоны — через `machine_gate.sh light|medium inspector-bottles-d2`. Входы: `docs/reports/2026-11-20_lane-D2_C-36.md` (механизм и числа), `docs/reports/2026-11-20_cto-review-1.0.md:50` (вердикт «A сейчас, с громкой пробой из C; B после тега 1.0»), `plans/queue/defects.md:283`.

memory hits: `python scripts/memory/search.py restart reuse queues rlock incarnation` -> `docs/claude/memory/feedback_mp_queue_is_async_in_tests.md`, `docs/claude/memory/project_switch_routing_stale.md`.

Обозначения команд ниже:
- `G` = `bash /Users/twokrai/Project_code/Inspector_bottles/scripts/machine_gate.sh`.
- `R` = скрипт-обёртка: `cd <worktree>; export PYTHONPATH=<worktree> INSPECTOR_PID_FILE=/tmp/d2_c36a_pid.json PYTHONUTF8=1; <main>/.venv/bin/python -c "import multiprocess_framework as m; print('IMPORT', m.__file__)"; <main>/.venv/bin/python -m pytest -q --tb=short -p no:cacheprovider "$@"`.

## Цель

1. Рестарт процесса по умолчанию даёт новому воплощению свежие очереди (A). Новое воплощение после `kill -9` в любой момент читает свои очереди. Глухих воплощений 0.
2. Замок чтения (`_rlock`), занятый без живого читателя, на рестарте даёт ERROR с именем процесса и типом очереди и +1 к счётчику. `_drain_process_queues` больше не глотает это молча.
3. Трафик выжившего писателя к перезапущенному потребителю доходит (через hub-relay PM). Если это не так на настоящем PM — решение A отменяется (условие CTO). Тест этого условия — раздел «Живой тест условия отмены».

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
3. **Как выжившие узнают о новой очереди.** Никак: `mp.Queue` не пиклится вне spawn (ADR-PMM-010, `process_manager_module/DECISIONS.md:100`). Ребёнок в `_cmd_routing_refresh` (`process_module/commands/builtin_commands.py:3979-4055`) видит incarnation ≠ локальной и зовёт `psr.drop_process_queues(name)` (`shared_resources_module/state/process_state_registry.py:126-150`). Дальше его `send_to_process` → `_deliver_by_targets` (`router_module/core/router_manager.py:675`) → `_queue_absent` → `_relay_via_hub` (`:769-783`, `:911-955`): билет едет командой `router.relay` в **system-очередь PM** (maxsize 100, never-drop: `process_module/configs/process_launch_config.py:14-15`, `queues/core/manager.py:512-529`). PM: `_cmd_router_relay` (`builtin_commands.py:3915-3933`) → `router.send_async` → свежий PSR PM → новая очередь. Хаб по умолчанию `"ProcessManager"` (`router_manager.py:146`).
   - **Это и делает путь A с data-трафиком к перезапущенному:** весь трафик выживших к нему идёт через message-processor PM навсегда — до switch (новые bundle) или перезапуска приложения. ADR-PMM-010 именно это отверг для restart: «Всегда сажать соседей на hub-relay после restart — все кадры через system-очередь PM (бутылочное горло)» (`DECISIONS.md:114`).
   - Наблюдено на настоящем PM (раздел «Живой тест»): после рестарта `preprocessor` 30 из 30 билетов `devices → preprocessor` дошли, все 30 через relay.
   - **Дыра A:** каналы `{target}_{qtype}` (`process_module/communication/process_communication.py:83-100`) у выжившего привязаны к СТАРОЙ очереди; refresh их не снимает. Они работают при явном `channel`, маршруте dispatcher или kind-каналах. Kind-каналы по умолчанию выключены (`router_manager.py:173-179`; включаются env `MULTIPROCESS_USE_KIND_CHANNELS` или `router.use_kind_channels`). Живых `register_route(` вне тестов нет (`git grep -n "register_route(" -- '*.py' ':!**/tests/**'` → только определения). При включённых kind-каналах выживший пишет в брошенную очередь — тихая потеря. Выведено чтением, не проверено.
   - Широковещание выжившего (`ProcessCommunication.broadcast` → `queue_registry.broadcast_message` по своей PSR, `process_communication.py:227`) после `drop_process_queues` перезапущенного не видит; relay для широковещания нет. Выведено чтением, не проверено.
4. **Накопленное в старой очереди.** Выбрасывается вместе с объектом: PM заменяет его в PSR, читателя у старой очереди больше нет. Сегодня при `reuse=True` то же выбрасывает `_drain_process_queues` (`:4886-4911`). Положенное выжившими по старой ссылке до применения refresh теряется (окно ADR-PMM-010, `DECISIONS.md:106`). **Метку «читатель ушёл» брошенные очереди сегодня не получают:** `mark_reader_gone=False` `:5709`; `plans/lifecycle-stop-ownership.md:127` («не проверено»). Без метки писатель с кадром крупнее pipe висит на выходе (ADR-PMM-030, `DECISIONS.md:1252-1258`: 0/5 без метки). Причина «рестарт не маркирует» (`DECISIONS.md:1295-1299`) — переиспользование; при A её нет.
5. **Relay-классы T/L.** `process.relay` (класс T, `:1697`, `:1747`) идёт GUI → PM → свежий PSR PM; при A работает как сегодня. L не задет. Это из отчёта расследования (`2026-11-20_lane-D2_C-36.md:54`); сам я T/L не проверял.
6. **Что уже покрыто тестами при `reuse=False`.** `git grep -n -F restart_reuse_queues -- '*.py'`: из тестов — только `backend_ctl/tests/test_fencing_live.py` (живой: incarnation, epoch, fence старого инстанса). Поток данных к перезапущенному, глухота, метка на брошенных очередях — не покрыты нигде. Обратный контракт закреплён: `backend_ctl/tests/test_routing_epoch_live.py:140-170` требует прямой доставки после restart (`relayed_to_hub` не растёт). При A этот тест красный (наблюдено, ниже).
7. **Вывод.** A «за флагом» рабочий: при `false` путь доставляет (30/30 через relay на настоящем PM). Чего не хватает:
   - (а) умолчание `True`;
   - (б) метки «читатель ушёл» на брошенных очередях;
   - (в) пробы замка; `_drain_process_queues` глотает `Empty` от занятого замка молча (`:4908`);
   - (г) счётчика.

## Решения для владельца/CTO

- **Р1. Умолчание.** Варианты:
  - O1 — в коде PM `None → False` (прототип ниже); `true` остаётся откатом.
  - O2 — код не трогать, ключ `restart_reuse_queues: false` в конфиге оркестратора прототипа. Место ключа в конфигах прототипа я не нашёл; его ищут в слоте.
  - O3 — оставить `True` и лечить только пробой с пересозданием (это вариант C, не A).
  
  **Рекомендация — O1.** Дефект во framework, не в прототипе (принцип владельца 2: чинить framework вперёд). O2 оставляет глухим любого другого пользователя framework. O3 противоречит правилу владельца 2026-10-26 («очереди убитого ребёнка не переиспользуются»). Без правки транспорта C-36 в продукте закрывает O1 + метка (б) + проба (в, г). O1 меняет решение B ADR-PMM-010 для restart и горячий путь (relay) — **это решение CTO**. Условие отмены CTO написано как раз для этого шага.
- **Р2. Уровень голоса при A.** При `reuse=false` занятый замок вреда не делает: очередь брошена. При этом ERROR будет почти на каждом рестарте после `kill` простаивающего потребителя (расследование: data 142/142). Рекомендация — оставить ERROR, как сказал CTO: строка и есть счёт событий C-36. Альтернатива — WARNING при `false`, ERROR при `true`. Решает CTO.
- **Р3. `reuse=true` + занятый замок.** В прототипе тогда весь процесс уходит на свежие очереди (откат C) и даёт отдельный ERROR. Иначе путь отката оставляет воплощение глухим. Это шире «громкой пробы»; нужно подтверждение CTO.
- **Р4. Kind-каналы при A** (п. 3, «дыра A»). Варианты:
  - снимать каналы `{name}_*` в `routing.refresh` — правка `builtin_commands.py`, вне файла PM;
  - отказ на старте при kind ON и `reuse=false`.
  
  До решения это строка рисков. Решает CTO.
- **Р5. Потолок relay на data-линии.** Порог кадров в секунду через system-очередь PM не измерен. Числа в тесте условия отмены (ниже) — мои предложения; утверждает CTO.

## Файлы

**Править (в слоте, после слияния Ф):**
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` — умолчание, проба, метка, счётчик, дренаж только при reuse (diff ниже).
- `backend_ctl/tests/test_routing_epoch_live.py:140-170` — ожидание B («relay не растёт») сменить на A («доставлено и через relay»). Это смена контракта: только вместе с ADR.
- новые тесты: `process_manager_module/tests/test_c36_restart_fresh_queues.py` (+ помощник spawn только на stdlib), `backend_ctl/tests/test_c36_relay_flow_live.py`, живой тест data-линии (ниже). Пишет слепой tester по разделу «Тесты»; прототипы — в приложении.
- `process_manager_module/DECISIONS.md` — поправка ADR-PMM-010 (restart: B → A по умолчанию, `true` — откат, цена: relay навсегда) и ADR-PMM-030 («Почему рестарт не маркирует» → при `reuse=false` маркирует); затем `python -m scripts.sync`.
- `process_manager_module/STATUS.md` / `README.md` — ключ, умолчание, поле `orphaned_read_locks` в `supervision.status`.
- `plans/queue/defects.md:283` — статус C-36.
- Если поля `supervision.status` описаны в CAPABILITIES или контракте `backend_ctl` — перегенерировать. Я не проверял.

**Не трогать:** `shared_resources_module/core/shared_resources_manager.py`, `queues/core/manager.py`, `queues/core/reader_gone.py`, `router_module/**`, `process_module/commands/builtin_commands.py` (если Р4 не решён иначе), `process_manager_module/launcher/spawner.py`, `queue_channel.py`, `data_receiver.py`.

**Конфликтные зоны:**
- `process_manager_process.py` и `launcher/spawner.py` сейчас у полосы Ф: правка PM-файла строго после слияния Ф и rebase на свежий `main`. Строки этого брифа после Ф сдвинутся: якоря — имена функций.
- К (`camera_device`) и Р2 (визит) по их планам PM-файл не трогают. Их ветки я не открывал (запрещено брифом) — не проверено.

**Последовательность:** слияние Ф → rebase → слепой tester (тесты по разделу ниже, ДО кода) → writer (diff) → инъекции → Opus-ревью (concurrency/IPC — обязательно) → живой тест условия отмены на стенде → слияние → `defects.md`, ADR, `scripts.sync`.

## Правка (diff прототипа)

Проверен на одноразовом worktree: `ruff check -q` → `rc=0`. Радиус: 9 файлов рестарта и PM → `95 passed in 45.08s` (`G medium inspector-bottles-d2 bash R test_routing_epoch.py test_restart_process_failure_unmarks.py test_supervisor_restart_incarnation.py test_supervisor_restart_incarnation_hazards.py test_lifecycle_restart_reply.py test_run_restart_incarnation.py test_run_restart_incarnation_hazards.py test_process_manager_process.py shared_resources_module/tests/test_writer_outlives_reader_acceptance.py`). В ветку не коммитился.

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
@@ -5728,5 +5817,7 @@ class ProcessManagerProcess(ProcessModule):
             self.shared_resources.process_state_registry.update_state(process_name, status="initializing")
             # Дренаж переиспользованных очередей: новый инстанс стартует чистым.
-            self._drain_process_queues(process_name)
+            # Свежие очереди пусты — дренировать нечего.
+            if reuse_queues:
+                self._drain_process_queues(process_name)
         ids_after = self._process_queue_ids(process_name)
 
```

Как это работает:
- Проба идёт после подтверждённой смерти и до `register_process`: в PSR ещё очереди убитого. 5 попыток `acquire(False)` с паузой 10 мс: свободный замок отвечает сразу; занятый стоит ≤ 40 мс на очередь.
- Ложное срабатывание от живого вытесняющего писателя (`queues/core/manager.py:532`, `get_nowait` из чужой очереди держит замок микросекунды) отсекает повтор (инъекция I4 ниже).
- Счётчик — `orphaned_read_locks` на процесс в `supervision.status` (рядом с `instance_restarts`). Строка ERROR: `C-36: очередь '<qtype>' процесса '<name>': замок чтения занят без живого читателя …`.

## Тесты и break-injection

### Прототип (одноразовый worktree, настоящие PM `restart_process`, SRM/PSR, `ReaderGoneQueue`, межпроцессный `_rlock`)

Замок осиротевает настоящим способом: spawn-помощник берёт `q._rlock` и получает `SIGKILL` (`exitcode == -9`, затем `q._rlock.acquire(False) is False`). Двойники — реестр OS-процессов (`MockProcessRegistry`) и `communication` (MagicMock). Каждый `restart_process` — в daemon-потоке с `join(30)`.

| тест | что проверяет | литералы |
|---|---|---|
| (в) `test_system_lock_orphaned_default_restart_reader_gets_command_10_of_10` | 10 раз: осиротить `_rlock` system → `restart_process` (умолчание) → spawn-читатель на новой очереди получает `{"command": "ping", "i": i}` за 1 с | `got_ok == 10` |
| (г) `test_reuse_true_orphaned_data_lock_is_loud_counted_and_recreated` | `restart_reuse_queues=true`, осиротить `_rlock` data | ERROR содержит `очередь 'data' процесса 'cam'`, про `system` строки нет; `orphaned_read_locks == 1`; data и system — новые объекты; старая data `is_reader_gone() is True` |
| ложная тревога | `reuse=true`, поток держит `_rlock` data 15 мс в момент пробы (×3) | строк `C-36` 0; счётчик 0; identity data та же |
| метка | умолчание | новые объекты; старые `is_reader_gone` `[True, True]`, новые `[False, False]` |

Команда: `G medium inspector-bottles-d2 bash R multiprocess_framework/modules/process_manager_module/tests/test_c36_restart_queues_prototype.py` → `4 passed, 1 warning in 7.26s`.

**Матрица инъекций.** Предсказания записаны до прогона. Скрипт подменяет файл PM, гоняет файл тестов и возвращает прототип (`restored: True`). Команда: `G medium inspector-bottles-d2 <python> inject_c36.py`.

| инъекция | предсказано (падают) | наблюдено |
|---|---|---|
| I0 прототип | ничего | `4 passed in 8.27s` |
| I1 умолчание снова `True` (проба и откат C на месте) | метка | метка (`assert False`, identity старая); (в) зелёный — его вытаскивает откат C |
| I2 пробы нет (`stuck = []`) | (г) | (г): `AssertionError: []` |
| I3 ERROR пробы заглушён | (г) | (г): в списке осталась только строка отката |
| I4 проба без повтора (1 попытка) | ложная тревога | ложная тревога: строка `C-36` появилась |
| I5 метки на брошенных нет | метка, (г) | метка `[False, False] == [True, True]`; (г) `assert False is True` |
| I6 исходный `main` | все 4 | все 4: (в) `assert 0 == 10`; (г) `AssertionError: []`; ложная тревога `KeyError: 'orphaned_read_locks'` (поля нет — красный по форме, не по поведению); метка `assert False` |

Честная оговорка по I6: в первом прогоне (в) упал по другой причине — `помощник не взял замок за 20 с`. На `main` очередь переиспользуется, а её замок уже осиротел; помощник второй итерации висел на `acquire()`. Я поправил тест: уже осиротевший замок не берётся повторно. После этого (в) упал с предсказанным `assert 0 == 10`. Остальные строки совпали с предсказанием с первого раза.

### Требования к слепому tester (пишет ДО кода, по этому разделу, не по прототипу)

- (в) и (г) — как в таблице. Ожидаемые значения — литералы. Хотя бы один тест на настоящих объектах: spawn-помощник + `SIGKILL`, не мок замка.
- (б) **data-линия, 30 kill.** Живой стенд (раздел ниже), `preprocessor` (потребитель `camera_0`) простаивает: кадров нет (run-гейт закрыт). 30 раз `kill -9` по pid из `supervision.status`, затем `process.restart`. После каждого ready: 3 команды (`introspect.status` → ответ за 1 с) и 3 элемента data (кадры `camera_0` после открытия гейта или `routing.probe` с data-грузом; надо выбрать наблюдаемый эффект — счётчик кадров потребителя в `introspect.telemetry`). «Глухой» = за 5 с после ready не дошло ни одной из 3 команд или ни одного из 3 элементов. Порог: **0/30**. Контроль на `main` (`reuse=True`): предсказание **≥ 29/30 глухих** (у стенда 55/55, на kill 142/142). Не прогнано: тяжёлый класс (≈ 30 × 4 с + подъём), имя счётчика кадров не проверено.
- (г) по тексту строки: подстроки `очередь 'data'`, `процесса '<name>'`, `C-36`; счётчик через `supervision.status`.
- Инъекции для приёмки — те же I1–I6. Набор падающих предсказывается до прогона; таблица «предсказано / наблюдено» — в отчёт.

## Живой тест условия отмены (настоящий PM)

**Формализация «держит поток».** После `process.restart` потребителя выживший писатель шлёт N билетов обычным peer-путём (`send_to_process`). Держит, если одновременно:
- дошло ≥ N (наблюдаемый эффект у нового воплощения);
- `relayed_to_hub` писателя вырос ровно на N (доказательство, что шли путём A, а не по старой очереди);
- `errors_delivery_failed` писателя вырос на 0.

**Красный отменяет решение A.**

**Прогнано (минимум, light, ~12 с на прогон):** стенд — `BackendHarness(with_base=True)` (настоящий PM, настоящие дети base.yaml); писатель `devices`, потребитель `preprocessor`, груз `routing.probe` → `health.report` (command в system-очередь), N = 30, порт 8797.
- Прототип (A по умолчанию): `G light inspector-bottles-d2 bash R -s -rf -m harness_smoke backend_ctl/tests/test_c36_relay_flow_live_prototype.py` → `C36-FLOW N=30 health.errors=30 relayed_delta=30 delivery_failed_delta=0 took=2.00s`, `1 passed, 1 warning in 11.74s`.
- Контроль, исходный PM `main` (тот же тест): `C36-FLOW N=30 health.errors=30 relayed_delta=0 delivery_failed_delta=0 took=2.13s`, `E assert 0 == 30`, `1 failed in 11.95s`. Тест различает путь A и прямой путь: на `main` то же доставляется напрямую.
- Существующий тест контракта B на прототипе: `G light inspector-bottles-d2 bash R -rf -m harness_smoke "backend_ctl/tests/test_routing_epoch_live.py::test_peer_send_after_restart_delivered"` → доставка есть (в логе `probe:post-restart` у `preprocessor`), падение на последнем assert: `relayed_to_hub 0→1`, `1 failed in 15.83s`. Как предсказано: при A этот тест надо переписать (п. «Файлы»).
- Без `-m harness_smoke` живые тесты `backend_ctl` пропускаются (`1 skipped in 0.12s`): не путать skip с зелёным.

**Что минимум НЕ доказывает:**
- груз — command в system-очередь, не data-линия;
- темп задаёт driver (30 билетов за 2 с), это не кадры камеры;
- потолок relay не мерян.

**Полный тест условия отмены (слот, стенд; не прогнан).** Тот же `BackendHarness`. Рестарт **одного** процесса оставляет выжившими всех прочих (protected важен только для switch). Значит, писатель — `camera_0`, потребитель — `preprocessor`. Шаги:
- открыть run-гейт, дождаться потока, `process.restart preprocessor`, окно T = 10 с после ready;
- метрики: кадры, отправленные `camera_0` за окно; кадры, принятые и обработанные `preprocessor`; `relayed_to_hub`, `errors_delivery_failed`, `data_evicted.preprocessor.data` у `camera_0`; `system_evict_blocked` PM; статусы всех процессов.

Порог (предложение, утверждает CTO — Р5):
- принято ≥ 95 % отправленного (вытеснение drop_oldest считается отдельно, не как потеря доставки);
- `errors_delivery_failed` +0;
- `system_evict_blocked` PM +0;
- ни одного `unresponsive` за окно;
- `relayed_to_hub` ≈ числу кадров.

Красный по любому пункту — A отменяется (или Р5 пересматривается CTO). Плюс тот же тест с 3 рестартами подряд разных процессов (каскад).

## Приёмка

1. `G medium inspector-bottles-d2 bash R process_manager_module/tests/test_c36_restart_fresh_queues.py` — зелёный. Матрица I1–I6 — каждая инъекция роняет предсказанный набор (таблица выше — образец).
2. `G medium inspector-bottles-d2 bash R` + радиус рестарта (9 файлов из раздела «Правка») — 0 failed (прототип: `95 passed`).
3. `G light inspector-bottles-d2 bash R -m harness_smoke backend_ctl/tests/test_c36_relay_flow_live.py backend_ctl/tests/test_routing_epoch_live.py backend_ctl/tests/test_fencing_live.py` — зелёные (последний — fence при `reuse=false`, не прогонял).
4. Живой тест data-линии (условие отмены) и (б) 30 kill — на стенде в окне `stand`/`heavy` по `machine.lock`: глухих 0/30; пороги раздела выше.
5. `ruff check -q` на тронутых файлах; `sentrux check .` (новых нарушений слоёв нет: импорт `reader_gone` внутри framework, PM уже импортирует его через `process_registry.py:31`).
6. Opus-ревью (concurrency/IPC).

## Границы

- Только вариант A + проба. B (очередь без межпроцессного замка чтения, перенос вытеснения и дренажа к читателю) — после тега 1.0, не здесь.
- Аномалия «13/13 на SemLock» и `mp.Event` — не здесь (CTO: слот до железа не тратить).
- `_wlock` убитого писателя проба не ловит и не лечит (расследование: 0/226, не воспроизведено).
- Транспорт (`router_module`, `shared_resources_module`) не меняется. При решении Р4 «снимать каналы» — отдельная правка `builtin_commands.py`.

## Что осталось открытым / ненадёжно

- **Data-линия к перезапущенному на настоящем PM не прогнана.** Прогнан только command-груз через relay (30/30); кадры камеры через system-очередь PM (maxsize 100, never-drop) могут её переполнить и задеть heartbeat всех детей. Потолок не измерен — это и есть главный риск A и условие отмены.
- (б) 30 kill на живом стенде не прогнан: тяжёлый класс; наблюдаемый счётчик кадров потребителя не выбран и не проверен.
- (в) проверен на spawn-читателе stdlib, а не на `GenericProcess` за настоящим `ProcessRegistry` (это есть у расследования: свежие очереди → 0/57 глухих).
- Дыра A при kind-каналах и потеря широковещания выжившего — выведены чтением, не проверены.
- Окно до применения refresh: билеты выживших в брошенную очередь теряются (ADR-PMM-010), с меткой «читатель ушёл» их feeder отпускается. Счётчик потерь этого окна я не искал.
- Каскад (несколько рестартов подряд): процессы, перезапущенные раньше, держат стейл-ссылки на перезапущенных позже и тоже уходят на relay. Доля трафика через PM растёт до switch. Выведено чтением.
- Займ SHM кадра (`_frame_loan_active`, `on_evict`) при доставке relay'ем из PM — не проверял.
- Проба берёт `_rlock` брошенной очереди на ≤ 40 мс; живой вытесняющий писатель в это время может получить `Empty` в `remove_old_if_full` и потерять один `put` в брошенную очередь — вреда нет, не измерено.
- Windows и Orin не проверены. На Windows у `mp.Queue` `_rlock` есть, `_wlock` нет; проба та же.
- Счётчик живёт в памяти PM (как `instance_restarts`), после перезапуска приложения обнуляется.
- Шумность ERROR при A (почти каждый kill простаивающего потребителя) — оценка по числам расследования, не по прогону PM.
- Все числа — один прогон на общей машине.

## Приложение: прототипы тестов (одноразовый worktree; для tester — образец механики, не ожидания)

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
