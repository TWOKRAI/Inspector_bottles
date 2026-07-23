---
name: project-backend-ctl-mcp-surface-audit-2026-07-23
description: MCP tool-surface audit of backend_ctl (49 tools) — two structural DX bugs found, not just doc drift
metadata:
  type: project
---

Full DX/contract audit of `backend_ctl/mcp_tools.py` + `dispatch.py` + `mcp_server_sdk.py` (49 tools,
2026-07-23). Two structural bugs found, beyond the expected doc-drift:

1. **`full=true` escape hatch is schema-blocked for ~45 of 49 tools.** `dispatch.py::_cap_heavy`
   (`mcp_tools.py:267-293`) byte-caps every tool NOT in `_UNCAPPED_TOOLS` (`events`/`events_page`/
   `register_snapshot`, `mcp_tools.py:52`) and always emits hint text `"full=true — полный объём"`.
   But only 3 tools (`system_overview`, `state_get_subtree`, `telemetry_history`) actually declare a
   `full` property in their `input_schema`. Every other tool's top-level schema has
   `additionalProperties: False` (the `_obj()` default, `mcp_tools.py:73-87`) — the official MCP SDK's
   `mcp.server.lowlevel.Server.call_tool()` runs `jsonschema.validate` against the cached tool
   definition BEFORE the handler runs (`.venv/.../mcp/server/lowlevel/server.py:528-532`), so a client
   trying to follow the hint on e.g. `capabilities`/`introspect_memory`/`session_log` gets rejected
   with "Additional properties are not allowed ('full' was unexpected)". The advertised escape hatch
   is unreachable for most tools it claims to cover.
2. **`record_start`/`record_dump` are classified `SAFETY_READ`** (`mcp_tools.py:1142,1147`) with the
   stated rationale "recording is a local observer, backend isn't mutated" — true for the backend, but
   `Recorder` opens the target file with `open(path, "w", ...)` (`recorder.py:86`), silently
   overwriting any existing recording of the same name with zero warning/dedupe. Because the class is
   `read`, this destructive local side effect (a) is allowed even under `--read-only` MCP mode, and
   (b) is excluded from the E.1 audit journal (`_AUDITED_SAFETY = {WRITE, ESCALATED}`,
   `mcp_tools.py:1184`) — an overwritten flight recording leaves no audit trail.

Also notable: `system_command`'s `command` arg is a bare `{"type": "object", "additionalProperties":
True}` with no nested schema for the documented `cmd`/`process_name` contract (`mcp_tools.py:525-531`),
and unlike `send_command`, it gets NO pre-flight E.2 validation (`dispatch.py:339` only special-cases
`name == "send_command"`, not `system_command`) — a typo'd key sails through to the backend and shows
up as a timeout, not a schema error.

Doc-drift was minor by comparison: AGENTS.md/README.md were already current for the two newest tools
(`introspect_telemetry`, `process_restart_verified`, added 2026-07-23 commits e038a747/9aeaa17a); only
`STATUS.md`'s "47 инструментов" line and README's narrow MCP-tool enumeration paragraph
(`README.md:192-205`, lists ~25 of 49) were stale. `docs/contracts/CAPABILITIES.md/.yaml` (backend
command contracts, not the MCP tool registry) has an automated drift gate
(`dump_capabilities.py` + `test_capabilities.py::test_dump_matches_committed`) — the MCP tool registry
itself (AGENTS.md/README.md/STATUS.md counts) has no equivalent CI gate.

**Why:** owner cares about "signal ≠ reality" bugs (see [[project_backend_ctl_signal_integrity]]) and
trust/audit ([[project_backend_ctl_recorder_kept]]) — both findings above are exactly that class:
advertised behavior (`full=true` works; recording is safe/read-only) that silently doesn't hold.

**How to apply:** when next touching `mcp_tools.py`/`dispatch.py`, (a) either add `full` to every
byte-capped tool's schema or make `_cap_heavy`'s hint conditional on the tool actually declaring it;
(b) reclassify `record_start`/`record_dump` as `write` (or add explicit overwrite protection +
audit them) — don't trust the "backend not mutated" rationale alone when local filesystem is mutated;
(c) give `system_command` either a structured nested schema or route it through the same E.2
pre-flight validator as `send_command`.
