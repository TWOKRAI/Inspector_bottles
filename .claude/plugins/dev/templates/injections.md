# Injections — form for `tasks/<id>.injections.json`

The lead's break-injection matrix (`.claude/CLAUDE.md` → «Test authorship»): one object = one claimed property broken
on purpose. The format is ADR-ATL-004 §3 (`scripts/atlas/DECISIONS.md`).

**Writers:** the lead writes `id`, `prop`, `forecast`, `test` BEFORE the run; the author of the task writes `file`, `old`, `new` from them (`project-rules` §5); `observed` comes from the run (`atlas inject
run`, Task 1.9e; by hand until then). **Readers:** `atlas lint-brief` (1.9c: `old` found once in `file`), `atlas inject`
(1.9e: apply, run the radius, `observed`, revert, summary), `atlas pack` (mismatch tail — 1.9e), Atlas nodes
`injection` and edges `breaks` (`observed`), `lists` (ADR-ATL-001). Contract test:
`scripts/atlas/tests/test_formats_1_9d.py::test_injections_example_schema` reads the example below.

## Rules

- A JSON array; every object has exactly these eight keys, nothing else (no legend objects, no aliases like `T2`, no
  `note` — explanations go to the brief's head):

  | key | type | meaning |
  |---|---|---|
  | `id` | str | `inj-<n>`, n = 1, 2, … in array order; never renumbered (Atlas node `<slug>#<id>/inj-<n>`) |
  | `prop` | str | the broken property — a DESIGN or ACCEPTANCE line, one line |
  | `file` | str | repo-relative path, `/` separators |
  | `old` | str | verbatim substring of `file` at the commit the injection applies to; occurs exactly once |
  | `new` | str | replacement; may be empty |
  | `forecast` | list[str] | nodeids predicted red, written before the run and never edited; `[]` = "no test catches it" |
  | `observed` | null or list[str] | `null` before the run, then the nodeids that went red in the radius |
  | `test` | str | the radius: pytest arguments from the repo root, space-separated; run as `python -m pytest -q -p no:cacheprovider <test>` |

- A nodeid matches `^[^\s:]+\.py::\S+$` (`::Class::test` and `[param]` are fine).
- Matched = `observed` is not `null` and equals `forecast` as a set. Summary line for `## Инъекции` of the result:
  `- N инъекций, совпало M, расхождений K — tasks/<id>.injections.json` (`, не прогнано L` when L > 0); every mismatch
  also gets a line under `## Не проверено`. A prediction is never edited after the run.

## Example

Illustrative (K0 task 1.2): paths are real, `old` and nodeids are not checked against HEAD — the contract
test reads the shape only.

```json
[
 {
  "id": "inj-1",
  "prop": "таймер перезапускается на каждое событие",
  "file": "multiprocess_framework/modules/config_module/tools/watcher.py",
  "old": "        self._timer.cancel()\n",
  "new": "",
  "forecast": [
   "multiprocess_framework/modules/config_module/tests/test_watcher.py::test_second_write_is_reloaded"
  ],
  "observed": [
   "multiprocess_framework/modules/config_module/tests/test_watcher.py::test_second_write_is_reloaded"
  ],
  "test": "multiprocess_framework/modules/config_module/tests/test_watcher.py"
 },
 {
  "id": "inj-2",
  "prop": "флаг ожидания снимается до чтения файла",
  "file": "multiprocess_framework/modules/config_module/tools/watcher.py",
  "old": "        self._pending = False\n        data = self._read()\n",
  "new": "        data = self._read()\n        self._pending = False\n",
  "forecast": [],
  "observed": null,
  "test": "multiprocess_framework/modules/config_module/tests/test_watcher.py -k reload"
 }
]
```

Old forms stay as history and are not rewritten: `1.6c.injections.json` (ids `A01…`, no `observed`/`test`, forecast
= bare function names), `1.9a.injections.json` (a `legend` object, aliases `T<n>`/`H<n>`), prose
`tasks/<id>.injections.md` (no new ones).
