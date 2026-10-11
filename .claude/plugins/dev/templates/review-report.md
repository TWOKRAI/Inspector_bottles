# Review report — form for `reports/<id>.review-r<N>.md` and `reports/<id>.review-code-r<N>.md`

The reviewer's final message, saved by the lead verbatim: `plans/<plan>/reports/<id>.review-r<N>.md` for stage 0
(`MODE: plan`), `reports/<id>.review-code-r<N>.md` for the review after code; N from 1. The format is ADR-ATL-004 §5
(`scripts/atlas/DECISIONS.md`). The lead's spawn prompt names this file for both review kinds — `reviewer.md` does
not carry the form yet (its categories `spec`…`tests` may appear in a finding's text; the class goes in the tag).

**Readers:** `atlas metrics` (1.9f: M2 = blocker+major of classes fact, dryrun, form in round 1; M3 = rounds to
APPROVED). Contract test: `scripts/atlas/tests/test_formats_1_9d.py::test_review_example_counts_match_header` reads
the example below.

## Rules

- Lines 1–4, exactly (all seven classes in this order, zeros written, nothing after the numbers):
  `# <id> — ревью <стадии 0|после кода>, раунд <N>`;
  `Вердикт: APPROVED` or `Вердикт: CHANGES REQUESTED`;
  `Итог: blocker <n>, major <n>, minor <n>, nit <n>`;
  `Классы: fact <n>, dryrun <n>, form <n>, context <n>, design <n>, scope <n>, process <n>`.
- `## Замечания`: one finding = one item `- [<severity>/<class>] <text>`; continuation lines indented two spaces.
  Severity ∈ blocker, major, minor, nit. The counts per severity equal `Итог`, per class equal `Классы`. A line
  starting `- [` that does not fit is a violation. A finding carries `input → observed output`; without one it says
  «совещательно».
- Classes, in precedence order — when several fit, take the first:
  1. `fact` — a stated number, path, `file:line`, name or command output does not match the repo;
  2. `dryrun` — the plan does not run as written: a command, test or injection fails or checks the wrong thing;
  3. `form` — the text breaks its own format or reads two ways for the executor;
  4. `context` — the brief misses a consumer, a neighbour, a past task's tail, a project rule or lesson;
  5. `design` — the decision itself is wrong or incomplete: race, order, API boundary, mechanism;
  6. `scope` — task boundary: too much, too little, overlap with another task;
  7. `process` — stage order, tester / injection / review / commit rules.
  `nit` is a severity only, never a class.
- Other sections are free; `## Что я оставил открытым / ненадёжным` is required and non-empty.

## Example

````markdown
# 1.2 — ревью стадии 0, раунд 1
Вердикт: CHANGES REQUESTED
Итог: blocker 0, major 2, minor 1, nit 1
Классы: fact 1, dryrun 1, form 0, context 1, design 1, scope 0, process 0

## Замечания
- [major/dryrun] Тест «stop() сразу» не ловит инъекцию «без замка»: 3 прогона под инъекцией → `passed` 3 из 3.
  Исправить: пауза 0,2 с перед `stop()`; с ней красный 3 из 3.
- [major/design] Флаг ожидания снимается после чтения файла: вторая запись теряется (`CLEAR=after` → `cfg=v1`, файл `v2`).
  Исправить: снимать флаг до чтения; инъекция «флаг после чтения» с прогнозом.
- [minor/context] Ещё потребитель `_on_reload`: `app_module/tests/test_observability_watcher_events.py:75` — нет в радиусе.
- [nit/fact] `watcher.py:81–96` → факт 82–99 (`git grep -n "def _on_modified"`).

## Сверено и верно
- `orchestrator.py:166` — debounce не передаётся, умолчание 1,0 с.

## Что я оставил открытым / ненадёжным
- Windows не проверялся; прогоны короткие (N = 3).
````
