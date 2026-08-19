# Phase 6 — Пульт (вкладка GUI)

Часть плана [`plan.md`](plan.md). Реализует «Пульт — вкладка в GUI прототипа по
образцу существующих» из vision.md: управление (скорость/поток/брак/пауза/«выпусти
брак сейчас») + журнал обмена (две колонки, в духе окна-монитора робота) + ROI мышью.

---

### Task 6.1 — Вкладка-пульт: скелет + контролы

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** новая вкладка в GUI прототипа (по образцу `tabs/pipeline`: `tab.py` +
presenter, `DiffScrollTabLayout`, `AppServices` DI) с контролами: скорость ленты
(→ команда ПЧ), интервал/плотность потока объектов, вероятность брака, пауза потока,
кнопка «выпусти брак сейчас» — каждый контрол вызывает УЖЕ существующий
программный API из Ф2–Ф3 (эта задача не добавляет новую логику, только UI-обвязку).

**Контекст:** `multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py` —
прямой образец MVP: `PipelineTab.__init__(self, services: AppServices, ...)`,
`self._presenter = PipelinePresenter(services, ...)`, `DiffScrollTabLayout(title=...,
action_width=..., nav_width=...)`. Пульт проще (нет canvas/graph) — структура: колонка
контролов + область журнала (Task 6.2) снизу/сбоку.

**Files:**
- НОВЫЙ `multiprocess_prototype/frontend/widgets/tabs/line_sim_pult/tab.py` —
  `LineSimPultTab(QWidget)`
- НОВЫЙ `multiprocess_prototype/frontend/widgets/tabs/line_sim_pult/presenter.py` —
  `LineSimPultPresenter`
- НОВЫЙ `multiprocess_prototype/frontend/widgets/tabs/line_sim_pult/__init__.py`
- Точка регистрации вкладки (найти по образцу — где регистрируется `PipelineTab` в
  общем списке вкладок GUI, тот же механизм для новой)
- `multiprocess_prototype/frontend/widgets/tabs/line_sim_pult/tests/
  test_line_sim_pult_tab.py`, `test_line_sim_pult_presenter.py`

**Steps:**
1. Найти, где и как регистрируются вкладки верхнего уровня (grep по использованию
   `PipelineTab(` вне его собственного пакета — вероятно в главном окне/`chrome`
   слое) — зарегистрировать `LineSimPultTab` рядом, УСЛОВНО (вкладка видна только
   когда активный рецепт содержит `sim.enabled: true` — не показывать пульт для
   чисто боевых рецептов; свериться, есть ли уже механизм условной видимости вкладок
   по содержимому рецепта, например у Devices/Pipeline).
2. `LineSimPultPresenter`: методы `set_belt_speed(mm_s)` → команда
   `DeviceManager.call("vfd_belt", "run"/"set_freq", {...})` (через
   `command_sender`/`process_manager_proxy`, как уже делает `PipelinePresenter` для
   `restart_topology`/`proc_start` и т.п. — те же привилегированные CONTROL_ACTIONS,
   см. `PipelineTab._CONTROL_ACTIONS`); `set_spawn_interval(lo, hi)`,
   `set_defect_probability(p)`, `set_paused(bool)`, `release_defect_now()` →
   команды `LineSimCameraPlugin`/`ObjectSpawner`-хуку (Ф3.3) через тот же
   command-канал.
3. `LineSimPultTab`: `DiffScrollTabLayout` с action-колонкой (кнопки/слайдеры
   контролов) — БЕЗ palette/canvas-колонок пайплайна (не копировать структуру
   3-колоночного layout буквально, брать только то, что нужно).

**Acceptance criteria:**
- [ ] `LineSimPultTab(services)` создаётся без исключений при наличии
      `AppServices`-фикстуры (по образцу существующих тестов `test_pipeline_tab_
      integration.py` — какая фикстура там используется, та же годится здесь).
- [ ] Нажатие контрола скорости с конкретным значением (например 30 мм/с) приводит
      к вызову `command_sender`/`process_manager_proxy` с командой, эквивалентной
      `DeviceManager.call("vfd_belt", "set_freq", {"freq_hz": ...})` (проверяется
      через fake/spy `command_sender` в тесте — assert на ИМЕННО этот вызов, не на
      факт "что-то отправили").
- [ ] Кнопка «выпусти брак сейчас» вызывает `release_defect_now()` РОВНО один раз на
      клик (двойной клик — либо debounce, либо два вызова — зафиксировать выбранное
      поведение явно и тестом).
