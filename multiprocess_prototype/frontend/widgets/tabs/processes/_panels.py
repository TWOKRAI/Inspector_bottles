# -*- coding: utf-8 -*-
"""Композитные content-панели для ProcessesTab.

AllProcessesPanel — для ключа ALL_PROCESSES_KEY: health-панель sticky-сверху +
внутренний QStackedWidget с Cards (группы EntityCard по категориям) и Table
(QTableWidget со всеми процессами).

SingleProcessPanel — для имени одного процесса: внутренний QStackedWidget с
Cards (детальная EntityCard) и Table (key-value метрики).

Обе панели сами подписываются на свои bindings (StateStore) в __init__.
Каждая знает, как переключаться между Cards/Table через ``set_view_mode``.

Task E.2: панели принимают ``bindings`` (GuiStateBindings) напрямую вместо
``ctx``. bindings — live runtime state, не покрыт AppServices Protocol'ами
(Q4 Phase D, ревизия Phase G).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.process_module.heartbeat.telemetry import GATED_METRICS
from multiprocess_framework.modules.frontend_module.widgets.telemetry_chart import (
    SeriesSpec,
    TelemetryChart,
)
from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner
from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode
from multiprocess_prototype.frontend.state.telemetry_history import (
    TelemetryHistorySource,
    make_history_source,
)
from multiprocess_prototype.frontend.widgets.primitives import (
    CardAction,
    EntityCard,
)

from ._system_dashboard import SystemDashboardSection
from ._telemetry_controls import TelemetryControlsSection
from .widgets import CreateWorkerDialog, ProcessCard, WorkerTable

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
    from multiprocess_framework.modules.frontend_module.state import TelemetryViewModel

    from .presenter import ProcessesPresenter

_logger = logging.getLogger(__name__)

# Колонки таблицы «Все процессы»
_ALL_TABLE_COLUMNS = ["Имя", "Категория", "Статус", "Циклов/с", "Плагины"]

# Колонки key-value таблицы одного процесса
_DETAIL_TABLE_COLUMNS = ["Параметр", "Значение"]

# Колонки таблицы пер-сегментной трассировки кадра (frame-trace)
_TRACE_TABLE_COLUMNS = ["Участок", "Тип", "Среднее, мс"]

# Колонки мини-таблицы сводки ветвей fan-in (trace_branches)
_BRANCHES_TABLE_COLUMNS = ["Ветвь", "total_ms, мс", "Спанов"]

# Порядок групп карточек на странице «Все процессы»
_CATEGORY_ORDER = [
    "source",
    "processing",
    "rendering",
    "output",
    "control",
    "service",
    "utility",
]


# QSS подсветки выбранной карточки/строки (process-scope кнопок).
_SELECTED_CARD_QSS = "QFrame#EntityCard { border: 2px solid #2563eb; }"

# Дебаунс каскада обнаружения рантайм-воркеров (Task 0.4, часть A): N
# обнаружений подряд коалесцируются в один _refresh_workers.
_WORKER_DISCOVERY_DEBOUNCE_MS = 50

# Диапазоны графика телеметрии (Ф2, Task 2.2): ключ → (подпись кнопки, окно в
# секундах). "10m" — единственный ring-buffer-диапазон (без похода в БД, см.
# _refresh_graph_from_ring); "1h"/"1d" читают TelemetryHistorySource.
_GRAPH_RANGES: tuple[tuple[str, str, float], ...] = (
    ("10m", "10 мин", 600.0),
    ("1h", "1 час", 3600.0),
    ("1d", "1 день", 86400.0),
)
_DEFAULT_GRAPH_RANGE = "10m"

# Шаблон секции «Телеметрия» (Ф4.1): RU-метки и дефолтные интервалы для метрик
# framework GATED_METRICS. Ключи — те же метрики; отсутствующий ключ → сам ключ /
# общий дефолт. Значения — app-specific presentation (framework даёт лишь список).
_TELEMETRY_METRIC_LABELS: dict[str, str] = {
    "fps": "FPS (кадров/с)",
    "latency_ms": "Задержка, мс",
    "effective_hz": "Частота цикла, Гц",
    "cycle_duration_ms": "Длит. цикла, мс",
    "shm": "SHM",
}
_TELEMETRY_METRIC_DEFAULTS: dict[str, float] = {
    "fps": 1.0,
    "latency_ms": 1.0,
    "effective_hz": 1.0,
    "cycle_duration_ms": 1.0,
    "shm": 2.0,
}
# Верхняя граница точек, тащимых из БД на один запрос графика (даунсемпл — Task 2.1).
_GRAPH_HISTORY_MAX_POINTS = 300


def _format_uptime(value: object) -> str:
    """Секунды → «MM:SS» / «H:MM:SS» для метрики uptime карточки процесса."""
    if not isinstance(value, (int, float)):
        return "—"
    total = int(value)
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _make_vm_setter(
    widget: QWidget,
    prop: str,
    formatter: Callable[[Any], Any] | None = None,
) -> Callable[[Any], None]:
    """Собрать setter «значение → виджет» для VM-режима (Task 1.3).

    Повторяет применение значения из ``GuiStateBindings._apply_to_widget``: тот же
    formatter, тот же вызов setter (``text`` → ``setText(str(...))``,
    ``set_state`` → ``set_state(...)``, прочее — ``getattr(widget, prop)(...)``).

    Отличие от legacy НА УДАЛЕНИИ узла (``deleted=True`` → в батче ``updated``
    приходит ``(path, None)``): legacy-путь без явного ``reset`` виджет НЕ трогает
    (оставляет последнее значение), VM-путь прогоняет ``None`` через formatter →
    метка показывает «—», индикатор — состояние «unknown». Это НАМЕРЕННО: для
    исчезнувшего процесса «нет данных» корректнее застрявшего старого значения.
    Расхождение проявляется лишь на реальном сносе узла топологии (редко, обычно
    с перестройкой панели). Зафиксировано тестом ``test_*deleted*`` в
    ``test_telemetry_vm_panels.py``.

    Замыкает виджет сильной ссылкой — живёт ровно столько, сколько панель-владелец
    (её dict сеттеров), затем GC вместе с ней; сигнал ``updated`` авто-отключается
    Qt при уничтожении панели-получателя.
    """

    def _setter(value: Any) -> None:
        display = formatter(value) if formatter is not None else value
        if prop == "text":
            widget.setText(str(display))  # type: ignore[attr-defined]
        elif prop == "set_state":
            widget.set_state(display)  # type: ignore[attr-defined]
        else:
            method = getattr(widget, prop, None)
            if callable(method):
                method(display)

    return _setter


class AllProcessesPanel(QWidget):
    """Панель для ALL_PROCESSES_KEY: health + inner-стек Cards/Table."""

    card_action_requested = Signal(str, str)  # (entity_id, action_id)
    process_selected = Signal(object)  # имя выбранного процесса (str) | None

    def __init__(
        self,
        presenter: "ProcessesPresenter",
        bindings: "GuiStateBindings | None",
        *,
        telemetry: "TelemetryViewModel | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._presenter = presenter
        self._bindings = bindings
        # Ф1 (gui-telemetry-read-model 1.3): локальный read-model телеметрии.
        # VM-режим предпочтителен (один слот на ``updated`` вместо N bind);
        # None → fallback на bindings-путь (существующие тесты/оболочки без VM).
        self._telemetry = telemetry
        # Карта VM-режима: точный путь → setter(value). Заполняется в
        # _connect_telemetry_vm; читается _apply_telemetry_items.
        self._vm_setters: dict[str, Callable[[Any], None]] = {}
        # Fan-out'ы VM-режима: точный путь → callback(path, value) (trace-таблицы).
        self._vm_fanouts: dict[str, Callable[[str, Any], None]] = {}
        self._cards: dict[str, EntityCard] = {}
        self._selected_card_name: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # Health-панель sticky-сверху (до inner_stack).
        self._build_health_panel(outer)

        # Дашборд телеметрии (Ф2): многосерийный график (серия на процесс),
        # легенда-тумблеры, zoom/pan — PyQtGraph через generic TelemetryChart.
        self._build_dashboard(outer)

        # Разбивка кадра по участкам (frame-trace) — под health, скрыта пока
        # нет данных (заполняется только при INSPECTOR_FRAME_TRACE=1).
        self._build_trace_panel(outer)

        # Внутренний стек: Cards (0) / Table (1).
        self._inner_stack = QStackedWidget()
        self._inner_stack.addWidget(self._build_cards_page())
        self._inner_stack.addWidget(self._build_table_page())
        outer.addWidget(self._inner_stack, stretch=1)

        # Bindings подписываемся один раз при создании.
        self._connect_bindings()

    # ------------------------------------------------------------------ #
    #  Build                                                               #
    # ------------------------------------------------------------------ #

    def _build_health_panel(self, parent_layout: QVBoxLayout) -> None:
        self._health_panel = QGroupBox("Здоровье системы")
        health_layout = QHBoxLayout(self._health_panel)
        health_layout.setContentsMargins(8, 4, 8, 4)

        summary = self._presenter.get_health_summary()

        self._lbl_total = QLabel(f"Всего: {summary['total']}")
        self._lbl_active = QLabel("Активно: 0")
        self._lbl_wires = QLabel("Обрывы связей: 0")
        self._lbl_wires.setTextFormat(Qt.TextFormat.RichText)
        self._lbl_avg_fps = QLabel("Средняя частота: —")
        # Сквозной FPS цепочки: сколько кадров/с проходят через ВСЕ процессы и
        # доходят до дисплея (выходная пропускная способность пайплайна целиком).
        self._lbl_chain_fps = QLabel("FPS цепочки: —")
        # Сквозная задержка: время одного кадра capture→display (через все процессы).
        self._lbl_chain_latency = QLabel("Задержка цепочки: —")

        health_layout.addWidget(self._lbl_total)
        health_layout.addWidget(self._lbl_active)
        health_layout.addWidget(self._lbl_wires)
        health_layout.addWidget(self._lbl_avg_fps)
        health_layout.addWidget(self._lbl_chain_fps)
        health_layout.addWidget(self._lbl_chain_latency)
        health_layout.addStretch()

        parent_layout.addWidget(self._health_panel)

    def _build_dashboard(self, parent_layout: QVBoxLayout) -> None:
        """Собрать системный дашборд: серия на процесс, live из read-model (Ф2).

        Серии — по списку процессов топологии (конструкторно). Обновление гонится в
        :meth:`_apply_telemetry_items` при касании fps/latency-путей. VM=None (тесты
        без read-model) → дашборд без данных, но собирается (graceful).
        """
        names = [p.name for p in self._presenter.get_processes()]
        self._dashboard = SystemDashboardSection(names, self._telemetry)
        parent_layout.addWidget(self._dashboard)

    def _build_trace_panel(self, parent_layout: QVBoxLayout) -> None:
        """Таблица пер-сегментной разбивки кадра (transport + process спаны) +
        компактный блок ветвей fan-in (trace_branches).

        Скрыта по умолчанию: данные приходят только при INSPECTOR_FRAME_TRACE=1.
        Показывается при первой непустой публикации system.trace_segments.
        Блок ветвей скрыт дополнительно — показывается только при непустом
        system.trace_branches (нелинейный пайплайн с fan-in).
        """
        self._trace_box = QGroupBox("Разбивка кадра по участкам")
        box_layout = QVBoxLayout(self._trace_box)
        box_layout.setContentsMargins(8, 4, 8, 4)
        box_layout.setSpacing(4)

        # Label «critical path» над таблицей сегментов (поясняет семантику).
        self._trace_critical_label = QLabel("Critical path (самый медленный путь кадра):")
        self._trace_critical_label.setObjectName("TraceCriticalLabel")
        box_layout.addWidget(self._trace_critical_label)

        self._trace_table = QTableWidget(0, len(_TRACE_TABLE_COLUMNS))
        self._trace_table.setHorizontalHeaderLabels(_TRACE_TABLE_COLUMNS)
        self._trace_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._trace_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        h = self._trace_table.horizontalHeader()
        if h:
            h.setStretchLastSection(True)
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # Компактная высота: трасса обычно 5–8 участков.
        self._trace_table.setMaximumHeight(220)
        box_layout.addWidget(self._trace_table)

        # Блок ветвей fan-in: скрыт пока нет trace_branches (линейный пайплайн).
        self._branches_label = QLabel("Ветви fan-in:")
        self._branches_label.setObjectName("TraceBranchesLabel")

        self._branches_table = QTableWidget(0, len(_BRANCHES_TABLE_COLUMNS))
        self._branches_table.setHorizontalHeaderLabels(_BRANCHES_TABLE_COLUMNS)
        self._branches_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._branches_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        bh = self._branches_table.horizontalHeader()
        if bh:
            bh.setStretchLastSection(True)
            bh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # Мини-таблица: 3–5 ветвей обычно.
        self._branches_table.setMaximumHeight(140)

        box_layout.addWidget(self._branches_label)
        box_layout.addWidget(self._branches_table)

        # Блок ветвей скрыт до первых данных.
        self._branches_label.setVisible(False)
        self._branches_table.setVisible(False)

        self._trace_box.setVisible(False)
        parent_layout.addWidget(self._trace_box)

    def _on_trace_segments(self, _path: str, value: object) -> None:
        """Fan-out callback: обновить таблицу разбивки кадра + строку «Итого».

        value — список {label, kind, ms} (среднее за период, порядок = ход кадра).
        Поддерживает kind=merge (merge @ node): отображается как «слияние».
        """
        if not isinstance(value, list) or not value:
            return
        rows = [s for s in value if isinstance(s, dict)]
        total = sum(s.get("ms", 0.0) for s in rows if isinstance(s.get("ms"), (int, float)))
        self._trace_table.setRowCount(len(rows) + 1)
        kind_ru = {"transport": "передача", "process": "обработка", "merge": "слияние"}
        for r, span in enumerate(rows):
            ms = span.get("ms")
            # ms=0 отображаем как «—» согласно ТЗ (edge case merge ms=0).
            if isinstance(ms, (int, float)) and ms > 0:
                ms_str = f"{ms:.2f}"
            else:
                ms_str = "—"
            self._trace_table.setItem(r, 0, QTableWidgetItem(str(span.get("label", "?"))))
            self._trace_table.setItem(r, 1, QTableWidgetItem(kind_ru.get(span.get("kind", ""), "")))
            self._trace_table.setItem(r, 2, QTableWidgetItem(ms_str))
        # Строка «Итого» — сквозная сумма средних по участкам.
        total_item = QTableWidgetItem("Итого")
        total_ms = QTableWidgetItem(f"{total:.2f}")
        self._trace_table.setItem(len(rows), 0, total_item)
        self._trace_table.setItem(len(rows), 1, QTableWidgetItem(""))
        self._trace_table.setItem(len(rows), 2, total_ms)
        self._trace_box.setVisible(True)

    def _on_trace_branches(self, _path: str, value: object) -> None:
        """Fan-out callback: обновить мини-таблицу ветвей fan-in.

        value — список {branch, total_ms, spans} (снимок из trace_branches
        последнего кадра нелинейного пайплайна). Пустой список / None → скрыть.
        """
        if not isinstance(value, list) or not value:
            self._branches_label.setVisible(False)
            self._branches_table.setVisible(False)
            return

        rows = [b for b in value if isinstance(b, dict)]
        if not rows:
            self._branches_label.setVisible(False)
            self._branches_table.setVisible(False)
            return

        self._branches_table.setRowCount(len(rows))
        for r, branch in enumerate(rows):
            name = str(branch.get("branch", "?"))
            total_ms = branch.get("total_ms")
            spans = branch.get("spans")
            # total_ms=0 → «—» (edge case).
            if isinstance(total_ms, (int, float)) and total_ms > 0:
                ms_str = f"{total_ms:.2f}"
            else:
                ms_str = "—"
            spans_str = str(spans) if isinstance(spans, int) else "—"
            self._branches_table.setItem(r, 0, QTableWidgetItem(name))
            self._branches_table.setItem(r, 1, QTableWidgetItem(ms_str))
            self._branches_table.setItem(r, 2, QTableWidgetItem(spans_str))

        self._branches_label.setVisible(True)
        self._branches_table.setVisible(True)

    def _build_cards_page(self) -> QWidget:
        """Cards-страница: контейнер с группами EntityCard по категориям.

        Без собственного QScrollArea — вертикальный overflow обрабатывает
        мастер-скролл ``DiffScrollTabLayout``. Иначе появлялся бы второй
        скроллбар внутри content-колонки.
        """
        self._cards_container = QWidget()
        self._all_scroll_layout = QVBoxLayout(self._cards_container)
        self._all_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._all_scroll_layout.addStretch()

        self._populate_cards()
        return self._cards_container

    def _build_table_page(self) -> QWidget:
        """Table-страница: QTableWidget со всеми процессами."""
        self._all_table = QTableWidget(0, len(_ALL_TABLE_COLUMNS))
        self._all_table.setHorizontalHeaderLabels(_ALL_TABLE_COLUMNS)
        self._all_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._all_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._all_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._all_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        h = self._all_table.horizontalHeader()
        if h:
            h.setStretchLastSection(True)
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        return self._all_table

    def _populate_cards(self) -> None:
        """Создать компактные EntityCard для всех процессов сгруппированно."""
        processes = self._presenter.get_processes()
        groups = self._presenter.group_by_category(processes)

        for cat in _CATEGORY_ORDER:
            procs = groups.get(cat, [])
            if not procs:
                continue

            group_box = QGroupBox(self._presenter.category_title(cat))
            group_layout = QVBoxLayout(group_box)
            group_layout.setContentsMargins(4, 4, 4, 4)

            for proc in procs:
                actions = [CardAction("start", "Запустить")]
                if not proc.protected:
                    actions.append(CardAction("stop", "Остановить"))
                actions.append(CardAction("restart", "Перезапустить"))
                card = EntityCard(
                    entity_id=proc.name,
                    title=proc.name,
                    actions=actions,
                )
                worker_count = len(self._presenter.get_workers(proc.name))
                card.set_metrics(
                    {
                        "Плагины": ", ".join(proc.plugins) or "—",
                        "Воркеров": str(worker_count),
                    }
                )
                card.set_status(proc.status)
                card.action_clicked.connect(self.card_action_requested)

                group_layout.addWidget(card)
                self._cards[proc.name] = card
                self._register_card_click(card)

            idx = self._all_scroll_layout.count() - 1
            self._all_scroll_layout.insertWidget(idx, group_box)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def set_view_mode(self, mode: ViewMode) -> None:
        """Переключить отображение Cards (0) / Table (1)."""
        if mode == ViewMode.TABLE:
            self._refresh_table()
            self._inner_stack.setCurrentIndex(1)
        else:
            self._inner_stack.setCurrentIndex(0)

    def selected_process(self) -> str | None:
        """Имя выбранной (карточкой/строкой) процесса или None."""
        return self._selected_card_name

    # ------------------------------------------------------------------ #
    #  Выбор процесса (карточка/строка) → process_selected               #
    # ------------------------------------------------------------------ #

    def _register_card_click(self, card: EntityCard) -> None:
        """Установить event-filter на карточку и её детей для перехвата клика.

        EntityCard — фреймворковый примитив без сигнала клика; не модифицируем
        его, а ловим MouseButtonPress через filter (клик по кнопке действия тоже
        выделяет карточку — это ожидаемо, кнопка при этом отрабатывает свой сигнал).
        """
        card.installEventFilter(self)
        for child in card.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 — Qt override
        if event.type() == QEvent.Type.MouseButtonPress:
            name = self._card_owner(obj)
            if name is not None:
                self._select_process(name)
        return super().eventFilter(obj, event)

    def _card_owner(self, obj: object) -> str | None:
        """Найти имя процесса по виджету (поднимаясь по родителям до карточки)."""
        widget = obj if isinstance(obj, QWidget) else None
        while widget is not None:
            for name, card in self._cards.items():
                if card is widget:
                    return name
            widget = widget.parentWidget()
        return None

    def _select_process(self, name: str) -> None:
        """Выделить процесс (карточку) и сообщить наружу."""
        self._selected_card_name = name
        for n, card in self._cards.items():
            card.setStyleSheet(_SELECTED_CARD_QSS if n == name else "")
        self.process_selected.emit(name)

    def _on_table_selection_changed(self) -> None:
        """Строка таблицы выбрана → синхронизировать выбор процесса."""
        items = self._all_table.selectedItems()
        if not items:
            return
        row = items[0].row()
        name_item = self._all_table.item(row, 0)
        if name_item is not None:
            self._selected_card_name = name_item.text()
            self.process_selected.emit(self._selected_card_name)

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _refresh_table(self) -> None:
        rows = self._presenter.get_table_rows()
        self._all_table.setRowCount(len(rows))
        for row_idx, row_data in enumerate(rows):
            for col_idx, col_name in enumerate(_ALL_TABLE_COLUMNS):
                self._all_table.setItem(
                    row_idx,
                    col_idx,
                    QTableWidgetItem(row_data.get(col_name, "")),
                )

    def _connect_bindings(self) -> None:
        """Подключить телеметрию карточек/health: VM-режим или bindings-fallback.

        VM-режим (Task 1.3) предпочтителен: один слот на ``updated`` вместо N
        точечных ``bind`` (0 серверных подписок из панели). Fallback на прежний
        ``bindings.bind``-путь — когда VM не подан (telemetry=None): часть тестов
        и оболочки без read-model.
        """
        # Плейсхолдеры метрик карточек — общие для обоих путей (создают QLabel'ы
        # «Циклов/с»/«Время цикла», к которым дальше цепляются setter'ы/binding'и).
        for card in self._cards.values():
            card.set_metrics({"Циклов/с": "—", "Время цикла": "—"})

        if self._telemetry is not None:
            self._connect_telemetry_vm()
        elif self._bindings is not None:
            self._connect_bindings_legacy()

    # --- VM-режим (Task 1.3) ------------------------------------------- #

    def _connect_telemetry_vm(self) -> None:
        """Собрать карту путей→setter, подписаться на ``updated`` одним слотом,
        первично наполнить из snapshot (late-binding)."""
        setters: dict[str, Callable[[Any], None]] = {}

        # Карточки: статус + Циклов/с + Время цикла.
        for name, card in self._cards.items():
            setters[f"processes.{name}.state.status"] = _make_vm_setter(card._indicator, "set_state")
            hz_label = card._metric_labels.get("Циклов/с")
            if hz_label is not None:
                setters[f"processes.{name}.state.fps"] = _make_vm_setter(
                    hz_label, "text", lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—"
                )
            cycle_label = card._metric_labels.get("Время цикла")
            if cycle_label is not None:
                setters[f"processes.{name}.state.latency_ms"] = _make_vm_setter(
                    cycle_label, "text", lambda v: f"{v:.1f} мс" if isinstance(v, (int, float)) else "—"
                )

        # Health-метки (те же formatter'ы, что в legacy — байт-в-байт).
        setters["system.health.active"] = _make_vm_setter(
            self._lbl_active, "text", lambda v: f"Активно: {v}" if isinstance(v, (int, float)) else "Активно: 0"
        )
        setters["system.health.broken_wires"] = _make_vm_setter(
            self._lbl_wires,
            "text",
            lambda v: (
                f"<span style='color: #dc2626;'>Обрывы связей: {v}</span>"
                if isinstance(v, (int, float)) and v > 0
                else "Обрывы связей: 0"
            ),
        )
        setters["system.health.avg_fps"] = _make_vm_setter(
            self._lbl_avg_fps,
            "text",
            lambda v: f"Средняя частота: {v:.1f}" if isinstance(v, (int, float)) else "Средняя частота: —",
        )
        setters["system.chain_fps"] = _make_vm_setter(
            self._lbl_chain_fps,
            "text",
            lambda v: f"FPS цепочки: {v:.1f}" if isinstance(v, (int, float)) else "FPS цепочки: —",
        )
        setters["system.chain_latency_ms"] = _make_vm_setter(
            self._lbl_chain_latency,
            "text",
            lambda v: f"Задержка цепочки: {v:.0f} ms" if isinstance(v, (int, float)) else "Задержка цепочки: —",
        )
        self._vm_setters = setters

        # Fan-out'ы (trace_segments/trace_branches) — точные пути, значение списком.
        self._vm_fanouts = {
            "system.trace_segments": self._on_trace_segments,
            "system.trace_branches": self._on_trace_branches,
        }

        self._telemetry.updated.connect(self._on_telemetry_batch)

        # Первичное наполнение из снимка (late-binding): панель, созданная ПОСЛЕ
        # публикации, сразу показывает актуальное. Границы поддеревьев по точке.
        initial = list(self._telemetry.snapshot("processes").items())
        initial += list(self._telemetry.snapshot("system").items())
        self._apply_telemetry_items(initial)

    def _on_telemetry_batch(self, batch: list[tuple[str, Any]]) -> None:
        """Слот на ``TelemetryViewModel.updated`` — один на панель (не по пути)."""
        self._apply_telemetry_items(batch)

    def _apply_telemetry_items(self, items: list[tuple[str, Any]]) -> None:
        """Применить пачку (path, value): setter карточки/health + trace-fan-out + дашборд."""
        dashboard_touched = False
        for path, value in items:
            setter = self._vm_setters.get(path)
            if setter is not None:
                try:
                    setter(value)
                except Exception as exc:  # виджет↔значение — не валим GUI (правило 5)
                    _logger.debug("telemetry-vm: setter failed on %s: %s", path, exc)
            fanout = self._vm_fanouts.get(path)
            if fanout is not None:
                try:
                    fanout(path, value)
                except Exception as exc:
                    _logger.debug("telemetry-vm: fan-out failed on %s: %s", path, exc)
            # Ф2: дашборд перечитывает ring-историю при касании метрик state.<metric>.
            if path.endswith(".state.fps") or path.endswith(".state.latency_ms"):
                dashboard_touched = True
        # Один refresh на батч (O(процессы×точки) из ring — дёшево, не per-путь).
        if dashboard_touched and hasattr(self, "_dashboard"):
            self._dashboard.refresh()

    # --- Fallback: прежний bindings-путь ------------------------------- #

    def _connect_bindings_legacy(self) -> None:
        """Прежний путь через GuiStateBindings (VM не подан). Полное удаление —
        Phase 3.1."""
        bindings = self._bindings
        assert bindings is not None

        # Карточки: статус + Циклов/с (частота, среднее за секунду) + Время цикла.
        for name, card in self._cards.items():
            bindings.bind(
                f"processes.{name}.state.status",
                card._indicator,
                "set_state",
            )
            hz_label = card._metric_labels.get("Циклов/с")
            if hz_label is not None:
                bindings.bind(
                    f"processes.{name}.state.fps",
                    hz_label,
                    "text",
                    formatter=lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
                )
            cycle_label = card._metric_labels.get("Время цикла")
            if cycle_label is not None:
                bindings.bind(
                    f"processes.{name}.state.latency_ms",
                    cycle_label,
                    "text",
                    formatter=lambda v: f"{v:.1f} мс" if isinstance(v, (int, float)) else "—",
                )

        # Health-метки.
        bindings.bind(
            "system.health.active",
            self._lbl_active,
            "text",
            formatter=lambda v: f"Активно: {v}" if isinstance(v, (int, float)) else "Активно: 0",
        )
        bindings.bind(
            "system.health.broken_wires",
            self._lbl_wires,
            "text",
            formatter=lambda v: (
                f"<span style='color: #dc2626;'>Обрывы связей: {v}</span>"
                if isinstance(v, (int, float)) and v > 0
                else "Обрывы связей: 0"
            ),
        )
        bindings.bind(
            "system.health.avg_fps",
            self._lbl_avg_fps,
            "text",
            formatter=lambda v: f"Средняя частота: {v:.1f}" if isinstance(v, (int, float)) else "Средняя частота: —",
        )
        # Сквозной FPS цепочки (кадров/с на выходе пайплайна, измеряется GUI по
        # прибытию кадров на дисплей; инъекция локальной state-дельты в _update_fps).
        bindings.bind(
            "system.chain_fps",
            self._lbl_chain_fps,
            "text",
            formatter=lambda v: f"FPS цепочки: {v:.1f}" if isinstance(v, (int, float)) else "FPS цепочки: —",
        )
        bindings.bind(
            "system.chain_latency_ms",
            self._lbl_chain_latency,
            "text",
            formatter=lambda v: (
                f"Задержка цепочки: {v:.0f} ms" if isinstance(v, (int, float)) else "Задержка цепочки: —"
            ),
        )
        # Пер-сегментная разбивка кадра (frame-trace) — fan-out: значение списком,
        # не привязывается к одному виджету. Заполняет таблицу _trace_table.
        bindings.bind_fanout("system.trace_segments", self._on_trace_segments, owner=self)
        # Сводка ветвей fan-in (нелинейный пайплайн) — fan-out: заполняет
        # мини-таблицу ветвей _branches_table. Скрыта при пустом/отсутствующем.
        bindings.bind_fanout("system.trace_branches", self._on_trace_branches, owner=self)


class SingleProcessPanel(QWidget):
    """Панель одного процесса: inner-стек детальной карточки и key-value таблицы."""

    card_action_requested = Signal(str, str)  # (entity_id, action_id)
    worker_selection_changed = Signal(object)  # worker_name (str) | None

    def __init__(
        self,
        presenter: "ProcessesPresenter",
        bindings: "GuiStateBindings | None",
        process_name: str,
        *,
        telemetry: "TelemetryViewModel | None" = None,
        history_source: "TelemetryHistorySource | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._presenter = presenter
        self._bindings = bindings
        # Ф1 (gui-telemetry-read-model 1.3): локальный read-model. VM-режим
        # предпочтителен; None → fallback на bindings-путь.
        self._telemetry = telemetry
        # Ф2 (gui-telemetry-read-model 2.1/2.2): read-сторона telemetry.db для
        # графика за час/день. Конструктор source — без I/O (только путь), None
        # → дефолтный источник под схему стока прототипа (env
        # INSPECTOR_TELEMETRY_DB / data/telemetry.db). Инъекция параметром — для
        # тестов (fake-источник).
        self._history_source = history_source if history_source is not None else make_history_source()
        # RequestRunner (P2 command-result-bridge) — гоняет list_range() на
        # worker-потоке QThreadPool, результат доставляется в main-thread
        # сигналом (см. модуль request_runner.py). Без него чтение БД в
        # main thread фризило бы GUI на время I/O (план запрещает это явно).
        self._history_runner = RequestRunner(self)
        self._graph_range: str = _DEFAULT_GRAPH_RANGE
        # Генерация запроса истории: инкрементируется на каждый submit; async-ответ
        # применяется, только если его генерация совпадает с текущей. Иначе быстрое
        # переключение диапазона (1ч→1д→10м) могло бы применить устаревший ответ
        # поверх актуального выбора (QThreadPool не гарантирует порядок завершения).
        self._graph_request_id = 0
        # Карты VM-режима: точный путь → setter(value). Статичные пути процесса
        # (_vm_setters) и пере-собираемые пути воркеров (_vm_worker_setters,
        # обновляются в _bind_worker_telemetry при каждом перестроении строк).
        self._vm_setters: dict[str, Callable[[Any], None]] = {}
        self._vm_worker_setters: dict[str, Callable[[Any], None]] = {}
        self._process_name = process_name
        # Рантайм-воркеры, обнаруженные из телеметрии (data_receiver,
        # pipeline_executor, source_producer_* — создаются в рантайме и в
        # конфиг-топологии отсутствуют). Подмешиваются в таблицу как read-only.
        self._runtime_workers: set[str] = set()
        # Дебаунс каскада обнаружения (Task 0.4, часть A): взведён ли уже
        # отложенный _flush_worker_refresh (коалесцирует N обнаружений в 1).
        self._worker_refresh_pending = False
        # Гвард от гонки: панель уничтожена до срабатывания таймера — не
        # трогать мёртвый виджет во _flush_worker_refresh / _on_history_ready.
        self._is_destroyed = False
        self.destroyed.connect(self._mark_destroyed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._inner_stack = QStackedWidget()
        self._inner_stack.addWidget(self._build_cards_page())
        self._inner_stack.addWidget(self._build_table_page())
        outer.addWidget(self._inner_stack, stretch=1)

        self._connect_bindings()

    # ------------------------------------------------------------------ #
    #  Build                                                               #
    # ------------------------------------------------------------------ #

    def _build_cards_page(self) -> QWidget:
        """Cards-страница: насыщенная ProcessCard + секция управления воркерами."""
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(8)

        proc = self._presenter.get_process_by_name(self._process_name)
        if proc is None:
            page_layout.addStretch()
            return page

        # ProcessCard сам скрывает stop/delete для protected.
        self._card = ProcessCard(
            entity_id=proc.name,
            title=proc.name,
            category=proc.category,
            protected=proc.protected,
        )
        self._card.set_status(proc.status)
        metrics = self._presenter.get_detail_metrics(self._process_name)
        self._card.set_metric("Циклов/с", metrics.get("Циклов/с", "—"))
        self._card.set_metric("PID", metrics.get("PID", "—"))
        self._card.set_metric("Uptime", metrics.get("Uptime", "—"))
        self._card.action_clicked.connect(self.card_action_requested)
        page_layout.addWidget(self._card)

        # Секция воркеров: компактная таблица (создание/удаление/старт/стоп — в
        # левой панели вкладки, worker-scope по выбранной строке).
        workers_box = QGroupBox("Воркеры")
        box_layout = QVBoxLayout(workers_box)
        box_layout.setContentsMargins(6, 6, 6, 6)
        self._worker_table = WorkerTable()
        self._worker_table.selection_changed.connect(self.worker_selection_changed)
        self._worker_table.changed.connect(self._on_worker_changed)
        box_layout.addWidget(self._worker_table)
        page_layout.addWidget(workers_box)

        # Секция графика (Ф2, Task 2.2): fps/latency процесса, переключатель
        # диапазона 10 мин / 1 час / 1 день.
        page_layout.addWidget(self._build_graph_box())

        # Секция управления телеметрией (Ф4.1): авто-строки контролов вкл/выкл +
        # частота по списку метрик GATED_METRICS (шаблон, не хардкод). Запись —
        # через command-result-bridge (RequestRunner), результат несёт caps.
        self._telemetry_controls = TelemetryControlsSection(
            self._process_name,
            list(GATED_METRICS),
            labels=_TELEMETRY_METRIC_LABELS,
            defaults=_TELEMETRY_METRIC_DEFAULTS,
            on_change=self._on_telemetry_change,
        )
        self._telemetry_runner = RequestRunner(self)
        page_layout.addWidget(self._telemetry_controls)

        # Карточка + таблица + график прижаты вверх, без растягивания на всю высоту.
        page_layout.addStretch(1)

        self._refresh_workers()
        # Late-binding: панель, созданная ПОСЛЕ публикации, показывает график
        # 10 мин сразу из ring-буфера VM (без ожидания следующего батча).
        self._refresh_graph_from_ring()

        # Fan-out: обнаруживать рантайм-воркеров из телеметрии и добавлять в
        # таблицу (их нет в конфиг-топологии get_workers()). В VM-режиме
        # обнаружение идёт из батч-слота (_apply_telemetry_items, discover=True),
        # bindings.bind_fanout нужен ТОЛЬКО в fallback (VM не подан).
        if self._telemetry is None and self._bindings is not None:
            self._bindings.bind_fanout(
                f"processes.{self._process_name}.workers.*.status",
                self._on_worker_discovered,
                owner=self,
            )
        return page

    # ------------------------------------------------------------------ #
    #  График (Ф2, Task 2.2)                                               #
    # ------------------------------------------------------------------ #

    def _build_graph_box(self) -> QWidget:
        """Секция графика: переключатель диапазона + спарклайны fps/latency.

        10 мин — ring-буфер VM (без похода в БД); 1 час/1 день — БД через
        TelemetryHistorySource, чтение off-main (см. _refresh_graph_from_history).
        """
        box = QGroupBox("График")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        range_row = QHBoxLayout()
        self._graph_range_buttons: dict[str, QPushButton] = {}
        for key, label, _seconds in _GRAPH_RANGES:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == self._graph_range)
            btn.clicked.connect(lambda _checked=False, k=key: self._on_graph_range_selected(k))
            range_row.addWidget(btn)
            self._graph_range_buttons[key] = btn
        range_row.addStretch()
        layout.addLayout(range_row)

        # Мини-графики fps/latency — тот же generic TelemetryChart, что дашборд (единая
        # система графиков), одиночная серия без легенды, но интерактивный: зум колесом
        # по времени (Ф2.3). Отдельные графики (разные юниты — своя авто-шкала у каждого).
        layout.addWidget(QLabel("FPS"))
        self._fps_chart = TelemetryChart([SeriesSpec("fps", "FPS", color="#2563eb")], legend=False)
        self._fps_chart.setMaximumHeight(150)
        layout.addWidget(self._fps_chart)

        layout.addWidget(QLabel("Задержка, мс"))
        self._latency_chart = TelemetryChart([SeriesSpec("latency", "Задержка, мс", color="#d97706")], legend=False)
        self._latency_chart.setMaximumHeight(150)
        layout.addWidget(self._latency_chart)

        return box

    # ------------------------------------------------------------------ #
    #  Телеметрия: управляемая публикация (Ф4.1)                           #
    # ------------------------------------------------------------------ #

    def _on_telemetry_change(self, metric: str, enabled: bool | None, interval_sec: float | None) -> None:
        """Пользователь дёрнул тумблер/частоту метрики → запись через bridge.

        RequestRunner гонит блокирующий request на worker-потоке (main-thread не
        фризится), результат (охват + ``capped_by_throttle``) приходит в main-thread
        и уходит в секцию — «no silent caps» (Task 1.4) виден пользователю.
        """
        self._telemetry_runner.submit(
            lambda: self._presenter.apply_telemetry_metric(
                self._process_name, metric, enabled=enabled, interval_sec=interval_sec
            ),
            on_result=lambda res, m=metric: self._on_telemetry_result(m, res),
        )

    def _on_telemetry_result(self, metric: str, result: dict[str, Any]) -> None:
        """Callback RequestRunner (main-thread): показать результат записи метрики."""
        if self._is_destroyed or not hasattr(self, "_telemetry_controls"):
            return
        self._telemetry_controls.show_result(metric, result)

    def _on_graph_range_selected(self, key: str) -> None:
        """Переключить диапазон графика (кнопка 10 мин / 1 час / 1 день)."""
        if key == self._graph_range:
            return
        self._graph_range = key
        for k, btn in self._graph_range_buttons.items():
            btn.setChecked(k == key)
        self._refresh_graph()

    def _refresh_graph(self) -> None:
        """Перерисовать графики под текущий выбранный диапазон."""
        # Любой новый рефреш инвалидирует ещё летящие async-ответы истории
        # (в т.ч. при переключении на «10 мин», обслуживаемое синхронно из ring).
        self._graph_request_id += 1
        if self._graph_range == "10m":
            self._refresh_graph_from_ring()
        else:
            self._refresh_graph_from_history()

    def _refresh_graph_from_ring(self) -> None:
        """10 мин — из кольцевого буфера VM (Task 1.2), без похода в БД.

        VM не подан → графики деградируют в пустую серию (TelemetryChart рисует
        пустой график без падений).

        Читаем только точки внутри wall-окна (``since``): deque вытесняет старые
        лишь при append, поэтому после ОСТАНОВКИ потока метрики (процесс встал /
        метрика выключена gate'ом) буфер бессрочно держал бы последние точки и
        спарклайн рисовал бы замороженное прошлое как текущее. Отсёк по времени
        → нет свежих данных = пустой график, а не стейл-окно.
        """
        if self._telemetry is None:
            self._fps_chart.set_series_data("fps", [])
            self._latency_chart.set_series_data("latency", [])
            return
        proc = self._process_name
        window = next((s for k, _label, s in _GRAPH_RANGES if k == "10m"), 600.0)
        since = time.time() - window  # ring хранит wall-clock ts (единая ось с DB/DateAxisItem)
        self._fps_chart.set_series_data("fps", self._telemetry.history(f"processes.{proc}.state.fps", since=since))
        self._latency_chart.set_series_data(
            "latency", self._telemetry.history(f"processes.{proc}.state.latency_ms", since=since)
        )

    def _refresh_graph_from_history(self) -> None:
        """1 час / 1 день — TelemetryHistorySource.list_range на worker-потоке.

        Чтение БД гоняется через RequestRunner (QThreadPool) — main thread НЕ
        блокируется на I/O; результат приходит в _on_history_ready сигналом
        уже в main-thread (тот же приём, что у command-result-bridge).
        """
        seconds = next((s for k, _label, s in _GRAPH_RANGES if k == self._graph_range), 3600.0)
        now = time.time()
        ts_from = now - seconds
        proc = self._process_name
        source = self._history_source
        request_id = self._graph_request_id

        def _fetch() -> dict[str, Any]:
            records = source.list_range(proc, ts_from, now, ("fps", "latency_ms"), max_points=_GRAPH_HISTORY_MAX_POINTS)
            return {"records": records, "request_id": request_id}

        self._history_runner.submit(_fetch, on_result=self._on_history_ready)

    def _on_history_ready(self, result: dict[str, Any]) -> None:
        """Callback RequestRunner (main-thread): применить выборку БД к графикам.

        result — либо {"records": [...]} (успех _fetch), либо
        {"success": False, "error": ...} (исключение source.list_range —
        RequestRunner перехватывает сам, TelemetryHistorySource штатно её не
        бросает, но fake-источник в тестах может). Оба случая → records=[]
        деградируют в плейсхолдер, панель не падает.
        """
        if self._is_destroyed:
            return
        # Отбросить устаревший ответ: пока запрос летел, пользователь мог
        # переключить диапазон (тогда _graph_request_id уже другой). Ответ без
        # request_id (напр. {"success": False} от RequestRunner при исключении)
        # относится к текущему запросу — применяем как деградацию (records=[]).
        if "request_id" in result and result["request_id"] != self._graph_request_id:
            return
        records = result.get("records", [])
        fps_points = [(r["ts"], r["fps"]) for r in records if isinstance(r.get("fps"), (int, float))]
        latency_points = [(r["ts"], r["latency_ms"]) for r in records if isinstance(r.get("latency_ms"), (int, float))]
        self._fps_chart.set_series_data("fps", fps_points)
        self._latency_chart.set_series_data("latency", latency_points)

    # ------------------------------------------------------------------ #
    #  Workers                                                             #
    # ------------------------------------------------------------------ #

    def _refresh_workers(self) -> None:
        """Перечитать воркеров из presenter и перепривязать телеметрию.

        К конфиг-воркерам подмешиваются рантайм-воркеры, обнаруженные из
        телеметрии (read-only protected-строки) — чтобы видеть время цикла
        каждого реального потока, а не только тех, что заданы в топологии.
        """
        if not hasattr(self, "_worker_table"):
            return
        workers = self._presenter.get_workers(self._process_name)
        known = {w.get("worker_name") for w in workers}
        for rname in sorted(self._runtime_workers):
            if rname not in known:
                workers.append(
                    {
                        "worker_name": rname,
                        "priority": "NORMAL",
                        "execution_mode": "loop",
                        "target_interval_ms": None,
                        "worker_class": None,
                        "protected": True,
                        "description": "Рантайм-воркер (только телеметрия)",
                        "config": {},
                    }
                )
        self._worker_table.set_workers(workers)
        self._bind_worker_telemetry()
        # Выбор сбросился после перестроения строк → уведомить вкладку.
        self.worker_selection_changed.emit(self._worker_table.selected_worker())

    def _on_worker_discovered(self, path: str, _value: object) -> None:
        """Fan-out callback: обнаружен воркер в телеметрии (processes.X.workers.NAME.status).

        Только копит имя воркера и взводит одиночный отложенный
        ``_flush_worker_refresh`` (Task 0.4, часть A) — N обнаружений подряд
        (типичный каскад при первом подключении процесса) коалесцируются в
        ОДНО перестроение таблицы вместо N.
        """
        parts = path.split(".")
        # ['processes', proc, 'workers', NAME, 'status']
        if len(parts) < 5:
            return
        name = parts[3]
        if name in self._runtime_workers:
            return
        self._runtime_workers.add(name)
        if not self._worker_refresh_pending:
            self._worker_refresh_pending = True
            QTimer.singleShot(_WORKER_DISCOVERY_DEBOUNCE_MS, self._flush_worker_refresh)

    def _flush_worker_refresh(self) -> None:
        """Отложенный коалесцированный refresh (см. _on_worker_discovered).

        Если панель уже уничтожена к моменту срабатывания таймера — не
        трогаем мёртвый виджет (гонка при быстром закрытии/переключении).
        """
        self._worker_refresh_pending = False
        if self._is_destroyed:
            return
        self._refresh_workers()

    def _mark_destroyed(self, *_args: object) -> None:
        """Слот на ``destroyed`` --- взводит гвард для _flush_worker_refresh."""
        self._is_destroyed = True

    # ------------------------------------------------------------------ #
    #  Worker actions (вызываются из левой панели вкладки, worker-scope)  #
    # ------------------------------------------------------------------ #

    def selected_worker(self) -> str | None:
        """Имя выбранного воркера в таблице или None."""
        if not hasattr(self, "_worker_table"):
            return None
        return self._worker_table.selected_worker()

    def is_selected_worker_protected(self) -> bool:
        """Защищён ли выбранный воркер (для логики кнопок Удалить/Остановить)."""
        worker = self.selected_worker()
        if not worker:
            return False
        return self._worker_table.is_worker_protected(worker)

    def request_add_worker(self) -> None:
        """Показать диалог создания воркера → presenter.add_worker + refresh."""
        dialog = CreateWorkerDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()
        ok = self._presenter.add_worker(
            self._process_name,
            worker_name=data["worker_name"],
            priority=data["priority"],
            execution_mode=data["execution_mode"],
            target_interval_ms=data["target_interval_ms"],
        )
        if not ok:
            QMessageBox.warning(
                self,
                "Воркер",
                f"Не удалось добавить воркер «{data['worker_name']}» (дубликат или защищённое имя).",
            )
        self._refresh_workers()

    def request_remove_worker(self) -> None:
        """Удалить выбранный воркер (persist + live-IPC). Protected — no-op в presenter."""
        worker = self.selected_worker()
        if not worker:
            return
        self._presenter.remove_worker(self._process_name, worker)
        self._refresh_workers()

    def request_start_worker(self) -> None:
        """Запустить выбранный воркер (live-IPC)."""
        worker = self.selected_worker()
        if worker:
            self._presenter.start_worker(self._process_name, worker)

    def request_stop_worker(self) -> None:
        """Остановить выбранный воркер (live-IPC). Protected — no-op в presenter."""
        worker = self.selected_worker()
        if worker:
            self._presenter.stop_worker(self._process_name, worker)

    def _on_worker_changed(self, worker_name: str, field: str, value: object) -> None:
        self._presenter.update_worker(self._process_name, worker_name, **{field: value})

    def _bind_worker_telemetry(self) -> None:
        """Привязать статус/Гц каждого воркера к телеметрии (forward-compatible).

        Backend публикует per-worker телеметрию в processes.{proc}.workers.{name}.*
        (heartbeat workers_status → fan-out). Вызывается после каждого перестроения
        строк таблицы (_refresh_workers).

        VM-режим (Task 1.3): пересобрать карту путей воркеров→setter и первично
        наполнить новые строки из snapshot. Fallback: прежний bindings.bind
        (привязки переживают пересоздание строк через weakref auto-cleanup).
        """
        if self._telemetry is not None:
            self._rebuild_worker_vm_setters()
            return

        bindings = self._bindings
        if bindings is None:
            return
        proc = self._process_name
        for name in self._worker_table.worker_names():
            widgets = self._worker_table.telemetry_widgets(name)
            status_w = widgets.get("status")
            if status_w is not None:
                bindings.bind(
                    f"processes.{proc}.workers.{name}.status",
                    status_w,
                    "text",
                    formatter=lambda v: str(v),
                )
            hz_w = widgets.get("hz")
            if hz_w is not None:
                bindings.bind(
                    f"processes.{proc}.workers.{name}.effective_hz",
                    hz_w,
                    "text",
                    formatter=lambda v: f"{v:.1f} Гц" if isinstance(v, (int, float)) else "—",
                )
            cycle_w = widgets.get("cycle")
            if cycle_w is not None:
                bindings.bind(
                    f"processes.{proc}.workers.{name}.cycle_duration_ms",
                    cycle_w,
                    "text",
                    formatter=lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
                )

    def _rebuild_worker_vm_setters(self) -> None:
        """VM-режим: пересобрать карту путей воркеров→setter под текущие строки.

        Вызывается после каждого перестроения таблицы (строки-QLabel'ы новые).
        После пересборки первично наполняет свежие строки из snapshot (без
        discover — строки уже созданы, повторное обнаружение вызвало бы цикл
        refresh↔prime; discover идёт только из живого батча/начального prime).
        """
        proc = self._process_name
        setters: dict[str, Callable[[Any], None]] = {}
        for name in self._worker_table.worker_names():
            widgets = self._worker_table.telemetry_widgets(name)
            status_w = widgets.get("status")
            if status_w is not None:
                setters[f"processes.{proc}.workers.{name}.status"] = _make_vm_setter(status_w, "text", lambda v: str(v))
            hz_w = widgets.get("hz")
            if hz_w is not None:
                setters[f"processes.{proc}.workers.{name}.effective_hz"] = _make_vm_setter(
                    hz_w, "text", lambda v: f"{v:.1f} Гц" if isinstance(v, (int, float)) else "—"
                )
            cycle_w = widgets.get("cycle")
            if cycle_w is not None:
                setters[f"processes.{proc}.workers.{name}.cycle_duration_ms"] = _make_vm_setter(
                    cycle_w, "text", lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—"
                )
        self._vm_worker_setters = setters
        # Реприм новых строк из снимка (только setter'ы, без discover).
        if self._telemetry is not None:
            snap = self._telemetry.snapshot(f"processes.{proc}")
            self._apply_telemetry_items(list(snap.items()), discover=False)

    def _build_table_page(self) -> QWidget:
        """Table-страница: key-value QTableWidget с метриками одного процесса."""
        self._detail_table = QTableWidget(0, len(_DETAIL_TABLE_COLUMNS))
        self._detail_table.setHorizontalHeaderLabels(_DETAIL_TABLE_COLUMNS)
        self._detail_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        h = self._detail_table.horizontalHeader()
        if h:
            h.setStretchLastSection(True)
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        return self._detail_table

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def set_view_mode(self, mode: ViewMode) -> None:
        """Переключить отображение Cards (0) / Table (1)."""
        if mode == ViewMode.TABLE:
            self._refresh_table()
            self._inner_stack.setCurrentIndex(1)
        else:
            self._inner_stack.setCurrentIndex(0)

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _refresh_table(self) -> None:
        metrics = self._presenter.get_detail_metrics(self._process_name)
        self._detail_table.setRowCount(len(metrics))
        for row, (key, value) in enumerate(metrics.items()):
            self._detail_table.setItem(row, 0, QTableWidgetItem(key))
            self._detail_table.setItem(row, 1, QTableWidgetItem(value))

    def _connect_bindings(self) -> None:
        """Подключить телеметрию карточки процесса: VM-режим или bindings-fallback.

        В VM-режиме карта путей→setter карточки собирается один раз, панель
        подписывается на ``updated`` одним слотом и первично наполняется из
        snapshot; воркер-пути и обнаружение рантайм-воркеров идут через тот же
        батч-слот (см. _apply_telemetry_items). Fallback — прежний bind-путь.
        """
        if not hasattr(self, "_card"):
            return
        if self._telemetry is not None:
            self._connect_telemetry_vm()
        elif self._bindings is not None:
            self._connect_bindings_legacy()

    # --- VM-режим (Task 1.3) ------------------------------------------- #

    def _is_worker_status_path(self, path: str) -> bool:
        """Путь вида ``processes.{proc}.workers.<w>.status`` (для discover)."""
        parts = path.split(".")
        return (
            len(parts) == 5
            and parts[0] == "processes"
            and parts[1] == self._process_name
            and parts[2] == "workers"
            and parts[4] == "status"
        )

    def _connect_telemetry_vm(self) -> None:
        """Собрать карту путей карточки→setter, подписаться на ``updated``,
        первично наполнить из snapshot (late-binding), обнаружить воркеров."""
        card = self._card
        name = self._process_name
        setters: dict[str, Callable[[Any], None]] = {}

        setters[f"processes.{name}.state.status"] = _make_vm_setter(card._indicator, "set_state")
        hz_label = card._metric_labels.get("Циклов/с")
        if hz_label is not None:
            setters[f"processes.{name}.state.fps"] = _make_vm_setter(
                hz_label, "text", lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—"
            )
        cycle_label = card._metric_labels.get("Время цикла")
        if cycle_label is not None:
            setters[f"processes.{name}.state.latency_ms"] = _make_vm_setter(
                cycle_label, "text", lambda v: f"{v:.1f} мс" if isinstance(v, (int, float)) else "—"
            )
        uptime_label = card._metric_labels.get("Uptime")
        if uptime_label is not None:
            setters[f"processes.{name}.state.uptime"] = _make_vm_setter(uptime_label, "text", _format_uptime)
        self._vm_setters = setters

        # Воркер-строки, созданные в _build_cards_page → _refresh_workers →
        # _bind_worker_telemetry, уже наполнили _vm_worker_setters. Подписка +
        # первичный prime процесса (discover=True: строим строки рантайм-воркеров,
        # уже опубликованных к моменту создания панели — late-binding).
        self._telemetry.updated.connect(self._on_telemetry_batch)
        snap = self._telemetry.snapshot(f"processes.{name}")
        self._apply_telemetry_items(list(snap.items()), discover=True)

    def _on_telemetry_batch(self, batch: list[tuple[str, Any]]) -> None:
        """Слот на ``TelemetryViewModel.updated`` — один на панель."""
        self._apply_telemetry_items(batch, discover=True)

    def _apply_telemetry_items(self, items: list[tuple[str, Any]], *, discover: bool) -> None:
        """Применить пачку (path, value): setter карточки/воркера + (опц.) discover.

        discover=True — живой батч/начальный prime: путь ``…workers.<w>.status``
        дополнительно скармливается _on_worker_discovered (строит строку нового
        рантайм-воркера). discover=False — реприм после перестроения строк:
        только setter'ы (иначе refresh↔prime зациклились бы).
        """
        fps_path = f"processes.{self._process_name}.state.fps"
        latency_path = f"processes.{self._process_name}.state.latency_ms"
        graph_touched = False
        for path, value in items:
            setter = self._vm_setters.get(path)
            if setter is None:
                setter = self._vm_worker_setters.get(path)
            if setter is not None:
                try:
                    setter(value)
                except Exception as exc:  # виджет↔значение — не валим GUI (правило 5)
                    _logger.debug("telemetry-vm: setter failed on %s: %s", path, exc)
            if discover and self._is_worker_status_path(path):
                self._on_worker_discovered(path, value)
            if path == fps_path or path == latency_path:
                graph_touched = True
        # График 10 мин читает ring-буфер VM — обновляем ТОЛЬКО когда этот
        # диапазон активен (1ч/1д не трогаем: они читают БД по кнопке/таймеру,
        # не по каждому батчу). Дешёвая O(k)-выборка буфера, не I/O.
        if graph_touched and self._graph_range == "10m" and hasattr(self, "_fps_chart"):
            self._refresh_graph_from_ring()
        # Ф4.1: обновить читаемый статус строк телеметрии из read-model (fps/latency).
        if graph_touched and hasattr(self, "_telemetry_controls"):
            self._telemetry_controls.update_readouts(self._telemetry)

    # --- Fallback: прежний bindings-путь ------------------------------- #

    def _connect_bindings_legacy(self) -> None:
        """Прежний путь карточки процесса через GuiStateBindings (VM не подан)."""
        bindings = self._bindings
        assert bindings is not None
        card = self._card
        name = self._process_name

        bindings.bind(
            f"processes.{name}.state.status",
            card._indicator,
            "set_state",
        )
        hz_label = card._metric_labels.get("Циклов/с")
        if hz_label is not None:
            bindings.bind(
                f"processes.{name}.state.fps",
                hz_label,
                "text",
                formatter=lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
            )
        cycle_label = card._metric_labels.get("Время цикла")
        if cycle_label is not None:
            bindings.bind(
                f"processes.{name}.state.latency_ms",
                cycle_label,
                "text",
                formatter=lambda v: f"{v:.1f} мс" if isinstance(v, (int, float)) else "—",
            )
        uptime_label = card._metric_labels.get("Uptime")
        if uptime_label is not None:
            bindings.bind(
                f"processes.{name}.state.uptime",
                uptime_label,
                "text",
                formatter=_format_uptime,
            )
