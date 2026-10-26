## Раунд 2

- R2A: **PASS**
  - разброс min/median/max: {"branch/camera_0": {"n": 9, "unanswered": 0, "min": 2.03, "median": 4.16, "max": 4.45, "p99": 4.45}, "branch/devices": {"n": 9, "unanswered": 0, "min": 1.56, "median": 1.88, "max": 2.14, "p99": 2.14}, "main/camera_0": {"n": 9, "unanswered": 0, "min": 2.03, "median": 4.23, "max": 4.7, "p99": 4.7}, "main/devices": {"n": 9, "unanswered": 0, "min": 1.59, "median": 1.97, "max": 2.94, "p99": 2.94}}
- R2B: **PASS**
- R2C: **FAIL**
  - branch run 6: 2.015 с >= 2.0
  - branch run 7: 2.031 с >= 2.0
  - main run 4: 2.156 с >= 2.0
  - разброс min/median/max: {"branch": {"n": 10, "unanswered": 0, "min": 1.125, "median": 1.5859999999999999, "max": 2.031, "p99": 2.031}, "main": {"n": 10, "unanswered": 0, "min": 1.125, "median": 1.4845000000000002, "max": 2.156, "p99": 2.156}}
