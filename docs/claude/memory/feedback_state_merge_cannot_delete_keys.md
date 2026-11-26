---
name: feedback_state_merge_cannot_delete_keys
description: state.merge не удаляет ключи и отвергает не-dict; set узла ослепляет подписчиков листьев / StateStore merge cannot clear a value, set vs delete, glob subscribers
metadata:
  type: feedback
  module: [state_store_module]
  mechanism: [state, ipc]
---

`state.merge` with a non-dict value is rejected; `merge(path, {})` deletes nothing. To clear or replace a value use `set` / `delete`. `set` on a node does not notify leaf or glob subscribers below it.

**Why:** a "clear the last error" built on merge silently keeps the old text on screen.

**How to apply:** when a device publishes a value that must be cleared, use `set` on the leaf or `delete`; warn lane Ф before using `delete`. Source: reading during the `last_error` analysis (R2, 2026-11-26); re-check by running before relying on it.
