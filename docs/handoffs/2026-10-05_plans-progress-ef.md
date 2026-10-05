# Handoff лида: plans-progress-dashboard, сессия ef (2026-10-05)

План: `plans/2026-10-02_plans-progress-dashboard/plan.md`. Прежний handoff: `2026-10-05_plans-progress-a9.md`.
Итог: **22 из 31** задачи DONE (1.3 — SUPERSEDED, вне счёта). Осталось 9: 4.2–4.4, 6.1–6.5, 7.1.

## Сделано и влито в `main`

| Задача | Слияние / коммит | Итог |
|---|---|---|
| 5.6 радар пересечений | `f01776e28` | `tasks/5.6.result.md`: 14 инъекций (M1 — эквивалентный мутант), ревью кода 2 раунда (ред. 2: пара с общей историей считается от своей merge-base), 1984 passed на слиянии со свежим `main`; живое дерево 30d — 0 пересечений |
| 1.3 отчёт `robot-protocol-v2` | `752d4ba84` | SUPERSEDED: `--json` 13 из 36 по тем же id, что выполнены в `ORDER.md` §2 Р |
| 5.4 `plan.ref` | `9d28c2978` | правило в `.claude/plugins/core/agents/_WORKTREE_PATTERN.md` + `/dev:team` шаг 2; ревью 2 раунда; `extensions.worktreeConfig` уже был включён, резолвер 5.2 читал `plan.ref` |
| Phase 7 «Одно окно» | `9d28c2978` | по вердикту CTO (Атлас, `plans/2026-10-04_atlas/research/CTO_VERDICT.md`, дополнение 2026-10-05): Task 7.1, строка Out of scope; «Открытые вопросы» плана → `docs/claude/OPEN_QUESTIONS.md`, раздел «plans-progress: нерешённое» |

Также: отчёт developer 5.6 → `docs/reviews/` (`89a096c1e`); память тестера 5.6 перенесена в главное дерево **без коммита** (там же незакоммиченные строки другой сессии); урок в `docs/claude/memory/feedback_inject_only_after_the_work_is_committed.md` (`a76804a0a`).
Удалены worktree: `pp-33`, `pp-34`, `pp-41`, `pp-54`, `pp-56`, `red-34`, `red-41`, `red-56`. Ветки оставлены (судьба `red/*` — решение владельца).
Push: Атлас пушит `main` вместе со своим; на момент записи `origin/main` = `f01776e28`.

## Дальше

1. **Task 7.1** — без внешних условий; должна быть до Атласа 3.1 (стык 7 в `ORDER.md`: путь файла и якоря — контракт). Условие CTO: в `scripts/plans_progress/` ноль строк чтения atlas — `grep -c atlas` на каждом ревью. Спека `tasks/7.1.md` ещё нет.
2. Фаза 6 — черновик; четыре решения владельца до 6.3 (JS на странице и др., `design.md`). 6.5 ждёт 6.1 (5.4 закрыта, §7 `team-protocol` уже в `main`).
3. 4.2–4.4 ждут путь к claude-kit от владельца; один дом сида — `.claude/plugins/core/scripts/`, наша 4.4 первая, Атлас 5.2 позже.

## Открыто

- 5.6, minor (ревью раунд 2): перекрёстная история — `git merge-base` без `--all`; ложная строка, если обе сестринские ветки влили один новый `main`. Живых случаев 0. Исправление ~5 строк + тест — `tasks/5.6.result.md`.
- 5.4: куда пишут журнал агент с `isolation: "worktree"`, сессия после `EnterWorktree`, teammate Agent Teams — не проверено; строка `plan.ref` в бриф `/dev:pipeline` — отдельной задачей (`OPEN_QUESTIONS.md`).
- `ORDER.md` ~191: `⛔ 5.4 … после слияния Атласа 2.4b + 2.4c` устарело (5.4 DONE) — вне блока прогресса, правит сверка очереди.
- Посмотреть радар глазами на живом дереве нельзя (0 пересечений, секция только при N > 0) — демо-фикстура по запросу.

## Ловушки сессии

- Субагенты прошлой сессии по agentId не возобновляются («No transcript found») — новая сессия зовёт свежих.
- Хук `lint-brief` отклоняет бриф developer без DESIGN/FILES/REDS/REPORT — форма `.claude/plugins/dev/templates/executor-brief.md`.
- Не удалять worktree, стоя в нём: `git worktree remove` снимает метаданные, каталог остаётся (`Permission denied`) — сменить cwd, затем `rmdir`.
- Журнал агентов пишется в дерево **сессии**: `Agent` из главного дерева не делает worktree активным на доске.

## agentId (эта сессия)

| Роль | agentId | Состояние |
|---|---|---|
| reviewer 5.6 (код, 2 раунда) | `a8e9e175a43e987a0` | закрыт |
| developer 5.6 ред. 2 | `a29fbe92e7d1fd99f` | закрыт |
| reviewer 5.4 (2 раунда) | `a65549550d56ff9fd` | закрыт |
