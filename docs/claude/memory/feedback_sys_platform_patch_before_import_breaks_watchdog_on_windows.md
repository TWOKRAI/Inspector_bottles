---
name: sys-platform-patch-before-import-breaks-watchdog-on-windows
description: "Faking sys.platform=\"linux\" before importing the framework on Windows crashes in watchdog (ctypes.CDLL(None)); import first, patch right before the call / подмена sys.platform до импорта ломает watchdog на Windows"
mechanism: [windows-env, test-infra]
role: tester
metadata:
  type: feedback
---

In a fresh-interpreter script on Windows, `sys.platform = "linux"` BEFORE `import multiprocess_framework...` dies in `watchdog.observers.inotify_c` (`ctypes.CDLL(None)` TypeError) via config_module. That is a red for the wrong reason.

**Why:** found on atlas 0.8b (2026-10-05); darwin patch survives (only a UserWarning), linux does not.

**How to apply:** import multiprocessing + framework under the real platform, patch `sys.platform` immediately before calling the unit; print `platform=` in the RESULT line so the patch is proven. Disclose that import-time platform checks are then invisible. Also: never leave a bare `python -` in a bash chain with a heredoc after it (blocks on stdin, 300 s hang). A throwaway good-stub plus mutations (non-idempotent, win32-only) turns "predicted red" into measured red.
