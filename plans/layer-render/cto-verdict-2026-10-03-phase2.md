# Вердикт CTO (Fable) — приёмка Ф2 и merge gate `feat/layer-render` → `main` — 2026-10-03

Родитель: [plan.md](plan.md). Прошлый вердикт: [cto-verdict-2026-10-01.md](cto-verdict-2026-10-01.md). Дерево приёмки
`c146064a6` (с влитым `main` `0ce55ac1f`). Агент `cto` (Fable), 250k токенов, 24 мин. Все числа — его прогон.

**Вердикт 1 — приёмка Ф2 «ядро `Services/layer_render`»: ACCEPT WITH CONDITIONS.**
**Вердикт 2 — merge gate `feat/layer-render` → `main`: ACCEPT WITH CONDITIONS** (один `docs(plans)`-коммит до слияния).
Блокеров нет.

## Три объектива

- **Проводка.** На реальных данных стенда: `line_sim.ObjectFactory.make` и `layer_render.ObjectFactory.render` — 20/20 seed
  равны (rgba, класс, угол, дефект, `layer_params`), rgba read-only; `load_scene_preset` (старый путь) и
  `ScenePreset.from_yaml` (новый) — равные `to_dict()`; `render_scene` на входах вне спеки (scroll −123456, отрицательный
  origin, объект за кадром, эффекты blur+noise+jpeg с `rng(42)`) — по контракту. Эталон плагина
  `test_acceptance_lateral_offset_plugin.py` (литерал до Ф1) — зелёный.
- **Честность тестов.** 8 осей подмены `__code__` (pytest-плагин, файлы не тронуты), база 1849 passed: `composite` +1 →
  170 красных; `render_scene` roll 1 px → 16; `render_background` +1 → 53; лишний розыгрыш `apply_effects` → 22;
  `transform_layer` +1 → 142; `get_sprite` всегда первый → 2; угол `render` +1 → 82; лишний `rng.random()` в
  `compose_layers` → 85. Все оси живые.
- **Фундамент.** 77 пар «старый путь `is` новый» — все `True`. Два имени дают два объекта: `ObjectFactory` (подкласс по
  дизайну) и `RangeF` (равные алиасы). Статических циклов 0; 40 модулей чистым процессом первыми — rc=0. Потребители вне
  Files не правились. `sentrux check .` 41 rules pass; `validate.py` exit 0; `git merge-tree` с `main` — без конфликтов;
  трейлеры 73/73; `line_sim + dataset_gen + ml_train` — 910 passed, 2 skipped.

Решения 2026-10-01: 2, 3, 7 выполнены; условие (б) выполнено (LR-002); условия (а) и (в) не записаны.

## Находки

| # | Суть | Когда |
|---|---|---|
| M1 | `goldens.md` строки 5–6 байты не пинят (файл 3.6 удалён в `f2f125de7`; `test_*_3_6` и `test_augment`/`test_engine` зелёные под инъекциями) | до слияния — исправлено |
| M2 | статусы в спек-файлах `[PENDING]`/`[IN PROGRESS]` при `DONE` в `plan.md` | до слияния — исправлено |
| m1 | `Services/STATUS.md:35` описывает `layer_render` как «стек фона (1.1)» | до слияния — исправлено |
| m2 | условие (в) 2026-10-01 (риск второго RGBA-тайла, 39.5 мс) не записано; (а) grep не подтверждает | (в) — follow-up; (а) — в 3.1 |
| m3 | докстринг `Plugins/sim/scene_source/plugin.py:955` ссылается на переворот каналов в `render()`, которого нет | follow-up |
| m4 | путь `DatasetEngine` без байтового эталона (`composite` +1 пережил `test_engine.py`) | литерал до Task 6.2 |
| m5 | `RangeF` определён дважды (равные алиасы) | по желанию |

Открыто у CTO: Plugins/sim целиком и apps/line_sim не перегонял (числа лида); процессный стенд не поднимал; подпроцессные
тесты (A7 2.4b, A1 2.5) инъекции через `__code__` не видят; литералы сняты на win32. Судьба `DatasetEngine` (решение 6) —
у владельца.
