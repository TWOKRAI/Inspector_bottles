---
name: feedback-a-late-test-edit-needs-the-whole-test-dir
description: "Поправил один тестовый файл и прогнал только его — сторож всего каталога покраснел позже / after a late test edit run the whole test directory, directory-wide guards do not live in the edited file"
metadata:
  type: feedback
  module: [services]
  mechanism: [test-infra]
---

**Trap.** After the last full run, a small edit to one test file was verified by running that file alone. A guard that scans the whole directory was not collected.

**Measured (2026-11-28, R2-S1d).** A new `monkeypatch.setattr(rig.drv._client, "stop", ...)` seam: the edited file 45 passed, then the pre-merge run failed `test_no_private_driver_state.py::test_seam_whitelist_is_literal` (`_client`: 3 != 2) after 16 minutes of `Services/device_hub/tests`.

**How to apply.** After the last test edit run the whole test directory, or at least its guard tests (`test_no_private_driver_state.py` in `Services/device_hub/tests`). Patch a method on the class (`monkeypatch.setattr(RobotClientV2, "stop", ...)`) instead of reaching through a private driver field.

**Trigger.** A test edit after the full run, especially one that adds a seam through `drv._something`.
