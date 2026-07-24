---
name: project_strokes_points_perf
description: webcam_sketch FPS-просадка на детальных кадрах = O(n²) sort + пересчёт каждый кадр; NumPy не векторизует trace_skeleton
metadata:
  node_type: memory
  type: project
  originSessionId: eb29baac-57ba-4bcc-a322-dd956afb0ae8
  modified: 2026-07-24T06:24:09.876Z
---

Симптом: в рецепте webcam_sketch «больше контуров/точек → просадка FPS, задержка; мало точек → быстро». Тормозила обработка точек ПОСЛЕ TEED (не сеть). Два узких места, оба растут с числом штрихов (2026-07-24, Plugins/processing/strokes_to_points):

1. `geometry.sort_nearest_neighbor` был O(n²) — пересобирал NumPy-массив начал на каждой итерации. 400 штрихов = 25 мс, 800 = 96 мс/кадр. ГЛАВНЫЙ драйвер. Фикс: массив строится один раз, занятые → inf, argmin по квадрату расстояния. Побайтово тот же вывод (сверено с эталоном на 20 наборах), 5–9× быстрее.
2. Геометрия считалась каждый кадр, даже когда маска не менялась. edge_detection при `inference_every_n>1` отдаёт ТОТ ЖЕ объект `_last_mask`. Фикс: мемоизация в plugin.py, ключ = маска (np.array_equal) + снимок всех live-tunable register-полей (пульт продолжает работать). Кэш-попадание 0.04 мс vs 65 мс на кадре со 119 контурами.

**Почему НЕ Rust/NumPy для остатка:** `trace_skeleton` — обход графа скелета (pointer-chasing, ~20 мс, линейно от пикселей). NumPy не векторизует: точная переделка = 1.3×, int-индексная = 1.4× но МЕНЯЕТ вывод (другой порядок обхода развилок). Правильный инструмент здесь — Numba `@njit` на одну функцию (pip, без Rust-тулчейна под Win+Mac), либо снизить детализацию тюнингом (min_stroke_len / DP epsilon / blob min_area — всё в пульте). См. [[feedback_plausible_is_not_verified]], [[project_webcam_sketch_freeze]].

**Why:** диагноз стоил профилирования; неочевидно, что виноват sort, а не сеть/скелетизация, и что NumPy принципиально не ускорит граф-walk.
**How to apply:** при жалобах на FPS webcam_sketch — сначала профилировать sort/trace, не сеть; хотспот-graph-walk = Numba, не Rust и не NumPy.
