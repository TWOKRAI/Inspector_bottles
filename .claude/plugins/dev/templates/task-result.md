# Task result — form for `tasks/<id>.result.md`

Atlas parses this file (ADR-ATL-001: nodes `result`, `injection`; edges `reports`, `lists`, `breaks`), so the
headings and the table header below are a contract: keep them literally, in this order; an empty section says
`нет` (except `## Не проверено`, which is never empty). Required — the seven from `## Сделано` to `## Кому передано`
(`atlas lint-result <file>`, the PostToolUse hook `lint-result.sh`, finding `RESULT_FORM`); `## Для следующего брифа`
and `## Память` are optional. `atlas pack` of the next task prints `## Осталось`, `## Не проверено` and
`## Для следующего брифа` as tails (Task 1.9a).

Writers, in order, one at a time: the executor writes the file before its report; the lead then appends rows to
`## Инъекции` (its own break-injection) and fills `слияние:` after the merge. Nobody else edits it.

Budget: the prose sections (`## Сделано` … `## Кому передано`, without the injection table) ≤ 2 KB. The table and
`## Память` are outside it. Command outputs, reasoning, long lists go to
`docs/reviews/<YYYY-MM-DD>_task-<id>-<role>.md` (the path from `executor-brief.md` REPORT); name it under `## Файлы`.
Language: Russian prose (the owner reads it); headings, codes, paths, commands as below.

````markdown
# Task <id> — итог

## Сделано
- <outcome, one line each; every acceptance number with the command that produced it>

## Осталось
- <what the task promised and did not deliver | нет>

## Не проверено
- <what was claimed without a run that shows it, and why; at least one line — "всё проверено запуском" is not a line>

## Файлы
- <path> — <what changed>
- полный отчёт: docs/reviews/<file>.md | нет

## SHA
- <short SHA> <commit subject>
- слияние: <merge SHA in main | ещё нет>

## Инъекции
| инъекция | предсказано красных | наблюдалось | тест |
|---|---|---|---|
| <what was broken, file:line> | <N, written BEFORE the run> | <N> | <pytest nodeid>[, <nodeid>…] |

## Кому передано
- <role / session / next task id | нет>

## Для следующего брифа
- <what the next brief on these modules must know: a wrong fact, a trap, an open lead question | нет>

## Память
memory hits: <command> -> <paths> | none
MEMORY LESSON <name>.md: <full file text> | none
````

## Rules for the table `## Инъекции`

- One row = one injection = one claimed property broken on purpose (`.claude/CLAUDE.md` → «Test authorship»).
  Row order is the id: `<slug>#<id>/inj-<n>`, n from 1 — never reorder rows once committed.
- `предсказано красных` is written before the run; a mismatch with `наблюдалось` stays in the row and gets a line
  under `## Не проверено` — never edit the prediction afterwards.
- `тест` — full pytest nodeid(s) without parameters, comma-separated. `наблюдалось` > 0 means the named test(s)
  went red; Atlas raises `TEST_NEVER_RED` on a test named only in rows with 0.
- A task without injections (docs, plans) keeps the header and one row: `| нет | 0 | 0 | — |`.
- Tests that guard a declared guarantee carry `@pytest.mark.guards("G-<module>-NNN")` (ADR-ATL-001 §4); the
  guarantee link comes from the marker, not from this table.

## Rules for `## Память`

- `memory hits:` — the search command from `project-rules` §8 and its hits.
- `MEMORY LESSON <name>.md:` is followed either by `none` or by the full lesson text on the next lines inside a
  four-backtick fence (````) — lessons contain `## ` headings and 22 of them contain ``` themselves. Tags as `project-rules` §8 requires
  (`description:` RU+EN, `module:` ⊆ `modules.yaml`, `mechanism:` ⊆ `docs/claude/memory/TAGS.yaml`, `role:`).
- The lead writes the lesson into `docs/claude/memory/` and then replaces the fenced block with the file name — the
  lesson keeps one home. An executor never writes a lesson file.

## Known conflict

`plans_ledger.py` (`RESULT_TOO_BIG`) counts the whole file's bytes, not the prose sections; 18 of 37 results are
already over 2048 bytes. Until the ledger counts the prose only, it reports on files that follow this form.
