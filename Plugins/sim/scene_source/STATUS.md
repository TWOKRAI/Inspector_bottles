# Plugins/sim/scene_source — STATUS

**Состояние: сделано (Task 2.2 плана line-sim).**

**Обновлено:** 2026-09-22 — Task 2.2, ветка `feat/line-sim-2.2-world`, правка
по живому расследованию ведущего (бесконечная лента + спрайт-квадрат).

| Что | Состояние |
|---|---|
| `plugin.py` — `SceneSourcePlugin` | есть: `configure`/`start`/`produce`, подписка `sim.belt.**` (sync=False), обе формы дельт, протухание → предупреждение (де-дублировано по `t`), спрайт-квадрат 32×32 `SPRITE_BGR`, бесконечная лента (без зажима) |
| Тесты офлайн | `tests/test_scene_source_acceptance.py` (tester) — 4/4 (хелпер поиска спрайта — цветовая маска, арбитраж ведущего 2026-09-22); `tests/test_scene_source_hazards.py` — 5/5 (вкл. перенос через край) |
| Тесты live | `apps/line_sim/tests/test_f2_task22_live.py` (`LINE_SIM_LIVE=1`) — 5 passed (camera_alone живой), 3× подряд |
| Границы | `tests/test_scene_source_acceptance.py::test_no_forbidden_imports` — 0 запрещённых импортов |

## Долг / открытые вопросы

- Сцена обновляется ≈8 раз/с, не 20: дельты мира приходят пачками ~120 мс (замер ревью 2026-09-22).
- Один объект, без spawn/despawn и реальных спрайтов — Ф3.
- Числа живых прогонов — `docs/reviews/2026-09-21_task-2.2-developer.md`.
