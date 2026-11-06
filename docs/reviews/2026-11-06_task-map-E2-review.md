# Ревью стадии 5, раунд 1, map-E2; ревьюер Sonnet; находки переданы лидом с решениями

Stage 5 review of map-E2, round 1: CHANGES REQUESTED. Fix F1–F13 below + item P; no commit; files: your same 6 only.

Reviewer reproductions + lead decisions (all accepted):

F1 [high, false fact] `ConfigFileWatcher` io = `watches self._handler :238`; real: `self._observer.schedule(self._handler, str(self._path.parent), recursive=False)`. Take `args[1]` or `keywords['path']` for `.schedule` with ≥ 2 args; else not a watch. Your test fixture `observer.schedule(folder)` encodes a non-existent form — replace with `observer.schedule(handler, folder, recursive=False)` -> `folder`.

F2 [mid-high, misleading address] `write_companion` call_sites = only a backend_ctl probe; real caller `observability_companion.py:275` in `persist_session_to_companion` was hidden as `same_file_calls=1`. Same-file calls go into call_sites with a mark; every call site carries its enclosing symbol (`path:275 in persist_session_to_companion`). Probes/tests sorted after production callers.

F3 [mid] add io op `replaces` for `os.replace`, `os.rename`, `Path.replace/rename`, `shutil.move` (`tmp -> path`).

F4 [mid] `bases_resolved: [{name, where}]`, `from_where` on inherited members (resolve_class already has file/line) — gives IBaseManager `base_manager/interfaces.py:28`.

F5 [mid] `line` on every member and every district house (first `def` line, not the decorator).

F6 [mid] tests as `{file, line, name}`, printed `path:LINE name`; group per file «N тестов» with all names (no cap of 5 for the reference).

F7 [mid, noise] structural matches only if the interface has ≥ 2 required non-dunder names, or arity + parameter names match; private `_X` classes and classes in layers that do not import the interface are excluded; otherwise `structural_total: null` + «слишком общий протокол (1 член)». IConfig→Config must stay.

F8 [low] Protocol/ABC without `__init__`: `signature: null`, text «конструктора нет (интерфейс)»; also check `Имя()` for classes with unresolved external bases — null if unknown.

F9 [low] line 2 for interfaces adds «наследников N».

F10 [tests] reviewer's injections: `inherited_members` always [] -> 16 passed; correct `args[1]` -> 16 passed. Add tests: ABC inheriting 2 abstract members from a base in another file; `.schedule(handler, folder)`; same-file call site with enclosing symbol; `replaces`; `run_bench` on a mini repo checking `meta.targets`.

F11 [low] repeatable `--skip-dir` (default from the defaults block).

F12 [low] `meta.dirty` from `git status --porcelain` over indexed paths.

F13 [info] reference JSON compact (no indent); print its size in tokens estimate (chars/3.5) in the report.

P [owner's framing 2026-11-06: «автоматически формируется мануал с разделами, как для любого технического устройства, все одинаковые по структуре»]: the text format of every card (layer/unit/package/district/house) prints the SAME fixed sections in the same order, empty ones shown as «—»: «Назначение» / «Подключение» (direction rule, __all__, interfaces, signature, members) / «Связи» (uses me / I use, subclasses, call sites, bases) / «Где работает» (processes if known, threads, commands, io) / «Проверка» (findings, tests) / «Состояние» (tier, doc_missing). JSON gets the same top-level section keys. Update SIGNBOARD.md with the section contract. cards.html uses the same order.

Regenerate k0_reference.json and cards.html after the fixes. Break-inject after: F1 back to args[0]; inherited_members []; drop enclosing symbol — predicted reds written BEFORE the run, observed after. Report ≤ 25 lines + «Раунд 2» in docs/reviews/2026-11-06_task-map-E2-developer.md. If your context passes the soft budget, write a handoff instead of rushing.
