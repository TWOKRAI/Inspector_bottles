---
name: config-reload-inline-rejects-unknown-observability-keys
description: Unlike raw SchemaBase construction (extra=ignore, silently drops), the config.reload INLINE observability path has its own explicit unknown-key guard (validate_layer_section → unknown_section_keys) that rejects with success=False BEFORE writing to the layer. A RED test for a brand-new ObservabilityConfig scalar field driven through config.reload gets a clean success=False + "did you mean" reason, not a silent no-op.
metadata:
  type: feedback
---

[[feedback_pydantic_extra_ignore_hides_red]] establishes that `SchemaBase` (Pydantic v2,
`extra='ignore'`) silently drops an undeclared constructor kwarg — true for direct
`ObservabilityConfig(**dict)` construction. It does NOT hold for the `config.reload` INLINE
`data["observability"]` path specifically: `validate_layer_section` (`observability_layers.py:1251`)
calls `unknown_section_keys(section)` for the session layer (`layer == LAYER_SESSION`, i.e. the
inline/operator-typed-it-by-hand door only — file/recipe/switch doors stay silent-and-log, by
design, see that function's own docstring "Задача 5.4"), and raises `ValueError` BEFORE any
write. `builtin_commands.py:1902-1910` catches it and returns
`{"success": False, "source": "inline", "reason": "слой session отвергнут — ... heartbeat_interval_sec; похоже, имел в виду: retention_sweep_interval_sec"}`
— a fuzzy-matched "did you mean" suggestion included.

**Why:** writing a RED test for Task 2.3 (`observability-closure`) I initially assumed sending
`config.reload({"observability": {"heartbeat_interval_sec": 1.0}})` before the field exists in
the schema would silently no-op (matching the `extra=ignore` pattern from the earlier finding),
and planned to assert on the unchanged attribute value only. Reading `validate_layer_section`'s
docstring first (it explicitly says "session → отказ ДО записи") caught this before writing the
test, and the actual pytest run confirmed the predicted `success: False` exactly, word for word.

**How to apply:** for a RED test of "new scalar key on `ObservabilityConfig`, applied via
`config.reload` inline", assert `res["success"] is True` (which will be `False` today) as the
PRIMARY assertion — this is a cleaner, more diagnostic failure than probing the live attribute
first, and the `res["reason"]` string is genuinely useful output to show in the test failure
message. Only probe the live attribute as a SECOND assertion after `success`. This guard applies
to the **inline/session door only** — the file/recipe/switch doors (`LAYER_APP` etc.) do NOT
reject unknown keys (silent + logged, by explicit design choice in the same function). Don't
generalize this "clean rejection" expectation to file-based `config.reload` or recipe-driven
paths — those still need the "silently ignored, assert the attribute directly" approach from
[[feedback_pydantic_extra_ignore_hides_red]].
