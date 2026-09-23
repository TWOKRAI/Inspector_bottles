# Plugins/sim/scene_source — источник кадров сцены сима

Task 2.2 плана [`plans/line-sim/phase-2-belt-truth.md`](../../../plans/line-sim/phase-2-belt-truth.md),
подключение реального движка — Task 3.4 плана [`plans/line-sim/phase-3-object-engine.md`](../../../plans/line-sim/phase-3-object-engine.md).

## Назначение

Source-плагин (форма — [`Plugins/sources/synthetic_frame_source`](../../sources/synthetic_frame_source/README.md)):
фон + объекты движка [`Services.line_sim`](../../../Services/line_sim/README.md)
(`ObjectSpawner` + `SceneCompositor`), положение которых следует за энкодером
ленты из общего мира (`sim.belt.*`, публикует
[`Plugins/sim/robot_host`](../robot_host/README.md)). **Заглушка-спрайт Task 2.2
(`_draw_sprite`, `SPRITE_BGR`, бесконечная лента по модулю) удалена Task 3.4** —
камера теперь конечная (`camera_rect` фиксирован конфигом ширины/высоты кадра),
объект, уехавший за край, просто не рисуется, деспавн — по `scene_length_mm`
(Task 3.3), а не по модулю периода кадра.

## Чтение мира — подпиской, не `get()`

`StateProxy.get()` без предварительной подписки на путь **всегда** уходит в
синхронный IPC-раундтрип (до 5 с), а `produce()` зовётся на каждый кадр —
недопустимо. Поэтому `start()` подписывается на `sim.belt.**`
(`sync=False` — подписка регистрируется до появления приёмного потока
процесса, синхронный раундтрип ждать некому, тот же приём, что у
`TelemetrySinkPlugin`), колбэк только кладёт последнее значение в поле под
`Lock` — ни одного IPC на кадр.

Без `ctx.state_proxy` (Task 2.0 не влита) — плагин живёт, спрайт остаётся в
`spawn_encoder`.

## Конфиг (`pipeline.yaml`)

| Ключ | Дефолт | Смысл |
|---|---|---|
| `resolution_width` / `resolution_height` | `640` / `480` | размер кадра |
| `spawn_encoder` | `0` | значение энкодера, предполагаемое ДО первой дельты из мира |
| `px_per_mm` | `1.0` | масштаб мм → px |
| `belt_y_px` | `resolution_height / 2` | вертикальная линия ленты в кадре |
| `spawn_interval_s` | `[2.0, 4.0]`, если не задан ни один из двух | диапазон интервала спавна по времени (`ObjectSpawner(interval_s=...)`, Task 3.3) |
| `spawn_spacing_mm` | нет | диапазон шага спавна по пути ленты, мм (`ObjectSpawner(spacing_mm=...)`, Task 3.3a) |
| `scene_length_mm` | `(resolution_width / px_per_mm) * 2` | длина видимой зоны — за ней объект деспавнится |
| `defect_probability` | `0.0` | вероятность дефект-слоя `"damaged"` (Task 3.2) |
| `preset_path` | нет (движок недоступен) | путь к каталогу классов (`Services.dataset_gen.core.catalog.SpriteCatalog`) |
| `stale_ms` | `500` | порог протухания значения мира (мс) |
| `seed` | `0` | seed `np.random.default_rng` движка (класс/угол/дефект объектов) |
| `camera_id` | `0` | попадает в `item["camera_id"]` (форма как у боевых источников) |
| `background_texture` | нет (сплошной фон) | путь к картинке фона (Task 3.6): относительный — от корня репозитория, как `preset_path`. Тайл прокручивается с энкодером (`Services/line_sim/README.md` → «Фон-текстура»). Нечитаемый файл — один `log_error` в `configure()`, движок работает на сплошном фоне. Тайл из фото — `python -m Services.line_sim.tools.make_seamless_texture` |

**Ровно один из `spawn_interval_s`/`spawn_spacing_mm`** (Task 3.3a): оба заданы в конфиге
стенда — `ValueError` в `configure()`, НЕ проглатываемый общим `try/except` вокруг сборки
движка (это ошибка конфигурации, а не сбой сборки, который допустимо проглотить и упасть
на фон). Если не задан ни один — плагин МОЛЧА берёт таймерный режим `spawn_interval_s=
[2.0, 4.0]` — тот самый режим, из-за которого объекты копились в одной точке на стоящей
ленте (репродукция на живом стенде 2026-09-23, план Task 3.3a); это существующее
поведение по умолчанию, не изменённое этой задачей, — здесь честно названо, а не спрятано.

