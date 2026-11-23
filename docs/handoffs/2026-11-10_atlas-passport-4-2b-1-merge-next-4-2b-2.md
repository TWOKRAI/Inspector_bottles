# Handoff · Атлас · 4.2b-1 до слияния → 4.2b-2 (`map`) в новом чате

Дата 2026-11-10. Ветка плана — `main` (локально, не пушить). План — `plans/2026-11-06_atlas-passport/plan.md`. Ответы владельцу — по-русски; первая строка «Атлас · <имя сессии>»; в конце непустой раздел «что оставил открытым / ненадёжно».

## Что делать новой сессии
1. Task 4.2b-1 уже влита в `main` (см. ниже); начинать с 4.2b-2.
2. Task 4.2b-2 (`map` юнита и файла). Текст — `plans/2026-11-06_atlas-passport/tasks/4.2b-2.md` (ред. 4, 7,2 КБ) и форма — `plans/2026-11-06_atlas-passport/map-form.md` (часть задачи: tester и teamlead читают оба). Stage 0 прошёл три раунда (sonnet ×2, opus ×1): `reports/4.2b-2.review-r1.md`, `r2.md`, `r3.md`. Ред. 4 (после р.3) никто не перепроверял — по желанию один раунд reviewer (opus, свежий) или сразу INTERFACE.
3. Цепочка: INTERFACE (developer sonnet, подписи `build_map`, флаги `map`, поле `MAP_SHOW_ALL`) → слепой tester (RED, worktree на коммите INTERFACE) → teamlead (opus) GREEN → инъекции (прогнозы лида ДО прогона, прогон — haiku `junior`) → ревью sonnet (р.2 — тот же агент) → result → слияние ff-only. Затем 4.3 (условие `atlas` в `nav_bench`, не зависит от `map`), потом 5.1.

## 4.2b-1: ЗАКРЫТА и влита в `main` (ff-only, HEAD `c6add165e`, 2026-11-10)
Коммиты после rebase: INTERFACE `df71a74a7`, RED `24e5db435`, GREEN `8b68205ce`, инъекции `2421ed93f`, правки ревью `28d068f3c`, result `c6add165e`. Ревью стадии 5 (sonnet) — APPROVED: `plans/2026-11-06_atlas-passport/reports/4.2b-1.review-stage5-r1.md`; итог — `tasks/4.2b-1.result.md` (полный набор 502 passed, 6 skipped; тёплый `ref` 1,27–1,40 с; гейт БД 3,33× — перемер на GREEN). В `plan.md` 4.2b-1 DONE. Долги из result: нет наблюдаемого теста на `--no-renames`/`--literal-pathspecs`; `resolve(root, "HEAD")` на каждый паспорт; `line` неточен при `\`-продолжениях в докстринге; `index.lock` до ~0,5 с; Windows (argv) не проверялся. Worktree `atlas-4-2b-1` и `atlas-4-2b-1-tester` можно убрать в чате «Git · push и уборка».

## Решения по 4.2b-2, которые нельзя потерять
- `used_by` юнита — операторы импорта (`scan.ImportIndex.resolve`), цель — любой файл юнита, включая `__init__.py`; НЕ `links.of` по `top` (реэкспорт не виден: `process_module` 79 против 388).
- `interface.all` юнита = `FileFacts.all` его `__init__.py`; `members` файла — с `_`, юнита (`top`) — без `_`.
- `_stale` в `map`: pathspec только при ≤ 100 путей, иначе один `git diff` без pathspec и пересечение в Python (argv `process_module` 29 КБ); править Post докстринга `_stale`.
- `--format` по умолчанию `passport`, `--budget` 60; `MAP_SHOW_ALL` = `members, used_by, tests, threads, io`; `ref --all members` остаётся кодом 2; в `__main__.py` три литерала `args.command == "ref"` (l.184, 189, 209), l.225 не трогать.
- `interface.layer` — id юнита (как 4.2a), `purpose.text` файла без докстринга — `""` и `doc_missing: true`.
- `uses` (исходящие зависимости юнита) в OUT OF SCOPE; Opus-ревью заметил, что для вопроса A3 («кто даёт очереди») он ~5 строк — решение владельца/лида.
- Ограничение сканера (не `map`): воркеры стартуют не через `Thread(...)`, вопрос A8 `map process_module` не ответит — ждать на Kill-2.

## Правила, которые срабатывали
- Коммит: Conventional Commits + `Why:` (одна строка) + `Layer:` (`scripts`/`docs`) + `Refs: plans/2026-11-06_atlas-passport/plan.md` + `Task: atlas-passport#4.2b-2` (id `4.2b-2` разбирается; `4.2b1` — нет) + `Decision: ADR-ATL-005` при ADR + `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` без пустой строки перед ним; сообщения — `-F` из файла в scratchpad. Предупреждение «тема > 72» не блокирует.
- `lint-brief` на брифах агентов: `BRIEF-OVERRIDE: <причина>` для слепого tester, ревьюеров, механических прогонов; бриф INTERFACE/GREEN тоже с override (нет REDS/форма). Task ≤ 8192 байт, FILES ≤ 6, REDS ≤ 10 (`scripts/atlas/lint_brief.py:34`).
- Слепой tester: worktree на коммите INTERFACE; запретные пути — реализации, `docs/reviews/**`, `plans/**/reports/**`, `*.result.md`; разрешены задача и `map-form.md`. Прошлый tester нарушил слепоту на чтение `_Ctx.passport` и раскрыл это — спрашивать отчёт о нарушениях.
- Инъекции: прогноз лида до прогона; прогнозы по «сколько тестов упадёт» заниженные (перекрытие слепых и авторских) — прогнозировать ПРИСУТСТВИЕ ключевых, не точный набор; проверять, что мутация действительно меняет эффект (J11: строка записи ключа обратно).
- Основное дерево может стоять на чужой ветке (было `chore/subagent-cheap-defaults`): коммитить в `main` через detached worktree + `git merge --ff-only` или проверять `git branch --show-current`; файлы владельца не трогать (неотслеженные/изменённые: `.claude/memory/*`, `docs/reports/2026-10-26_stage0-eval.md`, `docs/handoffs/2026-11-09_status-to-1.0-and-start-prompts.md`).
- Тесты — через `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" medium <session> <cmd…>`; в worktree — `.venv` основного дерева + `PYTHONPATH=<worktree>`, не `uv sync`.
- Живые прогоны, повтор C0 (3 сессии Haiku), Kill-3 (7.2b), справка `atlas` ×3 — ТОЛЬКО по слову владельца; закрытие 6.1 без сработавшего kill — только явной записью владельца; не пушить.

