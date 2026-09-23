# Plugins/sim/scene_source — STATUS

**Состояние: сделано (Task 2.2 + Task 3.4 + Task 3.6 + Task 3.5b плана line-sim).**

**Обновлено:** 2026-09-23 — Task 3.6: ключ `background_texture`, фон-тайл едет с энкодером (до этого — Task 3.4, заглушка-спрайт заменена движком `Services.line_sim`).

| Что | Состояние |
|---|---|
| `plugin.py` — `SceneSourcePlugin` | есть: `configure`/`start`/`produce`, подписка `sim.belt.**` (sync=False, не тронуто Task 3.4), обе формы дельт, протухание → предупреждение (де-дублировано по `t`); движок line_sim (`ScenePreset`/`ObjectFactory`/`ObjectSpawner`/`SceneCompositor`), fallback на фон при недоступном каталоге, `sim.objects` в мир по смене состава |
| Тесты офлайн | `tests/test_scene_source_acceptance.py` (tester, Task 2.2, минимально обновлён Task 3.4 — см. блок правки в файле) — 4/4; `tests/test_scene_source_hazards.py` (автор) — 8/8 (Task 2.2: гонка старта/обе формы дельт/де-дублирование/конкурентность; Task 3.4: воспроизводимость по seed, падающая фабрика не роняет кадр, `sim.objects` только по смене состава, item без `sim_truth`) |
| Тесты live | `apps/line_sim/tests/test_f2_task22_live.py` (`LINE_SIM_LIVE=1`) — прогонялось на Task 2.2; живой стенд с движком — шаг лида (не в этом коммите) |
| Тесты Task 3.6 | `tests/test_scene_source_task_3_6.py` (tester) — нечитаемая текстура: 1 `log_error`, объекты живы; порядок каналов BGR; `tests/test_scene_source_hazards_3_6.py` (автор) — путь от корня репо при чужом CWD, битый файл |
| Задания робота (Task 3.5b) | есть: команды `scene.job_done`/`scene.status`, конфиг `geometry`/`match_radius_mm`/`dup_window_s`, разбор очереди в начале `produce()` (`match_job` → `spawner.remove`); `tests/test_scene_source_task_3_5.py` (tester) — 7/7; `tests/test_scene_source_hazards_3_5.py` (автор) — 3/3 (200 заданий из 4 потоков во время `produce()`, `ecap` далеко впереди мира, два задания на объект в одном разборе) |
| Границы | `tests/test_scene_source_acceptance.py::test_no_forbidden_imports` — 0 запрещённых импортов |
| Направление ленты / точка входа (Task 5.3b) | есть: конфиг `belt_direction`/`entry_x_px` → `SceneCompositor`; `tests/test_scene_source_hazards.py::test_belt_direction_minus_one_object_moves_toward_smaller_x` (автор, WIRING реальным плагином+движком) |

## Долг / открытые вопросы

- Сцена обновляется ≈8 раз/с, не 20: дельты мира приходят пачками ~120 мс (замер ревью 2026-09-22, Task 2.2, актуально и с движком).
- `scene_length_mm`/`belt_y_px` дефолты — эвристика разработчика (не измерены на живом стенде), см. README.
- Task 3.5b: объект, уехавший за `scene_length_mm` раньше «выполнено», даёт `no_object` (см. README).
- Task 3.5b: гонка «команда против `produce()`» сторожится вероятностно — авторский
  break-injection ловит «`recent` без замка» 2 раза из 5, «снимок очереди → `clear()`» без
  расширенного окна не ловит вовсе (см. докстринг `test_scene_source_hazards_3_5.py`).
- Живой двухпроцессный стенд с реальным движком (счётчик `line_filter` > 0) — шаг лида, не проверено в этом коммите.
