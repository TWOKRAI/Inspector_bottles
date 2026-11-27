---
name: feedback-taskstop-may-leave-a-gate-waiter-alive
description: "TaskStop фонового скрипта на Windows мог оставить bash в живых: два конвейера стенда шли разом, окно освободил чужой экземпляр / a stopped background waiter may survive; make runner scripts single-instance"
metadata:
  type: feedback
  module: [scripts]
  mechanism: [test-infra]
---

**Trap.** A background script that waits for a gate window was stopped with TaskStop and replaced by a new script. The old one stayed alive. Both got the same window (the gate keys a window by session name, not by script instance), ran on the same ports, and the first to finish released the window under the other.

**Measured (2026-11-27, R2-S1a stand).** Two pipelines from 19:19:44: the second sim failed to bind (`WinError 10048`), its driver talked to the first sim, scenario S0 showed 6 exchanges that belonged to the neighbour, and both wrote the same `log/*.log`. The window was gone at 19:21:50 while the survivor ran until 19:32:30. The harness port check passed because the sim released the port after the check. TaskStop of the survivor later left its orchestrator listening on 8765.

**How to apply.**
- A runner script takes its own single-instance guard (`mkdir` of a lock directory) and exits before it touches the window or a port.
- It releases the window only if this instance got it, and stops at the first `NO WINDOW`.
- Each launch writes into its own log and run directories.
- After TaskStop, verify by effect (ports free, no new files), not by the "stopped" reply.

**Trigger.** Replacing or stopping a background script that waits for a window or starts servers.
