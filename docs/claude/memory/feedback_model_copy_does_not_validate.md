---
name: feedback-model-copy-does-not-validate
description: "model_copy(update=) кладёт dict вместо схемы молча — потребитель читает атрибуты и получает «молчу»; также: validate_assignment + model_validator(after) rejects but leaves the value stored; full revalidation is not the fix"
merged_from: [feedback_pydantic_assignment_keeps_rejected_value]
metadata:
  node_type: memory
  type: feedback
  originSessionId: b8e44328-c9ca-4dcc-95a9-56386a3c3faf
  modified: 2026-08-03T16:59:45.527Z
---

`SchemaBase.model_copy(update={...})` (Pydantic v2) **не валидирует** переданное:
словарь на месте вложенной схемы проходит сборку молча. Потребитель, читающий
`getattr(rule, "level", None)`, получает `None` — то есть «настройки нет», а не ошибку.

Поймано дважды за один заход (Ф2.2/2.3a, 2026-08-03):
1. правило иерархии `loggers[""] = {"level": "DEBUG"}` вместо `LoggerRuleSchema` —
   правило молча не действовало;
2. профиль скоупов, положенный сырыми dict'ами, — `min_level` молча переставал
   фильтровать.

**Why:** симптом — не падение, а исчезновение настройки. Ищется в конфиге и в
слоях, то есть далеко от причины. Класс «проглоченный сбой»: следствие есть,
следа нет — см. [[feedback_swallowed_failure_class]].

**How to apply:** в `model_copy(update=…)` класть **построенные схемы**
(`LoggerRuleSchema(...)`) или `Model.model_validate(...)`, а не словари. Там, где
значение может приехать словарём по границе (Dict at Boundary), приводить его
один раз на входе потребителя — как `NameHierarchy` приводит `Mapping` в
конструкторе. На форму ставить страж-тест (`isinstance` по составу), иначе
гарантия держится на внимательности. Связано:
[[feedback_fakes_feed_config_flat_so_key_address_defects_are_invisible]], [[feedback_merge_changes_the_form]].

## Слито из feedback_pydantic_assignment_keeps_rejected_value (_archive/feedback_pydantic_assignment_keeps_rejected_value.md)

With `validate_assignment=True`, pydantic v2 assigns first and runs `model_validator(mode="after")` afterwards; a raise does NOT roll back. Reproduced 2026-10-02 on `OtelExportConfig`: `max_export_batch_size = 20480` → ValidationError, value still `20480`. Every bare `setattr` on a register (`update_field`, `RegistersManager.set_field_value`, `cmd_set_config`, `_init_register`) inherits this.

**Why:** a rejected config value stays live in the backend register while the operator is told "rejected".

**How to apply:** fix by snapshot of touched `__dict__` keys + `__pydantic_fields_set__` → setattr → restore both on exception. Do NOT use `model_validate({**current, **new})` as the atomic check: registers with an invalid-by-design default (otel `endpoint=""`) then reject every edit on an unrelated field (spec review of gui-service 1b.2d caught it before code). Build error text with `exc.errors(include_input=False)` so secrets do not leak. See [[gui-service-1b2d]].
