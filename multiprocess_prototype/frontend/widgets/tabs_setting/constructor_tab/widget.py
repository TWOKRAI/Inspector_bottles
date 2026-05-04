"""ConstructorTabWidget -- вкладка визуального конструктора.

Фаза 2: NodeGraphQt канвас с процессами-как-нодами + toolbar.
Фаза 3: правые панели (ProcessPluginPanel, WireInspectorPanel) + Save/Load Blueprint.
Фаза 5: ShmDashboardPanel — страница 3, кнопка "SHM" в toolbar.

Структура:
  ┌─────────────────────────────────────────────────────────────┐
  │ Toolbar: [Обновить][Авто-layout][Вписать][Проверить]       │
  │          [Сохранить Blueprint][Загрузить Blueprint][SHM]    │
  ├────────────────────────────────┬────────────────────────────┤
  │                                │  QStackedWidget:           │
  │    NodeGraphQt канвас          │    0: Placeholder          │
  │   (процессы-ноды, wires)       │    1: ProcessPluginPanel   │
  │                                │    2: WireInspectorPanel   │
  │                                │    3: ShmDashboardPanel    │
  └────────────────────────────────┴────────────────────────────┘
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.bridges.wire_data_bridge import WireDataBridge
from multiprocess_prototype.registers.system_topology.schemas import (
    SECTION_DISPLAYS,
    SECTION_PROCESSES,
    SECTION_WIRES,
)

from .panels.process_plugin_panel import ProcessPluginPanel
from .panels.shm_dashboard_panel import ShmDashboardPanel
from .panels.wire_inspector import WireInspectorPanel

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.models.system_topology_editor import (
        SystemTopologyEditor,
    )

logger = logging.getLogger(__name__)

# Индексы страниц QStackedWidget
_PAGE_PLACEHOLDER = 0
_PAGE_PROCESS = 1
_PAGE_WIRE = 2
_PAGE_DASHBOARD = 3


class ConstructorTabWidget(QWidget):
    """Вкладка визуального конструктора межпроцессных связей.

    Позволяет собирать систему из процессов, плагинов и wire-соединений
    через визуальный граф-редактор (NodeGraphQt).

    Данные: единое дерево SystemTopologyEditor.
    Канвас синхронизируется через PluginGraphAdapter.

    Args:
        topology_editor: Центральная модель конфигурации системы.
        topology_bridge: Мост для применения конфигурации (Apply).
        command_handler: Отправка команд в ProcessManager.
    """

    def __init__(
        self,
        topology_editor: SystemTopologyEditor,
        topology_bridge: Any = None,
        command_handler: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._editor = topology_editor
        self._bridge = topology_bridge
        self._command_handler = command_handler

        # Компоненты (создаются в _init_canvas)
        self._adapter = None
        self._cross_model = None
        self._wire_model = None
        self._graph = None
        self._graph_widget = None

        # Guard: ключ процесса для восстановления выделения после rebuild
        self._pending_reselect: str | None = None

        # Мост мониторинга wire-статусов (graceful: работает без command_handler)
        self._wire_bridge = WireDataBridge(
            command_handler=command_handler,
            topology_editor=topology_editor,
            parent=self,
        )

        self._init_ui()
        self._subscribe_to_topology()

    def _init_ui(self) -> None:
        """Инициализация UI: toolbar + canvas + правая панель."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        self._toolbar = self._create_toolbar()
        layout.addWidget(self._toolbar)

        # Основная область: splitter (canvas + правая панель)
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Canvas (NodeGraphQt или fallback)
        canvas_widget = self._create_canvas()
        self._splitter.addWidget(canvas_widget)

        # Правая панель — QStackedWidget с панелями
        right_panel = self._create_right_panel()
        self._splitter.addWidget(right_panel)

        # Пропорции: 75% canvas, 25% правая панель
        self._splitter.setSizes([750, 250])

        layout.addWidget(self._splitter)

        logger.info("ConstructorTabWidget: инициализирован (Фаза 3)")

    def _create_toolbar(self) -> QToolBar:
        """Создать toolbar с кнопками управления."""
        toolbar = QToolBar("Конструктор", self)
        toolbar.setMovable(False)

        # Обновить канвас
        btn_refresh = QPushButton("Обновить")
        btn_refresh.setToolTip("Перестроить канвас из текущей конфигурации")
        btn_refresh.clicked.connect(self._on_refresh)
        toolbar.addWidget(btn_refresh)

        toolbar.addSeparator()

        # Авто-расположение
        btn_layout = QPushButton("Авто-layout")
        btn_layout.setToolTip("Автоматическое расположение нод (Sugiyama)")
        btn_layout.clicked.connect(self._on_auto_layout)
        toolbar.addWidget(btn_layout)

        # Подогнать вид
        btn_fit = QPushButton("Вписать")
        btn_fit.setToolTip("Подогнать масштаб под все ноды")
        btn_fit.clicked.connect(self._on_fit_view)
        toolbar.addWidget(btn_fit)

        toolbar.addSeparator()

        # Валидация
        btn_validate = QPushButton("Проверить")
        btn_validate.setToolTip("Валидация wire-соединений")
        btn_validate.clicked.connect(self._on_validate)
        toolbar.addWidget(btn_validate)

        toolbar.addSeparator()

        # Применить wire-конфигурацию в runtime
        btn_apply = QPushButton("Применить")
        btn_apply.setToolTip("Применить wire-конфигурацию в runtime")
        btn_apply.clicked.connect(self._on_apply_wires)
        toolbar.addWidget(btn_apply)

        toolbar.addSeparator()

        # Save/Load Blueprint
        btn_save = QPushButton("Сохранить Blueprint")
        btn_save.setToolTip("Сохранить конфигурацию системы в JSON-файл")
        btn_save.clicked.connect(self._on_save_blueprint)
        toolbar.addWidget(btn_save)

        btn_load = QPushButton("Загрузить Blueprint")
        btn_load.setToolTip("Загрузить конфигурацию системы из JSON-файла")
        btn_load.clicked.connect(self._on_load_blueprint)
        toolbar.addWidget(btn_load)

        toolbar.addSeparator()

        # SHM Dashboard toggle
        self._btn_shm = QPushButton("SHM")
        self._btn_shm.setCheckable(True)
        self._btn_shm.setToolTip("Показать/скрыть SHM Dashboard (мониторинг буферов)")
        self._btn_shm.clicked.connect(self._on_toggle_dashboard)
        toolbar.addWidget(self._btn_shm)

        toolbar.addSeparator()

        # Статус
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #888; padding-left: 12px;")
        toolbar.addWidget(self._status_label)

        return toolbar

    def _create_canvas(self) -> QWidget:
        """Создать NodeGraphQt канвас или fallback-заглушку."""
        try:
            return self._init_canvas()
        except Exception as exc:
            logger.warning(
                "ConstructorTabWidget: NodeGraphQt недоступен — %s. "
                "Отображаем fallback.",
                exc,
            )
            return self._create_fallback_canvas()

    def _init_canvas(self) -> QWidget:
        """Инициализация NodeGraphQt канваса + adapter + models."""
        from NodeGraphQt import NodeGraph

        from multiprocess_prototype.frontend.models.wire_model import WireEditorModel
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_graph_adapter import (
            PluginGraphAdapter,
        )
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_process_node import (
            PluginProcessNode,
        )
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.shm_route_node import (
            ShmRouteNode,
        )
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.models.cross_process_model import (
            CrossProcessModel,
        )

        # Создаём NodeGraphQt граф
        self._graph = NodeGraph()
        self._graph.set_background_color(30, 30, 30)
        self._graph.set_grid_mode(1)  # Точечная сетка

        # Регистрируем кастомные типы нод
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.display_target_node import (
            DisplayTargetNode,
        )

        self._graph.register_node(PluginProcessNode)
        self._graph.register_node(ShmRouteNode)  # fan-out route-нода
        self._graph.register_node(DisplayTargetNode)  # display target-нода

        # Модели данных (всё через единое дерево topology editor)
        self._cross_model = CrossProcessModel(self._editor)
        self._wire_model = WireEditorModel(self._editor.wires_section)

        # Адаптер — связка NodeGraphQt ↔ WireEditorModel
        self._adapter = PluginGraphAdapter(
            graph=self._graph,
            wire_model=self._wire_model,
            cross_model=self._cross_model,
            topology_editor=self._editor,
            parent=self,
        )

        # Подключаем сигналы адаптера к правой панели
        self._adapter.wire_rejected.connect(self._on_wire_rejected)
        self._adapter.node_selected.connect(self._on_node_selected)
        self._adapter.wire_selected.connect(self._on_wire_selected)
        self._adapter.selection_cleared.connect(self._on_selection_cleared)

        # Подключаем WireDataBridge — обновление цветов pipes при смене статусов
        self._wire_bridge.statuses_changed.connect(self._on_wire_statuses_changed)
        # Подключаем WireDataBridge — обновление метрик badges при смене метрик
        self._wire_bridge.metrics_changed.connect(self._on_wire_metrics_changed)

        # Получаем Qt-виджет канваса
        self._graph_widget = self._graph.widget
        self._graph_widget.setMinimumSize(400, 300)

        # Загружаем текущее состояние
        self._adapter.load_scene()

        return self._graph_widget

    def _create_fallback_canvas(self) -> QWidget:
        """Fallback при отсутствии NodeGraphQt."""
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        label = QLabel(
            "Конструктор межпроцессных связей\n\n"
            "NodeGraphQt не удалось инициализировать.\n"
            "Проверьте установку: pip install NodeGraphQt\n\n"
            "Данные wire-соединений доступны через SystemTopologyEditor."
        )
        label.setStyleSheet("color: #888; font-size: 14px; padding: 40px;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        return widget

    # ------------------------------------------------------------------
    # Правая панель — QStackedWidget (Фаза 3)
    # ------------------------------------------------------------------

    def _create_right_panel(self) -> QWidget:
        """Создать правую панель с QStackedWidget (placeholder / process / wire)."""
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Заголовок
        title = QLabel("Свойства")
        title.setStyleSheet(
            "font-weight: bold; font-size: 13px; padding: 8px 8px 4px 8px;"
        )
        layout.addWidget(title)

        # QStackedWidget с тремя страницами
        self._stack = QStackedWidget(self)

        # Страница 0: Placeholder
        placeholder = self._create_placeholder_page()
        self._stack.addWidget(placeholder)  # index 0

        # Страница 1: ProcessPluginPanel
        self._process_panel = ProcessPluginPanel(self)
        self._process_panel.process_changed.connect(self._on_process_panel_changed)
        self._stack.addWidget(self._process_panel)  # index 1

        # Страница 2: WireInspectorPanel
        self._wire_panel = WireInspectorPanel(self)
        self._wire_panel.wire_changed.connect(self._on_wire_panel_changed)
        self._stack.addWidget(self._wire_panel)  # index 2

        # Страница 3: SHM Dashboard
        self._shm_dashboard = ShmDashboardPanel(self)
        self._stack.addWidget(self._shm_dashboard)  # index 3

        self._stack.setCurrentIndex(_PAGE_PLACEHOLDER)
        layout.addWidget(self._stack)

        widget.setMinimumWidth(200)
        widget.setMaximumWidth(450)

        return widget

    def _create_placeholder_page(self) -> QWidget:
        """Страница-заглушка: ничего не выбрано."""
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)

        info = QLabel(
            "Выберите процесс или\nwire-соединение на канвасе\n"
            "для просмотра свойств."
        )
        info.setStyleSheet("color: #888; padding: 16px;")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)
        layout.addStretch()

        return page

    # ------------------------------------------------------------------
    # Подписки на topology editor (единое дерево данных)
    # ------------------------------------------------------------------

    def _subscribe_to_topology(self) -> None:
        """Подписаться на изменения в секциях processes, wires и displays."""
        self._editor.subscribe(SECTION_PROCESSES, self._on_processes_changed)
        self._editor.subscribe(SECTION_WIRES, self._on_wires_changed)
        self._editor.subscribe(SECTION_DISPLAYS, self._on_displays_changed)

    def _on_processes_changed(self) -> None:
        """Секция processes изменилась — перестроить канвас."""
        if self._adapter is not None:
            # Guard: запомнить текущий выбранный процесс для восстановления
            if self._stack.currentIndex() == _PAGE_PROCESS:
                self._pending_reselect = self._process_panel.current_proc_key()

            self._cross_model.invalidate()
            self._adapter.refresh_from_topology()
            self._update_status("Канвас обновлён (изменения процессов)")

            # Восстановить выделение если процесс всё ещё существует
            if self._pending_reselect:
                proc_data = self._editor._data.get("processes", {}).get(
                    self._pending_reselect
                )
                if proc_data is not None:
                    self._process_panel.show_process(
                        self._pending_reselect, dict(proc_data)
                    )
                    self._stack.setCurrentIndex(_PAGE_PROCESS)
                else:
                    # Процесс удалён — вернуться к placeholder
                    self._process_panel.clear()
                    self._stack.setCurrentIndex(_PAGE_PLACEHOLDER)
                self._pending_reselect = None

    def _on_wires_changed(self) -> None:
        """Секция wires изменилась извне — обновить статус."""
        wire_count = len(self._editor._data.get("wires", {}))
        self._update_status(f"Wires: {wire_count}")

    def _on_displays_changed(self) -> None:
        """Секция displays изменилась — перестроить канвас."""
        if self._adapter is not None:
            self._adapter.refresh_from_topology()
            self._update_status("Канвас обновлён (изменения displays)")

    # ------------------------------------------------------------------
    # Обработчики кнопок toolbar
    # ------------------------------------------------------------------

    def _on_refresh(self) -> None:
        """Кнопка «Обновить»."""
        if self._adapter is not None:
            self._adapter.refresh_from_topology()
            self._update_status("Канвас обновлён")

    def _on_auto_layout(self) -> None:
        """Кнопка «Авто-layout» — перерасчёт позиций Sugiyama."""
        if self._adapter is None:
            return

        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.auto_layout import (
            auto_layout,
        )

        process_keys = set(self._adapter.node_map.keys())
        wires = self._wire_model.wires if self._wire_model else {}
        positions = auto_layout(process_keys, wires)

        for pk, (x, y) in positions.items():
            qt_node = self._adapter.node_map.get(pk)
            if qt_node is not None:
                qt_node.set_pos(x, y)

        self._update_status("Авто-layout применён")

    def _on_fit_view(self) -> None:
        """Кнопка «Вписать»."""
        if self._adapter is not None:
            self._adapter.fit_to_view()

    def _on_validate(self) -> None:
        """Кнопка «Проверить»."""
        if self._wire_model is None:
            return

        errors = self._wire_model.validate_all()
        if errors:
            self._update_status(f"Ошибки: {len(errors)}", error=True)
            for err in errors[:5]:
                logger.warning("Валидация wire: %s", err)
        else:
            wire_count = len(self._wire_model.wires)
            self._update_status(f"Всё ОК ({wire_count} wires)")

    # ------------------------------------------------------------------
    # Save / Load Blueprint (Task 2.3)
    # ------------------------------------------------------------------

    def _on_save_blueprint(self) -> None:
        """Кнопка «Сохранить Blueprint» — экспорт в JSON."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить Blueprint", "", "JSON (*.json)"
        )
        if not path:
            return

        try:
            from multiprocess_prototype.frontend.widgets.tabs_setting.processes_tab.blueprint_io import (
                save_blueprint,
                topology_to_blueprint,
            )

            proc_data = self._editor._data.get("processes", {})
            wires_data = self._editor._data.get("wires", {})

            bp = topology_to_blueprint(
                proc_data,
                name=Path(path).stem,
                wires_data=wires_data,
            )
            save_blueprint(bp, Path(path))

            self._update_status(f"Blueprint сохранён: {Path(path).name}")
            logger.info("Blueprint сохранён: %s", path)
        except Exception as exc:
            self._update_status(f"Ошибка сохранения: {exc}", error=True)
            logger.exception("Ошибка сохранения blueprint: %s", exc)

    def _on_load_blueprint(self) -> None:
        """Кнопка «Загрузить Blueprint» — импорт из JSON."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Загрузить Blueprint", "", "JSON (*.json)"
        )
        if not path:
            return

        try:
            from multiprocess_prototype.frontend.widgets.tabs_setting.processes_tab.blueprint_io import (
                blueprint_to_topology,
                load_blueprint,
            )

            bp = load_blueprint(Path(path))
            topo_data = blueprint_to_topology(bp)

            # Полная замена данных editor — все вкладки обновятся через подписки
            self._editor.load(topo_data)

            # Сбросить правую панель и dashboard
            self._process_panel.clear()
            self._wire_panel.clear()
            self._shm_dashboard.clear()
            # Снять toggle SHM и вернуться к placeholder
            self._btn_shm.setChecked(False)
            self._stack.setCurrentIndex(_PAGE_PLACEHOLDER)

            self._update_status(f"Blueprint загружен: {bp.name}")
            logger.info("Blueprint загружен: %s из %s", bp.name, path)
        except Exception as exc:
            self._update_status(f"Ошибка загрузки: {exc}", error=True)
            logger.exception("Ошибка загрузки blueprint: %s", exc)

    # ------------------------------------------------------------------
    # SHM Dashboard toggle
    # ------------------------------------------------------------------

    def _on_toggle_dashboard(self, checked: bool) -> None:
        """Кнопка SHM — toggle dashboard панели."""
        if checked:
            self._stack.setCurrentIndex(_PAGE_DASHBOARD)
        else:
            # Вернуть на placeholder (выбор нода/wire восстановится при следующем клике)
            self._stack.setCurrentIndex(_PAGE_PLACEHOLDER)

    # ------------------------------------------------------------------
    # Обработчики сигналов адаптера → правая панель
    # ------------------------------------------------------------------

    def _on_wire_rejected(self, source: str, target: str, reason: str) -> None:
        """Wire отклонён при drag-connect."""
        self._update_status(f"Отклонено: {reason}", error=True)

    def _on_node_selected(self, process_key: str) -> None:
        """Нода выбрана — заполнить ProcessPluginPanel, показать если dashboard не активен."""
        proc_data = self._editor._data.get("processes", {}).get(process_key)
        if proc_data is not None:
            # Всегда обновляем данные панели — чтобы были актуальны после снятия dashboard
            self._process_panel.show_process(process_key, dict(proc_data))
            # Переключить stack только если dashboard не показан
            if not self._btn_shm.isChecked():
                self._stack.setCurrentIndex(_PAGE_PROCESS)
        else:
            logger.warning(
                "ConstructorTabWidget: процесс '%s' не найден в editor",
                process_key,
            )

    def _on_wire_selected(self, wire_key: str) -> None:
        """Wire выбран — заполнить WireInspectorPanel, показать если dashboard не активен."""
        wire_data = self._editor._data.get("wires", {}).get(wire_key)
        if wire_data is not None:
            # Всегда обновляем данные панели — чтобы были актуальны после снятия dashboard
            self._wire_panel.show_wire(wire_key, dict(wire_data))
            # Переключить stack только если dashboard не показан
            if not self._btn_shm.isChecked():
                self._stack.setCurrentIndex(_PAGE_WIRE)
        else:
            logger.warning(
                "ConstructorTabWidget: wire '%s' не найден в editor",
                wire_key,
            )

    def _on_selection_cleared(self) -> None:
        """Выделение снято — показать placeholder или dashboard."""
        self._process_panel.clear()
        self._wire_panel.clear()
        # Не трогать stack если dashboard активен
        if not self._btn_shm.isChecked():
            self._stack.setCurrentIndex(_PAGE_PLACEHOLDER)

    # ------------------------------------------------------------------
    # Обработчики сигналов панелей → модель
    # ------------------------------------------------------------------

    def _on_process_panel_changed(self, proc_key: str, proc_data: dict) -> None:
        """ProcessPluginPanel сообщает об изменении плагинов.

        Guard: запомнить proc_key, после rebuild восстановить выделение.
        """
        self._pending_reselect = proc_key
        self._editor.update_item("processes", proc_key, proc_data)
        # notify → _on_processes_changed → adapter.refresh → guard восстановит

    def _on_wire_panel_changed(self, wire_key: str, changed_fields: dict) -> None:
        """WireInspectorPanel сообщает об изменении wire."""
        if self._wire_model is not None:
            self._wire_model.modify_wire(wire_key, changed_fields)
            self._update_status(f"Wire обновлён: {wire_key}")

    # ------------------------------------------------------------------
    # Apply wires — применение конфигурации в runtime
    # ------------------------------------------------------------------

    def _on_apply_wires(self) -> None:
        """Кнопка «Применить» — отправить wire-конфигурацию через TopologyBridge.

        Алгоритм:
        1. Пометить все wires как PENDING (WireDataBridge.on_apply_started).
        2. Применить секцию wires через TopologyBridge.apply(SECTION_WIRES).
        3. При успехе — запустить мониторинг статусов.
        4. При ошибке — обновить статус в toolbar.
        """
        if self._bridge is None:
            self._update_status("TopologyBridge не настроен", error=True)
            return

        # Получить все ключи wire из текущей конфигурации
        wire_keys = list(self._editor._data.get("wires", {}).keys())

        # Пометить wires как PENDING — сигнал statuses_changed → окраска в жёлтый
        self._wire_bridge.on_apply_started(wire_keys)

        # Применить конфигурацию через TopologyBridge
        success = self._bridge.apply(SECTION_WIRES)

        if success:
            self._update_status(f"Wires применены ({len(wire_keys)})")
            logger.info(
                "ConstructorTabWidget: wires применены — %d шт.", len(wire_keys)
            )
            # Запустить polling статусов для отображения IDLE/ACTIVE/BROKEN
            self._wire_bridge.start_monitoring()
        else:
            self._update_status("Ошибка применения wires", error=True)
            logger.warning("ConstructorTabWidget: TopologyBridge.apply вернул False")

    def _on_wire_statuses_changed(self, statuses: dict) -> None:
        """Слот: WireDataBridge обновил статусы — перекрасить pipes на канвасе.

        Args:
            statuses: Словарь wire_key → WireStatus от WireDataBridge.
        """
        if self._adapter is not None:
            self._adapter.update_wire_colors(statuses)

    def _on_wire_metrics_changed(self, metrics: dict) -> None:
        """Слот: WireDataBridge обновил метрики — обновить badges и dashboard.

        Args:
            metrics: Словарь wire_key → метрики (dict или WireMetrics) от WireDataBridge.
        """
        if self._adapter is not None:
            self._adapter.update_wire_metrics(metrics)
        # Обновить SHM dashboard (всегда, не только когда он показан)
        self._shm_dashboard.update_metrics(metrics)

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def _update_status(self, text: str, error: bool = False) -> None:
        """Обновить статусную строку в toolbar."""
        color = "#e85838" if error else "#888"
        self._status_label.setStyleSheet(f"color: {color}; padding-left: 12px;")
        self._status_label.setText(text)


__all__ = ["ConstructorTabWidget"]
