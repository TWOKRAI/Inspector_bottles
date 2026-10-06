---
name: feedback-ctypes-setattr-unknown-field-is-silent
description: "setattr on a ctypes Structure with a wrong field name silently creates a Python attribute (молча, без ошибки) — tests fill zeros and stay green; guard with a `_fields_` check"
module: [services/code_reader]
mechanism: [fixtures, error-handling]
metadata:
  type: feedback
  last-verified: 2026-09-29
---

`setattr(struct, "nX", 5)` on a `ctypes.Structure` that has no field `nX` does not raise — it
adds an ordinary Python attribute, and the C memory keeps zeros. A test that builds input
structs by guessed field names therefore feeds all-zero data and can pass against wrong code.

**Why:** 2026-09-29, code_reader Ф6: a blind tester guessed `nX`/`nY` and `nDecodeQuality`
(header says `x`/`y`, `nDeCode`) without reading the header; corners and grades would have been
silently zero. Caught by the lead while unifying two testers' assumptions, not by any test.

**How to apply:** in tests (and any code) that fill ctypes structs by name, use a helper that
asserts `name in {f[0] for f in type(obj)._fields_}` before `setattr`. Brief blind testers to
take field names from the vendor header, and pin every field name the contract relies on.
