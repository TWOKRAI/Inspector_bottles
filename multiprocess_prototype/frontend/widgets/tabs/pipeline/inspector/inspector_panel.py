"""NodeInspectorPanel — панель параметров выбранного узла pipeline.

Task E.1: мигрирован на AppServices DI. set_services(services) вместо
set_context(ctx). RegistersManager и form_context() не покрыты AppServices
Protocol — оставлены как bridge через adapter (TODO Phase G: registers→G.2, form_context→G.4).
"""

from __future__ import annotations

import logging
from collections import namedtuple
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from multiprocess_prototype.domain.app_services import AppServices
    from multiprocess_prototype.frontend.forms.field_editor import FieldEditor

from ..graph.constants import CATEGORY_COLORS

# Thin wrapper для backward compatibility: combo _populate_display_id_combo
# ожидает .id и .name, а DisplaySpec имеет display_id/display_name.
_DisplayEntry = namedtuple("_DisplayEntry", ["id", "name"])

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_process: str = ""
        self._current_node_id: str = ""
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
    ) -> None:
        """Передать AppServices + live RegistersManager (G.2, runtime-dep).

        registers_manager используется в _try_build_cards_editors для получения
        framework FieldInfo (forms-фабрика строит виджеты из FieldInfo, не domain FieldSpec).
        """
        self._services = services
        self._registers_manager = registers_manager

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

        # Scroll area для параметров
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._params_widget = QWidget()
        self._params_layout = QFormLayout(self._params_widget)
        self._params_layout.setContentsMargins(0, 4, 0, 4)
        self._params_layout.setSpacing(6)
        self._scroll.setWidget(self._params_widget)
        content_layout.addWidget(self._scroll, stretch=1)

        self._content.setVisible(False)
        layout.addWidget(self._content, stretch=1)

        # Подключить обработчики изменений combo
        self._target_process_combo.currentIndexChanged.connect(self._on_target_process_combo_changed)
        self._display_id_combo.currentIndexChanged.connect(self._on_display_id_combo_changed)
        self._move_process_combo.currentIndexChanged.connect(self._on_move_process_combo_changed)
        self._move_worker_combo.currentIndexChanged.connect(self._on_move_worker_combo_changed)

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

        finally:
            self._suppress_changes = False

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

    @staticmethod
    def _worker_for_plugin(plugin_category: str, plugin_name: str, step: int, total: int) -> str:
        """Метка воркера плагина — соответствует авто-назначению в GenericProcess.

        source → свой поток source_producer_<name> (параллельно);
        processing → общий pipeline_executor (последовательно, шаг N/total).
        """
        if plugin_category == "source":
            return f"source_producer_{plugin_name} · свой поток (параллельно)"
        if total > 1:
            return f"pipeline_executor · последовательно (шаг {step}/{total})"
        return "pipeline_executor · последовательно"

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
        """Получить имена процессов из активного рецепта.

        Task F.4: использует RecipeStore Protocol (services.recipes.read_raw).

        Returns:
            Список имён процессов или пустой список если недоступно.
        """
        if self._services is None:
            return []

        store = self._services.recipes

        try:
            active_slug = store.get_active()
            if not active_slug:
                return []

            recipe_dict = store.read_raw(active_slug)
            if not isinstance(recipe_dict, dict):
                return []

            blueprint = recipe_dict.get("blueprint", {})
            if not isinstance(blueprint, dict):
                return []

            processes = blueprint.get("processes", [])
            names = []
            for proc in processes:
                if isinstance(proc, dict):
                    name = proc.get("process_name", "")
                else:
                    name = getattr(proc, "process_name", "")
                if name:
                    names.append(name)
            return names

        except Exception:
            logger.debug("Не удалось получить список процессов из рецепта", exc_info=True)
            return []

    def _get_display_entries(self) -> list[Any]:
        """Получить список DisplaySpec из DisplayCatalog (services.displays).

        Returns:
            Список DisplaySpec-like объектов или пустой список если недоступно.
        """
        if self._services is None:
            return []

        try:
            specs = self._services.displays.list_displays()
            # DisplaySpec имеет display_id и display_name. Combo использует .id и .name.
            # Создаём thin wrapper для backward compatibility с combo код.
            result = []
            for spec in specs:
                result.append(_DisplayEntry(id=spec.display_id, name=spec.display_name))
            return result
        except Exception:
            logger.debug("Не удалось получить список дисплеев из реестра", exc_info=True)
            return []

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
        """Имена воркеров процесса из топологии (+ синтетический message_processor).

        Единый источник с вкладкой «Процессы»: services.topology → Process.workers.
        """
        if self._services is None or not process_name:
            return ["message_processor"]
        try:
            topo = self._services.topology.load()
            proc = topo.find_process(process_name)
            workers = [w.worker_name for w in proc.workers] if proc is not None else []
        except Exception:
            logger.debug("Не удалось получить воркеры процесса '%s'", process_name, exc_info=True)
            workers = []
        if "message_processor" not in workers:
            workers.insert(0, "message_processor")
        return workers

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

        while self._params_layout.count():
            item = self._params_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
