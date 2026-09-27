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

## Итерация 2 (ревью it.1 → it.2)

Коммиты: `957ee7ec` fix(recipe) — атомарный `update_yaml_preserving`; `88fe338a` fix(scene_source) — S1–S4, N3, пресет.
Тесты: `Services/line_sim/tests Plugins/sim/scene_source multiprocess_framework/modules/recipe/tests` → 483 passed, 1 skipped; ruff чисто.
RED до правки: 6 hazard-тестов плагина (unchanged, comments, outside-root, no-engine, budget, read-only) и 2 теста yaml_io (сбой fsync/replace, сбой сериализации).
`keeps_file_mode` на HEAD зелёный по построению (`open("w")` права не менял) — сторож нового пути; инъекция «убрать chmod» → 2 красных.

- **R.** `compute_rev` и `update_yaml_preserving` из модуля `recipe`; свои `_write_preset_atomic` и sha256 удалены.
  В `yaml_io`: ruamel пишет в буфер, дальше `service._atomic_write` (tmp `.<имя>.XXXX.tmp`, fsync, replace). После replace — `chmod` к прежнему mode.
  Цикла импорта нет: `service.py` ничего не импортирует из пакета.
- **S4.** Сравниваю нормализованные `to_dict()` (файл → `ScenePreset` → dict), а не сырой dict файла: иначе get→commit без правок писал бы `layers` из-за развёрнутых дефолтов.
- **S3.** Корни: `_REPO_ROOT` и каталог файла пресета. Одно сообщение для любого пути вне корней; петля симлинков даёт тот же отказ.
- **S2.** Без движка commit валидирует через `ObjectFactory`, пишет файл, отвечает `applied: false` и сообщение; фабрику в слот не кладёт.
- **S1 — цель не достигнута.** Реальный пресет (Arial, 300 px, объект 378×378 RGBA): превью по умолчанию 8×160 — первый вызов 95.2 мс, тёплый кэш медиана 87.0 мс (min 85.9, max 89.1).
  Разбивка тёплого: `make` 71.7 мс (`compose.composite` + `astype` на полном размере спрайта), `_fit_tile` 12.5, PNG 1.0, `from_yaml` 1.3.
  Кэш снимает только ~8 мс `ObjectFactory()`. 16×160 и 16×256 → `bad_request` (0.01 мс). 16×113 проходит бюджет и стоит 165.5 мс.
  Бюджет по пикселям тайла не ограничивает цену: она определяется числом сидов × размером спрайта. ESCALATION → lead.

### Что истолковал, а не выполнил буквально
- «file's parsed dict» — сравниваю нормализованный пресет файла; при неразборном файле пишутся все ключи.
- Ответ commit с изменениями: `{"status","rev","changed": true,"applied"}` (+`message` без движка) — `changed` добавлен к форме S2.
- `update_blueprint_metadata_preserving` тоже переведён на атомарную запись (тот же файл, тот же дефект).
- Mode — `chmod` после `os.replace`: `service.py` править нельзя, поэтому `copymode` на tmp недоступен. Новый файл: `touch` (mode по umask), при сбое удаляется.

### Что оставил открытым / ненадёжным
- S1: 87 мс на потоке команд на каждый вызов превью.
- Окно 0600 между `os.replace` и `chmod`. Решение — `copymode` внутри `_atomic_write`; у `recipe.service` та же потеря прав, это follow-up.
- Пресет вне репозитория с картинками вне своего каталога (раскладка скретча ревьюера) через редактор не правится вовсе: `catalog_dir` не проходит ограду.
- Кэш превью не версирует картинки на диске (N5). Симлинк-пресет по-прежнему заменяется обычным файлом.
- ruamel переформатирует изменённый ключ (блочные списки у `color_rgb`) и отступы соседей в файле с другой раскладкой; значения при этом верны.
- N1, N4, N6 не трогал — вне брифа. README и STATUS `scene_source` пишет лид (D2: реальные числа выше).

## Итерация 2b — превью в своём процессе `layers` (ответ лида на эскалацию S1)

