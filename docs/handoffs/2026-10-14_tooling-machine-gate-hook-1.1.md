# Передача: полоса «Инструменты · хук гейта» — Task 1.1 готова, дальше слияние и Task 1.2

Дата: 2026-10-14. Сессия-автор: inspector-bottles-ec (раньше f5; координатор — inspector-bottles-23, прежний b4).
План: `plans/2026-10-13_tooling-machine-gate-hook.md` + подфайлы `…/classification.md`, `…/injections.md`.

## Состояние (по git, не по шапке)

- Ветка `feat/tooling-machine-gate-hook`, worktree `.claude/worktrees/gate-hook-1.1`, HEAD `31c1f39a0`. В main ничего не влито.
- Task 1.1 — `[DONE 0bfd4bb76]` (коммит закрытия `894292125`). Реализация `5f14906c2` + правки по ревью `6818bfc77`;
  слепые тесты `68fb35129` (102) + авторские hazard-тесты (42, файл `test_machine_gate_classify_hazards.py`) = 144 passed.
- Инъекции: I/M — 24 из 25 поймано (I6 — эквивалентный мутант); Q — 14 из 16 (Q9 эквивалентна, Q10 не ловится). Факты — в `injections.md`.
- Ревью плана: 2 итерации (итог — единственный блокер закрыт строкой TRAPS). Ревью кода: 2 итерации, раунд 2 — APPROVED.
- Task 1.2 (`grant`/`close`/`status`/`validate_lock`) — `[PENDING]`, не начата; ветка та же, тот же `machine_gate.sh`.
- Хук `machine-gate-guard.sh` зарегистрирован в `.claude/settings.json` ТОЛЬКО в этой ветке.

## Что решает не лид

1. **Слияние в main = включение хука для ВСЕХ сессий.** Только по слову владельца и после того, как координатор предупредит полосы
   (хук блокирует голый pytest/make gate/run_sim_all мимо гейта, пока лежит machine.lock). Слияние — `merge: <суть>` + Why/Layer/Refs,
   нужен оформленный `/code-review` (память: feedback_git_main_merge_hook_traps, feedback_formal_review_before_merge).
2. Решение владельца про `timed`/слот пришло через координатора; текст ответа 2 в плане дополнен строкой «Уточнение» — владельцу показать
   формулировку (написана со слов координатора).
3. Расширение 1.1 сверх прямого ответа владельца: `make gate|test|test-fast|test-fw|test-ctl` → heavy; префиксы `env/time/xargs/do/then/…`. Если не нужно — убрать.

## Порядок после слова владельца

1. Слияние ветки в main (отдельная сессия-лид слияния или тот же лид), затем **живая проба P1**: субагент haiku с `isolation: "worktree"`
   выполняет `python -m pytest --version` и `echo "$CLAUDE_PROJECT_DIR"; pwd`; ожидается блок и строка `hook:` — результат в OPEN_QUESTIONS/урок.
2. После слияния (лид, в своих границах): skill `coordinator` §3, `project-rules` §8, `.claude/CLAUDE.md` «Shared machine» — `[--timed] heavy|medium|light`,
   класс medium, timed; исходник в `.claude/plugins/dev/…`, затем побайтная копия в `.claude/skills/…`, `cmp`. Список — п. 7 «Пайплайна» плана.
3. Task 1.2 — конвейер как в 1.1: manager (Task 1.2 под grant/close/status; не забыть: `medium` — класс команды, kind окна quiet|heavy|stand) →
   reviewer `MODE: plan` → слепой tester в worktree на коммите до реализации → developer → инъекции J1–J5 → reviewer.

## Таблица агентов (agentId; переиспользовать по SendMessage)