**`preset_path` относительный — резолвится от КОРНЯ РЕПОЗИТОРИЯ, не от CWD процесса**
(фикс ревью Task 3.4, P5): `Path(__file__).resolve().parents[3]` от `plugin.py`. Раньше
`ScenePreset(catalog_dir=preset_path)` строился напрямую (резолюцию относительных путей
умеет только `ScenePreset.from_yaml`, не голый конструктор), поэтому один и тот же
`pipeline.yaml` давал движок то готовым, то fallback-на-фон — в зависимости от того,
из какого каталога запущен процесс. `data/` — gitignored: на свежем клоне репозитория
демо-каталог нужно сгенерировать явно (`python -m Services.line_sim.tools.make_demo_catalog
--out data/line_sim/demo_catalog`), иначе `preset_path` не существует и движок падает в
fallback (см. ниже).

## Робот забрал — объект исчезает (Task 3.5)

Конфиг:

| Ключ | Дефолт | Смысл |
|---|---|---|
| `geometry` | `{origin_x_mm: 0.0, origin_y_mm: 0.0}` | точка сцены «путь 0, центр полосы» в координатах робота (`BeltGeometry`) |
| `match_radius_mm` | `5.0` | невязка задания и объекта строго меньше — совпадение |
| `dup_window_s` | `10.0` | сколько снятый объект остаётся кандидатом для исхода `dup` (часы сцены, момент снятия) |

Команды:

- `scene.job_done` — аргументы `JobDone.to_dict()` (`index, x_mm, y_mm, ecap, t`); только
  ставит задание в очередь, ответ ровно `{"status": "ok"}`; кривые аргументы →
  `{"status": "error", "message": ...}`, без исключения.
- `scene.status` → `{"status": "ok", "active": int, "recent": [...]}`; `recent` —
  последние ≤ 32 исхода `{index, outcome, object_id, residual_mm}`, старые первыми;
  `active` = 0, если движок не собран.

Потоки: команда идёт в потоке команд и только кладёт задание в `collections.deque`;
спавнер меняет только `produce()`. В начале каждого кадра, ДО `spawner.tick()` и
независимо от того, пришёл ли мир, очередь разбирается целиком: чистка снятых старше
`dup_window_s` → `match_job(...)` (положение объекта считается от `ecap` ЗАДАНИЯ, не от
энкодера мира сцены) → при `matched` `spawner.remove(id)` → исход в `recent` + одна
строка `log_info`. `sim.objects` переопубликует тот же `_sync_world_objects()`.
Движок не собран → каждое задание получает `no_object`.

**Известный предел:** объект, уехавший за `scene_length_mm` раньше события «выполнено»,
даёт `no_object` — его нет ни среди активных, ни среди снятых. `scene_length_mm` стенда
обязан покрывать зону робота.

## Рендер (Task 3.4 — движок `Services.line_sim`)

`configure()` собирает `ScenePreset(catalog_dir=preset_path, defect_probability=...)` →
`ObjectFactory` → `ObjectSpawner(scene_length_mm=..., **spawner_kwargs)` (`spawner_kwargs` —
`interval_s=...` ИЛИ `spacing_mm=...`, Task 3.3a) → `SceneCompositor(spawner, px_per_mm,
belt_y_px)`. `produce()`: `spawner.tick(now_encoder=<из мира>, now_wall_s=time.monotonic(),
rng=self._rng)`, НО ТОЛЬКО когда `_world_ready` (пришла хотя бы одна дельта — review Task
3.3a, находка 4: без этого гейта первые кадры тикали бы на конфигурационном
`spawn_encoder` вместо реального, порождая призрачный объект на `spawn_encoder=0`);
исключение фабрики ловится, лог де-дублирован — не чаще раза в секунду, кадр отдаётся с
прежней сценой → `compositor.render(...)` → `cv2.cvtColor(RGB2BGR)` → `item["frame"]`.
`rng = np.random.default_rng(seed)` живёт в плагине — единственный producer, у него часы и
rng (`SceneCompositor.render()` их не трогает, LS-009).

