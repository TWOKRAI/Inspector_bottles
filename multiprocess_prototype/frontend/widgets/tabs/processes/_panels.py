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

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode
from multiprocess_prototype.frontend.widgets.primitives import (
    CardAction,
    EntityCard,
)

from .widgets import CreateWorkerDialog, ProcessCard, WorkerTable

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.state.bindings import GuiStateBindings

    from .presenter import ProcessesPresenter

# Колонки таблицы «Все процессы»
_ALL_TABLE_COLUMNS = ["Имя", "Категория", "Статус", "FPS", "Плагины"]

# Колонки key-value таблицы одного процесса
_DETAIL_TABLE_COLUMNS = ["Параметр", "Значение"]

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


class AllProcessesPanel(QWidget):
    """Панель для ALL_PROCESSES_KEY: health + inner-стек Cards/Table."""

    card_action_requested = Signal(str, str)  # (entity_id, action_id)

    def __init__(
        self,
        presenter: "ProcessesPresenter",
        bindings: "GuiStateBindings | None",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._presenter = presenter
        self._bindings = bindings
        self._cards: dict[str, EntityCard] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # Health-панель sticky-сверху (до inner_stack).
        self._build_health_panel(outer)

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
        self._lbl_avg_fps = QLabel("Средний FPS: —")

        health_layout.addWidget(self._lbl_total)
        health_layout.addWidget(self._lbl_active)
        health_layout.addWidget(self._lbl_wires)
        health_layout.addWidget(self._lbl_avg_fps)
        health_layout.addStretch()

        parent_layout.addWidget(self._health_panel)

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
        self._all_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
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
        """Подписаться на StateStore для карточек и health-меток."""
        bindings = self._bindings
        if bindings is None:
            return

        # Карточки: статус + FPS + Latency.
        for name, card in self._cards.items():
            card.set_metrics({"FPS": "—", "Latency": "—"})

            bindings.bind(
                f"processes.{name}.state.status",
                card._indicator,
                "set_state",
            )
            fps_label = card._metric_labels.get("FPS")
            if fps_label is not None:
                bindings.bind(
                    f"processes.{name}.state.fps",
                    fps_label,
                    "text",
                    formatter=lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
                )
            latency_label = card._metric_labels.get("Latency")
            if latency_label is not None:
                bindings.bind(
                    f"processes.{name}.state.latency_ms",
                    latency_label,
                    "text",
                    formatter=lambda v: f"{v:.0f} ms" if isinstance(v, (int, float)) else "—",
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
            formatter=lambda v: f"Средний FPS: {v:.1f}" if isinstance(v, (int, float)) else "Средний FPS: —",
        )


class SingleProcessPanel(QWidget):
    """Панель одного процесса: inner-стек детальной карточки и key-value таблицы."""

    card_action_requested = Signal(str, str)  # (entity_id, action_id)

    def __init__(
        self,
        presenter: "ProcessesPresenter",
        bindings: "GuiStateBindings | None",
        process_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._presenter = presenter
        self._bindings = bindings
        self._process_name = process_name

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
        self._card.set_metric("FPS", metrics.get("FPS", "—"))
        self._card.set_metric("PID", metrics.get("PID", "—"))
        self._card.action_clicked.connect(self.card_action_requested)
        page_layout.addWidget(self._card)

        # Секция воркеров (таблица CRUD).
        workers_box = QGroupBox("Воркеры")
        box_layout = QVBoxLayout(workers_box)
        box_layout.setContentsMargins(6, 6, 6, 6)
        self._worker_table = WorkerTable()
        self._worker_table.add_requested.connect(self._on_worker_add)
        self._worker_table.remove_requested.connect(self._on_worker_remove)
        self._worker_table.changed.connect(self._on_worker_changed)
        box_layout.addWidget(self._worker_table)
        page_layout.addWidget(workers_box, stretch=1)

        self._refresh_workers()
        return page

    # ------------------------------------------------------------------ #
    #  Workers                                                             #
    # ------------------------------------------------------------------ #

    def _refresh_workers(self) -> None:
        """Перечитать воркеров из presenter и перепривязать телеметрию."""
        if not hasattr(self, "_worker_table"):
            return
        self._worker_table.set_workers(self._presenter.get_workers(self._process_name))
        self._bind_worker_telemetry()

    def _on_worker_add(self) -> None:
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

    def _on_worker_remove(self, worker_name: str) -> None:
        self._presenter.remove_worker(self._process_name, worker_name)
        self._refresh_workers()

    def _on_worker_changed(self, worker_name: str, field: str, value: object) -> None:
        self._presenter.update_worker(self._process_name, worker_name, **{field: value})

    def _bind_worker_telemetry(self) -> None:
        """Привязать статус/Гц каждого воркера к StateStore (forward-compatible).

        Backend публикует per-worker телеметрию в processes.{proc}.workers.{name}.*
        (heartbeat workers_status → fan-out). Привязки переживают пересоздание строк
        через weakref auto-cleanup GuiStateBindings.
        """
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
        bindings = self._bindings
        if bindings is None or not hasattr(self, "_card"):
            return

        card = self._card
        name = self._process_name

        bindings.bind(
            f"processes.{name}.state.status",
            card._indicator,
            "set_state",
        )
        fps_label = card._metric_labels.get("FPS")
        if fps_label is not None:
            bindings.bind(
                f"processes.{name}.state.fps",
                fps_label,
                "text",
                formatter=lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
            )
        latency_label = card._metric_labels.get("Latency")
        if latency_label is not None:
            bindings.bind(
                f"processes.{name}.state.latency_ms",
                latency_label,
                "text",
                formatter=lambda v: f"{v:.0f} ms" if isinstance(v, (int, float)) else "—",
            )
