# -*- coding: utf-8 -*-
"""HikvisionSettingsWidget — поля управления камерой Hikvision (как в SDK App).

Повторяет контролы Services/hikvision_camera/sdk_app/main_window.py, но без
собственного превью: изображение идёт в дисплей активного рецепта. Виджет —
«тупой» (View): только сигналы наружу + сеттеры состояния. Вся логика (IPC к
плагину) — в HikvisionSettingsPresenter.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Signal


class HikvisionSettingsWidget(QWidget):
    """Поля настроек камеры Hikvision (поиск/открытие/параметры)."""

    # Сигналы наружу — presenter подключается к ним.
    enum_requested = Signal()
    open_requested = Signal()
    close_requested = Signal()
    get_params_requested = Signal()
    apply_params_requested = Signal(float, float, float)  # fps, exposure, gain

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # --- Выбор устройства ---
        dev_group = QGroupBox("Выбор устройства")
        dev_layout = QVBoxLayout(dev_group)

        self._btn_enum = QPushButton("Найти устройства")
        self._btn_enum.clicked.connect(self.enum_requested.emit)
        dev_layout.addWidget(self._btn_enum)

        self._combo_devices = QComboBox()
        dev_layout.addWidget(self._combo_devices)

        open_close = QHBoxLayout()
        self._btn_open = QPushButton("Открыть")
        self._btn_open.clicked.connect(self.open_requested.emit)
        self._btn_close = QPushButton("Закрыть")
        self._btn_close.clicked.connect(self.close_requested.emit)
        open_close.addWidget(self._btn_open)
        open_close.addWidget(self._btn_close)
        dev_layout.addLayout(open_close)
        root.addWidget(dev_group)

        # --- Параметры камеры ---
        params_group = QGroupBox("Параметры камеры")
        params_layout = QGridLayout(params_group)

        params_layout.addWidget(QLabel("Частота кадров:"), 0, 0)
        self._edit_fps = QLineEdit("0.00")
        self._edit_fps.setPlaceholderText("FPS")
        params_layout.addWidget(self._edit_fps, 0, 1)

        params_layout.addWidget(QLabel("Экспозиция:"), 1, 0)
        self._edit_exposure = QLineEdit("0.00")
        self._edit_exposure.setPlaceholderText("мкс")
        params_layout.addWidget(self._edit_exposure, 1, 1)

        params_layout.addWidget(QLabel("Усиление:"), 2, 0)
        self._edit_gain = QLineEdit("0.00")
        self._edit_gain.setPlaceholderText("дБ")
        params_layout.addWidget(self._edit_gain, 2, 1)

        params_btns = QHBoxLayout()
        self._btn_get = QPushButton("Получить")
        self._btn_get.clicked.connect(self.get_params_requested.emit)
        self._btn_apply = QPushButton("Применить")
        self._btn_apply.clicked.connect(self._emit_apply)
        params_btns.addWidget(self._btn_get)
        params_btns.addWidget(self._btn_apply)
        params_layout.addLayout(params_btns, 3, 0, 1, 2)
        root.addWidget(params_group)

        # --- Статус ---
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setObjectName("hikvision_status")
        root.addWidget(self._status)
        root.addStretch()

    # ------------------------------------------------------------------ #
    # Сигналы-хелперы
    # ------------------------------------------------------------------ #

    def _emit_apply(self) -> None:
        self.apply_params_requested.emit(
            _to_float(self._edit_fps.text()),
            _to_float(self._edit_exposure.text()),
            _to_float(self._edit_gain.text()),
        )

    # ------------------------------------------------------------------ #
    # Сеттеры состояния (вызывает presenter/секция)
    # ------------------------------------------------------------------ #

    def selected_index(self) -> int:
        """Индекс устройства в комбобоксе (0 если пусто)."""
        idx = self._combo_devices.currentData()
        if idx is None:
            return max(self._combo_devices.currentIndex(), 0)
        try:
            return int(idx)
        except (TypeError, ValueError):
            return 0

    def set_devices(self, devices: list[dict]) -> None:
        """Заполнить комбобокс приборами ``list_devices`` (dict ``{kind, value, name}``)."""
        self._combo_devices.clear()
        for index, dev in enumerate(devices):
            label = dev.get("name") or dev.get("value") or f"[{index}]"
            self._combo_devices.addItem(str(label), index)

    def set_params(self, fps: float, exposure: float, gain: float) -> None:
        """Записать параметры в поля ввода."""
        self._edit_fps.setText(f"{fps:.2f}")
        self._edit_exposure.setText(f"{exposure:.2f}")
        self._edit_gain.setText(f"{gain:.2f}")

    def set_status(self, text: str) -> None:
        """Установить текст статус-метки."""
        self._status.setText(text)


def _to_float(text: str) -> float:
    """Безопасный парс float (запятая→точка, пусто→0)."""
    try:
        return float(text.replace(",", ".").strip() or "0")
    except (TypeError, ValueError):
        return 0.0
