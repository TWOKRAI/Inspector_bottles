---
name: negative-ui-case-needs-same-fixture-control-row
description: "for \"no section/chip\" acceptance, put a second independent pair in the same git fixture that MUST produce a row; makes every negative RED today and exact-row assertions catch plan-level false pairing / контрольная строка в той же фикстуре, негативный UI-тест"
module: [scripts]
mechanism: [fixtures, test-assertions]
role: tester
metadata:
  type: feedback
---

For "feature must NOT show X" tests on a new page section, build the control into the same fixture (e.g. two extra branches editing a second file) and assert the full row set equals only the control row.

**Why:** without it every negative is green against a missing feature (5.6 radar: 7 guards green, 32 red only because of controls). Comparing the whole row set also catches plan-level pairing, not just file-level.

**How to apply:** also check the red set with a throwaway stub implementation in the scratchpad (copy of the script with a naive radar): a duplicated branch walk was caught only by the in-process git-verb count test, mutations (no independence check, window on root, root excluded) each flipped exactly the intended tests. Equal-tip branches are NOT separated by the independence check alone (stack touched-set already empties the child).
