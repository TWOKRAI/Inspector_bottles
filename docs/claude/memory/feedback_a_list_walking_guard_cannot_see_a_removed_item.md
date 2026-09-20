---
name: a-list-walking-guard-cannot-see-a-removed-item
description: "A guard that iterates a registry (\"every key in LOSS_KEYS is published by its plane\") stays green when a key is REMOVED from the registry — it checks membership one way; removal is caught only by a literal-presence test next to it"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 6ba40fcc-81c2-440a-b226-24fcdf6b63d8
  modified: 2026-08-29T18:50:27.434Z
---

Injection I16 on Task 1.1 of `observability-closure` (2026-08-29): `"hook_delivery_failures"` deleted
from `backend_ctl/protocol.py::OBSERVABILITY_LOSS_KEYS` → `backend_ctl/tests/test_overview.py::
test_loss_keys_match_the_real_publisher` stayed GREEN (it walks the list and checks each present
key is published — a key that is gone is simply not visited). The property was held by exactly one
test, the independent tester's A9b, which asserts by literal that the counter feeds an
`observability_loss` anomaly. Predicted red set was {A9b, G2}; actual {A9b}.

**Why:** "the guard exists" felt sufficient — but a walker over a registry proves consistency of what
is there, never completeness. Deleting an entry is the most common way a registry regresses (someone
"cleans up" a key they don't recognise), and it is invisible to the walker by construction.

**How to apply:** for every registry-membership property write the literal test
(`assert "key" in REGISTRY`) beside the walker; in an injection matrix always include the patch
"item removed from the registry" for each registry touched, and predict which test catches it —
if the answer is "the walker", the answer is wrong. Related:
[[feedback_a_guard_that_counts_at_least_once_is_blind]], [[feedback_prove_test_red_without_fix]].
