---
name: poller-misses-submillisecond-window
description: A background poll thread cannot see a state window shorter than its tick (stop→respawn in restart); snapshot the state at the entry of the next step instead
metadata:
  type: feedback
---

A daemon thread polling a flag every 1 ms stayed GREEN under the exact break it guarded
(restart marked the reused queue, create_and_register cleared it < 1 ms later — Task 1.2
lifecycle-stop-ownership, 2026-09-24). Replaced with a wrapper on the next step's entry
(`create_and_register`) that records the flag at the window point; then the injection killed it.

**Why:** GIL switch interval (5 ms) and the poll tick are both longer than in-thread windows
between two synchronous calls; "never observed" is absence of news (see [[absence-of-news-is-not-evidence]]).

**How to apply:** when the hazard is "state X visible between step A and step B" in one thread,
assert X at the entry of B (wrap B), not by concurrent polling; always break-inject it.
