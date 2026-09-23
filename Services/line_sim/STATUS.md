# line_sim — статус

**Состояние:** Task 3.1 + 3.1a + 3.2 + 3.3 + 3.3a + 3.4 + 3.6 (план `plans/line-sim/phase-3-object-engine.md`).

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
| `ObjectSpawner` — спавн по интервалу ИЛИ по шагу ленты в мм, деспавн, пауза, форс-хук брака | готово (Task 3.3, режим `spacing_mm` — Task 3.3a, LS-010) |
| Подключение к `SceneSourcePlugin` (`Plugins/sim/scene_source`) | готово (Task 3.4; `spawn_spacing_mm` — Task 3.3a) |
| Фон-тайл в `SceneCompositor` (`background_tile`) + `tools/make_seamless_texture.py` | готово (Task 3.6, LS-011); на реальном фото ленты ещё не прогонялся — ждёт снимка владельца |
| `core/matching.py` (`match_job`/`object_robot_xy`, `BeltGeometry`/`JobDone`/`MatchResult`) + `ObjectSpawner.remove()` | готово (Task 3.5a, LS-012) — job↔object matching для плагина сцены (часть B) |
| `core/truth.py` (`TruthLedger`) — поймал/пропустил/дубль/ложная тревога/ошибка захвата | готово (Task 5.2; 5.1b — `false_alarm_frozen_xy`: ложная тревога в той же точке X/Y с другим `ecap`, окно `frozen_window_s` 10 с по `job.t`, радиус `frozen_radius_mm` 5 мм); подключение к `Plugins/sim/scene_source` — команды `truth.status`/`truth.reset`, уровни `truth_*` (ADR-PM-038, прореживание `truth_publish_s`) |
| `SceneCompositor(belt_direction, entry_x_px)` + `tools/make_letter_catalog.py` — сим подогнан под боевой рецепт `hikvision_letter_robot.yaml` | готово (Task 5.3b, контракт §4.1–§4.2); согласованность геометрии сима с `bilinear_px_to_mm` прототипа сторожит `apps/line_sim/tests/test_fit_letter_robot.py` |

**Известное ограничение (2026-09-22):** эталоны дисков-букв реально не сняты на этой машине —
`data/dataset_gen/ru_letters_real/sprites` отсутствует. `tools/cut_real_disks.py` готовит их из
фото (см. `Services/dataset_gen/README.md` → `cut_real_disks`). До тех пор
`test_real_letters_disk_num_classes_or_skip` в `tests/test_acceptance_3_2.py` — легитимный skip
(тот же критерий проверен на каталоге-фикстуре в `tmp_path`); `ObjectFactory` и `letters_disk.yaml`
работают с любым каталогом формата `SpriteCatalog`, не только с этим конкретным.

Тесты: `Services/line_sim/tests/` — `test_acceptance_3_1.py`/`test_acceptance_3_2.py`/
`test_acceptance_3_3.py`/`test_acceptance_3_4.py`/`test_acceptance_3_6.py`/`test_acceptance_5_2.py`/
`test_acceptance_5_3b.py`
(независимый tester), `test_hazards_3_1.py`/
`test_hazards_3_2.py`/`test_hazards_3_3.py`/`test_hazards_3_4.py`/`test_hazards_3_6.py`/`test_hazards_5_2.py`/
`test_hazards_5_3b.py`
(автор), `test_spawner.py`
(автор, режим `spacing_mm` — Task 3.3a, независимого тестера на этой задаче намеренно нет,
см. LS-010).
