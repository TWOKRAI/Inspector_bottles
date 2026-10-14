---
name: yaml-safe-load-raises-more-than-yamlerror
description: "yaml.safe_load on a corrupt file raises KeyError, AttributeError, IndexError, ValueError, RecursionError — not only YAMLError; catching (YAMLError, ValueError) is incomplete / safe_load бросает не только YAMLError, доменная ошибка разбора"
module: [services/robot_comm]
mechanism: [break-injection, test-assertions]
role: reviewer
metadata:
  type: feedback
---

`yaml.safe_load(bytes)` on a corrupt file raises exceptions outside the `yaml.YAMLError` hierarchy.
Measured (PyYAML, Python 3.12.12, T5.2 stage-5 review 2026-10-14, `RobotDataStore.read`):

| input | exception |
|---|---|
| `d: 2020-99-99` | `ValueError` |
| `v: !!bool foo` | `KeyError` |
| `v: !!timestamp foo` | `AttributeError` |
| `v: !!int ''`, `v: !!float ''` | `IndexError` |
| `[` × 3000 | `RecursionError` |
| `safe_dump` of a body nested 600 deep | `RecursionError` |

**Why:** the developer widened the catch to `(YAMLError, ValueError)` as a declared deviation without a test. An injection that
narrowed it back left 30/30 green. Four of the inputs above escaped the "file does not parse → StoreDocumentInvalid" contract.

**How to apply:** wrap the parse of in-memory bytes (no I/O inside) in `except Exception` and raise the domain error `from exc`.
Add one literal test per input class (explicit tag, impossible date, deep nesting). A widened catch without a test is a deviation
without a red.
