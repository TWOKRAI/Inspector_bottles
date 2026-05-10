# Plan: Конструктор Phase 6 — Display assignment + Live мониторинг

**Date:** 2026-05-04
**Status:** DONE

## Overview

Фаза 6 добавляет два аспекта к конструктору: (1) назначение wire-соединений на display-окна через визуальную ноду DisplayTargetNode и QComboBox в WireInspectorPanel; (2) live-мониторинг wire-каналов — overlay с fps/latency/buffer_fill на pipes канваса и SHM dashboard в правой панели.

Фундамент: расширение WireDataBridge для сбора метрик (сейчас только статусы), затем визуальные компоненты.

## Порядок выполнения

### Phase 1: WireMetrics — расширение WireDataBridge

- Task 1.1: WireMetrics dataclass + сигнал metrics_changed [DONE]
- Task 1.2: Polling метрик через wire.metrics команду [DONE]

### Phase 2: Wire Monitoring Overlay (QGraphicsItem badge)

- Task 2.1: WireMetricsBadge — QGraphicsItem overlay на pipe [DONE]
- Task 2.2: Интеграция badge в PluginGraphAdapter [DONE]

### Phase 3: DisplayTargetNode

- Task 3.1: DisplayTargetNode — кастомная нода канваса [DONE]
- Task 3.2: Генерация display-нод из SECTION_DISPLAYS + wire assignment [DONE]

### Phase 4: Display selector в WireInspectorPanel

- Task 4.1: QComboBox display_target в WireInspectorPanel [DONE]

### Phase 5: SHM Dashboard Panel

- Task 5.1: ShmDashboardPanel — страница index 3 в QStackedWidget [DONE]
- Task 5.2: Интеграция dashboard в ConstructorTabWidget [DONE]

## Риски и ограничения

- NodeGraphQt не поддерживает child QGraphicsItems на pipes напрямую — badge нужно позиционировать относительно pipe midpoint вручную
- wire.metrics IPC-команда может не существовать в framework — Task 1.2 реализует fire-and-forget с graceful degradation
- Количество displays может быть 0 — DisplayTargetNode не создаётся если SECTION_DISPLAYS пуст

---

## Задачи

### Task 1.1 — WireMetrics dataclass + сигнал metrics_changed

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Добавить dataclass WireMetrics и сигнал metrics_changed в WireDataBridge для передачи fps/latency/buffer_fill в GUI.

**Context:** Сейчас WireDataBridge содержит только статусы (WireStatus). Для overlay и dashboard нужны количественные метрики. Dataclass отделяет метрики от статусов — два независимых сигнала.

**Files:**
- `multiprocess_prototype/frontend/bridges/wire_data_bridge.py` — добавить WireMetrics, _wire_metrics dict, сигнал metrics_changed(dict)

**Steps:**
1. Добавить `@dataclass` класс `WireMetrics` с полями: `fps: float = 0.0`, `latency_ms: float = 0.0`, `buffer_fill: float = 0.0` (0.0-1.0).
2. Добавить в WireDataBridge: `metrics_changed = Signal(dict)` — payload: `{wire_key: WireMetrics}`.
3. Добавить `_wire_metrics: dict[str, WireMetrics] = {}`.
4. Добавить публичный метод `get_metrics(wire_key: str) -> WireMetrics` (возвращает дефолтный WireMetrics если ключ неизвестен).
5. Добавить публичный метод `get_all_metrics() -> dict[str, WireMetrics]` (копия).
6. Добавить метод `on_metrics_received(data: dict) -> None` — парсит dict `{wire_key: {fps, latency_ms, buffer_fill}}`, обновляет `_wire_metrics`, эмитит `metrics_changed`.
7. Добавить `WireMetrics` в `__all__`.

