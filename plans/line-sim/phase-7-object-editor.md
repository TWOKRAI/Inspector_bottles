# Phase 7 — Редактор объекта: слои мышью и числами, HTML + Qt

> **Сверка по ветке `feat/line-sim` (2026-09-22): у этой фазы есть конкурент, написанный днём раньше** —
> [`plans/line-sim-layer-editor.md`](../line-sim-layer-editor.md) (только на ветке; DRAFT 2026-09-21,
> «редактор как в paint»): автономное PySide6-окно `Services/line_sim/tools/layer_editor`, своя канва,
> не ждёт Пульта. Общее у обоих: одна модель `LayerSpec`/`ObjectTemplate` (там — Task **3.1a**,
> `phase-3a-layer-contract.md` на ветке: трансформ, диапазоны аугментации, выборка один раз на объект,
> round-trip пресета — то есть часть «Дополнено 2026-09-22» в `phase-3` здесь **уже расписана**), один
> рендер, UI ничего не компонует. Рекомендация — **свести в эту фазу и снять автономное окно**: 7.1 + 7.2
> (HTML) дают редактор без Qt и без Пульта раньше окна (HTTP-сервер в процессе уже есть — образцы
> `pult_web`/`mjpeg_sink` на ветке), 7.3 — после gui-service 3.2. Зависимости ниже читать так:
> «Ф3.1» = 3.1 + 3.1a ветки; «Ф1.2 процесс `scene`» = процесс `camera` с `scene_source` (уже есть);
> «тот же stdlib-сервер, что frame_stream» = сервер `pult_web`/`mjpeg_sink`. `QUEUE.md` решение №14.

Часть плана [`plan.md`](plan.md). **Добавлена 2026-09-22** по решению владельца: «закинуть PNG с
полупрозрачным фоном, накладывать слои друг на друга, перемещать, масштабировать, поворачивать на
угол — мышью, как в обычных редакторах, и значениями; аугментация к слоям и к группе; интерфейс
дублируется в HTML и в Qt». Объекты потом едут по конвейеру — движок Ф3.

## Принцип: одна модель, один рендер, два тонких клиента

```
   Qt-вкладка в Пульте оператора            HTML-страница (браузер)
   QGraphicsView + спин-боксы               Fabric.js + <input type=number>
           │ команды по SocketChannel                │ HTTP JSON (тот же stdlib-сервер,
           ▼                                         ▼  что frame_stream / phone_gateway)
   ┌──────────── процесс scene дерева симулятора ────────────────┐
   │ ObjectTemplate = [LayerSpec…]  ↔ YAML (ruamel, с комментариями) │ ← единственная модель (Ф3.1)
   │ LayeredObject.render() → PNG-превью                          │ ← единственный рендер (Ф3.1)
   │ ObjectSpawner берёт шаблон при СЛЕДУЮЩЕМ спавне (Ф3.3 Step 5) │
   └───────────────────────────────────────────────────────────────┘
```

**UI ничего не компонует и не хранит.** Жест мышью → числа (`offset_xy_mm`, `scale`,
`angle_offset_deg`) → те же поля `LayerSpec`, что и в спин-боксах → движок рендерит превью и отдаёт
PNG. Во время жеста клиент двигает PNG слоя своим нативным трансформом (CSS `transform` /
`QGraphicsItem.setTransform`) — плавно; на отпускание (и ~20 Гц в процессе) числа уходят в движок,
приходит честное превью. Что видишь — то поедет по ленте. Дублирование интерфейса стоит дёшево ровно
потому, что в клиентах нет логики.

**Конвенция координат** зафиксирована в Ф3.1 (угол CCW как `compose.py`, центр слоя, мм); Qt (CW,
Y вниз) и Fabric.js (CW) конвертируют у себя на границе — контракт-тест Ф3.1 держит движок, тесты 7.2/7.3
держат конверсию клиентов.

**Что берём готовым:** модель и рендер — Ф3.1; HTTP-сервер в процессе без новых зависимостей —
`Services/phone_gateway` / `Services/frame_stream` (stdlib `ThreadingHTTPServer`); `ruamel.yaml` —
уже в зависимостях; `QGraphicsView` — уже используется в `tabs/pipeline/graph/graph_view.py`
(перемещение элементов нативное, `ItemIsMovable`); гизмо с ручками в HTML — Fabric.js одним `<script>`
(выделение, угловые ручки масштаба, ручка поворота из коробки — вручную ~200 строк JS, не стоит).

