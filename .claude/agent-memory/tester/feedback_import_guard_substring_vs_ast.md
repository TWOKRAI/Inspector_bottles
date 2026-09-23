---
name: import-guard-substring-vs-ast
description: A "modules don't import each other" guard test must parse imports via AST, not substring-search the file text
metadata:
  type: feedback
---

A guard test asserting "module A does not import module B" must walk `ast.parse(...)` for
`Import`/`ImportFrom` nodes and check names there — never `"B" not in source_text`. A docstring
or comment mentioning the other module by name (e.g. "паблишер — этот путь мира —
`Plugins.sim.robot_host`") makes the substring check fail even though there is zero real
import. Found on line-sim Task 3.5 part B (`test_plugins_do_not_import_each_other`):
`scene_source/plugin.py`'s module docstring names `Plugins.sim.robot_host` in prose while the
actual `import` list never mentions it.

**Why:** predicted this guard as "may be GREEN today" and it came back RED on the first run —
the failure was in my own test's method (substring match), not the code under test. Caught it
because the general RED-mode rule says an unexpectedly-failing guard is a finding to explain,
not a green rubber-stamp.

**How to apply:** any time a test's job is "X does not reference/import/depend on Y", prefer
AST (imports) or a real dependency-graph tool (`sentrux`/`graph_slice`) over grepping raw text
— text search catches prose, not structure. See also [[feedback_review_injection_patch_proves_coverage_gap_not_a_live_bug]] for the adjacent "verify your own test's failure mode before trusting it" habit.
