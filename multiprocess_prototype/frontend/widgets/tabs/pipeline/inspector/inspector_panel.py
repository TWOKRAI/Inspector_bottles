"""NodeInspectorPanel — панель параметров выбранного узла pipeline.

Task E.1: мигрирован на AppServices DI. set_services(services) вместо
set_context(ctx). RegistersManager и form_context() не покрыты AppServices
Protocol — оставлены как bridge через adapter (TODO Phase G: registers→G.2, form_context→G.4).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from multiprocess_prototype.domain.app_services import AppServices

from ..graph.constants import CATEGORY_COLORS
from .cam_actual_section import CamActualSection
from .exec_info_section import ExecInfoSection
from .io_debug_section import IoDebugSection
from .params_form_section import ParamsFormSection
from .process_selector_section import ProcessSelectorSection
from .selectors_data import (
    display_entries,
    process_names_from_recipe,
    workers_for_process,
)

logger = logging.getLogger(__name__)


class NodeInspectorPanel(QWidget):
    """Панель параметров выбранного узла pipeline.

    Показывает: имя процесса, категория, список плагинов, параметры.
    Если RegistersManager доступен — создаёт типизированные виджеты
    через CardsFieldFactory. Иначе — QLineEdit (fallback).

    Поддерживает два режима отображения:
    - show_plugin_node() — для plugin-узлов: combo «Процесс назначения» + параметры.
    - show_display_node() — для display-узлов: combo «Display» из DisplayRegistry.

    При отсутствии выбора — placeholder.

    Signals:
        field_changed(process_name, field_name, value): параметр изменён пользователем.
        target_process_changed(node_id, new_process_name): выбран новый процесс назначения.
        display_id_changed(node_id, new_display_id): выбран новый display.
    """

    # Signal: (process_name, field_name, new_value)
    field_changed = Signal(str, str, object)

    # Signal: (node_id, new_process_name) — пользователь выбрал целевой процесс
    target_process_changed = Signal(str, str)

    # Signal: (node_id, new_display_id) — пользователь выбрал display
    display_id_changed = Signal(str, str)

    # Signal: (from_node_id, to_process) — Phase B: перенести узел (его плагины) в процесс
    move_to_process_requested = Signal(str, str)

    # Signal: (node_id, locked) — кнопки «Закрепить/Открепить» (дубль правого клика,
    # удобно для сенсорного экрана — рядом с полями Процесс/Воркер).
    node_lock_set_requested = Signal(str, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_process: str = ""
        self._current_node_id: str = ""
        # Имя плагина выбранной ноды (для команды set_enabled / bypass).
        self._current_plugin_name: str = ""
        # D.2: индекс выбранного плагина в цепочке процесса (для SetPluginConfig
        # presenter читает его как panel.current_plugin_index). По умолчанию 0 —
        # совместимо с прямым field_changed.emit в тестах (1 плагин/процесс).
        self._current_plugin_index: int = 0
        self._suppress_changes: bool = False
        # Форма параметров (cards/QLineEdit), _field_editors/_use_cards/hik-refs —
        # внутри ParamsFormSection (F.6). Создаётся в _init_ui.
        # AppServices — задаётся через set_services()
        self._services: AppServices | None = None
        # G.2: live RegistersManager (FieldInfo-схемы) — runtime-dep через set_services,
        # т.к. forms-фабрике нужен framework FieldInfo (domain FieldSpec lossy).
        self._registers_manager: Any = None
        # GuiStateBindings — для actual-телеметрии камеры (Phase 3). None → readout скрыт.
        self._bindings: Any = None
        # command_sender + topology_bridge — для встраиваемых контролов Hikvision.
        self._command_sender: Any = None
        self._topology_bridge: Any = None
        # Текущий режим отображения: "plugin" или "display"
        self._mode: str = "plugin"
        # Combo/формы селекторов — внутри ProcessSelectorSection (F.6), см. _init_ui.
        self._init_ui()

    def set_services(
        self,
        services: "AppServices",
        *,
        registers_manager: Any = None,
        bindings: Any = None,
        command_sender: Any = None,
        topology_bridge: Any = None,
    ) -> None:
        """Передать AppServices + live RegistersManager (G.2, runtime-dep).

        registers_manager используется в _try_build_cards_editors для получения
        framework FieldInfo (forms-фабрика строит виджеты из FieldInfo, не domain FieldSpec).
        bindings (GuiStateBindings) — для actual-телеметрии камеры (Phase 3).
        command_sender + topology_bridge — для встраиваемых контролов камеры Hikvision
        (request/response enum/params + live-команды).
        """
        self._services = services
        self._registers_manager = registers_manager
        # Форма параметров строит cards по FieldInfo из RegistersManager.
        self._params_section.set_services(services, registers_manager)
        if bindings is not None:
            self._bindings = bindings
            # io-debug секция подписывается на io_peek через те же bindings.
            self._io_debug.set_bindings(bindings)
            # actual-секция камеры привязывает метки к state store через те же bindings.
            self._cam_section.set_bindings(bindings)
        if command_sender is not None:
            self._command_sender = command_sender
        if topology_bridge is not None:
            self._topology_bridge = topology_bridge

    def set_context(self, ctx: object) -> None:
        """Legacy bridge для backward compatibility. Deprecated.

        Если ctx имеет app_services — используем его. Иначе — сохраняем как fallback.
        TODO Phase G (G.5): удалить после удаления AppContext.
        """
        app_services = getattr(ctx, "app_services", None)
        if app_services is not None:
            self._services = app_services

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Placeholder
        self._placeholder = QLabel("Выберите узел")
        self._placeholder.setObjectName("InspectorPlaceholder")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._placeholder)

        # Content container (скрыт когда нет выбора)
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        # Заголовок: имя процесса
        self._title = QLabel()
        self._title.setObjectName("InspectorTitle")
        content_layout.addWidget(self._title)

        # Badge: категория
        self._category_badge = QLabel()
        self._category_badge.setObjectName("InspectorCategoryBadge")
        content_layout.addWidget(self._category_badge)

        # Блок «Исполнение» (Phase A, read-only): в каком ПРОЦЕССЕ исполняется нода
        # и в каком ВОРКЕРЕ каждый плагин (+ порядок). Секция инкапсулирует раскладку (F.6).
        self._exec_section = ExecInfoSection()
        content_layout.addWidget(self._exec_section)

        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("InspectorDivider")
        content_layout.addWidget(line)

        # Селекторы процесса/воркера/display + фиксация + bypass — самостоятельная
        # секция с локальным suppress (F.6, Н-6). Панель маппит её сигналы в внешние.
        self._selector_section = ProcessSelectorSection()
        self._selector_section.set_providers(
            self._get_process_names_from_recipe,
            self._get_workers_for_process,
            self._get_display_entries,
        )
        self._selector_section.sig_target_selected.connect(self._on_target_selected)
        self._selector_section.sig_display_selected.connect(self._on_display_selected)
        self._selector_section.sig_move_requested.connect(self.move_to_process_requested)
        self._selector_section.sig_worker_selected.connect(self._on_worker_selected)
        self._selector_section.sig_lock_set.connect(self._on_lock_set)
        self._selector_section.sig_bypass_toggled.connect(self._on_bypass_toggled)
        content_layout.addWidget(self._selector_section)

        # Разделитель между combo и параметрами
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setObjectName("InspectorDivider2")
        content_layout.addWidget(line2)
        self._divider2 = line2

        # Параметры плагина — БЕЗ вложенного скролла: поля идут одно за другим,
        # карточка раскрыта целиком. Вертикальный overflow обрабатывает мастер-
        # скролл DiffScrollTabLayout (правый). Раньше здесь был QScrollArea —
        # он давал второй (внутренний) скроллбар, который путал (убран).
        self._params_section = ParamsFormSection()
        # Секция эмитит field_changed(field, value); панель добавляет процесс.
        self._params_section.field_changed.connect(self._on_params_field_changed)
        content_layout.addWidget(self._params_section, stretch=1)

        # Блок «Камера (actual)» — read-only телеметрия что камера реально применила
        # (cap.get), привязка к state store processes.{proc}.state.cam.actual.*.
        # Секция инкапсулирует 6 подписок + их teardown (F.6, Н-4).
        self._cam_section = CamActualSection()
        content_layout.addWidget(self._cam_section)

        # Секция «I/O (debug)» — generic наблюдение in/out плагина (в самом низу карточки).
        # bindings придут позже через set_services → set_bindings.
        self._io_debug = IoDebugSection()
        content_layout.addWidget(self._io_debug)

        self._content.setVisible(False)
        layout.addWidget(self._content, stretch=1)

    # ------------------------------------------------------------------ #
    #  Селекторы: маппинг сигналов секции в внешние сигналы панели (F.6)   #
    # ------------------------------------------------------------------ #

    def _on_target_selected(self, new_process: str) -> None:
        """IPC-таргет выбран → target_process_changed для текущей ноды."""
        if self._current_node_id:
            self.target_process_changed.emit(self._current_node_id, new_process)

    def _on_display_selected(self, display_id: str) -> None:
        """Display выбран → display_id_changed для текущей ноды."""
        if self._current_node_id:
            self.display_id_changed.emit(self._current_node_id, display_id)

    def _on_worker_selected(self, worker: str) -> None:
        """Воркер выбран → persist assigned_worker через field_changed (SetPluginConfig)."""
        if self._current_process:
            self.field_changed.emit(self._current_process, "assigned_worker", worker)

    def _on_lock_set(self, locked: bool) -> None:
        """Кнопки «Закрепить/Открепить» → сигнал для текущей ноды."""
        if self._current_node_id:
            self.node_lock_set_requested.emit(self._current_node_id, locked)

    def _on_bypass_toggled(self, checked: bool) -> None:
        """Тумблер bypass → команда set_enabled в процесс ноды (fire-and-forget).

        checked=True → нода обрабатывает; False → пропускает кадр без обработки.
        Без command_sender (редактор без живого backend) — no-op (нечего слать).
        """
        if self._command_sender is None or not self._current_process or not self._current_plugin_name:
            return
        try:
            self._command_sender.send_command(
                self._current_process,
                "set_enabled",
                {"plugin_name": self._current_plugin_name, "enabled": bool(checked)},
            )
        except Exception:
            logger.debug("set_enabled не отправлен для %s.%s", self._current_process, self._current_plugin_name)

    # ------------------------------------------------------------------ #
    #  Публичный API: show_plugin_node                                     #
    # ------------------------------------------------------------------ #

    def show_plugin_node(
        self,
        node_id: str,
        category: str = "utility",
        target_process: str = "",
        plugin_name: str = "",
        plugins: list[dict[str, Any]] | None = None,
        params: dict[str, Any] | None = None,
        available_processes: list[str] | None = None,
        process_name: str = "",
        plugin_index: int = 0,
    ) -> None:
        """Показать inspector для выбранной плагин-ноды.

        Отображает combo «Процесс назначения» (заполняется из активного рецепта)
        и параметры плагина через CardsFieldFactory или QLineEdit (fallback).

        D.1/D.2: нода = плагин. ``node_id`` = `{process}.{plugin}` (для заголовка),
        ``process_name`` + ``plugin_index`` адресуют конкретный плагин для
        SetPluginConfig (presenter читает current_plugin_index). ``process_name``
        пусто → fallback на node_id (legacy/show_node).

        Args:
            node_id: идентификатор узла (плагин-нода `{process}.{plugin}`).
            category: категория плагина.
            target_process: текущее значение целевого процесса.
            plugin_name: имя плагина (= имя регистра). Поля параметров резолвятся
                ПО НЕМУ через RegistersManager.get_fields — тот же путь, что вкладка
                Plugins. Пусто → fallback на node_id (legacy).
            plugins: список плагинов процесса [{plugin_name, ...}] (для блока «Исполнение»).
            params: dict значений конфигурации ВЫБРАННОГО плагина {field_name: value}.
            available_processes: другие процессы для combo «Перенести в процесс».
            process_name: имя процесса (цель SetPluginConfig). Пусто → node_id.
            plugin_index: индекс выбранного плагина в цепочке процесса.
        """
        self._suppress_changes = True
        try:
            self._mode = "plugin"
            self._current_node_id = node_id
            self._current_process = process_name or node_id
            self._current_plugin_index = plugin_index
            self._current_plugin_name = plugin_name or node_id
            self._placeholder.setVisible(False)
            self._content.setVisible(True)

            # Заголовок
            self._title.setText(node_id)

            # Badge
            color = CATEGORY_COLORS.get(category, "#9e9e9e")
            self._category_badge.setText(category)
            self._category_badge.setStyleSheet(f"background-color: {color}; color: #fff;")

            # Блок «Исполнение»: процесс + воркер/порядок по плагинам (Phase A)
            self._exec_section.setVisible(True)
            self._populate_exec_info(node_id, category, plugins)

            # Селекторы (IPC-таргет + перенос процесса + воркер + фиксация + bypass):
            # секция сама подавляет свои сигналы на время наполнения (Н-6). Форму IPC-таргета
            # показывает только при непустом combo; строку «Процесс / Воркер» — всегда.
            assigned_worker = str((params or {}).get("assigned_worker", "") or "")
            self._selector_section.configure_plugin_mode(
                self._current_process, target_process, available_processes, assigned_worker
            )

            # Форма параметров: заголовки плагинов процесса + поля выбранного плагина.
            # Поля резолвятся по plugin_name (имя регистра), а не node_id: RegistersManager
            # ключует регистры по имени плагина. _current_process остаётся node_id — туда
            # уйдёт SetPluginConfig при правке поля.
            self._params_section.build(plugin_name or node_id, params, plugins)

            # Actual-телеметрия камеры (Phase 3): только для camera_service.
            if (plugin_name or node_id) == "camera_service":
                self._show_camera_actual(self._current_process)
            else:
                self._hide_camera_actual()

            # Контролы камеры Hikvision (поиск/захват/параметры/SDK App) — дублируют
            # секцию Services прямо в карточке ноды. Только для плагина hikvision.
            if (plugin_name or node_id) == "hikvision":
                self._params_section.embed_hikvision(self._services, self._command_sender, self._topology_bridge)

            # io-debug: привязать секцию к io_peek текущего плагина (process+plugin).
            self._io_debug.set_target(self._current_process, plugin_name or node_id)

        finally:
            self._suppress_changes = False

    # ------------------------------------------------------------------ #
    #  Камера: actual-телеметрия (делегаты CamActualSection, F.6)          #
    # ------------------------------------------------------------------ #

    def _hide_camera_actual(self) -> None:
        """Скрыть блок actual и снять подписки (делегат секции)."""
        self._cam_section.hide_and_unbind()

    def dispose(self) -> None:
        """Teardown панели: снять cam-подписки (Н-4). Идемпотентен.

        Делегирует в CamActualSection.dispose() — снимаются только подписки
        (чистый Python), без обращения к возможно уже удалённым Qt-виджетам
        (destroyed-путь). Вызывается из PipelineTab.dispose() (closeEvent / destroyed).
        """
        self._cam_section.dispose()

    def _show_camera_actual(self, process_name: str) -> None:
        """Показать блок actual и привязать метки к state store (делегат секции)."""
        self._cam_section.show_for(process_name)

    def show_display_node(
        self,
        node_id: str,
        display_id: str = "",
        display_name: str = "",
    ) -> None:
        """Показать inspector для display-узла.

        Отображает только combo «Display» заполненный из DisplayRegistry.
        Параметры не показываются (display-узел не имеет настраиваемых полей).

        Args:
            node_id: идентификатор узла.
            display_id: текущий выбранный display_id.
            display_name: имя выбранного дисплея (для отображения).
        """
        self._suppress_changes = True
        try:
            self._mode = "display"
            self._current_node_id = node_id
            self._current_process = node_id
            self._placeholder.setVisible(False)
            self._content.setVisible(True)

            # Заголовок
            title = display_name if display_name else node_id
            self._title.setText(title)

            # Badge — зелёный display
            from ..graph.constants import DISPLAY_CATEGORY_COLOR

            self._category_badge.setText("display")
            self._category_badge.setStyleSheet(f"background-color: {DISPLAY_CATEGORY_COLOR}; color: #fff;")

            # Селекторы: display-режим (combo Display виден, target/move скрыты, populate).
            self._selector_section.configure_display_mode(display_id)

            # Блок «Исполнение» не относится к display-узлам — очистить и спрятать.
            self._clear_exec_info()
            self._exec_section.setVisible(False)
            self._hide_camera_actual()
            self._io_debug.clear_target()  # у display-узла нет плагина → io-debug спит

            # Очистить параметры (у display нет параметров)
            self._clear_params()

        finally:
            self._suppress_changes = False

    def show_node(
        self,
        process_name: str,
        category: str = "utility",
        plugins: list[dict[str, Any]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Показать параметры plugin-узла (алиас для show_plugin_node).

        Обратная совместимость: делегирует в show_plugin_node без target_process.

        Args:
            process_name: имя процесса (используется как node_id).
            category: категория плагина.
            plugins: список плагинов [{plugin_name, ...}].
            params: dict параметров {field_name: value}.
        """
        self.show_plugin_node(
            node_id=process_name,
            category=category,
            target_process="",
            plugins=plugins,
            params=params,
        )

    # ------------------------------------------------------------------ #
    #  Блок «Исполнение» (Phase A, read-only)                              #
    # ------------------------------------------------------------------ #

    def _populate_exec_info(self, process_name: str, node_category: str, plugins: list | None) -> None:
        """Заполнить блок «Исполнение» (делегат ExecInfoSection, F.6)."""
        self._exec_section.populate(process_name, node_category, plugins)

    def _clear_exec_info(self) -> None:
        """Очистить блок «Исполнение» (делегат ExecInfoSection, F.6)."""
        self._exec_section.clear()

    # ------------------------------------------------------------------ #
    #  Селекторы: провайдеры данных + refresh (F.6)                        #
    # ------------------------------------------------------------------ #

    def refresh_display_combo(self) -> None:
        """Обновить combo «Display» при изменении DisplayRegistry (no-op вне display-режима)."""
        if self._mode != "display":
            return
        self._selector_section.refresh_display(self._selector_section.current_display_id())

    # ------------------------------------------------------------------ #
    #  Провайдеры данных для секций (делегаты selectors_data, F.6)         #
    # ------------------------------------------------------------------ #

    def _get_process_names_from_recipe(self) -> list[str]:
        """Имена процессов активного рецепта (делегат selectors_data, F.6)."""
        recipes = self._services.recipes if self._services is not None else None
        return process_names_from_recipe(recipes)

    def _get_display_entries(self) -> list[Any]:
        """Список DisplayEntry из DisplayCatalog (делегат selectors_data, F.6)."""
        displays = self._services.displays if self._services is not None else None
        return display_entries(displays)

    def _get_workers_for_process(self, process_name: str) -> list[str]:
        """Имена воркеров процесса (делегат selectors_data, F.6)."""
        topology = self._services.topology if self._services is not None else None
        return workers_for_process(topology, process_name)

    # ------------------------------------------------------------------ #
    #  Форма параметров: делегаты ParamsFormSection (F.6)                  #
    # ------------------------------------------------------------------ #

    def _on_params_field_changed(self, field_name: str, value: Any) -> None:
        """Переизлучить field_changed секции с адресом процесса (гейт _suppress_changes)."""
        if self._suppress_changes:
            return
        self.field_changed.emit(self._current_process, field_name, value)

    def _clear_params(self) -> None:
        """Очистить форму параметров (делегат ParamsFormSection, F.6)."""
        self._params_section.clear()

    def clear(self) -> None:
        """Очистить inspector (показать placeholder)."""
        self._current_process = ""
        self._current_node_id = ""
        self._placeholder.setVisible(True)
        self._content.setVisible(False)
        self._selector_section.clear()
        self._clear_exec_info()
        self._hide_camera_actual()
        self._io_debug.clear_target()
        self._clear_params()

    @property
    def current_process(self) -> str:
        """Имя текущего отображаемого процесса (цель SetPluginConfig/MovePlugin)."""
        return self._current_process

    @property
    def current_plugin_index(self) -> int:
        """Индекс выбранного плагина в цепочке процесса (D.2).

        Presenter читает это значение в _on_inspector_field_changed, чтобы
        SetPluginConfig адресовал ИМЕННО выбранный плагин (не хардкод index 0).
        """
        return self._current_plugin_index
