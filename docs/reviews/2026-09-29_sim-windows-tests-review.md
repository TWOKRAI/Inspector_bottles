# Ревью: падающие тесты на main — fix/sim-windows-tests и fix/pm-gone-reader-mark (reviewer, 2026-09-29)

**Вердикт:** A fix/sim-windows-tests (3496e98f) — **REQUEST_CHANGES** (итерация 1 из 2, две небольшие правки). B fix/pm-gone-reader-mark (ffc37efc) — **APPROVE_WITH_NITS**.

qex не использовался (Ollama выключен), поиск шёл через Grep/Read. Все прогоны на Windows 10, CPython 3.12.12, pymodbus 3.13.0 (зафиксирован в uv.lock), QT_QPA_PLATFORM/QT_QPA_FONTDIR сняты.

## Слияние
- git merge-tree --write-tree: main+A exit 0; main+B exit 0; B+A (= main + обе ветки) exit 0. docs/sessions/*.md сливается как merge=union. main = 97bdcf9b.

## A — прогоны
- pytest Plugins/sim Services/line_sim Services/robot_comm: **1 failed, 1397 passed, 8 skipped, 2 xpassed** за 162 с; упал только pult_web/test_acceptance_5_3a.py::test_negative_content_length_is_400... (известный флик). В diff нет добавленных skip/xfail/rerun (единственный skipif — «pymodbus не установлен», а он установлен).
- Инъекции (плагины pytest в scratchpad, дерево не трогал; прогон Plugins/sim/robot_host Services/robot_comm):
  - INJ-A: убран override init_setup_connect_listen (имитирует переименование хука в pymodbus, то есть тихий откат на reuse_address=True). Предсказание: 1 red, test_start_listener_raises_when_port_taken_by_foreign. Факт: ровно он, 1 failed / 922 passed.
  - INJ-C: свой сокет, но SO_REUSEADDR вместо SO_EXCLUSIVEADDRUSE. Предсказание: тот же 1 red. Факт: он же (3 из 3 прогонов); второй red в первом прогоне — флик, см. ниже.
  - INJ-B: дедлайн _sleep_at_least на time.monotonic вместо perf_counter. Предсказание: 1 red, test_binder_delay_is_never_shorter... Факт: red в 5 из 6 прогонов (1–4 коротких замера из 80) — см. нит 3.
- Апгрейд pymodbus: если хук или call_create переименуют, откат тихий в продукте, но громкий в тестах (INJ-A). Если пропадёт loop/handle_new_connection — AttributeError при каждом старте, красные все тесты слушателя. На POSIX подкласс не используется.
- SO_EXCLUSIVEADDRUSE, матрица на этой машине: свежий bind поверх живого слушателя отбивается во всех сочетаниях, кроме reuse+reuse. Простой bind (без флагов) отбился бы так же, так что эксклюзивность лишняя, но не вредит. Повторный bind при хвосте прежнего соединения (server TIME_WAIT, client TIME_WAIT, FIN_WAIT_2, незакрытый accepted-сокет) проходит у excl/plain/reuse во всех случаях: регрессии рестарта fault.drop нет.
- _sleep_at_least: добор — 0 итераций в простаивающем цикле, в среднем 0.9–1.05 (максимум 2) при тикере в 1 мс. Цикл не крутится вхолостую: CPU/wall около 0. Перебор над заказанным до 17.7 мс. Отмена на 10 мс (первый sleep) и на 49 мс (добор) даёт CancelledError за 0.03–0.04 мс. Верхняя граница 0.55 в целевом тесте запас выдерживает.
- Conftest, общий для процесса: зонд после сбора test_image_panel.py + test_codegen_v2.py показал offscreen и каталог Temp/qt_fonts_*. Утечка настоящая. testpaths по умолчанию содержат multiprocess_prototype/frontend и Services, поэтому весь фронт в дефолтном гейте на Windows идёт на offscreen с одним DejaVuSans. Замер: multiprocess_prototype/frontend отдельно — 20 failed / 2460 passed; вместе с conftest robot_comm — тот же набор 20 упавших (diff пуст). 6 пиксельных/размерных файлов фронта с robot_comm в обоих порядках — 939 passed. Каталоги qt_fonts_* после прогонов: 0.

## A — находки
1. [Services/robot_comm/server/sim_monitor.py:64,146] [quality, побочный эффект продуктовой правки] Ветка перевела часы SimJournal по умолчанию на perf_counter (sim_journal.py:176), а SimMonitorWindow по-прежнему переводит отметки журнала в настенное время через якорь self._t0_mono = time.monotonic(). Вход: SimJournal() + SimMonitorWindow(journal), 20 событий on_event. Наблюдение: показанное время минус time.time() = +28.5…+28.7 мс, систематически (аптайм 5.8 ч, perf_counter минус monotonic = 0.0286 с). На main было ±15.6 мс квантования без сдвига. Величина зависит от машины. Исправление: якорь на тех же часах, что у журнала. Лучше всего брать часы у самого журнала (публичный clock у SimJournal), чтобы они не разошлись снова. Плюс тест: штамп в пределах нескольких мс от time.time().
2. [Plugins/sim/robot_host/tests/test_acceptance_time_wait.py:157] [tests] Ветка win32 в предусловии проверяет только «bind проходит», а это верно и при отсутствии TIME_WAIT. Задача предусловия, прописанная в его же докстринге («без этой проверки AC1 мог бы пройти впустую»), на Windows больше не выполняется. Проверить можно: после _put_port_into_server_side_time_wait(port) psutil показывает (TIME_WAIT, 127.0.0.1:51996 к 127.0.0.1:51997), а эксклюзивный bind поверх него проходит. Исправление: на win32 сначала утверждать наличие TIME_WAIT на (127.0.0.1, port) через psutil.net_connections(kind="tcp"), потом bind. Имя ..._raises_eaddrinuse на Windows утверждает обратное — поправить докстринг или имя.

## A — ниты (не блокируют)
3. test_sim_robot_delay_floor.py:23 — тонкую поломку (INJ-B) тест ловит вероятностно, в 5 из 6 прогонов. Грубую (голый asyncio.sleep, инъекция лида) ловит надёжно, 76 из 80. Можно поднять _SAMPLES или прямо написать в докстринге, что обнаружение вероятностное.
4. Services/robot_comm/tests/conftest.py:23-42 — окружение процесса зависит от того, собран ли robot_comm. Сейчас это безвредно (замер выше). Эффект стоит описать в комментарии; переезд в корневой conftest — отдельной задачей.
5. sim_robot.py:71: комментарий «пустой host = все интерфейсы, как у pymodbus» неточен. Сокет AF_INET слушает только IPv4, тогда как asyncio с пустым host поднял бы v4+v6. Проба плагина и так AF_INET.
6. test_commit_keeps_file_mode: на POSIX проверка стала строже (S_IMODE + предусловие 0o644). На Windows защищает только бит read-only, это предел платформы, а не ослабление. repo_texture_dir пишет в data/ (в .gitignore, git check-ignore подтвердил). imread_unicode — продукт уже импортирует dataset_gen (make_font_letters.py:37). Правки line_sim, codegen и perf_counter в тестах — честные исправления тестов.

## Новый флик (есть на main, ветка ни при чём)
Plugins/sim/robot_host/tests/test_hazards.py::test_watchdog_holds_lock_across_mailbox_read_and_stop: упал 1 раз из 3 прогонов robot_host без инъекций и 1 раз из 40 прямых вызовов. Механизм: _jog_deadline = time.monotonic() + 0.05 (plugin.py:738, проверка на :484), а тест спит time.sleep(0.06). monotonic на Windows отсчитывает 60 мс как 46.9 мс в 252 из 2000 замеров, и сторож не видит истёкший дедлайн. Файлы в ветке не менялись (git diff --quiet main...HEAD чист). Тот же класс «квантованный monotonic». Это отдельная задача: тест должен спать дольше таймаута плюс разрешение часов, либо сторож перейти на perf_counter.

## B — прогоны и находки
- Целевой файл test_pm_marks_gone_reader_hazards.py 5 раз подряд: 11 passed каждый раз. process_manager_module целиком: 993 passed, 31 skipped, exit 0.
- Инъекция продукта «метка до _stop_one» (патч ProcessRegistry.stop_one): 4 red, включая целевой, как у лида.
- Нит 7 [tests]: в тесте нет положительного контроля пробы. С той же поломкой продукта плюс _pid_present, всегда возвращающим False, целевой test_mark_only_after_confirmed_death зелёный (3 red вместо 4). Сейчас пробу страхует только инъекция лида. Одна строка после reader.start(); time.sleep(0.3): assert _pid_present(reader.pid) is True.
- L-7 в defects.md сформулирован по делу; не проверял (вне охвата).

## Что оставил открытым / ненадёжно
- Всё мерено на одной машине, Win10 и py3.12. Оценка «эксклюзивность = простой bind» и «TIME_WAIT не мешает эксклюзивному bind» — тоже с неё. На других сборках Windows не проверял.
- Сдвиг +28 мс в находке 1 зависит от машины. Растёт ли расхождение QPC и tick-count с аптаймом, не измерял.
- Утечку conftest проверял на дереве фронта; остальные Qt-тесты из testpaths (backend_ctl, apps) с ней не гонял. Полный набор не запускал — по условию брифа.
- В дереве фронта 20 падений, которые ветка не трогала (sandbox/dashboard), не разбирал. Скорее всего, они есть и на main.
- Цену добора под реальной нагрузкой сервера (много клиентов) не мерил, только тикер 1 мс.