**Fallback на фон, если движок собрать не удалось** (`preset_path` не задан, каталог не
существует, пресет невалиден) — `configure()` ловит исключение сборки, логирует ОДИН раз
через `ctx.log_error` и оставляет `self._compositor = None`; `produce()` в этом случае
отдаёт кадр одного фона без исключений — до конца жизни процесса, без движка.

**`sim.objects` в общем мире** — паспорта активных объектов, публикуются ТОЛЬКО при смене
МНОЖЕСТВА активных `object_id` (спавн/деспавн), не на каждый кадр:
`ctx.state_proxy.set("sim.objects", {object_id: passport.to_dict(), ...})`. Позиция объекта
в мир не пишется — вычисляется потребителем из `sim.belt.encoder` и `passport.spawn_encoder`
(`Services.line_sim.core.belt.encoder_to_offset_mm`).

**Заменяет заглушку Task 2.2** (квадрат `32×32`, константа `SPRITE_BGR`, бесконечная лента
по модулю `((x_px + 16) % (width + 32)) - 32`) — снята целиком вместе с `_draw_sprite`.
Камера теперь конечная: объект, уехавший за `camera_rect` (фиксирован размером кадра),
просто не рисуется; деспавн — по `scene_length_mm` (Task 3.3), не по периоду кадра.
`test_scene_source_hazards.py::test_sprite_wraps_past_right_edge_instead_of_parking`
(пинил именно бесконечную ленту заглушки) снят вместе с поведением — тест автора, не
независимого тестера, см. блок правки в файле.

## Протухшее значение

Позиция ВСЕГДА берётся из последней доставленной дельты — отдельного пути
«двигать спрайт по времени» нет, поэтому «заморозка» между кадрами на
неизменном мире — не код, а следствие отсутствия новой дельты.
Единственный наблюдаемый эффект протухания — `ctx.log_warning`,
де-дублированный по значению `t` (не спамит на каждый кадр одним и тем же
протухшим значением).

## Правда на проводе (Task 5.2 + 5.1b)

`TruthLedger` (`Services.line_sim.core.truth`) считает исходы сам, без участия прототипа —
своим локом `_truth_lock` (НЕ `_lock` мира): `on_spawn`/`on_despawn` кормятся из diff
множества `active_objects()` до/после `spawner.tick()` в `produce()` (после `_drain_jobs` —
поэтому объект, снятый заданием в этом же кадре, засчитывается как `caught`, не `missed`);
`on_match` кормится из каждого исхода `_drain_jobs` вместе с самим `job` (Task 5.1b, §3 —
в ОБЕИХ ветках, включая «движок не собран», `MatchResult("no_object", ...)` — растёт
`false_alarm`, а если рядом с этой же точкой недавно было задание с ДРУГИМ `ecap` — ещё и
`false_alarm_frozen_xy`, причина «те же X/Y с новым энкодером», переехавшая сюда из
`SimJournal` — на проводе робота она ложно срабатывала на разных дисках у триггера).

Команды: `truth.status` -> `{"status": "ok", "counters": {...}}` (полный набор ключей —
докстринг `Services/line_sim/core/truth.py` и контракты `plans/line-sim/phase-5-contract-5.2.md` §1,
`plans/line-sim/phase-5-contract-5.1b.md` §2); `truth.reset` -> `{"status": "ok"}`, счётчики
в ноль (включая `false_alarm_frozen_xy`), объекты под учётом остаются, память недавних
заданий (frozen-xy) очищается.

Шесть уровней (`truth_caught`, `truth_dup_jobs`, `truth_missed`, `truth_false_alarm`,
`truth_false_alarm_frozen_xy`, `truth_on_belt`, ADR-PM-038) публикуются из `produce()` не
чаще раза в `truth_publish_s` (конфиг, дефолт `1.0` с) — первый `produce()` публикует
всегда. В дерево мира (`sim.*`) счётчики НЕ пишутся — это порт наблюдений, не состояние
для других устройств.

## Границы

`Plugins/sim/scene_source` не импортирует `Plugins.sim.robot_host` ни
`multiprocess_prototype` (принцип 5 видения line-sim: модели не знают друг
друга) — проверено `tests/test_scene_source_acceptance.py::test_no_forbidden_imports`.

## Out of scope

Фотометрия (Ф4.3), fps/размер/цвет кадра (Ф4.1), ROI (Ф4.2) — `camera_rect` сейчас
фиксированный конфиг размера кадра; переполнение
32-бит энкодера — см. [`apps/line_sim/README.md`](../../../apps/line_sim/README.md).
