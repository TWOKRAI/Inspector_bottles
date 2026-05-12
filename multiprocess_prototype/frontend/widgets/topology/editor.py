"""TopologyEditorWidget — главный виджет таба редактора topology."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from .presenter import TopologyPresenter
from .process_list import ProcessListWidget
from .wire_list import WireListWidget
from .plugin_selector import PluginSelectorDialog
from .validation_panel import ValidationPanel


class TopologyEditorWidget(QWidget):
    """Редактор topology — главный виджет для таба MainWindow.

    Layout:
        Toolbar (New | Load | Save | Validate)
        QSplitter:
            Left:  ProcessListWidget + WireListWidget
            Right: ValidationPanel
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._presenter = TopologyPresenter()
        self._build_ui()
        self._connect_signals()
        # Показать начальное состояние
        self._refresh_all()

    # ------------------------------------------------------------------ #
    #  Построение UI                                                       #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        """Создать и разместить все дочерние виджеты."""
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Toolbar (строка кнопок сверху)
        root.addLayout(self._build_toolbar())

        # Строка статуса (имя файла)
        self._status_label = QLabel("Новая топология")
        self._status_label.setObjectName("StatusHint")
        root.addWidget(self._status_label)

        # Основной сплиттер
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Левая панель: процессы + wires
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._process_list = ProcessListWidget()
        self._wire_list = WireListWidget()
        left_layout.addWidget(QLabel("Процессы:"))
        left_layout.addWidget(self._process_list)
        left_layout.addWidget(QLabel("Wires:"))
        left_layout.addWidget(self._wire_list)
        splitter.addWidget(left_panel)

        # Правая панель: валидация
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Валидация:"))
        self._validation_panel = ValidationPanel()
        right_layout.addWidget(self._validation_panel)
        splitter.addWidget(right_panel)

        # Пропорции: левая 60%, правая 40%
        splitter.setSizes([600, 400])
        root.addWidget(splitter)

    def _build_toolbar(self) -> QHBoxLayout:
        """Создать строку кнопок toolbar."""
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self._btn_new = QPushButton("New")
        self._btn_load = QPushButton("Load")
        self._btn_save = QPushButton("Save")
        self._btn_validate = QPushButton("Validate")

        for btn in (self._btn_new, self._btn_load, self._btn_save, self._btn_validate):
            btn.setFixedHeight(28)
            toolbar.addWidget(btn)

        toolbar.addStretch()
        return toolbar

    # ------------------------------------------------------------------ #
    #  Подключение сигналов                                               #
    # ------------------------------------------------------------------ #

    def _connect_signals(self) -> None:
        """Связать сигналы виджетов с обработчиками."""
        # Toolbar
        self._btn_new.clicked.connect(self._on_new)
        self._btn_load.clicked.connect(self._on_load)
        self._btn_save.clicked.connect(self._on_save)
        self._btn_validate.clicked.connect(self._on_validate)

        # ProcessList
        self._process_list.process_add_requested.connect(self._on_add_process)
        self._process_list.process_remove_requested.connect(self._on_remove_process)

        # WireList
        self._wire_list.wire_add_requested.connect(self._on_add_wire)
        self._wire_list.wire_remove_requested.connect(self._on_remove_wire)

        # ValidationPanel
        self._validation_panel.validate_requested.connect(self._on_validate)

    # ------------------------------------------------------------------ #
    #  Обновление UI из данных presenter                                  #
    # ------------------------------------------------------------------ #

    def set_topology_dir(self, dir_path: Path) -> None:
        """Установить директорию с topology файлами.

        Сканирует *.yaml/*.yml, загружает первый найденный.
        При Load — QFileDialog откроется в этой директории.
        """
        self._topology_dir = dir_path
        if not dir_path.is_dir():
            return
        # Найти все yaml файлы
        files = sorted(dir_path.glob("*.yaml")) + sorted(dir_path.glob("*.yml"))
        # Загрузить первый найденный (или текущий запущенный)
        if files:
            self.load_file(files[0])

    def load_file(self, path: Path) -> None:
        """Загрузить topology из файла."""
        try:
            self._presenter.load_from_file(path)
            self._refresh_all()
        except Exception:
            pass  # Если файл не читается — просто оставить пустым

    def _refresh_all(self) -> None:
        """Синхронизировать все виджеты с текущим состоянием presenter."""
        bp = self._presenter.blueprint
        self._process_list.refresh(self._presenter.get_process_names())
        self._wire_list.refresh(bp.wires)
        self._validation_panel.clear()

        # Обновить строку статуса
        fp = self._presenter.file_path
        if fp:
            self._status_label.setText(str(fp))
        else:
            self._status_label.setText(f"Новая топология: {bp.name}")

    # ------------------------------------------------------------------ #
    #  Обработчики действий toolbar                                        #
    # ------------------------------------------------------------------ #

    def _on_new(self) -> None:
        """Создать новый пустой blueprint."""
        name, ok = QInputDialog.getText(
            self, "Новая топология", "Имя топологии:", text="new_topology"
        )
        if ok and name.strip():
            self._presenter.new_topology(name.strip())
            self._refresh_all()

    def _on_load(self) -> None:
        """Открыть YAML-файл и загрузить blueprint."""
        start_dir = str(self._topology_dir) if hasattr(self, "_topology_dir") else ""
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Открыть topology", start_dir, "YAML Files (*.yaml *.yml);;All Files (*)"
        )
        if not path_str:
            return
        try:
            self._presenter.load_from_file(Path(path_str))
            self._refresh_all()
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка загрузки", str(exc))

    def _on_save(self) -> None:
        """Сохранить blueprint в YAML-файл."""
        # Определить путь (текущий или новый)
        default = str(self._presenter.file_path) if self._presenter.file_path else ""
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Сохранить topology", default, "YAML Files (*.yaml *.yml);;All Files (*)"
        )
        if not path_str:
            return
        try:
            self._presenter.save_to_file(Path(path_str))
            self._status_label.setText(path_str)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка сохранения", str(exc))

    def _on_validate(self) -> None:
        """Запустить валидацию и показать результат."""
        errors = self._presenter.validate()
        self._validation_panel.show_results(errors)

    # ------------------------------------------------------------------ #
    #  Обработчики CRUD процессов                                          #
    # ------------------------------------------------------------------ #

    def _on_add_process(self) -> None:
        """Добавить новый процесс."""
        # Запросить имя процесса
        name, ok = QInputDialog.getText(
            self, "Добавить процесс", "Имя процесса:"
        )
        if not ok or not name.strip():
            return

        # Предложить выбрать плагины (опционально)
        plugins_list: list[dict] = []
        available = self._presenter.available_plugins()
        if available:
            add_plugin = QMessageBox.question(
                self,
                "Плагины",
                "Добавить плагин к процессу?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            while add_plugin == QMessageBox.StandardButton.Yes:
                plugin_dict = PluginSelectorDialog.get_plugin(self, available)
                if plugin_dict:
                    plugins_list.append(plugin_dict)
                add_plugin = QMessageBox.question(
                    self,
                    "Плагины",
                    "Добавить ещё плагин?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )

        self._presenter.add_process(name.strip(), plugins=plugins_list)
        self._refresh_all()

    def _on_remove_process(self, name: str) -> None:
        """Удалить выбранный процесс."""
        reply = QMessageBox.question(
            self,
            "Удалить процесс",
            f"Удалить процесс '{name}' и все его wires?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._presenter.remove_process(name)
            self._refresh_all()

    # ------------------------------------------------------------------ #
    #  Обработчики CRUD wires                                              #
    # ------------------------------------------------------------------ #

    def _on_add_wire(self) -> None:
        """Добавить новый wire через диалог ввода."""
        source, ok = QInputDialog.getText(
            self, "Добавить wire", "Source (process.plugin.port):"
        )
        if not ok or not source.strip():
            return

        target, ok = QInputDialog.getText(
            self, "Добавить wire", "Target (process.plugin.port):"
        )
        if not ok or not target.strip():
            return

        description, ok = QInputDialog.getText(
            self, "Добавить wire", "Описание (необязательно):"
        )
        # description ok не проверяем — поле необязательное
        self._presenter.add_wire(
            source.strip(), target.strip(), description.strip() if ok else ""
        )
        self._refresh_all()

    def _on_remove_wire(self, index: int) -> None:
        """Удалить wire по индексу."""
        self._presenter.remove_wire(index)
        self._refresh_all()
