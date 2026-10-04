# CONSOLIDATED — чистка памяти: сводное предложение

Дата: 2026-10-04. Только чтение: ни память, ни репозиторий не менялись. Источники: `R1_feedback_a-l.md` (135), `R2_feedback_m-z.md` (138), `R3_project_rest.md` (157), три индекса (MEMORY, CRAFT, ARCHIVE) = 433 файла. Проверки по репозиторию — `git grep` (без `grep -r` от корня).

## 0. Итог в числах

| Показатель | Было | Станет |
|---|---|---|
| `MEMORY.md` (грузится в каждую сессию) | 33 516 Б | **7831 Б** (`wc -c MEMORY.new.md`), цель ≤ 8 192 |
| Файлов в корне памяти | 433 | 254 (из них 3 новых урока, 4 файла CRAFT-*, заглушки правил) |
| Файлов в `_archive/` | 0 | 187 |
| Размер CRAFT (читается по триггеру) | 40 233 Б одним файлом | 33942 Б в 4 файлах по 7.5–9.9 КБ |

Действия по 430 файлам (без 3 индексов):

| вид \ действие | KEEP | MERGE | MOVE-RULE | POINTER | ARCHIVE | всего |
|---|---|---|---|---|---|---|
| LESSON | 190 | 3 | 0 | 0 | 1 | 194 |
| RULE | 2 | 4 | 28 | 5 | 0 | 39 |
| STATE | 1 | 0 | 0 | 0 | 72 | 73 |
| REFERENCE | 14 | 1 | 0 | 0 | 0 | 15 |
| DUP | 1 | 41 | 2 | 0 | 0 | 44 |
| REDUNDANT | 1 | 0 | 0 | 0 | 34 | 35 |
| STALE | 0 | 3 | 0 | 0 | 27 | 30 |
| **всего** | **209** | **52** | **30** | **5** | **134** | **430** |

Итого: KEEP 209 · MERGE→выживший 52 · MOVE-RULE 30 · POINTER 5 · ARCHIVE 134 (из них MOVE-RULE и POINTER остаются в памяти заглушкой; в `_archive/` уходят ARCHIVE и MERGE = 186).

Показано «до» вердиктов R1–R3: KEEP 88+83+29 (R1/R2/R3), MERGE 27+23+2, MOVE 16+14+0, ARCHIVE 4+16+114. Мои правки: +1 KEEP (`migration_fixture`), +MERGE для `parametrization`, `a_hook_that_writes…`, `pydantic_assignment`, `git_stash_pop`, `guard_on_existence`, `project_qex_reindex_timeout`; MERGE→KEEP для 5 «мягких» слияний R2; ARCHIVE→MOVE-RULE для `subagent_live_test_monitor_hang`; MOVE-RULE→POINTER для 3 правил, что уже есть в `.rules/`.

Уроков вытащено из STATE-файлов: **15** (3 новых файла, 12 дополнений к выжившим). Ещё 6 «находок» R3 уже лежат в репозитории (ADR, STATUS, ORDER) — действий нет (раздел 1).

Расхождения между отчётами решены так (подробности в разделах 2 и 5):
- Три цепочки «выживший одного отчёта архивируется другим» разрезаны: `background_reviewer_loses_the_verdict`, `git_main_merge_hook_traps`, `check_red_on_main_first`.
- Слияния G13 (R1), `protect_branch…` → `git_main_merge_hook_traps` (R2), `parametrization…` → G1 (R2) отклонены. Причины в разделе 2.
- Слияния G3, G5, G8 (сомнение R1) приняты частично: G3 и G5 — да, G8 — только пара из двух; тест миграции остаётся отдельным файлом.

## 1. Шаг 1. Разбор больших STATE-файлов (прочитаны целиком)

Прочитаны целиком: `project_observability_closure_progress` (55 КБ), `project_constructor_master_progress` (39 КБ), `project_cross_tab_phase_g` (35 КБ), `project_backend_ctl_d1_session_isolation` (18 КБ, единственный ещё > 15 КБ). Файлы 8–13 КБ (`pult_control_panel`, `telemetry_self_publish`, `backend_control_mcp`, `observability_namespace_symmetry`, `phone_gateway_service`, `line_sim_vision`, `phase_g_final_review`, `telemetry_subscription_bug`, `transport_router_hub`) просмотрены по словам «урок / ловушка / баг» и вырезкам вокруг них, не целиком.

Все четыре — чистый прогресс по закрытым или архивным планам. Вердикт для всех: ARCHIVE после переноса строк ниже.

### 1.1 Новые уроки (3 файла)

**L1. `feedback_test_the_door_the_production_caller_uses`** — модуль: process_module, router_module, frontend; механизм: test-entry-point. Три независимых случая одного класса, ни один не записан как урок:
- constructor-master Ф3.7: авто-рестарт (монитор → PM) живьём никогда не работал. `_dispatch_due_restarts` слал `type="system"`, после P4.4.1(B2) `process.command` стала командой CommandManager и до CM не доходила. Юнит Ф3.1 проверял факт отправки IPC, не исполнение. Поймала только fault-injection с реальной смертью процесса (kill → новый pid).
- backend-control-mcp P1 (`a6f0221a`): встроенные команды регистрировались после единственного `register_commands_with_router()`, в router их не было, IPC-команды молча дропались. P1-юниты звали handler через фейк.
- cross-tab G.4.4: два параллельных undo. Глобальный `QShortcut` в MainWindow затенял domain-undo, виден только в живом GUI. Тесты звали handler напрямую.
Тело (5–8 строк): ловушка — тест входит мимо двери, которой пользуется боевой вызывающий; признак — «тест зелёный, фича не работала живьём»; правило — входить через `router.receive` / настоящий key-event / реальную смерть процесса и утверждать эффект (новый pid, дельта state), не факт отправки; рядом — брать настоящий orchestrator+store+EventBus вместо `MagicMock(spec=...)`. Соседи: `two_tests_enter_from_both_sides_and_miss_the_connector`, `a_stand_with_a_verdict_is_also_a_harness`, `qt_mcp_smoke_verification`.

**L2. `feedback_getattr_default_hides_a_phantom_attribute`** — модуль: frontend, process_manager_module; механизм: dead-branch, getattr-default. Доказательства из cross-tab G: `getattr(services.commands, "action_bus", None)` стоял в 9 местах, метода у orchestrator не было никогда, ветка всегда `None`; `bus.execute` при `bus=None` молча терял правки полей (боевой баг); `getattr(services.topology, "_holder", None)` — при удалении holder вернёт `None` без ошибки; `TopologyBridge` не имеет свойства `topology` — пикер пуст; три `getattr(services.registers, "_rm")`. Тело: `getattr(x, "name", None)` на несуществующем имени — вечный тихий `None`; перед удалением или переездом holder/bridge грепнуть все `getattr(...,"имя",None)` против определения класса; заменить атрибутом Protocol или громким отказом.

**L3. `feedback_live_switch_test_survivor_must_be_protected`** — модуль: process_manager_module, backend_ctl; механизм: live-stand. `FullReplacePlanner` при `topology.apply` сносит ВСЕ non-protected процессы, `gui` вырезает `strip_gui`; поэтому «выживший отправитель» в живом тесте switch — только protected-процесс (`devices`). Доказательство: Ф3.1, `test_routing_epoch_live` (RED→GREEN), switch/restart на разных портах 8778/8779, switch необратимо пачкает relay-счётчик соседа. **Проверить до создания:** есть ли это в докстринге `test_routing_epoch_live.py`; если да — не создавать, дать ссылку.

### 1.2 Дополнения к выжившим (12)

| # | Куда добавить | Что (одна строка с доказательством) | Источник |
|---|---|---|---|
| A1 | `feedback_worktree_stale_base` | Worktree агента рождается от origin/main или чужой базы, не от текущего HEAD: агент не видит свежих доков; перед merge/cherry-pick сверять merge-base (Ф3.4: база `6e97b993` чужая); первый запуск агента может молча исполнить ДРУГУЮ задачу (вернул подсчёт LOC вместо C4) — сверять результат с ТЗ до merge | constructor_master |
| A2 | `project_observability_store_error_routing` | `health.report` логирует на WARNING, forward-tap с min ERROR его не ловит; настоящий ERROR даёт `start_capture` (live 2026-07-10) | constructor_master |
| A3 | `feedback_sentrux_depth_opaque` | Kill изолированных мёртвых листьев не двигает метрики (modularity 5665→5667, depth без сдвига); repo-wide modularity не видит разрез god-файла — мерить max-LOC зоны | constructor_master |
| A4 | `feedback_three_lenses_three_defect_classes` | Ф4.9: 2152 зелёных юнита пропустили дыру мульти-лист merge (все сценарии — одиночный set); поймало только Fable-ревью | constructor_master |
| A5 | `project_concurrent_backends_trap` | Живые пробники с BackendHarness — только файлом (spawn не работает из stdin); свой порт ≥ 8770, свой `INSPECTOR_PID_FILE`; `app.yaml` — артефакт лаунчера, в коммит не брать | constructor_master |
| A6 | `feedback_a_plans_premise_expires` | Cross-tab Ф.G: ложная посылка при детализации ШЕСТЬ раз подряд (G.2 Protocol не несёт FieldInfo; G.4.2b display-узлы никогда не рисовались; G.4.3 IPC уже был; G.4.4 фантом `action_bus()`; G.5; G.6 — 3 из 4 посылок brief §5). Даже «design LOCKED» требует grep + investigator | cross_tab_phase_g |
| A7 | `feedback_predict_injections_after_writing_tests` | Закон двух матриц Ф2 closure: расхождение предсказания в опасную сторону (красных меньше) дало ВСЕ настоящие находки (B2, E1; H5, H11); совпало 13 из 19 и 6 из 11. Недостача красных — находка, не шум | observability_closure |
| A8 | `feedback_classify_a_leaf_by_the_difference_of_two_values` | Раскладка от частичного запроса частична: один лист называется в одиночку и сверяется внутри полной секции (38 сверено / 14 названо на 52 листьях) | observability_closure |
| A9 | `feedback_an_inventory_grep_needs_fixed_strings` | Инвентарь по одному написанию пропускает семейство: «226» мерило `_log_error`, пропустив 66 вызовов `.log_error` (верно 315); считать по перечисленным написаниям | observability_closure |
| A10 | `feedback_measure_delta_not_file_size` | Число снято верно, приложено к не той величине: 476 Б payload против 745 Б строки на диске; горизонт платит вторую (рекомендация 1/18 → 1/31) | observability_closure |
| A11 | `project_live_findings_webcam_2026_07` | Живой отказ открытия камеры воспроизводится НЕСУЩЕСТВУЮЩИМ `device_id=7`, не занятым устройством (MSMF пускает второго открывателя) | observability_closure |
| A12 | `project_monotonic_resolution_windows` | `cycle_metrics.effective_hz = 1/cycle_duration` на `time.monotonic()` давал FPS=0 у consumer-воркеров; фикс `b6ce2bb8` — интервал между `record()` на `perf_counter` | telemetry_self_publish |

### 1.3 Уже есть в репозитории (действий нет, только указатель)

| Находка | Где лежит |
|---|---|
| Fencing по incarnation, не по epoch (live RED при зелёных юнитах) | ADR-PMM-014, ADR-MSG-009; `project_topology_fencing_token` |
| Авто-рестарт всех: механизм и громкие supervisor-события | ADR-PMM-015 |
| «Главное число Ф3 не взято» (горизонт 2.6 ч против 24, 54.8 МиБ/ч против 4), три рычага владельцу | `docs/claude/OPEN_QUESTIONS.md:733–773` (проверено, R3 не проверял) |
| Секция Services обязана реализовать `action_buttons()` | `Services/control_panel/STATUS.md:15` |
| Механизм per-session dotted-subscriber (BCTL-ADR-005) | `backend_ctl/DECISIONS.md:88–104` |
| Вердикт «recorder оставить» (2026-07-22) | `backend_ctl/DECISIONS.md:191–194` |

### 1.4 Решения владельца из этих файлов

| Решение | Где записано | Действие |
|---|---|---|
| Р-1…Р-12 `observability-closure` (Р-10 «единица — ветка»; критерий 2.4 принят непройденным; Ф3 урезана CTO с 9 до 6) | `plans/observability-closure/plan.md` (Р-10 на строке 351) | нет |
| G2 форм: FREEZE 7b/7c/7d | `multiprocess_framework/docs/MODULE_TIERS.md:68–72` | нет |
| Depth-гейт как принятый долг | `.sentrux/rules.toml:27` (сейчас **0.53**, в памяти написано 0.57) | в архив без правки |
| «Recorder оставить» | `backend_ctl/DECISIONS.md:191` | **не нужна запись в `plans/queue/decisions.md`**: файл ведёт только открытые решения. Флаг R3 снят |
| **Вкладка Plugins = превью/песочница без привязки к топологии; «слить Plugins с Pipeline» — отдельная UI-задача после Ф.G** (владелец 2026-05-29) | нигде кроме памяти (`git grep` песочниц/sandbox в `plans/`, `docs/claude/`: нет) | **ДОБАВИТЬ строкой в `plans/queue/decisions.md`** (открытое, UI) |
| Master plan «актуальный путь» `plans/current-path/` «ждёт одобрения» (2026-07-11) | план в репозитории, статус одобрения в ORDER не найден | **проверить**; если не одобрен — строка в `decisions.md` |
| Открытые вопросы constructor-master: перекалибровка метрик приёмки (H.5), ранний вынос frozen-boundaries, R2-residual (гейт recovered на health.status==ok), скоуп 5.11 | `decisions.md` содержит #4, #5, #7; остальные не найдены | **проверить** по `plans/2026-07-06_constructor-master/plan.md`; недостающее — строкой |

## 2. Шаг 2. Таблица действий и слияния

Полная таблица на 433 файла — раздел 6 (и машинная копия `ACTIONS.tsv` для скрипта). Здесь — группы слияния.

### 2.1 Решение по сомнению R1: G3, G5, G8 — слить или оставить раздельно

Критерий: общий триггер у человека в момент работы. Если триггер один и приёмы — оси одного чек-листа, то один файл с таблицей «ось → пример → проверка»; если триггеры разные, то раздельные файлы с общим тегом.

| Группа | Решение | Причина |
|---|---|---|
| G3 дублёры (4 файла) | **СЛИТЬ** в `a_faithful_fake_still_lacks_the_protocol` | Триггер один: «пишу дублёр». Четыре оси — протокол, читаемые против писаемых имён, форма отказа, темп — это пункты одного чек-листа. Прочитаны все 4 целиком. Целевой размер ≤ 5 КБ |
| G5 стражи (5 файлов) | **СЛИТЬ** четыре (`guard_threshold…`, `a_list_walking_guard…`, `coverage_per_check…`, `parametrization…`); `guard_on_existence…` вынут в G-testpaths | Один класс: сторож по агрегату или перечню слеп к точечной потере. Существование-против-содержимого — класс «тесты-невидимки» (testpaths), его триггер другой |
| G8 (3 файла R1) | **ПАРА**: `a_guard_below_the_claim…` → `a_handmade_readback…`. `a_migration_fixture…` — **отдельно** | Readback: фикстура собрана руками, производитель не охраняется. Миграция: фикстура собрана сегодняшним писателем, мигрировать нечего. Это ловушки с противоположным знаком и разным триггером (тест миграции) |
| Мягкая семья «probe-design», «break-injection-design (8)», «perf-measurement», «throttle» | **не сливать**, общий тег `mechanism:` | разные приёмы, свои доказательства; сжатие пары `different_lens` + `generator_must_differ` — на усмотрение лида |
| Новая пара R3: `switch_delivers_layer` + `switch_routing_stale` | **не сливать**, общий тег `switch-redelivers-state` | два механизма: стейл-копия PSR против недоставленного слоя L2; один триггер, но разные причины и фиксы |

### 2.2 Слияния, перечитанные целиком (16)

«Целиком» = оба или все файлы группы прочитаны до конца (длинные — первые 1.3–2.8 КБ после frontmatter, это почти весь урок). Выживший, что получает, и вердикт.