## Рабочие места и агенты
- Worktree: `atlas-4-2b-1` (GREEN, живой), `atlas-4-2b-1-tester`, старые `atlas-4-1`, `-4-1b`, `-4-2a*`; уборка — чат «Git · push и уборка».
- Агенты (agentId): stage 0 4.2b-1 `a3622a13e29a85080`; INTERFACE 4.2b-1 `a51f80c338b455fe2`; tester 4.2b-1 `aa2acd6cbf7b37368`; GREEN 4.2b-1 `af0fbc859729a1759`; инъекции 4.2b-1 `af8a1d5dc88c5feb0`; ревью 4.2b-1 `aabdd2cd372f9772a`; stage 0 4.2b-2: sonnet `ae2cac134a671296e`, opus `a84089bcba20eca71`. Потерянные — свежий агент с отчётом и диффом.
- Scratchpad предыдущей сессии: `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/7f7bb259-d7e8-4333-a17f-2a3998784630/scratchpad/` (сообщения коммитов `msg42*.txt`, прогнозы/скрипты инъекций `inj42b1/`, прототипы ревьюеров `s0r42b2/`, `r3/`); скрипты гейта A/B — `…/f8e98ab0-504b-47c5-8acb-c1cccd047512/scratchpad/ab_scan.py`, `scan_a1.py`.

## Что осталось открытым / ненадёжно
- Ред. 4 `4.2b-2.md`/`map-form.md` не перепроверена; значения ключей формы (бюджет 60, `layer` = id юнита, `doc_missing` = нет `README.md` среди `docs`, `top` ≤ 6) — решения лида.
- Время тёплого `map process_module` ≤ 2,0 с — расчёт по частям на загруженной машине (≈ 1,8–1,95 с), не замер.
- Полнота `used_by` файла через реэкспорт `__init__` не измерена; A6 с исправленным `used_by` до конца не воспроизведён (вложенный юнит `prototype/frontend/widgets`).
- Предел argv Windows 32 767 байт — из знания, не измерен.
- Прочее по плану: 6.1 ждёт решения владельца (счёт kill №2 ненадёжен); проход Fable 5.2 (рекомендация: один проход по полосе после 4.2b-2 до платных прогонов, второй при закрытии плана) — ответа владельца нет; долги 4.1/4.1b/4.2a в `4.2a.result.md`; карта `atlas-plan-map.html` не обновлялась; порог строк плана 18 303 превышен (в result — число).
