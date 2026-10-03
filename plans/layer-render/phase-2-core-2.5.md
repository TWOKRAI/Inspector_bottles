# layer-render — Task 2.5 (вынесена из phase-2-core.md: файл фазы у бюджета 32 КБ)

Фаза: [phase-2-core.md](phase-2-core.md) · план: [plan.md](plan.md) · предыдущая: [phase-2-core-2.4b.md](phase-2-core-2.4b.md) ·
архитектура: [cto-verdict-2026-10-01.md](cto-verdict-2026-10-01.md) решения 3 и 7

### Task 2.5 — `render_scene(background, placed, effects, rng)`: одна функция кадра; `SceneCompositor` делегирует

- **Статус:** [PENDING] волна 6; ревью спеки ит.1 — CHANGES REQUESTED (M1, m1–m10 внесены, 2026-10-03) · **Level:** Middle (Sonnet 5.5) · **Assignee:** tester → developer (свежий) → инъекции лида → reviewer
- **Module contract:** public-api-change (`layer_render` получает модуль `scene`: `render_scene`, `SceneBackground`,
  `PlacedObject`; сигнатура `SceneCompositor` не меняется, поведение на валидных входах — тоже; невалидный
  `background_bgr` — `ValueError` в `__init__`, LR-003)
- **CHAIN:** `tester`(RED, worktree до кода) → `developer`(GREEN) → инъекции лида → `reviewer`
- **Dependencies:** 2.4b (DONE, `b8c0624cd`). После — 3.1 (эффекты сцены в `produce()` идут через `effects` этой функции),
  4.2 (`scene.preview` = кадр `render_scene`), 6.2 (`LayerSceneGenerator` рисует сцену этой функцией)
- **Gate:** RED тестера → GREEN; инъекции записаны; `reviewer` APPROVED по SHA. Путь кадра сима переподключается, поэтому
  нужен A/B на конфиге стенда (sha кадров и паспортов до = после) и, при свободном `stand.lock`, короткий процессный прогон
  с записью в замок; занят — пропуск записать в план с причиной.

**Goal:** кадр сцены собирает одна функция `layer_render.scene.render_scene`: фон → объекты → эффекты кадра. Сим (через
`SceneCompositor`), превью редактора (4.2) и генератор обучения (6.2) зовут её же — «что в редакторе, то в симе и в
обучении». Кадры сима не меняются ни на байт; ни один потребитель вне `Files` не правится.

#### Files

1. `Services/layer_render/scene.py` (новый) — `SceneBackground`, `PlacedObject`, `render_scene`.
2. `Services/layer_render/__init__.py` — экспорт трёх имён (явно, в `__all__`).
3. `Services/line_sim/core/scene_compositor.py` — `render()` делегирует `render_scene`; отсечение по bbox, паспорта,
   геометрия ленты, `belt_direction`/`entry_x_px` остаются здесь. Импорт `composite` из `dataset_gen` уходит.
4. `Services/layer_render/README.md` — раздел «Сцена (`render_scene`)»; «Порядок сцены» — ссылка на функцию.
5. `Services/layer_render/DECISIONS.md` — LR-003 (граница `render_scene` ↔ `SceneCompositor`, `rng=None`).
6. `Services/layer_render/STATUS.md`, `Services/line_sim/README.md` (раздел SceneCompositor: «делегирует»),
   `Services/line_sim/STATUS.md` — по строке.
- тесты: тестер — `Services/layer_render/tests/test_acceptance_2_5_render_scene.py`; автор — hazard-тесты
  `Services/layer_render/tests/test_hazards_2_5_scene.py`.

#### DESIGN

```python
@dataclass(frozen=True, eq=False)
class SceneBackground:
    layers: Sequence[SolidFill | ScrollingTile]  # снизу вверх; хранится tuple; пусто -> чёрный кадр
    size_wh: tuple[int, int]                     # (w, h): tuple|list из двух int|np.integer >= 0; bool, float — нет
    center_y: float                              # Y центра полосы тайла в координатах сцены
    scroll_px: int = 0                           # сдвиг тайлов по X (как render_background)
    origin_xy: tuple[int, int] = (0, 0)          # левый верхний угол окна в координатах сцены

@dataclass(frozen=True, eq=False)
class PlacedObject:
    rgba: np.ndarray                 # (h, w, 4) uint8; иначе ValueError с shape/dtype
    center_xy: tuple[float, float]   # центр в координатах КАДРА (дробный, как composite)

def render_scene(background: SceneBackground, placed: Sequence[PlacedObject],
                 effects: Sequence[EffectSpec], rng: np.random.Generator | None) -> np.ndarray:
```

