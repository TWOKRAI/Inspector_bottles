---
name: reorder-after-event-set-is-invisible
description: "Перестановка вызова после Event.set() гонкой не ловится: следующий короткий вызов сеттера обгоняет разбуженного; Barrier пускает последнего первым / injection «do X after Event.set()» stays green in races"
mechanism: [concurrency, break-injection]
role: teamlead
metadata:
  type: feedback
---

Moving a short call from before `Event.set()` to after it is almost never caught by a thread race (Task 0.3 hand-off to parent: 0/3 runs red in 100-iteration race and in the tester's overlap test; red only with an added `sleep(0.001)`). The woken waiter needs the GIL and runs many bytecodes before it reaches the shared state; the setter's next call wins.

Also: with `threading.Barrier(2)` the thread that arrives last passes without blocking and usually runs first — a "symmetric" race was 100/100 one-sided until I made the second thread spin until the first one was inside (`while not c.closed`).

**Why:** a green race under a reorder injection looked like proof of nothing; measuring the interleaving distribution (Counter over outcomes) showed the race never happened.

**How to apply:** for ordering-before-signal fixes, report the injection honestly as "red only with delay"; force the overlap explicitly (spin on an observable state) and measure the outcome distribution before trusting a race test. Related: [[poller-misses-submillisecond-window]], [[thread-storm-does-not-prove-a-lock]].
