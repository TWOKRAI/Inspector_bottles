---
name: review-injection-patch-proves-coverage-gap-not-a-live-bug
description: When a review's "found ложные инкременты" claim used a throwaway monkeypatch to force the bad behavior, the missing negative-half test you write can legitimately come out GREEN today — that is the correct, expected outcome, not a wrong test
metadata:
  type: feedback
---

Task 2.7 of `observability-closure` (2026-09-01) asked for the missing negative
half of two counter pairs (`queue_full_events`, `pid_registry_failures`) —
review-phase-1.md's finding read "счётчик растёт на КАЖДОЙ успешной отправке
(6447 ложных инкрементов)". Read literally, that sounds like a live production
bug. It was NOT: the reviewer's own methodology section said explicitly
"Заплатка (throwaway pytest-плагин, рабочее дерево не тронуто): обёртка
`QueueRegistry.send_to_queue`, инкремент `queue_full_events` при ok==True" — the
6447 number came from a monkeypatch the reviewer wrote and applied *on top of*
correct code, to prove that if such a regression ever landed, no existing test
would catch it. The actual code (read directly) only increments inside
`except Exception as e: if isinstance(e, Full):` — already correct.

**Why:** I almost treated this as "code needs an implementation fix" and went
looking for how the increment could be reached on success. Reading the review's
own "Заплатка" / "Фактический вывод" wording before writing the test saved a
wasted implementation-hunting pass. Both new negative-half tests I wrote came
back GREEN on the first run (`2 passed`, `2 passed`) — exactly as this analysis
predicted — and that is the correct, disclosed finding, not a sign the test is
wrong.

**How to apply:** before writing a "missing half of the pair" test from a
review finding, check whether the review's evidence for the missing half came
from (a) a live/read trace of production code actually misbehaving, or (b) an
injected/monkeypatched proof of *what would happen if* the guard regressed.
Case (b) means the test you add is closing a coverage gap, not a behavior bug —
it is expected to pass immediately, and you should say so explicitly in the
report (which half is "coverage-gap-green" vs "genuinely red, implementation
still missing") rather than let a green result look uniform with red ones.
Related: [[feedback_pytest_raises_inverts_red_polarity]] (another case of
"green here is correct, not a mistake" needing explicit disclosure).
