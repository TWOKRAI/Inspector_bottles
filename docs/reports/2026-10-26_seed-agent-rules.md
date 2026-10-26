# Передача в claude_seed: правила агентов по статье о субагентах (2026-10-26)

Откуда: Inspector_bottles, сессия «Процессы · правила агентов» (inspector-bottles-60).
Коммиты в Inspector_bottles: `232f78c97` (правило «один исполнитель»), `a72dffe24` (аудит противоречий).
Патч для seed: [`2026-10-26_seed-agent-rules.patch`](2026-10-26_seed-agent-rules.patch) — 3 команды шаблона
(`dev/commands/{pipeline,team,debug}.md`), `git -C claude_seed apply --check` → exit 0 (проверено 2026-10-26 на
`8038b4c`, после правок по ревью р.1). Остальное — правками по смыслу ниже: в seed эти файлы написаны иначе.

## Зачем seed это нужно

`claude-kit upgrade --apply` перезаписывает в проекте `project-rules`, `team-protocol` и команды `dev/*`.
Пока seed не примет правку, следующий upgrade в Inspector_bottles молча вернёт старую цепочку
`tester FAIL → debugger`. Сохраняется только `.claude/CLAUDE.md`.

## Источник

Anthropic, «Building agents: When to fold subagents into your main agent loop»
(claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop).
Прочитана дважды (WebFetch даёт пересказ; цитаты короткие и сверены вторым запросом):
- субагенты сильны в «verification, parallel work, and modular permissioning»;
- деление «by problem type» ведёт к «telephone game» — каждая передача теряет точность;
- совет — «dividing by context»: кусок работы, которому мало нужно от остальной системы, и короткий итог;
- «Frankenprompt» — правила от разных авторов в одном промпте противоречат друг другу.

Отдельного раздела «When to keep subagents» в статье нет — этот список во введении.

## Изменение 1 — один исполнитель на задачу

Правило: автор задачи (`developer` / `teamlead`) сам разбирает каждый красный против своего кода,
в том числе красный слепого тестера (решает, неверен код или тест, и показывает доказательство),
и пишет патчи инъекций по предсказаниям лида. Лид вызывает его повторно по agentId. `debugger` —
только для кода, который не писал ни один агент задачи, или после 2-й неудачной итерации автора.
`tester` и `reviewer` остаются независимыми.

Довод в числах (Inspector_bottles):
- задача 1.9b: developer 221k → новый debugger 146k (причина красного — стенд тестера, не код) →
  новый developer на патчи инъекций 124k = **491k** на одних файлах;
- новый агент платит за вход 107–228k, повторный вызов +3…56k (30 запусков, ~3.0M токенов);
- замер Д47: один developer, сам пишущий красные, 92–105k против 210–237k у пары tester → developer.

В патче: `dev/commands/pipeline.md` (итерации FAIL, граф, правило), `dev/commands/team.md` (сборка команды, §7
инъекций), `dev/commands/debug.md` («Automatic activation»).

**Вручную (в seed другой текст, патч не ложится):**

| Файл seed | Строка сейчас | На что заменить по смыслу |
|---|---|---|
| `dev/skills/team-protocol/SKILL.md:28` | S5 «FAIL → debugger loop» | «FAIL → back to the author» |
| `dev/skills/team-protocol/SKILL.md:56` | «`tester`(FAIL) → `debugger` → `developer` → `tester`(retry)» | «→ the same author re-summoned (diagnosis + fix) → `tester`(retry); 3rd iteration: one `debugger` diagnosis, still red → `teamlead`; code no agent of the task wrote → `debugger` from the start» |
| `dev/modes/dev.md:10` | «(debugger on FAIL)» | «(author re-summoned on FAIL)» |
| `dev/modes/dev.md:24` | «failure-recovery via the debugger» | «failure-recovery through the author (`project-rules` §5)» |
| `dev/skills/project-rules/SKILL.md` §5 | — | вставить пункт ниже после «Apply every instruction…» |

```
- **One executor per task.** The implementer (`developer` / `teamlead`) owns its files end to
  end: the code, the diagnosis of every red against it (a blind tester's red too: it works out
  whether the code or the test is wrong and shows the evidence: failing assertion, spec line; it
  changes its own code and tests only and never edits, deletes, skips or xfails a blind tester's
  test or `interface.py`; a red it judges a wrong test goes to the lead, who decides), and the
  injection patches on its files from the lead's predictions. The lead re-summons the author by
  agentId (`SendMessage`); no second role on the same files. `debugger` from the start for code
  no agent of this task wrote; on the author's 3rd iteration on the same red, one `debugger`
  diagnosis (report only), still red → `teamlead`. `tester` and `reviewer` stay independent and
  fresh. Split agents by context (a self-contained piece that returns a compact result), never
  by role over the same files.
```

Ревью р.1 (Sonnet) нашло, что первая редакция позволяла прочитать правило как «автор правит тест тестера»;
текст выше это закрывает — переносить именно его.

## Изменение 2 — противоречия, найденные аудитом

- Инъекции: `team-protocol` S4 и `team.md` §7 говорили «never delegated / Not delegated», а правила
  проекта с 2026-10-12 отдают механический прогон агенту. Теперь: предсказания и вердикт — лид, прогон — агент
  с этими предсказаниями (в патче).
- Для `claude-md.template.md` (если там есть похожее, — не в патче):
  - фоновые субагенты и вложенность до 3 уровней — по документации верно (code.claude.com `sub-agents`);
    «фоновый агент сам коммитит, пушит и открывает PR» в документации **нет** — писать как наблюдение;
    версию «2.1.212+» документация не подтверждает (desktop/VS Code — 2.1.302);
  - MCP tool search включён по умолчанию; `ENABLE_TOOL_SEARCH=true` = как без переменной;
    `false` — только если шлюз отклоняет запросы;
  - имена slash-команд в шпаргалке — настоящие пути `.claude/commands/` (`/core:team:wrap-up`, не `/wrap-up`).
- Глобальный `~/.claude/CLAUDE.md` владельца поправлен так же (Debugger, Reviewer, Tester — «проект может требовать больше»).

## Не переносить (только для Inspector_bottles)

«Model by class» (Sonnet-ревьюер, пилот стадии 0 на Sonnet), машинный гейт и координатор, имена ролей проекта.

## Открыто

- Пилот стадии 0 (Sonnet против Opus) ещё не оценён: эталонный набор собирается, прогон ждёт «да» владельца.
- `dev/commands/pipeline.md` в Inspector_bottles 34,4 КБ при бюджете 32 КБ (было до правки); qex и graphify не индексируют хвост.
- Экономия на задачу (~150–250k) — оценка по прошлым замерам, не замер после правила.
