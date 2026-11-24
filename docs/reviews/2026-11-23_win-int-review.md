# Ревью интеграционного диффа Win (lane-T-py314): CHANGES REQUESTED, итерация 1 из 2

Дерево: Inspector_bottles--wf-int (c7a2ccca7, правки не закоммичены), 24 файла + один intent-to-add.
Роль: reviewer. Файлы не правил. Каждая проверка ниже: вход -> наблюдённый выход; без воспроизведения помечено как advisory.
Memory hits: scripts/memory/search.py windows exclusive bind reuseaddr -> общие уроки по Windows; project_monotonic_resolution_windows.md согласуется с правкой fake_port и PM; прямых хитов по теме нет.

## Вердикт

CHANGES REQUESTED. Четыре production-правки (run_alpha, process_manager_process, socket_channel, fake_port) приняты: дефектов не нашёл, на каждую есть инъекция или зонд.
Один пункт обязателен (F1, tests, major): шесть skipif не отражают реальный факт платформы. Остальное: advisory или решение владельца.

## Таблица находок

| # | файл:строка | вход | наблюдаемый выход | severity |
|---|---|---|---|---|
| F1 | scripts/atlas/tests/test_store_tree_blind_4_5d.py:428,440,452,465; scripts/atlas/tests/test_store_tree_hazards.py:166,179 | а) снять skipif в памяти (плагин, режим unskip_utf8) и запустить test_a8_*; б) собрать тот же репозиторий с путём bad<0xFF>.py через STDIN (git update-index -z --index-info) и вызвать Tree(root, head).files() на Windows | а) 4 failed: UnicodeDecodeError, utf-8 codec: byte 0xff in position 51 (frozen os:861, os.fsdecode в argv подпроцесса); б) Tree.files() == ["ok.py"], stderr «atlas: пропущено 1 путей не в UTF-8». Контракт на Windows проверяем; не представима только сборка фикстуры через argv. Причина skip «имя файла из байтов не представимо на Windows» неверна для контракта | major (tests) |
| F2 | scripts/tests/test_letters_baseline.py:258-266 | новая ветка pytest.skip «ассеты сима устарели» | не воспроизведено: в моём дереве раньше срабатывает прежний skip :257 (нет модели и каталога). Это не факт платформы, а устаревшие данные; причину лечит пересборка ассетов (build_stand_assets.py --force), а не skip. Правило владельца допускает skip только по факту платформы | minor, advisory, решение владельца |
| F3 | Services/camera_device/plugin_base.py:129 | git grep make_port в боевом коде | create_port("fake") лениво тянет make_port(frame_period_s=0.02): FakePort и _wait_next_frame лежат в боевом пути драйвера fake. Утверждение DESIGN «тестовый помощник, не поставляемый код» неточно. Поведение проверено зондом (безопасно), радиус больше, чем test_fake_port_options | minor, advisory |
| F4 | apps/line_sim/tests/test_fit_letter_robot.py:99-103; apps/line_sim/tests/test_f1_task11_acceptance.py:269-313 | чтение кода | калибровка теперь из СИМ-рецепта (use_linear: true); согласованность сима с β-рецептом (use_linear: false с R4-2), §4.1, никем не закреплена; тест test_robot_client_reads_growing_encoder больше не использует RobotClient (имя вводит в заблуждение). Дефекта не воспроизвёл | minor, advisory |
| F5 | multiprocess_framework/modules/router_module/channels/socket_channel.py:60-79 | git grep SO_EXCLUSIVEADDRUSE | четвёртая копия приёма (Services/code_reader/core/sink.py:36, Services/code_reader/tools/id3000_tcp_sink.py:77-87, Services/robot_comm/server/sim_robot.py:48-80). Фреймворк не может импортировать Services (слои), копия оправдана; общий помощник во фреймворке, который импортируют Services, убрал бы три копии | minor, advisory |
| F6 | Services/camera_device/tests/test_fake_port_options.py | нет теста на timeout_ms=0 и отрицательный при frame_period_s>0 | зонд: оба дают False, 0.0000 с, 0 вызовов sleep (верно), но ничем не закреплено | minor, advisory |

Что исправить (итерация 1): F1: собирать фикстуру через stdin (_git_bytes и _commit_bad_path), снять _SKIP_NON_UTF8_ARGV, прогнать a8-тесты и test_store_tree_hazards на Windows. F2: решение владельца: пересобрать ассеты в данных машины либо принять guard явно.

## Ответы на вопросы brief

