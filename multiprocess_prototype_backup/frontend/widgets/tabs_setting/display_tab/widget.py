# multiprocess_prototype/frontend/widgets/tabs_setting/display_tab/widget.py
"""
DisplayTabWidget — вкладка управления display-окнами.

Показывает таблицу активных окон, пресеты раскладки (0/1/2/4/Custom)
и кнопки Add/Remove для ручного управления.

Начиная с Task 2.4 — первичный источник данных DisplaysSectionView
(через SystemTopologyEditor). Если editor не передан — fallback на
DisplayRouter/DisplayWindowManager (обратная совместимость).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from registers.display.presets import LayoutPreset

if TYPE_CHECKING:
    from multiprocess_prototype.state_store.adapters.camera_state_adapter import CameraStateAdapter
    from frontend.managers.display_router import DisplayRouter
    from frontend.managers.window_manager import DisplayWindowManager

logger = logging.getLogger(__name__)


class DisplayTabWidget(QWidget):
    """Вкладка настроек display-окон.

    Позволяет применять пресеты раскладки одним кликом,
    добавлять и удалять окна вручную, видеть текущие активные подписки.

    Режимы работы:
    - Если передан topology_editor/topology_bridge — работает через
      DisplaysSectionView (Task 2.4).
    - Иначе — backward compat: прямые вызовы window_manager/display_router.
    """

    def __init__(
        self,
        window_manager: "DisplayWindowManager",
        display_router: "DisplayRouter",
        camera_registry: "CameraStateAdapter",
        topology_editor: Any | None = None,
        topology_bridge: Any | None = None,
        parent: Any | None = None,
    ) -> None:
        """Инициализация вкладки Display.

        Args:
            window_manager: Менеджер lifecycle display-окон.
            display_router: Маршрутизатор display-подписок.
            camera_registry: Адаптер камер (для получения camera_ids).
            topology_editor: SystemTopologyEditor (опционально, Task 2.4).
            topology_bridge: TopologyBridge (опционально, Task 2.4).
            parent: Родительский QWidget.
        """
        super().__init__(parent)

        # Сохраняем ссылки на менеджеры (используются для fallback и callback-ов)
        self._window_manager = window_manager
        self._display_router = display_router
        self._camera_registry = camera_registry

        # Section View для работы через SystemTopologyEditor (Task 2.4)
        self._topology_editor = topology_editor
        self._topology_bridge = topology_bridge
        self._section = topology_editor.displays if topology_editor is not None else None

        # Строим UI
        self._build_ui()

        # Подключаем callback-и от менеджера окон
        self._setup_callbacks()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Собрать layout вкладки: пресеты → таблица → нижняя панель."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # --- Верхняя секция: кнопки пресетов ---
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)

        preset_label = QLabel("Пресет:")
        preset_row.addWidget(preset_label)

        # Кнопка «0» — убрать все окна (NONE)
        btn_none = QPushButton("0")
        btn_none.setToolTip("Закрыть все display-окна")
        btn_none.clicked.connect(lambda: self._on_preset_clicked(LayoutPreset.NONE))
        preset_row.addWidget(btn_none)

        # Кнопка «1» — одно окно (SINGLE)
        btn_single = QPushButton("1")
        btn_single.setToolTip("Одно display-окно (camera_0)")
        btn_single.clicked.connect(lambda: self._on_preset_clicked(LayoutPreset.SINGLE))
        preset_row.addWidget(btn_single)

        # Кнопка «2» — два окна (DUAL)
        btn_dual = QPushButton("2")
        btn_dual.setToolTip("Два display-окна (camera_0, camera_1)")
        btn_dual.clicked.connect(lambda: self._on_preset_clicked(LayoutPreset.DUAL))
        preset_row.addWidget(btn_dual)

        # Кнопка «4» — четыре окна (QUAD)
        btn_quad = QPushButton("4")
        btn_quad.setToolTip("Четыре display-окна (camera_0..3)")
        btn_quad.clicked.connect(lambda: self._on_preset_clicked(LayoutPreset.QUAD))
        preset_row.addWidget(btn_quad)

        # Кнопка «Custom» — placeholder, отключена
        btn_custom = QPushButton("Custom")
        btn_custom.setToolTip("Пользовательская раскладка (недоступно)")
        btn_custom.setEnabled(False)
        preset_row.addWidget(btn_custom)

        preset_row.addStretch()
        main_layout.addLayout(preset_row)

        # --- Средняя секция: таблица активных окон ---
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["ID", "Источник", "FPS лимит", "Статус", ""])
        # Запрет редактирования ячеек
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # Выделение строками
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # Растягиваем колонки под содержимое
        self._table.horizontalHeader().setStretchLastSection(False)
        main_layout.addWidget(self._table)

        # --- Нижняя секция: кнопки управления ---
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)

        btn_add = QPushButton("Добавить окно")
        btn_add.setToolTip("Создать новое display-окно с источником camera_0")
        btn_add.clicked.connect(self._on_add_window)
        bottom_row.addWidget(btn_add)

        # Кнопка «Применить» — отправляет displays через TopologyBridge
        self._btn_apply = QPushButton("Применить")
        self._btn_apply.setToolTip("Применить изменения display-окон")
        self._btn_apply.clicked.connect(self._on_apply)
        # Кнопка видна только когда есть topology_bridge
        self._btn_apply.setVisible(self._topology_bridge is not None)
        bottom_row.addWidget(self._btn_apply)

        bottom_row.addStretch()
        main_layout.addLayout(bottom_row)

    # ------------------------------------------------------------------
    # Обработчики событий
    # ------------------------------------------------------------------

    def _on_preset_clicked(self, preset: LayoutPreset) -> None:
        """Применить выбранный пресет раскладки.

        Если передан topology_editor — работаем через DisplaysSectionView.
        Иначе — fallback на прямые вызовы DisplayRouter/DisplayWindowManager.

        Args:
            preset: Пресет раскладки (NONE/SINGLE/DUAL/QUAD).
        """
        if self._section is not None:
            # Новый путь: через DisplaysSectionView (Task 2.4)
            camera_keys = (
                self._topology_editor.camera_keys()
                if self._topology_editor is not None
                else []
            )
            preset_name = self._preset_to_name(preset)

            if preset_name == "none":
                # Убрать все текущие displays из section
                for key in list(self._section.displays.keys()):
                    self._section.remove_display(key)
            else:
                # Применить пресет через DisplaysSectionView
                self._section.apply_preset(preset_name, camera_keys)

            # Сразу применяем через bridge (чтобы окна появились без нажатия «Применить»)
            if self._topology_bridge is not None:
                from multiprocess_prototype.registers.system_topology.schemas import (
                    SECTION_DISPLAYS,
                )
                self._topology_bridge.apply(SECTION_DISPLAYS)

            self._refresh_table()
        else:
            # Fallback: старое поведение через DisplayRouter/DisplayWindowManager
            camera_ids = self._get_camera_ids()
            self._display_router.apply_preset(preset, camera_ids)

            active_subs = self._display_router.get_active_subscriptions()
            existing_windows = set(self._window_manager.list_windows())

            for sub in active_subs:
                if sub.window_id not in existing_windows:
                    self._window_manager.create_window(
                        sub.window_id, sub.source_ref, sub.transform
                    )

            # При NONE — уничтожаем все оставшиеся окна
            if preset == LayoutPreset.NONE:
                for wid in list(self._window_manager.list_windows()):
                    self._window_manager.destroy_window(wid)

            self._refresh_table()

    def _on_add_window(self) -> None:
        """Создать новое display-окно с источником camera_0."""
        if self._section is not None:
            # Новый путь: через DisplaysSectionView (Task 2.4)
            self._section.add_display(name="Display", source_ref="camera_0", fps_limit=30)
            self._refresh_table()
        else:
            # Fallback: прямой вызов window_manager
            window_id = f"win_{self._window_manager.window_count()}"
            source_ref = "camera_0"
            self._window_manager.create_window(window_id, source_ref)
            self._refresh_table()

    def _on_remove_window(self, window_id: str) -> None:
        """Уничтожить конкретное display-окно.

        Args:
            window_id: Идентификатор окна для удаления.
        """
        if self._section is not None:
            # Новый путь: через DisplaysSectionView (Task 2.4)
            try:
                self._section.remove_display(window_id)
            except KeyError:
                logger.warning(
                    "DisplayTabWidget: display '%s' не найден в section, пропуск",
                    window_id,
                )
            self._refresh_table()
        else:
            # Fallback: прямой вызов window_manager
            self._window_manager.destroy_window(window_id)
            self._refresh_table()

    def _on_apply(self) -> None:
        """Применить изменения display-окон через TopologyBridge.

        Вызывается кнопкой «Применить» для явного сохранения.
        """
        if self._topology_bridge is not None:
            from multiprocess_prototype.registers.system_topology.schemas import (
                SECTION_DISPLAYS,
            )
            self._topology_bridge.apply(SECTION_DISPLAYS)
            logger.info("DisplayTabWidget: topology_bridge.apply(SECTION_DISPLAYS) вызван")

    # ------------------------------------------------------------------
    # Обновление таблицы
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        """Перестроить таблицу по текущим активным подпискам/section."""
        # Очищаем содержимое таблицы
        self._table.setRowCount(0)

        if self._section is not None:
            # Новый путь: читаем из DisplaysSectionView (Task 2.4)
            displays = self._section.displays
            for win_id, cfg in displays.items():
                self._add_table_row_from_dict(win_id, cfg)
        else:
            # Fallback: читаем из DisplayRouter
            subs = self._display_router.get_active_subscriptions()
            for sub in subs:
                fps_limit = ""
                if sub.transform and sub.transform.fps_limit:
                    fps_limit = str(sub.transform.fps_limit)
                row_data = {
                    "source_ref": sub.source_ref,
                    "fps_limit": fps_limit,
                }
                self._add_table_row_from_dict(sub.window_id, row_data)

        # Подгоняем ширину колонок под содержимое
        self._table.resizeColumnsToContents()

    def _add_table_row_from_dict(self, win_id: str, cfg: dict) -> None:
        """Добавить строку в таблицу из dict-конфига дисплея.

        Args:
            win_id: Идентификатор окна (ключ в section/router).
            cfg: Dict с полями: source_ref, fps_limit, name, ...
        """
        row = self._table.rowCount()
        self._table.insertRow(row)

        # Колонка: window_id
        self._table.setItem(row, 0, QTableWidgetItem(win_id))

        # Колонка: source_ref
        source_ref = cfg.get("source_ref", "") if isinstance(cfg, dict) else ""
        self._table.setItem(row, 1, QTableWidgetItem(str(source_ref)))

        # Колонка: fps_limit
        fps_limit = cfg.get("fps_limit", "") if isinstance(cfg, dict) else ""
        self._table.setItem(row, 2, QTableWidgetItem(str(fps_limit) if fps_limit else ""))

        # Колонка: статус
        self._table.setItem(row, 3, QTableWidgetItem("Active"))

        # Колонка: кнопка закрытия строки
        close_btn = QPushButton("✕")
        close_btn.setToolTip(f"Закрыть окно {win_id}")
        # Захватываем window_id по значению через default arg
        close_btn.clicked.connect(
            lambda checked=False, wid=win_id: self._on_remove_window(wid)
        )
        self._table.setCellWidget(row, 4, close_btn)

    # ------------------------------------------------------------------
    # Настройка callback-ов менеджера окон
    # ------------------------------------------------------------------

    def _setup_callbacks(self) -> None:
        """Подключить callback-и DisplayWindowManager для авто-обновления таблицы."""
        # Обновляем таблицу при создании любого окна
        self._window_manager.add_on_create(lambda wid: self._refresh_table())
        # Обновляем таблицу при уничтожении любого окна
        self._window_manager.add_on_destroy(lambda wid: self._refresh_table())

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _get_camera_ids(self) -> list[int]:
        """Получить список camera_ids.

        Если topology_editor есть — берём из него (camera_keys).
        Иначе — fallback на camera_registry.

        Returns:
            Список целочисленных camera_id.
        """
        if self._topology_editor is not None:
            # camera_keys() возвращает строковые ключи вида "cam_0", "cam_1"
            # Для старого DisplayRouter нужны int. Конвертируем через порядковый номер.
            keys = self._topology_editor.camera_keys()
            return list(range(len(keys)))
        return self._camera_registry.camera_ids()

    @staticmethod
    def _preset_to_name(preset: LayoutPreset) -> str:
        """Конвертировать LayoutPreset в строковое имя для DisplaysSectionView.

        Args:
            preset: Enum-значение пресета.

        Returns:
            Строковое имя: "none", "single", "dual", "quad".
        """
        mapping = {
            LayoutPreset.NONE: "none",
            LayoutPreset.SINGLE: "single",
            LayoutPreset.DUAL: "dual",
            LayoutPreset.QUAD: "quad",
        }
        return mapping.get(preset, "none")
