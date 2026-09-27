# Task 1.2a — команды пресета `scene_source` (teamlead, реализация)

План: `plans/line-sim-layer-editor.md`, Task 1.2a «Устройство», критерии P1–P8.
Цепочка: tester RED → **teamlead** → лид (инъекции, документация) → reviewer.

DESIGN (от лида): `preset.get/commit/preview` на плагине; commit проверяет вне лока, под
`_preset_lock` сверяет rev с байтами файла и пишет атомарно (tmp в том же каталоге → `os.replace`),
передаёт фабрику воркеру; `produce()` подменяет фабрику до `tick()`; `ObjectSpawner.set_factory`
переносит невыпущенный форс-брак; `ObjectFactory.force_defect_pending`.

## Что сделано

| Файл | Изменение |
|---|---|
| `Plugins/sim/scene_source/plugin.py` | 3 команды; `_apply_defect_override` — общий шов override для `configure()` и commit/preview; `_apply_pending_factory` в `produce()` сразу после `_drain_jobs()`; атомарная запись с сохранением прав файла |
| `Services/line_sim/core/spawner.py` | `set_factory(factory)` |
| `Services/line_sim/core/factory.py` | свойство `force_defect_pending` |
| `Plugins/sim/scene_source/tests/test_scene_source_hazards_1_2a.py` | 9 hazard-тестов |
| `Services/line_sim/tests/test_hazards_1_2a_set_factory.py` | 3 hazard-теста |

## Прогоны

- `pytest Services/line_sim/tests Plugins/sim/scene_source -q` → `324 passed, 1 skipped`
  (пропуск существовал и раньше: `test_acceptance_3_2.py:313` — эталоны владельца не сняты на этой машине).
- Приёмка тестера `test_acceptance_1_2a_preset_commands.py` → `9 passed` (8 RED + контроль).
- `ruff check Services/line_sim Plugins/sim/scene_source` → `All checks passed!`; `ruff format --check` чист.

## Авторские инъекции (прогноз записан до прогона; полная матрица — у лида)

| Инъекция | Прогноз упавших | Факт |
|---|---|---|
| I1 `set_factory` не переносит форс-брак | 2 (сервис + плагин) | совпало |
| I2 проигравший `conflict` кладёт свою фабрику | 2 (последовательный + потоковый) | совпало |
| I3 без `copymode` | `test_commit_keeps_file_mode` | совпало |
| I4 без удаления tmp | `test_io_error_on_replace…` | совпало |
| I5 preview через живую фабрику | `test_preview_does_not_consume…` | совпало |
| I6 preview тянет `self._rng` плагина | мой + **`test_p6` тестера** | **расхождение: `test_p6` зелёный** |
| I7 `base_dir` клиента побеждает | `test_client_base_dir_is_ignored` | совпало |
| I8 `produce()` не применяет фабрику | 4 моих + `test_p5` | совпало |

**Находка по I6 (в тестах тестера, не в коде):** `test_p6_preview_grid_and_no_effect_on_frames`
слеп к тому, что preview сдвигает rng плагина: после preview он делает 3 шага без паузы, а при
`spawn_interval_s=[0.01, 0.02]` за это время спавна нет, и кадры близнецов совпадают при любом
состоянии rng. Свойство держит мой `test_preview_does_not_consume_forced_defect_or_rng`
(режим `spawn_spacing_mm`, 12 шагов, спавн почти на каждом). Решение за лидом: исправлять ли p6.

## Замер

`preset.preview` по умолчанию (8 сидов, тайл 160), фикстура hazard-тестов (диск 30×30 + буква
20×20): `png_b64` = 10 868 символов, JSON-ответ = **12 158 байт**, ~12 мс. На реальных пресетах
(`Services/line_sim/presets/letters_*.yaml`) замерить не удалось: в worktree нет каталога классов,
движок не собирается.

## Что я истолковал, а не выполнил буквально

1. **Передача фабрики — `deque(maxlen=1)`, не голое поле.** DESIGN: «одно присваивание ссылки,
   воркер читает и очищает». Если поток переключится между «прочитал» и «очистил», commit,
   пришедший в этот момент, потеряется: файл новый, а лента работает на старой фабрике.
   У `deque(maxlen=1)` операции `append` (затирает неприменённую) и `popleft` атомарны в CPython —
   тот же приём, что уже используется для `_jobs`. Семантика та же: один слот, в силе последняя фабрика.
   Детерминированного красного теста на эту потерю нет (окно — несколько байткодов).
2. `copymode` перед `os.replace`: `NamedTemporaryFile` создаёт файл с правами 0600, и без
   `copymode` commit менял бы права пресета. Закреплено `test_commit_keeps_file_mode`.
3. `base_dir` у плагина, собранного из каталога (он бывает только в preview): корень
   репозитория (`_REPO_ROOT`), от которого резолвится и `preset_path` конфига.
4. Preview применяет override `defect_probability` из конфига стенда, как живая лента;
   в файл при commit пишется пресет клиента **без** override.
5. `preset.get` читает `rev` раньше пресета и под `_preset_lock`. Если внешний писатель
   вклинится между двумя чтениями, клиент получит старый `rev`, и его commit уйдёт в `conflict`.
6. Seeds должны быть `>= 0`: `default_rng(-1)` бросает исключение, поэтому отрицательный сид → `bad_request`.
7. `class_names` берутся из `_live_factory` плагина. Эта ссылка обновляется воркером при подмене,
   поэтому приватное поле спавнера наружу не открываю.

## Что оставил открытым / ненадёжным

- `os.replace` по симлинку заменяет сам симлинк обычным файлом. Не проверено и не обработано.
- Нет `fsync` ни tmp, ни каталога: при потере питания сразу после commit на диске может остаться
  старое содержимое или пустой файл. Атомарность здесь — против читателей, а не против сбоя питания.
- В hazard-тестах есть белый ящик: `plugin._spawner._factory._preset`, `force_defect_next()`
  через `plugin._spawner`. При переименовании полей они упадут, а не молча позеленеют.
- Гоночный тест (`test_commit_racing_produce…`) проверяет итог и валидность кадров. Окно потери
  обновления из пункта 1 он поймал бы только вероятностно.
- Preview на каждый вызов заново грузит каталог классов (`ObjectFactory`). Цена на большом
  каталоге не измерена.
- `preset.commit` при недоступном движке возвращает `invalid` и файл не пишет. Сохранить пресет,
  пока лента не работает, нельзя. Так велел DESIGN; для редактора это может оказаться неудобно.
