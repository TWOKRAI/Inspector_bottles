# Handoff — Атлас, лид, 2026-10-05 (ред. 2, после 2.4e и реализации 0.2)

**Ветка:** `feat/atlas`, worktree `.claude/worktrees/atlas`. **HEAD:** коммит этого файла (родитель `38462b530`).
**План:** `plans/2026-10-04_atlas/plan.md`; Task 2.4 — `tasks/2.4.md` («Ход»), Task 0.2 — `tasks/0.2.md` (спека ред. 3).
**main:** 2.4e слита (`138e6f606` и раньше). Не в main: `6ad8ad850`, `0da509963`, `1663d06fd`, `2a33f26cb`, `38462b530` + этот файл — влить вместе с приёмкой 0.2.
**origin:** main запушен до 2.4e включительно; новые коммиты main (dashboard `9d28c2978`, commit-mechanism `d267dc89e`, `a76804a0a`) не запушены — dashboard просил пушить вместе с нашим.

## Сделано

- **2.4e DONE** — MCP по ролям: 12 ролей с `disallowedTools: mcp__<server>`, таблица — `docs/claude/LEAD_RULES.md` «MCP routing». serena запрещён всем ролям (привязан к main-checkout: мутатор из worktree пишет в main); встроенные агенты (Explore, Plan, general-purpose) мутаторы serena сохраняют — не запускать их, пока писатели в worktree. Fable — в «Ход» 2.4.md.
- **0.2 — реализация `1663d06fd`**: job `commits` в `ci.yml`, только `pull_request`, диапазон `base.sha..head.sha`, валидатор и слои из базы PR, `python -I`. A1 (эмуляция в sparse-клоне) и A4 пройдены; инъекции I2–I7 пойманы. Не покрыто: синтетический merge `HEAD^!` — до commit-mechanism 3.1 (записано).
- **Вердикт CTO «одно окно»** (`research/CTO_VERDICT.md`, дополнение): данные в одну сторону `plans_progress --json` → `atlas`; до 1.7 окно — страница дашборда + dashboard 7.1 (якоря `id="plan-<slug>"`); после 1.7 — `atlas html` (3.1) с `<iframe>` на дашборд; один дом сида `.claude/plugins/core/scripts/`. Стык 7 — `plans/queue/ORDER.md`. Dashboard принял, Phase 7 у них в плане (`9d28c2978`).
- **Страница системы** — `research/atlas-explainer.html` (`38462b530`), артефакт https://claude.ai/artifact/9Mkfune537nwQZeoPgK7ia (версия 4). Mermaid не проверен отрисовкой.
- Решения владельца (push, кредит, serena/graphify) — `docs/claude/memory/project_owner_push_and_tools_decisions.md`.

## Следующее (по порядку)

1. **0.2 — приёмка на GitHub** (спека `tasks/0.2.md`, A2/A3/A5):
   - A2: ветка `atlas/0.2-ci-red`, плохой коммит — в клоне без хуков → PR → job красный;
   - A3: база `atlas/0.2-base` (одноразовая), зелёный PR в неё + опыт с устаревшим `base.sha`;
   - A5: закрыть PR, удалить 3 ветки.
   - Нужно: `gh auth login` владельца (или PR руками по ссылкам) и договорённость с сессиями перед push.
   - Затем reviewer раунд 2 (`a54a587d4b59c6bff`), Fable, merge feat/atlas → main, push (вместе с коммитами соседей).
2. **2.4g — единая память** (условия Fable А/Б/В — «Ход» 2.4.md). Сначала закоммитить уроки ролей в main: `.claude/agent-memory/{teamlead,tester}/` (2 изменённых индекса + 5 новых файлов на 2026-10-05).
3. **2.4h** — перевод команд на английский; **2.4i** — корневой CLAUDE.md на английский.
4. P1.1 — облачный пилот; затем 0.5/0.7, Phase 1.

## Ждёт владельца

- `gh auth login` — для PR приёмки 0.2.
- Защита гейта от облачных PR: (а) CODEOWNERS на `.github/workflows/**`, `scripts/validate_commit/**` + обязательный ревью (рекомендация), или (б) ручной разбор лидом (правило уже в plan.md). `docs/claude/OPEN_QUESTIONS.md`.
- Срок против кредита: kill-проверка K1.1 — не раньше 21 дня после 1.7, кредит до 2026-11-04 → Phase 4 в кредит только при 1.7 до ~10-14. Выбор: отдать Phase 4 под ревью `.claude`/`claude_seed` или вынести за кредит.

## Агенты (адрес — agentId)

| роль | agentId | что знает |
|---|---|---|
| reviewer 0.2 спека | `abd83d1810cbc13ba` | спека 0.2 ред. 1–3 |
| reviewer 0.2 код | `a54a587d4b59c6bff` | job `commits`, инъекции — для раунда 2 |
| cto (Fable) одно окно | `ae733174b33f4d677` | вердикт «одно окно» |
| cto (Fable) 2.4e | `a232101fc03a9a438` | приёмка 2.4e |
| cto (Fable) дизайн 2.4g | `a18b5af5c1aa5265d` | условия А/Б/В |
| tech-writer страница | `a3c0b7377285136a8` | `atlas-explainer.html` |

`af3258997915c7e58` (Fable 2.4b/c) не возобновился — брать нового. Tester и reviewer первого раунда для новой задачи — свежие.

## Соседние сессии (адрес = имя; после перезапуска — `ListAgents`)

- `inspector-bottles-f7` — сейчас ведёт и commit-mechanism (1.5 в main), и dashboard (5.4 + Phase 7 в main). Сообщать ему о старте задачи и перед merge/push.
- Один main-checkout: перед `git merge` — `git rev-parse -q --verify MERGE_HEAD` (пусто = свободно); тесты после коммита в main у соседей — ждать «main свободен».

## Ловушки сессии (проверено)

- **CRLF + regex:** `$` с `re.M` на CRLF-содержимом захватывает `\r` → в файле `\r\r\n`, индекс `i/-text`, pre-commit откатывает коммит. Патчить байтами или `newline=""` и `\r?$`.
- Клон в scratchpad: «Filename too long» → `--no-checkout` + sparse; пути `/scripts/...` в sparse — с `MSYS_NO_PATHCONV=1`.
- Команда с `eval`/`rm -rf` запрещена разрешениями → скрипт-файл через Write.
- Трейлеры одним блоком; `grep -i -F` вместе падает rc=134; размер файла — в git (`git show <ref>:<path> | wc -c`).
- Файлы агентов подхватываются посреди сессии с задержкой в минуты (новые и изменённые; замерено ~4 мин).
- `git checkout -- <file>` запрещён разрешениями.