| Роль | agentId | Состояние |
|---|---|---|
| manager (спека 1.1) | ad034a80b1a3e9b26 | свободен |
| reviewer (план, MODE: plan) | a73efc6c962a6fba6 | сдал, 2 итерации выбраны |
| tester (слепой 1.1) | a1d65e20b1e5818db | второй раз не запускать |
| developer 1.1 | a16b60a7987fcfee1 | свободен (контекст ~300k — на 1.2 новый) |
| reviewer (код 1.1) | a8afc9065d3b514a3 | 2 итерации выбраны; для 1.2 — новый |
| haiku: матрица I/M | a293ab06c2fe8e969 | сдал |
| haiku: матрица Q | afe3f7e08995916c7 | сдал |

## Тонкости, которые стоили времени

- Агенты-писатели проходят `lint-brief` (DESIGN ≥ 3 строк, каждая — отдельной строкой; FILES ≤ 6; REDS ≤ 10 или `n/a`; блок REPORT). `Explore` писать/гонять скрипты не может — для матриц `junior` + haiku.
- Скрипты матрицы (`inject_driver.py`, `inject_driver_q.py`) лежали в scratchpad сессии; общий приём: применить правку по точной строке (assert count == 1), прогнать через ВНЕШНИЙ гейт `light`, `git checkout --` откат, сверка «предсказано / наблюдено». Команда прогона обязана собирать ВСЕ файлы теста (один раз скрипт брал один файл — все `obs=0` ничего не значили).
- Гейт основного дерева зовёт `<git-common-dir>/../scripts/machine_gate.sh`; тесты проверяют гейт СВОЕГО worktree (скрипт рядом с тестом) — это нормально.
- Хук в worktree активен с регистрацией в `settings.json`: heredoc с `pytest -q` в начале строки после правки классификатора уже не блокируется, но голый `pytest` при живом замке блокируется — гонять только через внешний гейт.
- `OPEN_QUESTIONS.md` (CRLF в рабочей копии): дописывать с тем же стилем концов строк, иначе git видит перепись всего файла.
- MEMORY.md = 8 240 Б при пределе 8 КБ; указатель на новый урок (`feedback_a_text_command_classifier_must_respect_quotes_and_heredocs`) не добавлен — нужна чистка индекса.
- Worktree слепого tester `.claude/worktrees/gate-hook-1.1-tester` (ветка `tests/gate-hook-1.1-blind`) оставлен до слияния; после — `git worktree remove` и удалить ветку.
- Untracked `docs/reviews/2026-10-14_task-1.1-developer.md` в worktree — отчёт developer, в коммиты не брался.

## Обновление после слияния (2026-10-14, тот же лид, сессия inspector-bottles-ec)

- **Влито в main:** `f15ea6e04` (merge: tooling-machine-gate-hook 1.1). Перед ним main подтянут в ветку (`0187ecf9b`), правка авторства решения про слот (`81b5f4e5b`: «Решение координатора b4 по поручению владельца»), правка тегов урока и индекса памяти (`0b983cb80`, `validate.py` без ошибок). Полосы Р (84) и С (5d) предупреждены координатором 23 до слияния. Хук в main живой; проба P1 закрыта (хук основного дерева блокирует и субагента в worktree — см. OPEN_QUESTIONS).
- **Правки skill и правил** (coordinator §3, project-rules §8, .claude/CLAUDE.md, зеркала побайтно): ветка `docs/gate-hook-medium-timed`, коммиты `90e5738ea`, `9f6e12b0a`, worktree `.claude/worktrees/gate-docs-medium`. **В main НЕ влиты** — слияние по слову владельца (меняет то, что читают все сессии).
- **Дальше — Task 1.2** (`grant`/`close`/`status`/`validate_lock`) отдельной веткой от main: новый worktree, пайплайн как в 1.1 (manager → reviewer MODE: plan → слепой tester → developer → инъекции J1–J5 → reviewer). Worktree `gate-hook-1.1` и ветку `feat/tooling-machine-gate-hook` можно удалить (влита); worktree слепого tester и пробы P1 уже удалены.
