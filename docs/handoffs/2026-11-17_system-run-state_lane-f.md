# Handoff — полоса Ф (run-state), 2026-11-17

Роль: лид полосы Ф (сессия inspector-bottles-91, координатор inspector-bottles-26). План: `plans/2026-10-27_system-run-state/plan.md`. Отчёт: `docs/reports/2026-11-17_system-run-state_lane-f-checkpoint.md` (состояние веток, числа, открытое, agentId). Ответы владельцу — по-русски.

## Цель
К железу ≈ 22.11.2026 прототип запускается в «готов»; ЗАПУСТИТЬ запускает, ОСТАНОВИТЬ останавливает (v2 = `stop SOFT`, v1 = `abort mode 3`); причины не-готовности видны; автостарт headless один раз за boot (`run_autostart`, `run.py --autostart`). К 21.11 — таблица «что готово из 1.11/3.3/2.1/2.2/2.3/2.6/2.4» координатору числами, без прогноза «успеем».
Установка владельца: «сразу как полагается, без костылей, единообразно». Правило отката CTO по S1+П2: к концу 19.11 нужны (окно heavy 0 новых красных; рассылка ≤ +10 %; живой стенд четырёх вкладок; инъекции красные), иначе S1+П2 не сливается, П3 остаётся.

## Состояние веток (worktrees в `.claude/worktrees/`)
- `lane-f-2.7` (`feat/run-state-2-7`, `7c3cbede4`): S3a…S3c′, 2.7d, M2, слиты 2.9 и M2, **M1 закоммичен**. Дерево чисто. `process_manager_module/tests` целиком: 141 failed + 5 errors одинаково на базе и после M1 (не регрессия, причина не разобрана — тесты с реальным spawn; не гонять два прогона параллельно). Разобрать причину — задача для debugger/Haiku-инвентаря до слияния.
- `lane-f-2.9` (`e6c05fc1a`): APPROVED, к слиянию.
- `lane-f-2.2` (`feat/run-state-2-2`, `0732ef317`): S4a+S4b с правками раунда 1 закоммичены. Дальше: ревью Sonnet раунд 2 (агент `aa2c120c212e6a766`, либо свежий). `test_no_private_access.py` изменён и НЕ коммитится.
- `lane-f-2.8a` (`feat/run-state-2-8a`, `2b10b5428`): П3, ревью раунд 2 APPROVED. 17 файлов ruff-шума в `state_store_module` не коммитить.
- `lane-f-integ`: временная, в main не идёт. `lane-f-merge` — слот слияния на main.

