---
name: feedback-a-fake-that-restarts-counters-hides-a-post-reconnect-baseline
description: "A fake port that restarts frame numbers on start_grabbing keeps a post-reconnect baseline test green before the fix; inject higher numbers during the outage (фейк камеры, переподключение, опорный номер кадра, потерянные кадры, зелёный тест до правки)"
module: [services/camera_device]
mechanism: [test-doubles]
metadata:
  type: feedback
  last-verified: 2026-11-26
---

**Trap.** `Services/camera_device/testing/fake_port.py` resets `_frame_num` and `_delivered` in `start_grabbing`.
After a reconnect the numbers start from 1 again. `_on_frame` counts only a rise of the number, so a stale
baseline is invisible: the test is green on the broken code.

**Measured.** Plugin kept the baseline across `lost -> grabbing`. Frames 1..10, outage, frames from 500 injected
through `port._frame_meta`: `lost_frames` 489 (expected 0); triggers from 300: `trigger_lost` 289.

**How to apply.** For any "state carried across reconnect" test, replace `port._frame_meta` during the outage with
numbers HIGHER than before. To fix the last number before the outage, wrap `port.get_frame` so it returns `None`
after the scripted frames (otherwise the fake keeps counting). Run the test on the unchanged code first.
