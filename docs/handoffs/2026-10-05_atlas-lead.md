# Handoff — Атлас, лид, 2026-10-05

**Ветка:** `feat/atlas`, worktree `.claude/worktrees/atlas`. **HEAD:** коммит этого файла (родитель `d3d024836`).
**План:** `plans/2026-10-04_atlas/plan.md`; Task 2.4 — `plans/2026-10-04_atlas/tasks/2.4.md` (раздел «Ход» — вся история, читать первым).
**main:** Атлас 2.4b + 2.4c слиты — `900012c69`. После слияния на ветке 5 коммитов (только план, язык, этот файл) — в `main` не влиты, влить вместе с 2.4e.

## Сделано в сессии 2026-10-04/05

- Проба `omitClaudeMd` (CC 2.1.289): снимает три CLAUDE.md, `~/.claude/rules`, индекс авто-памяти; память роли и `skills:` остаются.
- 2.4b: 14 агентов dev с флагом; ядро `project-rules` 8091 Б (предел поднят до 10 240 Б), карта `## Map`. Fable: NOT WORSE, замечания исполнены.
- 2.4c: корневой `CLAUDE.md` 12 155 Б, `.claude/CLAUDE.md` 13 946 Б; обоснования — `docs/claude/LEAD_RULES.md` (EN), `TOOLING_NOTES.md` (RU). Fable: BETTER.
- Task 0.1 DONE (`60cd0518e`): валидатор v2 сессии commit-mechanism в main (`06a70f7e6`), трейлер `Task:` виден git.
- `plans/queue/ORDER.md`: порядок трёх планов полосы М, таблица «Стыки М» (`f3ac41aec`).
- Решения владельца 2026-10-05: всё, что читает модель, — по-английски (2.4h, 2.4i); Science Company — изолированный плагин `knowledge`, согласовано с `claude_seed` Task 3.4 (`215ac46` в сиде); Haiku вместо локальной модели; метрики из встроенного OTel Claude Code (в plan.md, «Открытые вопросы»).

## Следующее (по порядку)

1. **2.4e — MCP по ролям** (developer, Sonnet). Спеки нет — написать по образцу 2.4b/2.4c: таблица «роль → серверы» из `enabled.yaml`, `disallowedTools: mcp__<server>` остальным. Стадия 0 — reviewer на текст, затем исполнитель, лид — грепы и инъекции, reviewer, Fable.
2. **2.4g — единая память** — дизайн принят Fable с условиями А/Б/В (урок = файл, индекс скриптом; словарь тегов; поиск по пути main-checkout). Условия — в «Ход» 2.4.md. Сначала закоммитить 6 незакоммиченных уроков ролей в main (`git status` в main: `.claude/agent-memory/{teamlead,tester}/`).
3. **2.4h — перевод** 77 команд `.claude/commands/**` и `TOOLING_NOTES.md` на английский.
4. **2.4i — корневой CLAUDE.md на английский**; строка `.claude/CLAUDE.md:116` (зоны планов) → `plans/`; одна копия плагина `knowledge`.
5. Влить хвост ветки в main вместе с 2.4e.

## Агенты (адрес — agentId; повторный вызов дешевле нового)

| роль | agentId | что знает |
|---|---|---|
| reviewer 2.4b (спека + код) | `abf8de80dace51952` | ядро, трасса 2.4b |
| reviewer 2.4c (спека + код) | `a7d86f775afdb98d4` | CLAUDE.md, команды приёмки A1–A13 |
| teamlead 2.4b | `acb3fc45bdd30c3c1` | контекст велик — для новой задачи брать нового |
| teamlead 2.4c | `a98c6471a76509ea4` | контекст велик — для новой задачи брать нового |
| cto (Fable) 2.4b/2.4c | `af3258997915c7e58` | вердикты, merge gate |
| cto (Fable) дизайн 2.4g | `a18b5af5c1aa5265d` | условия А/Б/В |

Reviewer и tester первого раунда для новой задачи — свежие относительно кода.

## Соседние сессии (адрес = имя; после перезапуска имена меняются — `ListAgents`)

- `inspector-bottles-f7` — commit-mechanism: 2.1 в main; делает 2.2 (документы в новые дома, одна копия `.claude/COMMIT_GUIDE.md`, правило «трейлеры одним блоком» во всех шаблонах).
- `inspector-bottles-a9` — plans-progress-dashboard: 4.1, 3.4, 5.5 в main; делает 5.6; 5.4 и 6.5 открыты (после Атласа).
- `inspector-bottles-e8` — назвался лидом dashboard; возможна вторая сессия на том же плане — сообщено обеим.
- Один main-checkout: перед `git merge` — `git rev-parse -q --verify MERGE_HEAD` (пусто = свободно).

## Ловушки сессии (проверено)

- **Трейлеры одним блоком.** Пустая строка перед `Co-Authored-By` прячет `Why/Layer/Refs/Task` от git (`%(trailers)` пуст). Так написаны все коммиты Атласа до `60cd0518e`, включая `900012c69`. Шаблон правит commit-mechanism 2.2.
- `grep -i -F` вместе в этом Git Bash падает rc=134 — нижний регистр через `tr`.
- Хук `lint-brief` не пускает `teamlead`/`tester` без формы `executor-brief.md`; для пробы — строка `BRIEF-OVERRIDE: <причина>`.
- Проба из worktree: `settings.local.json` из git держит `autoMemoryDirectory` с путём Mac — запускать `claude -p --settings <json с Windows-путём>`, иначе контроль ложно без памяти.
- Новые файлы агентов подхватываются посреди сессии с задержкой в минуты, не только при старте.
- Python на Windows пишет CRLF в текстовом режиме — для файлов с LF открывать с `newline=""`.
- `git checkout -- <file>` (сброс правок) в этой сессии запрещён разрешениями — не повторять, обходить.
- Размер файла мерить в git (`git show <ref>:<path> | wc -c`): рабочая копия с CRLF даёт +1 Б на строку.

## Открыто (владельцу)

- Push в `origin` — не делался; только по слову владельца.
- Песочницы Claude Code на нативной Windows нет — `docs/claude/OPEN_QUESTIONS.md`.
- Ручной pytest: корневой `CLAUDE.md` п.4 против `_stack.md:20` — `OPEN_QUESTIONS.md`.
