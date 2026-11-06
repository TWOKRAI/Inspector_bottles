# Ревью плана system-run-state (MODE: plan, стадия 0) — 2026-11-02

Сессия лида: inspector-bottles-40, полоса «Оператор». Ревьюер: reviewer (MODE: plan). Читал текст плана на коммите
3f5aa9c4e (ветка docs/system-run-state-approve, поверх 886c9cb7a). Код не запускал и не правил; факты сверены
git grep / чтением в этом же worktree. Пути даны от корня репозитория; PLAN = plans/2026-10-27_system-run-state.

memory hits: scripts/memory/search.py (system run state fault ack plan review) ->
docs/claude/memory/feedback_absence_of_news_is_not_evidence.md (R2 «молчание = не готов» с ним согласуется),
docs/claude/memory/feedback_the_plans_stated_cause_is_a_hypothesis.md (имена и пути плана сверены с кодом, расхождения ниже).

## Вердикт: CHANGES REQUESTED (итерация 1 из 2)

Ответы владельца В1–В8 внесены верно по существу (таблица в конце). Approve блокирует другое: машина состояний собрана
из кусков, которые между собой не сходятся (fault уходит сам в 1.3 и 1.4, §3.2 ведёт fault через stopping, topology.apply
обходит квитирование), а у задач 1.7 и 1.8 DESIGN не даёт слепому тестеру сигнатур, и FILES 1.8 неполон. Ниже 18 пунктов:
1–10 меняют задачи или design, 11–18 касаются привязки, цифр и остатков.

## Список (файл:строка → что не так → как исправить)

1. PLAN/design.md:64, :74-78, :156; PLAN/tasks/1.3.md:21-23; PLAN/tasks/1.4.md:19-22 → fault и stopping противоречат.
   Строка таблицы stopping (design.md:64) берёт вход «по аварии — сразу», а §3.5 (:156) и квитирование (:74-78) держат
   состояние fault до ack с отказом fault_stopping, пока идёт аварийная остановка. 1.4 п.3-4 (:19-22) заканчивает аварийную
   ветку в ready/not_ready («Итог: все paused → ready/not_ready»); 1.3 п.3 (:21-23) вводит «временно автоматический» выход
   из fault, который 1.7 потом удаляет. Между merge 1.3 и 1.7 машина нарушает design, а код 1.3 пишется, чтобы быть стёртым.
   Исправить: (а) design.md:64 — вход в stopping только «STOP оператора»; авария остаётся в fault с внутренним признаком
   fault_stop_done; (б) 1.3 п.3 — fault липкий: выход только system.shutdown, фразу «временно автоматический» удалить;
   (в) 1.4 п.3-4 — аварийная ветка после paused или срока остаётся в fault, fault_stop_done = True; RED
   test_fault_stop_done_keeps_fault; (г) 1.7 п.1 «Переход fault → … без ack удалить» заменить на «добавить ack»; TRAPS 1.7
   (:47-48) убрать. Тогда каждая точка merge — валидная машина, и ни одной строки не пишется на выброс.

2. PLAN/tasks/1.5.md:16-18; PLAN/design.md:183-185 → topology.apply обходит квитирование. 1.5 отказывает только в
   running и stopping; из fault apply проходит → booting → ready: оператор сменил рецепт и вышел из аварии без «Квитировать»,
   судьба last_fault не определена. Кроме того design.md:183 отказывает только в running, а 1.5 ещё и в stopping, и код
   отказа в обоих случаях "running" (для stopping имя неверно). Исправить: одно правило для design и 1.5 — apply в
   running|stopping|fault|shutting_down отказ с кодом = имени состояния (running|stopping|fault_unacknowledged|
   shutting_down; текст «сначала ОСТАНОВИТЬ» или «сначала Квитировать»); разрешён в booting|not_ready|ready. REDS 1.5 +2:
   test_apply_in_fault_refused_unacknowledged, test_apply_in_stopping_refused_stopping.

3. PLAN/design.md:58-66 → матрица (состояние × команда) неполна. Колонки START и STOP есть, ack только абзацем (:72-78).
   Не определены: stop и ack в shutting_down (в §4, :207-208, кода shutting_down для них нет); потеря готовности в
   stopping; мёртвый процесс никогда не пришлёт paused: true — ожидание идёт весь run_stop_timeout_s (10 с) и пишет «не
   подтвердил остановку» вместо настоящей причины «процесс не жив»; то же для ack в fault (1.7 п.4, :23: упавший процесс
   держит fault_stopping до таймаута). Исправить: добавить в таблицу §3.2 колонку ACK и принять правила: ack вне fault →
   no_fault (в shutting_down → shutting_down); stop в fault и stopping — no-op; потеря готовности в stopping состояние не
   меняет; для ожидания paused мёртвый или без отчёта процесс считается остановленным (причина «процесс не жив» остаётся);
   start в booting — not_ready. Предлагаемая полная матрица:
   - booting: start → not_ready; stop → no-op; ack → no_fault; apply → снова booting.
   - not_ready: start → not_ready + причины; stop → no-op; ack → no_fault; apply → booting.
   - ready: start → running; stop → no-op; ack → no_fault; apply → booting.
   - running: start → already_running; stop → stopping; ack → no_fault; apply → отказ running; потеря готовности → fault.
   - stopping: start → stopping; stop → no-op; ack → no_fault; apply → отказ stopping; по итогу → ready или not_ready.
   - fault: start → fault_unacknowledged; stop → no-op; ack → ok при fault_stop_done, иначе fault_stopping; apply → отказ
     fault_unacknowledged; готовность вернулась → остаёмся в fault.
   - shutting_down: всё, кроме status → отказ shutting_down.
   Автоперезапуск против fault: процесс с флагом вне окна run_restart_grace_s ведёт себя как без флага (→ fault).