- [ ] Пауза (чекбокс/кнопка) переключает состояние `set_paused` в соответствии с
      видимым состоянием контрола (toggle туда-обратно даёт `set_paused(True)`, затем
      `set_paused(False)` — не залипает на одном значении).
- [ ] Вкладка НЕ видна/недоступна, когда активный рецепт не содержит
      `sim.enabled: true` (проверяется через presenter/условие видимости, без
      необходимости реально запускать GUI).

**Out of scope:** журнал обмена (Task 6.2), ROI (Task 6.3).
**Edge cases:** команда отправлена, пока процесс `robot`/`line_cam` ещё не поднят
(гонка старта) — presenter не должен падать, ошибка команды обрабатывается так же,
как у `PipelinePresenter` (есть `notify`/`_show_status` — переиспользовать этот
канал сообщений, не заводить новый).
**Dependencies:** Task 2.1 (скорость ПЧ реально на что-то влияет), Task 3.3 (спавн/
пауза/форс-брак — реальные хуки, не заглушки).
**Module contract:** new-full (новый пакет вкладки — tab.py + presenter.py + tests/,
≥3 файла, ≥2 публичных класса).

---

### Task 6.2 — Встроенный журнал обмена (переиспользование `SimMonitorWindow`)

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** журнал «принято от инспектора ↔ ответила линия» — ВСТРОЕННЫЙ в вкладку
пульта (не отдельное всплывающее окно), переиспользующий панели/цвета/рендер из
`Services/robot_comm/server/sim_monitor.py` (перенесён в Ф0) + счётчики из Ф5.1/5.3.

**Контекст:** `SimMonitorWindow` уже реализует ВСЁ необходимое: две колонки, цвет по
классу события, автопрокрутка, шапка со счётчиками — как отдельный `QWidget`. Задача —
не переписать это, а извлечь переиспользуемую часть (панели) и встроить в
`LineSimPultTab`, подключив `journal.drain()`/`counters()` через уже существующую
экспозицию (Task 5.1 — команда `get_journal_counters`; здесь нужен ЕЩЁ доступ к самим
строкам журнала (`drain()`), которого Task 5.1 не давал — только counters).

**Files:**
- `Services/robot_comm/server/sim_monitor.py` — при необходимости выделить
  `_make_pane`/`_render`/`_TAG_COLOR` в переиспользуемые функции/класс (МИНИМАЛЬНЫЙ
  рефактор, не переписывать логику — `SimMonitorWindow` как отдельное окно должен
  продолжать работать для CLI `--gui`, регрессия недопустима)
- `Plugins/sim/robot_sim_process/plugin.py` — добавить команду
  `drain_journal_entries` (аналог `get_journal_counters` из Ф5.1, но возвращает
  `journal.drain()` — сериализованный в dict/list, Dict at Boundary)
- НОВЫЙ `multiprocess_prototype/frontend/widgets/tabs/line_sim_pult/journal_panel.py`
  — `LineSimJournalPanel(QWidget)`, встраивается в `LineSimPultTab`

**Steps:**
1. Проверить, что `Services/robot_comm` может отдавать `JournalEntry` через границу
   процесса — `JournalEntry`/`side`/`text`/`tag`/`t` (все примитивы, `to_dict()`-
   подобная сериализация нужна, т.к. `frozen dataclass` сам по себе не Dict at
   Boundary — добавить `asdict`-конверсию в команде `drain_journal_entries`).
2. `LineSimJournalPanel`: таймер (как `SimMonitorWindow._pump`, `QTimer`), тянет
   `drain_journal_entries` через `command_sender`, рендерит теми же
   правилами/цветами, что `SimMonitorWindow._render`/`_TAG_COLOR` (импортировать
   функцию рендера, не копировать её текст).
3. Убедиться, что `python -m Services.robot_comm.server --gui` (отдельное окно,
   Ф0/существующий CLI) продолжает работать НЕ ЗАТРОНУТЫМ этим рефакторингом —
   regression-прогон существующих `test_sim_monitor.py`.

**Acceptance criteria:**
- [ ] `drain_journal_entries({})` возвращает список словарей с ключами `t`, `side`,
      `text`, `tag`, дважды вызванный подряд без новых событий между вызовами —
      второй вызов возвращает ПУСТОЙ список (журнал дренируется, не копится
      бесконечно — то же поведение, что `SimJournal.drain()` уже гарантирует).
- [ ] `LineSimJournalPanel`, подключенная к фейковому источнику с известными
      записями (`tag="dup"`), рендерит их визуально отличимо (другой цвет/стиль) от
      записей `tag=""` — проверяется через `qt-mcp`/`pytest-qt`-снятие текста/стиля
      виджета, ЛИБО через прямую проверку возвращаемого HTML/стиля рендер-функции
      (что дешевле и надёжнее — выбрать при реализации).
