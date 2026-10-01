---
name: feedback-cv-threads-tuning
description: When configuring or tuning a recipe for throughput, consider the per-process cv_threads key (OpenCV internal pool), not only our workers
metadata:
  type: feedback
---

Every process has a per-recipe key `cv_threads` (Task 4.6 of transport-single-policy, default 2): the size of
OpenCV's INTERNAL thread pool, set via `cv2.setNumThreads` in the process runner before the process class is
built. It is not our worker threads — OpenCV splits a frame across its own pool, and by default that pool equals
the core count in EVERY process (measured 16 on the owner's machine; processor burned 5.2 cores).

**Why:** the owner asked (2026-09-29) that agents remember this knob when tuning — the right value is
scenario-dependent: raise it (4–8) for one heavy process on large frames while others idle; 1 for light work
or small frames; the sum over simultaneously busy processes ≈ core count.

**Form:** `extras: {cv_threads: N}` in the process block. A FLAT `cv_threads: N` is silently folded into
`metadata` by the domain model and never reaches the process (verified on the 4.6 stand; the extras-only
convention is enforced by `TestExtrasShorthandDriftGuard` in `multiprocess_prototype/domain/tests/`).

**How to apply:** when a recipe is slow or CPU-heavy, check `introspect.status` → `cv_threads` per process and
tune it in the recipe by measurement (per-process CPU and plugin time via backend_ctl, see
[[windows-cpu-psutil-tick-sampled]]), never by eye. The template comment lives in
`multiprocess_prototype/backend/topology/TEMPLATE.yaml` (processor block).
