---
name: pytest-owns-threading-excepthook-for-the-session
description: "Under pytest, threading.excepthook is pytest's own collector for the whole session and prints NOTHING to stderr — an acceptance anchor \"the previous hook printed a Traceback to stderr\" is unreachable by any implementation; restore the precondition (threading.__excepthook__) inside the test, don't weaken the criterion"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 6ba40fcc-81c2-440a-b226-24fcdf6b63d8
  modified: 2026-08-29T18:50:19.070Z
---

pytest 9.x (`_pytest/threadexception.py::pytest_configure`) replaces `threading.excepthook` for the
WHOLE session with a collector (`functools.partial(thread_exception_hook, append=deque)`) that stores
the exception and later emits `PytestUnhandledThreadExceptionWarning`. pytest-qt does the same to
`sys.excepthook`. So "the previous hook" seen by any hook installed inside a test is pytest's
collector, and stderr stays empty. Measured on Task 1.1 of `observability-closure` (2026-08-29):
probe without the mechanism under test — thread raises `RuntimeError` under `capfd` → `err == ''`;
with `threading.excepthook = threading.__excepthook__` set first → 648 bytes, `Traceback` present.
The tester's A4 anchor ("after uninstall the traceback reaches stderr") was undetectable by
construction while A5 demanded restoration of the previous hook BY IDENTITY — the two were
incompatible until the precondition was restored.

**Why:** a criterion that no implementation can satisfy gets "fixed" by weakening the assertion —
which is exactly the kind of test edit that must never happen silently. The honest fix is one line
that restores the premise the criterion assumes, documented in the class docstring.

**How to apply:** any test that relies on a stdlib default hook (`threading.excepthook`,
`sys.excepthook`, `warnings.showwarning`) sets that default explicitly inside the test body and
restores the slot in teardown (autouse fixture). To guard "the previous hook still receives the
event", use a SPY hook installed before the mechanism, not stderr. Counting
`PytestUnhandledThreadExceptionWarning` (2 → 0) is a cheap detector that the chain to pytest's hook
was cut — the reviewer used it to expose an unguarded property. Related:
[[feedback_tester_blindness_needs_a_worktree]], [[feedback_test_authorship_three_roles]].