1. Поколение PM. Путей нет. Чтение: process_manager_process.py:1110 (внутри with self._run_lock) и :1614 (with self._run_lock). Запись: :1168 внутри того же with в _run_apply, единственная точка записи _run_state (:1165; второе упоминание :328 это __init__). Тик зовёт только монитор (process_monitor.py:840), под _run_lock он не вызывается, взаимной блокировки нет. Счётчик только растёт, поэтому eval_generation != текущее эквивалентно старому eval_started < метки входа; два входа подряд тоже дают !=. Остатков _run_running_mono и eval_started в коде нет (git grep). Инъекции (плагин в памяти, предсказание записано до запуска): nodrop (отбрасывание устаревшего такта выключено) -> красные test_stale_tick_after_start_does_not_fault и test_stale_tick_after_second_start_does_not_fault, зелёные остальные 2 (наблюдено 2 failed 2 passed: assert fault == running на :113 и :138); gen_first_only (счётчик растёт только при первом входе) -> красный ТОЛЬКО test_stale_tick_after_second_start_does_not_fault (наблюдено 1 failed 3 passed). Новый тест второго цикла различает.
2. SocketChannel. Зонд probe_timewait.py (Windows 10, 127.0.0.1): сервер закрыл принятое соединение первым (TIME_WAIT) -> перепривязка с EXCLUSIVEADDRUSE OK (с REUSEADDR тоже OK, без флага тоже OK); принятое соединение ещё открыто при закрытом слушателе -> OK в обоих режимах; два живых слушателя: оба EXCLUSIVEADDRUSE -> второй bind FAIL WinError 10048, оба REUSEADDR -> второй bind OK (это и был дефект). Опоры на REUSEADDR нет: SocketChannel.close() закрывает клиентов раньше серверного сокета, TIME_WAIT на Windows bind не мешает. Вызыватель с занятым портом: backend_ctl_endpoint.py:148-152 (start() False -> токен не трогается). Тесты: router exclusive_bind 3 passed; backend_ctl/tests/test_token_handshake.py 11 passed 1 skipped (skip вне диффа, причину не читал; в нём test_failed_bind_leaves_other_token_intact: второй ПМ на занятый порт, ожидает None); router test_socket_channel.py 29 passed; test_socket_client.py 3 passed; Services/robot_comm/tests/test_t38_line_view_acceptance.py 14 passed (fixed port через _t38_line_host.py:136). Инъекция reuseaddr (SO_REUSEADDR вместо исключительного): красный только test_second_start_on_busy_port_fails_and_first_keeps_serving (assert True is False), два теста переоткрытия зелёные, как предсказано. POSIX: getattr(socket, SO_EXCLUSIVEADDRUSE, None) даёт None, ветка SO_REUSEADDR как раньше; по чтению кода, не запускал.
3. fake_port. _wait_next_frame: перед sleep проверено now < next и now < deadline, значит аргумент sleep строго положителен; цикл выходит по сроку или по таймауту. Зонд probe_wait.py: timeout_ms=0 -> False, 0.0000 с, 0 sleep; timeout_ms=-5 -> то же; 40 кадров при периоде 0.05 и таймауте 500: None=0, минимальный интервал 0.0500, не более 1 вызова sleep на кадр; период 10 с, таймаут 100 мс -> False за 0.1005 с, 1 sleep. Кадр раньше периода невозможен: _next_frame_at = now + период, now берётся после срока. Инъекция oldwait (старая monotonic-логика) -> 2 failed (в том числе новый тест: assert 22 == 0, то есть 22 из 30 кадров были None), 18 passed.
4. run_alpha. self.tree = os.path.realpath(args.tree) (:260), script это константа без «..» (:35-36). На POSIX normpath от канонического пути и чистого литерала не меняет строку, normcase no-op: сравнение то же, что раньше, мягче не стало. Единственное расширение, Windows: разделители и регистр (NTFS регистр не различает). Инъекция nonorm (normcase и normpath тождества): 6 failed 3 passed, среди них test_listener_problem_compares_paths_across_separators (получено несовпадение D:/stand/apps/line_sim/run.py), новый тест охраняет свойство. Контроль в тесте: чужой скрипт и чужое дерево дают not None.
5. Skip. Новые в диффе: (а) _SKIP_NON_UTF8_ARGV определён в test_store_tree_blind_4_5d.py и применён к 4 test_a8_* (:428, :440, :452, :465); (б) то же определение в test_store_tree_hazards.py, применён к 2 тестам (:166, :179); (в) pytest.skip в test_letters_baseline.py (:258-266). xfail, importorskip: нет. Изменён (не новый) skipif у a5: hasattr(os, geteuid) and geteuid()==0; на Windows тест теперь запускается и проходит (blind_4_5d: 18 passed 4 skipped). Четыре «возможно лишних» skipif на test_a8_* существуют в диффе; без skip они красные (4 failed), но по F1 skip избыточен по сути: фикстуру можно собрать через stdin. Прочие skip в прогонах (time.tzset, geteuid в hazards:191,218; token_handshake; letters_baseline:257) в дифф не входят.
6. Spy и выведенные значения. Просмотрены все новые и изменённые тесты. Шпионов вместо наблюдаемого эффекта нет: exclusive_bind проверяет списки принятых сообщений и результат start(); fake_port проверяет список frame_num == [1..30]; стале-тик проверяет состояние running, событие, last_fault None; pid-реестр использует pid, записанный самим процессом-жертвой; run_alpha использует литеральные пути. Значения литералы. Слабое место одно: test_run_config_and_view_hazards подменяет time() в модуле PM на «+1 с на чтение» (_AdvancingTime), но проверяется набор записанных листов в сторе (наблюдаемый эффект), а не сами метки. Бенч f2: литерал 616 -> 629 оправдан коммитом b19437fdb (предок HEAD, правит stats_manager.py на включённой дороге), выключенная дорога 139 не тронута; тест 1 passed, прецедент e5777b1a7.
7. Окончания строк. git config core.autocrlf = true. git diff --numstat и git diff --ignore-space-at-eol --numstat: IDENTICAL, 24 строки, ни один файл не переписан целиком. git ls-files --eol: все изменённые i/lf w/crlf (смешанных w/mixed нет); scan.py: i/lf w/lf attr/text eol=lf; новый тест: i/none w/crlf (intent-to-add, нормализуется при add).
8. .gitattributes и SCANNER. SCANNER = "1-" + sha256(байты scan.py)[:12] (scan.py:69). sha256 блоба HEAD и индекса (LF): d8b9d44d5b0d; тот же файл в CRLF: aa42c394135e; файл в рабочем дереве сейчас (правило применено): d8b9d44d5b0d. git grep 1-d8b9d44d5b0d -- docs plans: хиты в plans/2026-11-06_atlas-passport/reports/... (паспорта 4.6-baseline, entry_before.out); закоммиченный хеш это LF-вариант. В docs/atlas ключа нет.