4. PLAN/tasks/1.1.md:134-136; PLAN/tasks/1.7.md:16-19, :30-37; PLAN/tasks/1.8.md:18-21, :32-38 → слепой тестер не может
   написать RED: нет сигнатур. transition(state, event, *, ready: bool) из 1.1 не принимает «аварийная остановка
   завершена», а RED test_ack_before_stop_done_refused_fault_stopping без этого входа не написать. Для 1.8
   evaluate(expected, leaves, alive, now, stale_s) (1.3 п.1, :16-18) не принимает ни флага процесса, ни down_since, ни
   grace_s, ни «сдался». Исправить: в DESIGN 1.7 зафиксировать transition(state, event, *, ready: bool, stop_done: bool =
   False) либо класс-держатель с полем fault_stop_done; в DESIGN 1.8 — расширение evaluate: auto_restart: set[str],
   down_since: dict[str, float], grace_s: float, given_up: set[str], и кто хранит down_since (PM, по тику монитора).
   REDS 1.7 +3: test_stop_in_fault_noop, test_shutdown_from_fault_without_ack, test_ack_twice_second_refused_no_fault.

5. PLAN/tasks/1.8.md:6, :27-30 (FILES п.3 «путь — лид»); PLAN/design.md:244-245 → путь схемы процесса не решён, и он не
   один. Нашёл git grep-ом: поле процесса рецепта проходит через четыре места:
   - multiprocess_framework/modules/process_manager_module/topology/blueprint.py:133 (typed-поле restart_policy) и :287-290
     (as_generic_config);
   - multiprocess_framework/modules/process_module/configs/process_launch_config.py:67 (поле), :178 (pop), :226-227
     (верхний уровень proc_dict);
   - multiprocess_prototype/domain/entities/process.py:102 (domain Process, extra="forbid"; комментарий :32-41 обязывает
     синхронизацию, иначе поле теряется при GUI round-trip — класс AU-2; страж
     multiprocess_prototype/domain/tests/test_entities_roundtrip.py:374 TestExtrasShorthandDriftGuard);
   - монитор читает _process_configs[name] (process_monitor.py:1099-1124).
   Задача заявлена Layer: framework, а затрагивает multiprocess_prototype/domain. Исправить: вариант А — FILES 1.8 =
   blueprint.py, process_launch_config.py, domain/entities/process.py + тесты, Layer: framework + prototype/domain, RED на
   цепочку «YAML рецепта → domain Process → proc_dict → _process_configs[name]» (текущий
   test_flag_default_false_in_topology_dict проверяет только дефолт, а риск — потеря поля на границе слоёв). Вариант Б
   (передать в К7 как факт): флаг внутри уже существующего restart_policy (core/restart_policy.py:15, поле
   run_auto_restart) — один файл вместо четырёх: поле уже доходит до _process_configs[name]["restart_policy"]
   (process_monitor.py:1115); тогда п.6 DESIGN 1.8 («RestartPolicy не менять») меняется. Сейчас К7 (plan.md:147-148) цену не
   показывает, cto решает вслепую.

6. PLAN/tasks/1.8.md:18-21, :46 → FILES неполон для DESIGN. Шаг 2 требует знать, что «монитор запланировал или выполняет
   рестарт», шаг 3 — «сдался (gave_up)». Эти данные в мониторе приватны: _pending_restarts (process_monitor.py:131),
   _pending_recovery (:137), _given_up (:152). OUT OF SCOPE запрещает править process_monitor.py, а читать приватные поля
   из PM нельзя (граница модуля). Публичный путь есть: ProcessMonitor.get_supervision_snapshot() (process_monitor.py:1727-
   1746) отдаёт status, last_exit, restart_count; give-up виден как status == "failed" (:1286-1287). Исправить: DESIGN 1.8
   п.2-3: «окно считает PM (down_since процесса с флагом: нет свежего листа или не жив); give-up =
   get_supervision_snapshot()[name]["status"] == "failed"; правок process_monitor.py нет»; в FILES добавить строку «только
   чтение: monitor/process_monitor.py (get_supervision_snapshot)». Достаточность status проверять RED
   test_flagged_gave_up_goes_fault на настоящем снимке, не на моке.

7. PLAN/tasks/1.1.md:138-139; PLAN/tasks/1.7.md:20; PLAN/design.md:51-54;
   multiprocess_framework/modules/process_manager_module/README.md:512-532 → класс команды не определён. 1.1 называет
   start, stop, status классом R; design.md:51 — классом R только status; 1.4 п.1 (:16-17) гонит последовательность STOP
   через исполнитель жизненного цикла (класс L); 1.7 ставит ack «рядом» (R). В README все команды PM имеют класс (R, L, T,
   S) и исполнитель, новая команда без класса — дыра контракта. Машина состояний трогается из двух потоков (тик монитора
   считает готовность, message_processor принимает команды), design о синхронизации молчит; 1.3 TRAPS (:49) знает только
   дедлок. Исправить: в DESIGN 1.1 и 1.7 — класс каждой команды (status: R; start и ack: мгновенные, без ожиданий; stop:
   принять и передать L-исполнителю), строка в таблицу README (FILES 1.1/1.7 или 2.5); одно правило «все переходы под
   одним замком держателя состояния». REDS: hazard-тесты «ack одновременно с завершением аварийной остановки» и «start
   одновременно с потерей готовности» (project-rules §9).