**Не строить впрок (v1):** undo/redo, мультивыделение, привязки/сетка, панель слоёв с миниатюрами,
кривые/маски. Добавлять, когда базовое гизмо и YAML-редактирование реально упрутся.

---

### Task 7.1 — Модель редактора + команды процесса `scene`

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** чистый Python без UI: `TemplateEditor` над `ObjectTemplate` (Ф3.1) — операции
`add_layer(png_bytes|path)`, `remove_layer`, `reorder`, `set_layer(field, value)`,
`set_layer_range(field, lo, hi)`, `set_object(field, value)`, `preview(seed) -> PNG bytes`,
`save()`/`load()` (YAML round-trip); те же операции — команды процесса `scene` (через
`CommandManager`), чтобы оба клиента (7.2 HTTP, 7.3 Qt по сокету) звали **одно и то же**.

**Files:**
- `Services/line_sim/core/template_editor.py` — `TemplateEditor`
- `Plugins/sources/line_sim_scene/plugin.py` — команды `template.*` (тонкая обвязка: dict → метод → dict)
- `Services/line_sim/tests/test_template_editor.py`, `Plugins/sources/line_sim_scene/tests/test_template_commands.py`

**Steps:**
1. Операции — чистые функции над копией шаблона; валидация значений через Pydantic-модель `LayerSpec`
   (диапазон `scale > 0`, `lo ≤ hi`, RGB без альфы — ошибка при `add_layer`).
2. `preview(seed)` — `LayeredObject.render(rng(seed))` → PNG (`cv2.imencode`), один и тот же код, что
   рендер на ленте (импорт, не копия). Размер превью — `size_mm × px_per_mm` шаблона.
3. `save()` — атомарная запись (tmp + `os.replace`), комментарии YAML сохранены; `load()` — понятная
   ошибка валидации на битом файле, не `AttributeError`.
4. Команды `template.get/set_layer/add_layer/remove_layer/reorder/preview/save/reload` в `scene` —
   `Dict at Boundary`; `add_layer` принимает base64 PNG (граница ≤ N МБ — валидировать).
5. Автор пишет hazard-тест: `save()` во время `produce()` (другой поток) — спавнер видит либо старый,
   либо новый шаблон целиком, не половину (шаблон подменяется атомарно по ссылке).

**Acceptance criteria:**
- [ ] `add_layer` с PNG без альфа-канала → `ValueError` с текстом, называющим «alpha»; с RGBA — слой добавлен,
      `len(layers) + 1`.
- [ ] `set_layer(i, "angle_offset_deg", 90)` → `preview()` отличается от `preview()` до правки (пиксельная
      разность > 0); `set_layer(i, "scale", 0)` → ошибка валидации, шаблон не изменён.
- [ ] `preview(seed=1)` дважды — побитово одинаков; `preview(seed=1)` и `preview(seed=2)` при слое
      `mode="augmented"` с ненулевым диапазоном — различаются.
- [ ] `save()` → `load()` → равный объект; комментарий из фикстуры YAML сохранён.
- [ ] Команда `template.set_layer` через `CommandManager` процесса `scene` (тест с стабом контекста)
      меняет шаблон, который читает `ObjectSpawner` при следующем спавне (объект, заспавненный после,
      рендерится иначе; заспавненный до — нет).

**Out of scope:** UI; аутентификация (gui-service 2.2); несколько шаблонов/пресетов одновременно
(v1 — один активный шаблон на сцену).
**Edge cases:** удаление последнего слоя — ошибка («объект без слоёв»), не пустой шаблон; `reorder`
с индексом вне диапазона — ошибка с индексом.
**Dependencies:** Ф3.1 (модель), Ф3.3 (спавнер читает шаблон), Ф1.2 (процесс `scene`).
**Module contract:** impl-only (`Services/line_sim` уже new-full).

---

### Task 7.2 — HTML-редактор: страница с гизмо (Fabric.js) поверх команд 7.1

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** страница, отдаваемая тем же stdlib-сервером в процессе `scene` (образец `phone_gateway.web`):
канва с слоями (Fabric.js — перемещение, угловые ручки масштаба, ручка поворота), панель числовых полей
(те же поля), загрузка PNG, кнопки «прокрутить» (новый seed превью) и «сохранить». Каждый жест →
JSON-команда `template.*` → превью от движка.