## Запущено (через gate, light, lane-T-py314, главный venv, PYTHONPATH = дерево)

| файл | результат |
|---|---|
| router_module/tests/test_socket_channel_exclusive_bind.py | 3 passed |
| backend_ctl/tests/test_token_handshake.py | 11 passed, 1 skipped |
| router_module/tests/test_socket_channel.py | 29 passed |
| router_module/tests/test_socket_client.py | 3 passed |
| Services/robot_comm/tests/test_t38_line_view_acceptance.py | 14 passed |
| process_manager_module/tests/test_run_shutdown_from_running_hazards.py | 4 passed |
| process_manager_module/tests/test_run_config_and_view_hazards.py | 52 passed |
| process_manager_module/tests/test_pid_registry_checkout_acceptance.py | 18 passed (75 s) |
| process_module/tests/test_f2_numbers_disabled_cost_bench.py | 1 passed |
| data_schema_module/tests/test_logger_seam_no_direct_logger_import.py | 5 passed |
| Services/camera_device/tests/test_fake_port_options.py | 20 passed |
| scripts/alpha_sim/tests/test_p4_alpha_runner.py | 9 passed |
| scripts/atlas/tests/test_store_tree_blind_4_5d.py | 18 passed, 4 skipped |
| scripts/atlas/tests/test_store_tree_hazards.py | 10 passed, 4 skipped |
| scripts/atlas/tests/test_file_not_parsed.py | 9 passed |
| scripts/atlas/tests/test_modules_roots_blind.py | 47 passed |
| scripts/atlas/tests/test_modules_roots_4_4.py | 13 passed |
| scripts/atlas/tests/test_passport_map.py | 13 passed |
| scripts/tests/test_letters_baseline.py + scripts/nav_bench/tests/test_analyze_pilot.py | 38 passed, 1 skipped (:257, прежний) |
| apps/line_sim/tests/test_fit_letter_robot.py | 3 passed |
| Plugins/processing/word_layout/tests/test_p3_hazards.py | 13 passed |
| apps/line_sim/tests/test_f1_task11_acceptance.py -k "robot_client or app_boots" | 3 passed (18 s) |

