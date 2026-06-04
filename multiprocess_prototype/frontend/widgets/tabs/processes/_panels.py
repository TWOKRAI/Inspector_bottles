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

from PySide6.QtCore import QEvent, QObject, Qt, Signal
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


class AllProcessesPanel(QWidget):
    """Панель для ALL_PROCESSES_KEY: health + inner-стек Cards/Table."""

    card_action_requested = Signal(str, str)  # (entity_id, action_id)
    process_selected = Signal(object)  # имя выбранного процесса (str) | None

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
        self._selected_card_name: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # Health-панель sticky-сверху (до inner_stack).
        self._build_health_panel(outer)

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
        """Подписаться на StateStore для карточек и health-меток."""
        bindings = self._bindings
        if bindings is None:
            return

        # Карточки: статус + Циклов/с (частота, среднее за секунду) + Время цикла.
        for name, card in self._cards.items():
            card.set_metrics({"Циклов/с": "—", "Время цикла": "—"})

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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._presenter = presenter
        self._bindings = bindings
        self._process_name = process_name
        # Рантайм-воркеры, обнаруженные из телеметрии (data_receiver,
        # pipeline_executor, source_producer_* — создаются в рантайме и в
        # конфиг-топологии отсутствуют). Подмешиваются в таблицу как read-only.
        self._runtime_workers: set[str] = set()

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
        # Карточка + таблица прижаты вверх, без растягивания таблицы на всю высоту.
        page_layout.addStretch(1)

        self._refresh_workers()

        # Fan-out: обнаруживать рантайм-воркеров из телеметрии и добавлять в
        # таблицу (их нет в конфиг-топологии get_workers()).
        if self._bindings is not None:
            self._bindings.bind_fanout(
                f"processes.{self._process_name}.workers.*.status",
                self._on_worker_discovered,
                owner=self,
            )
        return page

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

        Если воркер ещё не в таблице — перестроить её с ним. Дубли отсекаются
        (перестроение только при новом имени), поэтому storm'а нет.
        """
        parts = path.split(".")
        # ['processes', proc, 'workers', NAME, 'status']
        if len(parts) < 5:
            return
        name = parts[3]
        if name in self._runtime_workers:
            return
        self._runtime_workers.add(name)
        self._refresh_workers()

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
            cycle_w = widgets.get("cycle")
            if cycle_w is not None:
                bindings.bind(
                    f"processes.{proc}.workers.{name}.cycle_duration_ms",
                    cycle_w,
                    "text",
                    formatter=lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
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
