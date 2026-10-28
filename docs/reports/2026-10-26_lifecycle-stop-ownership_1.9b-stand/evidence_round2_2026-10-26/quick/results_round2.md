## Раунд 2

- R2A: **FAIL**
  - branch s1 camera_0 #2: запрос драйвера завершился 'timeout' (не ответ PM)
  - branch s1 camera_0 #2: ОТВЕТ РАНЬШЕ строки PM restarted на 0.339 с
  - branch s1 camera_0 #2: 5.03 с >= 5.0
  - branch s1 camera_0 #3: запрос драйвера завершился 'timeout' (не ответ PM)
  - branch s1 camera_0 #3: ОТВЕТ РАНЬШЕ строки PM restarted на 0.210 с
  - branch s1 camera_0 #3: 5.03 с >= 5.0
  - разброс min/median/max: {"branch/camera_0": {"n": 3, "unanswered": 0, "min": 2.25, "median": 5.03, "max": 5.03, "p99": 5.03}, "branch/devices": {"n": 3, "unanswered": 0, "min": 1.64, "median": 2.36, "max": 2.94, "p99": 2.94}, "main/camera_0": {"n": 3, "unanswered": 0, "min": 2.14, "median": 4.74, "max": 4.83, "p99": 4.83}, "main/devices": {"n": 3, "unanswered": 0, "min": 1.67, "median": 2.28, "max": 2.86, "p99": 2.86}}
- R2B: **PASS**
- R2C: **PASS**
  - разброс min/median/max: {"branch": {"n": 1, "unanswered": 0, "min": 1.078, "median": 1.078, "max": 1.078, "p99": 1.078}, "main": {"n": 1, "unanswered": 0, "min": 1.188, "median": 1.188, "max": 1.188, "p99": 1.188}}