Gate выдал exit 0 на каждом запуске; пропусков gate (exit 75) не было. Соответствие чисел файлам в параллельной пачке (три раза по 13 passed: word_layout, passport_map, roots_4_4) выведено по порядку вызовов; сверять по именам файлов.
secrets_audit.py --format json: --root multiprocess_framework/modules/router_module -> exit 0, findings пусто; --root multiprocess_framework/modules/process_manager_module/process -> exit 0, findings пусто.

## Инъекции (в памяти, ни один файл не правился)

Плагин: C:/Users/INNOTECH/AppData/Local/Temp/claude/65f734dde6ea3dc7/ad054591-efb3-40e2-a684-2e0d7b7b2962/scratchpad/rev_int/rev_inject.py, режим в переменной REV_INJECT, запуск pytest -p rev_inject, в PYTHONPATH дерево и эта папка.
Зонды в той же папке: probe_timewait.py, probe_a8_stdin.py, probe_wait.py.
Режимы nodrop, gen_first_only, oldwait, nonorm, reuseaddr, unskip_utf8: предсказания записаны до запуска, все совпали (см. ответы 1-5).

## What I left open / unreliable

- Не запускал каталоги целиком. Radius SocketChannel: не гонял frontend_module/tests/test_remote_*, channel_routing_module/tests/test_forward_outcome.py, backend_ctl/tests/test_driver.py, test_session_isolation.py, test_token_client.py, router hol- и auth-тесты. Radius fake_port: весь Services/camera_device/tests (класс medium и выше). Зелёные только перечисленные файлы.
- POSIX не запускал (машины нет): неизменность поведения SocketChannel на POSIX выведена по чтению кода, не по прогону.
- TIME_WAIT и «открытое принятое соединение» измерены на 127.0.0.1, одна сборка Windows 10; не на стенде и не с аварийно упавшим процессом, державшим соединения.
- Ветку «ассеты устарели» test_letters_baseline не исполнял (в дереве нет data/ с моделью): F2 это чтение кода, не воспроизведение.
- apps/line_sim acceptance: 3 теста из 7. Утверждение в docstring, что v1 REG_ENC (0x1112) под v2 читается нулём, не проверял; порядок слов TLM_ENC подтверждён лишь тем, что тест роста проходит.
- Инъекции есть только для PM, fake_port, run_alpha, SocketChannel и a8. Для переименований aux_ и nul_, _posix в nav_bench, real_pid в pid-реестре, бенча f2, _AdvancingTime и -X utf8 в seam-тесте зелёный прогон доказывает лишь, что тесты проходят, а не что охраняют свойство.
- G4 «threads without scope path» (socket-ch-inbound-backend_ctl) в прогонах T38 и test_socket_client: информативно; базовый коммит не прогонял, не знаю, было ли так до правки.
- Правило eol=lf для scan.py действует при новом checkout или git add --renormalize: уже существующие CRLF-копии scan.py дают другой SCANNER (aa42c394135e) и холодный кэш. Не проверял, остаются ли такие копии в главном дереве.
- Отчёты исполнителей (docs/reviews/2026-11-23_win-*.md, docs/reports/2026-11-23_deps-py314_win-compare.md) не читал: вывод построен на диффе и прогонах. Слои (sentrux check) не запускал: новых межслойных импортов в диффе нет, socket_channel добавил только вызовы socket.
- Один skip в test_token_handshake.py (вне диффа) не разбирал.

## Round 2 (итерация 2 из 2): только F1

Вердикт: APPROVED. F1 закрыт; новых находок нет.