- **Порядок (один для всех потребителей):** `frame = np.empty((h, w, 3), uint8)` → `render_background(frame, layers,
  scroll_px=…, origin_xy=…, center_y=…)` → для каждого `placed` по порядку `frame = composite(frame, rgba, center_xy)` →
  при непустом `effects` — `apply_effects(frame, effects, rng)`. Выход — RGB uint8 `(h, w, 3)`, новый массив.
- **Отсечения нет.** Объект вне кадра ничего не рисует (так ведёт себя `composite`), функция видимость не сообщает.
  Отсечение по bbox и список паспортов — дело `SceneCompositor` (решение CTO 7). Причина: паспорта — понятие ленты.
- **Проверки полей.** `SceneBackground`: `size_wh` (см. выше), элементы `layers` — `SolidFill`/`ScrollingTile`, иначе
  `ValueError` с индексом. `center_y`, `scroll_px`, `origin_xy` **не проверяются**: числа даёт вызывающий (целый `belt_y_px`
  допустим и не должен давать ошибку). `size_wh` хранится парой Python `int`.
- **Свёртка фона — у вызывающего.** `render_scene` рисует стек как дан; `render_background` даёт один и тот же кадр для
  свёрнутого и несвёрнутого стека (Task 1.1). `SceneCompositor` по-прежнему сворачивает один раз в `__init__`.
- **Контракт rng.** Пустой `effects` — ноль розыгрышей, `rng` может быть `None`. Порядок проверок до любого рисования:
  (1) элемент `placed` не `PlacedObject` — `ValueError` с индексом; (2) элемент `effects` не `EffectSpec` — `ValueError`
  с индексом; (3) непустой `effects` при `rng=None` — `ValueError`, в тексте `rng`. Свой поток эффектов
  `render_scene` не создаёт: генератор отдаёт вызывающий (в симе — `[seed, 1]`, Task 3.1).
- **`SceneCompositor` после задачи.** `__init__`: при `background_layers=None` стек = `[SolidFill(color_rgb=(r, g, b))]`
  из `background_bgr=(b, g, r)`; иначе — `fold_background(...)`, как сейчас. `render()`: `w, h = int(round(w_px)),
  int(round(h_px))`; `origin_xy = (int(round(x_px)), int(round(y_px)))`; `center_y = belt_y_px`;
  `scroll_px = belt_direction * int(round(float(encoder_to_offset_mm(now_encoder, 0.0) * px_per_mm)))` **только когда
  задан `background_layers`**, иначе `0` (без стека `now_encoder=NaN` не бросает — держать);
  объекты: `obj.render()` для каждого активного, `cx, cy` — прежние формулы, `_bbox_intersects` → `PlacedObject` и
  паспорт; затем `render_scene(SceneBackground(...), placed, (), None)`. Возврат `(frame, passports)` как раньше.
- **Сужение для невалидного `background_bgr`.** Прежде: `(300, 0, 0)` и `(-1, 0, 0)` — `OverflowError` в `render()`;
  `(60.5, 60, 60)` молча усекался до `60`; `(np.int64(60), 60, 60)` и `(60.0, 60.0, 60.0)` работали. Теперь все пять —
  `ValueError` в `__init__`. `SceneCompositor` перевыбрасывает ошибку `SolidFill` своим текстом:
  `ValueError("SceneCompositor.background_bgr: ожидались три целых 0..255 (B, G, R)") from exc` (у `SolidFill` в тексте
  чужое имя и каналы в обратном порядке). Причина сужения: правила цвета — в одном месте, `SolidFill`. Производитель
  один — `_BACKGROUND_BGR = (60, 60, 60)` (`plugin.py:138`), регрессии нет. Три `int` 0..255 дают тот же кадр. Записать
  в LR-003 и в README `line_sim`.