**Acceptance criteria:**
- [ ] `from multiprocess_prototype.frontend.bridges.wire_data_bridge import WireMetrics` работает
- [ ] `WireDataBridge().get_metrics("x")` возвращает WireMetrics с нулями
- [ ] `on_metrics_received({"w1": {"fps": 30.0, "latency_ms": 5.0, "buffer_fill": 0.5}})` эмитит `metrics_changed`
- [ ] Unit-тест: создание bridge, on_metrics_received → сигнал эмитирован с правильным payload

**Out of scope:** реальный IPC (fire-and-forget отправка команды — Task 1.2), GUI-виджеты.

**Edge cases:**
- Пустой data dict → не эмитить сигнал
- Отсутствующие поля в nested dict → использовать 0.0 как default
- wire_key в metrics, но не в statuses → допустимо (метрики могут приходить раньше статусов)

---

### Task 1.2 — Polling метрик через wire.metrics команду

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Расширить _poll_statuses в WireDataBridge: дополнительно отправлять fire-and-forget запрос wire.metrics и обрабатывать ответ.

**Context:** Метрики собираются runtime (StatsManager/LatencyTracker) и доступны через IPC-команду. WireDataBridge уже отправляет wire.status — аналогично добавляем wire.metrics.

**Files:**
- `multiprocess_prototype/frontend/bridges/wire_data_bridge.py` — расширить `_poll_statuses()`, добавить `_poll_metrics()`

**Steps:**
1. Добавить отдельный QTimer `_metrics_timer` с интервалом 1000 мс (метрики обновляются чаще статусов).
2. Добавить слот `_poll_metrics()`: если `self._cmd is not None` — отправить `self._cmd.send("process.command", data={"cmd": "wire.metrics"})`. Fire-and-forget, try/except с логированием.
3. В `start_monitoring()` — запускать оба таймера. В `stop_monitoring()` — останавливать оба.
4. Добавить публичный метод `set_metrics_interval(ms: int)` для настройки интервала polling.

**Acceptance criteria:**
- [ ] При `start_monitoring()` запускаются два таймера (statuses 2000ms, metrics 1000ms)
- [ ] При `stop_monitoring()` оба таймера остановлены
- [ ] `_poll_metrics()` не падает при `_cmd is None`
- [ ] Unit-тест: mock command_handler, start_monitoring, проверить что send вызван для wire.metrics

**Out of scope:** реальная реализация wire.metrics на стороне ProcessManager (это framework задача).

**Dependencies:** Task 1.1

---

### Task 2.1 — WireMetricsBadge — QGraphicsItem overlay на pipe

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать QGraphicsItem-виджет (badge) для отображения fps/latency/buffer_fill рядом с pipe на канвасе.

**Context:** Паттерн из InspectorNodeItem (pipeline_tab) — QGraphicsPixmapItem overlay как child. Но для pipe (QGraphicsPathItem) используем отдельный QGraphicsRectItem с текстом, позиционируемый в midpoint pipe. Badge рисует компактную плашку "30fps | 5ms | 50%".

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/wire_metrics_badge.py` — создать новый файл
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/__init__.py` — экспорт

**Steps:**
1. Создать класс `WireMetricsBadge(QGraphicsRectItem)`:
   - Конструктор: `__init__(self, parent: QGraphicsItem | None = None)` — задать Z-value выше pipe (Z+10), полупрозрачный фон (rgba 40,40,40,200), скруглённые углы.
   - Метод `update_metrics(fps: float, latency_ms: float, buffer_fill: float)` — обновить текст и перерисовать.
   - Метод `update_position(pipe_item: QGraphicsPathItem)` — вычислить midpoint path и разместить badge.
   - Размер badge: авто по тексту (QFontMetrics), padding 4px.
   - Текст формат: `"{fps:.0f}fps | {latency_ms:.1f}ms | {buffer_fill*100:.0f}%"`.
   - Скрывать badge если все метрики == 0.
