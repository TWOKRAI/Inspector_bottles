# Task 1b.2d-1 — developer report (2026-10-02)

STATUS: DONE, 10 container params green; commit on feat/gs-1b2d.

## Tests (command from the brief)
- 18 failed / 253 passed. Failed = 16 reds of 1b.2d-2 (26 - 10, unchanged) + 2 PRE-EXISTING, unrelated:
  - `test_field_info_codec_acceptance.py::test_fieldinfo_path_default_goes_as_str` — Windows `str(Path('/tmp/x'))` = `\tmp\x`.
  - `frontend/forms/tests/test_catalog_kind_roundtrip.py::...for_all_register_fields` — pin 417 fields vs 448 found.
  Both verified red with HEAD version of `field_info.py` swapped in (then restored).
- ruff check on the two touched .py: clean.

## Where each property is held (core/field_info.py)
- list element described: 101-104 (`_describe_type`); rebuilt: 123-125 (`_build_type`).
- dict key/value described: 105-109; rebuilt: 126-130 (missing half -> Any).
- old payload (no item/key/value) -> bare container: 124/127 (`.get`) + 128-129.
- nested literal choices: 97-100 (nested literal without args -> None); build guard 138-139 (`_build_nested`).
- recursion shared top level/nested: `_describe_type` called from `to_dict` (234, 246), `_build_type` from `from_dict` (262); tag table `_SCALAR_TYPES` 72.

## Self-injection (textual patch of field_info.py, then restored; hazards + 10 container params)
| property | reverted | died |
|---|---|---|
| list item carried | `desc["item"] = item` -> pass | 20: 7 roundtrip, pinned shapes, nested literal, 2 copy_type, 10 container params (all list ones) |
| dict key/value carried | `desc[key] = sub` -> pass | 8: 3 roundtrip, pinned shapes, bare/unsupported, half_described, copy_type dict, otel_export.headers |
| old payload compat | `.get("item")` -> `["item"]` | 1: old_payload[list] (dict side not injected) |
| nested literal choices | choices skipped when nested | 3: 2 roundtrip literal, nested_literal_keeps_choices |
| nested literal no Literal[None] | guard in `_build_nested` removed | 1: nested_literal_without_choices_in_payload |
| build side item | `return list` | 19 (all list container params) |
| build side key/value | `return dict` | 6 (dict ones incl. otel_export.headers) |

## Interpreted rather than followed
- "Nested literal without choices -> omit the key": read as the whole nested description is dropped (describe side, unreachable for real `Literal`); build side symmetric guard.
- Missing half of dict -> `Any` on build.
- Also edited two other stale mentions in ADR-RM-007 (the "Контекст/Решение" paragraph and the "Финальный судья" bullet) so they do not point at the removed bullet; the brief named only the bullet.
- Hazard tests appended to the existing `test_field_info_codec_hazards.py`; added `Any` to its typing import.

## Left open / unreliable
- Element types `Any` / `Optional[X]` / unions are NOT carried (tag unsupported -> key omitted): `list[Optional[int]]` copy accepts `[None]`-like loosening vs original? original accepts None, copy accepts anything — wider, not stricter. Inventory has none such.
- Nested `Enum` literal choices go through `_json_safe` -> str (pre-existing lossy behaviour, now also nested).
- Injection C only reverted the list side; dict side `.get` compat is covered by the parametrized old-payload test but not break-injected.
- `dict` with non-str keys: JSON stringifies dict keys in defaults only; type description unaffected, not tested end to end.
- Did not run the full suite or sentrux.
