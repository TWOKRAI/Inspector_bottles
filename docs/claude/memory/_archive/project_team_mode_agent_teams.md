---
name: project-team-mode-agent-teams
description: "Командный режим агентов (2026-09-02): Agent Teams включён, /dev:team, cto=Fable и junior=Haiku добавлены, общие правила в skill project-rules, цепочка эскалации вверх, три хука-гейта; живой прогон команды ещё не делался"
metadata:
  node_type: memory
  type: project
  originSessionId: 2bef5f02-841d-4f66-86fc-b9d72ba30dce
  modified: 2026-09-03T06:01:15.602Z
---

Решение владельца 2026-09-02: разработка в режиме **живой команды** — агенты создаются один раз,
живут в сессии, делят список задач, переписываются по имени, отдают результат владельцу. Главная
сессия — PM (Opus, effort high по `.claude/settings.json`), Fable только в роли `cto`.

**Что стоит в конфиге (ветка `chore/agent-team-mode`, влита в `main` и в `feat/observability-closure`):**
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` в `env` `settings.json` (источник `plugins/core/settings.partial.json`), там же `model: opus`, `effortLevel: high`.
- Агенты: `cto` (Fable, xhigh, read-only, вердикты и верх эскалации), `junior` (Haiku, low, механика по готовому диффу, не коммитит). Лишних ролей нет: PM = лид, не агент.
- Общие правила всех 14 агентов — один skill `project-rules` (`plugins/dev/skills/project-rules/SKILL.md` → `.claude/skills/project-rules/`), подгружается через `skills:`; в агентах остался четырёхстрочный указатель. §7 skill — цепочка эскалации: junior/docs-writer → developer/tech-writer → teamlead → cto → владелец (через лида, в OPEN_QUESTIONS.md); формат `ESCALATION -> <role>` / Question / Tried / Blocked on / Files.
- Команда `/dev:team` (`plugins/dev/commands/team.md`) — протокол PM из девяти шагов; шаблон брифа `plugins/dev/templates/team-brief.md` с заметками под модели (Sonnet буквален — scope явно; Opus не просить перепроверять; Haiku — шаги и якоря; Fable — отчёты о ходе и батч вызовов).
- Хуки `plugins/dev/hooks/`: `TaskCompleted` (ruff + pytest на изменённых тестах; `[RED]`/`[docs]`/`[skip-gate]` пропуск), `TeammateIdle` (блок только в linked worktree), `SubagentStart/Stop` → `data/team-journal.jsonl`. Fail-open после двух блоков; `TEAM_GATES=off`.
- `.gitattributes`: `docs/sessions/*.md merge=union`.
- Руководство владельца: `docs/claude/AGENT_TEAMS_GUIDE.md` (что изменилось, как пользоваться, стоимость, ограничения движка, насколько лучше и почему).

**Ревью сделано** (reviewer, Opus, синхронно, 2026-09-02/03): 18 находок, блокеров нет, вердикт CHANGES → правки
внесены вторым коммитом `c595b252` (гейт только по префиксу `[RED]`, указатели у cto/junior, английский в
агентах, инвентари, потолки doctor); смоук хуков 16/16. Коммиты ветки: `14ab981b`, `c595b252`; merge в feat:
`f652607f`, `579f216b`. Ревьюер инъекцией подтвердил, что снятие `\r` в гейтах несущее (без него exit 0 вместо 2).

**Не проверено:** живая команда в сессии не запускалась (переменная подхватывается при старте);
preload `skills:` для in-process участников — по докам неясно, есть указатель-fallback; хуки
проверены только на синтетическом репозитории. Первый прогон — рецепт в руководстве §3:
tester + developer + reviewer на одной маленькой задаче, цель — проверить проводку, не фичу.

**Ограничения движка 2.1.222:** участники не переживают `/resume`; одна команда на сессию; без
вложенных команд и фоновых субагентов у участников; в Windows Terminal / VS Code только in-process
(↑/↓ + Enter, Esc, x, Ctrl+T); каждый участник — полная сессия, ~25k токенов до первого действия.

См. [[feedback_materialized_agents_drift_from_plugin_source]], [[feedback_model_economy_scheme]],
[[feedback_parallel_agents_commit_race]], [[feedback_tester_once_per_mechanism_before_the_code]].