2. Переопределить `paint()` — рисовать прямоугольник с текстом (QFont size 8px, цвет #cccccc).
3. Добавить метод `set_visible_threshold(min_fps: float = 0.1)` — badge скрывается если fps < threshold (wire неактивен).

**Acceptance criteria:**
- [ ] `WireMetricsBadge()` создаётся без ошибок
- [ ] `update_metrics(30, 5.2, 0.5)` → текст содержит "30fps"
- [ ] `update_position(mock_pipe)` позиционирует badge в midpoint пути pipe
- [ ] Badge скрыт при fps=0, latency=0, buffer_fill=0
- [ ] Unit-тест: создание badge, update_metrics, проверка видимости

**Out of scope:** анимация, sparkline-графики, tooltip с историей.

**Edge cases:**
- pipe_item без path (пустой QPainterPath) → badge в (0,0), setVisible(False)
- Очень длинный текст (latency > 1000ms) → badge расширяется по ширине

---

### Task 2.2 — Интеграция badge в PluginGraphAdapter

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Связать WireMetricsBadge с pipes на канвасе: создавать badge для каждого pipe, обновлять при metrics_changed.

**Context:** PluginGraphAdapter уже имеет `_wire_key_to_pipe` маппинг и метод `update_wire_colors`. Нужен аналогичный `update_wire_metrics` + маппинг wire_key → badge. Badge — child item pipe.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/plugin_graph_adapter.py` — добавить _wire_key_to_badge, update_wire_metrics(), _rebuild_badges()
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/widget.py` — подключить metrics_changed к adapter

**Steps:**
1. В PluginGraphAdapter добавить `_wire_key_to_badge: dict[str, WireMetricsBadge] = {}`.
2. В `_rebuild_pipe_map()` после построения маппинга pipe — создавать WireMetricsBadge для каждого pipe, привязывать как child QGraphicsItem (setParentItem), сохранять в `_wire_key_to_badge`. Начальное состояние — hidden.
3. Добавить публичный метод `update_wire_metrics(metrics: dict[str, Any]) -> None`:
   - Для каждого wire_key в metrics: найти badge в `_wire_key_to_badge`, вызвать `badge.update_metrics(...)` и `badge.update_position(pipe)`.
4. В `load_scene()` — очистить `_wire_key_to_badge` (badge удаляются вместе с pipe при clear сцены).
5. В ConstructorTabWidget: подключить `self._wire_bridge.metrics_changed.connect(self._on_wire_metrics_changed)`.
6. Добавить слот `_on_wire_metrics_changed(metrics: dict)` → вызвать `self._adapter.update_wire_metrics(metrics)`.

**Acceptance criteria:**
- [ ] После load_scene() для каждого wire создан WireMetricsBadge (скрытый)
- [ ] metrics_changed с данными fps>0 → badge становится видимым
- [ ] Badge позиционирован в midpoint pipe
- [ ] При полной перезагрузке канваса (refresh_from_topology) badges пересоздаются
- [ ] Unit-тест: mock graph, load_scene, update_wire_metrics → badge visible

**Out of scope:** toggle visibility (кнопка "показать/скрыть метрики" — будущее), анимация.

**Dependencies:** Task 1.1, Task 2.1

---

### Task 3.1 — DisplayTargetNode — кастомная нода канваса

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать DisplayTargetNode — визуальную ноду на канвасе конструктора, представляющую display-окно. Wire к display = назначение потока на экран.

**Context:** Паттерн — ShmRouteNode (кастомная нода с NodeItem, paint override для body). DisplayTargetNode: один входной порт "frame", read-only body с именем display и fps_limit. Визуально отличается цветом (#3a5a3a — зеленоватый).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/display_target_node.py` — создать
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/__init__.py` — экспорт

**Steps:**
1. Создать `DisplayNodeItem(NodeItem)`:
   - `__init__`: min_width=140, min_height=60, фоновый цвет #3a5a3a (зеленоватый).
   - `set_display_info(name: str, fps_limit: int)` — сохранить для paint.
   - `paint()`: super().paint() + рисуем строки "Display" (зелёный текст) и "{name} @ {fps_limit}fps".
2. Создать `DisplayTargetNode(BaseNode)`:
   - `__identifier__ = "constructor.nodes"`, `NODE_NAME = "DisplayTargetNode"`.
   - `__init__`: use DisplayNodeItem, add_input("frame", multi_input=False).
   - `set_display_data(display_key: str, name: str, fps_limit: int)` — сохранить property "display_key", "display_name", обновить DisplayNodeItem.
   - Property: `display_key -> str`.
3. Константа `DISPLAY_NODE_TYPE = "constructor.nodes.DisplayTargetNode"`.

**Acceptance criteria:**
- [ ] `graph.register_node(DisplayTargetNode)` + `graph.create_node(DISPLAY_NODE_TYPE)` — работает
- [ ] Нода имеет 1 входной порт "frame"
- [ ] `set_display_data("win_0", "Main", 30)` обновляет body text
- [ ] Unit-тест: создание ноды, set_display_data, проверка properties

**Out of scope:** wire validation (Task 3.2), обновление при изменении SECTION_DISPLAYS runtime.

**Edge cases:**
- fps_limit=0 → отображать "unlimited"
- Пустое имя → отображать display_key

---

### Task 3.2 — Генерация display-нод из SECTION_DISPLAYS + wire assignment

**Level:** Senior (Opus, normal)
**Assignee:** teamlead
**Goal:** Интегрировать DisplayTargetNode в PluginGraphAdapter: генерировать display-ноды из текущих displays в topology, при wire-connect к display — создавать assignment (wire с target "display.{display_key}.frame").

**Context:** GraphBuilder.build() создаёт process-ноды и route-ноды. Нужно добавить display-ноды. При connect pipe к display.in — создать wire с target формата "ui_process.{display_key}.frame". Также подписка на SECTION_DISPLAYS — при добавлении/удалении display перестроить ноды.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/graph_builder.py` — добавить создание display-нод в build()
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/plugin_graph_adapter.py` — маппинг display nodes, обработка connect к display
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/widget.py` — подписка на SECTION_DISPLAYS, register_node(DisplayTargetNode)

**Steps:**
1. В `widget.py` `_init_canvas()`: добавить `self._graph.register_node(DisplayTargetNode)`.
2. В `widget.py` `_subscribe_to_topology()`: подписаться на `SECTION_DISPLAYS` → `_on_displays_changed` (rebuild канваса).
3. В `graph_builder.py` `build()`: после создания process-нод — прочитать displays из topology_data, для каждого display создать DisplayTargetNode, вызвать `set_display_data(...)`, позиционировать справа от process-нод. Вернуть display_nodes в результате (расширить return).
4. В `plugin_graph_adapter.py`:
   - Добавить `_display_nodes: dict[str, DisplayTargetNode] = {}`.
   - В `load_scene()`: сохранить display_nodes из builder.
   - В `_on_port_connected()`: если target_qt_node — DisplayTargetNode, формировать target_addr как `"ui_process.{display_key}.frame"` и создавать wire через wire_model. Эмитить wire_selected для правой панели.
   - В `_on_node_selection_changed()`: если выбрана DisplayTargetNode — пока эмитить selection_cleared (display node не имеет процессной панели).
5. Обработать disconnect от display аналогично стандартному disconnect.

**Acceptance criteria:**
- [ ] При наличии displays в topology — display-ноды появляются на канвасе
- [ ] Wire от process port → display.frame создаёт wire в модели с target "ui_process.{key}.frame"
- [ ] Disconnect от display удаляет wire
- [ ] При изменении SECTION_DISPLAYS (добавление display) — канвас перестраивается
- [ ] При пустом SECTION_DISPLAYS — display-нод нет (graceful)
- [ ] Unit-тест: build с displays → display nodes created, connect → wire created

**Out of scope:** drag display node для изменения позиции (layout фиксирован), display-specific правая панель.

**Dependencies:** Task 3.1

**Edge cases:**
- Display с пустым source_ref (ещё не назначен) → нода на канвасе есть, wire нет
- Несколько wire к одному display → только последний wire валиден (replace)
- Wire от ShmRouteNode → display → должен работать через route.out_N

---

### Task 4.1 — QComboBox display_target в WireInspectorPanel

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Добавить QComboBox для быстрого назначения wire на display прямо в WireInspectorPanel (альтернатива drag-to-display).

**Context:** WireInspectorPanel уже показывает source/target/transport/description. Добавляем combo "Display target" со списком display из topology. При выборе — эмитим wire_changed с `{"display_target": "win_0"}`. ConstructorTabWidget обрабатывает это: обновляет wire.target и source_ref в DisplayDefinition.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/panels/wire_inspector.py` — добавить QComboBox
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/widget.py` — обработка display_target в _on_wire_panel_changed

**Steps:**
1. В WireInspectorPanel._init_ui() после строки "description":
   - Добавить разделитель QFrame (HLine).
   - Добавить `self._display_combo = QComboBox(self)` с placeholder "(не назначен)".
   - `form.addRow("Display:", self._display_combo)`.
2. Добавить публичный метод `set_available_displays(displays: list[dict])` — заполняет combo items из списка `[{"key": "win_0", "name": "Main"}]`. Первый item — "(нет)" с userData=None.
3. В `_connect_signals()`: подключить `self._display_combo.currentIndexChanged.connect(self._on_display_changed)`.
4. В `_on_display_changed(index: int)` — получить userData (display_key или None), эмитить `wire_changed(wire_key, {"display_target": display_key})`.
5. В `show_wire()`: blockSignals + выбрать текущий display из wire_data.get("display_target").
6. В `clear()`: сбросить combo на index 0.
7. В ConstructorTabWidget: при показе WireInspectorPanel (в `_on_wire_selected`) — вызвать `self._wire_panel.set_available_displays(...)` с данными из topology_editor displays.
8. В `_on_wire_panel_changed`: если changed_fields содержит "display_target" — обновить DisplayDefinition.source_ref через displays_section.

**Acceptance criteria:**
- [ ] QComboBox "Display:" виден в WireInspectorPanel
- [ ] Список содержит "(нет)" + все displays из topology
- [ ] Выбор display → wire_changed эмитирован с display_target
- [ ] show_wire() с wire_data["display_target"]="win_0" → combo выбирает правильный item
- [ ] Unit-тест: set_available_displays → combo count, выбор → signal

**Out of scope:** Обратная синхронизация (display → wire panel). Валидация совместимости порта.

**Dependencies:** Task 3.2 (wire model знает про display_target)

---

### Task 5.1 — ShmDashboardPanel — страница index 3 в QStackedWidget

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать ShmDashboardPanel — read-only панель мониторинга SHM-буферов с QProgressBar для каждого wire.

**Context:** Правая панель — QStackedWidget (0:placeholder, 1:process, 2:wire). Добавляем страницу 3: SHM dashboard. Показывает все wire-каналы с их buffer_fill как QProgressBar + fps/latency текстом. Обновляется из metrics_changed.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/panels/shm_dashboard_panel.py` — создать
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/panels/__init__.py` — экспорт

**Steps:**
1. Создать `ShmDashboardPanel(QWidget)`:
   - Layout: QVBoxLayout с заголовком "SHM Dashboard" + QScrollArea с вертикальным списком wire-виджетов.
   - Внутренний виджет-строка: `_WireMetricsRow(QWidget)` — QLabel(wire_key), QProgressBar(buffer_fill 0-100%), QLabel("30fps, 5ms").
2. Публичный метод `update_metrics(metrics: dict[str, Any])`:
   - metrics: `{wire_key: WireMetrics}` или `{wire_key: {"fps": ..., "latency_ms": ..., "buffer_fill": ...}}`.
   - Для каждого wire_key: если строка есть — обновить, если нет — создать новую строку.
3. Публичный метод `clear()` — удалить все строки.
4. QProgressBar:
   - value = int(buffer_fill * 100)
   - Цвет: зелёный (0-60%), жёлтый (60-85%), красный (85-100%) — через stylesheet.
5. Строки сортируются по wire_key (алфавитно).

**Acceptance criteria:**
- [ ] `ShmDashboardPanel()` создаётся без ошибок
- [ ] `update_metrics({"w1": {"fps": 30, "latency_ms": 5, "buffer_fill": 0.7}})` → строка с прогресс-баром 70%
- [ ] При buffer_fill > 0.85 → красный progressbar
- [ ] `clear()` удаляет все строки
- [ ] Повторный `update_metrics` с тем же wire_key — обновляет существующую строку (не дублирует)
- [ ] Unit-тест: создание, update_metrics, проверка widget count и progressbar value

**Out of scope:** Исторические графики (sparkline), группировка по процессам, экспорт метрик.

**Edge cases:**
- 0 wire_keys → пустая панель с текстом "Нет активных wire-каналов"
- buffer_fill > 1.0 → clamp к 100%
- Удалённый wire (был в метриках, больше нет) → строка остаётся greyed-out до clear()

---

### Task 5.2 — Интеграция ShmDashboardPanel в ConstructorTabWidget

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Добавить ShmDashboardPanel как страницу index 3 в QStackedWidget + кнопку "SHM Dashboard" в toolbar для переключения.

**Context:** QStackedWidget: 0=placeholder, 1=process, 2=wire. Добавляем 3=dashboard. Кнопка-toggle в toolbar. Dashboard обновляется из metrics_changed. Показывается вместо placeholder при нажатии кнопки.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/widget.py` — добавить страницу, кнопку, обработчик

**Steps:**
1. Импорт `ShmDashboardPanel` из panels.
2. В `_create_right_panel()`: после добавления WireInspectorPanel (index 2) — создать `self._shm_dashboard = ShmDashboardPanel(self)`, `self._stack.addWidget(self._shm_dashboard)` → index 3.
3. Добавить константу `_PAGE_DASHBOARD = 3`.
4. В `_create_toolbar()`: добавить QPushButton "SHM" (toggle-стиль, checkable). При checked — показать dashboard (index 3). При unchecked — вернуть на текущую "логическую" страницу (placeholder/process/wire).
5. В `_on_wire_metrics_changed(metrics)`: дополнительно вызвать `self._shm_dashboard.update_metrics(metrics)`.
6. В `_on_selection_cleared()` — если dashboard-кнопка не нажата → placeholder. Если нажата → dashboard.
7. При load_scene / refresh → `self._shm_dashboard.clear()`.

**Acceptance criteria:**
- [ ] Кнопка "SHM" в toolbar — checkable
- [ ] При нажатии SHM → правая панель показывает dashboard (index 3)
- [ ] metrics_changed → dashboard обновлён
- [ ] При снятии кнопки SHM → возврат к обычному поведению (selection-based pages)
- [ ] Unit-тест: нажатие кнопки → currentIndex == 3, metrics → dashboard.update_metrics вызван

**Out of scope:** Автоматическое переключение на dashboard при start_monitoring. Закрепление dashboard как split-view.

**Dependencies:** Task 5.1, Task 1.1

---

## Summary

| Task | Level | Assignee | Estimated files | Dependencies |
|------|-------|----------|-----------------|--------------|
| 1.1 | Middle | developer | 1 | - |
| 1.2 | Middle | developer | 1 | 1.1 |
| 2.1 | Middle+ | developer | 2 | - |
| 2.2 | Middle+ | developer | 2 | 1.1, 2.1 |
| 3.1 | Middle+ | developer | 2 | - |
| 3.2 | Senior | teamlead | 3 | 3.1 |
| 4.1 | Middle | developer | 2 | 3.2 |
| 5.1 | Middle+ | developer | 2 | - |
| 5.2 | Middle | developer | 1 | 5.1, 1.1 |

**Параллельные потоки:**
- Tasks 1.1, 2.1, 3.1, 5.1 — могут начинаться одновременно (нет зависимостей)
- Tasks 1.2, 2.2, 3.2 — второй уровень (после фундамента)
- Tasks 4.1, 5.2 — финальная интеграция
