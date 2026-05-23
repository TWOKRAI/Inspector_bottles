# -*- coding: utf-8 -*-
"""ProcessesTab — таб управления процессами.

Шаблон визуально и архитектурно идентичен Settings/Recipes: 3 колонки
(actions / nav / content) + мастер-скролл + QGroupBox с заголовком через
``DiffScrollTabLayout``; динамический список процессов во второй колонке
через ``BaseListNavTab``. Каждому nav-ключу соответствует свой композитный
content-виджет (``AllProcessesPanel`` / ``SingleProcessPanel``) с внутренним
переключателем Cards/Table — toggle меняет только визуализацию.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseListNavTab
from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode, ViewModeToggle
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import DiffScrollTabLayout

from ._panels import AllProcessesPanel, SingleProcessPanel
from .data import ALL_PROCESSES_KEY
from .presenter import ProcessesPresenter

if TYPE_CHECKING:
    from PySide6.QtGui import QIcon

    from multiprocess_prototype.frontend.app_context import AppContext


def _layout_factory() -> DiffScrollTabLayout:
    # Размеры колонок согласованы с Settings/Recipes — визуальная унификация.
    return DiffScrollTabLayout(title="Процессы", action_width=160, nav_width=230)


class ProcessesTab(BaseListNavTab):
    """Таб управления процессами на шаблоне ``DiffScrollTabLayout`` (как Settings/Recipes).

    Каждый процесс (и сводный ключ ``ALL_PROCESSES_KEY``) получает свой
    композитный content-виджет с внутренним Cards/Table стеком. Toggle в
    первой колонке переключает режим во всех созданных панелях разом —
    режим сохраняется при смене выбора в nav.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        self._presenter = ProcessesPresenter(ctx)
        self._all_panel: AllProcessesPanel | None = None
        self._single_panels: dict[str, SingleProcessPanel] = {}
        self._selected_process: str | None = None  # None при ALL_PROCESSES_KEY
        self._current_mode: ViewMode = ViewMode.CARDS

        # Динамические алиасы (обновляются в _on_nav_changed) — для совместимости тестов.
        self._detail_card = None
        self._detail_table = None

        super().__init__(
            title="Процессы",
            ctx=ctx,
            layout_factory=_layout_factory,
            parent=parent,
        )

        # Backward-compat alias на nav-список (исторически тесты ходят через _nav_list).
        self._nav_list = self._nav_widget

        self._setup_actions()
        # Авто-refresh scroll area при смене активной content-страницы (nav-ключ).
        self._tab_layout.connect_stack(self._content_stack, "content")

        self._sync_nav()

        # После _sync_nav AllProcessesPanel создан — пробрасываем его атрибуты
        # как алиасы на уровень tab, чтобы существующие тесты продолжали работать.
        self._publish_all_panel_aliases()

    @classmethod
    def create(cls, ctx: "AppContext") -> "ProcessesTab":
        """Фабричный метод для TabFactory."""
        return cls(ctx)

    # ------------------------------------------------------------------ #
    #  BaseListNavTab hooks                                                #
    # ------------------------------------------------------------------ #

    def _create_item_widget(self, key: str) -> QWidget:
        if key == ALL_PROCESSES_KEY:
            panel = AllProcessesPanel(self._presenter, self._ctx)
            panel.card_action_requested.connect(self._on_card_action)
            self._all_panel = panel
            return panel
        panel = SingleProcessPanel(self._presenter, self._ctx, key)
        panel.card_action_requested.connect(self._on_card_action)
        self._single_panels[key] = panel
        return panel

    def _make_nav_item(
        self,
        key: str,
        label: str,
        icon: "QIcon | None" = None,
    ) -> QListWidgetItem:
        item = super()._make_nav_item(key, label, icon)
        if key == ALL_PROCESSES_KEY:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        return item

    def _on_nav_changed(self, key: str) -> None:
        super()._on_nav_changed(key)  # переключает content_stack
        if key == ALL_PROCESSES_KEY:
            self._selected_process = None
        else:
            self._selected_process = key

        # Применить текущий режим к показанной панели.
        panel = self._all_panel if key == ALL_PROCESSES_KEY else self._single_panels.get(key)
        if panel is not None:
            panel.set_view_mode(self._current_mode)

        # Динамические алиасы под активный single-panel.
        single = self._single_panels.get(self._selected_process) if self._selected_process else None
        self._detail_card = getattr(single, "_card", None) if single else None
        self._detail_table = getattr(single, "_detail_table", None) if single else None

        self._update_buttons_state()

    # ------------------------------------------------------------------ #
    #  Actions / Buttons                                                   #
    # ------------------------------------------------------------------ #

    def _setup_actions(self) -> None:
        lay = self._tab_layout

        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(6)

        # Тумблер Cards/Table.
        self._toggle = ViewModeToggle(initial_mode=ViewMode.CARDS)
        self._toggle.mode_changed.connect(self._on_view_mode_changed)
        action_layout.addWidget(self._toggle)

        # 4 кнопки управления.
        self._btn_create = self._make_action_button("create", "Создать")
        action_layout.addWidget(self._btn_create)

        self._btn_delete = self._make_action_button("delete", "Удалить")
        self._btn_delete.setEnabled(False)
        action_layout.addWidget(self._btn_delete)

        self._btn_start = self._make_action_button("start", "Запустить")
        self._btn_start.setEnabled(False)
        action_layout.addWidget(self._btn_start)

        self._btn_stop = self._make_action_button("stop", "Остановить")
        self._btn_stop.setEnabled(False)
        action_layout.addWidget(self._btn_stop)

        action_layout.addStretch(1)
        lay.set_action_widget(action_widget)

        # Permission gating: tabs.processes.edit.
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        _auth = getattr(self._ctx, "auth", None)
        auth_state = getattr(_auth, "state", None) if _auth is not None else None
        for btn in (self._btn_create, self._btn_delete, self._btn_start, self._btn_stop):
            install_permission_aware_enable(btn, "tabs.processes.edit", auth_state)

    def _make_action_button(self, action_id: str, label: str) -> QPushButton:
        btn = QPushButton(label)
        btn.clicked.connect(lambda _checked=False, aid=action_id: self._on_button_action(aid))
        return btn

    def _on_button_action(self, action_id: str) -> None:
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

    def _update_buttons_state(self) -> None:
        has_selection = self._selected_process is not None
        self._btn_delete.setEnabled(has_selection)
        self._btn_start.setEnabled(has_selection)
        self._btn_stop.setEnabled(has_selection)

    # ------------------------------------------------------------------ #
    #  View mode                                                           #
    # ------------------------------------------------------------------ #

    def _on_view_mode_changed(self, mode_str: str) -> None:
        mode = ViewMode(mode_str)
        self._current_mode = mode
        if self._all_panel is not None:
            self._all_panel.set_view_mode(mode)
        for panel in self._single_panels.values():
            panel.set_view_mode(mode)

    # ------------------------------------------------------------------ #
    #  Nav populate                                                        #
    # ------------------------------------------------------------------ #

    def _sync_nav(self) -> None:
        """Заполнить навигацию: «Все процессы» (жирно) + имена процессов."""
        assert self._nav_widget is not None
        self._nav_widget.blockSignals(True)
        self._nav_widget.clear()
        # Сбросить content-стек.
        while self._content_stack.count() > 0:
            w = self._content_stack.widget(0)
            self._content_stack.removeWidget(w)
            if w is not None:
                w.deleteLater()
        self._key_to_item.clear()
        self._key_to_index.clear()
        self._all_panel = None
        self._single_panels.clear()
        self._nav_widget.blockSignals(False)

        self.add_item(ALL_PROCESSES_KEY, "Все процессы")
        for name in self._presenter.get_process_names():
            self.add_item(name, name)

        # Дефолтная выборка — «Все процессы».
        self.select_item(ALL_PROCESSES_KEY)

    # ------------------------------------------------------------------ #
    #  Backward-compat aliases                                             #
    # ------------------------------------------------------------------ #

    def _publish_all_panel_aliases(self) -> None:
        """Пробросить атрибуты AllProcessesPanel как алиасы на уровень tab.

        Существующие тесты обращаются к ``tab._cards``, ``tab._health_panel``,
        ``tab._lbl_*``, ``tab._all_table``, ``tab._all_scroll`` напрямую.
        """
        panel = self._all_panel
        if panel is None:
            self._cards = {}
            self._health_panel = None
            self._lbl_total = None
            self._lbl_active = None
            self._lbl_wires = None
            self._lbl_avg_fps = None
            self._all_table = None
            self._all_scroll = None
            return
        self._cards = panel._cards
        self._health_panel = panel._health_panel
        self._lbl_total = panel._lbl_total
        self._lbl_active = panel._lbl_active
        self._lbl_wires = panel._lbl_wires
        self._lbl_avg_fps = panel._lbl_avg_fps
        self._all_table = panel._all_table
        self._all_scroll = panel._all_scroll

    # ------------------------------------------------------------------ #
    #  Card actions / legacy                                               #
    # ------------------------------------------------------------------ #

    def _on_card_action(self, entity_id: str, action_id: str) -> None:
        """Обработать действие на карточке (всплывает из любой панели)."""
        self._presenter.on_process_action(entity_id, action_id)

    def _on_toolbar_action(self, action_id: str) -> None:
        """Legacy: обратная совместимость для тестов (start_all / stop_all)."""
        for name in self._cards:
            if action_id == "start_all":
                self._presenter.on_process_action(name, "start")
            elif action_id == "stop_all":
                self._presenter.on_process_action(name, "stop")
