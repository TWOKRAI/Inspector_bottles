---
name: reference-delta-rl-manual
description: "Official Delta DRAStudio manuals (RL language 2024, CVT 2022) live outside this repo; key facts already extracted and which of them contradict v1 firmware."
metadata:
  node_type: memory
  type: reference
  last-verified: 2026-09-27
  originSessionId: c32ae566-e57e-41ad-ae5f-46899ddaeaf0
  modified: 2026-09-26T22:37:40.746Z
---

Manuals (text PDFs, pypdf extracts cleanly; no special tool needed):
`/Users/twokrai/Project_code/PROJECT_INNOTECH/knowledge-base/inbox/books/DELTA_IA-ROBOT_DRAStudio_RL_EN_20240920.pdf`
(246 pp, robot language RL) and `DELTA_IA-ROBOT_DRAStudio_CVT_EN_20220905.pdf` (67 pp, conveyor tracking).
The owner also offered a controller hardware manual on request (not fetched yet).

Facts that change design (page = manual page label):
- 4th axis item in WritePoint/ReadPoint is "RZ" (5-9, 5-10); v1 `robot/main_actual.lua:501,511` writes "R" — likely a v1 bug in place-pose rotation.
- User Modbus 0x1000..0x1FFF volatile, 0x3000..0x3FFF retained on power loss (12-2); W range ±32767.
- TimerOn()/TimerRead() ms timer (3-4); MultiTask is obsolete, AuxTasks slices 15 ms (11-4..11-6).
- ReadPoint exists (5-9); global points stored in internal memory, local points 1001..31000 must pre-exist in the project (5-2, 5-5).
- RSmasterRead/RSmasterWrite built-in RS-485 Modbus master (12-6); MotionStop decelerates with current Dec, DecL max 25000 (1-51, 2-8).
- `goto` is a keyword → Lua ≥ 5.2. Also available: MovLR, MArchP/MArchL, ContinueCartesianJOG (non-blocking), OpenWorkSpace/WorkSpace, registerErrorHandleFile.

DRAStudio has a "Virtual Robot" connect mode (Delta FAQ 2336); whether it runs Lua and serves Modbus TCP is unverified.
All of the above is re-checked on hardware by `robot/pc_platform_probe/` (GATE-1). Related: [[project-work-order-2026-09-22-line-sim-then-pult]].