| Выживший | Поглощает | Что унести (по прочитанным файлам) | Вердикт |
|---|---|---|---|
| injection_zero_may_mean_the_guards_were_not_collected | a_zero_under_injection_has_three_readings, injection_base_needs_a_collected_count, broken_injection_is_not_a_vacuous_test, an_injection_must_prove_its_axis_is_live, zero_reds_can_mean_a_useless_layer | Таблица «чтение нуля → признак → проверка»: (1) не собрались, база без фильтра и `passed>0`; (2) заплата не легла (греп маркера, `count==1`, `except` в заплате запрещён); (3) ось пуста: `round`≈`int` на 0 из 144, показать `база → под заплатой` ДО подсчёта, traceback не ось (порог: красных втрое больше предсказания или код возврата зонда ≠ 0); (4) сломанный импорт даёт ERROR, не FAILED; подмена похожим вызовом; инъекция в алиас вместо контейнера; (5) код лишний (сравнение уже в Pydantic `__eq__`) — исход: удалить слой. `injection_base_needs…` уже целиком внутри | ПОДТВЕРЖДЕНО (5 файлов; `parametrization…` убран). Выживший 8.3 КБ → перестроить в таблицу, ≤ 6 КБ |
| a_guard_that_counts_at_least_once_is_blind | guard_threshold_hides_partial_blindness, a_list_walking_guard_cannot_see_a_removed_item, coverage_per_check_is_not_coverage_per_claim, parametrization_built_from_the_subject_collapses_with_it | Одна ось «сторож по агрегату слеп к точечной потере»: порог по сумме → цикл по записям `blind=[…]` (инъекция и-3); обходчик реестра → литерал `assert "key" in REGISTRY` рядом + заплата «запись удалена» (I16: предсказано {A9b,G2}, получено {A9b}); инъекция на УТВЕРЖДЕНИЕ, не на проверку (F2-3: три утверждения, одна инъекция; K12 0→1); параметризация из испытуемого исчезает вместе с ним (59→47, пороги ≥25/≥8 пройдены) → страж поимённого покрытия. Остаётся прокси-лок по дорогам (`_CountingLock`, литералы 2/1) | ПОДТВЕРЖДЕНО (5 файлов); `guard_on_existence…` вынут в G-testpaths. Выживший ≤ 5 КБ |
| zone_guard_never_closes_the_class | tests_invisible_to_testpaths, guard_on_existence_is_not_a_guard_on_content | `path.exists()` против «в каталоге есть `test_*.py`»: пустой каталог с `__pycache__` после `git mv` ADR-124, страж молчал три месяца; усиление показать красным на историческом случае, прежняя редакция на нём зелёная; уборка мусора делает видимым скрытое. Первый случай серии: три каталога `tests/`, 58 тестов вне testpaths (5361 passed) | ПОДТВЕРЖДЕНО для `guard_on_existence` (прочитан); `tests_invisible…` — по голове |
| a_faithful_fake_still_lacks_the_protocol | a_stub_silences_the_names_it_is_read_for, fake_that_always_succeeds_mutes_the_gate, double_must_block_like_the_original | Чек-лист из четырёх осей: протокол (`track_error` pop-ает `module`/`message`; одно имя, две двери, два симптома); читаемые против писаемых имён (И6: 5 красных; И10: 69 зелёных; контракт-тест `hasattr` + поиск `self.<имя> =`); форма отказа (`queue_registry` True на любую очередь → I-12: 0 красных вместо 1); темп (мгновенный `receive` против `timeout=0.1` → разгон памяти, одна инъекция осталась в дереве) | ПОДТВЕРЖДЕНО (4 файла целиком). Выживший ≤ 5 КБ, таблица «ось → пример → инъекция» |
| a_handmade_readback_leaves_its_producer_unguarded | a_guard_below_the_claim_guards_the_layer_not_the_claim | Сторож стоит у НАЧАЛА дороги, заявление называет КОНЕЦ: `base_stats.update(voice_counters())`→`pass` убила 0 из 350, второй сторож охранял членство в белом списке. Приём: минимум один тест берёт `effective` у настоящего производителя; своя матрица ломает механику, а не дорогу наружу | ПОДТВЕРЖДЕНО (пара). `a_migration_fixture…` ОТДЕЛЬНО: противоположная ловушка |
| commit_takes_the_whole_index | commit_msg_format, precommit_rollback_drops_unstaged_edits | `git commit` берёт индекс целиком (34 удаления D2 уехали в `fix(store): D3`); `git show --stat` сразу; ruff-format правит файлы → re-stage и НОВЫЙ commit, не amend; откат pre-commit теряет незастейдженное, правки живут в `~/.cache/pre-commit/patchNNN` → `git apply --3way`. Пункт 1 `commit_msg_format` (trailer одной строкой) УСТАРЕЛ: хук терпит перенос с 2026-07-14 — не переносить | ПОДТВЕРЖДЕНО (3 файла); `rollback_drops` перенаправлен сюда (R2 слал в B) |
| precommit_stash_collision_2plus_agents | parallel_agents_commit_race, a_hook_that_writes_a_shared_file_deadlocks_two_writers | Хук `append session log` СНЯТ 2026-10-03 — основной механизм ушёл, остаётся стеш pre-commit при двух писателях. Уникальное: `MM` значит «обе стороны есть», не «обе целы»; commit с pathspec строит ВРЕМЕННЫЙ индекс из HEAD, пустой `git diff` его не видит; три коммита подряд отбиты; потолок 2–3 повторов, затем стоп; история: 5 агентов 2026-05-24, сообщение коммита `829176c` не совпало с содержимым (одна строка) | ПОДТВЕРЖДЕНО. R1 ставил STALE → ARCHIVE; перенаправлено в MERGE: уникальные факты остаются |
| a_peer_session_shares_the_tree | shared_tree_makes_injections_look_like_flakes, worktree_for_parallel_samefile, git_stash_pop_wrong_stash | Общее git-состояние: инъекция `restore` затёрла правку агента (два ложных факта; хэш исходников в потоке, `base=CHANGED`); worktree от committed HEAD для правки того же файла (`git checkout -b` утащит чужую незакоммиченную работу); `git stash` общий на ВСЕ worktree; `stash -u` на чистом дереве ничего не прячет, `pop` берёт чужой `stash@{0}`; после любого pop — `grep '<<<<<<< '`; агентам `git stash` запрещён в промптах | ПОДТВЕРЖДЕНО (4 файла). `check_red_on_main_first` НЕ влит (раздел 2.3) |
| framework_first | constructor_modularity, fewer_layers, fix_framework_forward, freeze_over_kill | Пять принципов одним блоком из 5 строк: framework универсален, прототип расходный; чинить вперёд, не удалять; FREEZE, не KILL (прецеденты `actions_module`, GATE G2 форм 7b/7c/7d, P4.4 command-bus); меньше слоёв; pluggable/testable/composable. «Unused ≠ unneeded» — для блоков фреймворка за контрактом; мёртвая проводка прототипа — просто чистка | ПОДТВЕРЖДЕНО (5 файлов); цель — root CLAUDE.md (+~700 Б на сессию, решение лида/владельца) |
| logger_error_stats_managers | all_components_base_manager, three_managers_share_base | Цена единообразия — lifecycle-церемония `initialize/shutdown`, принята осознанно 2026-06-07; иерархия `ChannelRoutingManager` ← `LoggerCore` (Logger, Error) и `StatsManager` мимо `LoggerCore` (у stats нет `set_sink_enabled`, `add_log_tap`, `_fallback_log`) — факт 2026-07-26 | ПОДТВЕРЖДЕНО (3 файла по 0.9–1.3 КБ). Правило уже в root CLAUDE.md п. 6 → POINTER; сверить `.rules/logging.md` |
| zero_observations_looks_like_a_result | silent_detector_proves_nothing | Детектор показать СТРЕЛЯЮЩИМ хоть раз: 5.11-R4 `No handler for key` — ноль дважды (смотрел не в тот каталог логов; строка есть в обоих прогонах с тем же счётом). Три обличья 2026-08-23: мёртвые агенты (mtime + `.pytest_cache` + ListAgents), харнесс `passed=0`, приёмка мимо настоящего кода | ПОДТВЕРЖДЕНО (пара) |
| test_params_hide_defect_window | test_values_near_defaults_test_the_default, test_setting_one_handle_of_a_pair_measures_priority | Три способа сделать свойство неразличимым: упрощённые параметры (backoff 0.0, severity ниже порога tap, `adapter=None`) → хоть один тест с боевыми значениями; значение у дефолта (0.25 ≥ 0.25 → 0.60 против ≥ 0.45 даёт 2/2); пара ручек (`MULTIPROCESS_LOG_DIR`/`INSPECTOR_LOG_DIR`) → чистить соседнюю форму | ПОДТВЕРЖДЕНО (3 файла) |
| test_reddens_only_under_a_paired_injection | two_safeguards_hide_which_one_holds | Два предохранителя держат гарантию: трасса мимо цепочки + INFO ниже потолка `sampling_max_level: DEBUG` → 0 красных вместо 1; в стенде снять все предохранители, кроме проверяемого; сломать ПАРУ: красный от пары = композиция (оставить), зелёный от пары = вакуум (переписать) | ПОДТВЕРЖДЕНО (пара) |
| test_survived_its_own_break | seam_must_fire_on_full_release | Шов на RLock: считать глубину, стрелять на ПОЛНОМ отпускании; признак — файл 5.43 с вместо 0.36 с (= `join(timeout=5)`); конкурент в отдельном потоке с `join` по дедлайну (тот же поток проходит через RLock насквозь); `sys.setswitchinterval(1e-6)` с восстановлением в `finally` | ПОДТВЕРЖДЕНО (пара) |
| qex_full_rebuild_runbook | qex_reindex_budget, project_qex_reindex_timeout | Одна хронология: 4b + таймаут ~10 с в бинаре → keep_alive=-1 (47 с против 1.9 с) → 0.6b + полный ребилд 2026-08-27 → runbook 2026-10-01. Диагностика: три неверные гипотезы, греп по `GIN`, не `api/embed`; свежесть — `last_indexed`. Таймаут кусает при батче ≥ 10 с (раздел 5, п. 1) | ПОДТВЕРЖДЕНО частично (3 файла прочитаны); `project_qex_model` вне группы |
| git_main_merge_hook_traps | (protect_branch_blocks_worktree_subagents — НЕ влит) | — | ОТКЛОНЕНО: другой триггер (бриф писателя в worktree); MOVE-RULE в project-rules §5 |

### 2.3 Слияния, отклонённые или перенаправленные

| Предложено | Решение | Причина |
|---|---|---|
| R1 G13: `git_stash_pop_wrong_stash` → `check_red_on_main_first` | **ОТКЛОНЕНО**. Stash-pop → `a_peer_session_shares_the_tree`; `check_red_on_main_first` → MOVE-RULE в debugger | у одного триггер «диагностирую красный тест», у другого «общий git-стейт». Новое знание из constructor_master: stash общий на все worktree |
| R2: `protect_branch_blocks_worktree_subagents` → `git_main_merge_hook_traps` | **ОТКЛОНЕНО**. MOVE-RULE в project-rules §5 и team-brief | триггер «пишу бриф писателю в worktree», не «сливаю в main». Хук сам записан в `OPEN_QUESTIONS.md:1390,1465` |
| R2: `parametrization_built_from_the_subject…` → G1 | **ПЕРЕНАПРАВЛЕНО** в G5 | это не «ноль красных», а «таблица случаев исчезает вместе с испытуемым» (59→47); родня `guard_threshold` |
| R1 G13/R2 цепочка: `zero_reds_can_mean_a_useless_layer` → `a_zero_under_injection…` (сам слит) | **ПЕРЕНАПРАВЛЕНО** прямо в выжившего G1 | цепочка из двух слияний ломает ссылки |
| R2: `subagent_live_test_monitor_hang` → `background_reviewer…` (R1 архивирует цель) | **ПЕРЕНАПРАВЛЕНО**: MOVE-RULE в project-rules §5 | цель в архиве — вливать некуда |
| R2: `model_economy_scheme`, `review_economy_tiers` → ARCHIVE; `model_split…` → `explicit_model_per_agent_role` | принято | ростер ролей в `.claude/CLAUDE.md` |
| R2 «мягкие» merge: `probe_liveness_is_not_render`, `pydantic ×2`, `stub/stub` | `probe_liveness` — KEEP; `pydantic ×2` — слить (выживший `model_copy_does_not_validate`) | probe_liveness — другой дефект (рендер); pydantic — один класс «v2 не стережёт изменение» |
| R3: `project_qex_model` → qex-группа | **KEEP отдельно** | REFERENCE по платформам; ловушка silent-CPU уникальна |
| R3: `project_recipe_inspector_join_key` KEEP | **ARCHIVE** | костыль `_hoist_inspector_from_metadata` снят в Ф4.7 (раздел 5, п. 2) |
| R3: `project_backend_ctl_recorder_kept` | ARCHIVE | вердикт уже в `backend_ctl/DECISIONS.md:191` |
| R2: `package_install_by_user` — «deny уже в settings» | ARCHIVE, но причина другая | в `settings.json` это `ask` (`pip install`, `uv pip install`, `uv add`), не `deny`; `python -m pip install` не закрыт |

### 2.4 Слияния, принятые по голове (файлы не перечитывались целиком)

Выполняющий перед каждым слиянием читает оба файла целиком и переносит только строки из колонки «унести».

| Выживший | Поглощает | Что унести (по отчёту) |
|---|---|---|
| inject_only_after_the_work_is_committed | injection_rollback_by_restore_not_replace, a_lock_patch_can_hang_the_exit_not_the_test | откат восстановлением сохранённого текста (`str.replace` задел соседнее поле, 7 красных); заплата на лок вешает выход через `logging.shutdown` — внешний срок и КОД ВЫХОДА; лучше как чек-лист скрипта инъекций (R1) |
| fakes_feed_config_flat_so_key_address_defects_are_invisible | config_delivery_shape_differs | исправление `read_process_config(svc, key)` в `process_module/configs/observability_layers.py`; спавнер мержит `orchestrator_config` в корень (R1) |
| an_absence_assertion_needs_a_reachability_check | absence_assertion_under_extra_ignore_is_vacuous | частный случай pydantic `extra=ignore`: переписать на `model_fields_set` (R1) |
| a_control_reproduces_the_defect_it_was_built_to_catch | checked_true_answers_for_the_call_not_the_coverage | `checked: true` при пустом списке: `continue` на правиле без `interval_sec`, троттл резал в 40 раз (R1) |
| bash_tool_unbalanced_quote_breaks_command | bash_heredoc_collapses_backslashes | обход один: скрипты с прозой и обратными слэшами — через Write/Edit, `chr(92)` в Python; подтверждено на себе: heredoc с апострофом упал и при сборке этого отчёта (R1) |
| backend_ctl_for_agents | diagnose_live_system_with_backend_ctl | `system_overview` + `supervision_status` + `get_status` за 3 вызова против самописного psutil (R1) |
| three_lenses_three_defect_classes | review_finds_the_seam_between_own_pieces | пример 5.11 d+f: каждый кусок верен, стык нет (R2) |
| the_plans_stated_cause_is_a_hypothesis | plan_spec_can_lie | `manual_restarts` → `instance_restarts` (ревью Fable) (R2) |
| property_unchecked_at_the_second_party | one_door_two_roads_needs_two_guards | `channels.hub_stats.enabled`: `_setup_channels` против пересборки после `config.reload` (R2); R2 просил перечитать |
| recipe_knob_must_be_named_in_from_recipe | read_the_key_from_the_section_already_travelling | два `BlueprintAssembler`: boot `launch.py` и switch `orchestrator_hooks.py` (R2) |
| sqlite_pragma_fails_silently | stepwise_statement_needs_draining | таблица форм вызова `incremental_vacuum`: 2116 → 2115 страниц (R2) |
| qt_mcp_flag_value_is_compared_verbatim | qt_mcp_always_probe | строка запуска `QT_MCP_PROBE=1 python multiprocess_prototype/run.py <recipe>` (R2) |
| explicit_model_per_agent_role | model_split_impl_vs_review | исполнители Sonnet по умолчанию, Opus — верхний край; главный чат без `[1m]` и fast mode (R2) |
| model_copy_does_not_validate | pydantic_assignment_keeps_rejected_value | `validate_assignment`: отказ, но значение осталось (`max_export_batch_size=20480`) (R2) |
| project_backend_ctl_signal_integrity | project_backend_ctl_missing_contract | «missing / ноль / null — три факта», поле `missing` (R3) |
| project_devseed_overwrites_claude_dir | project_claude_kit_migration | как обновлять `.claude/`; пути Mac пометить (R3) |

## 3. Шаг 3. Правила → механизмы

35 файлов RULE (R1 — 20, R2 — 14, R3 — 5; после слияния G11 и перенаправлений — 35 строк действий). Для каждой — «уже есть?» по `git grep` целевого файла. «Нет» = перенос нужен в рецепте (шаг 8). «Есть» = только указатель.

**Пункты `settings.json` — РЕШЕНИЕ ВЛАДЕЛЬЦА (права доступа). Не считать одобренными.** Их три: `no_global_taskkill`, `uv_sync_prunes_venv`, `no_qt_popups_offscreen`. Для третьего предложен другой механизм (см. строку).

