"""ProcessesTab — таб управления процессами.

Композиция: ActionToolbar + QScrollArea[EntityCard × N].
Группировка карточек по категории плагинов.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype_2.frontend.widgets.primitives import (
    ActionToolbar,
    CardAction,
    EntityCard,
)

from .presenter import ProcessesPresenter

if TYPE_CHECKING:
    from multiprocess_prototype_2.frontend.app_context import AppContext


class ProcessesTab(QWidget):
    """Таб управления процессами.

    Показывает все процессы из topology как EntityCard,
    сгруппированные по категории плагинов.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._presenter = ProcessesPresenter(ctx)
        self._cards: dict[str, EntityCard] = {}

        self._init_ui()
        self._populate()
        self._connect_bindings()

    @classmethod
    def create(cls, ctx: "AppContext") -> "ProcessesTab":
        """Фабричный метод для TabFactory."""
        return cls(ctx)

    # ------------------------------------------------------------------ #
    #  UI                                                                  #
    # ------------------------------------------------------------------ #

    def _init_ui(self) -> None:
        """Построить layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Заголовок
        header = QLabel("Процессы")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        # Тулбар
        self._toolbar = ActionToolbar(actions=[
            ("start_all", "Запустить все"),
            ("stop_all", "Остановить все"),
        ])
        self._toolbar.action_triggered.connect(self._on_toolbar_action)
        layout.addWidget(self._toolbar)

        # Scroll area с карточками
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.addStretch()
        self._scroll.setWidget(self._scroll_content)

        layout.addWidget(self._scroll, stretch=1)

    def _populate(self) -> None:
        """Заполнить карточки из topology."""
        processes = self._presenter.get_processes()
        groups = self._presenter.group_by_category(processes)

        # Порядок категорий
        category_order = [
            "source", "processing", "rendering", "output",
            "control", "service", "utility",
        ]

        for cat in category_order:
            procs = groups.get(cat, [])
            if not procs:
                continue

            # Группа по категории
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
                # Начальные метрики
                card.set_metrics({
                    "Плагины": ", ".join(proc.plugins) or "—",
                })
                card.set_status(proc.status)
                card.action_clicked.connect(self._on_card_action)

                group_layout.addWidget(card)
                self._cards[proc.name] = card

            # Вставить перед stretch
            idx = self._scroll_layout.count() - 1
            self._scroll_layout.insertWidget(idx, group_box)

    def _connect_bindings(self) -> None:
        """Подключить реактивные обновления из StateStore."""
        bindings = self._ctx.bindings()
        if bindings is None:
            return

        for name, card in self._cards.items():
            # Подписка на статус процесса
            # GuiStateBindings ожидает state_delta с path вида processes.{name}.state.status
            # Пока StateStore не broadcasting — это noop, но готово к Phase 12
            pass
            # TODO Phase 12: bindings.bind(f"processes.{name}.state.status", ...)

    # ------------------------------------------------------------------ #
    #  Обработчики                                                         #
    # ------------------------------------------------------------------ #

    def _on_card_action(self, entity_id: str, action_id: str) -> None:
        """Обработать действие на карточке процесса."""
        self._presenter.on_process_action(entity_id, action_id)

    def _on_toolbar_action(self, action_id: str) -> None:
        """Обработать действие тулбара."""
        for name in self._cards:
            if action_id == "start_all":
                self._presenter.on_process_action(name, "start")
            elif action_id == "stop_all":
                self._presenter.on_process_action(name, "stop")
