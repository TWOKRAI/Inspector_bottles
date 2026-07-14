---
name: app-module-windows-test-debt
description: "2 app_module-теста красные ТОЛЬКО на Windows (os.replace WinError 5 + endswith прямой слэш) — pre-existing долг, не seqlock/G.3; зелёные на Mac/CI-Linux"
metadata:
  node_type: memory
  type: project
---

**Долг (заведён 2026-07-14 при старте Ф7 G.4):** на Windows-машине владельца
стабильно красны 2 теста `app_module`, оба **платформенно-специфичны** (зелёные на
Mac/CI-Linux — поэтому CI их не ловит, а полный локальный suite показывает «2
pre-existing fail»). К seqlock/G.3 отношения не имеют.

1. **`test_concurrent_writes_multiprocess_no_lost_update`**
   (`multiprocess_framework/modules/app_module/tests/test_manifest_store.py:93`) —
   `PermissionError: [WinError 5]` на `os.replace(tmp, self._path)` в
   `app_module/store.py:148`. Причина: на POSIX `os.replace` атомарно заменяет файл
   даже под открытыми хендлами, на **Windows** — не может заменить файл, открытый
   другим процессом. `ManifestStore._atomic_write_unlocked` полагается на flock
   (advisory) + atomic-replace; под spawn-конкуренцией 6 процессов на Windows
   os.replace конфликтует. Это реальная Windows-дыра атомарности ManifestStore (NEW-1
   из 5.11), не только тест.

2. **`test_minimal_app_manifest_and_discovery`**
   (`multiprocess_framework/modules/app_module/tests/test_minimal_app_smoke.py:32`) —
   `assert any(p.endswith("minimal_app/plugins") ...)` падает, потому что на Windows
   путь `discovery.plugin_paths` через `\` (`minimal_app\plugins`), а литерал в тесте
   с прямым слэшем. Баг **в тесте** (path-separator), не в коде.

**Why:** владелец работает Win+Mac ([[macos-shm-skipped-tests]]); CI = Linux → эти
падения невидимы в CI, всплывают только в локальном полном прогоне и создают шум
«2 fail» в каждом гейте фазы Ф7 (маскируют новые регрессы).

**How to apply:** чинить **отдельной** мелкой задачей (не в скоупе G.4):
(1) тест discovery — `os.path.normpath`/`Path`-сравнение вместо `endswith` со слэшем;
(2) store — на Windows retry-петля вокруг `os.replace` (ERROR_ACCESS_DENIED транзиентен
при конкуренции) ИЛИ пометить тест `@pytest.mark.skipif(win + spawn)` с трекингом дыры.
До фикса эталон полного suite Ф7 = «N passed, 2 pre-existing app_module fail (Windows)».
Связано с [[f7-g3-handoff]] (там эти 2 fail зафиксированы как pre-existing на чистом main).
