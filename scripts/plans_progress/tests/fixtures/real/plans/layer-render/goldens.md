# layer-render — золотые эталоны

Родитель: [plan.md](plan.md). Каждая задача держит зелёными эталоны, которых касается; красный эталон = находка, литералы под новый код не переписываются.

| Эталон | Что пинит |
|---|---|
| `Plugins/sim/layer_preview/tests/test_hazards_1_3h_layout.py:40-44` | sha256 `make().render()` + класс/угол/дефект, 3 пресета × seed 0..4 |
| `Plugins/sim/scene_source/tests/test_acceptance_lateral_offset_plugin.py:492-493` | sha256 12 кадров плагина + паспорта |
| `Services/line_sim/tests/test_acceptance_lateral_offset.py:355` | `rng.random()` после 40 спавнов, seed 11 |
| `Services/line_sim/tests/test_acceptance_look_1_2_ink_disk.py`, `test_hazards_look_1_2.py` | PNG инструмента букв |
| `Services/line_sim/tests/test_acceptance_3_6.py`, `test_hazards_3_6.py`, `Plugins/sim/scene_source/tests/test_scene_source_task_3_6.py` | фон-тайл (старый путь `background_texture`) |
| `Services/dataset_gen/tests/test_augment.py`, `test_engine.py` | фотометрия и движок датасета |