| № | Правило (одна строка; язык цели) | Цель | Исходные файлы | Уже есть? (git grep цели) |
|---|---|---|---|---|
| 1 | Before closing a plan, read QUEUE/ORDER and the plans of adjacent mechanisms; add a two-way link (who owns what, what it takes, what it gives, where the conflict is). | `/dev:plan` + агент manager | a_new_plan_must_be_placed_among_its_neighbours | нет: в `plan.md` слова ORDER/QUEUE о другом |
| 2 | In a developer brief: commit subject in English or Russian, never transliterated Latin; check `git log --oneline -1` before any push. | project-rules §4 | agent_commit_quality | нет (`translit`: 0) |
| 3 | Use tier aliases (opus/sonnet/haiku/fable) in agent files and prose; a model version only with a stated reason. | project-rules §5 + lint-agents allow-list | always_latest_models | нет в skill; allow-list не проверен |
| 4 | Count dotted names (metrics, modules, config keys) with `grep -F` only, over every spelling of the family. | project-rules §1/§2 | an_inventory_grep_needs_fixed_strings (+A9) | нет |
| 5 | Debug and test the backend through `backend_ctl` (same router messages as the GUI); `qt-mcp` only to test the GUI itself; no ad-hoc psutil. | `.claude/CLAUDE.md` «MCP routing», строка backend-ctl (стр. 310) | backend_ctl_for_agents, diagnose_live_system_with_backend_ctl | частично: строка описывает сервер, правила нет |
| 6 | Commits for `backend_ctl` use `Layer: mixed`, not `tools` (allowlist has no `tools`). | `docs/claude/COMMIT_GUIDE.md` | backend_ctl_layer_mixed | частично: `mixed` описан (стр. 100), про backend_ctl нет |
| 7 | Before diagnosing a red test as a regression, run it on main (worktree, not stash). | агент debugger + skill systematic-debugging | check_red_on_main_first | нет |
| 8 | Unsaved-changes dialog: Save (default) / Don't Save / Cancel. | `.rules/gui.md` | dialog_conventions | нет |
| 9 | Memory has ONE canonical copy (`docs/claude/memory`); the local folder is a cache refreshed by `robocopy`; never `cp` over without `diff`. **Текст меняется вместе с режимом dual-write.** | root CLAUDE.md «Memory» + `.claude/CLAUDE.md` «Memory» | dual_write_by_copy_destroys_the_other_side | нет; старый dual-write надо переписать |
| 10 | Pass `model` explicitly on every Agent call (reviewer/teamlead opus, developer/tester/debugger sonnet, cto fable); state it in the brief. | project-rules §5 | explicit_model_per_agent_role, model_split_impl_vs_review | нет (ростер ролей есть, правила передачи нет) |
| 11 | A dark-launch flag task is closed only when the flag and its OFF branch are deleted. | `/dev:ship` + шаблон Task | flags_must_not_become_crutches | нет |
| 12 | Run a formal `/code-review` before any merge to main. | `/dev:ship` | formal_review_before_merge | нет (`code-review`: 0) |
| 13 | Framework universal, prototype disposable; fix framework by improving; freeze dead code, do not kill; fewer layers; every component pluggable and testable. | root CLAUDE.md «Принципы владельца» (5 строк, +~700 Б на сессию) | framework_first (+4 файла G11) | нет; FREEZE частично в `MODULE_TIERS.md:72` |
| 14 | A gate result is valid only for the HEAD it ran on; at acceptance run the gate yourself. | `/dev:ship` + агент cto | gate_signature_lives_on_a_head | нет |
| 15 | Merge commits: `merge: <что вошло>` + Why/Layer/Refs; `git merge -F -` does not read stdin. | `COMMIT_GUIDE.md` + root CLAUDE.md; грабли 1–6 остаются LESSON | git_main_merge_hook_traps | нет (`merge:` в COMMIT_GUIDE: 0) |
| 16 | Log, report errors, count stats only through injected managers (ObservableMixin). | root CLAUDE.md правило 6, `.rules/logging.md` | logger_error_stats_managers (+2) | ЕСТЬ в root; **`.rules/logging.md` требует «import logging запрещён» при 142 файлах на `get_std_logger` — проверить актуальность** |
| 17 | New GUI tab — full MVP (presenter + view Protocol + widget). | `.rules/gui.md:17` | mvp_pattern | ЕСТЬ |
| 18 | Never kill processes by image name; TaskStop or PID only. | `.claude/settings.json` deny `Bash(taskkill /IM*)`, `Bash(taskkill /F /IM*)`, `Bash(pkill*)`, `Bash(killall*)`. **РЕШЕНИЕ ВЛАДЕЛЬЦА** | no_global_taskkill | нет в deny. Частично: `.claude/security-patterns.json` напоминает при ПРАВКЕ кода, не при Bash |
| 19 | Agent test runs use `QT_QPA_PLATFORM=offscreen`. | `conftest.py` корня тестов (`os.environ.setdefault`). **РЕШЕНИЕ ВЛАДЕЛЬЦА.** `settings.json` env не годится: правило 34 требует настоящие окна для живого стенда | no_qt_popups_offscreen | нет |
| 20 | Plugins never read SHM directly; use framework middleware. | `.rules/plugins.md:15` | no_shm_hacks | ЕСТЬ (+ `security-patterns.json`) |
| 21 | Every observability knob switchable on/off at any boundary, zero load when off. | project-rules (раздел observability) + ADR модуля (Task 4.15) | observability_knobs_… | нет |
| 22 | One active plan per tool or module; add new work as a phase, not a new file. | root CLAUDE.md «Plan-Driven Development» | one_active_plan_per_tool | нет |
| 23 | One writing logger manager; others are views over it or a proven exception. | `channel_routing_module/DECISIONS.md` или ADR logger_module | one_log_writer | нет по фразе (проверить ADR) |
| 24 | A pipeline node inspector reuses the Plugins-tab widgets; fields resolve by `plugin_name`. | `.rules/gui.md` | pipeline_reuse_plugins_widgets | нет |
| 25 | After a task: `[ ]` → `[x]`, commit hash next to it. | `/dev:implement` (шаг закрытия) | plan_checkboxes | частично: `implement.md:76` про статус `[PENDING]→`, `[x]`+hash нет |
| 26 | Name the expected failing set AFTER the last test is written. | `.claude/CLAUDE.md`, bullet «Break-injection is the proof» | predict_injections_after_writing_tests (+A7) | нет по фразе |
| 27 | A writer in a worktree stages explicit paths, runs ruff itself, writes the commit message to a file; the lead commits (protect-branch reads main). | project-rules §5 + `team-brief.md` | protect_branch_blocks_worktree_subagents | нет |
| 28 | After a Qt task: run the prototype with `QT_MCP_PROBE=1` and `qt_snapshot`. | `.rules/gui.md` + чек-лист `/dev:implement` | qt_mcp_smoke_verification | частично: `gui.md:50–53` про probe и baseline |
| 29 | Run live tests synchronously; at the second stall the lead takes the check over. | project-rules §5 | subagent_live_test_monitor_hang | нет |
| 30 | Tab order: Settings → Recipes → functional tabs. | `.rules/gui.md:27` | tab_order | ЕСТЬ |
| 31 | A public path with no live caller is a contract: fix it or reject loudly in review. | агент reviewer + project-rules | unused_paths_are_contracts | нет |
| 32 | `uv sync` only with `--inexact`; never without. | `.claude/settings.json` ask `Bash(uv sync*)`. **РЕШЕНИЕ ВЛАДЕЛЬЦА** + строка в project-rules | uv_sync_prunes_venv | нет (в ask есть `uv add`, `uv pip install`; `uv sync` нет) |
| 33 | `claude-kit upgrade --apply` silently overwrites `.claude/`: keep valuable text only in preserved places; `diff` before upgrade. | `.claude/CLAUDE.md` | project_devseed_overwrites_claude_dir (+claude_kit_migration) | частично: `.claude/BOOTSTRAP.md` упоминает |
| 34 | Bring up the live GUI stand only through the production entry with `INSPECTOR_GUI_UNATTENDED=1` and real windows. | команда `core:quality:observability-acceptance` + project-rules | project_gui_stand_production_entry_only | нет (UNATTENDED только в `backend_ctl/AGENTS.md` и пробах) |
| 35 | Priority is a pendulum by free time; order of work only in `plans/queue/ORDER.md`. | `plans/queue/ORDER.md:62` | project_priority_engine_first | ЕСТЬ |

Итого: «есть» — 5 (16, 17, 20, 30, 35); «частично» — 5 (5, 6, 25, 28, 33); «нет» — 25.

**Конфликт 19 против 34.** Первое требует `offscreen`, второе — настоящие окна. Если положить `QT_QPA_PLATFORM` в `settings.json` env, он затронет и живой стенд, запущенный агентом из Bash. Поэтому для правила 19 предложен `conftest.py`, а не `settings.json`.

**Хуки как механизм.** Хук-кандидат нашёл один: `devseed`-правило (проверка перед `claude-kit upgrade`). Остальные — текст в командах, агентах и `project-rules`. Существующий механизм `security-patterns.json` уже ссылается на три памяти (`feedback_no_shm_hacks`, `feedback_dict_at_boundary_gui`, `feedback_no_global_taskkill`): `dict_at_boundary_gui` уходит в архив, поэтому в его reminder заменить ссылку на «CLAUDE.md rule 1».

## 4. Шаг 4. Новый MEMORY.md и CRAFT

Файлы: `MEMORY.new.md` (7831 Б по `wc -c`, цель ≤ 8 192) и `CRAFT.split.md` (четыре файла, 17 потерянных строк).

Что сделано в `MEMORY.new.md`:
- Скелет R3 §6.4: шапка, правила на каждую сессию (указатели), решения владельца, окружение (local-only), уроки по тегам, как писать.
- Убраны устаревшие строки: указатель на handoff 2026-09-07; «std_facade не используется — 76 файлов» (опровергнуто: `get_std_logger` в 142 файлах); «порядок 2026-09-09: line-sim → …» (ORDER.md 2026-10-03 ведёт порядок); «Командный режим … живой прогон не делался» (пилот v2 прошёл); весь раздел «Активные проекты и долги» (8 063 Б) заменён строкой про `ORDER.md`; раздел «Домен: робот, зрение, ML» (1 097 Б, указатели на STATE).
- Дубли с CRAFT.md (8 одинаковых ссылок и «три роли», «тестер один раз», «инъекция на свойство») сняты: в индексе остался указатель на `.claude/CLAUDE.md` «Test authorship» и четыре строки-триггера на CRAFT-файлы.
- Ссылки: 43 прямых для правил, которые срабатывают до того, как о них вспомнят, плюс 42 коротких имён в разделе 4 (`f:` = feedback_, `p:` = project_) ради бюджета байт. **Риск:** `memory_lint.py` ждёт формат `- [Title](file.md) — hook`; запустить его на `MEMORY.new.md` до приёмки. Если линтер отвергнет короткие имена — заменить их ссылками для 15 самых важных, остальное оставить в CRAFT.
- Две ссылки на файлы, которых нет в git-копии (`reference_gpu_monitoring_windows`, `user_career_goal` — local-only, исключены dual-write): в git-копии они мертвы; решение владельца — внести их в git или пометить `(локально)`.

Разрез CRAFT — см. `CRAFT.split.md`.

## 5. Шаг 5. Факты, которые надо проверить до исполнения

1. **qex: противоречие «BM25-сегменты» против «таймаут зашит в бинарь».** Прочитано целиком: `project_qex_reindex_timeout`, `feedback_qex_full_rebuild_runbook`, `project_qex_model`, корневой `CLAUDE.md` (раздел qex).
   - Файл `project_qex_reindex_timeout` (2026-07-27): таймаут клиента ≈ 10 с в бинаре, батч эмбеддингов 8–10 с (модель 4b) — попадание впритык. Ручки нет; лечится циклом повторов.
   - Тот же файл, добавка 2026-08-31: «подтверждает гипотезу, что реиндекс упирался в накопленные BM25-сегменты» (`tantivy/` 5.7 ГБ → 127 МБ).
   - Runbook (2026-10-01, модель 0.6b): три батча по 64 дают ровные ~2.7 с; п. 6 всё ещё пишет «два индексатора выбивают друг друга по зашитому ~10 с таймауту».
   - Вывод: утверждения не противоречат, но «подтверждает» — перебор. Таймаут 10 с кусает, только когда батч ≥ 10 с (модель 4b не в VRAM, два индексатора на одном Ollama, выгруженная модель). На 0.6b и прогретой модели батч 2.7 с — запас в 3.7 раза. BM25-сегменты объясняют часы, а не отказы по таймауту. Третье объяснение (`qex_reindex_budget`: выгрузка эмбеддера из VRAM, 47 с против 1.9 с) тоже написано под 4b.
   - **Проверить:** (а) `strings qex.exe` на «timeout»; (б) времена трёх батчей на 0.6b сейчас; (в) падал ли хоть один реиндекс по таймауту после 2026-08-27. До проверки в survivor `qex_full_rebuild_runbook` писать одну хронологию: 4b + таймаут → keep_alive → 0.6b + ребилд → runbook.
2. **`_hoist_inspector_from_metadata` «не найдена» — не потеряна, а снята.** `git grep` по `*.py` даёт 0 функций и 3 комментария в `process_manager_module/topology/blueprint.py` (стр. 214, 230, 413: «снятый», «снят вместе с этим методом»). Замена — `BlueprintSpec.infer_missing_collectors` (Ф4.7, join выводится из графа wires). Память `project_recipe_inspector_join_key` устарела → ARCHIVE. **Проверить остаток:** покрывает ли `process_module/tests/test_blueprint_wire_collector.py` случай «GUI-save уронил ключ в `metadata`».
3. **«Recorder оставить» не записано в `decisions.md`.** Проверено: решение записано в `backend_ctl/DECISIONS.md:191–194`; `plans/queue/decisions.md` ведёт только ОТКРЫТЫЕ решения (таблица «Открытые решения владельца», закрытые зачёркнуты). Запись не нужна. Побочно: нумерация в `decisions.md` сбита (две строки №10, №12 перед №11).
4. **`.rules/logging.md` против stdlib-миграции.** Файл: «в коде запрещён `import logging`, только LoggerManager». Корневой `CLAUDE.md`: «`get_std_logger` + LoggerManager»; `get_std_logger` в 142 файлах. Правило, вероятно, устарело; решить до того, как считать правило 16 «присутствующим».
5. **`settings.json`.** Проверено: `deny` не содержит `taskkill`, `pkill`, `killall`; `ask` не содержит `uv sync`; `package_install_by_user` покрыт `ask`, не `deny` (R2 ошибся); есть `env: MCP_TIMEOUT…`. `python -m pip install` не закрыт ничем.
6. **Три копии памяти, не две.** `docs/claude/memory/` (git, 431 файл, не хватает только `reference_gpu_monitoring_windows`, `user_career_goal`), локальная `~/.claude/projects/…/memory/` и `.claude/memory/` (36 файлов в git, Mac). `.claude/memory/MEMORY.md` ссылается на 4 переезжающих имени. Агентские папки `.claude/agent-memory/*` — отдельная система (11 файлов ссылаются на переезжающие имена).
7. **Входящие ссылки на переезжающие файлы.** `git grep -F`: 91 файл вне `docs/sessions` и `docs/claude/memory` + 75 файлов в `docs/sessions/` (журналы append-only). Из 91: ~35 в `plans/_archive/` (заморожены), ~12 в agent-memory и `.claude/memory`, остальные живые. **Функциональные ссылки (чинить):** `.claude/security-patterns.json` (3 имени, одно архивируется), тест-докстринг `logger_module/tests/test_f2_task27_manual_window_registry_matches_claims.py` (строка 40 ссылается на `project_observability_closure_progress.md:72`), `multiprocess_framework/DECISIONS.md` и `process_module/DECISIONS.md`, `multiprocess_prototype/frontend/app.py:692`, `backend_ctl/probes/probe_observability_consumer_acceptance.py:1341`. Остальное закрывает `_archive/INDEX.md` (имя → куда ушло).
8. **R3 не проверял живьём; решение об архиве зависит от проверки** (`ARCHIVE` держать до проверки):

| Файл | Что проверить до архива |
|---|---|
| project_device_hub | блок «контракты НЕ ломать» против `Services/device_hub/README` |
| project_processes_workers_runtime | долг `assigned_worker PENDING` |
| project_recipe_save_load_arch | долги `on_result`, `switch≠boot` |
| project_macos_shm | число 15 skipped (REFERENCE?) |
| project_command_engine_audit (KEEP) | ActionBus всё ещё сирота |
| project_gui_system_queue_storm (KEEP) | чинено ли (в `defects.md` нет) |
| project_switch_routing_stale (KEEP) | фикс через PM-хаб сделан? |
| project_app_module_windows_test_debt (KEEP) | красны ли 2 теста сейчас |
| project_services_vs_plugins | перенос строки «side-effect-процесс = плагин в GenericProcessApp + фрагмент топологии» в ADR-120, если её там нет |
| project_observability_namespace_symmetry | три факта (точки в паттернах троттла; `module_*` каналы в секции `modules`; глубокий merge каналов плоскости ошибок) есть в ADR logger_module? |
| project_pipeline_node_plugin_containers | долг MovePlugin в планах pipeline |

9. **Статус «план закрыт» взят из ORDER.md.** ORDER сам пишет, что шапки планов врали в 5 случаях. Скрипт шага 3 проверяет путь плана в колонке «target» каждой строки ARCHIVE: нет в `git ls-files` — строка возвращается в KEEP.
10. **Посылки «правило уже в target»** сверены по смыслу `git grep`, не построчно, для `.claude/CLAUDE.md` (REDUNDANT-вердикты R2: `test_authorship_three_roles`, `tester_*`, `spec_review…`, `think_en_speak_ru`). Проверить, нет ли в архивируемых файлах чисел, которых нет в `.claude/CLAUDE.md` (479k токенов там есть).
11. **Слепое пятно R1/R2:** `claude_cli_backend_costs_a_full_session` оставлен как файл (ссылается root CLAUDE.md), `check_qex_freshness_before_use` и `qex_query_english_code_bias` — ARCHIVE (правило в трёх местах).

## 6. Таблица действий (433 строки)

Колонки: файл | вид | действие | цель | теги | причина. Действия: KEEP · MERGE→выживший · MOVE-RULE→цель (правило переносится, файл остаётся заглушкой в 4 строки) · POINTER (правило уже в цели, файл → заглушка) · ARCHIVE (→ `_archive/`, запись в `ARCHIVE.md`). Теги `module:` / `mechanism:` — из отчётов R1–R3, без проверки по `modules/`. Имена даны без префикса `feedback_` и `project_` не сокращаются (префикс виден).