- `scene.py` импортирует только `background`, `compose`, `effects`, `interfaces` пакета и `numpy`.

#### Acceptance

##### Функция (A1–A6, тестер)

RED и GREEN на коде до задачи (M1 ревью спеки): **A7 и A9 п.1–2 зелёные до задачи** — тестер прогоняет их в своём
worktree и цитирует вывод. Импорт `Services.layer_render.scene` — только внутри тестов A1–A6 и A8, не в шапке файла:
иначе весь файл падает при сборе. Ожидаемый RED: A1–A6, A8, A9 п.3.

- [ ] **A1 имена и граница.** `from Services.layer_render import render_scene, SceneBackground, PlacedObject` и те же имена
  из `Services.layer_render.scene`. Чистый процесс `python -c "import Services.layer_render.scene"`: код возврата `0`,
  `Services.layer_render.scene` есть в `sys.modules`, и нет ни одного модуля `Services.line_sim*`, `Services.dataset_gen*`,
  `Services.ml_train*`.
- [ ] **A2 фон.** `SceneBackground([SolidFill((10, 20, 30))], (5, 4), center_y=2.0)`, без объектов и эффектов, `rng=None`
  → кадр формы `(4, 5, 3)`, `uint8`, все пиксели `[10, 20, 30]`. Пустой `layers` → все пиксели `0`. Тайл RGB со сдвигом
  `scroll_px` и `origin_xy` — столбцы кадра по формуле `cols = (arange(w) + origin_x - scroll_px) % tw`, литералами.
- [ ] **A3 объекты.** Порядок `placed` = порядок слоёв: два непрозрачных спрайта с перекрытием — в перекрытии пиксели
  второго. Полупрозрачный спрайт (альфа 128) на сплошном фоне — литерал по формуле `composite`
  (`floor(fg·a/255 + bg·(1 − a/255) + 0.5)`). Объект целиком за кадром — кадр равен кадру без него. Кадр равен цепочке
  `composite(...)` по тем же центрам.
- [ ] **A4 эффекты и rng.** Непустой `effects` с `rng=default_rng(7)` → кадр равен `apply_effects(кадр_без_эффектов,
  effects, default_rng(7))`, состояние `rng` после — как у копии после `apply_effects`. Эффект кадра применяется ПОСЛЕ
  объектов (пиксель объекта тоже изменён эффектом). Пустой `effects` с переданным `rng` → `rng.bit_generator.state` до ==
  после. `rng=None` + непустой `effects` → `ValueError`, в тексте `rng`; элемент `effects` не `EffectSpec` → `ValueError` с
  индексом; элемент `placed` не `PlacedObject` → `ValueError` с индексом. Порядок: `render_scene(bg, [], [object()], None)`
  → ошибка про элемент `effects`, не про `rng`.
- [ ] **A5 входы не меняются, выход свой.** Массивы `rgba` объектов и `image` тайлов побайтно те же после вызова; запись в
  выходной кадр не меняет их; два вызова дают разные массивы (`not np.shares_memory`). `rgba` с `flags.writeable=False` принимается без исключения.
- [ ] **A6 валидация.** `SceneBackground`: `size_wh` с `bool`, `float`, отрицательным числом, длиной не 2 или не
  `tuple`/`list` → `ValueError`; `[5, 4]` и `(np.int64(5), 4)` принимаются, `size_wh` после — `(5, 4)` из Python `int`;
  целый `center_y=2` принимается;
  элемент `layers` не `SolidFill`/`ScrollingTile` → `ValueError`. `PlacedObject`: `rgba` не `(h, w, 4)` или не `uint8` →
  `ValueError`, в тексте shape или dtype. Нулевой размер `(0, 4)` → кадр формы `(4, 0, 3)` без исключения.

##### Сим и проверки лида (A7–A11)

