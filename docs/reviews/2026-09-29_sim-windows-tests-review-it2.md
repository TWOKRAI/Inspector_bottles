VERDICT: APPROVE_WITH_NITS

# Ревью, итерация 2: fix/sim-windows-tests (reviewer, 2026-09-29)

HEAD 94c4163f, коммиты раунда 4: 0f735a20, 919e33ca, efd802a8, 7dc90228. Обе находки итерации 1 закрыты, ниты 3–5 тоже. Блокирующих находок нет.

## Слияние
- git merge-tree --write-tree main(d2216c8b) HEAD: exit 0, конфликтов нет.

## Прогоны (Windows 10, py3.12, QT_QPA_PLATFORM/QT_QPA_FONTDIR сняты)
- Plugins/sim Services/line_sim Services/robot_comm: 4 failed / 1397 passed / 8 skipped / 2 xpassed за 170 с. Упали 3 pult_web — известное семейство (test_truth_routes_forbidden_host_403, test_preset_commit_content_type_guard_still_applies, test_foreign_host_header_rejected_403_on_get_and_post) — и test_drop_refuses_then_recovers, см. «Новый флик». Прогон debugger — 1401 passed, 0 failed; значит, эти 4 плавающие.
- test_jog_deadline_clock + test_watchdog_holds_lock: 5 из 5 прогонов зелёные. test_sim_robot_delay_floor: 5 из 5 зелёные.

## Мои инъекции (предсказание записано до прогона; плагины pytest, дерево не трогал)
- Находка 1 (якорь монитора). INJ-M: якорь жёстко на time.perf_counter — часы верные по умолчанию, но не часы журнала. Предсказание: red только test_monitor_time_is_anchored_on_the_journal_clock. Факт: ровно он, 1 failed / 5 passed. Тест закрепляет «часы журнала», а не «perf_counter».
- Находка 2 (предусловие TIME_WAIT). INJ-T: помощник закрывает accepted-сокет через RST (SO_LINGER 0), TIME_WAIT на порту нет. Предсказание: red только предусловие, AC1 зелёный. Факт: ровно так, 1 failed / 3 passed. AC1 без TIME_WAIT проходит впустую, и теперь это ловит предусловие.
- Пункт 4 (дедлайн jog). INJ-J: дедлайн ставится на perf_counter, а проверяется на time.monotonic (рассинхрон часов; сдвиг на этой машине 0.030 с). Предсказание: red test_jog_deadline_clock и test_watchdog_holds_lock_across_mailbox_read_and_stop, остальное зелёное. Факт: ровно эти 2, 86 passed.
- Нит 3 повторно. INJ-B (дедлайн добора на monotonic) теперь даёт red в 8 из 8 прогонов; было 5 из 6.

## Допуск 15 мс в тесте монитора
- Замер: 300 свежих окон со случайной фазой — ошибка «показано − сейчас» от −1.51 до −0.03 мс. Окно, прожившее 2 с, 200 замеров — от −1.27 до −0.20 мс. Источник ошибки — усечение до мс в штампе. Запас около 10 раз.
- Остаточный риск флика (нит A): тест упадёт, если между journal.on_event и datetime.now() в помощнике поток простоит дольше 13 мс. Квант планировщика Windows — 15.6 мс, так что под полной нагрузкой такое возможно, но окно — доли миллисекунды. Надёжнее взять now до и после и требовать before − 2 мс <= shown <= after; тогда допуск не зависит от нагрузки.
- На Linux/macOS perf_counter совпадает с monotonic, поэтому второй тест там откат якоря не различит. Свойство детерминированно держит первый тест (сдвиг часов журнала на +5000 с).

## Новый флик (не от ветки, отдельной задачей)
test_acceptance_5_4_faults.py::test_drop_refuses_then_recovers: 1 падение в полном прогоне; отдельно 0 из 12. Вход: fault.drop{seconds:3}, сразу за ним _try_connect → коннект прошёл. Механизм (по коду): cmd_fault_drop (plugin.py:902–933) возвращается сразу, а слушателя закрывает поток _run_drop. Тест делает ОДИН немедленный коннект (строка 196), хотя докстринг обещает «отказан за <=1 с». Под нагрузкой коннект успевает раньше stop_listener. Ветка не меняла ни этот тест, ни путь fault.drop и stop_listener. На базе не воспроизводил — в изоляции флик не проявляется ни там, ни тут. Лечение: опрашивать отказ до 1 с, а не проверять один раз.

## Ниты (не блокируют)
- A: брекетинг времени в test_monitor_time_matches_wall_clock_with_default_journal_clock (см. выше).
- B: test_jog_deadline_clock импортирует _make_bare_plugin из соседнего тестового модуля. Работает, но хелпер уместнее держать в conftest.

## Что оставил открытым / ненадёжно
- Флик drop описан по коду и одному наблюдению; что он есть и на main, не доказано.
- Всё мерено на одной машине (Windows 10, py3.12). На Linux/Orin ветку не гонял.
- Допуск 15 мс проверен в простое, без параллельной нагрузки на CPU. Оценка риска под нагрузкой — рассуждение, не замер.
