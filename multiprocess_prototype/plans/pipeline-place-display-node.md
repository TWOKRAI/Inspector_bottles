# Pipeline: размещение узла дисплея на холсте + привязка кадра проводом

- **Slug:** pipeline-place-display-node
- **Дата:** 2026-05-29
- **Статус:** Реализовано (Task 1.1–4.2 done; остаётся опц. Task 5.1 + follow-ups #3/#6/#7/#8)
- **Ветка:** `refactor/config-driven-launch` (по решению владельца — без отдельной feat-ветки)
- **Коммиты:** `facab78f` (1.1+2.1+3.1) → ревью (12/16 находок) → `a4111768` (фиксы #1/#2/#4/#5 + тесты 4.1/4.2)

## Обзор

Сейчас дисплей-бокс (`DisplayNodeItem`) появляется на холсте Pipeline-редактора
**только** если в загруженном рецепте уже есть запись в `topology["displays"]`
(секция `display_bindings` YAML). В палитре — лишь плагины, в контекстном меню
фона — только «Add Process...» (причём даже этот сигнал не подключён к presenter).
Поэтому пользователь не может направить кадр на отображение через GUI без ручного
редактирования YAML рецепта — это разрыв в UX.

Реализуем **вариант A** (одобрен владельцем): пользователь ставит **пустой**
(непривязанный) бокс дисплея на холст через контекстное меню фона «Add Display →»
со списком каналов, затем тянет провод от выходного порта процесса в порт `frame`
бокса. Поддерживается fan-in (несколько источников в один дисплей).

## Ключевой архитектурный момент (главная сложность варианта A)

Модель хранит дисплеи **только** как binding `{node_id: <source endpoint>, display_id}`
в `topology["displays"]`. «Пустой» бокс без источника там храниться не может.
При каждой мутации происходит full scene reload из topology
(`_on_topology_replaced` → `load_scene_with_ports` → `_display_nodes_cache` строится
из `topo["displays"]` в `_build_display_nodes`), и непривязанный бокс-призрак исчезнет.

**Решение:** добавить в `PipelinePresenter` GUI-состояние «размещённые, но
непривязанные» дисплеи: `_placed_display_ids: set[str]` + позиция в
`_gui_positions[display_id]`. `_build_display_nodes` должен **дорисовывать** боксы для
placed-but-unbound каналов (которых ещё нет в `topo["displays"]`), чтобы они
переживали reload в рамках сессии. После того как пользователь притянул провод
(`BindDisplay` → запись в `topology["displays"]`), бокс становится «настоящим».

**Жизненный цикл `_placed_display_ids`:**
- `place_display(display_id, x, y)` → добавить в set + `_gui_positions[display_id] = (x, y)` + триггер reload, чтобы бокс отрисовался.
- После успешного `BindDisplay`: канал теперь есть в `topo["displays"]` → `_build_display_nodes` рисует его как «настоящий». Запись в `_placed_display_ids` становится избыточной, но **не вредит** (дедуп по `display_id` в `_build_display_nodes`). Допустимо: оставить в set до смены рецепта ИЛИ снять после bind — выбрать в Task 2.1, документировать.
- Удаление **непривязанного** бокса: убрать из `_placed_display_ids` + `_gui_positions` **без** topology-мутации (нет binding → нечего слать в `UnbindDisplay`).
- Смена рецепта / новый `load_topology_from_config`: `_placed_display_ids` сбрасывается (placed-but-unbound НЕ сохраняются в рецепт — нечего, binding нет). Это допустимо по решению владельца.

## Контракт DisplayCatalog (точные имена — проверено)

`multiprocess_prototype/domain/protocols/display_catalog.py`:
- `services.displays.list_displays() -> tuple[DisplaySpec, ...]`
- `services.displays.resolve(display_id) -> DisplaySpec | None`
- `DisplaySpec(display_id: str, display_name: str, width, height, format, fps_limit, ring_buffer_blocks, metadata)`

`presenter._resolve_display_name(display_id)` уже использует `services.displays.resolve(...).display_name` (presenter.py:917-925).

## Что переиспользуем (НЕ переделывать)

- `DisplayNodeItem` / `DisplayNodeData` — зелёный бокс, 1 входной порт `frame`, endpoint `display.<display_id>.frame` (`graph/display_node_item.py`).
- `GraphScene.add_display_node(DisplayNodeData)` (`graph_scene.py:100`).
- `presenter.add_wire` распознаёт префикс `display.` → `dispatch(BindDisplay)` (`presenter.py:443-461`).
- `presenter._build_display_nodes` рисует боксы из `topo["displays"]` (`presenter.py:870`).
- `presenter.remove_selected` для bound-боксов → `UnbindDisplay` (`presenter.py:384`).
- Контекстное меню фона `_show_background_menu` с сигналом `add_process_requested` (`graph_scene.py:283-290`).
- Permission gating: `tab._can_edit()` → `services.auth.has_permission("tabs.pipeline.edit")` (`tab.py:290`).

## Vertical slice (tracer bullet)

Фича multi-layer: **scene** (контекстное меню + сигнал) → **presenter**
(GUI-состояние placed-but-unbound) → **tab** (проброс каналов + wiring сигнала +
permission gating). Task 1.1 — тонкий E2E срез: один пункт «Add Display →» с одним
каналом ставит один пустой бокс, который переживает reload. Task 2.x и 3.x —
углубление каждого слоя (drag-to-bind, удаление unbound, fan-in, полное меню каналов).

---

## Порядок выполнения

### Phase 1: Vertical slice — пустой бокс на холсте переживает reload

- Task 1.1: **[VERTICAL SLICE]** Сквозной минимальный путь: меню «Add Display →» (один канал) → `scene.add_display_requested` → `tab` → `presenter.place_display` → бокс отрисован и переживает reload [DONE facab78f]
  - **Module contract:** public-api-change (новый сигнал в `GraphScene`, новый публичный метод `place_display` в presenter)

### Phase 2: Углубление presenter — корректное GUI-состояние

- Task 2.1: Полная логика `_placed_display_ids` в `_build_display_nodes` + удаление непривязанного бокса без topology-мутации [DONE facab78f; review-фиксы #1/#2/#4/#5 → a4111768] (зависит от 1.1)
  - **Module contract:** impl-only

### Phase 3: Углубление scene/tab — полное меню каналов + permission gating

- Task 3.1: Подменю «Add Display →» со списком всех каналов из `services.displays` + permission gating размещения [DONE facab78f — реализовано в составе 1.1] (зависит от 1.1)
  - **Module contract:** public-api-change (`GraphScene` принимает список каналов)

### Phase 4: Тесты

- Task 4.1: unit-тесты presenter (`place_display`, выживание при reload, удаление unbound, fan-in bind) [DONE a4111768 — 20 тестов] (зависит от 2.1)
  - **Module contract:** n/a
- Task 4.2: pytest-qt тесты scene/tab (контекстное меню, размещение, drag-to-bind) + smoke через qt-mcp [DONE a4111768 — pytest-qt 13 тестов; live smoke: реальная сборka таба ✓, жест контекст-меню не драйвится qt-mcp (Qt не шлёт QContextMenuEvent из синтетики)] (зависит от 3.1)
  - **Module contract:** n/a

### Phase 5 (опционально): фикс рассинхрона display_id

- Task 5.1: привести `display_id` в `demo_webcam_split_merge.yaml` к каналам из `displays.yaml` [PENDING] (независимо)
  - **Module contract:** n/a

---

## Задачи

### Task 1.1 — [VERTICAL SLICE] Размещение пустого бокса дисплея через меню фона

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Через контекстное меню фона «Add Display →» (минимум один канал) пользователь ставит пустой непривязанный бокс дисплея на холст; бокс переживает хотя бы один full scene reload в рамках сессии.
**Context:** Это tracer bullet через все три слоя. Цель — получить feedback loop сразу: новый сигнал scene, новое GUI-состояние presenter (`_placed_display_ids`), wiring в tab. Архитектурно самое сложное — заставить непривязанный бокс пережить reload, который перестраивает scene из `topo["displays"]`, где такого бокса нет. Поэтому уровень Senior+.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/graph_scene.py` — добавить сигнал `add_display_requested(str, float, float)` (display_id, x, y); в `_show_background_menu` добавить подменю «Add Display →» (на этом этапе — хотя бы один реальный канал, список прокидывается из tab — см. ниже; если список ещё пуст, подменю disabled). Хранить список каналов в поле scene (например `self._display_channels: list[tuple[str, str]]` = (display_id, display_name)), сеттер `set_display_channels(...)`.
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` — добавить поле `_placed_display_ids: set[str]` (инициализация в `__init__` рядом с `_display_nodes_cache`, ~line 92); публичный метод `place_display(self, display_id: str, x: float, y: float) -> None`; минимальная правка `_build_display_nodes`, чтобы дорисовывать боксы для `display_id` из `_placed_display_ids`, которых нет в `topo["displays"]`.
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py` — в `_connect_signals` подключить `self._scene.add_display_requested` → `self._on_add_display_requested`; реализовать `_on_add_display_requested(display_id, x, y)` с permission-guard (`if not self._can_edit(): return`) → `self._presenter.place_display(...)`; при инициализации (после `set_scene`) загрузить каналы из `services.displays.list_displays()` в scene через `set_display_channels`.

**Steps:**
1. В `GraphScene`: объявить `add_display_requested = Signal(str, float, float)`; в `__init__` — `self._display_channels: list[tuple[str, str]] = []`; метод `set_display_channels(self, channels: list[tuple[str, str]]) -> None`.
2. В `_show_background_menu` после `add_action = menu.addAction("Add Process...")` добавить подменю `display_menu = menu.addMenu("Add Display →")`; для каждого `(display_id, display_name)` из `self._display_channels` создать action (текст = `display_name or display_id`), хранить mapping action→display_id; если список пуст — `display_menu.setEnabled(False)`. После `menu.exec(...)` если выбран display-action — `self.add_display_requested.emit(display_id, pos.x(), pos.y())`.
3. В `PipelinePresenter.__init__`: добавить `self._placed_display_ids: set[str] = set()`.
4. Реализовать `place_display(display_id, x, y)`: записать `self._gui_positions[display_id] = (x, y)`; `self._placed_display_ids.add(display_id)`; затем триггернуть перерисовку scene (вызвать тот же путь, что reload использует для боксов — например прямой `_build_display_nodes` + `load_scene_with_ports`, либо переиспользовать существующий рендер-метод). Решение по способу перерисовки задокументировать комментарием. Без domain dispatch (binding ещё нет).
5. В `_build_display_nodes`: после построения боксов из `topo["displays"]` пройти по `self._placed_display_ids`; для каждого `display_id`, которого ещё нет в `boxes_by_display_id`, создать `DisplayNodeData(node_id=display_id, display_id=display_id, display_name=self._resolve_display_name(display_id), x, y из _gui_positions)` и добавить в `_display_nodes_cache`.
6. В `tab._connect_signals`: `self._scene.add_display_requested.connect(self._on_add_display_requested)`.
7. В `tab.__init__` после `self._presenter.set_scene(self._scene)`: получить каналы `[(s.display_id, s.display_name) for s in self._services.displays.list_displays()]` и `self._scene.set_display_channels(...)`.
8. Реализовать `tab._on_add_display_requested(self, display_id, x, y)`: guard `if not self._can_edit(): return`; `self._presenter.place_display(display_id, x, y)`.

**Acceptance criteria:**
- [ ] `GraphScene` имеет сигнал `add_display_requested(str, float, float)` и метод `set_display_channels`.
- [ ] Подменю «Add Display →» появляется в контекстном меню фона; при пустом списке каналов оно disabled.
- [ ] `presenter.place_display(display_id, x, y)` создаёт `DisplayNodeItem` на scene **без** обращения к `services.commands.dispatch`.
- [ ] После `place_display` + искусственного reload (`_on_topology_replaced` / повторный `_build_display_nodes`) бокс остаётся на scene (unit-проверка: `scene.get_node(display_id) is not None`).
- [ ] Permission gating: при `auth.has_permission("tabs.pipeline.edit") == False` `tab._on_add_display_requested` не вызывает `place_display`.
- [ ] `python scripts/run_framework_tests.py` (или целевой pytest по pipeline) — без падений существующих тестов.

**Out of scope:** drag-to-bind (Task 2.1 покрывает выживание, привязка уже работает через `add_wire`), удаление unbound-бокса (Task 2.1), полное меню всех каналов с группировкой (Task 3.1), фикс demo-рецепта (Task 5.1). Не сохранять placed-but-unbound в рецепт.
**Edge cases:** повторное `place_display` того же `display_id` (идемпотентно — set дедуплицирует); `place_display` канала, которого нет в каталоге (имя резолвится в пустое → подзаголовок = display_id).
**Dependencies:** нет.
**Module contract:** public-api-change

---

### Task 2.1 — Полный жизненный цикл placed-but-unbound в presenter

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Корректно обработать весь жизненный цикл непривязанного бокса: выживание при многократных reload, переход в «настоящий» бокс после `BindDisplay`, удаление непривязанного бокса без topology-мутации, сброс при смене рецепта.
**Context:** Развивает архитектурный фундамент из 1.1. Главная тонкость — `remove_selected` сейчас определяет display-боксы по `display_id` из `_model.get_displays()` (только bound). Непривязанный бокс там отсутствует → нужно отдельно проверять `_placed_display_ids` и удалять без dispatch. Также нужно решить судьбу записи в `_placed_display_ids` после bind и при смене рецепта.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` — доработать `remove_selected` (ветка для unbound-боксов), решить сброс `_placed_display_ids` при `load_topology_from_config` / смене рецепта, при необходимости снять `display_id` из set после успешного `BindDisplay` в `add_wire`.

**Steps:**
1. В `remove_selected`: до или внутри цикла учесть, что `node_id` может быть в `_placed_display_ids`, но отсутствовать в `display_box_ids` (нет binding). Для такого узла: `self._placed_display_ids.discard(node_id)`, `self._gui_positions.pop(node_id, None)`, затем перерисовать scene (тем же путём, что `place_display`) **без** `dispatch`. Не слать `UnbindDisplay` (нечего отвязывать).
2. Учесть смешанный случай: бокс, который был placed, а затем привязан (есть и в set, и в `topo["displays"]`). Удаление такого = существующая ветка `UnbindDisplay` + дополнительно `discard` из `_placed_display_ids`.
3. В `add_wire` (ветка `is_display_target`, после успешного `dispatch(BindDisplay)`): принять решение — снимать ли `display_id` из `_placed_display_ids`. Рекомендация: снять (`discard`), т.к. канал теперь живёт в `topo["displays"]` и рисуется как «настоящий»; дедуп в `_build_display_nodes` всё равно защищает от двойного бокса. Задокументировать выбор комментарием со ссылкой на этот план.
4. Сброс при смене рецепта: найти точку, где presenter перезагружает топологию из рецепта (`load_topology_from_config` и/или обработчик активации рецепта). Очищать `self._placed_display_ids.clear()` там, где это семантически «новая сессия редактора». Проверить, что обычный `_on_topology_replaced` (мутация в рамках сессии) НЕ очищает set.
5. Убедиться, что `_build_display_nodes` после bind не создаёт дубль бокса (дедуп по `display_id` в `boxes_by_display_id` уже есть — проверить, что placed-ветка идёт ПОСЛЕ построения из `topo["displays"]` и пропускает уже существующие).

**Acceptance criteria:**
- [ ] Удаление непривязанного бокса (Delete / контекстное меню) убирает его из scene и из `_placed_display_ids`, НЕ вызывая `services.commands.dispatch`.
- [ ] После `BindDisplay` (drag-to-bind) бокс остаётся ровно один (нет дубля от placed-ветки и bound-ветки).
- [ ] Удаление привязанного бокса по-прежнему вызывает `UnbindDisplay` для каждого источника (fan-in) — существующее поведение не сломано.
- [ ] Многократный reload (3+ `_on_topology_replaced` подряд) не теряет непривязанный бокс и не плодит дубли.
- [ ] Смена рецепта сбрасывает `_placed_display_ids` (непривязанные боксы исчезают), bound-дисплеи из нового рецепта рисуются корректно.
- [ ] Существующие тесты presenter (`test_presenter_domain_dispatch.py`, `test_presenter_enhanced.py`) — зелёные.

**Out of scope:** UI-список каналов (Task 3.1), сохранение unbound в рецепт, изменение domain-команд BindDisplay/UnbindDisplay.
**Edge cases:** удаление одновременно выбранных placed-unbound + bound + process-нод в одном `remove_selected`; bind того же источника на тот же дисплей дважды (domain/guard уже отвергает дубль wire — проверить, что для display не падает).
**Dependencies:** Task 1.1.
**Module contract:** impl-only

---

### Task 3.1 — Полное меню «Add Display →» со списком каналов + permission gating

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Подменю «Add Display →» показывает все каналы из `services.displays.list_displays()` (имя + id), размещение бокса доступно только при праве `tabs.pipeline.edit`.
**Context:** В 1.1 меню работало хотя бы с одним каналом и базовым проводом сигнала. Здесь — полноценный список каналов, аккуратные подписи, актуализация при необходимости и явное permission gating в tab. Scene не имеет доступа к `services` — список каналов всегда приходит из tab через `set_display_channels`.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/graph_scene.py` — финализировать построение подменю по полному `self._display_channels` (подпись = `display_name` или fallback `display_id`); корректная обработка отмены меню (ничего не эмитить).
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py` — финализировать загрузку каналов (`set_display_channels`) и permission gating в `_on_add_display_requested`; убедиться, что список каналов передаётся при инициализации (и, если нужно, обновляется при смене набора дисплеев — иначе задокументировать, что список статичен на сессию).

**Steps:**
1. В `_show_background_menu`: построить пункты подменю из всех `self._display_channels`; mapping action→display_id (например через dict или `action.setData(display_id)`); если канал уже размещён/привязан — на этом этапе НЕ фильтровать (повтор идемпотентен, см. 1.1), но допустимо пометить tooltip'ом. Отмена меню (exec вернул None или не-display action) → не эмитить `add_display_requested`.
2. В `tab`: убедиться, что `set_display_channels` вызывается с полным списком `[(s.display_id, s.display_name) for s in self._services.displays.list_displays()]`. Если каналов нет — список пустой, подменю disabled (поведение из 1.1).
3. Permission gating: `_on_add_display_requested` начинается с `if not self._can_edit(): return`. Дополнительно (UX): рассмотреть, нужно ли визуально гасить подменю при отсутствии прав — НЕ обязательно (guard в tab достаточно), но задокументировать решение.
4. Проверить, что подписи на русском не требуются (это id/имена каналов из конфига) — оставить как есть из `DisplaySpec.display_name`.

**Acceptance criteria:**
- [ ] Подменю «Add Display →» содержит по одному пункту на каждый канал из `list_displays()`, подпись = `display_name` (fallback `display_id`).
- [ ] Выбор пункта эмитит `add_display_requested(display_id, x, y)` с корректным `display_id`.
- [ ] Отмена контекстного меню не эмитит сигнал (тест на cancel).
- [ ] При `tabs.pipeline.edit == False` размещение не происходит (guard в `_on_add_display_requested`).
- [ ] Scene по-прежнему не импортирует `AppServices` / `services.displays` напрямую (список приходит из tab).

**Out of scope:** presenter-логика (Task 2.1), drag-to-bind (уже работает), фикс рецепта (5.1), динамическое добавление новых каналов в реестр.
**Edge cases:** пустой каталог дисплеев (подменю disabled); канал с пустым `display_name` (подпись = `display_id`); очень длинный список каналов (без скролла — приемлемо для текущего набора из 3).
**Dependencies:** Task 1.1.
**Module contract:** public-api-change

---

### Task 4.1 — Unit-тесты presenter: place_display, выживание, удаление, fan-in

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Покрыть unit-тестами логику presenter из Task 1.1/2.1 без GUI-зависимостей (через fakes из `domain/tests/_fakes.py`).
**Context:** Архитектурный риск — выживание непривязанного бокса при reload и отсутствие дублей после bind. Эти инварианты должны быть зафиксированы тестами. Использовать существующие хелперы и `FakeDisplayCatalog`.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_presenter_domain_dispatch.py` — дополнить ИЛИ создать новый `test_place_display.py` рядом.
- Опорные: `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/_helpers.py`, `multiprocess_prototype/domain/tests/_fakes.py` (FakeDisplayCatalog: `list_displays`, `resolve`).

**Steps:**
1. Тест: `place_display("main", 600, 50)` → на scene появляется `DisplayNodeItem` с `node_id == "main"`, без вызова `commands.dispatch` (проверить через spy/fake, что dispatch не звался).
2. Тест выживания: `place_display` → эмулировать `_on_topology_replaced` (или прямой повторный `_build_display_nodes` + `load_scene_with_ports`) → бокс всё ещё на scene.
3. Тест удаления unbound: `place_display` → `remove_selected(["main"])` → бокса нет, `dispatch` не звался, `"main"` нет в `_placed_display_ids`.
4. Тест перехода в bound: `place_display("main")` → `add_wire("capture_proc.capture.frame", "display.main.frame")` → `BindDisplay` dispatched; после reload ровно один бокс `main` (нет дубля).
5. Тест fan-in: два разных источника привязаны к одному `display_id` → один бокс, два binding-ребра.
6. Тест сброса при смене рецепта: `place_display` → `load_topology_from_config`/смена рецепта → `_placed_display_ids` пуст, непривязанный бокс исчез.

**Acceptance criteria:**
- [ ] Все 6 сценариев выше покрыты тестами и проходят.
- [ ] Тесты не требуют живого qt event loop там, где можно обойтись fakes (использовать `qtbot` только для scene/QGraphicsItem-частей).
- [ ] `python scripts/run_framework_tests.py` зелёный, новые тесты включены.

**Out of scope:** smoke через qt-mcp (Task 4.2), тесты контекстного меню (Task 4.2).
**Edge cases:** см. список выше; добавить тест идемпотентности повторного `place_display` того же канала.
**Dependencies:** Task 2.1.
**Module contract:** n/a

---

### Task 4.2 — pytest-qt тесты scene/tab + обязательный qt-mcp smoke

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** tester
**Goal:** Покрыть pytest-qt тестами контекстное меню «Add Display →», эмиссию сигнала, drag-to-bind через tab; затем провести обязательный smoke через qt-mcp (запуск прототипа + snapshot).
**Context:** Правило проекта (memory: «Qt-MCP smoke verification mandatory») — после любой переписки Qt-таба/виджета прогнать proto + qt_snapshot; pytest-qt unit не доказывают реальную сборку. Паттерн mock-меню — в `test_context_menu.py` (patch `QMenu`).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_context_menu.py` — добавить тесты подменю «Add Display →» (по аналогии с `test_show_background_menu_add_process`).
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_pipeline_tab_integration.py` — тест end-to-end: scene эмитит `add_display_requested` → presenter создаёт бокс → drag wire source→box (через `_on_wire_created` / `add_wire`) → binding в topology.

**Steps:**
1. pytest-qt: `set_display_channels([("main","Основной")])` → `_show_background_menu` (mock QMenu, выбрать display-action) → проверить эмиссию `add_display_requested("main", x, y)`.
2. pytest-qt: пустой список каналов → подменю disabled (проверить `display_menu.isEnabled() is False` или что display-actions нет).
3. pytest-qt: cancel меню → сигнал не эмитится.
4. Интеграция tab: с правом edit — `_on_add_display_requested` создаёт бокс; без права — нет.
5. Интеграция tab: после размещения бокса вызвать `_on_wire_created("<src endpoint>", "display.main.frame")` → проверить, что в `presenter.model` появилась запись display-binding.
6. **qt-mcp smoke (обязательно):** запустить прототип (`/run-proto` или эквивалент), открыть вкладку Pipeline, через `qt_find_widget`/`qt_batch` вызвать контекстное меню фона, выбрать «Add Display → <канал>», снять `qt_snapshot` — убедиться, что зелёный бокс появился; затем протянуть провод и проверить binding. Зафиксировать результат smoke в отчёте.

**Acceptance criteria:**
- [ ] pytest-qt: эмиссия `add_display_requested`, disabled при пустом списке, cancel — покрыты.
- [ ] Интеграционный тест tab: размещение + permission gating + drag-to-bind проходят.
- [ ] qt-mcp smoke выполнен на живом прототипе: бокс размещается через меню, провод привязывается, snapshot подтверждает (не только unit).
- [ ] `python scripts/run_framework_tests.py` зелёный.

**Out of scope:** presenter unit-логика (Task 4.1), фикс рецепта (5.1).
**Edge cases:** smoke на канале с длинным именем; повторное размещение того же канала через меню (бокс не дублируется).
**Dependencies:** Task 3.1 (и косвенно 2.1 для drag-to-bind).
**Module contract:** n/a

---

### Task 5.1 — (опционально) Фикс рассинхрона display_id в demo-рецепте

**Level:** Junior (Haiku)
**Assignee:** docs-writer
**Goal:** Привести `display_id` в `demo_webcam_split_merge.yaml` к реально существующим каналам из `displays.yaml`, чтобы demo-рецепт корректно резолвил имена дисплеев.
**Context:** Рецепт ссылается на `main_output` / `debug_input`, которых нет в каталоге; в `displays.yaml` определены `main` / `debug` / `main_copy`. Из-за рассинхрона `_resolve_display_name` возвращает пустое имя, и в demo боксы подписаны id вместо человекочитаемого имени. Чисто конфигурационная правка.

**Files:**
- `multiprocess_prototype/recipes/demo_webcam_split_merge.yaml` — секция `display_bindings` (строки 43-47).
- Сверка: `multiprocess_prototype/backend/config/displays.yaml` (каналы `main`/`debug`/`main_copy`).

**Steps:**
1. В `display_bindings`: заменить `main_output` → `main`, `debug_input` → `debug` (сохранив соответствующие `node_id` источников).
2. Проверить, нет ли других мест в рецепте/тестах, ссылающихся на `main_output`/`debug_input` (Grep) — если есть, согласовать.
3. Убедиться, что `io_roundtrip`/launch-тесты demo-рецепта остаются зелёными.

**Acceptance criteria:**
- [ ] `display_bindings` ссылается только на каналы, существующие в `displays.yaml` (`main`, `debug`, `main_copy`).
- [ ] Grep по `main_output`/`debug_input` не находит висячих ссылок (или они согласованно обновлены).
- [ ] `test_io_roundtrip.py` / `test_launch_recipe.py` (если затрагивают demo) — зелёные.

**Out of scope:** изменение набора каналов в `displays.yaml`, изменение `node_id` источников (это валидные endpoint'ы процессов).
**Edge cases:** если тесты жёстко ожидают старые id — обновить их в той же задаче.
**Dependencies:** нет (независимая задача, можно делать параллельно).
**Module contract:** n/a

---

## Зависимости между задачами

```
Task 1.1 (vertical slice, teamlead)
  ├── Task 2.1 (presenter lifecycle, teamlead)
  │     └── Task 4.1 (unit presenter, developer)
  └── Task 3.1 (full menu + gating, developer)
        └── Task 4.2 (pytest-qt + qt-mcp smoke, tester)  [также косвенно от 2.1]

Task 5.1 (фикс рецепта, docs-writer) — независимо, в любой момент
```

**Критический путь:** 1.1 → 2.1 → 4.1 и 1.1 → 3.1 → 4.2. Task 1.1 и 2.1 на одном
архитектурном слое — выполнять последовательно одним исполнителем (teamlead),
не параллелить (риск гонки коммитов в presenter.py — см. memory о parallel agents).

## Обязательные требования (применимо ко всем задачам)

- **Dict at Boundary:** presenter работает с `dict` (topology dict, displays как dict-binding); Pydantic/SchemaBase не пересекают границу процессов.
- **qt-mcp smoke обязателен** после Qt-правок (Task 4.2) — запуск proto + `qt_snapshot`, не только pytest-qt unit.
- **Commit trailers:** каждый коммит из плана обязан содержать `Refs: plans/pipeline-place-display-node.md`, `Why:`, `Layer: prototype` (или `mixed`). Conventional Commits.
- **Permission gating** (`tabs.pipeline.edit`): размещение и привязка дисплея — только при праве на edit.
- **Чекбоксы плана:** после каждой выполненной задачи отметить `[x]` + хеш коммита в разделе «Порядок выполнения».
- Весь пользовательский вывод и комментарии — на русском.

## Риски и ограничения

- **Главный риск:** placed-but-unbound состояние — это GUI-only слой поверх unidirectional reload. Неправильная точка сброса `_placed_display_ids` (например очистка в `_on_topology_replaced`) убьёт бокс при первой же мутации. Точку сброса определяет Task 2.1, тест выживания — Task 4.1.
- **Дубли боксов:** placed-ветка в `_build_display_nodes` должна идти ПОСЛЕ построения из `topo["displays"]` и пропускать уже существующие `display_id` (дедуп). Иначе после bind — два бокса.
- **Scene без services:** `GraphScene` не должен импортировать `AppServices`/`services.displays` — список каналов всегда из tab (граница соблюдена в Task 1.1/3.1).
- **sentrux:** новый публичный сигнал + метод presenter могут чуть сдвинуть связность модуля pipeline. Допустимо в пределах -5..-10; при большем — пересмотреть с teamlead.
- **Не сохраняем unbound в рецепт** — это сознательный компромисс (binding нет → нечего сериализовать), согласован с владельцем.