- [ ] **A7 сим побайтно прежний (тестер).** Литералы sha256 сняты с кода ДО задачи (worktree тестера): кадры
  `SceneCompositor.render` на сценарии с `[SolidFill, RGBA-тайл]`, `belt_direction=-1`, `entry_x_px≠0`, ненулевым
  `lateral_px`, ≥3 объектами с перекрытием и частично за краем, ≥10 шагов энкодера; и тот же сценарий со сплошной
  заливкой `background_bgr` без стека, цвет **не серый** — `(200, 10, 30)`. Паспорта — тот же список в том же порядке
  (литерал JSON/sha). Спрайты — синтетические numpy RGBA через `LayeredObject.from_rendered` и заглушку спавнера, без
  cv2 и файлов; окружение снимка (numpy, ОС, SHA) — комментарием у литералов.
- [ ] **A8 делегирование (тестер).** На том же сценарии кадр `SceneCompositor.render` == `render_scene` с фоном и
  объектами, собранными по формулам DESIGN: `cx = entry_x_px + dir·offset_mm·px_per_mm − x_px`,
  `cy = belt_y_px + lateral_px − y_px`, отсечение строгими неравенствами; фон — `scroll_px`, `origin_xy`, `center_y` и стек
  по пункту «`SceneCompositor` после задачи».
- [ ] **A9 старые контракты (тестер).** Без `background_layers` `render(float("nan"), rect)` не бросает; со стеком —
  бросает. Невалидный `background_bgr=(300, 0, 0)` → `ValueError` в `SceneCompositor(...)`, в тексте `background_bgr`.
- [ ] **A10 радиус (лид).** Без правки зелёные: `Services/layer_render`, `Services/line_sim`, `Plugins/sim`,
  `apps/line_sim`, `Services/dataset_gen`, `Services/ml_train`; золотые `test_acceptance_lateral_offset_plugin.py:492-493`.
  `grep -n "dataset_gen" Services/line_sim/core/scene_compositor.py` → 0. `sentrux check .` и `python scripts/validate.py`
  — чисто.
- [ ] **A11 стенд и цена (лид).** A/B на конфиге стенда по процедуре `docs/reviews/2026-10-03_task-2.4b-lead-injections.md:76`
  (скрипт в scratchpad лида, вне git; данные — `data/line_sim` worktree; 80 кадров, p=0.25): sha кадров
  `28f51303…` и паспортов `54b548c0…` = до задачи. Медиана `SceneCompositor.render` 1440×1080, 200 вызовов × 3 повтора,
  до и после — числа с разбросом в отчёте. Рост медианы больше разброса повторов — находка, не правка по ходу.

#### Out of scope

- Эффекты сцены в симе (`scene_effects`, поток `[seed, 1]`, `produce()`) — Task 3.1.
- `scene.preview` в `layers` — Task 4.2; `LayerSceneGenerator` — Task 6.2; вырез `crop` — Ф6.
- Ветка `_background_only_frame` плагина `scene_source` (движок не собран) — не трогать.
- Ускорение `composite` (копия кадра на каждый объект) — замер в A11, правка отдельной задачей.
- `SceneCompositorProtocol`, сигнатура `SceneCompositor`, `scene_source/plugin.py` — без изменений.

#### TRAPS

- **NaN-энкодер.** Сдвиг тайла считать только со стеком. Если считать всегда, `int(round(nan))` бросит на пути без
  стека — A9 и `SceneCompositor` docstring «без стека — не дают».
- **BGR → RGB.** `background_bgr` — BGR, `SolidFill` — RGB. Перепутанный порядок даёт зелёный тест на сером `(60, 60, 60)`
  и красный только на цветном. Проверять цветным.
- **Отсечение не переносить в `render_scene`.** Иначе редактор (4.2) потеряет объекты, частично вышедшие за кадр по
  иной логике, а паспорта разойдутся с кадром.
- **Не создавать `rng` внутри `render_scene`.** Свой `default_rng(...)` «на всякий случай» ломает контракт LR-001: поток
  эффектов принадлежит вызывающему.
- **`obj.render()` зовётся для всех активных**, и невидимых тоже: размер спрайта нужен для отсечения. `render()` отдаёт
  готовый массив из конструктора `LayeredObject` (`layered_object.py:52-53, 70-76`), он **read-only**. `PlacedObject` и
  `render_scene` обязаны принимать read-only `rgba` без копии и не писать в него (A5).
- **Лишняя копия.** `apply_effects` при пустом списке возвращает копию; на пустом `effects` не звать её вовсе — цена кадра.