## Следующие шаги (по порядку)
1. M1 принят и закоммичен (`7c3cbede4`). Далее — разбор базовых 141 красных PM-тестов (отдельным прогоном, один процесс).
2. Ревью Sonnet по пачке 2.7 (S3a…S3c′, 2.7d, M2, M1) — не проводилось; ревью Sonnet раунд 2 по 2.2a2.
3. Свежее слепое Opus-ревью перед main: 2.7, 2.9, 2.2, П3; затем сквозной обзор Opus по интеграции.
4. Слияния в main через `lane-f-merge` (`machine_gate.sh merge-begin`, `git merge --no-ff -F файл`, тема `feat(...)`): 2.9 → 2.7 → 2.2 → П3 → 2.8. В коммите 2.7d поправить строку `Decision:` (один ADR на строку). Конфликты индекса ADR — снять маркеры + `python -m scripts.sync`.
5. После слияния П3: пинг лиду К (inspector-bottles-20) — камерный стенд на фейке с числом; контракт readiness для плагина камеры (4.2a) файлом (хук `readiness(ctx)`, политика `readiness: {hold_s, severity}`, ключ `run_locked_commands`, «модель не загружена» через readiness в YAML).
6. **Task 2.8 (S1+П2 одной веткой, критический путь):** слепой tester (бриф `scratchpad/f/tester-brief-2.8.md`, база — main после слияния П3), teamlead; ADR-SS-024 дополнить; окно heavy и живой стенд четырёх вкладок до конца 19.11; замеры: цена `**` при bind на 12 тыс. листьев, рассылка ≤ +10 %; `rev-sonnet/proj_diff2.py` против настоящего `_replay_initial_state`.
7. S5 (пульт читает `run_gate`, `stop_allowed`), затем коммит B 2.1 (`run_gate: true` + golden + литерал `True`) после S3c, S3c′, S5 и условий (live recipe_service ×2, `test_frame_bridge_live`, start_run до apply).
8. 2.9b, 2.6, 2.4 (живая приёмка), 2.5, S6 = 2.2c (подтянуть к main), S3doc, 3.3 follow-up, живые приёмки в окне.
9. К 21.11 — таблица «что готово» координатору; финальный отчёт `docs/reports/<дата>_system-run-state_<задача>.md`.
10. В `docs/claude/OPEN_QUESTIONS.md` внести накопленное (источник — `scratchpad/f/open-questions-pending.md`, вносить через lane-f-merge): H5 непроверен; цена `**` на bind; импорт read-model тянет стор; дубли пар `**.**`; период снимка readiness и soak-замер; хвост except; живой `--autostart` не проверен; M3 (`tick_fails_limit`=3 не подтверждено); окно эпизода паузы `_PAUSE_EPISODE_S`=3,0 (сигнал ЗАПУСТИТЬ в плагин или принять до стенда); бюджет паузы 1,5 с против замка при соседях; SOFT/HARD/HALT; автостарт раз за boot; очередь v2 после stop; список `run_locked_commands`; Save `user_overrides`; гашение автостарта через отказанный ack; ключ узла `run_locked_commands` молча игнорируется; порог `conn_stale_s`; проверка `params.pause_action`; S1+П2 до/после 1.0; владелец `state_store_module` (подтверждение координатора до 19.11); `plan.md` 33,4 КБ (разделить); строка soak из 2.9 → ACCEPTANCE 2.2; R3-1 (П3).
11. Мелкое: обратные ссылки в `ORDER.md`, 2.3, 2.6, 2.2c; поправка 10a/10c в 2.7.md; удалить копии деревьев в scratchpad `f/` (`probe-merge/`, `rev-sonnet/`, `inj-*/`, ~160 МБ); память `docs/claude/memory/`: уроки (слепой файл правит лид по решению; не гонять матрицу в дереве с чужим писателем; не запускать `ruff format` по каталогу; перепроверять «дефект базы» запуском; «tester wrong model» как находка).

## Открыто для владельца (не решать самому)
В10 (индикатор «нет диска», блокирует п.6 Task 2.2), В4 пульта, итог SOFT/HARD/HALT, «fault на ходу» в 3.3, список `run_locked_commands`, M3, окно эпизода паузы.

## Окружение и правила
macOS; `machine.lock` нет (откат на `stand.lock`); основной `.venv`, `PYTHONPATH=<worktree>`; никакого `uv sync`, голого `git stash`, `uv run` без `--no-sync`; все прогоны через `machine_gate.sh light|medium inspector-bottles-91`, heavy только в окне; коммиты: `Why:`/`Layer:` (допустимые: docs, framework, infra, mixed, plugins, prototype, scripts, services, tests)/`Refs:`, `Decision: ADR-…` одним id на строку, `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; лид коммитит явными путями; инъекции только на копиях с откатом `cp`+`cmp`; слепому tester запрещено читать reports/design/plan; лид не исполняет — агенты; субагент не расширяет права (никакого permission laundering). Конвейер: stage 0 reviewer sonnet → слепой tester в worktree на pre-impl коммите → developer Sonnet / teamlead Opus → инъекции (предсказания до прогона) → ревью Sonnet на задачу + свежее слепое Opus перед слиянием.

## Рабочие файлы
Scratchpad: `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/a0109779-f0ed-4955-adcb-5fc95bcd07f8/scratchpad/f/` (брифы, сообщения коммитов c20–c76, `review-*.md`, `cto-s1-verdict.md`, `target-architecture.md`, `open-questions-pending.md`). Может быть очищен после перезагрузки — ценное уже в репозитории или в отчёте.
Транскрипт: `/Users/twokrai/.claude/projects/-Users-twokrai-Project-code-Inspector-bottles/a0109779-f0ed-4955-adcb-5fc95bcd07f8.jsonl`.

agentId — в отчёте (раздел 5). Все исполнители завершены.

HTML для владельца (обновлён 17.11): https://claude.ai/artifact/SDAuTh4RVMAfyK5SoTDzWs (исходник — `scratchpad/f/architecture-before-after.html`). Владелец спрашивал про Opus-ревью (не проведены) — ответа на «в этой сессии или в новой» не было; по умолчанию — в новой.
