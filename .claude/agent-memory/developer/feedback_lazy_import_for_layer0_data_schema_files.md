---
name: lazy-import-for-layer0-data-schema-files
description: any file loaded via data_schema_module/core/__init__.py cannot import get_std_logger (or anything importing data_schema_module) at module level — must defer the import to first call
metadata:
  type: feedback
---

Files re-exported by `data_schema_module/core/__init__.py` (LAYER 0 of the
package init chain) cannot do a module-level `from ...logger_module import
get_std_logger` — verified by reproduction, not assumed. `logger_module`
(via `configs/logger_manager_config.py` → `channel_routing_module` →
`data_schema_module`) imports the `data_schema_module` facade during its own
init, so a module-level import back into `logger_module` from a LAYER 0
`core/*.py` file gives `ImportError: cannot import name 'SchemaBase' from
partially initialized module`. This is the exact class of cycle already
documented in `logger_module/tests/test_std_logger_guard.py`'s `WHITELIST`
for `registry/discovery.py` and `registry/process_registry.py` — but
`core/metrics.py` is not in that whitelist tree (it's `core/`, not
`registry/`), so the fix there was different: a **lazy import inside a
`_std_logger()` helper**, cached in a module-level `_logger = None` global,
resolved on first real call rather than at import time. Confirmed via
`compileall`/import smoke test both "fresh import data_schema_module" and
"import logger_module then data_schema_module" — both hung on the eager
import, both cleared with the lazy one.

**Why:** the project mandates `get_std_logger(__name__)` over bare stdlib
loggers (Ф6.2/Ф6.3 guard tests) everywhere in `multiprocess_framework`, but
that rule collides with `data_schema_module`'s own LAYER 0 files being
imported before the package finishes initializing. The bare-stdlib-logger
AST guard (`test_no_bare_stdlib_logger_outside_whitelist`) doesn't care
*when* `get_std_logger` is imported, only that it's used — so lazy-importing
inside the file satisfies both the logger-facade rule and the import-cycle
constraint without adding a new whitelist entry.

**How to apply:** before adding any cross-module import (especially anything
touching `logger_module`, `channel_routing_module`, or `data_schema_module`
itself) to a file under `data_schema_module/core/` or any other package
whose `__init__.py` eagerly re-exports it, actually run a fresh-process
import check (`python -c "import ...data_schema_module"`) rather than
assuming the layering table in `README.md` ("core has zero deps") holds for
new imports. If it cycles, defer the import into a small cached accessor
function instead of adding to the stdlib-logger whitelist (that whitelist is
for files that must stay on bare stdlib logging permanently — not the right
tool for a resolvable-by-laziness cycle).

See also [[project_metrics_freeze_s27]] for the task this was found in, and
`multiprocess_framework/modules/data_schema_module/DECISIONS.md` ADR-DS-009
for the full writeup.
