# line_sim — статус

**Состояние:** Task 3.1 + 3.1a + 3.2 + 3.3 + 3.4 (план `plans/line-sim/phase-3-object-engine.md`).

| Часть | Статус |
|---|---|
| Контракт слоя/паспорта (`interfaces.py`) | готово |
| `LayeredObject` — выборка и рендер один раз | готово |
| `ScenePreset` — dict/YAML round-trip, валидация | готово (каталог + слои) |
| `encoder_to_offset_mm` | готово |
| `SceneCompositorProtocol` (Protocol) + `SceneCompositor` (реализация) | готово (Task 3.4, LS-009) |
| `ObjectPassport.to_dict()`/`from_dict()` | готово (Task 3.4, Dict at Boundary) |
| `ObjectFactory` + `catalog_bridge` — класс/угол из rng, дефект-слой `"damaged"`, `force_defect_next()` | готово |
| Пресет `letters_disk.yaml` | готово (ссылается на каталог dataset_gen, картинок не копирует) |
| `ObjectSpawner` — спавн по интервалу, деспавн, пауза, форс-хук брака на паузе | готово |
| Подключение к `SceneSourcePlugin` (`Plugins/sim/scene_source`) | готово (Task 3.4) |

**Известное ограничение (2026-09-22):** эталоны дисков-букв реально не сняты на этой машине —
`data/dataset_gen/ru_letters_real/sprites` отсутствует. `tools/cut_real_disks.py` готовит их из
фото (см. `Services/dataset_gen/README.md` → `cut_real_disks`). До тех пор
`test_real_letters_disk_num_classes_or_skip` в `tests/test_acceptance_3_2.py` — легитимный skip
(тот же критерий проверен на каталоге-фикстуре в `tmp_path`); `ObjectFactory` и `letters_disk.yaml`
работают с любым каталогом формата `SpriteCatalog`, не только с этим конкретным.

Тесты: `Services/line_sim/tests/` — `test_acceptance_3_1.py`/`test_acceptance_3_2.py`/
`test_acceptance_3_3.py`/`test_acceptance_3_4.py` (независимый tester), `test_hazards_3_1.py`/
`test_hazards_3_2.py`/`test_hazards_3_3.py`/`test_hazards_3_4.py` (автор).
