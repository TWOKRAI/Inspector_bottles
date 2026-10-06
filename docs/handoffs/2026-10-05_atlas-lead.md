# Handoff — Атлас, лид, 2026-10-05 (ред. 3, после 0.2 и 0.8)

**Ветка:** работа слита в `main` (`9ce2101b9`, merge 0.8). `feat/atlas` и `fix/atlas-ci-green` слиты; worktree `.claude/worktrees/atlas`, `ci-green`, `ci-green-tester` можно убрать после A6.
**План:** `plans/2026-10-04_atlas/plan.md`; итоги — `tasks/0.2.result.md`, `tasks/0.8.result.md`; Task 2.4 — `tasks/2.4.md` («Ход»).
**origin:** `main` запушен до `9ce2101b9` (после договорённости с соседями; им отправлено «main свободен»).

## Сделано

- **0.2 DONE** — job `commits` в `ci.yml` (только `pull_request`, диапазон `BASE..HEADSHA`, валидатор из базы PR, `python -I`). Приёмка на GitHub PR #2/#3 (PR создавал владелец вручную), reviewer р.2 APPROVED, Fable ACCEPT WITH CONDITIONS. Итог — `tasks/0.2.result.md`.
- **0.8 DONE** — CI на `main` впервые зелёный на Linux; `spawn` на всех ОС (решение владельца по замеру: старт +0,57 с на 4 ребёнка, USS +46 МБ на ребёнка, job `tests` 16:47 → 20:41).
  - Код: `setup_multiprocessing` по контракту (`None` → spawn, `spawn` → ничего, иное → `RuntimeError`), вызов первым в `SystemLauncher.__init__` и `ProcessSpawner.__init__`; conftest `pytest_configure`.
  - Три ошибки тестов, которые проявил первый прогон на Linux: object-массив (`tobytes` = адреса), окно hot_reload логгера, R2 — `resource_tracker` удаляет сегмент асинхронно.
  - PR #4 на `b5facd8ce` — все job `success` (прогон 37362092835). Windows 11002 passed, Linux 11037 passed. Итог — `tasks/0.8.result.md`.
- `plans/queue/ORDER.md`: строка стыка 7 и строка Атласа в §4.1.

## A6 — прогон `main` после слияния (закрыт 2026-10-06: попытка 2 — все job `success`)

- Push-прогон 37366975842 на `9ce2101b9`: все 4 job `cancelled` (19:59–20:14 UTC), `commits` и nightly — `skipped` штатно. Аннотация: «The job was not acquired by Runner of type hosted even after multiple attempts». githubstatus: инцидент Actions с 19:50 UTC. На 2026-10-06 Actions — `operational`, прогон не перезапущен.
- Нужно: «Re-run all jobs» на https://github.com/TWOKRAI/Inspector_bottles/actions/runs/37366975842 (вход под владельцем; API без токена перезапуск не умеет) → все job `success` → строка A6 в `tasks/0.8.result.md`.
- Если job `tests` покраснеет на одном тесте, которого не было на PR — сначала проверить, не тайминговый ли он (класс «впервые на Linux», см. ниже), прежде чем винить spawn.

## Следующее (по порядку)

1. A6 (выше).
2. **2.4g — единая память** (условия Fable А/Б/В — «Ход» 2.4.md). Сначала закоммитить уроки ролей: `.claude/agent-memory/{teamlead,tester}/` — 2 изменённых индекса + 6 новых файлов, лежат в main-checkout незакоммиченными (не мои, явными путями).
3. **2.4h** — команды на английский; **2.4i** — корневой CLAUDE.md на английский.
4. P1.1 — облачный пилот (после 0.2 и 0.8 — оба DONE); затем 0.5/0.7, Phase 1.

## Открытое (записано в `docs/claude/OPEN_QUESTIONS.md`)

- Гонка stale-store в кэше решений логгера (`logger_core.py:987` → `:1012`): реальная гонка фреймворка, лечение — счётчик поколений. Отдельная задача.
- Guard-job под `pull_request_target` вместо CODEOWNERS (у одного владельца CODEOWNERS не работает) — по вердикту Fable к 0.2.
- Число процессов `inspection_full` для пересчёта памяти spawn на Orin; живой прогон на Orin — владелец (`scripts/start_method_probe.py` оставлен для этого).
- Инъекции I2/I3 и страж порядка SIGINT проверяются только на Linux CI — локально не прогонялись.
- `plans/queue/ORDER.md` 55,8 КБ при бюджете 32 КБ.

## Ждёт владельца

- Re-run прогона 37366975842 (A6) — либо переподключить Chrome-расширение, тогда лид перезапустит сам.
- Срок против кредита: kill-проверка K1.1 — не раньше 21 дня после 1.7, кредит до 2026-11-04 (без изменений с ред. 2).

## Агенты (адрес — agentId)

| роль | agentId | что знает |
|---|---|---|
| developer 0.8 | `a911305261dcadd40` | 0.8a/0.8b, spawn везде |
| reviewer 0.8 | `a3ba6f353a3db6f08` | р.1–р.2, зонд прод-входов |
| reviewer спеки 0.8 | `a84466ea32feeefd7` | спека 0.8 ред. 1–2 |
| tester 0.8b (слепой) | `a0fe9c035de3fcad5` | `test_start_method_spawn_acceptance.py` |
| investigator CI | `adf38dcbe1d476d1c` | группы падений на Linux |
| investigator hot_reload | `aaf6c9eb59b3bcf24` | гонка stale-store |
| cto (Fable) commit-mechanism | `ae0ba7e1cb2a30b53` | оценка commit-mechanism |
| reviewer 0.2 код | `a54a587d4b59c6bff` | job `commits`, р.2 |
| cto (Fable) дизайн 2.4g | `a18b5af5c1aa5265d` | условия А/Б/В |
| tech-writer страница | `a3c0b7377285136a8` | `atlas-explainer.html` |

## Соседние сессии (адрес = имя; после перезапуска — `ListAgents`)

- `inspector-bottles-96` — трек Ж (lifecycle). `inspector-bottles-6f` — dashboard, на паузе. Эта сессия была `inspector-bottles-fe`.
- Один main-checkout: перед `git merge` — `git rev-parse -q --verify MERGE_HEAD` (пусто = свободно); push — только после договорённости.

## Ловушки сессии (проверено)

- **Worktree тестера:** «Filename too long» на `scripts/commit_audit/tests/fixtures/real/` → `git -c core.longpaths=true worktree add …`.
- **Восстановление через `git show <ref>:<path> > file`** даёт LF-копию, `git status` показывает `M` → писать байты с CRLF (или `newline=""`), потом сверить статус.
- **Тесты, впервые запущенные на Linux CI,** падают по таймингу (асинхронный `resource_tracker`, окно между записью конфига и сбросом кэша) — это ошибки тестов; ассерт на эффект с дедлайном, а не на мгновенное состояние.
- **GitHub без токена:** API 60 запросов в час; логи job — `403`, читать страницей Actions через Chrome, `fetch('/…/commit/<полный sha>/checks/<jobid>/logs')`, вывод санитизировать.
- **Итог CI читать по job, не по прогону:** `concurrency` с `cancel-in-progress` и сбои раннеров помечают прогон `cancelled`/`failure` без единого теста.
- **CRLF + regex:** `$` с `re.M` на CRLF захватывает `\r` → патчить байтами или `\r?$`.
- `git checkout -- <file>` запрещён разрешениями; команды с `eval`/`rm -rf` — скрипт-файлом через Write.