1. Фикстуры строят настоящий не-UTF-8 путь. test_store_tree_blind_4_5d.py:408-418: index_info = b"".join(b"100644 " + blob + b"TAB" + name + b"NUL") идёт в stdin git update-index --add -z --index-info; имена в тестах это байтовые литералы b"bad\xff.py" и b"dir/\xfe\xfd" + b"worse.py" (строки :425, :436, :447, :459). Страховка setup (assert b"TAB" + name + b"NUL" in listing по ls-tree -r -z) осталась. test_store_tree_hazards.py:136-148: stdin = b"100644 " + blob + b"TAB" + b"bad\xff.py" + b"NUL" (байтовый литерал). Зонд probe_indexinfo_eq.py: сырые байты в дереве есть, listing.decode("utf-8") -> invalid start byte at 56 (то есть не UTF-8-двойник). Ожидаемые значения в тестах литералы: ["ok.py"], list(oids) == ["ok.py"], "atlas: пропущено 1 путей не в UTF-8", «пропущено 2 путей».
2. Прогон (gate light): test_store_tree_blind_4_5d.py: 22 passed, 0 skipped; test_store_tree_hazards.py: 12 passed, 2 skipped. ruff check -q на обоих файлах: exit 0, вывода нет. git grep skipif и pytest.skip в двух файлах оставляет три места: (а) blind_4_5d.py:284 skipif(hasattr(os, geteuid) and os.geteuid() == 0), reason «root пишет в файл с правами 0o444: сценарий только чтение не воспроизвести»: реальный факт платформы (root), на Windows условие ложно и тест выполняется; (б) hazards.py:176 skipif(not hasattr(time, tzset)), reason «time.tzset нет (Windows): пояс процесса не подменить»: реальный факт платформы, прежний; (в) hazards.py:203 skipif(нет geteuid или root), reason «нет os.geteuid (Windows) или root: ... сценарий только чтение не воспроизвести»: прежний, в дифф не входит. Новых skip нет; _SKIP_NON_UTF8_ARGV отсутствует.
3. Моя инъекция (плагин rev_inject, режим noskipdec: Tree._ls теряет skip_undecodable, git_z вызывается с skip_undecodable=False). Предсказание до прогона: blind_4_5d 4 красных test_a8_* (пятый, test_a8_tree_without_non_utf8_paths, зелёный); hazards 1 красный test_non_utf8_path_skipped (test_git_z_is_strict_by_default_on_non_utf8_path остаётся зелёным, он и так зовёт git_z без пропуска). Наблюдено: blind_4_5d 4 failed 18 passed, красные ровно четыре test_a8_files_..., test_a8_oids_..., test_a8_non_utf8_path_reports_exactly_one_stderr_line_..., test_a8_skipped_count_...; hazards 1 failed 11 passed 2 skipped, красный test_non_utf8_path_skipped. Во всех пяти: UnicodeDecodeError: byte 0xff in position 56 (смещение 56 = 53 байта заголовка ls-tree + "bad", то есть настоящий 0xFF из вывода git). Предсказание совпало.
4. Эквивалентность --index-info -z и старой --cacheinfo (read-only свидетельства). Документация Git for Windows 2.50.0 (git-update-index.html, локальная): --index-info принимает формат mode SP sha1 TAB path, формат поддерживается и дальше; -z значим для --stdin и --index-info, пути разделены NUL; --cacheinfo описан как прямая вставка записи в индекс. На машине, эмпирически: для валидного UTF-8 пути (dir/файл.py) дерево write-tree после --cacheinfo и после --index-info -z побайтно одинаково (55f82a6b401ffb8e6e32047af2754cefba32f2af). Для пути с 0xFF на Windows работает только stdin-вариант (argv падает в os.fsdecode), поэтому равенство на таком пути напрямую не показать. Исходники git не читал: что оба пути приходят в add_cacheinfo, а в -z режиме путь не раскрывается из C-кавычек, помню по builtin/update-index.c, но в этой сессии не проверял; это свидетельство из памяти, не чтения. POSIX не запускал.

### What I left open / unreliable (round 2)

- POSIX: фикстуры не запускал на Linux/macOS; эквивалентность старой argv-фикстуры на POSIX опирается на документацию и на эмпирическое равенство деревьев для валидного пути на Windows. Для пути с 0xFF прямого сравнения двух способов нет (на Windows argv-способ невозможен).
- Поведение git в исходниках (add_cacheinfo, отсутствие unquote при -z) описано по памяти, не проверено чтением исходников.
- Версия git: проверено на 2.50.0.windows.1 одной машины; старые версии git, где --index-info -z мог вести себя иначе, не проверял.
- Инъекция noskipdec покрывает только продукт (Tree._ls); в фикстурах я не проверял вариант, где stdin-путь тихо превращается в валидный UTF-8 (его исключают assert страховки в blind_4_5d и ожидание stderr в hazards; в hazards у самой фикстуры страховки ls-tree нет, спасает ожидаемая строка «пропущено 1 путей», без неё утверждение files == ["ok.py"] было бы выполнено и при пустом пути).
- Остальные пункты раунда 1 (F2-F6, непрогнанные пакеты, POSIX SocketChannel) не пересматривал; они остаются как в разделе выше.