- [ ] `pytest Services/robot_comm/tests/test_sim_monitor.py -q` — 0 failed (регрессия
      к существующему отдельному окну отсутствует).
- [ ] Заголовок панели (счётчики) отражает те же числа, что
      `get_journal_counters` (Ф5.1) — оба пути чтения согласованы (не расходятся при
      одновременном опросе).

**Out of scope:** отдельное всплывающее Qt-окно (`SimMonitorWindow` как есть — не
трогать его публичное поведение, кроме вынесения переиспользуемых кусков).
**Edge cases:** журнал очень длинный (тысячи строк за долгий прогон) — панель не
должна замедлять GUI (переиспользовать `setMaximumBlockCount`, уже решённое
ограничение в `SimMonitorWindow._make_pane`).
**Dependencies:** Task 6.1, Task 5.1 (journal exposure), Task 5.3 (согласованность
счётчиков).
**Module contract:** impl-only.

---

### Task 6.3 — ROI мышью на превью сцены

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** прямоугольник ROI (Task 4.2) двигается и растягивается МЫШЬЮ на канве,
показывающей сцену целиком (не только то, что попадает в кадр камеры) — по отпускании
кнопки мыши вызывает `cmd_set_roi` (Task 4.2).

**Контекст:** `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/
graph_view.py`/`graph_scene.py`/`node_item.py` — уже рабочий пример
QGraphicsView-канвы с перетаскиваемыми элементами (ноды pipeline) — прямой
архитектурный прецедент для перетаскиваемого/растягиваемого прямоугольника ROI, не
писать QGraphicsView-интеграцию с нуля.

**Files:**
- НОВЫЙ `multiprocess_prototype/frontend/widgets/tabs/line_sim_pult/roi_canvas.py` —
  `RoiCanvasView(QGraphicsView)` + `RoiRectItem(QGraphicsRectItem)` (drag/resize по
  образцу `graph/node_item.py`)
- `multiprocess_prototype/frontend/widgets/tabs/line_sim_pult/tab.py` (из 6.1) —
  встроить канву

**Steps:**
1. Канва показывает СТАТИЧНУЮ картинку сцены (снимок текущего кадра `line_sim_camera`
   до ROI-кропа — если движок отдаёт только уже-кропнутый кадр, добавить
   диагностический вывод «полной сцены» отдельным каналом/дисплеем, минимально
   необходимым для этой задачи — не путать с полноценным вторым видом, это просто
   подложка для перетаскивания рамки).
2. `RoiRectItem`: перетаскивание (move) + минимум один resize-handle (угол) — по
   аналогии с существующими интерактивными QGraphicsItem в `graph/` (изучить, как
   там реализован drag, прежде чем писать с нуля).
3. По `mouseReleaseEvent` (отпускание кнопки) — вызвать `cmd_set_roi` (Task 4.2) с
   финальными координатами прямоугольника (НЕ на каждое промежуточное движение мыши
   — не заваливать команду-канал живым потоком во время перетаскивания).

**Acceptance criteria:**
- [ ] Программное перетаскивание `RoiRectItem` (через `pytest-qt`/`qt-mcp`
      `qt_batch`: mouse press → move → release на известные координаты) приводит
      РОВНО к одному вызову `cmd_set_roi` (не на каждый промежуточный `mouseMoveEvent`
      — проверяется счётчиком вызовов spy/fake команд-канала).
- [ ] Итоговые координаты, переданные в `cmd_set_roi`, соответствуют финальной
      геометрии прямоугольника на канве (с точностью до перевода экранных координат
      в координаты сцены — формула перевода детерминирована и тестируема отдельно
      от мыши).
- [ ] Растягивание за resize-handle меняет `width`/`height` прямоугольника, НЕ его
      `x`/`y` (перетаскивание за тело — наоборот, меняет `x`/`y`, не
      `width`/`height`) — два разных жеста дают два разных, различимых эффекта.
- [ ] Попытка растянуть/подвинуть рамку ЗА пределы канвы (сцены) — клампится
      визуально (рамка не уезжает за край подложки), согласовано с серверным
      клампом из Task 4.2 (те же границы).

**Out of scope:** полноценный второй вид сцены сбоку (Deferred); zoom канвы.
**Edge cases:** канва открыта, пока `line_cam`-процесс ещё не отдал ни одного кадра
(снимок сцены пуст) — показывать плейсхолдер, не падать.
**Dependencies:** Task 6.1, Task 4.2.
**Module contract:** impl-only.
