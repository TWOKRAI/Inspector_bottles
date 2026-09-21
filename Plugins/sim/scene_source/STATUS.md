# Plugins/sim/scene_source — STATUS

**Состояние: сделано (Task 2.2 плана line-sim).**

**Обновлено:** 2026-09-21 — Task 2.2, ветка `feat/line-sim-2.2-world`.

| Что | Состояние |
|---|---|
| `plugin.py` — `SceneSourcePlugin` | есть: `configure`/`start`/`produce`, подписка `sim.belt.**` (sync=False), обе формы дельт, протухание → предупреждение (де-дублировано по `t`) |
| Тесты | `tests/test_scene_source_acceptance.py` — 4 независимого tester (RED до этой задачи, worktree `362a319a`); `tests/test_scene_source_hazards.py` — 4 авторских (гонка старта, обе формы дельт в одной последовательности, де-дупликация предупреждения, конкурентность колбэка/produce) |
| Границы | `tests/test_scene_source_acceptance.py::test_no_forbidden_imports` — 0 запрещённых импортов |

## Долг / открытые вопросы

- Позиция спрайта — единственная колонка, задний край привязки
  (`round(x_px) - 1`); это интерпретация разработчика, выведенная из
  диф-теста тестера (эталон на `spawn_encoder=0` обязан быть невидим), а не
  буквальная часть DESIGN брифа ведущего — см. отчёт разработчика,
  `docs/reviews/2026-09-21_task-2.2-developer.md`.
- `mm_s` в мире (`sim.belt.encoder.mm_s`) публикуется паблишером как
  производная энкодера МЕЖДУ тиками публикации (`Plugins/sim/robot_host`), а
  не читается из `BeltDrive` напрямую — `RobotSimCore`/`BeltDrive` не выставляют
  публичного аксессора скорости (Task 2.1b их не трогает). `scene_source`
  само это значение не использует (только `value`/`t`) — упомянуто здесь как
  контекст, не как долг этого пакета.
- Живой прогон (`apps/line_sim/tests/test_f2_task22_live.py`,
  `LINE_SIM_LIVE=1`) — числа и статус см. отчёт разработчика.