| файл | вид | действие | цель | теги | причина |
|---|---|---|---|---|---|
| ARCHIVE | INDEX | KEEP+EXTEND | раздел «Перенесено 2026-10-04» | - | дом для 186 перенесённых файлов |
| CRAFT | INDEX | SPLIT | CRAFT-injection/tests/verdict/config-qt (CRAFT.md → заглушка) | - | разрез по триггеру, 17 строк потеряно |
| MEMORY | INDEX | REPLACE | MEMORY.new.md | - | новый индекс ≤ 8 КБ |
| feedback_a_budget_belongs_to_a_path_not_to_a_mechanism | LESSON | KEEP | - | mod: telemetry/observability; mech: perf-… | Замер 1.35 против 3.53 мкс; верное решение отвергли по чужой дороге |
| feedback_a_control_can_exist_and_be_dead | LESSON | KEEP | - | mod: telemetry, config.reload; mech: acce… | Стенд: success, но лист шагает 5.0 с |
| feedback_a_control_reproduces_the_defect_it_was_built_to_catch | LESSON | KEEP | - | mod: observation_port; mech: success-valu… | Три этажа одного дефекта; delivered=5 без приёмников |
| feedback_a_criterion_that_transforms_observes_the_library | LESSON | KEEP | - | mod: config_module (pydantic); mech: acce… | Критерий неисполним ни одной реализацией; S-24 |
| feedback_a_decision_orphans_what_encoded_the_previous_one | LESSON | KEEP | - | mod: telemetry config, golden snapshots; … | cb79d884 осиротил 3 артефакта; гейт две недели красный |
| feedback_a_dedup_marker_is_an_assertion_about_someone_else | LESSON | KEEP | - | mod: logger_module, error_module; mech: d… | Харнес: 1 строка до правки, 0 после |
| feedback_a_degenerate_value_is_not_zero_it_is_unknown | LESSON | KEEP | - | mod: process_module telemetry; mech: vali… | tick=0.0 вернул тот же отчёт; heartbeat min=0.0 |
| feedback_a_delta_benchmark_hides_what_sits_on_both_sides | LESSON | KEEP | - | mod: observation_port; mech: perf-measure… | Мерился двойник; бюджет 2 -> 5 мкс поднят зря |
| feedback_a_diagnostic_answer_must_be_computed_last | LESSON | KEEP | - | mod: process_module (config.reload); mech… | Два одинаковых reload дали разные caps |
| feedback_a_diff_based_rescue_omits_untracked_files | LESSON | KEEP | - | mech: git, worktree | Тест на 454 строки не попал в патч |
| feedback_a_faithful_fake_still_lacks_the_protocol | LESSON | KEEP | - | mech: test-doubles; mod: error_module | track_error pop-ает message; сторож зелёный на лжи |
| feedback_a_fix_on_a_finding_must_not_outgrow_it | LESSON | KEEP | - | mod: pipeline/plugin_module; mech: review… | Фильтр RUNNING срезал processing; батч поехал молча |
| feedback_a_guard_below_the_claim_guards_the_layer_not_the_claim | DUP | MERGE→ | a_handmade_readback_leaves_its_producer_unguarded | mod: logger_module; mech: guard-layer | Заплата pass убила 0 из 350; тот же класс, что G8 |
| feedback_a_guard_that_counts_at_least_once_is_blind | LESSON | KEEP | - | mech: guard-design, lock-discipline | RLock в 7 позициях снят: 12 тестов зелёные |
| feedback_a_handmade_readback_leaves_its_producer_unguarded | LESSON | KEEP | - | mod: observability_wiring; mech: guard-la… | 145 зелёных при снятой строке readback |
| feedback_a_hook_dead_on_windows_by_a_trailing_cr | LESSON | KEEP | local-only (Windows/Git Bash) | mech: hooks | autoformat мёртв с 2026-05-15; 68 отказов ruff |
| feedback_a_hook_that_writes_a_shared_file_deadlocks_two_writers | STALE | MERGE→ | precommit_stash_collision_2plus_agents | mech: git, pre-commit | Хук снят 2026-10-03; в .git/hooks/pre-commit его нет |
| feedback_a_knob_can_be_applied_and_unverifiable | LESSON | KEEP | - | mod: process_module (observability_verifi… | events.*: unverifiable при checked=0; соседняя ручка 8/8 |
| feedback_a_list_walking_guard_cannot_see_a_removed_item | DUP | MERGE→ | a_guard_that_counts_at_least_once_is_blind | mod: backend_ctl protocol; mech: guard-de… | I16: ключ удалён, тест зелёный; держит один литерал-тест |
| feedback_a_lock_patch_can_hang_the_exit_not_the_test | DUP | MERGE→ | inject_only_after_the_work_is_committed | mod: logger_module; mech: break-injection… | 1 failed, 162 passed, затем pytest завис минутами |
| feedback_a_measurement_capped_by_its_own_limit_proves_nothing | LESSON | KEEP | - | mod: backend_ctl (history_query); mech: p… | С limit=20000: 8788 = 2298 + 6490 |
| feedback_a_migration_fixture_built_by_todays_writer_tests_the_writer | DUP | KEEP | - | mod: observability store; mech: migration… | отдельный триггер (тест миграции); обратная ловушка к readback |
| feedback_a_new_guard_can_weaken_an_old_one | LESSON | KEEP | - | mod: process_module commands; mech: guard… | bool -> 1.0 дошёл до хендлера; нашёл старый тест |
| feedback_a_new_plan_must_be_placed_among_its_neighbours | RULE | MOVE-RULE | команда /dev:plan + агент manager | mech: plans | Правило процесса; поправка владельца 2026-09-22 |
| feedback_a_number_without_spread_across_repeats_is_an_observation | LESSON | KEEP | - | mod: BoundedChannel/telemetry; mech: perf… | 118.7, 48.8, 0.5 мкс на одном коде |
| feedback_a_pass_through_block_is_not_a_fork | LESSON | KEEP | - | mod: scripts static guards (AST); mech: A… | Три редакции обходчика, ошибки нашла только инъекция |
| feedback_a_peer_session_shares_the_tree | LESSON | KEEP | - | mech: git, parallel-sessions | Автор найден через ListAgents; стейджить явные пути |
| feedback_a_plans_premise_expires | LESSON | KEEP | - | mech: plans, deferred-tasks | 2.3b: коллизия жива после 2.4/2.5 |
| feedback_a_probe_must_enumerate_before_it_asks | LESSON | KEEP | - | mod: config_module (defaults_for_category… | Категорий sources/utility нет вовсе; нашло ревью |
| feedback_a_probe_that_guesses_tempo_says_no_when_it_means_dont_know | LESSON | KEEP | - | mod: otel-export; mech: probe-design | Все пять — дефекты зонда: форма, темп, готовность |
| feedback_a_process_wide_throttle_turns_neighbours_vacuous | LESSON | KEEP | - | mod: logger_module (windowed_voice); mech… | Два соседа сломаны правкой в 8 строк; вакуумный зелёный |
| feedback_a_shared_throttle_swallows_the_record_not_the_line | LESSON | KEEP | - | mod: process_module/health, error_module;… | Повтор в окне: плоскость ошибок не получила ничего |
| feedback_a_shortened_interval_waits_out_the_old_deadline | LESSON | KEEP | - | mod: observability_wiring (history purge)… | Ждали 14 с: ноль голоса; ручка отвечала success |
| feedback_a_stand_with_a_verdict_is_also_a_harness | LESSON | KEEP | - | mod: otel-export; mech: live-stand, test-… | Своя заглушка 200 на любой путь; otelcol дал 404 |
| feedback_a_stub_silences_the_names_it_is_read_for | DUP | MERGE→ | a_faithful_fake_still_lacks_the_protocol | mech: test-doubles | И6 писаемое имя: 5 красных; И10 читаемое: молчит |
| feedback_a_test_that_pins_a_hole_is_green_both_ways | LESSON | KEEP | - | mod: backend_ctl (history_query); mech: b… | Заплата И5 его не покраснила; это документация |
| feedback_a_zero_under_injection_has_three_readings | DUP | MERGE→ | injection_zero_may_mean_the_guards_were_not_collected | mech: break-injection | Тот же ноль, те же чтения; унести: у выхода несколько стражей |
| feedback_absence_assertion_under_extra_ignore_is_vacuous | DUP | MERGE→ | an_absence_assertion_needs_a_reachability_check | mod: config_module (pydantic extra=ignore… | Тот же класс; унести: переписать на model_fields_set |
| feedback_absent_receiver_lets_a_test_pin_an_impossible_input | LESSON | KEEP | - | mod: config_module (MetricRule); mech: te… | Тест годами зелёный на {fps: True}, прод отвергает |
| feedback_acceptance_criterion_needs_a_live_trigger | LESSON | KEEP | - | mod: observation_port (plugin shutdown); … | _do_shutdown вызывается из одного места; ручки нет |
| feedback_agent_commit_quality | RULE | MOVE-RULE | skill project-rules §4 (одна строка) | mech: agents, commits | Правило процесса; в агентах/плагине слова translit нет |
| feedback_agent_hard_budget_is_off_by_default | REFERENCE | KEEP | - | mod: hooks (agent_context_ceiling); mech:… | developer ушёл на 401k токенов; хук и файл есть |
| feedback_agent_resume_ghost | LESSON | KEEP | - | mech: agents, SendMessage | Watchdog не смерть; проверять mtime зоны |
| feedback_alias_keeps_the_object_alive | LESSON | KEEP | - | mod: channel_routing_module/router_module… | После сноса 204 красных; channel_dispatcher = self._dispatcher |
| feedback_all_components_base_manager | DUP | MERGE→ | logger_error_stats_managers | mod: base_manager; mech: ObservableMixin | Тот же принцип; унести: цена — lifecycle-церемония, принято |
| feedback_always_latest_models | RULE | MOVE-RULE | skill project-rules §5 + lint-agents allow-list | mech: agents, models | Правило процесса; закреплено lint allow-list |
| feedback_always_project_venv | REFERENCE | KEEP | local-only (Windows, пути .venv) | mech: env | uv run падает на extras ml-torch; qt-mcp висел в cfg |
| feedback_an_absence_assertion_needs_a_reachability_check | LESSON | KEEP | - | mod: scripts static guards; mech: absence… | Тест-негатив зелёный при красном предмете |
| feedback_an_applying_command_cannot_measure_what_it_reapplies | LESSON | KEEP | - | mod: process_module (config.reload); mech… | Второй reload вернул 3.5 вместо 9.25: переустановил |
| feedback_an_avoidance_rule_can_be_a_false_safety_catch | LESSON | KEEP | - | mod: scripts/run_framework_tests.py; mech… | Раннер уже гоняет оба в одном процессе |
| feedback_an_injection_must_prove_its_axis_is_live | DUP | MERGE→ | injection_zero_may_mean_the_guards_were_not_collected | mod: otel-export; mech: break-injection | round vs int совпали на 0 из 144; унести: показать изменение выхода ДО подсчёта |
| feedback_an_inventory_grep_needs_fixed_strings | RULE | MOVE-RULE | skill project-rules §1/§2 (одна строка: счёт имён только grep -F) | mech: grep, inventory | queue.evicted дал 3 вместо 0; точка = любой символ |
| feedback_attribute_the_source_before_cutting | LESSON | KEEP | local-only (два уровня .claude/ и ~/.claude/) | mech: context-audit | Резал не тот источник; экономия заявлена до прогона |
| feedback_backend_ctl_for_agents | RULE | MOVE-RULE | CLAUDE.md, раздел MCP routing, строка backend-ctl | mod: backend_ctl; mech: agents, live-stand | Директива владельца 2026-07-06 |
| feedback_backend_ctl_layer_mixed | RULE | MOVE-RULE | skill project-rules §4 или docs/claude/COMMIT_GUIDE.md | mod: backend_ctl; mech: commits | Allowlist validate_commit.py не знает tools (grep 0) |
| feedback_background_reviewer_loses_the_verdict | REDUNDANT | ARCHIVE | .claude/CLAUDE.md «Subagents are background by default» | mech: agents, review | правило уже записано там |
| feedback_barrier_at_entry_does_not_reproduce_the_race | LESSON | KEEP | - | mod: state_store_module (_make_room); mec… | Стенд зелёный 6/6 под собственной инъекцией |
| feedback_base_guard_dead_in_heir | LESSON | KEEP | - | mod: channel_routing_module (Logger/Error… | LoggerCore передаёт config=None: слепок пуст |
| feedback_baseline_taken_after_the_act_proves_nothing | LESSON | KEEP | - | mod: backend_ctl BuiltinCommands; mech: a… | commands_before снят после регистрации |
| feedback_bash_heredoc_collapses_backslashes | DUP | MERGE→ | bash_tool_unbalanced_quote_breaks_command | local-only (Windows Bash tool); mech: too… | Три раза 2026-09-29; тот же обход: Write/Edit |
| feedback_bash_tool_unbalanced_quote_breaks_command | LESSON | KEEP | - | local-only (Windows Bash tool); mech: too… | Дважды 2026-09-02; скрипты с прозой — через Write |
| feedback_born_wrong_then_fixed_looks_like_working | LESSON | KEEP | - | mod: stats_module, orchestrator L0; mech:… | StatsManager предупреждал о своём конфиге при верном yaml |
| feedback_broad_except_in_frame_loop_hides_dead_mechanism | LESSON | KEEP | - | mod: line_sim (SceneSourcePlugin), frame … | set_flow сбросил порог в None; лог — одна строка |
| feedback_broken_injection_is_not_a_vacuous_test | DUP | MERGE→ | injection_zero_may_mean_the_guards_were_not_collected | mech: break-injection | 0 красных читалось как вакуум; унести: считать ERROR |
| feedback_cache_hides_the_once_only_property | LESSON | KEEP | - | mod: logger_module (gate dedup); mech: te… | Три одинаковые записи; снятие дедупа не краснело |
| feedback_check_qex_freshness_before_use | REDUNDANT | ARCHIVE | root CLAUDE.md раздел qex + project-rules §1 + .claude/CLAUDE.md | mech: qex | Правило уже в 3 местах; убрать строку из индекса |
| feedback_check_red_on_main_first | RULE | MOVE-RULE | агент debugger + skill systematic-debugging | mech: debugging, git | G13 отклонён: stash-pop уходит в a_peer_session |
| feedback_checked_true_answers_for_the_call_not_the_coverage | DUP | MERGE→ | a_control_reproduces_the_defect_it_was_built_to_catch | mod: process_module (detect_throttle_caps… | continue на правиле без interval_sec; троттл резал в 40 раз |
| feedback_classify_a_leaf_by_the_difference_of_two_values | LESSON | KEEP | - | mod: process_module (expand_observability… | Одно значение путает «не читается» и «равно дефолту» |
| feedback_claude_cli_backend_costs_a_full_session | REDUNDANT | KEEP | - | mech: cost, graphify | на файл ссылается root CLAUDE.md; из индекса убрать |
| feedback_cleanup_must_survive_abnormal_disconnect | LESSON | KEEP | - | mod: backend_ctl (SocketChannel); mech: r… | 0 из 12 вежливых; RST воспроизвёл с 1-й попытки |
| feedback_coinciding_constants_hide_opposite_implementations | LESSON | KEEP | - | mod: state_store_module (throttle prune);… | floor(now/1.0)==now: 18 тестов зелёные под инъекцией |
| feedback_commit_msg_format | DUP | MERGE→ | commit_takes_the_whole_index | mech: git, pre-commit | Пункт 1 (trailer в одну строку) устарел: хук терпит перенос |
| feedback_commit_takes_the_whole_index | LESSON | KEEP | - | mech: git, pre-commit | 34 удаления D2 уехали в fix(store): D3 |
| feedback_compare_validated_values_not_raw_config | LESSON | KEEP | - | mod: config_module; mech: defaults-audit | Сырой YAML занижает счёт; S-26 |
| feedback_config_delivery_shape_differs | DUP | MERGE→ | fakes_feed_config_flat_so_key_address_defects_are_invisible | mod: process_module (spawner, process_run… | Тот же факт; унести: исправление read_process_config(svc,key) |
| feedback_config_reload_ttl_addressing_guard | LESSON | KEEP | - | mod: process_module (config.reload); mech… | низкая ценность: первый кандидат в архив при следующей чистке |
| feedback_config_update_dead_with_handler | LESSON | KEEP | - | mod: process_module (Config.update); mech… | Тест строил объект без config_handler |
| feedback_constant_from_domain_physics_not_measured | LESSON | KEEP | - | mod: telemetry histograms; mech: constant… | 99.28 % значений ниже выбранной границы |
| feedback_constructor_modularity | RULE | MERGE→ | framework_first | mech: architecture | Принцип владельца; в корневой CLAUDE.md одной строкой |
| feedback_coverage_holds_settrace_not_setprofile | LESSON | KEEP | - | mod: framework tests (_road_cost.py); mec… | _road_cost.py использует setprofile — живо |
| feedback_coverage_per_check_is_not_coverage_per_claim | DUP | MERGE→ | a_guard_that_counts_at_least_once_is_blind | mod: scripts/docs_verify; mech: guard-des… | F2-3: инъекции только у первого; унести: инъекция на утверждение |
| feedback_ctypes_setattr_unknown_field_is_silent | LESSON | KEEP | - | mod: Services/code_reader (ctypes); mech:… | Слепой тестер угадал nX/nY; нули прошли бы |
| feedback_deep_merge_is_not_associative | LESSON | KEEP | - | mod: config layers (deep_merge); mech: pr… | 20 000 троек: 239 расхождений |
| feedback_default_path_must_match_publisher | LESSON | KEEP | - | mod: alerts, Plugins/sources/capture; mec… | drops_count никто не публикует; 26 тестов зелёные |
| feedback_defect_fixed_on_one_path_only | LESSON | KEEP | - | mod: process_module (config.reload, telem… | Ревью 5.10: два воскресших дефекта |
| feedback_detector_comparing_representation_fires_always | LESSON | KEEP | - | mod: prototype backend/assembly (planner)… | Повторный apply той же топологии: protected_conflicts не пуст |
| feedback_diagnose_live_system_with_backend_ctl | DUP | MERGE→ | backend_ctl_for_agents | mod: backend_ctl; mech: live-stand | Тот же принцип; унести: system_overview+supervision_status+get_status за 3 вызова |
| feedback_dialog_conventions | RULE | MOVE-RULE | path-scoped .rules/gui.md | mod: frontend; mech: GUI conventions | Конвенция владельца 2026-07-13, RS-4 |
| feedback_dict_at_boundary_gui | REDUNDANT | ARCHIVE | .rules/gui.md и корневой CLAUDE.md правило 1 (Dict at Boundary) | mod: frontend | Правило уже в .rules/gui.md; git grep подтвердил |
| feedback_discriminator_switch_must_be_verified | LESSON | KEEP | - | mech: experiment-control, pytest testpaths | «Без Qt» прогон исполнил 2411 Qt-тестов |
| feedback_docs_assert_what_registration_never_set | LESSON | KEEP | - | mod: worker_module (heartbeat_sender, wor… | Флап unresponsive<->running каждые 5 с |
| feedback_double_must_block_like_the_original | DUP | MERGE→ | a_faithful_fake_still_lacks_the_protocol | mech: test-doubles | Мгновенный receive: инъекция дала разгон по памяти |
| feedback_drop_oldest_reports_success | LESSON | KEEP | - | mod: observability hub (BoundedChannel); … | Судить по приросту счётчика, не по статусу |
| feedback_dual_write_by_copy_destroys_the_other_side | RULE | MOVE-RULE | раздел Memory в .claude/CLAUDE.md + скрипт сверки diff перед записью | mech: memory, git | cp затёр 22 строки уникального; копии расходятся в обе стороны |
| feedback_duplicate_fixture_verifies_itself | LESSON | KEEP | - | mod: backend_ctl tests (conftest); mech: … | Три счётчика в conftest, копия осталась прежней |
| feedback_emergency_log_reaches_stderr_not_the_log_files | LESSON | KEEP | - | mod: logger_module (_fallback); mech: voi… | 0 строк в файле против 2 у FallbackLogger |
| feedback_env_knob_reads_its_own_write | LESSON | KEEP | - | mod: prototype build(); mech: env-config | Второй build() принял свой setdefault за волю оператора |
| feedback_explicit_model_per_agent_role | RULE | MOVE-RULE | skill project-rules §5 + одна строка в .claude/CLAUDE.md | mech: agents, models | Журнал не пишет модель; ревью ушло не на Opus |
| feedback_facade_is_a_whitelist_not_a_passthrough | LESSON | KEEP | - | mod: process_module (observability_config… | log_line_max_bytes: тест зелёный, из конфига не управляется |
| feedback_fake_that_always_succeeds_mutes_the_gate | DUP | MERGE→ | a_faithful_fake_still_lacks_the_protocol | mod: queue_registry; mech: test-doubles | Инъекция I-12: 0 красных вместо 1 |
| feedback_fakes_feed_config_flat_so_key_address_defects_are_invisible | LESSON | KEEP | - | mod: process_module config; mech: test-do… | Класс «ключ по неверному адресу» тестам невидим |
| feedback_false_alarm_traded_for_silent_loss | LESSON | KEEP | - | mod: observability (sink.disable, config.… | config.reload поднял снятый канал: все классы потерь = 0 |
| feedback_fewer_layers | RULE | MERGE→ | framework_first | mech: architecture | Принцип владельца 2026-06-05 |
| feedback_fix_framework_forward | RULE | MERGE→ | framework_first | mech: architecture | Принцип владельца 2026-06-04 |
| feedback_flags_must_not_become_crutches | RULE | MOVE-RULE | команда /dev:ship + шаблон Task (критерий «флаг удалён») | mech: feature-flags | Владелец 2026-07-22; реестр уже 18 флагов |
| feedback_formal_review_before_merge | RULE | MOVE-RULE | команда /dev:ship (проверка артефакта /code-review) | mech: review, git | Классификатор блокирует merge без артефактов ревью |
| feedback_framework_first | RULE | MOVE-RULE | root CLAUDE.md «Принципы владельца» (5 строк) | mech: architecture | слияние 5 принципов; после переноса файл = заглушка |
| feedback_freeze_over_kill | RULE | MERGE→ | framework_first | mech: architecture, dead-code | Прецеденты actions_module, GATE G2 форм |
| feedback_gate_criterion_can_contradict_an_owner_decision | LESSON | KEEP | - | mod: telemetry gate; mech: acceptance | Ф6: 6 из 16 пунктов; два — критерий против решения |
| feedback_gate_off_zeroes_deltas_not_messages | LESSON | KEEP | - | mod: state_store/telemetry (publisher gat… | status идёт мимо гейта; мерить state.changed |
| feedback_gate_signature_lives_on_a_head | RULE | MOVE-RULE | команда /dev:ship + агент cto (приёмка гоняет гейт сама) | mech: gates, acceptance | 21 красный сутки на HEAD после 6 хвостовых коммитов |
| feedback_git_main_merge_hook_traps | RULE | MOVE-RULE | единый формат merge -> docs/claude/COMMIT_GUIDE.md и корневой CLAUDE.… | mech: git, hooks, merge | Решение владельца 2026-10-03; два вида содержимого в одном файле |
| feedback_git_stash_pop_wrong_stash | DUP | MERGE→ | a_peer_session_shares_the_tree | mech: git | Тот же приём; унести: stash@{0} — не «мой» |
| feedback_global_clock_patch_flake | LESSON | KEEP | - | mod: state_store_module (throttle tests);… | Чужие потоки доедают список: StopIteration в чужом тесте |
| feedback_green_run_hides_synchronous_only_correctness | LESSON | KEEP | - | mod: router_module (_log_debug); mech: la… | 30 тестов и 6950 гейт зелёные; мину нашёл линтер |
| feedback_guard_must_be_reachable | LESSON | KEEP | - | mod: plugin_module (PluginContext.write_d… | kind как обычный параметр: запись теряется исключением |
| feedback_guard_on_existence_is_not_a_guard_on_content | DUP | MERGE→ | zone_guard_never_closes_the_class | mod: pytest testpaths; mech: guard-design | Пустой каталог после carve-out: ложь о покрытии три месяца |
| feedback_guard_threshold_hides_partial_blindness | DUP | MERGE→ | a_guard_that_counts_at_least_once_is_blind | mod: tests (thread deadlines); mech: guar… | Инъекция и-3; унести: проверять каждую запись списка отдельно |
| feedback_gui_save_strips_yaml_comments | LESSON | KEEP | - | mod: frontend settings (yaml_io.py); mech… | yaml.safe_dump(model_dump) на yaml_io.py:58 |
| feedback_hot_path_hook_must_be_priced | LESSON | KEEP | - | mod: logger_module (redaction); mech: per… | +5.64 мкс при цене 4.04 мкс — удвоил log() |
| feedback_idempotent_is_not_monotonic | LESSON | KEEP | - | mod: process_module (fan-out delivery); m… | Отложенная досылка перекрыла свежий конверт |
| feedback_inject_only_after_the_work_is_committed | LESSON | KEEP | - | mech: break-injection harness, git | Три файла вернулись к HEAD до базового прогона |
| feedback_inject_the_call_site_not_only_the_helper | LESSON | KEEP | - | mod: process_module (process_monitor); me… | 0 красных из 4297 |
| feedback_injection_base_needs_a_collected_count | DUP | MERGE→ | injection_zero_may_mean_the_guards_were_not_collected | mech: break-injection | Уже целиком внутри выжившего; уникального нет |
| feedback_injection_generator_must_differ_from_criteria_author | LESSON | KEEP | - | mech: break-injection, independence | Список критериев со знаком минус; нужен род «нуль/тотал» |
| feedback_injection_green_when_the_substitute_equals_the_fact | LESSON | KEEP | - | mod: process_module (voice class); mech: … | 0 красных при 11 зелёных: константа = факт |
| feedback_injection_must_cover_all_check_sites | LESSON | KEEP | - | mod: still_relevant ready-gate; mech: bre… | Дважды: 1 точка из 3 — 18 passed; полная — красные |
| feedback_injection_must_reproduce_the_mechanism_not_the_shape | LESSON | KEEP | - | mod: plugin_module (write_document); mech… | Позиционный-only параметр: 0 на 146 (PEP 570) |
| feedback_injection_must_use_a_different_lens_than_the_test | LESSON | KEEP | - | mod: telemetry; mech: break-injection, in… | Красный доказывает согласие двух копий одной модели |
| feedback_injection_prediction_on_a_shared_corpus | LESSON | KEEP | - | mech: break-injection, prediction | Равенство множеств тонет в шуме чужих тестов |
| feedback_injection_rollback_by_restore_not_replace | DUP | MERGE→ | inject_only_after_the_work_is_committed | mech: break-injection harness | str.replace задел соседнее поле; 7 красных нашёл полный гейт |
| feedback_injection_too_coarse_proves_nothing_specific | LESSON | KEEP | - | mod: state_store (throttle); mech: break-… | Предсказан 1 красный, получено 9, причина другая |
| feedback_injection_zero_may_mean_the_guards_were_not_collected | LESSON | KEEP | - | mech: break-injection, harness | 16, 2, 1 вместо 1, 0, 0; collected 0 вместо 563 |
| feedback_logger_error_stats_managers | RULE | POINTER | root CLAUDE.md правило 6 + .rules/logging.md | mod: logger_module, error_module, statist… | правило уже есть; сверить .rules/logging.md со stdlib-миграцией |
| feedback_materialized_agents_drift_from_plugin_source | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Standing rules» (абзац History) | mech: materialized-mirror | тот же факт и правило уже в `.claude/CLAUDE.md` |
| feedback_materialized_default_hides_absence | LESSON | KEEP | — | mod: config_module; mech: schema-defaults | ErrorManager manager_name B3, вход→выход есть |
| feedback_mcp_tool_api_drift | STALE | ARCHIVE | - | mech: mcp-routing | пример про codegraph, которого нет в .mcp.json |
| feedback_measure_delta_not_file_size | LESSON | KEEP | — | mech: measurement | замер 9 МБ vs дельта, 2026-08-03 |
| feedback_merge_changes_the_form | LESSON | KEEP | — | mod: config_module/recipe; mech: config-f… | воспроизведённый дефект observability.persist |
| feedback_mirror_check_never_reads_the_original | LESSON | KEEP | — | mod: recipe/blueprint; mech: drift-guard | `_pick`-ключи не покраснели в Ф7 G.4.b |
| feedback_modal_dialog_waits_instead_of_failing | LESSON | KEEP | — | mod: frontend_module; mech: qt-tests | три виновных теста, владелец жал ОК |
| feedback_model_copy_does_not_validate | LESSON | KEEP | см. группу G-pydantic | mod: data_schema_module; mech: pydantic-v2 | два случая Ф2.2/2.3a, потребитель получает None |
| feedback_model_economy_scheme | STALE | ARCHIVE | .claude/CLAUDE.md «Roles → models» | mech: model-selection | схема на 2026-07-14 устарела |
| feedback_model_split_impl_vs_review | DUP | MERGE→ | explicit_model_per_agent_role | mech: model-selection | ростер моделей по ролям уже в `.claude/CLAUDE.md` |
| feedback_mp_queue_is_async_in_tests | LESSON | KEEP | — | mod: shared_resources_module/queues; mech… | 164/178 вместо 200 на том же коде |
| feedback_mvp_pattern | RULE | POINTER | .rules/gui.md:17 (правило уже есть) | mod: frontend_module | git grep: полный MVP в .rules/gui.md |
| feedback_named_main_cause_may_be_a_minor_share | LESSON | KEEP | — | mech: measurement | таблица замера logs_live, гейт недостижим |
| feedback_named_mechanism_is_not_a_commitment | LESSON | KEEP | — | mech: spec-review | 3 из 6 задач Ф4 закрылись другим механизмом |
| feedback_negative_criterion_needs_an_existence_anchor | LESSON | KEEP | — | mech: tester-brief | тестер переводит «листа нет» в вакуумный assert |
| feedback_no_global_taskkill | RULE | MOVE-RULE | .claude/settings.json permissions.deny (РЕШЕНИЕ ВЛАДЕЛЬЦА) | mech: process-kill | deny на taskkill/pkill/killall: git grep 0 |
| feedback_no_qt_popups_offscreen | RULE | MOVE-RULE | conftest корня тестов (setdefault QT_QPA_PLATFORM=offscreen); РЕШЕНИЕ… | mod: frontend_module; mech: qt-tests | settings.json env сломал бы живой стенд с настоящими окнами |
| feedback_no_regression_proved_by_identical_build | LESSON | KEEP | — | mech: acceptance-proof | D8: шумные живые прогоны не различают регресс |
| feedback_no_shm_hacks | RULE | POINTER | .rules/plugins.md:15 (правило уже есть) | mod: Plugins; mech: layering | git grep: ЗАПРЕЩЕНО читать SHM напрямую |
| feedback_numba_without_boundscheck_turns_a_broken_invariant_into_ub | LESSON | KEEP | — | mod: Plugins (trace_skeleton); mech: brea… | 29 красных в Python vs 104 зелёных в numba |
| feedback_observability_knobs_switchable_at_any_boundary_zero_cost_off | RULE | MOVE-RULE | `docs/direction/` или DECISIONS модуля observability + строка в `proj… | mod: observability; mech: knobs | стоячая планка владельца 2026-09-08; Task 4.15 ещё впереди |
| feedback_one_active_plan_per_tool | RULE | MOVE-RULE | `.claude/CLAUDE.md` «Plan-Driven Development» (одна строка) | mech: planning | семь файлов backend_ctl дали воскрешение отменённой задачи |
| feedback_one_control_proves_sufficiency_not_exclusivity | LESSON | KEEP | — | mech: controls | layer-render 6.4: 6.78° vs сетка 2×2 20.4°/42.2° |
| feedback_one_door_two_roads_needs_two_guards | DUP | MERGE→ | property_unchecked_at_the_second_party | mod: config_module; mech: config.reload | тот же класс «проверено на одном call-site»; унести пример hub_stats |
| feedback_one_function_two_positions | LESSON | KEEP | — | mod: channel_routing_module (levels.py); … | `level_rank` Ф3.1; код `levels.py` это подтверждает |
| feedback_one_log_writer | RULE | MOVE-RULE | `channel_routing_module/DECISIONS.md` + `logger_module` ADR (проверит… | mod: logger_module; mech: architecture | решение владельца 2026-07-27; в DECISIONS уже ссылаются на правило |
| feedback_one_owner_blinds_the_shared_state_test | LESSON | KEEP | — | mech: test-resolution | рефактор «под одного владельца» обнуляет разрешающую способность |
| feedback_package_install_by_user | REDUNDANT | ARCHIVE | .claude/settings.json ask: pip install, uv pip install, uv add | mech: deps | R2 писал deny, на деле ask; python -m pip install не закрыт |
| feedback_parallel_agents_commit_race | STALE | MERGE→ | precommit_stash_collision_2plus_agents | mech: parallel-commits | хук `pre-commit-session-log` снят; правило «один worktree на писателя» в `.claude/CLAUDE.… |
| feedback_parametrization_built_from_the_subject_collapses_with_it | DUP | MERGE→ | a_guard_that_counts_at_least_once_is_blind | mech: break-injection | 59→47 случаев, пороги ≥25/≥8 пройдены |
| feedback_pipeline_reuse_plugins_widgets | RULE | MOVE-RULE | `.rules/` (путь `frontend/.../pipeline/`) | mod: frontend_module (pipeline); mech: DRY | директива владельца 2026-05-30; нужна при правке pipeline |
| feedback_plan_checkboxes | RULE | MOVE-RULE | команда `/dev:implement` / `/dev:ship` (шаг «отметить [x] + hash») | mech: plan-driven | процесс; `/dev:ship` уже сверяет Refs |
| feedback_plan_dual_save | REDUNDANT | ARCHIVE | `.claude/commands/dev/plan.md`, CLAUDE.md «Plan-Driven Development» | mech: plan-driven | то же самое сказано в команде `/dev:plan` и CLAUDE.md |
| feedback_plan_spec_can_lie | DUP | MERGE→ | the_plans_stated_cause_is_a_hypothesis | mech: spec-review | `manual_restarts` → `instance_restarts`; уникум: пример |
| feedback_plausible_is_not_verified | LESSON | KEEP | — | mech: verification | четыре ошибки одного происхождения; правило «honesty» уже в `project-rules` |
| feedback_port_wire_is_not_a_process_route | LESSON | KEEP | — | mod: chain_module/recipe; mech: wiring | Ф8.7: `chain_targets` без `processor`, плагин не вызван |
| feedback_positional_call_hides_parameter_name_drift | LESSON | KEEP | — | mod: Plugins (SubPluginContext); mech: st… | `duration=` → TypeError у заглушки |
| feedback_post_publication_mark_breaks_collapsing | LESSON | KEEP | — | mod: observability (ObservabilityAudit); … | Ф8.5, воспроизведено ревьюером |
| feedback_precommit_rollback_drops_unstaged_edits | DUP | MERGE→ | commit_takes_the_whole_index | mech: pre-commit | один писатель + ruff format: тот же механизм патч-стеша |
| feedback_precommit_stash_collision_2plus_agents | LESSON | KEEP | — | mech: pre-commit, parallel-commits | независимо воспроизведено двумя агентами 2026-07-20 |
| feedback_predict_injections_after_writing_tests | RULE | MOVE-RULE | `.claude/CLAUDE.md`, bullet «Break-injection is the proof» (+ одна фр… | mech: break-injection | 3 из 7 инъекций разошлись; уточнение к правилу |
| feedback_priority_belongs_to_the_receiver | LESSON | KEEP | — | mod: telemetry/config layers; mech: repla… | last-write-wins приёмник, 2026-08-16 |
| feedback_probe_liveness_is_not_render | LESSON | KEEP | G-qtmcp | mod: frontend_module; mech: qt-mcp | `Widgets: 0`, `skip_hidden` по умолчанию |
| feedback_process_counter_is_not_per_key | LESSON | KEEP | — | mod: observability; mech: measurement | 2000 записей, ожидали 1992 подавлено — фон |
| feedback_property_unchecked_at_the_second_party | LESSON | KEEP | — | mech: break-injection, call-sites | дважды в 3.4 telemetry-stage6, ноль погибших |
| feedback_protect_branch_blocks_worktree_subagents | DUP | MOVE-RULE | project-rules §5 + .claude/plugins/dev/templates/team-brief.md | mech: protect-branch hook | другой триггер, чем merge в main: слияние отклонено |
| feedback_protect_the_unit_of_contention | LESSON | KEEP | — | mod: logger_module (FileChannel); mech: b… | Ф7.2: лок канала, делят хэндлер |
| feedback_prototype_the_guard_before_fixing_its_wording | LESSON | KEEP | — | mech: spec-review, guards | 1.3c: 3 функции/4 адреса красных |
| feedback_prove_test_red_without_fix | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Break-injection is the proof» | mech: break-injection | дословно то же правило в `.claude/CLAUDE.md` |
| feedback_pydantic_assignment_keeps_rejected_value | LESSON | MERGE→ | model_copy_does_not_validate | mod: data_schema_module, config_module; m… | `max_export_batch_size=20480` остался после ValidationError |
| feedback_pytest_import_order_hides_a_cycle | LESSON | KEEP | — | mech: import-cycles | layer-render 2.4a: 14 красных точечно, цикл виден только в `import X` |
| feedback_pytest_owns_threading_excepthook_for_the_session | LESSON | KEEP | — | mech: pytest-internals | pytest 9.x `threadexception.py`; якорь приёмки недостижим |
| feedback_qex_full_rebuild_runbook | REFERENCE | KEEP | `.claude/plugins/mcp-qex/` команда | mod: qex; mech: runbook | пошаговый порядок, первый прогон убит на 94 % |
| feedback_qex_query_english_code_bias | REDUNDANT | ARCHIVE | корневой `CLAUDE.md` раздел «MCP: qex» | mech: qex | дословно в корневом `CLAUDE.md` |
| feedback_qex_reindex_budget | STALE | MERGE→ | qex_full_rebuild_runbook | mech: qex, VRAM | написано под 4b, теперь 0.6b; унести только keep_alive и число 47 с |
| feedback_qt_mcp_always_probe | DUP | MERGE→ | qt_mcp_flag_value_is_compared_verbatim | mod: frontend_module; mech: qt-mcp | та же ручка; унести строку запуска `run.py` |
| feedback_qt_mcp_flag_value_is_compared_verbatim | LESSON | KEEP | — | mech: qt-mcp, env-flags | рендер GUI не проверялся три раунда |
| feedback_qt_mcp_smoke_verification | RULE | MOVE-RULE | `.rules/` путь `frontend/` + шаг в `/dev:implement` чек-листе | mod: frontend_module; mech: smoke | pytest-qt с mock ctx не доказывает реальную сборку |
| feedback_read_the_key_from_the_section_already_travelling | DUP | MERGE→ | recipe_knob_must_be_named_in_from_recipe | mod: recipe/blueprint; mech: config-deliv… | два BlueprintAssembler: boot и switch |
| feedback_read_timestamp_is_not_data_freshness | LESSON | KEEP | — | mod: telemetry; mech: freshness | замерший датчик + свежий `snapshot_ts`, Task 3.2 |
| feedback_ready_signal_meant_less_than_read | LESSON | KEEP | — | mod: process_module; mech: readiness | команда в окне читается и выбрасывается |
| feedback_recipe_knob_must_be_named_in_from_recipe | LESSON | KEEP | — | mod: recipe, process_module; mech: config… | `_pick` + `extra=ignore` |
| feedback_red_tests_manufacture_the_appearance_of_new_diagnostics | LESSON | KEEP | — | mech: measurement, pytest | closure Task 3.2, `idle_sinks` |
| feedback_refusal_after_the_write_poisons_the_neighbour | LESSON | KEEP | — | mod: telemetry/config layers; mech: layer… | ключ живёт 300 с, следующий reload падает |
| feedback_register_routing_hang | LESSON | KEEP | - | mod: frontend_module/registers; mech: Fie… | проверить fail-fast в FrontendRegistersBridge до решения |
| feedback_removal_leaves_a_tail_in_the_neighbour | LESSON | KEEP | — | mod: logger_module; mech: deletion-refact… | Ф2.6: каждый CRITICAL чистил карты решений |
| feedback_removing_waste_reddens_tests_that_measured_it | LESSON | KEEP | — | mech: test-resolution | 20 конвертов → 1; один тест зелёный на несуществующем свойстве |
| feedback_review_economy_tiers | STALE | ARCHIVE | .claude/CLAUDE.md «Task launch convention» | mech: review | вытеснено решением 2026-08-13 |
| feedback_review_finds_the_seam_between_own_pieces | DUP | MERGE→ | three_lenses_three_defect_classes | mech: review | то же утверждение «ревью — связки»; унести пример 5.11 d+f |
| feedback_row_count_never_catches_the_loop | LESSON | KEEP | — | mod: telemetry; mech: feedback-loop | строки 1,2,3,4,5 — рост без геометрии, ADR утверждал обратное |
| feedback_ru_output_encoding_and_wc | REFERENCE | KEEP | — | mech: encoding | подтвердилось в этом аудите: UnicodeEncodeError cp1251 |
| feedback_ruff_strips_unused_import | LESSON | KEEP | — | mech: PostToolUse formatter hook | PostToolUse ruff --fix удаляет «неиспользуемый» импорт |
| feedback_runtime_config_dies_with_the_process | LESSON | KEEP | — | mod: config_module (config.reload); mech:… | 1972 Б при count=392 в обеих строках |
| feedback_safeguard_can_be_a_noop_with_green_units | LESSON | KEEP | — | mod: backend_ctl (harness.strip_gui); mec… | D8: пять зелёных юнитов, strip_gui ничего не резал |
| feedback_scripted_patch_needs_a_unique_anchor | LESSON | KEEP | — | mech: break-injection tooling | якорь дважды, заплата ушла в соседнюю фикстуру |
| feedback_seam_must_fire_on_full_release | DUP | MERGE→ | test_survived_its_own_break | mech: break-injection, RLock | тот же класс «тест пережил слом»; унести признак 5.43 с vs 0.36 с |
| feedback_second_consumer_reveals_the_defect | LESSON | KEEP | — | mod: logger_module; mech: singleton lifec… | `LoggerManager._instance` пережил shutdown, Ф6.8 |
| feedback_sentrux_depth_opaque | REFERENCE | KEEP | — | mod: sentrux | замер 2026-07-10: depth=6 при удалении 7-уровневого пакета |
| feedback_sentrux_gate_narrowed | REDUNDANT | ARCHIVE | `scripts/hooks/pre-push` (git-tracked), `.claude/plugins/mcp-sentrux/… | mod: sentrux | хук в git — источник истины; файл на него сам ссылается |
| feedback_shared_tree_makes_injections_look_like_flakes | DUP | MERGE→ | a_peer_session_shares_the_tree | mech: shared-tree, break-injection | `restore` затёр правку агента; унести оба ложных факта |
| feedback_side_effect_must_not_undo_the_transaction | LESSON | KEEP | — | mod: recipe/orchestrator (switch); mech: … | 5.11: чтение адреса рецепта откатывало успешный switch |
| feedback_signal_placed_in_a_branch_goes_blind | LESSON | KEEP | — | mod: logger_module; mech: detector-placem… | Ф2.4: `_scope_schema` не вызывается при правиле имени |
| feedback_silent_detector_proves_nothing | DUP | MERGE→ | zero_observations_looks_like_a_result | mech: detectors | 5.11-R4: `No handler for key` дал ложный ноль дважды; унести оба случая |
| feedback_single_marker_verdict_lies | LESSON | KEEP | — | mod: backend_ctl (process_restart_verifie… | pid сменился, но процесс умер; pid переиспользован ОС |
| feedback_single_reader_test_misses_multi_reader_defect | LESSON | KEEP | — | mod: observability readback; mech: shared… | 15 тестов и зонд 7/7 зелёные, два читателя портят друг друга |
| feedback_spawn_child_inherits_parent_sys_path | LESSON | KEEP | — | mod: process_module (SystemLauncher/Backe… | измерено line-sim Task 1.1, 2026-09-20 |
| feedback_spec_review_needs_independent_agent | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Task launch convention», стадия 0 | mech: spec-review | правило стадии 0 уже закреплено; пример 5.13 остаётся в плане |
| feedback_sqlite_pragma_fails_silently | LESSON | KEEP | — | mod: Services/sql, observability store; m… | Ф5.2: auto_vacuum читается как 0 после WAL |
| feedback_stepwise_statement_needs_draining | DUP | MERGE→ | sqlite_pragma_fails_silently | mod: Services/sql; mech: sqlite | таблица форм вызова 2116 → 2115; унести её |
| feedback_subagent_live_test_monitor_hang | DUP | MOVE-RULE | project-rules §5 (одна строка: live-тест синхронно; 2-я заминка — лид… | mech: subagent-sync | в архивный survivor вливать нельзя |
| feedback_substring_assert_passes_on_the_wrong_branch | LESSON | KEEP | — | mod: observability; mech: test-assert | `documents` есть в тексте обеих веток, Task 4.2 |
| feedback_suffix_rename_is_a_blind_injection | LESSON | KEEP | — | mech: break-injection tooling | S-29, `_get_protected_names`; подстрочные проверки не краснеют |
| feedback_swallowed_failure_class | LESSON | KEEP | — | mod: process_module/middleware; mech: swa… | четыре экземпляра за один день 2026-07-21 |
| feedback_switching_off_a_writer_promotes_its_placeholder_to_a_claim | LESSON | KEEP | — | mod: telemetry; mech: placeholders | РТ-2, `logs_live/rt2_blocker1` |
| feedback_symmetric_names_with_different_periods | LESSON | KEEP | — | mod: telemetry (get_stats); mech: naming | `window_series_dropped` 4 → flush → 0 |
| feedback_tab_order | RULE | POINTER | .rules/gui.md:27 (правило уже есть) | mod: frontend_module | git grep: Tab order в .rules/gui.md |
| feedback_test_authorship_three_roles | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Test authorship» | mech: test-authorship | таблица дословно в `.claude/CLAUDE.md` |
| feedback_test_params_hide_defect_window | LESSON | KEEP | — | mech: test-params | два HIGH ревью 2026-07-10 под зелёными тестами |
| feedback_test_raising_the_error_itself_guards_the_branch | LESSON | KEEP | — | mod: code_version; mech: test-mechanism | `code_version()` timeout=5, найдено Fable |
| feedback_test_reddens_only_under_a_paired_injection | LESSON | KEEP | — | mech: break-injection | как отличить — сломать пару |
| feedback_test_setting_one_handle_of_a_pair_measures_priority | DUP | MERGE→ | test_params_hide_defect_window | mod: config_module; mech: legacy-alias | D4: MULTIPROCESS_LOG_DIR и алиас; унести пример |
| feedback_test_survived_its_own_break | LESSON | KEEP | — | mech: break-injection, concurrency | Task 5.8: окно гонки два байткода, переключение раз в 5 мс |
| feedback_test_values_near_defaults_test_the_default | DUP | MERGE→ | test_params_hide_defect_window | mod: logger_module; mech: test-params | 0.25 ≥ 0.25; после разведения 2/2 |
| feedback_tester_always_and_inject_against_it | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Independent tester — on every task» | mech: test-authorship | решение 2026-08-13 переписано в `.claude/CLAUDE.md` дословно |
| feedback_tester_blindness_needs_a_worktree | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Blindness is enforced by the worktree» | mech: tester | тот же абзац и те же две утечки в `.claude/CLAUDE.md` |
| feedback_tester_once_per_mechanism_before_the_code | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Stage 1 refined 2026-08-20» | mech: tester | число 479k/16 мин уже в `.claude/CLAUDE.md` |
| feedback_tests_invisible_to_testpaths | DUP | MERGE→ | zone_guard_never_closes_the_class | mod: framework tests (pytest.ini); mech: … | первый случай серии; унести 5361 passed и имена каталогов |
| feedback_the_off_half_of_a_pair_can_be_done_by_a_timer | LESSON | KEEP | — | mod: backend_ctl, config L3 TTL; mech: ON… | success=true подтверждает доставку, не эффект |
| feedback_the_plans_stated_cause_is_a_hypothesis | LESSON | KEEP | — | mod: process_manager; mech: spec-review | closure 1.2: две дороги вместо «пишет раньше регистрации» |
| feedback_the_sentence_is_wider_than_the_command_it_quotes | LESSON | KEEP | — | mech: report-honesty | `61bb7496` +34 строки CONNECTORS.md, otel Ф0 |
| feedback_think_en_speak_ru | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Language policy» | mech: language | политика языка уже в `.claude/CLAUDE.md` (internal reasoning any language) |
| feedback_thread_target_pins_its_owner | LESSON | KEEP | — | mod: state_store_module, app_module; mech… | 23 теста, access violation гейта ушёл 5/5 |
| feedback_three_lenses_three_defect_classes | LESSON | KEEP | — | mech: test/live/review | 5.12: 6368 зелёных пропустили обе живые находки |
| feedback_three_managers_share_base | DUP | MERGE→ | logger_error_stats_managers | mod: channel_routing_module, base_manager… | то же решение владельца; унести факт иерархии 2026-07-26 |
| feedback_tool_features_before_validation | LESSON | KEEP | — | mod: backend_ctl; mech: scope-discipline | ultra-ревью 4.5/10, 844 строки тестов потеряны |
| feedback_transitive_gui_backend_in_tests | LESSON | KEEP | - | mech: qt-in-tests | низкая ценность: мина не взорвалась |
| feedback_transport_arbitrates_what_it_cannot_understand | LESSON | KEEP | — | mod: telemetry (ThrottleMiddleware); mech… | воспроизведено вход→выход, proceed=true без rejection_reason |
| feedback_two_green_gates_can_hide_a_red_pair | LESSON | KEEP | — | mod: framework tests (declarations); mech… | `forget_declarations("metric", {"fps"})` ломает каталог |
| feedback_two_patches_one_red_set_means_one_assert | LESSON | KEEP | — | mech: break-injection | матрица Task 3.0a, S3 и S4 |
| feedback_two_safeguards_hide_which_one_holds | DUP | MERGE→ | test_reddens_only_under_a_paired_injection | mod: observability (frame trace); mech: b… | Ф7.5: 0 красных вместо 1; унести пример sampling_max_level |
| feedback_two_tests_enter_from_both_sides_and_miss_the_connector | LESSON | KEEP | — | mod: observation_port; mech: connector-te… | Ф3/3.2: записи порта не доехали до стора |
| feedback_unblocking_signal_at_the_moment_of_fact | LESSON | KEEP | — | mod: process_manager (stop_many); mech: l… | 13 тестов зелёные, живой SIGKILL gui = 5.7 с как до правки |
| feedback_unconnected_driver_reads_as_a_clean_zero | LESSON | KEEP | — | mod: backend_ctl driver; mech: measurement | delta=0 в приёмке 3.3 неотличима от «трафика нет» |
| feedback_unkillable_fix_needs_a_hand_set_state | LESSON | KEEP | — | mod: observation_port; mech: white-box pin | Ф0 Task 0.2, правка 3 |
| feedback_unparsed_is_not_absent | LESSON | KEEP | — | mod: scripts/sync, validate.py; mech: sil… | `## ADR-DS-009 (S-27)` не сматчился, validate зелёный |
| feedback_unused_paths_are_contracts | RULE | MOVE-RULE | agent `reviewer` (чек-лист) + `project-rules` | mech: review | решение владельца 2026-07-13; должно срабатывать в ревью |
| feedback_upper_layer_default_disables_the_guard_below | LESSON | KEEP | — | mod: logger_module (log_paths); mech: def… | три точки подставляют `Path("logs")` вместо temp |
| feedback_use_graph_semantic_tools | REDUNDANT | ARCHIVE | корневой `CLAUDE.md` «qex-first / sentrux-first» | mech: mcp-routing | правило уже в корневом `CLAUDE.md`; codegraph не подключён |
| feedback_uv_sync_prunes_venv | RULE | MOVE-RULE | .claude/settings.json permissions.ask uv sync* (РЕШЕНИЕ ВЛАДЕЛЬЦА) + … | mech: env, local-only | ask на uv sync: нет; есть только uv add/pip install |
| feedback_walk_skips_worktrees | LESSON | KEEP | — | mech: worktrees, bulk-replace | os.walk залез в полные чекауты чужих агентов |
| feedback_wallclock_threshold_measures_the_heap | LESSON | KEEP | — | mod: state_store_module; mech: flaky-tests | 113.2 и 158.5 мс против 100 в общем гейте |
| feedback_widget_qt_patterns | LESSON | KEEP | `.rules/gui.md` | mod: frontend_module; mech: QTreeWidget | рекурсия, exitcode 0xC000001D на Windows |
| feedback_worktree_for_parallel_samefile | DUP | MERGE→ | a_peer_session_shares_the_tree | mech: worktrees | `git checkout -b` утащил бы чужую работу; унести пример driver.py |
| feedback_worktree_stale_base | LESSON | KEEP | — | mech: worktrees | волна 2026-07-11: два из трёх на `a50d1f74` |
| feedback_zero_mentions_criterion_erases_the_reason | LESSON | KEEP | — | mech: acceptance-criteria | ADR о снятом механизме обязан называть его |
| feedback_zero_observations_looks_like_a_result | LESSON | KEEP | — | mech: detectors, measurement | трижды за день 2026-08-23, включая два мёртвых агента |
| feedback_zero_reds_can_mean_a_useless_layer | DUP | MERGE→ | injection_zero_may_mean_the_guards_were_not_collected | mech: break-injection | Ф2.7: сравнение уже в Pydantic `__eq__`; добавить как четвёртое чтение |
| feedback_zone_guard_never_closes_the_class | LESSON | KEEP | — | mod: framework tests; mech: testpaths | 4.0: 114 файлов, 1464 теста, четыре красных |
| handoff_sources_widget_refactor | STALE | ARCHIVE | git; docs/refactors/2026-04_widgets_reorg.md | frontend/sources | git grep SourcesTabWidget = 0 |
| project_all_process_autorestart | STATE | ARCHIVE | ADR-PMM-015 в process_manager_module/DECISIONS.md; флаг FW_AUTORESTAR… | process_manager | механизм исполнен 8ac43361, факт в ADR |
| project_app_module_windows_test_debt | STATE | KEEP | - | app_module; windows | local-only; перепроверить, красны ли 2 теста сейчас |
| project_arch_boundaries_plan | REDUNDANT | ARCHIVE | plans/2026-07-06_constructor-master/plan.md (Ф5-добор C1-C8); ADR-RCP… | recipe | решение уже в плане и ADR |
| project_archives_removed | REDUNDANT | ARCHIVE | корневой CLAUDE.md, раздел "История версий" | repo | CLAUDE.md говорит то же |
| project_backend_control_mcp | STALE | ARCHIVE | plans/_archive/2026-05-31_backend-control-mcp | backend_ctl | "Следующее: P3" давно сделано, план в _archive |
| project_backend_ctl_d1_session_isolation | STATE | ARCHIVE | plans/_archive/2026-07-19_backend-ctl-d1-session-isolation.md | backend_ctl; router | план в _archive |
| project_backend_ctl_framework_module | STATE | ARCHIVE | plans/_archive/2026-07-21_backend-ctl-framework-module.md | backend_ctl | план в _archive |
| project_backend_ctl_gaps_2026_07 | STALE | ARCHIVE | коммиты 857ed851, 6b9d4e1f | backend_ctl | пункты 1-2 помечены закрытыми |
| project_backend_ctl_missing_contract | LESSON | MERGE→ | project_backend_ctl_signal_integrity | backend_ctl; mechanism: missing-vs-zero | тот же класс болезни |
| project_backend_ctl_recorder_kept | STATE | ARCHIVE | backend_ctl/DECISIONS.md:191 (вердикт 2026-07-22) | backend_ctl | вердикт уже в ADR; decisions.md ведёт только открытые |
| project_backend_ctl_signal_integrity | LESSON | KEEP | - | backend_ctl; mechanism: false-signal | три дефекта = одна болезнь, коммиты в таблице |
| project_backend_ctl_socket_bypasses_mw | LESSON | KEEP | - | backend_ctl; router_module; mechanism: re… | fence проверять только через peer-канал |
| project_backend_ctl_ultra_review | STATE | ARCHIVE | plans/_archive/2026-07-20_backend-ctl-hardening.md | backend_ctl | файл сам говорит "закрыты" |
| project_calibration_gui_progress | LESSON | KEEP | - | gui_process; state_store; mechanism: stat… | есть тест test_gui_process::test_subscriptions_* |
| project_camera_settings_feature | STATE | ARCHIVE | код Services/camera_service | camera_service | "uncommitted, 5 фаз" 2026-06; код — источник |
| project_claude_kit_migration | REFERENCE | MERGE→ | project_devseed_overwrites_claude_dir | claude-kit | пути /Users/twokrai (Mac); пересекается |
| project_comm_system_p0 | STATE | ARCHIVE | plans/_archive/comm-system-*.md | router; message_module | план в _archive |
| project_command_bus_p4_4 | STATE | ARCHIVE | plans/_archive/2026-05-31_transport-router-hub | command_manager | план в _archive |
| project_command_engine_audit | LESSON | KEEP | - | actions_module; command_manager | ActionBus есть в framework/DECISIONS.md; сироту не пере-проверял |
| project_command_result_bridge | STATE | ARCHIVE | plans/_archive/2026-06-06_command-result-bridge | command_manager; gui | план в _archive |
| project_component_scoped_styles | STATE | ARCHIVE | multiprocess_prototype/plans/component_scoped_styles.md | frontend/styles | файл плана существует; память — указатель |
| project_concurrent_backends_trap | LESSON | KEEP | - | process_manager; shm; mechanism: global-r… | PID-реестр исправлен в harness; SHM-cleanup латентен |
| project_config_driven_arch | STALE | ARCHIVE | - | generic_process | Constructor-слой удалён 2026-05 (phase6) |
| project_config_voice_belongs_to_the_apply_stage | LESSON | KEEP | - | config_module; mechanism: IO-in-parser | корень = ввод-вывод внутри парсера |
| project_constructor_master_progress | STATE | ARCHIVE | plans/2026-07-06_constructor-master/plan.md; docs/handoffs/2026-07-11… | constructor-master | чистый прогресс; по ORDER осталось H.3/H.5/H.6 |
| project_constructor_phase5 | STALE | ARCHIVE | git | prototype/constructor | Constructor-слой удалён 261b90f |
| project_constructor_phase6 | STALE | ARCHIVE | git show 9885bb88 | prototype/constructor | файл сам DEPRECATED |
| project_cross_tab_phase_b | STATE | ARCHIVE | plans/_archive/2026-05-27_cross-tab-architecture | domain layer | план в _archive |
| project_cross_tab_phase_c | STATE | ARCHIVE | то же | adapters | план в _archive |
| project_cross_tab_phase_d | STATE | ARCHIVE | то же | AppServices DI | план в _archive |
| project_cross_tab_phase_e | STATE | ARCHIVE | то же | per-tab migration | план в _archive |
| project_cross_tab_phase_f | STATE | ARCHIVE | то же | legacy removal | план в _archive |
| project_cross_tab_phase_g | STATE | ARCHIVE | то же | ActionBus; AppContext | план в _archive |
| project_cuda_torch_setup | REFERENCE | KEEP | - | ml_train; gpu | факт машины |
| project_dataset_gen_service | REDUNDANT | ARCHIVE | Services/dataset_gen/STATUS.md:58 | dataset_gen | единственная находка (центр (size-1)/2) уже в STATUS.md |
| project_device_hub | STATE | ARCHIVE | plans/_archive/device-hub.md; plans/device-tree-recipe.md | device_hub | Фазы 0-5 DONE; контракты из ревью не сверены |
| project_devseed_overwrites_claude_dir | RULE | MOVE-RULE | .claude/CLAUDE.md (одна строка про claude-kit upgrade) | claude-kit | git grep: в .claude/CLAUDE.md правила нет |
| project_display_registry | REDUNDANT | ARCHIVE | display_module ADR-DM-001 | display_module | решения в ADR модуля |
| project_draw_mode_rework | STATE | ARCHIVE | plans/draw-mode-rework/plan.md (A,C,D DONE) | robot draw | план в таблице закрытых |
| project_f2_4_scope_is_a_string | STATE | ARCHIVE | plans/observability-unified-routing.md | logger_module | план DONE |
| project_f2_closed_2026_08 | STATE | ARCHIVE | то же | observability | план DONE |
| project_f3_external_review | STATE | ARCHIVE | docs/reviews/2026-08-05_f3_review.md | observability | отчёт в docs/reviews |
| project_f4_processors_closed | STATE | ARCHIVE | plans/observability-unified-routing.md | observability | план DONE |
| project_f5_cross_review | STATE | ARCHIVE | docs/reviews/2026-08-01_f5-cross-review.md | observability | отчёт в docs/reviews |
| project_f6x_review_basket | STATE | ARCHIVE | коммиты 7e3eabae..f258a200 | observability | план DONE |
| project_f7_cross_review | STATE | ARCHIVE | docs/reviews/2026-08-06_f7-cross-review.md | observability | отчёт в docs/reviews |
| project_f7_g3_handoff | STATE | ARCHIVE | plans/2026-07-06_constructor-master/g3-review-2026-07-14.md | shm; frame | закрыто; флаги в реестре |
| project_f7_g4_done | STATE | ARCHIVE | plans/2026-07-06_constructor-master/g4-execution-plan.md | frame_pool; shm | закрыто, правда в плане |
| project_f7_g7_flip_ladder | STATE | ARCHIVE | plans/2026-07-06_constructor-master/g7-flip-plan.md, baseline.md | shm; feature_flags | числа уже в baseline.md |
| project_f7_g7_num_consumers | LESSON | KEEP | - | frame_pool; process_module/generic; mecha… | урок с корнем и фиксом fe0f4d41 |
| project_f8_review_and_stitching | STATE | ARCHIVE | ADR-PM-028 (process_module/DECISIONS.md); docs/reviews/2026-08-08_f8-… | process_module | итог фазы = ADR |
| project_feature_flags_registry | REDUNDANT | ARCHIVE | config_module/feature_flags.py + README | config_module | код и тесты — источник; список флагов устаревает |
| project_fencing_test_race | LESSON | KEEP | - | topology fencing; mechanism: test-asserts… | флейк по построению, замер 3/3 красный, 1/3 проба |
| project_fw_version_from_git | REDUNDANT | ARCHIVE | multiprocess_framework/version.py (docstring про .dirty) | framework | docstring в version.py говорит то же |
| project_g5_ownership_decision | STATE | ARCHIVE | plans/2026-07-06_constructor-master/g5-execution-plan.md | frame_pool | решение исполнено в G.5 |
| project_generic_process_vision | STALE | ARCHIVE | git (GenericProcess реализован) | generic_process | видение реализовано, три слоя уже в CLAUDE.md |
| project_gorynych_pypi_deferred | REFERENCE | KEEP | - | packaging | решение владельца с 3 условиями возврата |
| project_graceful_stop_debt | LESSON | KEEP | plans/lifecycle-stop-ownership.md | process_manager; mechanism: mp.Queue feed… | диагноз верифицирован дампом; опровергнутое записано |
| project_graphify_mcp_setup | REFERENCE | KEEP | - | graphify | рантайм --with ломает коннект; числа графа датированы |
| project_gui_constructor_layers_2026_09_26 | LESSON | KEEP | plans/gui-constructor/plan.md (DRAFT) | gui-constructor | решение; перекрывается планом gui-constructor — сверить |
| project_gui_stand_production_entry_only | RULE | MOVE-RULE | команда core:quality:observability-acceptance + project-rules | gui; backend_ctl; mechanism: live-stand | git grep UNATTENDED в командах: 0 |
| project_gui_system_queue_storm | LESSON | KEEP | - | gui; router; state_store; mechanism: neve… | диагноз 2026-07-22; в defects.md не найден — статус неясен |
| project_gui_telemetry_read_model | STATE | ARCHIVE | plans/gui-telemetry-read-model.md; ADR-136 | telemetry_readmodel | план DONE, ADR-136 |
| project_hardware_roles_2026_09_23 | REFERENCE | KEEP | - | hardware | факт владельца |
| project_hierarchical_addressing | REDUNDANT | ARCHIVE | message_module/addressing/address.py; ADR-COMM | message_module; router | реализовано (P0.2), цитируется в backend_ctl d1 |
| project_hikvision_aspect_ratio | LESSON | KEEP | - | Services/hikvision_camera | эллипс = target_aspect/sensor_aspect, фикс конфигом |
| project_hikvision_letter_robot | REDUNDANT | ARCHIVE | multiprocess_prototype/recipes/hikvision_letter_robot.yaml | recipes | рецепт yaml — источник правды |
| project_honest_verdict_2026_09 | STATE | ARCHIVE | docs/audits/2026-09-04_honest-verdict-bus-and-niche.md; plans/queue/d… | product | отчёт и очередь уже в docs/plans |
| project_kind_channels_dead_evict_branch | LESSON | KEEP | survivor: этот файл | router; frame_pool; mechanism: dead-branc… | флаг ещё в backend_ctl/README и пробах |
| project_knobs_universal_manager | STATE | ARCHIVE | plans/observability-closure/plan.md Task 4.9 | observability; knobs | направление записано в плане |
| project_letter_angle_training | STATE | ARCHIVE | plans/letters-retrain/plan.md | ml_train | план жив и ведёт состояние |
| project_line_filter_feature | STATE | ARCHIVE | plans/_archive/2026-06-08_line-filter-virtual.md | line_filter | план в _archive |
| project_line_sim_vision | STATE | ARCHIVE | plans/line-sim/vision.md, plans/line-sim/plan.md | line_sim | видение и план в репо, DONE Ф0-Ф3,Ф5 |
| project_live_findings_webcam_2026_07 | LESSON | KEEP | - | backend_ctl; mechanism: swallowed-cause | три находки, ни одну не ловили 504 теста |
| project_live_verification_2026_07_21 | STATE | ARCHIVE | docs/audits/2026-07-20_bug-hunt.md §9-10 | audit | закрыто, отчёт в docs/audits |
| project_macos_shm | STATE | ARCHIVE | plans/_archive/framework_assessment_2026_05_07.md | memory_module; macos | дата 2026-05, источник — план в _archive |
| project_memory_module_consolidation | RULE | KEEP | - | memory_module | директива владельца жива до закрытия плана H |
| project_ml_train_service | REDUNDANT | ARCHIVE | Services/ml_train/STATUS.md | ml_train | план в _archive/ml-train-service.md |
| project_monotonic_resolution_windows | LESSON | KEEP | - | tests; windows; mechanism: clock-resoluti… | разности <100 мс недостоверны, замер get_clock_info |
| project_observability_audit | STATE | ARCHIVE | plans/observability-unified-routing.md | observability | план DONE |
| project_observability_closure_progress | STATE | ARCHIVE | plans/observability-closure/plan.md; docs/claude/OPEN_QUESTIONS.md | observability | чистый прогресс, ORDER: Ф4 4.4/4.11/4.13 DONE |
| project_observability_config_layers | STATE | ARCHIVE | plans/observability-unified-routing.md; ADR | observability | план DONE; схема слоёв в ADR |
| project_observability_consumer_acceptance | REDUNDANT | ARCHIVE | .claude/commands core:quality:observability-acceptance | observability | зонд и чек-лист стали командой |
| project_observability_control_plane | STATE | ARCHIVE | plans/_archive/2026-06-03_observability-control-plane | observability | план в _archive |
| project_observability_namespace_symmetry | STATE | ARCHIVE | plans/observability-unified-routing.md | logger_module | план DONE; один мелкий урок |
| project_observability_session_ttl | STATE | ARCHIVE | ADR наблюдаемости | observability | план DONE |
| project_observability_stdlib_migration | STATE | ARCHIVE | plans/observability-unified-routing.md | logger_module | план DONE |
| project_observability_store_error_routing | LESSON | KEEP | - | observability_store; logger_module; mecha… | live-boot вскрыл, юниты прятали (0 error из 60) |
| project_observability_subscription_broker | STATE | ARCHIVE | plans/observability-unified-routing.md | observability | план DONE |
| project_observability_tail_repair | STATE | ARCHIVE | docs/reviews/2026-08-12_observability-hard-review.md | observability | закрыто |
| project_observation_port_progress | STATE | ARCHIVE | plans/observation-port/plan.md | observation_port | план DONE (ORDER: шапка "черновик" врёт) |
| project_otel_export_plan_state | STATE | ARCHIVE | plans/otel-export.md; docs/reviews/2026-09-05_otel-export-plan-review… | otel | план живёт и сам ведёт состояние |
| project_phase5_data_pipeline | STALE | ARCHIVE | git | generic_process | путь multiprocess_prototype_2/ удалён |
| project_phase5_progress | STALE | ARCHIVE | git | generic_process | старая нумерация фаз, всё в git |
| project_phase_g_final_review | STATE | ARCHIVE | docs/reviews | constructor-master | исполнено, фаза G закрыта |
| project_phone_gateway_service | REDUNDANT | ARCHIVE | Services/phone_gateway/README.md, STATUS.md | phone_gateway | v1 готов, состояние в STATUS |
| project_pipeline_demo | STALE | ARCHIVE | git | pipeline_tab | Phase 7a/7b 2026-05, UI с тех пор переписан |
| project_pipeline_editor_runtime_decoupled | STALE | ARCHIVE | plans/_archive/2026-05-31_pipeline-live-control | pipeline | план pipeline-live-control в _archive, мост достроен |
| project_pipeline_live_control_stage1 | STATE | ARCHIVE | то же | pipeline | план в _archive |
| project_pipeline_live_control_stage2 | STATE | ARCHIVE | то же | pipeline | план в _archive |
| project_pipeline_live_incremental_vision | STALE | ARCHIVE | то же | pipeline | видение владельца 05-31 реализовано планом |
| project_pipeline_node_plugin_containers | STALE | ARCHIVE | git | pipeline_tab | запись 2026-05-30 "НЕ закоммичено"; UI переписан |
| project_pipeline_node_process_worker | STALE | ARCHIVE | git | pipeline_tab | план лежит в prototype/frontend/..., "uncommitted" |
| project_pipeline_recipe_driven_launch | REDUNDANT | ARCHIVE | plans/_archive/2026-05-31_pipeline-live-control | pipeline; recipes | направление владельца 05-31 исполнено |
| project_plan_driven_dev | REDUNDANT | ARCHIVE | корневой CLAUDE.md, раздел Plan-Driven Development | process | CLAUDE.md говорит то же |
| project_plugin_system_phase6 | STALE | ARCHIVE | git | processes_tab | 2026-04-30, SystemTopology заменён |
| project_priority_engine_first | RULE | POINTER | plans/queue/ORDER.md (строка про маятник) | priorities | правило уже в ORDER.md; файл сжать до ссылки |
| project_processes_tab | STALE | ARCHIVE | git | processes_tab | 2026-04-28 |
| project_processes_workers_runtime | STATE | ARCHIVE | git | processes_tab; worker_module | план в репо отсутствует, ветка закрыта |
| project_prototype_audit_2026_06 | STALE | ARCHIVE | docs/audits/2026-06-13_prototype-services-plugins-audit.md | audit | часть находок починена с тех пор; отчёт сам хранит ID |
| project_prototype_carveout | STALE | ARCHIVE | plans/_archive/prototype-carveout.md; корневой CLAUDE.md (Phase 4/5 c… | framework; Services; Plugins | Services/ и Plugins/ вынесены (CLAUDE.md) |
| project_pult_control_panel | STATE | ARCHIVE | plans/pult-control-panel.md (Phase 1-3 DONE) | Services tab; SectionProtocol | единственный урок спрятан в 8.6 КБ статуса |
| project_qex_model | REFERENCE | KEEP | - | qex; ollama | REFERENCE по платформам; ловушка silent-CPU уникальна |
| project_qex_reindex_timeout | LESSON | MERGE→ | qex_full_rebuild_runbook | qex; windows | CLAUDE.md пишет, что тормозили BM25-сегменты — причина могла устареть |
| project_recipe_hotswap | STATE | ARCHIVE | plans/_archive/2026-06-06_replace-blueprint-hotswap.md | recipe; process_manager | план в _archive |
| project_recipe_inspector_join_key | LESSON | ARCHIVE | blueprint.py infer_missing_collectors (Ф4.7); process_manager_module/… | recipes; mechanism: silent-disable | костыль _hoist_inspector_from_metadata снят; в коде остались комментарии |
| project_recipe_save_load_arch | STATE | ARCHIVE | plans/_archive/2026-06-06_recipe-orchestrator-unify.md | recipe | FIXED x2, план в _archive |
| project_recipes_manager | REDUNDANT | ARCHIVE | ADR-131; multiprocess_prototype/recipes/manager.py | recipes | решения в ADR-131 |
| project_robot_vfd_services | STATE | ARCHIVE | ADR-MB-001/002; plans/_archive/robot-vfd-services.md | Services/modbus | Фазы 0-5 DONE |
| project_root_gate_misses_framework_modules | LESSON | KEEP | Makefile gate | tests; pytest; mechanism: coverage-of-the… | контрмера в Makefile есть; урок общий: сверять testpaths |
| project_runtime_knob_expires_in_300s | LESSON | KEEP | - | telemetry; observability; mechanism: sess… | L3 TTL снимает гейт; ключ system.yaml:176-182 |
| project_sentrux_baseline_2026_05 | STALE | ARCHIVE | mcp__sentrux__evolution | sentrux | цифра 4 месяца как мертва; evolution даёт ряд |
| project_sequencing_observability_then_audit | STATE | ARCHIVE | plans/observability-closure/review-phase-2-cto.md:208 | ponytail-audit | решение владельца 09-02, исполняется по плану closure |
| project_service_registry | REDUNDANT | ARCHIVE | service_module ADR-SVC-001 | service_module | решения в ADR модуля |
| project_services_vs_plugins | REDUNDANT | ARCHIVE | ADR-120; корневой CLAUDE.md (Слои импортов) | Services; Plugins | CLAUDE.md и ADR-120 описывают границу |
| project_settings_mvp_refactor | STALE | ARCHIVE | plans/_archive/settings-mvp | settings tab | план в _archive, план-файл в ~/.claude/plans |
| project_sketch_robot_draw | STATE | ARCHIVE | multiprocess_prototype/recipes/webcam_sketch.yaml | robot draw | рецепт — источник правды |
| project_source_topology | STALE | ARCHIVE | код registers/ | sources; processing | 2026-04-28, реестры с тех пор переделаны |
| project_state_topology_gate | LESSON | KEEP | ADR-SS-019 | state_store; mechanism: topology-gate | гейт и флаг есть; урок: призраки после switch |
| project_std_facade_unused | STALE | ARCHIVE | git grep get_std_logger -- *.py = 142 файла | logger_module | Ф6 stdlib-миграция (100 файлов) устранила; число устарело |
| project_strokes_points_perf | LESSON | KEEP | - | Plugins; numpy; mechanism: O(n^2)-per-fra… | фикс сделан; урок — искать пересборку массива в цикле |
| project_switch_delivers_layer | LESSON | KEEP | - | recipe switch; observability L2; mechanis… | два механизма одного триггера: общий тег switch-redelivers-state, не слияние |
| project_switch_routing_stale | LESSON | KEEP | - | recipe switch; process_state_registry; me… | см. switch_delivers_layer |
| project_system_topology_phase1 | STALE | ARCHIVE | git | system_topology | ветка refactor/flatten-structure, 2026-04 |
| project_team_mode_agent_teams | REDUNDANT | ARCHIVE | .claude/CLAUDE.md, раздел Team mode | team | CLAUDE.md описывает; "живой прогон не делался" устарело (пилот v2, 4.7d) |
| project_telemetry_coherence_remediation | STATE | ARCHIVE | plans/telemetry-coherence-remediation.md (DONE) | telemetry | план DONE |
| project_telemetry_dashboard | STATE | ARCHIVE | plans/telemetry-dashboard.md (DONE) | telemetry; pyqtgraph | план DONE; решение pyqtgraph в коде |
| project_telemetry_db_sink | STATE | ARCHIVE | plans/_archive/2026-06-04_telemetry-db-sink.md | telemetry; Services/sql | план в _archive |
| project_telemetry_gui_controls | STATE | ARCHIVE | plans/telemetry-publish-control.md (DONE) | telemetry; gui | план DONE |
| project_telemetry_publish_control | STATE | ARCHIVE | ADR-PM-018 | telemetry | план DONE, ADR |
| project_telemetry_self_publish | STATE | ARCHIVE | plans/_archive/telemetry-self-publish-redesign.md | telemetry; monotonic | строку про monotonic FPS=0 перенести в project_monotonic_resolution_windows |
| project_telemetry_subscription_bug | STATE | ARCHIVE | git (16e14084) | telemetry; state_store | остаток (late-binding) решён ADR-136 |
| project_topology_fencing_token | STATE | ARCHIVE | ADR-PMM-014, ADR-MSG-009 | message_module/fencing | исполнено e16e2ea8 |
| project_transport_router_hub | STATE | ARCHIVE | plans/_archive/2026-05-31_transport-router-hub; plans/transport-singl… | router | план в _archive; продолжение — transport-single-policy |
| project_universal_lifecycle_decision | RULE | KEEP | - | lifecycle; subscriptions; mechanism: scop… | решение владельца; план lifecycle-owner-scope активен |
| project_universal_object_generator | STATE | ARCHIVE | plans/layer-render/plan.md | layer_render | план layer-render APPROVED, ведёт сам |
| project_venv_locked_by_mcp | LESSON | KEEP | - | venv; backend_ctl MCP; windows | kill по PID гонку не выигрывает, замер 07-31 трижды |
| project_vfd_bridge_robot_reboot | LESSON | KEEP | - | Services/vfd; robot; mechanism: bridge-ca… | ≥2 раза; сначала проверять носителя |
| project_webcam_sketch_freeze | STATE | ARCHIVE | ADR-136; plans/gui-telemetry-read-model.md | gui; telemetry | закрыто ADR-136, инвариант-тест 0 блокирующего IPC |
| project_work_order_2026_09_22_line_sim_then_pult | STATE | ARCHIVE | plans/queue/ORDER.md ("единственное место порядка") | priorities | ORDER.md объявлен единственным местом порядка |
| project_worker_cycle_timing | STALE | ARCHIVE | worker_module (effective_hz в system_overview, 6b9d4e1f) | worker_module | пожелание реализовано |
| project_workers_architecture | REDUNDANT | ARCHIVE | worker_module/README.md | worker_module | описание кода |
| reference_gpu_monitoring_windows | REFERENCE | KEEP | - | gpu; ollama; windows | факт машины |
| reference_qt_mcp_launch | REFERENCE | KEEP | .claude/plugins/mcp-qt/SETUP_GUIDE.md | qt-mcp | MCP README уже требует чтения перед использованием; можно в AR |
| reference_tech_stack_2026 | REFERENCE | KEEP | docs/direction/TECH_STACK_2026.md | stack | указатель на живой документ владельца |
| user_career_goal | REFERENCE | KEEP | - | owner | решение владельца 2026-08-20 |

## 7. Шаг 6. Рецепт исполнения

Исполняет лид после одобрения, одним PR. Ветка по правилам проекта: `<type>/<slug>`, например `docs/memory-cleanup`; коммит ветки с таким именем требует `Refs:` — использовать `Refs: docs/claude/memory (аудит 2026-10-04)` или завести план через `/dev:plan` (см. п. 18). Коммиты: Conventional + `Why:` + `Layer: docs`. Один писатель, одно дерево: перед стартом `ListAgents` и `git status`.

**Подготовка**
1. `git switch -c docs/memory-cleanup` от `main` (чистое дерево; в `git status` на 2026-10-04 лежат чужие `.claude/agent-memory/*` и `plans/2026-10-04_atlas/` — не трогать, стейджить явные пути).
2. Резервная копия: `tar`/`robocopy` локальной папки `~/.claude/projects/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/memory/` в `scratchpad/memory-backup/`. Не удалять до конца PR.
3. Сверка копий: для каждого файла из `pass1.json` со статусом не `same` (`differ`, `only_git`, `only_local`) — `diff <git> <local>` и ручное решение; `cp` без `diff` запрещён (урок `dual_write_by_copy_destroys_the_other_side`). Итог — `docs/claude/memory/` = канон. `reference_gpu_monitoring_windows.md` и `user_career_goal.md` — решение владельца (в git или local-only).
4. Предпроверки раздела 5 (п. 1, 2, 4, 8, 9). Каждая строка ARCHIVE с планом в «цель» проверяется: `git ls-files plans | grep <slug>`; нет — вернуть в KEEP.

**Содержание**
5. Прогнать слияния (раздел 2): для каждой группы открыть выжившего и поглощаемых целиком, перенести строки «унести» (таблицы 2.2 и 2.4), в `description` выжившего вписать триггеры поглощённых, в frontmatter добавить `merged_from: [..]`. Целевой размер выжившего: G1 ≤ 6 КБ, G3 ≤ 5 КБ, G5 ≤ 5 КБ, остальные ≤ 4 КБ.
6. Создать три новых урока (1.1) и внести двенадцать дополнений (1.2). Перед созданием L3 — `git ls-files | grep test_routing_epoch_live`, затем `git grep -n protected` в найденном файле.
7. Теги: во frontmatter каждого KEEP-урока (LESSON, 190 + выжившие) добавить `module:` и `mechanism:` из колонки «теги» раздела 6. Скрипт читает `ACTIONS.tsv`. Прогнать `.claude/plugins/core/scripts/memory_lint.py`.
8. Перенос правил (раздел 3): группировать по цели.
   - `project-rules`: править **источник** `.claude/plugins/dev/skills/project-rules/SKILL.md`, затем зеркало `.claude/skills/project-rules/SKILL.md`, затем `diff -q` (урок `materialized_agents_drift_from_plugin_source`). Строки 2, 3, 4, 10, 21, 27, 29, 31, 34, 32 (текст).
   - Команды и агенты — то же правило «источник, потом зеркало»: `/dev:plan`, `/dev:ship`, `/dev:implement`, `debugger`, `reviewer`, `cto`, `manager`, `systematic-debugging`, `observability-acceptance`.
   - `.claude/CLAUDE.md`, корневой `CLAUDE.md` (блок «Принципы владельца» и «Memory»), `.rules/gui.md`, `.rules/plugins.md`, `.rules/logging.md`, `COMMIT_GUIDE.md`, ADR logger_module.
   - `settings.json`, `conftest.py` — **только после явного одобрения владельца**, отдельным коммитом (правки прав доступа).
9. Для файлов MOVE-RULE и POINTER (35): заменить тело заглушкой — rule одной строкой + `→ <цель>` + дата переноса; frontmatter оставить. Файл остаётся на месте (поиск по имени работает).
10. Для L1/L2: добавить строки в `CRAFT-tests.md` и `CRAFT-verdict.md` (раздел 4 `CRAFT.split.md`).

**Перенос и индексы**
11. `mkdir docs/claude/memory/_archive`; `git mv` для всех строк ARCHIVE и MERGE из `ACTIONS.tsv` (скрипт: читает TSV, `git mv docs/claude/memory/<file> docs/claude/memory/_archive/<file>`). После — `git show --stat` (урок `commit_takes_the_whole_index`).
12. Создать `_archive/INDEX.md`: `имя → куда ушло` (выживший, ADR, plans/_archive, правило). Переписать ссылки: (а) внутри памяти — `](x.md)` и `[[x]]` на перенесённые файлы → `_archive/x.md` или выживший; (б) в живых документах репозитория — только функциональные ссылки (раздел 5, п. 7). Журналы `docs/sessions/*` и `plans/_archive/*` не править.
13. Добавить в `ARCHIVE.md` раздел «Перенесено 2026-10-04»: одна строка на группу (22 закрытых плана наблюдаемости, 7 телеметрийных, 6 cross-tab, 6 pipeline, прочее) и ссылка на `_archive/INDEX.md`.
14. Разрез CRAFT: создать четыре файла по `CRAFT.split.md`; `CRAFT.md` оставить заглушкой из четырёх ссылок (входящие ссылки на него есть); удалить 17 строк раздела 2 того документа; переписать 14 ссылок раздела 3.
15. `MEMORY.md` ← `MEMORY.new.md`. Проверка: `wc -c MEMORY.md` ≤ 8192; все `](…)` целей существуют (скрипт из шага 16); `memory_lint.py` зелёный.
16. Проверка целостности: число файлов корень + `_archive/` = 433 + 3 новых урока + 4 файла CRAFT + `_archive/INDEX.md` = 441 (раздел 0: корень 254, архив 187); нет мёртвых ссылок в `MEMORY.md`, `CRAFT-*.md`, `ARCHIVE.md`; `python scripts/validate.py`; команда `core:quality:claude-md-audit` (проверяет ссылки MEMORY).
17. Синхронизация кэша: локальная папка ← `docs/claude/memory/` (`robocopy /MIR`, исключая два local-only файла, если владелец оставил их вне git). Обновить правило dual-write (строка 9 раздела 3) в корневом и `.claude/CLAUDE.md`; зеркало Mac `.claude/memory/MEMORY.md` — не трогать, сообщить владельцу.
18. PR: ревью — `reviewer`, синхронно (`run_in_background: false`), с воспроизведением (счёт файлов, `wc -c`, линтер); для merge в main нужен оформленный `/code-review` (урок `formal_review_before_merge`). Тестера не нужно: задача — документы; сказать это в PR явно (правило «нет легитимного пропуска тестера» требует записи причины).

Ожидаемый размер PR: ~186 переносов, ~35 заглушек, ~60 правок выживших, 3 новых файла, 4 файла CRAFT, 6–9 правок файлов-целей. Токены: исполнение ~1–2 М при одном агенте-исполнителе на группу; разумно разбить на волны по шагам 5–6, 8, 11–15 и держать лида вне чтения файлов.

## 8. Что ненадёжно

- **Охват чтения.** R1, R2, R3 читали только голову файлов (R1 — ещё 4 целиком, R2 и R3 — ни одного). Я перечитал целиком (или первые 1.3–2.8 КБ после frontmatter) файлы 16 слияний и 4 больших STATE-файла. Остальные ~25 слияний в разделе 2.4 приняты по голове.
- **Классификация kind и action для ~340 файлов не проверялась мной** — это доверие к трём отчётам. Выборочные сверки: 40 пунктов R1, 30 пунктов R2, планы по ORDER.md (R3). Три ошибки уже найдены на них (`package_install_by_user` «deny»; `_hoist_inspector…` «не найдена»; «recorder не записан»), значит скрытых может быть больше.
- **Файлы 8–13 КБ типа STATE** просмотрены по ключевым словам. Урок мог остаться в абзаце без слов «урок/ловушка/баг» (`phone_gateway_service` 12 КБ, `line_sim_vision` 11 КБ, `telemetry_subscription_bug` 10 КБ).
- **Новые уроки L1–L3** сформулированы по STATE-прозе; доказательства (коммиты, номера) взяты оттуда и не перепроверены `git show`. L3 требует проверки докстринга теста.
- **Уникальное содержимое слияний (таблицы 2.2 и 2.4)** — мой пересказ; точный перенос строк делает исполнитель с обоими файлами в руках.
- **Размеры** (`MEMORY.new.md` 7831 Б, CRAFT) посчитаны скриптами; размеры слитых выживших — оценка, не замер.
- **Короткие имена `f:`/`p:` в `MEMORY.new.md`** не проходили `memory_lint.py`.
- **`_archive/` внутри `docs/claude/memory/`:** не проверено, что `claude-md-audit`, `/core:memory:search`, `memory_lint.py` и сам Claude Code автозагрузчик не сканируют подпапки так, что `_archive` попадёт в поиск или в индекс. Проверить до PR; запасной вариант — `docs/claude/memory-archive/` рядом.
- **Откат:** git revert PR восстанавливает git-копию; локальная копия — из резервной папки шага 2.
- Вопросы, которые переживают задачу (в `docs/claude/OPEN_QUESTIONS.md`): три копии памяти; судьба local-only файлов; цена `_archive` в поиске; допустимость `f:`/`p:` в индексе.
