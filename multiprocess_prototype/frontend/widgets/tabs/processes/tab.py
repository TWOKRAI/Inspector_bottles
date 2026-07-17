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
    QDialog,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseListNavTab
from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.events import TopologyReplaced
from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode, ViewModeToggle
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import DiffScrollTabLayout

from ._panels import AllProcessesPanel, SingleProcessPanel
from .data import ALL_PROCESSES_KEY
from .presenter import ProcessesPresenter
from .widgets import CreateProcessDialog

if TYPE_CHECKING:
    from PySide6.QtGui import QIcon

    from multiprocess_prototype.frontend.bridge.command_sender import CommandSender
    from multiprocess_prototype.frontend.bridge.topology_bridge import TopologyBridge
    from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
    from multiprocess_prototype.frontend.state.telemetry_view_model import TelemetryViewModel


def _layout_factory() -> DiffScrollTabLayout:
    # Размеры колонок согласованы с Settings/Recipes — визуальная унификация.
    return DiffScrollTabLayout(title="Процессы", action_width=160, nav_width=230)


class ProcessesTab(BaseListNavTab):
    """Таб управления процессами на шаблоне ``DiffScrollTabLayout`` (как Settings/Recipes).

    Task E.2: мигрирован на AppServices DI. Принимает ``services: AppServices``.
    command_sender / topology_bridge / bindings — live-runtime зависимости вне
    scope AppServices (Phase G aggregate) — передаются отдельными параметрами.

    Каждый процесс (и сводный ключ ``ALL_PROCESSES_KEY``) получает свой
    композитный content-виджет с внутренним Cards/Table стеком. Toggle в
    первой колонке переключает режим во всех созданных панелях разом —
    режим сохраняется при смене выбора в nav.
    """

    def __init__(
        self,
        services: AppServices,
        *,
        command_sender: "CommandSender | None" = None,
        topology_bridge: "TopologyBridge | None" = None,
        bindings: "GuiStateBindings | None" = None,
        telemetry: "TelemetryViewModel | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        self._services = services
        self._bindings = bindings
        # Ф1 (gui-telemetry-read-model 1.3): локальный read-model телеметрии,
        # прокидывается в панели (VM-режим вместо bind на телеметрию).
        self._telemetry = telemetry
        self._presenter = ProcessesPresenter(
            services,
            command_sender=command_sender,
            topology_bridge=topology_bridge,
        )
        self._all_panel: AllProcessesPanel | None = None
        self._single_panels: dict[str, SingleProcessPanel] = {}
        self._selected_process: str | None = None  # None при ALL_PROCESSES_KEY
        # Выбранный процесс в виде «Все процессы» (карточка/строка) — цель кнопок
        # в process-scope. Отличается от _selected_process (= открытая подвкладка).
        self._all_selected_process: str | None = None
        self._current_mode: ViewMode = ViewMode.CARDS

        # Динамические алиасы (обновляются в _on_nav_changed) — для совместимости тестов.
        self._detail_card = None
        self._detail_table = None

        super().__init__(
            title="Процессы",
            ctx=None,  # type: ignore[arg-type]  # framework generic-слот, прототип не использует ctx
            layout_factory=_layout_factory,
            parent=parent,
            # Хвост 0.4: панели процессов строятся лениво (только активная
            # при открытии) --- иначе Qt C++ стойл на layout/paint N панелей
            # глубокой вложенности (см. plans/gui-telemetry-read-model.md).
            lazy_content=True,
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

        # Реакция на изменение топологии (create/delete процесса из любой вкладки).
        # Воркер-правки не меняют набор процессов → nav не перестраивается (см. handler).
        self._topology_sub = self._services.events.subscribe(TopologyReplaced, self._on_topology_replaced)

    @classmethod
    def create(
        cls,
        services: AppServices,
        runtime: RuntimeDeps = RuntimeDeps(),
    ) -> "ProcessesTab":
        """Фабричный метод для register_all_tabs() / TabFactory.

        Task F.9: принимает AppServices + RuntimeDeps (Q-F1=B).
        Runtime-зависимости (command_sender, topology_bridge, bindings) --
        accepted: runtime layer, не AppServices.
        """
        return cls(
            services,
            command_sender=runtime.command_sender,
            topology_bridge=runtime.topology_bridge,
            bindings=runtime.bindings,
            telemetry=runtime.telemetry,
        )

    # ------------------------------------------------------------------ #
    #  BaseListNavTab hooks                                                #
    # ------------------------------------------------------------------ #

    def _create_item_widget(self, key: str) -> QWidget:
        if key == ALL_PROCESSES_KEY:
            panel = AllProcessesPanel(self._presenter, self._bindings, telemetry=self._telemetry)
            panel.card_action_requested.connect(self._on_card_action)
            panel.process_selected.connect(self._on_all_process_selected)
            self._all_panel = panel
            return panel
        single_panel = SingleProcessPanel(self._presenter, self._bindings, key, telemetry=self._telemetry)
        single_panel.card_action_requested.connect(self._on_card_action)
        single_panel.worker_selection_changed.connect(lambda _name=None: self._update_buttons_state())
        self._single_panels[key] = single_panel
        return single_panel

    def _on_all_process_selected(self, name: object) -> None:
        """Карточка/строка процесса выбрана в виде «Все процессы» → цель кнопок."""
        self._all_selected_process = name if isinstance(name, str) and name else None
        self._update_buttons_state()

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

        # Permission gating через AuthFacade Protocol (F.6).
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        for btn in (self._btn_create, self._btn_delete, self._btn_start, self._btn_stop):
            install_permission_aware_enable(btn, "tabs.processes.edit", self._services.auth)

    def _make_action_button(self, action_id: str, label: str) -> QPushButton:
        btn = QPushButton(label)
        btn.clicked.connect(lambda _checked=False, aid=action_id: self._on_button_action(aid))
        return btn

    def _on_button_action(self, action_id: str) -> None:
        """Контекст-свитч: в виде «Все процессы» кнопки = process-scope,
        в подвкладке процесса = worker-scope (по выбранному воркеру)."""
        if self._selected_process is None:
            self._on_process_scope_action(action_id)
        else:
            self._on_worker_scope_action(action_id)

    def _on_process_scope_action(self, action_id: str) -> None:
        """Process-scope (вид «Все процессы»): действия над выбранным процессом."""
        if action_id == "create":
            self._create_process_dialog()
            return
        target = self._all_selected_process
        if target is None:
            return
        # Guard: защищённый процесс нельзя удалить или остановить через GUI.
        if action_id in ("delete", "stop") and self._presenter.is_protected(target):
            return
        if action_id in ("start", "stop"):
            self._presenter.on_process_action(target, action_id)
        elif action_id == "delete":
            self._delete_process(target)

    def _on_worker_scope_action(self, action_id: str) -> None:
        """Worker-scope (подвкладка процесса): действия над выбранным воркером."""
        panel = self._single_panels.get(self._selected_process) if self._selected_process else None
        if panel is None:
            return
        if action_id == "create":
            panel.request_add_worker()
            return
        worker = panel.selected_worker()
        if not worker:
            return
        if action_id == "delete":
            panel.request_remove_worker()
        elif action_id == "start":
            panel.request_start_worker()
        elif action_id == "stop":
            panel.request_stop_worker()

    def _create_process_dialog(self) -> None:
        """Показать диалог создания процесса → presenter.create_process (+ персист)."""
        dialog = CreateProcessDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()
        ok = self._presenter.create_process(data["name"], category=data["category"])
        if not ok:
            QMessageBox.warning(
                self,
                "Создать процесс",
                f"Процесс «{data['name']}» уже существует или имя некорректно.",
            )
        # Перестроение nav — через TopologyReplaced (набор процессов изменился).

    def _delete_process(self, name: str) -> None:
        """Подтвердить и удалить процесс (persist + live hot_remove)."""
        if self._presenter.is_protected(name):
            return
        reply = QMessageBox.question(
            self,
            "Удалить процесс",
            f"Удалить процесс «{name}»?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._presenter.delete_process(name)
        # Перестроение nav — через TopologyReplaced.

    def _update_buttons_state(self) -> None:
        """Включить/выключить кнопки по контексту (process-scope vs worker-scope)."""
        if self._selected_process is None:
            self._update_buttons_process_scope()
        else:
            self._update_buttons_worker_scope()

    def _update_buttons_process_scope(self) -> None:
        """Вид «Все процессы»: кнопки действуют на выбранную карточку/строку."""
        target = self._all_selected_process
        has_selection = target is not None
        is_protected = self._presenter.is_protected(target) if target is not None else False
        self._btn_create.setToolTip("Создать новый процесс")
        self._btn_delete.setEnabled(has_selection and not is_protected)
        self._btn_start.setEnabled(has_selection)
        self._btn_stop.setEnabled(has_selection and not is_protected)
        if not has_selection:
            tip = "Выберите процесс в списке"
            self._btn_delete.setToolTip(tip)
            self._btn_start.setToolTip(tip)
            self._btn_stop.setToolTip(tip)
        else:
            prot_tip = "Системный процесс защищён от изменений"
            self._btn_delete.setToolTip(prot_tip if is_protected else "Удалить процесс")
            self._btn_start.setToolTip("Запустить процесс")
            self._btn_stop.setToolTip(prot_tip if is_protected else "Остановить процесс")

    def _update_buttons_worker_scope(self) -> None:
        """Подвкладка процесса: кнопки действуют на выбранный воркер в таблице."""
        panel = self._single_panels.get(self._selected_process) if self._selected_process else None
        worker = panel.selected_worker() if panel is not None else None
        has_selection = worker is not None
        is_protected = panel.is_selected_worker_protected() if (panel is not None and worker) else False
        self._btn_create.setToolTip("Добавить воркер в процесс")
        self._btn_delete.setEnabled(has_selection and not is_protected)
        self._btn_start.setEnabled(has_selection)
        self._btn_stop.setEnabled(has_selection and not is_protected)
        if not has_selection:
            tip = "Выберите воркер в таблице"
            self._btn_delete.setToolTip(tip)
            self._btn_start.setToolTip(tip)
            self._btn_stop.setToolTip(tip)
        else:
            prot_tip = "Системный воркер IPC защищён от изменений"
            self._btn_delete.setToolTip(prot_tip if is_protected else "Удалить воркер")
            self._btn_start.setToolTip("Запустить воркер")
            self._btn_stop.setToolTip(prot_tip if is_protected else "Остановить воркер")

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
        # Набор процессов меняется → прежний выбор в All-виде мог исчезнуть.
        self._all_selected_process = None
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
        # Ручной resync (в обход remove_item) — сбрасываем и очередь ленивых
        # ключей, иначе имена прежней topology остаются в ней бесполезным
        # хвостом (lazy_content=True, Хвост 0.4).
        self._pending_lazy_keys.clear()
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
        ``tab._lbl_*``, ``tab._all_table`` напрямую.
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
            return
        self._cards = panel._cards
        self._health_panel = panel._health_panel
        self._lbl_total = panel._lbl_total
        self._lbl_active = panel._lbl_active
        self._lbl_wires = panel._lbl_wires
        self._lbl_avg_fps = panel._lbl_avg_fps
        self._all_table = panel._all_table

    # ------------------------------------------------------------------ #
    #  Card actions / legacy                                               #
    # ------------------------------------------------------------------ #

    def _on_card_action(self, entity_id: str, action_id: str) -> None:
        """Обработать действие на карточке (всплывает из любой панели)."""
        if action_id == "delete":
            self._delete_process(entity_id)
            return
        if action_id == "stop" and self._presenter.is_protected(entity_id):
            return
        self._presenter.on_process_action(entity_id, action_id)

    def _on_topology_replaced(self, _event: object = None) -> None:
        """Перестроить nav только при изменении НАБОРА процессов (create/delete).

        Воркер-правки сохраняют набор процессов → nav не трогаем (панель уже
        обновила таблицу воркеров локально). Это избегает дорогого full-rebuild
        и сброса выбора на каждое изменение приоритета воркера.
        """
        current = set(self._key_to_item.keys()) - {ALL_PROCESSES_KEY}
        new = set(self._presenter.get_process_names())
        if current != new:
            self._sync_nav()
            self._publish_all_panel_aliases()

    def _on_toolbar_action(self, action_id: str) -> None:
        """Legacy: обратная совместимость для тестов (start_all / stop_all)."""
        for name in self._cards:
            if action_id == "start_all":
                self._presenter.on_process_action(name, "start")
            elif action_id == "stop_all":
                if not self._presenter.is_protected(name):
                    self._presenter.on_process_action(name, "stop")
