---
name: project-observability-facade-extension
description: How to add a new toggle to the observability control plane (ObservabilityConfig/expand_observability) — the 4 touchpoints, and why feature_flags.py is the WRONG place for logs/stats toggles
metadata:
  type: project
---

Task (2026-07-21, plan `backend-ctl-proof-discipline`, live finding — command_manager's
"executed successfully" INFO line flooded messages.log to 645MB): owner wanted a
default-off toggle for one specific noisy log call site, reusing whatever mechanism
already exists rather than inventing a new one.

**First instinct was wrong:** `multiprocess_framework/modules/config_module/feature_flags.py`
(the `FW_*` flag registry) looks like the obvious place for a boolean toggle — but its own
module docstring explicitly rules this out: "логи/статистика/ошибки НЕ являются `FW_*`-
флагами. Их тумблеры живут в секции `observability` app.yaml" (ADR-CRM-006). Always read
that docstring before adding a new `FW_*` flag for anything log/stats/telemetry-shaped.

**Correct home:** `multiprocess_framework/modules/process_module/configs/observability_config.py`
— `ObservabilityConfig` is a facade with sibling sub-sections (`errors`, `stats`, and now
`commands`), each mirroring the shape of an underlying manager config. `expand_observability(dict)`
flattens it into a dict of per-manager overlays.

**The 4 touchpoints to extend it** (all needed, in this order):
1. New `Observability<X>Config` sub-schema class + field on `ObservabilityConfig` (mirror
   `ObservabilityErrorsConfig`/`ObservabilityStatsConfig` — `@register_schema`, `FieldMeta`, sane default).
2. `expand_observability()`: add the new top-level key to the returned dict (currently
   `{"logger", "error", "stats", "command"}` — was 3 keys, now 4) + update its docstring.
3. **Consumer wiring** — the new key only matters if something reads it. For `command`,
   that's `process_module/managers/process_managers.py::_create_command_manager` reading
   `managers_config.get("command", {})` — same dict, same pattern as `enable_logging`/
   `enable_statistics` already there. `merge_managers()` (process_module/configs/managers_config.py)
   is a **generic** deep-merge over ALL top-level keys, so a brand-new key added to
   `expand_observability()`'s output flows through automatically once the consumer reads it —
   no change needed to `merge_managers` itself, and none to `ManagersConfig`/`CommandManagerConfig`
   EXCEPT adding the matching field there too (for schema truthfulness / GUI introspection).
4. **Golden snapshot regen** — `multiprocess_prototype/backend/tests/test_build_characterization.py`
   freezes the ENTIRE assembled `proc_dict` per real recipe (phone_sketch, hikvision_letter_robot).
   Any new field anywhere in the managers/observability chain WILL break it. See
   [[feedback-golden-snapshot-diff-before-regen]] for the safe regeneration procedure.

**Hot-reload is a SEPARATE, narrower story:** `process_module/managers/observability_reload.py`
(`apply_observability_reconfigure`/`start_observability_watcher`) only ever wired
Logger/Error/Stats (all CRM-based managers with `.reconfigure(dict)`). `CommandManager` was
never part of that chain — it has no `.reconfigure()`. Wiring a new `command` key into live
hot-reload would mean touching `app_module/orchestrator.py` (the watcher's real call site,
`self.command_manager` is available there) AND `process_module/commands/builtin_commands.py`
(the `config.reload` IPC handler, same availability) — both are high-blast-radius orchestration
files outside a typical narrow bugfix's file list. Decision made this session: implement
boot/rebuild-time wiring only (via the 4 touchpoints above), add a `set_<x>_enabled(bool)`
method on the concrete manager class as an extension seam (not on the abstract interface —
precedent: `LoggerManager.set_sink_enabled` isn't on `ILoggerManager` either), and disclose the
hot-reload gap explicitly rather than either silently skip it or silently expand scope into
orchestrator/IPC internals.
