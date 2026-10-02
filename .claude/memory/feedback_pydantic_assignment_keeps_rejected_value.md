---
name: pydantic-assignment-keeps-rejected-value
description: validate_assignment + model_validator(after) rejects but leaves the value stored; full revalidation is not the fix
metadata:
  type: feedback
---

With `validate_assignment=True`, pydantic v2 assigns first and runs `model_validator(mode="after")` afterwards; a raise does NOT roll back. Reproduced 2026-10-02 on `OtelExportConfig`: `max_export_batch_size = 20480` → ValidationError, value still `20480`. Every bare `setattr` on a register (`update_field`, `RegistersManager.set_field_value`, `cmd_set_config`, `_init_register`) inherits this.

**Why:** a rejected config value stays live in the backend register while the operator is told "rejected".

**How to apply:** fix by snapshot of touched `__dict__` keys + `__pydantic_fields_set__` → setattr → restore both on exception. Do NOT use `model_validate({**current, **new})` as the atomic check: registers with an invalid-by-design default (otel `endpoint=""`) then reject every edit on an unrelated field (spec review of gui-service 1b.2d caught it before code). Build error text with `exc.errors(include_input=False)` so secrets do not leak. See [[gui-service-1b2d]].
