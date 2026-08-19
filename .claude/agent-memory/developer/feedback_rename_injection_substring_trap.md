---
name: feedback-rename-injection-substring-trap
description: Suffix-style rename (name -> name_RENAMED) in break-injection experiments can leave the old name as a substring of the new one, silently defeating substring-based ("in blob") contract checks even though hasattr alone would have caught it
metadata:
  type: feedback
---

When break-injecting a "rename" to prove a contract test catches a renamed
identifier, do NOT rename by appending a suffix (`old_name` -> `old_name_RENAMED`,
`old_name_v2`, `old_name_impl`, ...) if the old name has any `self.<name>`
internal call sites. The substring `self.<name>` survives as a literal PREFIX
inside the new call text (`self.<name>_RENAMED(...)`), so any check built on
`name not in blob` / `name in blob` (containment, not exact-identifier
equality) stays fooled — even though `hasattr(cls, name)` alone would already
have flipped correctly.

**Why:** Found on S-29 (Inspector_bottles queue), verifying
`assert_stub_speaks_the_real_class_surface()` in
`multiprocess_prototype/backend/tests/_orchestrator_stub_contract.py` — a
two-part check mirroring `test_hot_rebuild_provenance_hazards.py::
test_the_stub_orchestrator_speaks_the_real_class_surface` (S-26): (1)
`hasattr(RealClass, name)` on the class, (2) a fallback substring search
`f"self.{name}" not in blob` across `inspect.getsource()` of the whole MRO,
for names that are instance attributes and therefore invisible to `hasattr`.
Renaming `_get_protected_names` -> `_get_protected_names_RENAMED` at its `def`
line AND all 3 internal `self._get_protected_names()` call sites still left
the whole 74-test catalog green. Root cause, confirmed by direct
`python -c` introspection: `hasattr(...)` correctly returned `False`, but
`"self._get_protected_names" in blob` was `True` — that literal substring is
a prefix of `"self._get_protected_names_RENAMED(...)"`, still present at the
3 call sites. The `AND` between the two checks means the blob-search's false
"still there" vetoes the correct `hasattr`-based detection. Re-running with a
substring-unrelated name (`_get_protected_names` -> `_zzz_moved_elsewhere`)
immediately produced the expected 5 failures across the catalog.

Two other renames in the same task (`live_process_config`,
`_topology_current_names`) went red correctly on the FIRST try with the same
suffix-style pattern — only because those two names happen to have zero
internal `self.<name>` call sites in `process_manager_process.py` (def-only),
so there was no leftover substring to rescue them. The trap only fires when
the renamed name is *also* referenced via `self.<name>` elsewhere in the
same source blob — which is the common case for anything non-trivial.

**How to apply:** for ANY break-injection experiment that renames an
identifier to prove a name-presence/absence check fires — not just this
project's stub-contract checks, any check using substring/`in` containment
rather than exact equality — pick a replacement name that shares NO substring
with the original in either direction (e.g. `_zzz_moved_elsewhere`, never
`<name>_v2`/`<name>_RENAMED`/`<name>_impl`). Before trusting a green
break-injection result, grep the target file for `self.<name>` (not just the
`def` line) to know whether the substring trap even applies. This is also a
real (if narrow) blind spot of the *production* check itself: a genuine
prod rename that happens to extend the old name as a prefix (`get_config` ->
`get_config_v2`) would similarly slip past the blob-search fallback — worth
naming in a report if it comes up again, not silently patched without the
task asking for it (S-29 explicitly scoped to extending protection to 4 files,
not redesigning the inherited S-26 check).

See [[project_orchestrator_stub_contract_s29]] for the task this was found on.

**Sequel, 2026-08-18 (review, same guard): word-boundary closes the PREFIX gap,
not the sibling TEXT gap — only AST closes both.** After this memory's finding
shipped `re.search(rf"self\.{re.escape(name)}(?![A-Za-z0-9_])", blob)` (word
boundary, no more prefix trap), a synchronous review found the guard was STILL
a text search over `inspect.getsource()`'s raw blob — which includes comments
and docstrings, not just code. Paired injection proved it: rename all 10 live
`self.logger_manager` call sites across 3 real files -> guard correctly reds
(5/38 failed, catalog `backend/tests`); SAME rename plus ONE extra comment
line (`# исторически называлось self.logger_manager`) inserted anywhere in the
scanned MRO source -> guard flips back to a FALSE green (38/38 passed) — the
word-boundary regex cannot tell a comment from code, it only ever asked "is
this substring present," never "is this a real attribute access." Fix: stop
scanning text at all. Parse each class's source with `ast.parse`, walk for
`ast.Attribute` nodes where `.value` is `ast.Name(id="self")`, collect
`.attr`. Comments/docstrings never produce that node shape, so they can no
longer forge a match, and both reads and writes (`self.x` / `self.x = ...`)
collapse to the same node type for free. Re-ran the identical rename-plus-comment
injection against the AST version: stayed red (5/38), proving the class of
defect (text-search-over-source-as-a-safety-check) is closed, not just its
one known instance.

**How to apply (supersedes the narrower advice above for THIS class of
check):** any guard that greps/regexes `inspect.getsource()` output — even
with a correct word-boundary — is only ever pattern-matching characters, and
comments/docstrings are characters too. If the check's real question is "does
the code do X," parse it (`ast`) and ask the AST directly; don't clean the
text and re-run the same regex on the cleaned result either — the parser is
the single source of truth for "what counts as code" and never needs a
prose-forms-to-strip enumeration kept in sync by hand.