**Files:**
- `Plugins/sources/line_sim_scene/web/editor.html`, `editor.js` (vanilla + Fabric.js с CDN либо
  вендоренный один файл — решить и записать в DECISIONS: офлайн-цех против размера репо)
- `Plugins/sources/line_sim_scene/plugin.py` — HTTP-маршруты `/editor`, `/api/template/*` → команды 7.1
  (тот же `ThreadingHTTPServer`, что поток кадров)
- `Plugins/sources/line_sim_scene/tests/test_editor_api.py` (HTTP-тесты без браузера)

**Steps:**
1. `/api/template` GET → шаблон JSON; POST `/api/template/layer/<i>` → `set_layer`; `/api/template/
   preview?seed=` → PNG; `/api/template/layer` POST multipart → `add_layer`; `/api/template/save`.
2. Fabric.js: слой = `fabric.Image` из PNG слоя; выделение даёт гизмо; `object:modified` → числа
   (конверсия CW→CCW, px→мм через `px_per_mm` со страницы) → POST → превью в отдельном `<img>` рядом
   («как поедет»). Во время `object:moving/scaling/rotating` — троттлинг POST до 20 Гц.
3. Числовые поля `<input type="number">` привязаны к тем же полям: правка поля → POST → Fabric обновляет
   трансформ (одно направление истины — сервер).
4. Автор пишет hazard-тест (HTTP): два клиента правят один слой — последний выигрывает, шаблон валиден;
   POST с NaN/строкой в числовом поле → 400 с именем поля.

**Acceptance criteria:**
- [ ] `GET /editor` → `200`, HTML содержит `<canvas>`; `GET /api/template` → JSON с `layers`,
      каждый — с `offset_xy_mm/scale/angle_offset_deg`.
- [ ] `POST /api/template/layer/0 {"angle_offset_deg": 45}` → `200`; следующий `GET /api/template/preview`
      отличается от предыдущего (разность байт PNG > 0); `{"scale": -1}` → `400` с текстом про `scale`.
- [ ] **Конверсия углов клиента — тестом на чистой функции JS** (вынесена в `editor.js` как
      `toEngineAngle(fabricAngle)`): для `+30°` в Fabric ожидаемый угол движка — литерал в тесте
      (`node`-тест или `pytest` через `subprocess node`; если `node` в окружении нет — тест Python-зеркала
      той же формулы с пометкой, что JS покрыт только ручной проверкой).
- [ ] Загрузка RGBA-PNG через `/api/template/layer` → слой появился; RGB-PNG → `400` с текстом про альфу.
- [ ] Ручная приёмка в браузере (скриншот в PR): перетащил слой — числа в панели изменились; ввёл число —
      слой на канве переместился; превью «как поедет» совпадает с канвой по положению слоя (±2 px).

**Out of scope:** аутентификация (gui-service 2.2 добавит токен к тому же серверу); мобильная вёрстка;
undo.
**Edge cases:** PNG > лимита — `413` с лимитом в тексте; браузер без JS — страница показывает текст
«нужен JavaScript», не пустой экран.
**Dependencies:** Task 7.1.
**Module contract:** impl-only.

---

### Task 7.3 — Qt-редактор: вкладка в Пульте оператора (QGraphicsView + гизмо)

