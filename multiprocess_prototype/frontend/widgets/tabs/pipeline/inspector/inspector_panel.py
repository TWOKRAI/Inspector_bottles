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
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from multiprocess_prototype.domain.app_services import AppServices
    from multiprocess_prototype.frontend.forms.field_editor import FieldEditor

from ..graph.constants import CATEGORY_COLORS
from .io_debug_section import IoDebugSection
from .selectors_data import (
    DisplayEntry as _DisplayEntry,
    display_entries,
    process_names_from_recipe,
    workers_for_process,
    worker_label,
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
        # Хранит и QLineEdit (fallback) и FieldEditor (cards-режим)
        self._field_editors: dict[str, Any] = {}
        # Флаг: используем типизированные виджеты из CardsFieldFactory
        self._use_cards: bool = False
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
        # Контроллер встроенного виджета Hikvision (держим ссылку, иначе GC).
        self._hik_controller: Any = None
        self._hik_runner: Any = None
        # Текущий режим отображения: "plugin" или "display"
        self._mode: str = "plugin"
        # Combo «Процесс назначения» (для plugin-узлов)
        self._target_process_combo: QComboBox | None = None
        # Combo «Display» (для display-узлов)
        self._display_id_combo: QComboBox | None = None
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
        if bindings is not None:
            self._bindings = bindings
            # io-debug секция подписывается на io_peek через те же bindings.
            self._io_debug.set_bindings(bindings)
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
        # и в каком ВОРКЕРЕ каждый плагин (+ порядок в цепочке). Воркеры сейчас
        # назначаются автоматически в GenericProcess (см. plans/pipeline-node-process-worker.md):
        # source → свой source_producer_<plugin>; processing → общий pipeline_executor
        # (последовательно). Поэтому блок read-only — назначение придёт в Phase C.
        self._exec_info_form = QWidget()
        self._exec_info_layout = QFormLayout(self._exec_info_form)
        self._exec_info_layout.setContentsMargins(0, 0, 0, 0)
        self._exec_info_layout.setSpacing(2)
        content_layout.addWidget(self._exec_info_form)

        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("InspectorDivider")
        content_layout.addWidget(line)

        # Combo «Перенести в процесс» (Phase B): переносит плагины узла в выбранный
        # процесс — несколько плагинов в одном процессе = последовательная цепочка.
        # Первый пункт — плейсхолдер «— перенести в… —» (не вызывает мутацию).
        self._move_process_form = QWidget()
        mp_layout = QFormLayout(self._move_process_form)
        mp_layout.setContentsMargins(0, 0, 0, 0)
        mp_layout.setSpacing(4)
        self._move_process_combo = QComboBox()
        self._move_process_combo.setObjectName("MoveProcessCombo")
        self._move_process_combo.setToolTip(
            "Перенести этот узел (его плагины) в другой процесс. Плагины в одном\n"
            "процессе исполняются последовательно; разные процессы — параллельно."
        )
        # Воркер на той же строке, что и выбор процесса (по запросу владельца):
        # список — воркеры выбранного/текущего процесса (из вкладки «Процессы»).
        self._move_worker_combo = QComboBox()
        self._move_worker_combo.setObjectName("MoveWorkerCombo")
        self._move_worker_combo.setToolTip(
            "Воркер процесса, в котором исполняется узел.\nСписок — воркеры выбранного процесса (вкладка «Процессы»)."
        )
        pw_row = QWidget()
        pw_layout = QHBoxLayout(pw_row)
        pw_layout.setContentsMargins(0, 0, 0, 0)
        pw_layout.setSpacing(6)
        pw_layout.addWidget(self._move_process_combo, 1)
        pw_layout.addWidget(self._move_worker_combo, 1)
        mp_layout.addRow("Процесс / Воркер:", pw_row)

        # Кнопки «Закрепить/Открепить» рядом с выбором процесса/воркера (дубль
        # правого клика по ноде; крупные — для сенсорного экрана). Действуют на
        # текущую ноду (_current_node_id) через node_lock_set_requested.
        self._lock_btn = QPushButton("Закрепить")
        self._lock_btn.setObjectName("NodeLockButton")
        self._lock_btn.setMinimumHeight(40)
        self._lock_btn.setToolTip("Зафиксировать ноду: не двигается и пропускается авто-раскладкой")
        self._unlock_btn = QPushButton("Открепить")
        self._unlock_btn.setObjectName("NodeUnlockButton")
        self._unlock_btn.setMinimumHeight(40)
        self._unlock_btn.setToolTip("Снять фиксацию ноды")
        lock_row = QWidget()
        lock_layout = QHBoxLayout(lock_row)
        lock_layout.setContentsMargins(0, 0, 0, 0)
        lock_layout.setSpacing(6)
        lock_layout.addWidget(self._lock_btn, 1)
        lock_layout.addWidget(self._unlock_btn, 1)
        mp_layout.addRow("Фиксация:", lock_row)

        # Тумблер bypass: снять галку → нода пропускает кадр БЕЗ обработки (live).
        # Нужно, чтобы выключить тяжёлую/зависающую ноду (circle_detector) и спокойно
        # тюнить остальную цепочку (напр. hsv_mask по дисплею «mask»). Команда set_enabled
        # уходит в процесс ноды через command_sender. По умолчанию включена.
        self._bypass_check = QCheckBox("Нода включена (обрабатывает кадр)")
        self._bypass_check.setObjectName("NodeEnabledCheck")
        self._bypass_check.setChecked(True)
        self._bypass_check.setMinimumHeight(32)
        self._bypass_check.setToolTip(
            "Снять галку → нода пропускает кадр без обработки (bypass).\n"
            "Удобно отключить circle_detector, пока настраиваешь hsv-маску."
        )
        mp_layout.addRow("Обработка:", self._bypass_check)

        content_layout.addWidget(self._move_process_form)
        self._move_process_form.setVisible(False)

        # Combo «IPC-таргет команд» (только для plugin-узлов; опциональная маршрутизация
        # команд через target_process — НЕ влияет на то, в каком процессе исполняется нода).
        self._target_process_form = QWidget()
        tp_layout = QFormLayout(self._target_process_form)
        tp_layout.setContentsMargins(0, 0, 0, 0)
        tp_layout.setSpacing(4)
        self._target_process_combo = QComboBox()
        self._target_process_combo.setObjectName("TargetProcessCombo")
        self._target_process_combo.setToolTip(
            "Куда слать команды от плагина (IPC-маршрутизация). НЕ меняет процесс,\n"
            "в котором исполняется нода — назначение процесса/воркера будет в Phase B/C."
        )
        tp_layout.addRow("IPC-таргет команд:", self._target_process_combo)
        content_layout.addWidget(self._target_process_form)
        self._target_process_form.setVisible(False)

        # Combo «Display» (только для display-узлов)
        self._display_id_form = QWidget()
        di_layout = QFormLayout(self._display_id_form)
        di_layout.setContentsMargins(0, 0, 0, 0)
        di_layout.setSpacing(4)
        self._display_id_combo = QComboBox()
        self._display_id_combo.setObjectName("DisplayIdCombo")
        di_layout.addRow("Display:", self._display_id_combo)
        content_layout.addWidget(self._display_id_form)
        self._display_id_form.setVisible(False)

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
        self._params_widget = QWidget()
        self._params_layout = QFormLayout(self._params_widget)
        self._params_layout.setContentsMargins(0, 4, 0, 4)
        self._params_layout.setSpacing(6)
        content_layout.addWidget(self._params_widget, stretch=1)

        # Блок «Камера (actual)» — read-only телеметрия что камера реально применила
        # (cap.get), привязка к state store processes.{proc}.state.cam.actual.*.
        # Показывается только для camera_service-ноды (см. _show_camera_actual).
        self._cam_actual_form = QWidget()
        self._cam_actual_layout = QFormLayout(self._cam_actual_form)
        self._cam_actual_layout.setContentsMargins(0, 4, 0, 4)
        self._cam_actual_layout.setSpacing(2)
        self._cam_actual_labels: dict[str, QLabel] = {}
        cam_title = QLabel("Камера (actual)")
        cam_title.setProperty("role", "plugin-name")
        self._cam_actual_layout.addRow(cam_title)
        for key, caption in (
            ("fps", "FPS:"),
            ("resolution", "Разрешение:"),
            ("exposure", "Экспозиция:"),
            ("gain", "Усиление:"),
            ("fourcc", "Кодек:"),
        ):
            lbl = QLabel("—")
            self._cam_actual_labels[key] = lbl
            self._cam_actual_layout.addRow(caption, lbl)
        content_layout.addWidget(self._cam_actual_form)
        self._cam_actual_form.setVisible(False)
        # Дескрипторы активных подписок actual (для отписки при смене ноды)
        self._cam_actual_handles: list[Any] = []

        # Секция «I/O (debug)» — generic наблюдение in/out плагина (в самом низу карточки).
        # bindings придут позже через set_services → set_bindings.
        self._io_debug = IoDebugSection()
        content_layout.addWidget(self._io_debug)

        self._content.setVisible(False)
        layout.addWidget(self._content, stretch=1)

        # Подключить обработчики изменений combo
        self._target_process_combo.currentIndexChanged.connect(self._on_target_process_combo_changed)
        self._display_id_combo.currentIndexChanged.connect(self._on_display_id_combo_changed)
        self._move_process_combo.currentIndexChanged.connect(self._on_move_process_combo_changed)
        self._move_worker_combo.currentIndexChanged.connect(self._on_move_worker_combo_changed)
        self._lock_btn.clicked.connect(lambda: self._emit_lock(True))
        self._unlock_btn.clicked.connect(lambda: self._emit_lock(False))
        self._bypass_check.toggled.connect(self._on_bypass_toggled)

    def _on_bypass_toggled(self, checked: bool) -> None:
        """Тумблер bypass → команда set_enabled в процесс ноды (fire-and-forget).

        checked=True → нода обрабатывает; False → пропускает кадр без обработки.
        Без command_sender (редактор без живого backend) — no-op (нечего слать).
        """
        if self._suppress_changes:
            return
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

    def _emit_lock(self, locked: bool) -> None:
        """Кнопки «Закрепить/Открепить» → сигнал для текущей ноды."""
        if self._current_node_id:
            self.node_lock_set_requested.emit(self._current_node_id, locked)

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
            # Сброс тумблера bypass в «включено» при выборе ноды (readback живого
            # состояния пока нет — дефолт enabled; signal подавлен, чтобы не слать команду).
            self._bypass_check.setChecked(True)
            self._placeholder.setVisible(False)
            self._content.setVisible(True)

            # Заголовок
            self._title.setText(node_id)

            # Badge
            color = CATEGORY_COLORS.get(category, "#9e9e9e")
            self._category_badge.setText(category)
            self._category_badge.setStyleSheet(f"background-color: {color}; color: #fff;")

            # Блок «Исполнение»: процесс + воркер/порядок по плагинам (Phase A)
            self._exec_info_form.setVisible(True)
            self._populate_exec_info(node_id, category, plugins)

            # Скрыть display-combo
            self._display_id_form.setVisible(False)

            # Заполнить combo IPC-таргета из активного рецепта. Показываем форму ТОЛЬКО
            # если есть что выбрать (иначе пустой disabled combo путает — это и была
            # жалоба «почему не могу поменять»: combo не про исполнение и часто пуст).
            self._populate_target_process_combo(target_process)
            has_targets = bool(self._target_process_combo and self._target_process_combo.isEnabled())
            self._target_process_form.setVisible(has_targets)

            # Строка «Процесс / Воркер»: combo переноса в процесс + combo воркера.
            # Воркер-combo заполняем воркерами ТЕКУЩЕГО процесса, preselect из config
            # (assigned_worker). Строку показываем всегда в plugin-режиме — выбор воркера
            # релевантен независимо от наличия других процессов для переноса.
            self._suppress_changes = True
            try:
                self._populate_move_process_combo(available_processes)
                assigned_worker = str((params or {}).get("assigned_worker", "") or "")
                self._populate_move_worker_combo(self._current_process, assigned_worker)
            finally:
                self._suppress_changes = False
            self._move_process_form.setVisible(True)

            # Показать параметры плагина в scroll area
            self._clear_params()
            if plugins:
                for p in plugins:
                    pname = p.get("plugin_name", "") if isinstance(p, dict) else str(p)
                    label = QLabel(pname)
                    label.setProperty("role", "plugin-name")
                    self._params_layout.addRow(label)

            # Поля строим по plugin_name (имя регистра), а не node_id (process_name):
            # RegistersManager ключует регистры по имени плагина. _current_process
            # остаётся node_id — туда уйдёт SetPluginConfig при правке поля.
            fields_used = self._try_build_cards_editors(plugin_name or node_id, params)
            self._use_cards = bool(fields_used)

            if not self._use_cards and params:
                self._build_lineedit_editors(params)

            # Actual-телеметрия камеры (Phase 3): только для camera_service.
            if (plugin_name or node_id) == "camera_service":
                self._show_camera_actual(self._current_process)
            else:
                self._hide_camera_actual()

            # Контролы камеры Hikvision (поиск/захват/параметры/SDK App) — дублируют
            # секцию Services прямо в карточке ноды. Только для плагина hikvision.
            if (plugin_name or node_id) == "hikvision":
                self._embed_hikvision_controls()

            # io-debug: привязать секцию к io_peek текущего плагина (process+plugin).
            self._io_debug.set_target(self._current_process, plugin_name or node_id)

        finally:
            self._suppress_changes = False

    # ------------------------------------------------------------------ #
    #  Камера: actual-телеметрия (Phase 3)                                 #
    # ------------------------------------------------------------------ #

    def _unbind_camera_actual(self) -> None:
        """Снять подписки actual-телеметрии (баланс bind/unbind, волна B Н-4).

        GuiStateBindings.unbind() не бросает (ValueError ловится внутри),
        поэтому прежний широкий ``except Exception: pass`` убран. Чистый Python
        (без Qt-вызовов) — безопасно и после разрушения виджетов (destroyed-путь).
        """
        if self._bindings is not None:
            for h in self._cam_actual_handles:
                self._bindings.unbind(h)
        self._cam_actual_handles = []

    def _hide_camera_actual(self) -> None:
        """Скрыть блок actual и снять подписки."""
        self._unbind_camera_actual()
        self._cam_actual_form.setVisible(False)
        for lbl in self._cam_actual_labels.values():
            lbl.setText("—")

    def dispose(self) -> None:
        """Teardown панели: снять cam-подписки (волна B, Н-4). Идемпотентен.

        При разрушении панели с активной camera-нодой bind-хэндлы оставались
        жить в GuiStateBindings (утечка + обновление мёртвых QLabel через
        weakref). Вызывается из PipelineTab.dispose() (closeEvent / destroyed).
        Намеренно НЕ зовёт _hide_camera_actual целиком: в destroyed-пути
        дочерние Qt-виджеты уже удалены, setVisible/setText дали бы RuntimeError —
        снимаем только подписки (чистый Python).
        """
        self._unbind_camera_actual()

    def _show_camera_actual(self, process_name: str) -> None:
        """Показать блок actual и привязать метки к state store.

        Пути: processes.{proc}.state.cam.actual.{fps,width,height,exposure,gain,fourcc}.
        Разрешение собирается из width+height отдельным форматтером на оба пути.
        """
        self._hide_camera_actual()
        if self._bindings is None or not process_name:
            # Без bindings actual недоступен (нет live-подписки) — блок не показываем.
            return
        self._cam_actual_form.setVisible(True)
        base = f"processes.{process_name}.state.cam.actual"

        def _num(lbl: QLabel, unit: str = ""):
            return lambda v: f"{float(v):.0f}{unit}" if isinstance(v, (int, float)) else str(v)

        self._cam_actual_handles.append(
            self._bindings.bind(
                f"{base}.fps",
                self._cam_actual_labels["fps"],
                "text",
                formatter=_num(self._cam_actual_labels["fps"], " fps"),
            )
        )
        self._cam_actual_handles.append(
            self._bindings.bind(
                f"{base}.exposure",
                self._cam_actual_labels["exposure"],
                "text",
                formatter=_num(self._cam_actual_labels["exposure"]),
            )
        )
        self._cam_actual_handles.append(
            self._bindings.bind(
                f"{base}.gain", self._cam_actual_labels["gain"], "text", formatter=_num(self._cam_actual_labels["gain"])
            )
        )
        self._cam_actual_handles.append(
            self._bindings.bind(f"{base}.fourcc", self._cam_actual_labels["fourcc"], "text")
        )
        # Разрешение: width и height приходят раздельно → обновляем общую метку.
        self._cam_res = {"width": 0, "height": 0}

        def _res_update(key):
            def _fmt(v):
                try:
                    self._cam_res[key] = int(float(v))
                except (TypeError, ValueError):
                    pass
                return f"{self._cam_res['width']}×{self._cam_res['height']}"

            return _fmt

        self._cam_actual_handles.append(
            self._bindings.bind(
                f"{base}.width", self._cam_actual_labels["resolution"], "text", formatter=_res_update("width")
            )
        )
        self._cam_actual_handles.append(
            self._bindings.bind(
                f"{base}.height", self._cam_actual_labels["resolution"], "text", formatter=_res_update("height")
            )
        )

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

            # Показать display-combo, скрыть target_process / move-process combo
            self._target_process_form.setVisible(False)
            self._move_process_form.setVisible(False)
            self._display_id_form.setVisible(True)

            # Блок «Исполнение» не относится к display-узлам — очистить и спрятать.
            self._clear_exec_info()
            self._exec_info_form.setVisible(False)
            self._hide_camera_actual()
            self._io_debug.clear_target()  # у display-узла нет плагина → io-debug спит

            # Заполнить combo из DisplayRegistry
            self._populate_display_id_combo(display_id)

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

    # Тонкий делегат на чистую функцию selectors_data.worker_label (F.6).
    # Оставлен как staticmethod для совместимости со стабильными швами тестов.
    _worker_for_plugin = staticmethod(worker_label)

    def _populate_exec_info(
        self,
        process_name: str,
        node_category: str,
        plugins: list | None,
    ) -> None:
        """Заполнить блок «Исполнение»: процесс + воркер/порядок по плагинам.

        Read-only (Phase A): воркеры назначаются автоматически в GenericProcess,
        смена процесса/воркера придёт в Phase B/C (plans/pipeline-node-process-worker.md).
        """
        self._clear_exec_info()

        proc_value = QLabel(process_name)
        proc_value.setProperty("role", "exec-process")
        self._exec_info_layout.addRow("Процесс:", proc_value)

        plugin_list = plugins or []
        # Шаг считаем только среди processing-плагинов (источники независимы, свой поток).
        processing_total = sum(
            1 for p in plugin_list if ((p.get("category") if isinstance(p, dict) else "") or node_category) != "source"
        )
        step = 0
        for p in plugin_list:
            if isinstance(p, dict):
                pname = p.get("plugin_name", "")
                pcat = p.get("category") or node_category
            else:
                pname = str(p)
                pcat = node_category
            if pcat != "source":
                step += 1
                worker = self._worker_for_plugin(pcat, pname, step, processing_total)
            else:
                worker = self._worker_for_plugin("source", pname, 0, 0)
            self._exec_info_layout.addRow(f"{pname}:", QLabel(worker))

    def _clear_exec_info(self) -> None:
        """Очистить строки блока «Исполнение»."""
        while self._exec_info_layout.count():
            item = self._exec_info_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    # ------------------------------------------------------------------ #
    #  Заполнение combo                                                    #
    # ------------------------------------------------------------------ #

    def _populate_target_process_combo(self, current_value: str = "") -> None:
        """Заполнить combo «Процесс назначения» именами процессов из рецепта.

        Если RecipeManager или активный рецепт недоступны — combo пустое и disabled.

        Args:
            current_value: текущее значение, которое нужно выбрать.
        """
        combo = self._target_process_combo
        if combo is None:
            return

        combo.clear()
        process_names = self._get_process_names_from_recipe()

        if not process_names:
            combo.setEnabled(False)
            return

        combo.setEnabled(True)
        for name in process_names:
            combo.addItem(name)

        # Установить текущее значение
        if current_value:
            idx = combo.findText(current_value)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _populate_display_id_combo(self, current_display_id: str = "") -> None:
        """Заполнить combo «Display» из DisplayRegistry.

        Если DisplayRegistry недоступен — combo пустое и disabled.

        Args:
            current_display_id: текущий выбранный display_id.
        """
        combo = self._display_id_combo
        if combo is None:
            return

        combo.clear()
        entries = self._get_display_entries()

        if not entries:
            combo.setEnabled(False)
            return

        combo.setEnabled(True)
        for entry in entries:
            label = f"{entry.name} ({entry.id})" if entry.name else entry.id
            combo.addItem(label, userData=entry.id)

        # Установить текущее значение
        if current_display_id:
            for i in range(combo.count()):
                if combo.itemData(i) == current_display_id:
                    combo.setCurrentIndex(i)
                    break

    def refresh_display_combo(self) -> None:
        """Обновить combo «Display» при изменении DisplayRegistry.

        Вызывается при подписке на state.displays.changed.
        Работает только в режиме display (иначе no-op).
        """
        if self._mode != "display":
            return
        # Получить текущий выбранный display_id
        current_id = ""
        if self._display_id_combo is not None:
            idx = self._display_id_combo.currentIndex()
            if idx >= 0:
                current_id = self._display_id_combo.itemData(idx) or ""

        self._suppress_changes = True
        try:
            self._populate_display_id_combo(current_id)
        finally:
            self._suppress_changes = False

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы: получение данных из контекста               #
    # ------------------------------------------------------------------ #

    def _get_process_names_from_recipe(self) -> list[str]:
        """Имена процессов активного рецепта (делегат selectors_data, F.6)."""
        recipes = self._services.recipes if self._services is not None else None
        return process_names_from_recipe(recipes)

    def _get_display_entries(self) -> list[Any]:
        """Список DisplayEntry из DisplayCatalog (делегат selectors_data, F.6)."""
        displays = self._services.displays if self._services is not None else None
        return display_entries(displays)

    # ------------------------------------------------------------------ #
    #  Обработчики сигналов combo                                          #
    # ------------------------------------------------------------------ #

    def _on_target_process_combo_changed(self, index: int) -> None:
        """Обработчик выбора процесса в combo «Процесс назначения»."""
        if self._suppress_changes:
            return
        if self._target_process_combo is None:
            return
        new_process = self._target_process_combo.currentText()
        if new_process and self._current_node_id:
            self.target_process_changed.emit(self._current_node_id, new_process)

    def _on_display_id_combo_changed(self, index: int) -> None:
        """Обработчик выбора display в combo «Display»."""
        if self._suppress_changes:
            return
        if self._display_id_combo is None:
            return
        new_display_id = self._display_id_combo.itemData(index) or ""
        if new_display_id and self._current_node_id:
            self.display_id_changed.emit(self._current_node_id, new_display_id)

    def _populate_move_process_combo(self, available_processes: list[str] | None) -> None:
        """Заполнить combo «Перенести в процесс» (Phase B).

        Первый пункт — плейсхолдер (userData=""), не вызывает мутацию.
        """
        combo = self._move_process_combo
        if combo is None:
            return
        combo.clear()
        combo.addItem("— перенести в… —", userData="")
        for name in available_processes or []:
            combo.addItem(name, userData=name)
        combo.setCurrentIndex(0)

    def _on_move_process_combo_changed(self, index: int) -> None:
        """Обработчик выбора процесса-приёмника (Phase B) → move_to_process_requested.

        D.1: эмитим ИМЯ ПРОЦЕССА (_current_process), а не node_id плагин-ноды —
        presenter._on_move_to_process_requested ждёт from_process. Per-plugin drag
        (D.3) — основной путь; combo переносит весь процесс (его плагины).
        """
        if self._suppress_changes:
            return
        if self._move_process_combo is None:
            return
        to_process = self._move_process_combo.itemData(index) or ""
        # Воркер-combo всегда отражает воркеры РЕЛЕВАНТНОГО процесса: выбранного в
        # combo, либо текущего (когда плейсхолдер). Перезаполняем при смене процесса.
        self._suppress_changes = True
        try:
            self._populate_move_worker_combo(to_process or self._current_process)
        finally:
            self._suppress_changes = False
        if to_process and self._current_process and to_process != self._current_process:
            self.move_to_process_requested.emit(self._current_process, to_process)

    def _get_workers_for_process(self, process_name: str) -> list[str]:
        """Имена воркеров процесса (делегат selectors_data, F.6)."""
        topology = self._services.topology if self._services is not None else None
        return workers_for_process(topology, process_name)

    def _populate_move_worker_combo(self, process_name: str, current_worker: str = "") -> None:
        """Заполнить воркер-combo воркерами процесса. Пусто/нет процесса → message_processor."""
        combo = self._move_worker_combo
        if combo is None:
            return
        combo.clear()
        workers = self._get_workers_for_process(process_name)
        combo.setEnabled(bool(workers))
        for name in workers:
            combo.addItem(name, userData=name)
        if current_worker:
            idx = combo.findData(current_worker)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _on_move_worker_combo_changed(self, index: int) -> None:
        """Выбор воркера → персист assigned_worker в config плагина (через field_changed).

        Переиспользуем существующий путь field_changed → SetPluginConfig (G.4.3):
        assigned_worker сохраняется в config плагина editor-топологии. Runtime-
        исполнение по этому полю — отдельный шаг (см. plans/pipeline-node-process-worker.md).
        """
        if self._suppress_changes:
            return
        if self._move_worker_combo is None:
            return
        worker = self._move_worker_combo.itemData(index) or ""
        if worker and self._current_process:
            self.field_changed.emit(self._current_process, "assigned_worker", worker)

    # ------------------------------------------------------------------ #
    #  Оригинальные методы (backward compatibility)                        #
    # ------------------------------------------------------------------ #

    def _try_build_cards_editors(
        self,
        plugin_name: str,
        params: dict[str, Any] | None,
    ) -> bool:
        """Попытаться создать типизированные виджеты через CardsFieldFactory.

        Args:
            plugin_name: имя плагина (= имя регистра). RegistersManager ключует
                регистры по имени плагина — тот же путь, что вкладка Plugins
                (PluginsPresenter.get_register_fields). НЕ имя процесса.

        Returns:
            True если виджеты успешно созданы, False — нужен fallback.
        """
        if self._services is None:
            return False

        # G.2: live RegistersManager — explicit runtime-dep (через set_services, Q-F1=B).
        # forms-фабрике нужен framework FieldInfo (get_fields), который domain RegistersBackend
        # не может экспонировать (FieldSpec lossy + запрет импорта framework в domain).
        rm = self._registers_manager
        if rm is None:
            return False

        # FieldInfo из RegistersManager по имени ПЛАГИНА (= имя регистра).
        fields = rm.get_fields(plugin_name)
        if not fields:
            return False

        from multiprocess_prototype.frontend.forms.factory import CardsFieldFactory

        # TODO Phase G (G.4): form_context() не покрыт AppServices Protocol.
        # Для binding-aware editors нужен form_ctx. Пока — None (legacy путь).
        form_ctx = None

        for field_info in fields:
            editor = CardsFieldFactory.create(
                field_info,
                parent=self._params_widget,
                form_ctx=form_ctx,
            )

            # Установить значение из params если передан
            if params and field_info.field_name in params:
                try:
                    editor.setter(params[field_info.field_name])
                except Exception:
                    logger.debug(
                        "Не удалось установить значение '%s' для поля '%s'",
                        params[field_info.field_name],
                        field_info.field_name,
                    )

            # Подключить сигнал изменения если есть
            if editor.change_signal is not None:
                fn = field_info.field_name
                editor.change_signal.connect(lambda *_args, _fn=fn, _ed=editor: self._on_field_editor_changed(_fn, _ed))

            self._field_editors[field_info.field_name] = editor
            self._params_layout.addRow(editor.label, editor.widget)

        return True

    def _embed_hikvision_controls(self) -> None:
        """Встроить контролы камеры Hikvision (поиск/захват/параметры/SDK App).

        Дублирует Services-секцию «Hikvision Camera» прямо в карточке ноды.
        Требует command_sender/topology_bridge (через set_services из RuntimeDeps);
        без них кнопки дадут понятный статус «нет процесса камеры».
        """
        from types import SimpleNamespace

        from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner
        from multiprocess_prototype.frontend.widgets.tabs.services.hikvision.controller import (
            build_hikvision_controls,
        )

        runtime = SimpleNamespace(
            command_sender=self._command_sender,
            topology_bridge=self._topology_bridge,
        )
        self._hik_runner = RequestRunner()
        widget, controller = build_hikvision_controls(
            services=self._services,
            runtime=runtime,
            request_runner=self._hik_runner,
        )
        self._hik_runner.setParent(widget)
        self._hik_controller = controller
        # Вставляем контролы первой строкой params (над register-полями плагина).
        self._params_layout.insertRow(0, widget)

    def _build_lineedit_editors(self, params: dict[str, Any]) -> None:
        """Создать QLineEdit-редакторы (fallback если CardsFieldFactory недоступен)."""
        for field_name, value in params.items():
            editor = QLineEdit(str(value))
            editor.setProperty("field_name", field_name)
            editor.editingFinished.connect(lambda fn=field_name, ed=editor: self._on_field_edited(fn, ed))
            self._field_editors[field_name] = editor
            self._params_layout.addRow(field_name, editor)

    def clear(self) -> None:
        """Очистить inspector (показать placeholder)."""
        self._current_process = ""
        self._current_node_id = ""
        self._placeholder.setVisible(True)
        self._content.setVisible(False)
        self._target_process_form.setVisible(False)
        self._move_process_form.setVisible(False)
        self._display_id_form.setVisible(False)
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

    def _on_field_edited(self, field_name: str, editor: QLineEdit) -> None:
        """Обработчик изменения поля пользователем (QLineEdit fallback)."""
        if self._suppress_changes:
            return
        value = editor.text()
        self.field_changed.emit(self._current_process, field_name, value)

    def _on_field_editor_changed(self, field_name: str, editor: "FieldEditor") -> None:
        """Обработчик изменения поля через FieldEditor (cards-режим).

        Args:
            field_name: имя поля.
            editor: FieldEditor, у которого сработал change_signal.
        """
        if self._suppress_changes:
            return
        value = editor.getter()
        self.field_changed.emit(self._current_process, field_name, value)

    def _clear_params(self) -> None:
        """Удалить все виджеты параметров.

        Для FieldEditor: отключаем change_signal перед удалением
        чтобы избежать утечек сигналов при переключении нод.
        """
        for field_name, editor in self._field_editors.items():
            if not isinstance(editor, QLineEdit):
                # FieldEditor — отключаем change_signal
                try:
                    if editor.change_signal is not None:
                        editor.change_signal.disconnect()
                except (RuntimeError, TypeError):
                    pass  # Уже отключён или C++ объект удалён

        self._field_editors.clear()
        self._use_cards = False
        # Сбросить ссылки на встроенные контролы Hikvision (виджеты удалит цикл ниже).
        self._hik_controller = None
        self._hik_runner = None

        while self._params_layout.count():
            item = self._params_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
