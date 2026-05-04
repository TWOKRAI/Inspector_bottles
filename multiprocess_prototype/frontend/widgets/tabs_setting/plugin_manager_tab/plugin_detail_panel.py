# multiprocess_prototype/frontend/widgets/tabs_setting/plugin_manager_tab/plugin_detail_panel.py
"""PluginDetailPanel — правая панель с детальной информацией о плагине.

Отображает:
- Базовую информацию (имя, категория, путь, описание, статус)
- Порты (входные и выходные с типами)
- Метрики (MVP: заглушка)
- Дефолтную конфигурацию в формате JSON (редактируемую)
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_logger = logging.getLogger(__name__)

# Цвета статуса включён/выключен
_COLOR_ENABLED = "color: #2e7d32;"   # тёмно-зелёный
_COLOR_DISABLED = "color: #c62828;"  # тёмно-красный


class PluginDetailPanel(QWidget):
    """Панель детальной информации о выбранном плагине.

    Отображает данные из get_plugin_detail() в читаемом виде.
    Позволяет редактировать и сохранять дефолтную конфигурацию.

    Сигналы:
        default_config_changed(str, dict): (plugin_name, config) — пользователь
            сохранил дефолтную конфигурацию.
    """

    default_config_changed = Signal(str, dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Инициализировать панель.

        Args:
            parent: родительский виджет.
        """
        super().__init__(parent)

        # Имя текущего отображаемого плагина
        self._current_plugin_name: str | None = None

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Создать layout с прокруткой и все секции."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # Прокручиваемый контейнер
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        # Внутренний контейнер с контентом
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(8, 8, 8, 8)
        self._content_layout.setSpacing(8)

        # Секции
        self._build_info_section()
        self._build_ports_section()
        self._build_metrics_section()
        self._build_config_section()

        # Растягиваем снизу чтобы секции не разъезжались
        self._content_layout.addStretch(1)

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

    def _build_info_section(self) -> None:
        """Создать секцию базовой информации о плагине."""
        group = QGroupBox("Информация")
        form = QFormLayout(group)
        form.setSpacing(6)

        # Имя — жирным
        self._lbl_name = QLabel()
        self._lbl_name.setStyleSheet("font-weight: bold;")
        form.addRow("Имя:", self._lbl_name)

        # Категория
        self._lbl_category = QLabel()
        form.addRow("Категория:", self._lbl_category)

        # Путь к классу — моноширинный
        self._lbl_class_path = QLabel()
        self._lbl_class_path.setStyleSheet("font-family: monospace;")
        self._lbl_class_path.setWordWrap(True)
        form.addRow("Путь:", self._lbl_class_path)

        # Описание — с переносом строк
        self._lbl_description = QLabel()
        self._lbl_description.setWordWrap(True)
        form.addRow("Описание:", self._lbl_description)

        # Статус — цветной
        self._lbl_enabled = QLabel()
        form.addRow("Статус:", self._lbl_enabled)

        self._content_layout.addWidget(group)

    def _build_ports_section(self) -> None:
        """Создать секцию входных/выходных портов."""
        self._ports_group = QGroupBox("Порты")
        self._ports_layout = QVBoxLayout(self._ports_group)
        self._ports_layout.setSpacing(2)

        # Заглушка — виден пока нет данных
        self._lbl_no_ports = QLabel("Нет портов")
        self._ports_layout.addWidget(self._lbl_no_ports)

        self._content_layout.addWidget(self._ports_group)

    def _build_metrics_section(self) -> None:
        """Создать секцию метрик (MVP-заглушка)."""
        group = QGroupBox("Метрики")
        layout = QVBoxLayout(group)

        self._lbl_metrics = QLabel("Метрики недоступны")
        self._lbl_metrics.setStyleSheet("color: gray;")
        layout.addWidget(self._lbl_metrics)

        self._content_layout.addWidget(group)

    def _build_config_section(self) -> None:
        """Создать секцию редактирования дефолтной конфигурации."""
        group = QGroupBox("Дефолтная конфигурация")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # Редактор JSON
        self._config_editor = QPlainTextEdit()
        self._config_editor.setPlaceholderText('{"param": "value"}')
        self._config_editor.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        self._config_editor.setMaximumHeight(150)
        layout.addWidget(self._config_editor)

        # Кнопка сохранения
        self._save_config_btn = QPushButton("Сохранить дефолты")
        layout.addWidget(self._save_config_btn)

        self._content_layout.addWidget(group)

    # ------------------------------------------------------------------
    # Подключение сигналов
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Подключить кнопку сохранения конфигурации."""
        self._save_config_btn.clicked.connect(self._on_save_config_clicked)

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    def show_plugin(self, plugin_data: dict) -> None:
        """Заполнить панель данными плагина.

        Args:
            plugin_data: dict из get_plugin_detail() с полями name, category,
                         class_path, description, enabled, input_ports, output_ports.
        """
        self._current_plugin_name = plugin_data.get("name")

        # Секция информации
        self._lbl_name.setText(plugin_data.get("name", ""))
        self._lbl_category.setText(plugin_data.get("category", ""))
        self._lbl_class_path.setText(plugin_data.get("class_path", ""))
        self._lbl_description.setText(plugin_data.get("description", ""))

        # Статус — зелёный/красный
        if plugin_data.get("enabled", True):
            self._lbl_enabled.setText("включён")
            self._lbl_enabled.setStyleSheet(_COLOR_ENABLED)
        else:
            self._lbl_enabled.setText("выключен")
            self._lbl_enabled.setStyleSheet(_COLOR_DISABLED)

        # Секция портов
        self._populate_ports(
            plugin_data.get("input_ports", []),
            plugin_data.get("output_ports", []),
        )

        # Метрики
        self.update_metrics(plugin_data.get("metrics"))

        # Конфигурация — пустой dict по умолчанию
        self._config_editor.setPlainText("")

    def update_metrics(self, metrics: dict | None) -> None:
        """Обновить секцию метрик.

        Args:
            metrics: словарь метрик или None (MVP: только отображение).
        """
        if metrics:
            # Форматируем метрики как строку key: value
            lines = [f"{k}: {v}" for k, v in metrics.items()]
            self._lbl_metrics.setText("\n".join(lines))
            self._lbl_metrics.setStyleSheet("")
        else:
            self._lbl_metrics.setText("Метрики недоступны")
            self._lbl_metrics.setStyleSheet("color: gray;")

    def clear(self) -> None:
        """Сбросить все поля панели в пустое состояние."""
        self._current_plugin_name = None

        self._lbl_name.setText("")
        self._lbl_category.setText("")
        self._lbl_class_path.setText("")
        self._lbl_description.setText("")
        self._lbl_enabled.setText("")
        self._lbl_enabled.setStyleSheet("")

        self._clear_ports()
        self._lbl_no_ports.setVisible(True)

        self._lbl_metrics.setText("Метрики недоступны")
        self._lbl_metrics.setStyleSheet("color: gray;")

        self._config_editor.setPlainText("")

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _populate_ports(self, input_ports: list[dict], output_ports: list[dict]) -> None:
        """Заполнить секцию портов входными и выходными портами.

        Args:
            input_ports: список dict с полями name, dtype, shape, optional, description.
            output_ports: список dict с полями name, dtype, shape, optional, description.
        """
        self._clear_ports()

        has_ports = bool(input_ports or output_ports)
        self._lbl_no_ports.setVisible(not has_ports)

        # Входные порты
        for port in input_ports:
            name = port.get("name", "?")
            dtype = port.get("dtype", "?")
            shape = port.get("shape", "")
            optional = port.get("optional", False)

            suffix = " [optional]" if optional else ""
            shape_str = f", {shape}" if shape else ""
            lbl = QLabel(f"IN:  {name} ({dtype}{shape_str}){suffix}")
            lbl.setStyleSheet("color: #1565c0; margin-left: 4px;")  # синий для входа
            self._ports_layout.addWidget(lbl)

        # Выходные порты
        for port in output_ports:
            name = port.get("name", "?")
            dtype = port.get("dtype", "?")
            shape = port.get("shape", "")
            optional = port.get("optional", False)

            suffix = " [optional]" if optional else ""
            shape_str = f", {shape}" if shape else ""
            lbl = QLabel(f"OUT: {name} ({dtype}{shape_str}){suffix}")
            lbl.setStyleSheet("color: #2e7d32; margin-left: 4px;")  # зелёный для выхода
            self._ports_layout.addWidget(lbl)

    def _clear_ports(self) -> None:
        """Удалить все динамически добавленные метки портов из layout."""
        # Удаляем все виджеты кроме lbl_no_ports
        while self._ports_layout.count() > 0:
            item = self._ports_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._lbl_no_ports:
                widget.deleteLater()

        # Возвращаем заглушку в layout
        self._ports_layout.addWidget(self._lbl_no_ports)

    # ------------------------------------------------------------------
    # Слоты
    # ------------------------------------------------------------------

    def _on_save_config_clicked(self) -> None:
        """Обработать нажатие кнопки "Сохранить дефолты".

        Парсит JSON из редактора и эмитирует default_config_changed.
        При ошибке парсинга — выводит сообщение в редактор.
        """
        if self._current_plugin_name is None:
            return

        raw_text = self._config_editor.toPlainText().strip()

        # Пустой текст трактуем как пустой конфиг
        if not raw_text:
            self.default_config_changed.emit(self._current_plugin_name, {})
            return

        try:
            config = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            _logger.warning(
                "Ошибка парсинга JSON конфигурации плагина '%s': %s",
                self._current_plugin_name,
                exc,
            )
            # Показываем ошибку прямо в редакторе не затирая текст
            self._config_editor.setToolTip(f"Ошибка JSON: {exc}")
            return

        if not isinstance(config, dict):
            _logger.warning(
                "Конфигурация плагина '%s' должна быть объектом JSON (dict)",
                self._current_plugin_name,
            )
            return

        self._config_editor.setToolTip("")
        _logger.debug(
            "Сохранение дефолтной конфигурации плагина '%s': %s",
            self._current_plugin_name,
            config,
        )
        self.default_config_changed.emit(self._current_plugin_name, config)
