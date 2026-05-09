"""ProcessesTab — таб управления процессами.

3-колоночный layout по образцу RecipesTab:
  Левая панель (QListWidget): «Все процессы» + список по имени
  Центр (QStackedWidget): Cards / Table для сводки и для одного процесса
  Правая панель: ViewModeToggle + кнопки управления
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype_2.frontend.forms.view_mode_toggle import ViewMode, ViewModeToggle
from multiprocess_prototype_2.frontend.widgets.primitives import (
    CardAction,
    EntityCard,
)

from .data import ALL_PROCESSES_KEY
from .presenter import ProcessesPresenter

if TYPE_CHECKING:
    from multiprocess_prototype_2.frontend.app_context import AppContext

# Константы layout
_NAV_WIDTH = 200
_ITEM_HEIGHT = 40
_ITEM_SPACING = 4
_BTN_WIDTH = 120

# Страницы QStackedWidget
_PAGE_ALL_CARDS = 0
_PAGE_ALL_TABLE = 1
_PAGE_SINGLE_CARDS = 2
_PAGE_SINGLE_TABLE = 3

# Колонки таблицы «Все процессы»
_ALL_TABLE_COLUMNS = ["Имя", "Категория", "Статус", "FPS", "Плагины"]

# Колонки key-value таблицы одного процесса
_DETAIL_TABLE_COLUMNS = ["Параметр", "Значение"]


class ProcessesTab(QWidget):
    """Таб управления процессами.

    3-колоночный layout: навигация + контент (Cards/Table) + кнопки.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._presenter = ProcessesPresenter(ctx)
        self._cards: dict[str, EntityCard] = {}
        self._selected_process: str | None = None  # None = «Все процессы»
        self._detail_card: EntityCard | None = None

        self._init_ui()
        self._sync_nav()
        self._populate_all_cards()
        self._connect_bindings()

    @classmethod
    def create(cls, ctx: "AppContext") -> "ProcessesTab":
        """Фабричный метод для TabFactory."""
        return cls(ctx)

    # ------------------------------------------------------------------ #
    #  UI                                                                  #
    # ------------------------------------------------------------------ #

    def _init_ui(self) -> None:
        """Построить 3-колоночный layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Заголовок
        header = QLabel("Процессы")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        # 3-колоночный layout
        columns = QHBoxLayout()
        columns.setSpacing(8)

        # --- Левая панель: навигация ---
        self._nav_list = QListWidget()
        self._nav_list.setObjectName("ProcessNavList")
        self._nav_list.setFixedWidth(_NAV_WIDTH)
        self._nav_list.setSpacing(_ITEM_SPACING)
        self._nav_list.currentRowChanged.connect(self._on_nav_row_changed)
        columns.addWidget(self._nav_list)

        # --- Центр: QStackedWidget с 4 страницами ---
        self._center_stack = QStackedWidget()

        # Page 0: все процессы — карточки
        self._all_cards_page = self._build_all_cards_page()
        self._center_stack.addWidget(self._all_cards_page)

        # Page 1: все процессы — таблица
        self._all_table_page = self._build_all_table_page()
        self._center_stack.addWidget(self._all_table_page)

        # Page 2: один процесс — карточка
        self._single_cards_page = self._build_single_cards_page()
        self._center_stack.addWidget(self._single_cards_page)

        # Page 3: один процесс — таблица
        self._single_table_page = self._build_single_table_page()
        self._center_stack.addWidget(self._single_table_page)

        columns.addWidget(self._center_stack, stretch=1)

        # --- Правая панель: toggle + кнопки ---
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)

        # Тумблер Cards/Table
        self._toggle = ViewModeToggle(initial_mode=ViewMode.CARDS)
        self._toggle.mode_changed.connect(self._on_view_mode_changed)
        btn_layout.addWidget(self._toggle)

        # Кнопки управления
        self._btn_create = QPushButton("Создать")
        self._btn_create.setFixedWidth(_BTN_WIDTH)
        self._btn_create.clicked.connect(lambda: self._on_button_action("create"))
        btn_layout.addWidget(self._btn_create)

        self._btn_delete = QPushButton("Удалить")
        self._btn_delete.setFixedWidth(_BTN_WIDTH)
        self._btn_delete.setEnabled(False)
        self._btn_delete.clicked.connect(lambda: self._on_button_action("delete"))
        btn_layout.addWidget(self._btn_delete)

        self._btn_start = QPushButton("Запустить")
        self._btn_start.setFixedWidth(_BTN_WIDTH)
        self._btn_start.setEnabled(False)
        self._btn_start.clicked.connect(lambda: self._on_button_action("start"))
        btn_layout.addWidget(self._btn_start)

        self._btn_stop = QPushButton("Остановить")
        self._btn_stop.setFixedWidth(_BTN_WIDTH)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(lambda: self._on_button_action("stop"))
        btn_layout.addWidget(self._btn_stop)

        btn_layout.addStretch()
        columns.addLayout(btn_layout)

        layout.addLayout(columns, stretch=1)

    # ------------------------------------------------------------------ #
    #  Страницы центра                                                     #
    # ------------------------------------------------------------------ #

    def _build_all_cards_page(self) -> QWidget:
        """Page 0: health panel + scroll area с EntityCard для всех процессов."""
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(4)

        # Health панель
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

        page_layout.addWidget(self._health_panel)

        # Scroll area с карточками
        self._all_scroll = QScrollArea()
        self._all_scroll.setWidgetResizable(True)
        self._all_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._all_scroll_content = QWidget()
        self._all_scroll_layout = QVBoxLayout(self._all_scroll_content)
        self._all_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._all_scroll_layout.addStretch()
        self._all_scroll.setWidget(self._all_scroll_content)

        page_layout.addWidget(self._all_scroll, stretch=1)
        return page

    def _build_all_table_page(self) -> QWidget:
        """Page 1: QTableWidget со всеми процессами."""
        self._all_table = QTableWidget(0, len(_ALL_TABLE_COLUMNS))
        self._all_table.setHorizontalHeaderLabels(_ALL_TABLE_COLUMNS)
        self._all_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._all_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        h = self._all_table.horizontalHeader()
        if h:
            h.setStretchLastSection(True)
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        return self._all_table

    def _build_single_cards_page(self) -> QWidget:
        """Page 2: контейнер для детальной карточки одного процесса."""
        page = QWidget()
        self._detail_container_layout = QVBoxLayout(page)
        self._detail_container_layout.setContentsMargins(0, 0, 0, 0)
        self._detail_container_layout.addStretch()
        return page

    def _build_single_table_page(self) -> QWidget:
        """Page 3: key-value таблица одного процесса."""
        self._detail_table = QTableWidget(0, len(_DETAIL_TABLE_COLUMNS))
        self._detail_table.setHorizontalHeaderLabels(_DETAIL_TABLE_COLUMNS)
        self._detail_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._detail_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        h = self._detail_table.horizontalHeader()
        if h:
            h.setStretchLastSection(True)
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        return self._detail_table

    # ------------------------------------------------------------------ #
    #  Навигация                                                           #
    # ------------------------------------------------------------------ #

    def _sync_nav(self) -> None:
        """Перестроить список навигации: «Все процессы» + имена."""
        self._nav_list.blockSignals(True)
        self._nav_list.clear()

        # Первый элемент — «Все процессы»
        all_item = QListWidgetItem("Все процессы")
        all_item.setSizeHint(QSize(0, _ITEM_HEIGHT))
        all_item.setData(Qt.ItemDataRole.UserRole, ALL_PROCESSES_KEY)
        font = all_item.font()
        font.setBold(True)
        all_item.setFont(font)
        self._nav_list.addItem(all_item)

        # Отдельные процессы
        for name in self._presenter.get_process_names():
            item = QListWidgetItem(name)
            item.setSizeHint(QSize(0, _ITEM_HEIGHT))
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._nav_list.addItem(item)

        self._nav_list.blockSignals(False)
        self._nav_list.setCurrentRow(0)

    def _on_nav_row_changed(self, row: int) -> None:
        """Обработать выбор элемента в навигации."""
        if row < 0:
            return
        item = self._nav_list.item(row)
        if item is None:
            return

        key = item.data(Qt.ItemDataRole.UserRole)
        if key == ALL_PROCESSES_KEY:
            self._selected_process = None
        else:
            self._selected_process = key
            self._show_single_process(key)

        self._update_buttons_state()
        self._update_center_page()

    # ------------------------------------------------------------------ #
    #  Переключение вида                                                   #
    # ------------------------------------------------------------------ #

    def _on_view_mode_changed(self, _mode_str: str) -> None:
        """Переключить Cards / Table."""
        self._update_center_page()

    def _update_center_page(self) -> None:
        """Выбрать правильную страницу стека по (selection × view_mode)."""
        mode = self._toggle.mode()
        if self._selected_process is None:
            # Все процессы
            if mode == ViewMode.CARDS:
                self._center_stack.setCurrentIndex(_PAGE_ALL_CARDS)
            else:
                self._refresh_all_table()
                self._center_stack.setCurrentIndex(_PAGE_ALL_TABLE)
        else:
            # Один процесс
            if mode == ViewMode.CARDS:
                self._center_stack.setCurrentIndex(_PAGE_SINGLE_CARDS)
            else:
                self._refresh_detail_table()
                self._center_stack.setCurrentIndex(_PAGE_SINGLE_TABLE)

    # ------------------------------------------------------------------ #
    #  Заполнение данных                                                   #
    # ------------------------------------------------------------------ #

    def _populate_all_cards(self) -> None:
        """Создать компактные EntityCard для всех процессов."""
        processes = self._presenter.get_processes()
        groups = self._presenter.group_by_category(processes)

        category_order = [
            "source", "processing", "rendering", "output",
            "control", "service", "utility",
        ]

        for cat in category_order:
            procs = groups.get(cat, [])
            if not procs:
                continue

            group_box = QGroupBox(self._presenter.category_title(cat))
            group_layout = QVBoxLayout(group_box)
            group_layout.setContentsMargins(4, 4, 4, 4)

            for proc in procs:
                actions = [
                    CardAction("start", "Start"),
                    CardAction("stop", "Stop"),
                    CardAction("restart", "Restart"),
                ]
                card = EntityCard(
                    entity_id=proc.name,
                    title=proc.name,
                    actions=actions,
                )
                card.set_metrics({
                    "Плагины": ", ".join(proc.plugins) or "—",
                })
                card.set_status(proc.status)
                card.action_clicked.connect(self._on_card_action)

                group_layout.addWidget(card)
                self._cards[proc.name] = card

            idx = self._all_scroll_layout.count() - 1
            self._all_scroll_layout.insertWidget(idx, group_box)

    def _show_single_process(self, name: str) -> None:
        """Показать детальную карточку одного процесса."""
        # Удалить предыдущую карточку
        if self._detail_card is not None:
            self._detail_card.setParent(None)
            self._detail_card.deleteLater()
            self._detail_card = None

        proc = self._presenter.get_process_by_name(name)
        if proc is None:
            return

        actions = [
            CardAction("start", "Запустить"),
            CardAction("stop", "Остановить"),
            CardAction("restart", "Перезапустить"),
        ]
        self._detail_card = EntityCard(
            entity_id=proc.name,
            title=proc.name,
            actions=actions,
        )
        self._detail_card.set_metrics(
            self._presenter.get_detail_metrics(name)
        )
        self._detail_card.set_status(proc.status)
        self._detail_card.action_clicked.connect(self._on_card_action)

        self._detail_container_layout.insertWidget(0, self._detail_card)

        # Привязать live-данные к detail card
        self._bind_detail_card(name)

    def _refresh_all_table(self) -> None:
        """Перестроить таблицу всех процессов."""
        rows = self._presenter.get_table_rows()
        self._all_table.setRowCount(len(rows))
        for row_idx, row_data in enumerate(rows):
            for col_idx, col_name in enumerate(_ALL_TABLE_COLUMNS):
                self._all_table.setItem(
                    row_idx, col_idx,
                    QTableWidgetItem(row_data.get(col_name, "")),
                )

    def _refresh_detail_table(self) -> None:
        """Перестроить key-value таблицу одного процесса."""
        if self._selected_process is None:
            return
        metrics = self._presenter.get_detail_metrics(self._selected_process)
        self._detail_table.setRowCount(len(metrics))
        for row, (key, value) in enumerate(metrics.items()):
            self._detail_table.setItem(row, 0, QTableWidgetItem(key))
            self._detail_table.setItem(row, 1, QTableWidgetItem(value))

    # ------------------------------------------------------------------ #
    #  Кнопки и состояние                                                  #
    # ------------------------------------------------------------------ #

    def _update_buttons_state(self) -> None:
        """Обновить enabled/disabled кнопок по текущему выбору."""
        has_selection = self._selected_process is not None
        self._btn_delete.setEnabled(has_selection)
        self._btn_start.setEnabled(has_selection)
        self._btn_stop.setEnabled(has_selection)

    def _on_button_action(self, action_id: str) -> None:
        """Обработать нажатие кнопки управления."""
        if action_id == "create":
            # TODO: диалог создания процесса
            return
        if self._selected_process is None:
            return
        if action_id in ("start", "stop"):
            self._presenter.on_process_action(self._selected_process, action_id)
        elif action_id == "delete":
            # TODO: удаление процесса с подтверждением
            pass

    # ------------------------------------------------------------------ #
    #  Обработчики карточек                                                #
    # ------------------------------------------------------------------ #

    def _on_card_action(self, entity_id: str, action_id: str) -> None:
        """Обработать действие на карточке процесса."""
        self._presenter.on_process_action(entity_id, action_id)

    def _on_toolbar_action(self, action_id: str) -> None:
        """Legacy: обратная совместимость для тестов (start_all / stop_all)."""
        for name in self._cards:
            if action_id == "start_all":
                self._presenter.on_process_action(name, "start")
            elif action_id == "stop_all":
                self._presenter.on_process_action(name, "stop")

    # ------------------------------------------------------------------ #
    #  Reactive bindings                                                   #
    # ------------------------------------------------------------------ #

    def _connect_bindings(self) -> None:
        """Подключить реактивные обновления из StateStore."""
        bindings = self._ctx.bindings()
        if bindings is None:
            return

        # Bindings для карточек в all-view
        for name, card in self._cards.items():
            card.set_metrics({"FPS": "—", "Latency": "—"})

            # Статус → StatusIndicator
            bindings.bind(
                f"processes.{name}.state.status",
                card._indicator,
                "set_state",
            )

            # FPS → metric label
            fps_label = card._metric_labels.get("FPS")
            if fps_label is not None:
                bindings.bind(
                    f"processes.{name}.state.fps",
                    fps_label,
                    "text",
                    formatter=lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
                )

            # Latency → metric label
            latency_label = card._metric_labels.get("Latency")
            if latency_label is not None:
                bindings.bind(
                    f"processes.{name}.state.latency_ms",
                    latency_label,
                    "text",
                    formatter=lambda v: f"{v:.0f} ms" if isinstance(v, (int, float)) else "—",
                )

        # Health panel bindings
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

    def _bind_detail_card(self, name: str) -> None:
        """Привязать live-данные к детальной карточке процесса."""
        bindings = self._ctx.bindings()
        if bindings is None or self._detail_card is None:
            return

        card = self._detail_card

        # Статус
        bindings.bind(
            f"processes.{name}.state.status",
            card._indicator,
            "set_state",
        )

        # FPS
        fps_label = card._metric_labels.get("FPS")
        if fps_label is not None:
            bindings.bind(
                f"processes.{name}.state.fps",
                fps_label,
                "text",
                formatter=lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
            )

        # Latency (если есть)
        latency_label = card._metric_labels.get("Latency")
        if latency_label is not None:
            bindings.bind(
                f"processes.{name}.state.latency_ms",
                latency_label,
                "text",
                formatter=lambda v: f"{v:.0f} ms" if isinstance(v, (int, float)) else "—",
            )
