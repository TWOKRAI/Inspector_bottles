---
date: 2026-10-05
topic: commit-mechanism — 9 из 11; осталось 3.2 (замер до 10-12) и 3.1 (не раньше 10-13)
machine: Windows
branch: feat/commit-mechanism (worktree .claude/worktrees/commit-mech) = main
---

## Состояние

- В `main`: фазы 1–2; Task 3.0 — единая грамматика id в пяти носителях (`2e4877a6e`); Task 1.5 — хук форматирования
  не запускает Python на не-`.py` (`d267dc89e`). План — 9 из 11.
- Решения владельца 2026-10-05 и согласия сессий (Атлас, dashboard) — `plans/2026-10-03_commit-mechanism/amendments.md`.
- `~/.claude/settings.json` этой машины: `cleanupPeriodDays: 365`, `env.CLAUDE_PYTHON_BIN = python` (хуки не пробуют
  заглушку `python3` Microsoft Store, минус ~95 мс на запуск хука). В `.claude/settings.local.json` НЕ класть: файл общий
  с Mac и на Windows скрыт `skip-worktree` — слияние с его правкой упирается в флаг (OPEN_QUESTIONS:1497).
  Проверить в новой сессии: `echo $CLAUDE_PYTHON_BIN` → `python`.

## Next step

1. **3.2 замер** после 2026-10-12: `python scripts/commit_audit/classify.py --root C:\Users\INNOTECH\.claude\projects
   --since 2026-10-05 --until 2026-10-12`; сравнить с базой (amendments.md, «База замера 3.2»); решение о `commit.py`
   по правилу CTO (A1-Bash + C2 + C4 на 100 commit, база 4,89, порог 3).
2. **3.1** не раньше 2026-10-13: спека `tasks/3.1.md` ред. 3 прошла стадию 0 (2 раунда); дальше слепой тестер (только
   склейка) → developer → инъекции → ревью. Перед слиянием — сообщение соседям по `ListAgents` (правило `-F`).
   CI Атласа 0.2 читает ту же константу `STRICT` (валидатор из базы PR).

## Open

- Открытые вопросы плана (раздел «Открытые вопросы» plan.md): пункты порядка `plans_ledger` без тестов на новых формах id;
  устаревшие хеши манифестов; хук форматирования переформатирует сид-копию валидатора; видимый выигрыш 1.5 на `.md`.
- Сид-копии (`.claude/plugins/…`: валидатор, `plans_ledger`, хук 1.5) — перенести в devseed на Mac, иначе
  `claude-kit upgrade` откатит.
- CI: в detached HEAD правило Refs не срабатывает — кандидат `GITHUB_HEAD_REF`; чья задача — с Атласом.

## agentId (сессия 2026-10-05)

| Роль | agentId | Что знает |
|---|---|---|
| reviewer 3.0 (стадия 0 + код) | `a1e0ad0ae5022a5bf` | грамматика, замеры корпуса |
| reviewer 3.1 (стадия 0) | `a6ced34f42c065efb` | склейка, git interpret-trailers, раскладки редактора |
| developer 3.0 | `a1a6fa6d4efc8e80b` | пять носителей грамматики |
| reviewer 1.5 | `a2b3ffe8a5aece30a` | хук, payload, тайминги |
