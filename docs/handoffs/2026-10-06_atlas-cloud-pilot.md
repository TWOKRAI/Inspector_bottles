# Handoff — Атлас: настройка облака и пилот P1.1 (2026-10-06)

Для новой сессии, которая с владельцем настраивает облачные сессии Claude Code и проводит пилот P1.1.
Лид Атласа (сессия `inspector-bottles-65`, через `ListAgents`) продолжает 2.4g в
`.claude/worktrees/atlas-memory` — это дерево и ветку `feat/atlas-memory` не трогать.

## Прочитать первым

1. `plans/2026-10-04_atlas/CLOUD.md` — что делается в облаке, что локально, правила облачной сессии, соседи, порядок.
2. `plans/2026-10-04_atlas/tasks/P1.1.md` — бриф пилота (его выполняет облачная сессия, не ты).
3. `scripts/cloud/setup.sh` — setup script окружения (повторяет job CI `tests`).
4. `plans/2026-10-04_atlas/plan.md` → «Бюджет», «Правила исполнения», Phase P и Phase 1.

## Состояние на момент передачи

- `main` на origin: `ed96715d0` (бриф P1.1, `setup.sh`, `CLOUD.md`). CI на `main` зелёный (прогон 37366975842, попытка 2).
- Локально в `main` не запушены: `8b413017b` (кредит проверен — `CLOUD.md`), `25883b241` (агент `memory-classifier`
  для 2.4g). Пилоту они не нужны; push — по правилу ниже.
- Кредит проверен владельцем (страница Billing): $250, **тратится на облачные сессии первым**, лимиты плана — после;
  срок **2026-11-05 10:59 МСК**. Облако экономит.
- Сведения о cloud из документации (агент claude-code-guide, 2026-10-06): Ubuntu 24.04; setup script кэшируется,
  если укладывается в ~5 мин; `CLAUDE_CODE_REMOTE=true` в облаке; `.claude/settings.json` (хуки), `.claude/agents/`,
  `.mcp.json`, `CLAUDE.md` в облаке действуют; пользовательский `~/.claude/` — нет; субагенты и `model:` работают;
  облачная сессия **может** пушить в `main` (прокси блокирует только force-push); сессию можно забрать локально
  `claude --teleport <id>`.

## Шаги владельца — где остановились

| шаг | статус |
|---|---|
| GitHub App Claude установлен, доступ к репозиториям | сделано, но **на все репозитории** — посоветовано сузить: GitHub → Settings → Applications → Installed GitHub Apps → Claude → Configure → Only select repositories → `TWOKRAI/Inspector_bottles`. Подтверди у владельца |
| Ruleset `protect-main` (Settings → Rules → Rulesets) | форма заполнена верно (Active; Bypass — Repository admin; цель Default; Restrict creations, Restrict deletions, Require a pull request (0 approvals), Block force pushes), но **Create дал «Unauthorized»**. Версии: устаревшая сессия страницы (F5 и заново) или вход не под TWOKRAI. Подтверди результат |
| Окружение claude.ai/code | не подтверждено: Network `Trusted`; env `QT_QPA_PLATFORM=offscreen`; setup script `bash scripts/cloud/setup.sh` |
| Пилот | не запущен |

Ruleset с «Require a pull request» и Bypass = Repository admin: push лида в `main` под аккаунтом владельца проходит;
прямой push облачной сессии (GitHub App) — отклоняется. Проверить после создания: `git push` лида в `main` не сломан.

## Запуск пилота

Владелец: новая облачная сессия на `main`, текст — «Выполни `plans/2026-10-04_atlas/tasks/P1.1.md`. Это разведка: код
не правь, итог — один файл и PR». Первые 5 минут — наблюдать.

**Главный риск старта:** `.mcp.json` подключает 6 локальных серверов (sentrux, serena, qex, qt-mcp, backend-ctl,
graphify), а `.claude/settings.json` ставит `MCP_TIMEOUT=7200000` (2 ч). Отсутствующий бинарь обычно падает сразу,
но `uv run --no-sync … python …` (qex, qt-mcp, backend-ctl) может стартовать и висеть. Сессия не начала работу за
5 мин → остановить, скриншот; варианты починки — гард по `CLAUDE_CODE_REMOTE` в лаунчерах или отдельная правка
`.mcp.json` (это `.claude/`-уровень и общий для всех сессий файл — сначала договориться с лидом Атласа).

## Когда пилот сдаст PR

1. Прочитать `plans/2026-10-04_atlas/tasks/P1.1.result.md` из ветки `atlas/p1.1` (PR «atlas P1.1 — облачный пилот»):
   пять проверок, «что сломано и чем чинится», цена. Логи CI PR — по job, не по прогону; job `commits` должен быть
   зелёным (трейлеры).
2. Цена = $250 минус остаток на странице Billing после сессии (скриншот владельца) + `subagent_tokens` из итога.
3. Пересмотреть таблицу «что где» в `CLOUD.md` (правило: облачная задача Phase 1 дороже ~$3 или что-то из пяти
   проверок не работает → пересмотр до старта 1.2). Поломки облака — по одной строке в `docs/claude/OPEN_QUESTIONS.md`
   или задачей в плане, не чинить молча.
4. Строка P1.1 в `plan.md` → `[DONE <дата>]` с ссылкой на итог (слово статуса только из набора парсера: `READY`
   ломает `plans_progress --check` — проверено).
5. Слияние PR P1.1 — только итог-файл; через merge в GitHub или локально `merge:` + `Why/Layer/Refs` (корневой
   `CLAUDE.md` → «Формат commit-сообщений»).

## Правила, которые нельзя нарушать

- Ответы владельцу — по-русски. Push в origin — только после договорённости с живыми сессиями (`ListAgents` →
  сообщение каждой → ответ); `--force`, `--no-verify`, `git add -A`, голый `git stash` — нет; `git checkout -- <file>`
  запрещён разрешениями.
- Один писатель на дерево: в main-checkout перед коммитом — `git rev-parse -q --verify MERGE_HEAD` пусто, явные пути.
- Хук `protect-branch.sh` ловит только команду, начинающуюся с `git commit` (составная `git add … && git commit`
  проходит; push не проверяет) — `docs/claude/OPEN_QUESTIONS.md`. Не полагаться на него как на защиту `main`.
- Phase 1 в облаке — только после итога P1.1 и задач 0.5 → 0.7 → 1.1 (локально, у лида Атласа). Срок Phase 1 —
  ~2026-10-14, иначе Phase 4 выходит за кредит.

## Соседи (на 2026-10-06)

- `inspector-bottles-65` — лид Атласа, 2.4g (память), worktree `atlas-memory`; push `main` согласовывать с ним.
- `inspector-bottles-aa` — полоса Ж (lifecycle), `.claude/worktrees/lifecycle`; слияние T1 в `main` не скоро.
- `inspector-bottles-ef` — plans-progress, ветка `feat/plans-progress-61`; слияние позже, с предупреждением.
