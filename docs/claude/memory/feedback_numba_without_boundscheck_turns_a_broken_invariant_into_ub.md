---
name: feedback_numba_without_boundscheck_turns_a_broken_invariant_into_ub
description: "numba @njit без boundscheck: нарушенный инвариант пишет за буфер → полный набор тестов ЗЕЛЁНЫЙ, следующий процесс падает 0xC0000374; ядра с буферами по инварианту держать под boundscheck=True + явная сверка"
metadata:
  node_type: memory
  type: feedback
  originSessionId: ab6ee680-f11d-43f8-962b-0ce4162bb7ff
  modified: 2026-09-04T08:08:11.933Z
---

2026-09-04, `trace_skeleton` под numba. Инъекция «не помечать обратное направление ребра» в
Python-пути дала 29 красных, в numba-ядре с той же логикой — **104 зелёных**, а следующая
заплатка упала с кодом `0xC0000374` (heap corruption). Одиночный тест под тем же патчем —
красный. Буфер `out` был рассчитан из инварианта «каждое ребро один раз»; когда инвариант
сломан, ядро пишет за границу, а numba по умолчанию границы не проверяет — итог не исключение,
а UB: молчаливый зелёный, крах в соседнем процессе, возможно битый `.nbc`-кэш.

**Why:** это худший класс ложного зелёного — не тест слеп, а память испорчена так, что тест
не может увидеть поломку. Инъекция без boundscheck доказывает ничего.

**How to apply:** ядро с буферами, размер которых выведен из инварианта, — только
`@njit(boundscheck=True)` (цена здесь 2,0 → 2,4 мс на ядро) плюс явная сверка инварианта в
Python-обвязке с `RuntimeError`. В матрице инъекций против компилируемого кода: boundscheck
включён, парсер требует `passed > 0` и `errors == 0`, кэш numba (`__pycache__/*.nb*`)
чистить между заплатками. Связано: [[feedback_zero_observations_looks_like_a_result]],
[[feedback_prove_test_red_without_fix]], [[project_strokes_points_perf]].