**Level:** Senior (Opus) — гизмо поворота/масштаба в Qt пишется руками
**Assignee:** teamlead
**Goal:** вкладка редактора внутри подключения «Симулятор» в Пульте (gui-service 3.2): `QGraphicsView`
со слоями (`QGraphicsPixmapItem`, `ItemIsMovable` нативно), рамка с ручками масштаба и ручкой поворота
(своя, ~150 строк — в Qt стокового гизмо нет), панель `QDoubleSpinBox` на те же поля, загрузка PNG
(`QFileDialog`), «прокрутить», «сохранить». Все правки — команды `template.*` по `SocketChannel`
(`RemoteCommandSender`), превью — PNG из ответа.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/line_sim_editor/tab.py`, `presenter.py`, `gizmo.py`
  (`TransformGizmoItem`), `__init__.py` — MVP по образцу `tabs/pipeline`
- `multiprocess_prototype/frontend/widgets/tabs/line_sim_editor/tests/test_gizmo.py` (pytest-qt:
  математика ручек без сервера), `test_presenter.py` (стаб `RemoteCommandSender`)

**Steps:**
1. `TransformGizmoItem`: рамка по bbox выделенного слоя; 4 угловые ручки → `scale` (равномерный,
   относительно центра); ручка сверху → угол (atan2 от центра); перемещение — нативное. Конверсия
   Qt CW/Y-вниз → движок CCW/мм в одной функции `to_engine_transform()` с тестом-литералом.
2. Presenter: жест → `template.set_layer` (троттлинг 20 Гц во время жеста, финальный на отпускание) →
   `template.preview` → пиксмап «как поедет» рядом с канвой. Спин-боксы — те же команды.
3. Загрузка PNG → base64 → `template.add_layer`; RGB без альфы — диалог с текстом ошибки сервера.
4. Автор пишет hazard-тесты: (а) ответ превью пришёл после следующего жеста — отбрасывается по `seq`
   (не мигает старым); (б) обрыв сокета во время жеста — панель блокируется с индикацией, не падает.

**Acceptance criteria:**
- [ ] pytest-qt: перетаскивание слоя программно (`QTest.mouseMove`/`setPos`) → presenter отправил
      `template.set_layer` с `offset_xy_mm`, равным смещению / `px_per_mm` (литерал ±0.01 мм).
- [ ] Ручка поворота: угол Qt `+30°` → команда с углом движка по конвенции Ф3.1 (литерал в тесте, не
      вычисление той же формулой).
- [ ] Угловая ручка: растяжение bbox ×2 → `scale` ×2 (±0.01), центр слоя не сдвинулся (±1 px).
- [ ] Ввод в `QDoubleSpinBox` угла → та же команда, что от ручки; ответ сервера обновляет позицию элемента
      на канве (одно направление истины).
- [ ] Ручная приёмка в Пульте с живым симулятором (скриншот в PR): правка слоя видна на дисплее `scene`
      у следующего заспавненного объекта.
- [ ] Ни одного `if backend_name == ...` в вкладке; вкладка подключается через тот же MVP-контракт,
      что `tabs/pipeline` (gui-service 3.2 — точка посадки).

**Out of scope:** гизмо для группы слоёв целиком (паспортный угол/масштаб — спин-боксы объекта
достаточно в v1); undo; drag-and-drop файлов на канву.
**Edge cases:** слой полностью прозрачен после правок — рамка по нулевому bbox не рисуется, слой
выделяется из списка; два одинаковых слоя — выделение по z-order (верхний).
**Dependencies:** Task 7.1; gui-service Task 3.2 (Пульт подключён к симулятору).
**Module contract:** impl-only (вкладка по MVP-образцу; `gizmo.py` — докстринг-контракт с формулами).

---

### Task 7.4 — Горячее применение и содержимое каталога

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** сохранённый шаблон применяется без рестарта — следующий спавн берёт новый (Ф3.3 Step 5
`invalidate()`), текущие объекты не перерисовываются; загруженные PNG ложатся в каталог пресета
(`Services/line_sim/presets/<preset>/layers/`) рядом с YAML, чтобы пресет был переносим как папка.

**Files:**
- `Services/line_sim/core/template_editor.py` — `save()` пишет PNG слоёв в каталог пресета и относительные
  пути в YAML
- `Services/line_sim/core/spawner.py` — `invalidate()`/подписка на смену шаблона
- `Services/line_sim/tests/test_hot_apply.py`

**Acceptance criteria:**
- [ ] После `template.save` объект, заспавненный ДО — рендер не изменился (кэш), заспавненный ПОСЛЕ —
      с новым слоем (пиксельная разность > 0); `LayeredObject.render` не вызывался для старых объектов.
- [ ] Каталог пресета переносим: копия папки в tmp → `ScenePreset.from_yaml` из копии загружается и
      рендерит идентично (относительные пути).
- [ ] Битый PNG в каталоге → понятная ошибка при загрузке с именем файла, не крэш `cv2`.

**Out of scope:** версионирование шаблонов; библиотека пресетов с превью.
**Dependencies:** Task 7.1; Ф3.3.
**Module contract:** impl-only.
