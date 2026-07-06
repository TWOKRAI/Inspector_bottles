---
description: Opt-in weekly dependency bump — uv lock --upgrade, run the suite, ai-judge gate on green, open a DRAFT PR (human merges). Falls back to gh CLI / stdout diff. Never auto-runs, never merges.
---

**Opt-in weekly dep-bump.** Команда обновляет залоченные зависимости, прогоняет тесты,
и при зелёном вердикте открывает **draft PR** — но **никогда не мёрджит**. Мёрдж —
решение человека (`human-merges`).

> **OPT-IN — не запускается автоматически.** Выполняется **только** по явному вызову
> `/dev:dep-bump`. Не зарегистрирована ни в каком hook, cron или scheduled-агенте.
> «Еженедельно» = человек запускает её раз в неделю, а не harness по таймеру. Граница
> ответственности: **агент создаёт draft PR, человек ревьюит и мёрджит** (ROADMAP § E.4,
> человек на необратимом). Команда сама `git push`/merge в `main` не делает.

Аргумент: $ARGUMENTS — опц. конкретные пакеты (`--upgrade-package <name>`). Пусто = полный `--upgrade`.

## Цикл

**1. Ветка** — отделись от свежего `main`, чтобы bump не висел на рабочей ветке:
`git checkout main && git pull --ff-only && git checkout -b chore/dep-bump-<YYYY-MM-DD>`.

**2. Upgrade lock** — перересолви зависимости:
- Полный: `uv lock --upgrade`
- Точечный: `uv lock --upgrade-package <name>` (из $ARGUMENTS).
Зафиксируй diff `uv.lock` (`git diff uv.lock`) — это машинный сигнал для судьи (что и куда поднялось).

**3. Sync + suite** — установи новый lock и прогони весь suite:
`uv sync && uv run pytest tests/ -q` (scoped, не bare — см. `_stack.md`).
Захвати вывод в файл: `... 2>&1 | tee /tmp/depbump_out.txt`.

**4. ai-judge gate (зелёные тесты + нет breaking = PASS)** — запусти агента **ai-judge**
(Opus, fresh context) с машинным сигналом = `/tmp/depbump_out.txt` (результат suite) +
`git diff uv.lock` (что поднялось). Судья выдаёт один вердикт:
- `VERDICT: PASS` → suite зелёный **и** в diff нет рискованных major-скачков без подтверждения →
  переходи к draft PR.
- `VERDICT: BLOCK` → suite красный, либо major-bump с вероятным breaking change → **СТОП**:
  не создавай PR, выведи отчёт (что упало / какой пакет рисковый). Дальше — человек:
  откатить пакет (`--upgrade-package` точечно) или чинить через `/dev:debug`.

ai-judge здесь — bounded owner gate-решения (см. `agents/ai-judge.md`): он судит сигнал
(suite + lock-diff), он не правит зависимости и не мёрджит.

**5. Commit + draft PR (human-merges)** — только при `VERDICT: PASS`:
- Коммит: `chore(deps): weekly dependency bump (uv lock --upgrade)` с телом — список
  поднятых пакетов `name old → new` из `uv.lock` diff.
- Открой **draft** PR в `main` (3-уровневый fallback):
  1. **github MCP** доступен (`enabled.yaml` → `github`) → создай PR через MCP с флагом draft.
  2. Иначе **`gh` CLI**: `gh pr create --draft --base main --title "chore(deps): weekly dependency bump" --body <…>`.
  3. **Fallback (нет ни github MCP, ни `gh`)**: НЕ создавай PR. Выведи в stdout:
     `git diff main...HEAD --stat` + список bump'ов + готовую инструкцию:
     «PR не создан автоматически (github MCP / gh CLI недоступны). Запушь ветку
     `chore/dep-bump-<date>` и открой draft PR в `main` вручную.» Это не ошибка — это
     graceful degrade.

PR создаётся **draft** намеренно: человек ревьюит changelog'и поднятых пакетов и сам
переводит из draft в ready + мёрджит.

## Отчёт

- `VERDICT`: `PASS` (draft PR #N создан / инструкция выведена) / `BLOCK` (что упало или рисковый пакет).
- Поднятые пакеты: `name old → new` (особо пометь major-скачки).
- Suite: passed/failed.
- Следующий шаг для человека: ссылка на draft PR или команда запушить ветку.

## Когда вызывать

- Раз в неделю / перед спринтом — подтянуть патчи безопасности и minor-обновления под защитой suite.
- После долгой паузы в проекте — разовый контролируемый bump с draft PR на ревью.

## Когда НЕ вызывать

- Нужен конкретный пакет под фичу → ставь его напрямую (`uv add <pkg>`), это не «weekly bump».
- Suite уже красный до bump'а → сначала `/dev:test-triage` / `/dev:debug`, не маскируй падения апгрейдом.
- Нужно немедленно влить в `main` без ревью — **намеренно не поддерживается** (human-merges, только draft PR).

Пакеты / фокус: $ARGUMENTS