Коммиты: `38125a68` feat(line_sim) — `core/preview.py` (сетка, бюджет, кэш, `confine_preset_paths`); `0570070b` feat(layer_preview) — плагин, удаление превью из `scene_source`, процесс `layers` в `apps/line_sim/pipeline.yaml`, перенос тестов.
Тесты: `Services/line_sim/tests Plugins/sim multiprocess_framework/modules/recipe/tests` → 626 passed, 1 skipped; `apps/line_sim` → 26 passed, 6 skipped (live); ruff чисто.
RED: 9 тестов `test_layer_preview.py` падали `ModuleNotFoundError` до появления плагина. P6/P7 тестера перенесены с сохранением каждого утверждения; P6 теперь проверяет, что кадры двух `SceneSourcePlugin` остаются побитово равными после трёх превью на `LayerPreviewPlugin` с тем же файлом.

Замер `job_done` (скрипт `scratchpad/r12a/m12_jobdone.py`, реальный пресет Arial): `scene.cmd_job_done` вызывается на «потоке сцены», а `LayerPreviewPlugin` в соседнем потоке без паузы гонит превью 8×160 (34 штуки, медиана 88.3 мс).
Задержка `job_done`: медиана 0.004 мс, p99 0.035, максимум 0.075 (n=493). Раньше, когда оба вызова шли на одном потоке, `job_done` ждал 87.1 мс.
Замер in-process: два потока делят GIL, поэтому это верхняя оценка. В бою это разные процессы без общего GIL.

### Что истолковал
- Стенд держит `preset_path: data/line_sim/letter_catalog` — это каталог, а не `.yaml`. Поэтому `layer_preview` поддерживает каталожный режим: пресет строится один раз через `SceneSourcePlugin._build_preset`, клиентские пути пускаются только внутрь корня репозитория. В `layers` скопирован и `defect_probability: 0.25`, чтобы превью показывало то же, что едет на ленте.
- Пределы запроса проверяются до разбора пресета: при кривых `seeds` и кривом `preset` ответ `bad_request`, как было.
- Кэш фабрики — модульный, одна запись на процесс.

### Что оставил открытым / ненадёжным
- `apps/line_sim/tests/test_f2_task22_live.py:363` отфильтровывает `robot`/`pult` и ожидает `{camera, mjpeg}`. С `layers` тест упадёт при `--backend-live` (сейчас он skipped). Файл вне брифа, нужно добавить `layers` в фильтр.
- Живой стенд с процессом `layers` не поднимал: маршрутизация `preset.preview` в процесс `layers` проверена только по конфигу.
- `layer_preview` импортирует `Plugins.sim.scene_source.plugin` ради статик-методов, из-за этого в процессе `layers` регистрируется и `scene_source`.
- Цена одного превью не изменилась (~88 мс). Она ушла с потока сцены, но поток команд `layers` занят столько же.

## Итерация 2c — правила конфига в Services, живой прогон

Коммит `f638e281`. В `Services/line_sim/core/preset.py` вынесены `REPO_ROOT`, `resolve_repo_path`, `load_scene_preset` и `apply_defect_override`. Теперь `layer_preview` импортирует только `Services.line_sim.core`. Тест в подпроцессе проверяет, что после импорта плагина в `sys.modules` нет `Plugins.sim.scene_source`; на HEAD он был красным (`['Plugins.sim.scene_source', 'Plugins.sim.scene_source.plugin']`). У `scene_source` `_resolve_preset_path` остался тонким делегатом, потому что его зовут тесты.
Радиус `Services/line_sim/tests Plugins/sim multiprocess_framework/modules/recipe/tests apps/line_sim`: 658 passed, 7 skipped.
Живой прогон: флага `--backend-live` в этом pytest нет, живые тесты включаются переменной `LINE_SIM_LIVE=1`.
- Первый прогон: 1 failed, 31 passed. Упал `test_mjpeg_sprite_follows_belt` (лаг корреляции -1439.0): в worktree нет `data/line_sim/letter_catalog` (gitignored), и движок сцены работает только фоном.
- Второй прогон с временной ссылкой `data/line_sim` на каталог главного дерева: 32 passed за 61 с, стенд из 5 процессов вместе с `layers`. Ссылку удалил сразу после прогона.
Открыто: `preset.preview` через живой стенд в процесс `layers` не вызывал, маршрут проверен только тем, что процесс поднимается.