8. PLAN/tasks/1.1.md:136-139 (шаг 2: «В initialize() до спавна детей — self._run_event = …») против
   multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:144, :176-190 → порядок
   создания. ProcessRegistry(...) строится в _create_components() (вызов из __init__, :144), а system_ready_event передаётся
   ему в конструкторе (:179). Если _run_event создать позже, в initialize() (:280), реестр получит None. Исправить: шаг 2 —
   создать событие в _create_components() до ProcessRegistry( (:176); параметр run_event в ProcessRegistry.__init__; в
   kwargs Process рядом с system_ready_event (core/process_registry.py:367-372); не класть в bundle custom (:305).

9. PLAN/design.md:191-192; PLAN/plan.md:128-129; PLAN/tasks/2.2.md:15-24 → у индикатора «нет диска» (В8) нет
   производителя. design.md и plan.md говорят «Task 2.2, 2.3 п.5»; в 2.2 нет ни шага, ни RED, ни файла плагина сцены или
   ленты, который ставит out_of_spec. 2.3 п.5 только показывает. Исправить: шаг 6 в 2.2 — какой плагин (имя и путь), при
   каком условии (нет диска, лента пустая) возвращает {"severity": "out_of_spec", "reason": "нет диска"} из readiness();
   RED test_no_disk_is_out_of_spec_not_failure; FILES +1. Если плагин не определён — записать в plan.md «индикатор В8 в 1.0
   без источника» и согласовать с владельцем.

10. Превью в ready (В2) оформлено наполовину. (i) PLAN/design.md:127-129 «Не работает: кадры источников» без оговорки
    противоречит :131 (превью при run_gated: false). (ii) Ни одна задача не ставит run_gated: false источнику камеры в
    рецепте прототипа (2.1 FILES, :22-25). (iii) Резка потока для обработки, записи и робота «по К6, здесь только источник»
    (PLAN/tasks/1.1.md:148-149) — задачи под результат К6 нет, а Task 0.1 отдаёт правку задач лиду (0.1.md:7); приёмку В2
    никто не проверяет: у 2.4 нет сценария «превью в ready: кадры у display > 0, у обработки, записи и робота = 0».
    (iv) Предпосылка варианта «на потребителе» (design.md:134-135, «плагин в PAUSED не получает process()») мной не
    подтверждена: grep PAUSED по process_module/plugins/*.py и generic/*.py показал только переходы состояния
    (plugins/base.py:94, :1629-1637), места пропуска process() не нашёл; это не доказательство отсутствия (см. «Что оставил
    открытым»), но cto без этого факта К6 не решит. Исправить: design.md:127-129 дописать «кроме источников с run_gated:
    false»; в 0.1 DESIGN добавить факт «что делает плагин в PAUSED с кадром» в список воспроизводимых; в plan.md записать
    «после К6 лид добавляет Task 1.9 (резка потока) и строку в 2.1 (run_gated: false у камеры)»; в 2.4 добавить сценарий
    превью.

11. PLAN/tasks/0.1.md:106-107 (FILES: «design.md — только чтение», «nothing else») против :97-104 и PLAN/plan.md:138-148 →
    вердикт cto невыполним по тексту. К1–К7 лежат в plan.md, а не в design.md; DESIGN требует прочитать standards.md,
    воспроизвести test_apply_topology.py:492, git grep _do_pause, source_producer.py:144-147, health/state.py:677 и дать
    вердикт «по новым задачам 1.7, 1.8» — все эти файлы вне FILES (правило «файл вне FILES → stop and ask» остановит cto
    до первого ответа). К7 опирается на прочтение В6 «(а)», которое владелец ещё не подтвердил (В9, plan.md:133-136).
    Поле Assignee: cto нарушает пункт (e) чек-листа плана и team-protocol §2 (cto — «tasks: never»). Исправить: FILES 0.1 =
    plan.md, design.md, standards.md, tasks/1.1.md, 1.2.md, 1.7.md, 1.8.md и «только чтение» перечисленные в DESIGN файлы
    кода; в DESIGN: «К7 отвечать при прочтении (а); при (б) задача 1.8 переписывается»; факты пунктов 5, 6 и 10 добавить в
    К6 и К7; Assignee: lead (зовёт cto как гейт S1-prime, он уже есть в plan.md:101), в бюджете оставить «cto (fable)».

12. PLAN/plan.md:63-64, :70-72; PLAN/design.md:3-4, :214-216; PLAN/tasks/1.1.md:139; PLAN/tasks/1.2.md:16, :33 → условия
    входа устарели, номера строк уехали, лейн-ноты неполны. plans/queue/ORDER.md:36-37: LSO 1.10 (809ba536a), 1.11
    (2ba2b5f1b) и C-60 (116ed6964) уже влиты, а план ждёт 1.10 и C-60 и ссылается на main 3aa2c0b8f. Дрейф проверен:
    _do_pause в плане :1602-1614, в коде plugins/base.py:1628-1640; system.shutdown в плане :573, в коде
    process_manager_process.py:585. Остаются реальные блокеры: C-55b (в main нет PreflightFinding: git grep = 0 строк) и
    gui-graceful-close (pre_stop.py не существует; цепочка 0.1 → 1.1 → 1.2, 1.3 → 1.4 не начата, ORDER.md:46).
    Лейны: Ф1 пишет в файлы полосы Ф (process_manager_process.py, process_registry.py, process_runner.py, plugins/base.py,
    generic/*) — план должен прямо сказать «код стартует после merge перечисленных и одним писателем PM»; 2.3 пишет в
    frontend/windows/main_window.py (полоса Д; frontend/app.py — один писатель, ORDER.md:280), 2.1 — в
    multiprocess_prototype/app.yaml и драйвер backend_ctl, без заметки о владельце. Plugins/hub/device_hub (полоса Р2):
    запись в 2.2 п.1 с заметкой «через координатора» есть (2.2.md:8, :44), но п.4 «плагин ленты (путь — лид)» скрывает
    вторую запись в тот же файл: отдельного плагина ПЧ в репозитории нет — Services/vfd_comm это протокол-библиотека
    (Services/STATUS.md:28), команды vfd_* обслуживает device_hub (Plugins/hub/device_hub/tests/
    test_spi_commands_acceptance.py:77). Исправить: (а) переписать «Вход Ф1»: влиты 1.10, 1.11, C-60; ждём C-55b (1.2,
    1.6) и gui-graceful-close 1.4 (1.4 и далее); (б) строка в «Порядок»: «код начинается после перечисленных merge; номера
    строк в design и tasks сверять по HEAD»; (в) заметки о полосе для 2.1 и 2.3 («Д/координатор: frontend/app.py и
    главное окно — один писатель»); (г) FILES 2.2 п.4: device_hub/plugin.py (тот же файл, что п.1, Р2 через координатора)
    либо назвать настоящий файл ленты.

13. PLAN/plan.md:76-94 → порядок на файле PM не назван. 1.4, 1.5, 1.6 все «после 1.3» и все пишут
    process_manager_process.py (1.7 и 1.8 ещё и run_state.py, test_run_state.py, test_run_commands.py). Параллельными план
    их не называет (пункт (c) чек-листа не нарушен), но и строгой цепочки не даёт. Критический путь: 1.4 ждёт пять задач
    gui-graceful-close, а с ней 1.7, 1.8, 2.3, 2.4. Исправить: в «Порядок выполнения» одна строка: «Ф1 строго
    последовательно, один писатель PM: 1.1 → 1.2 → 1.3 → 1.4 → 1.7 → 1.5 → 1.6 → 1.8» и строка про критический путь через
    gui-graceful-close.

14. PLAN/tasks/2.4.md:8, :15-20, :28; PLAN/tasks/2.5.md:16-19, :29 → хвост не догнал 1.7 и 1.8. 2.4 Dependencies (:8) =
    «1.4, 1.5, 1.6, 2.1, 2.2, 2.3», а plan.md:94 говорит «1.4–1.8»; сценарий (ж) «убить процесс → fault, авто-рестарт,
    ready, START за оператором» пропускает «Квитировать» и вариант с флагом; нет сценариев ack («готовность вернулась —
    всё ещё fault; START → fault_unacknowledged; ack → ready»), превью и «нет диска»; ACCEPTANCE «все 7 сценариев»; матрица
    инъекций (:19-20) не знает о квитировании (например, «вернуть автовыход из fault» должен покраснеть
    test_fault_stays_fault_when_readiness_returns). 2.5 ссылается на «SHA задач 1.1–1.6» и не вносит в ADR ack, флаг
    run_auto_restart, run_gated; для задач public-api-change (1.1, 1.2, 1.6, 1.7, 1.8) обязателен раздел Public API модуля —
    README PM перечисляет команды (README.md:13, :525-532), в FILES 2.5 его нет. Исправить: Dependencies 2.4 = 1.4–1.8,
    2.1–2.3; сценарии (ж) + ack + флаг + превью + «нет диска» (около 10), числа порогов для (а), (б), (ж); 2.5: «SHA задач
    1.1–1.8», DESIGN п.1-2 дополнить, FILES +process_manager_module/README.md и process_module/README.md (Public API).

15. PLAN/standards.md:71 → остаток старой модели. «у нас last_fault гасится нажатием START — подтверждение действием»
    противоречит В4 и design.md:75-76 (ack ставит acknowledged_at, last_fault виден до следующего START). Строка ещё и
    склеена («Берём только … Берём:»). design.md:18 («раздел §9») ссылается в никуда после выноса. Исправить: «Берём
    Unacknowledged → Acknowledged: авария подтверждается отдельной командой system.run.ack (В4); START её не
    подтверждает»; design.md:18 → «standards.md §9».

16. PLAN/plan.md:50-59, :102; .claude/CLAUDE.md:56 → бюджет (пункт (g)). Сумма строк таблицы 0,2 + 3 раза (0,7–0,9) +
    3 раза (0,4–0,6) + 2 раза (0,4–0,6) + 3 раза (0,3–0,5) + 0,3 + 0,15 = 5,65–7,85M, а итог записан «~7–8,5M»; нет расчёта
    «участники умножить на ~56k стартового контекста плюс работа». Строки 1.1–1.6 и гейт plan.md:102 назначают ревью opus,
    строки 1.7 и 1.8 — sonnet; правило проекта (.claude/CLAUDE.md:56): Opus только на ревью ветки перед merge и вердикты
    по живым дефектам, постадийное ревью (IPC, жизненный цикл) — sonnet. Число «Opus ~16 запусков» из таблицы не
    выводится. Исправить: пересчитать итог по строкам и добавить строку «56k на участника»; привести ревьюеров к правилу
    (или записать исключение с причиной); обновить «Opus ~N».

17. PLAN/tasks/1.5.md:8, :35; PLAN/tasks/1.6.md:8; PLAN/plan.md:35; PLAN/design.md:162-168; plans/queue/ORDER.md:47;
    plans/queue/decisions.md:37 → закрытые вопросы остались условными, счётчики не обновлены. 1.5: «ответ владельца В7»
    и «если В7 = авто — задача переписывается» (В7 закрыт: «сначала ОСТАНОВИТЬ»); 1.6 «ответ владельца В5» (закрыт).
    plan.md:35 («процесс … перезапускается без аварии (1.8)») подаёт прочтение (а) как решённое, пока В9 открыт.
    ORDER.md:47 «12 задач», decisions.md:37 «вопросы CTO К1–К5» (теперь 14 задач и К1–К7) — обратные ссылки ставит лид
    (plan.md:105), не план. Исправить: заменить условные формулировки на «В7 и В5 закрыты 2026-11-02»; в plan.md:35
    дописать «(прочтение — В9)»; лиду обновить ORDER.md:47 и decisions.md:37.

18. PLAN/design.md:220-229 (§6 Риски); PLAN/tasks/1.7.md:23; PLAN/tasks/1.8.md:18-19, :48-49 → новые риски 1.7 и 1.8 не
    названы (пункт (h)). Нужны механизмы: (а) окно run_restart_grace_s 30 с против подъёма тяжёлого процесса
    (ml_inference грузит модель в фоне, design.md:228-229): здоровый рестарт может уйти в fault; (б) процесс робота с
    флагом встаёт в работу сам (1.8 TRAPS :48-49 говорит «не ставить», а 2.1 об этом молчит) — в 2.1 нужна строка «флаг
    run_auto_restart в рецепте 1.0 не ставится у процессов с device_hub»;
    (в) ack ждёт до run_stop_timeout_s (10 с) из-за мёртвого процесса (см. п.3); (г) кнопка «Квитировать» активна только в
    состоянии fault (design.md:206), а команда в первые 10 с отвечает отказом fault_stopping, поэтому в контракт §4 нужно
    поле ack_allowed рядом с start_allowed и RED в 2.3.

## Проверка 1: В1–В8 отражены согласованно (кроме перечисленного)

| Ответ | plan.md | design.md | задачи | остатки |
|---|---|---|---|---|
| В1 | :118 | :68-70 | 1.1 п.2 | нет |
| В2 | :119-120 | :131-136 | 1.1 п.6, 1.2 п.4 | п.10: design.md:127-129, нет задачи под К6, нет 2.1/2.4 |
| В3 | :121 | :156 | 1.4 п.4, 2.2 п.1 | нет |
| В4 | :122-123 | :72-78, :206-208 | 1.7, 2.3 п.4 | п.1, п.4, п.15; 2.4 |
| В5 | :124 | :107-111 | 1.6 | п.17 (условная формулировка) |
| В6 | :125-126 | :159-168 | 1.8 | п.5, п.6, п.17; В9 открыт |
| В7 | :127 | :181-187 | 1.5 | п.2, п.17 |
| В8 | :128-129 | :189-192 | 2.3 п.5 | п.9: производителя нет |

Подстроки из запроса. «Выход из fault сам» остался в 1.3.md:21-23 и 1.7.md:47 (заявлен временным, п.1), в 1.4.md:19-22
неявно (не заявлен) и в standards.md:71 (старая модель «START подтверждает»). «Превью нет в 1.0» не найдено (design.md:233-234
«превью … в 1.0 по решению владельца» верно). «Отдельное квитирование вне scope» не найдено (plan.md:48 и 1.7 OUT OF SCOPE
исключают только кнопки GUI и пульта и per-alarm квитирование — верно).

## Проверка 2: задачи 1.7 и 1.8

Формат совпадает с остальными: шапка, TASK/ROLE/CHAIN/DESIGN/FILES/REDS/ACCEPTANCE/TESTS/OUT OF SCOPE/TRAPS/HANDOFF IN
на месте, REDS не больше 10. Зависимости верны: 1.7 после 1.4, 1.8 после 1.3 и 1.7; временный автовыход 1.3 заменяется 1.7
(лучше убрать совсем, п.1). Не принято: п.4-6 (сигнатуры, FILES 1.8, чтение состояния рестарта), п.7 (классы команд) и FILES 1.8
п.3 «путь — лид» (нерешённая строка FILES противоречит форме брифа). Ревьюер 1.7 и 1.8 sonnet соответствует правилу
.claude/CLAUDE.md:56 и противоречит plan.md:102.

## Проверка 3: чек-лист MODE: plan (a–h)

(a) ACCEPTANCE с командами или литералами: да для 1.x; у 2.4 сценарии (а), (б), (ж) без порогов — п.14. (b) [VERTICAL SLICE]
на 1.1: да. (c) Параллельные задачи с пересекающимися Files: таких в плане нет, но порядок не зафиксирован — п.13.
(d) Module contract, Handoff, Gate, Dependencies заполнены у всех; Dependencies 2.4 неполны — п.14. (e) Level приемлем;
cto в Assignee Task 0.1 — нарушение, п.11. (f) Out of scope непустой и не равен Goal: да. (g) цифра есть, но не сходится и без
расчёта «участники на 56k» — п.16. (h) риски есть в design §6 с механизмами, новых нет — п.18.

## Что оставил открытым / ненадёжно

- Ничего не запускал (режим план-ревью): ни тесты из REDS, ни стенд; утверждения о коде — чтение и git grep в worktree (HEAD
  3f5aa9c4e). Свежесть индекса qex не проверял (только git grep).
- П.10 (iv), «плагин в PAUSED не получает process()»: не подтверждён и не опровергнут. Я искал PAUSED только в
  process_module/plugins/*.py и process_module/generic/*.py; вызов process() через plugin_runner (его модуль я не открывал)
  мог проверять состояние там, где мой grep не смотрел. Настоящее доказательство — тест: плагин в PAUSED, кадр на вход,
  счётчик process().
- П.5-6: вывод «get_supervision_snapshot() достаточен для give-up и рестарта» следует из чтения process_monitor.py:1286-1287 и
  :1727-1746; живого прогона нет, достаточность status в момент «рестарт запланирован, процесс ещё не поднят» не доказана
  (поэтому RED на настоящем снимке).
- Наследование run_event при рестарте (1.8 п.5, design.md:124) проверено по аналогии: ProcessRegistry.create_process кладёт
  system_ready_event в kwargs каждого спавна (core/process_registry.py:367-372); что restart_process
  (process_manager_process.py:3900) идёт через ту же create_process, я не прочитал.
- Лейны: владельцев generic_process.py, source_producer.py, plugin_orchestrator.py по списку полос не нашёл (проверил ORDER.md
  по строкам 32-47 и 280, не весь файл и не plans/lifecycle-stop-ownership.md); утверждение «файлы полосы Ф» взято из
  design.md:214-216. Содержимое gui-graceful-close, C-55b (бриф 101d49607) и pult-control-panel не читал.
- Не проверил: есть ли место под кнопки в frontend/windows/main_window.py; проверяется ли тестом перечень классов команд PM
  (README:512-532) на «команда без класса»; номера строк, не названные выше (design.md §2, остальные задачи), сверены
  выборочно: три совпали (source_producer.py:144-147, health/state.py:677, base.py:1540), два уехали (_do_pause, system.shutdown).
- Расчёт бюджета (п.16) — моя арифметика по строкам таблицы; «Opus ~16» по запускам не пересчитывал.
- В1–В8 не пересматривал (по условию). В9 (прочтение В6) — вопрос владельцу; мой совет совпадает с рекомендацией лида (а),
  но держится на допущении, что для оператора «линия не стоит» важнее «робот без оператора» — решает владелец.

---

# Раунд 2 (итерация 2 из 2) — сверка правок e7f083c4c

Сверка: git diff 3f5aa9c4e e7f083c4c и чтение текущих файлов (HEAD e7f083c4c). Код не запускал. PLAN = plans/2026-10-27_system-run-state.

## Вердикт раунда 2: CHANGES REQUESTED (остаток — 5 пунктов, это эскалация на уровень выше по правилу двух итераций)

Из 18 пунктов раунда 1: закрыто 14, закрыто с новым дефектом 4 (пп. 3, 4, 5, 9), не закрытых нет. Новые дефекты мелкие по объёму, но
два из них (R2-1, R2-2) меняют поведение в сторону безопасности и тестируемости, поэтому APPROVED пока не даю. Остаток — только то, что
ниже (R2-1 … R2-5); исправление каждого — правка текста плана на 1-5 строк.

## Остаток (файл:строка → что не так → как исправить)

R2-1. PLAN/design.md:70-72 (правило 3), PLAN/tasks/1.4.md:21-22 (п.3), PLAN/design.md:244-245 (риск) → правка п.3 раунда 1 ввела новое
   противоречие и дыру безопасности. Правило 3 и 1.4 п.3 считают остановленным не только мёртвый процесс, но и «процесс без
   свежего отчёта». Зависший, но живой процесс (устаревший лист, процесс жив, робот может ещё двигаться) тем самым засчитан
   остановленным, fault_stop_done взводится сразу, ack разрешён, следующий START даёт фронт run_event процессу, который так и не
   подтвердил paused. Тот же случай — инъекция из ACCEPTANCE 1.3 (заморозка heartbeat): замороженный процесс по правилу 3 «остановлен».
   Риск в design.md:244-245 говорит обратное («ack ждёт … если процесс завис»). Исправить: правило 3 и 1.4 п.3 — «остановленным
   считается только процесс, который PM признаёт не живым (alive == False); процесс жив, но без свежего отчёта, ждёт paused до
   run_stop_timeout_s»; по истечении срока для аварии — fault_stop_done = True, а причина «<процесс> не подтвердил остановку»
   дописывается в last_fault.reasons (для STOP оператора она уже есть в 1.4 п.3); RED в 1.4 test_stale_alive_process_not_counted_stopped;
   в design.md:244-245 одной формулой: «мёртвый — не ждём, завис — ждём срок».

R2-2. PLAN/tasks/1.8.md:23-26 (сигнатура evaluate) → сигнатура достаточна для слепого тестера по входам, но не по семантике, и из-за
   этого есть дефект поведения. (а) evaluate не знает состояния машины: процесс с флагом, упавший в ready или not_ready, получает
   причину out_of_spec «перезапуск» без failure, значит ready = True и start_allowed = true при мёртвом процессе; START переведёт
   систему в running без процесса. В design.md:170-173 и в 1.8 флаг действует только «в running». (б) не определено поведение при
   name not in down_since (первый тик после падения): KeyError или «окно только что началось». (в) нет текста причины failure по
   истечении окна и по given_up. Исправить: добавить параметр running: bool (или передавать auto_restart пустым вне running; решение
   записать в DESIGN 1.8 п.2), «нет в down_since — окно началось сейчас»; формулировки причин: failure, source: liveness,
   «перезапуск <процесс> не завершён за <N> с» и «<процесс>: супервизор сдался». RED +1:
   test_flagged_down_in_ready_is_failure_not_restart_indicator.

R2-3. PLAN/tasks/1.1.md:17-20 (список event) → сигнатура transition(state, event, *, ready, stop_done=False) принята, но перечень событий
   start|stop|ack|fault|apply|shutdown не содержит событий, которыми матрица design.md:60-66, 1.3 п.3 («после барьера → ready/not_ready по
   evaluate») и 1.4 п.3 («итог STOP → ready/not_ready») переводят booting в ready или not_ready, ready в not_ready и обратно, stopping в
   ready или not_ready. Слепой тестер не напишет RED на эти переходы на уровне чистой функции. Исправить: добавить событие settled
   (барьер или итог STOP завершён) и tick (обновление готовности; ready: bool = результат evaluate), записать правило «событие без смысла
   в состоянии = (то же состояние, None), отказ = (то же состояние, код)». Одна строка в 1.1 п.1 и три теста в 1.3/1.4.

R2-4. PLAN/tasks/1.8.md:16-22 (вариант Б) → вариант Б подтверждён как дешёвый (см. «Проверка варианта Б»), но в тексте не указана ловушка,
   которая делает его небезопасным по умолчанию. ProcessMonitor._resolve_policy (process_monitor.py:1099-1124) заменяет глобальную политику
   любым непустым словарём restart_policy процесса, а класс-умолчание RestartPolicy.enabled = False (core/restart_policy.py, поле enabled).
   Рецепт restart_policy: {run_auto_restart: true} без enabled: true даёт процесс, который супервизор НЕ поднимает (глобальное
   enabled=True перекрыто): после падения он не вернётся, окно истечёт, система уйдёт в fault; флаг молча ничего не делает. RED
   test_flag_default_false_reaches_process_configs этого не ловит. Исправить: в DESIGN 1.8 п.1 — «флаг читается PM из
   _process_configs[name]["restart_policy"] как сырой словарь; флаг без enabled: true в том же словаре считается неработающим: PM пишет
   WARNING при boot и обращается с процессом как без флага»; RED test_flag_without_enabled_treated_as_unflagged; в 2.1 п.4 — форма
   рецепта {enabled: true, run_auto_restart: true}.

R2-5. PLAN/tasks/2.2.md:26-29 (шаг 6) и PLAN/design.md:200-201 → word_layout как источник «нет диска» подтверждён частично: подходящего
   состояния в плагине нет, шаг 6 описывает его как существующее. Факт: Plugins/processing/word_layout/plugin.py:479-484 — комментарий
   «Пауза (нет диска/слабый) → взвестись, ждать следующий диск», затем if pred is None: self._armed = True внутри _should_take (:439).
   Это (i) покадровый признак «нет уверенного предсказания», который смешивает «нет диска» со «слабый»; (ii) ветка только режима без
   track_id и без триггера: в id-режиме (:460-474) при pred is None _armed не трогается, в триггер-режиме (:450) такой ветки нет;
   (iii) _armed не «пауза»: он True и до первого диска, и между двумя дисками (нормальный зазор потока), поэтому индикатор по нему мигал бы
   на каждом зазоре. Метода readiness() в плагине нет (git grep readiness по файлу = 0). Исправить: в шаге 6 написать, что состояние
   добавляется: self._no_disk_since (monotonic) ставится при первом pred is None и сбрасывается при pred is not None во всех трёх
   режимах; readiness() возвращает out_of_spec «нет диска», когда now - _no_disk_since >= no_disk_indicator_s (ключ конфига плагина,
   умолчание, например, 2.0 с); режим по триггеру без кадров состояния не даёт, и это сказать прямо. RED 2.2
   test_no_disk_is_out_of_spec_not_failure дополнить test_gap_between_discs_below_threshold_is_ready.

(мелкое, можно вписать вместе с R2-1 ... R2-5)
- PLAN/design.md:214-216 → после правки в §4 остался старый хвост: строка 216 по-прежнему говорит «Квитировать» активна, когда
  state == "fault", и конфликтует с ack_allowed строки 214; в JSON-примере (:208-211) нет поля ack_allowed. Удалить хвост строки 216,
  добавить поле в пример.
- PLAN/tasks/1.5.md:8 и PLAN/plan.md (порядок): 1.5 стоит после 1.7, а 1.3 п.3 («Boot/apply → booting») оставляет apply без отказа в
  running и fault на точках merge 1.3, 1.4, 1.7. Для ветки с run_gate: false по умолчанию это допустимо, но 2.1 зависит только от 1.3 и
  может включить run_gate: true раньше 1.5. Либо 1.5 сразу после 1.3 (ветку stopping добавить строкой в 1.4), либо в Dependencies 2.1
  дописать «после 1.5».
- PLAN/tasks/1.4.md:20-21 → причина «не подтвердил остановку» после STOP не имеет правила снятия (ack в not_ready даёт no_fault, START в
  not_ready отказан): если процесс пришлёт paused: true на 12-й секунде, причина должна уйти сама. Дописать «причина снимается, когда лист
  процесса снова показывает paused: true».
- PLAN/design.md:224 (§5, строка 1) → «Ф1 после merge 1.10 и C-60» устарело (оба влиты); привести к plan.md.

## Пункт за пунктом (раунд 1 -> раунд 2)

| П. | Статус | Основание |
|---|---|---|
| 1 | закрыт | design.md:64, :68-69; 1.3 п.3 (:21-24) fault липкий; 1.4 п.4 (:23-24) fault_stop_done; 1.7 п.1 только ack; TRAPS 1.7 без «выхода сам» |
| 2 | закрыт | design.md:191-196 и 1.5 п.1 (:16-18), REDS для stopping и fault (:29-30), ACCEPTANCE для fault |
| 3 | закрыт с новым дефектом | матрица design.md:58-66 полная по start/stop/ack/apply (R2-1: правило 3) |
| 4 | закрыт с новым дефектом | transition в 1.1:17 и 1.7:16, evaluate в 1.8:23 (R2-2, R2-3) |
| 5 | закрыт с новым дефектом | вариант Б выбран, цена показана в 1.8:16-22 (R2-4: ловушка enabled) |
| 6 | закрыт | 1.8 п.3 (:27-29) get_supervision_snapshot, FILES п.4 только чтение (:40) |
| 7 | закрыт | 1.1 п.2 (:24-27) классы и замок, design.md:72-74 правила 4-5, hazard RED 1.1:59 и 1.7:41; строка README в 2.5 п.4 (:21-22, :28) |
| 8 | закрыт | 1.1 п.2 (:21-23) создание в _create_components() до ProcessRegistry; п.3 (:30-31) в kwargs рядом с system_ready_event |
| 9 | закрыт с новым дефектом | шаг 6 и FILES п.4 в 2.2 (:26-35) есть; источник подтверждён частично (R2-5) |
| 10 | закрыт | design.md:137; plan.md «Task 1.9 после К6»; 2.1 п.5 (:22); 2.4 сценарий (и); предпосылка К6 честно помечена непроверенной (design.md:248) |
| 11 | закрыт | 0.1: Assignee «lead (зовёт cto как гейт; вердикт — cto)», FILES (:28-33) включает plan.md, standards.md, tasks 1.1/1.2/1.7/1.8 и код только на чтение, Dependencies «ревью плана APPROVED». DESIGN 0.1 целиком не перечитывал |
| 12 | закрыт | plan.md «Вход Ф1» и «Заметки о владельцах»; 2.2 п.4 (:22-24) «второго файла нет». Ссылки на C-64/C-79 и Д 1.10 в plan.md с ORDER.md не сверены |
| 13 | закрыт | порядок 1.1, 1.2, 1.3, 1.4, 1.7, 1.5, 1.6, 1.8 не нарушает ни одной Dependencies: 1.2 <- 1.1; 1.3 <- 1.2; 1.4 <- 1.3 и gui-graceful-close; 1.7 <- 1.4; 1.5 <- 1.3; 1.6 <- 1.3 и C-55b; 1.8 <- 1.3, 1.7 |
| 14 | закрыт | 2.4 Dependencies 1.4-1.8 (:8), сценарии (а)-(л) с ack, флагом, превью, «нет диска» (:16-26); 2.5 SHA 1.1-1.8, README в FILES п.4 |
| 15 | закрыт | standards.md:70-72 («START её не подтверждает»); design.md:18 ссылается на standards.md |
| 16 | закрыт | plan.md: строка стартового контекста ~32 x 56k = ~1,8M, итог 7,9-10,0M = 5,65-7,85 + 1,8 + 0,4 (арифметика сходится), ревьюеры sonnet по .claude/CLAUDE.md:56, Opus ~8 запусков перечислены |
| 17 | закрыт | 1.5:8 и :38, plan.md «В7 и В5 закрыты», plan.md:35 «прочтение — В9, ждёт владельца». ORDER.md:47 и decisions.md:37 за лидом, мной не проверялись |
| 18 | закрыт | design.md:240-248 (риски с механизмами), ack_allowed в 1.7:24 и 2.3:21, RED 2.3:35, 2.1:21 |

## Ответы на особое внимание координатора

(1) Матрица design.md §3.2 (:58-66). Пары состояние x {start, stop, ack, apply} определены все 28; shutdown — из любого состояния
(design.md:177-178), потеря готовности — правила 1-2. Не определено лишь третьестепенное: потеря и возврат готовности в shutting_down
(игнорируется по смыслу, не записано) и shutdown в stopping. Точки merge: после 1.3 fault липкий, выход только shutdown (1.3:22-24);
после 1.4 добавлен fault_stop_done без ack — состояние валидно (терминал до shutdown); после 1.7 появляется ack — валидно. Дыра в
другом: пока не влит 1.5, apply в running и fault не отказывает (1.3 п.3 «Boot/apply -> booting»), то есть на merge-точках 1.3, 1.4, 1.7
столбец apply матрицы не выполняется (см. «мелкое»). Остальное — R2-1 и R2-3.

(4) Сигнатуры. transition(..., stop_done) достаточна для ack-тестов 1.7; для переходов без команд нет событий (R2-3). evaluate(...,
auto_restart, down_since, grace_s, given_up) достаточна по входам, но не по семантике (R2-2).

(5) Вариант Б проверен чтением (запуска нет). Цепочка: рецепт restart_policy: {...} -> domain Process.restart_policy: dict[str, Any]
(multiprocess_prototype/domain/entities/process.py:102; extra="forbid" действует на ключи верхнего уровня Process, не на содержимое
словаря) -> framework ProcessConfig.restart_policy: dict[str, Any] (topology/blueprint.py:133, :289-290) -> ProcessLaunchConfig.restart_policy
(process_module/configs/process_launch_config.py:67, :178, :226-227) -> proc_dict["restart_policy"] -> _process_configs[name] (читает
_resolve_policy, process_monitor.py:1115). Ни на одном звене нет фильтра ключей, новый ключ проходит без правки схем. SchemaBase
(data_schema_module/core/schema_base.py, model_config около :56-60) не задаёт extra, значит RestartPolicy(**{..., "run_auto_restart": True})
без объявленного поля лишний ключ молча отбросит (умолчание pydantic), с полем — примет. Вариант Б действительно дешёвый (один файл и
тесты) при условии R2-4.

(9) word_layout как производитель «нет диска»: частично (R2-5). Строка :479 — комментарий внутри _should_take, а не состояние.

(11) Task 0.1: закрыт (FILES, Assignee, Dependencies).

(13) Порядок: зависимости не нарушены (таблица, п.13).

## Проверка варианта Б — коротко

Дёшево, если: (а) PM читает флаг как сырой словарь _process_configs[name]["restart_policy"]; (б) рецепт пишет enabled: true вместе с
флагом (R2-4); (в) поле run_auto_restart объявлено в RestartPolicy для документирования и валидации (для работы не обязательно, так как
лишний ключ отбрасывается).

## Что оставил открытым / ненадёжно (раунд 2)

- Ничего не запускал: ни тесты, ни стенд. Выводы по варианту Б и по word_layout — чтение; цепочка рецепт -> _process_configs[name] не
  проверена сквозным прогоном. Настоящее доказательство: RED на цепочку «YAML рецепта -> domain Process -> proc_dict ->
  _process_configs[name]["restart_policy"]["run_auto_restart"]» (в 1.8 REDS он назван test_flag_default_false_reaches_process_configs,
  но не написан).
- SchemaBase: вывод «extra не задан, pydantic игнорирует лишний ключ» взят из того, что в model_config (schema_base.py около :56-60) нет
  ключа extra; возможную настройку в SchemaMixin или по цепочке наследования не проверял.
- Не перечитывал DESIGN задачи 0.1 (список фактов К6/К7), только FILES, Assignee, Dependencies; не перечитывал полностью 1.2, 1.6, 2.1,
  2.3, 2.5 — смотрел только строки, закрывающие пункты раунда 1 (grep и фрагменты).
- Ссылки в plan.md на C-64/C-79 и «Д 1.10» не сверял с plans/queue/ORDER.md; ORDER.md:47 («12 задач») и decisions.md:37 («К1-К5») после
  коммита не открывал (по плану их обновляет лид).
- Замечание про apply на merge-точках 1.3-1.7 — оценка риска (ветка с run_gate: false по умолчанию, 2.1 зависит от 1.3); кто и когда
  включает run_gate: true в общей ветке, я не знаю.
- Семантику word_layout (три режима) читал по фрагментам :439-500, не весь файл: возможно, pred is None где-то выше (в process())
  дополнительно сводится в иной индикатор; git grep readiness по файлу = 0.
- Оценку «закрыто» по п.16 даю по арифметике таблицы (5,65 + 1,8 + 0,4 = 7,85, верхняя граница 10,05); число участников ~32 не пересчитывал.
