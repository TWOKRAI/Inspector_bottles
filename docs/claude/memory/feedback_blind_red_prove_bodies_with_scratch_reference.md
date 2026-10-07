---
name: blind-red-prove-bodies-with-scratch-reference
description: "Слепой RED, где все тесты падают на отсутствующем импорте, не доказывает тела ассертов: написать одноразовую эталонную реализацию по спеку и вставить через sitecustomize / a RED failing at the missing door proves nothing about test bodies"
mechanism: [acceptance, break-injection]
role: tester
metadata:
  type: feedback
---

All-red-from-missing-door hides broken assertion bodies. Write a small reference implementation from the spec ONLY (never the reviewer/CTO probe dirs) in the scratchpad, patch it onto the public module with a `sitecustomize.py` on PYTHONPATH (reaches subprocess tests too, because the tests build the child env from os.environ), run the suite green, then flip an env-var injection per spec row and check which tests go red.

**Why:** in Task 0.4 this showed 10/10 passable, no flake in 6 runs, and each injection reddened exactly the expected rows (S2 only on early-address removal).

**How to apply:** blind RED for a mechanism with injection rows. On Windows Git Bash separate PYTHONPATH entries with `;`, not `:` (a `D:/..:C:/..` value silently drops the second entry). Disclose in the report that the ref is the tester's own, uncommitted.
