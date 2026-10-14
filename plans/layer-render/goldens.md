# layer-render — золотые эталоны

Родитель: [plan.md](plan.md). Каждая задача держит зелёными эталоны, которых касается; красный эталон = находка, литералы под новый код не переписываются.

| Эталон | Что пинит |
|---|---|
| `Plugins/sim/layer_preview/tests/test_hazards_1_3h_layout.py:40-44` | sha256 `make().render()` + класс/угол/дефект, 3 пресета × seed 0..4 |
| `Plugins/sim/scene_source/tests/test_acceptance_lateral_offset_plugin.py:492-493` | sha256 12 кадров плагина + паспорта |
| `Services/line_sim/tests/test_acceptance_lateral_offset.py:355` | `rng.random()` после 40 спавнов, seed 11 |
| `Services/line_sim/tests/test_acceptance_look_1_2_ink_disk.py`, `test_hazards_look_1_2.py` | PNG инструмента букв |
| `Services/layer_render/tests/test_acceptance_2_5_render_scene.py` (A7) | sha256 кадров и паспортов `SceneCompositor`: стек `[solid, RGBA-тайл]` и цветная заливка без стека, 14 шагов энкодера |
| литералы тестеров `Services/layer_render/tests/test_acceptance_2_{1,2,3,4a,4b}_*.py` | композиция/io, эффекты, стек слоёв, пресет и каталог, фабрика и превью — снято до каждой задачи |
| `Services/dataset_gen/tests/test_augment_equivalence.py` | `apply_photometric` = список эффектов, побайтно |
| `Services/dataset_gen/tests/test_engine_golden_m4.py` (m4, `d0cdc9503`) | sha256 кадра и метка `DatasetEngine.generate_sample`: 2 конфига (фотометрия выкл/вкл), seed 0..4 и явные классы, 16 кейсов + 2 `symmetry_map`; сняты на win32; инъекции лида 4/4 (`composite` +1, яркость ×1.01, угол +1, фон +1) |
| `Services/dataset_gen/tests/test_layer_scene_golden_6_3.py` (6.3.0, `59558a638`) | выход `LayerSceneGenerator.generate_sample`: G1/G1-radius — независимый numpy-оракул (вырез fixed и radius), G2 — sha256 кадра и все поля метки, 6 кейсов, G3 — внутренний поток seed 11; 20 кейсов, сняты на win32; инъекции лида 8/8 (L1–L8, `phase-6-task-6.3.0.md`) |

**Не эталоны (приёмка CTO Ф2, 2026-10-03, M1).** Прежние строки «фон-тайл 3.6» и «`test_augment.py`, `test_engine.py`» байты не пинят: `test_scene_source_task_3_6.py` удалён в `f2f125de7` (Task 1.3); `test_*_3_6.py` проверяют период и шов тайла инструмента — зелёные под сдвигом `render_scene` на 1 px и `render_background` +1; `test_augment.py`/`test_engine.py` — 0 sha-литералов, зелёные под `composite` +1. Путь `DatasetEngine` без байтового эталона — закрыто литералом m4 (`d0cdc9503`, 2026-10-14) до кода Task 6.2.
