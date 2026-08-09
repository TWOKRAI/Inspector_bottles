---
name: feedback-model-copy-does-not-validate
description: model_copy(update=) кладёт dict вместо схемы молча — потребитель читает атрибуты и получает «молчу»
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
[[feedback_config_delivery_shape_differs]], [[feedback_merge_changes_the_form]].
