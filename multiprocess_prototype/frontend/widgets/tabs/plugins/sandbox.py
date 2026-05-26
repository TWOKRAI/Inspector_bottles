"""PluginSandboxWidget — GUI-виджет для тестирования плагина на одном кадре.

Vertical slice (Task 6.2):
  - ISandboxView Protocol
  - PluginSandboxWidget: выбор файла → before-preview → «Применить» → after-preview
  - Конвертация BGR numpy → QPixmap через cv2.cvtColor + QImage
  - show_error (красный QLabel), set_running (disable + текст)

MVP-паттерн: ISandboxView (Protocol) + PluginSandboxWidget (реализует Protocol).
SandboxPresenter инжектируется снаружи.

Ограничения:
  - Только stateless single-frame плагины (processing/render).
  - Синхронный вызов run_once (QThread добавляется в Task 6.3).
  - Webcam snapshot и параметры конфига — Task 6.3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import (
        SandboxPresenter,
    )


# ---------------------------------------------------------------------------
# Protocol (ISandboxView)
# ---------------------------------------------------------------------------


class ISandboxView(Protocol):
    """Интерфейс View для sandbox-виджета.

    Определяет контракт между PluginSandboxWidget и SandboxPresenter.
    Позволяет тестировать presenter с mock-view.
    """

    def show_result(self, before: np.ndarray, after: np.ndarray | None) -> None:
        """Показать результат применения плагина (before и after кадры).

        Args:
            before: исходный BGR кадр.
            after: результирующий BGR кадр или None (плагин не вернул данные).
        """
        ...

    def show_error(self, msg: str) -> None:
        """Показать сообщение об ошибке (красным цветом).

        Args:
            msg: текст ошибки для пользователя.
        """
        ...

    def set_running(self, is_running: bool) -> None:
        """Переключить состояние «выполняется».

        Args:
            is_running: True — disable кнопку + текст «Применяется…».
                        False — enable кнопку + текст «Применить».
        """
        ...


# ---------------------------------------------------------------------------
# Вспомогательная функция конвертации
# ---------------------------------------------------------------------------


def _numpy_bgr_to_pixmap(frame: np.ndarray) -> QPixmap | None:
    """Конвертировать BGR numpy array в QPixmap.

    cv2.imread возвращает BGR, QImage.Format_RGB888 ожидает RGB.
    Шаги: BGR → RGB через cvtColor → QImage (contiguous buffer) → QPixmap.

    Args:
        frame: numpy array формата BGR, dtype=uint8.

    Returns:
        QPixmap или None при ошибке конвертации.
    """
    if frame is None or frame.size == 0:
        return None

    try:
        # Обеспечиваем contiguous layout для QImage
        if not frame.flags["C_CONTIGUOUS"]:
            frame = np.ascontiguousarray(frame)

        if frame.ndim == 3 and frame.shape[2] == 3:
            # BGR → RGB
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        elif frame.ndim == 2:
            # Grayscale (2D)
            h, w = frame.shape
            qimg = QImage(frame.data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            return None

        return QPixmap.fromImage(qimg)

    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# PluginSandboxWidget
# ---------------------------------------------------------------------------


class PluginSandboxWidget(QWidget):
    """Виджет для sandbox-тестирования плагина на одном кадре.

    Три зоны:
      1. Источник — QPushButton «Выбрать файл…» + QLabel с именем файла.
      2. Действие — QPushButton «Применить» (disabled до загрузки кадра).
      3. Preview — два QLabel (before / after) в QHBoxLayout, высота 200px.

    Реализует ISandboxView Protocol.

    Args:
        presenter: SandboxPresenter — бизнес-логика sandbox.
        plugin_name: имя плагина для передачи в presenter.run_once().
        parent: родительский виджет (опционально).
    """

    def __init__(
        self,
        presenter: "SandboxPresenter",
        plugin_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._presenter = presenter
        self._plugin_name = plugin_name
        self._current_frame: np.ndarray | None = None  # текущий загруженный кадр

        self._build_ui()

    # ------------------------------------------------------------------ #
    #  Построение UI                                                       #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        """Собрать компоновку виджета."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        # Заголовок
        title = QLabel(f"Sandbox: {self._plugin_name}")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        root_layout.addWidget(title)

        # -- Зона источника (input_zone) --
        input_zone = QWidget()
        input_layout = QHBoxLayout(input_zone)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(6)

        self._btn_file = QPushButton("Выбрать файл…")
        self._btn_file.clicked.connect(self._on_file_selected)
        input_layout.addWidget(self._btn_file)

        self._lbl_filename = QLabel("файл не выбран")
        self._lbl_filename.setStyleSheet("color: gray;")
        input_layout.addWidget(self._lbl_filename, stretch=1)

        root_layout.addWidget(input_zone)

        # -- Зона ошибок (скрыта по умолчанию) --
        self._lbl_error = QLabel("")
        self._lbl_error.setStyleSheet("color: red;")
        self._lbl_error.setWordWrap(True)
        self._lbl_error.hide()
        root_layout.addWidget(self._lbl_error)

        # -- Зона действия --
        self._btn_apply = QPushButton("Применить")
        self._btn_apply.setEnabled(False)  # disabled пока нет кадра
        self._btn_apply.clicked.connect(self._on_apply_clicked)
        root_layout.addWidget(self._btn_apply)

        # -- Зона preview (before / after) --
        preview_zone = QWidget()
        preview_layout = QHBoxLayout(preview_zone)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)

        # Before-панель
        before_col = QVBoxLayout()
        before_col.setSpacing(2)
        lbl_before_title = QLabel("До:")
        lbl_before_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        before_col.addWidget(lbl_before_title)
        self.before_label = QLabel()
        self.before_label.setFixedHeight(200)
        self.before_label.setMinimumWidth(150)
        self.before_label.setScaledContents(True)
        self.before_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.before_label.setStyleSheet("background: #1a1a1a; border: 1px solid #444;")
        before_col.addWidget(self.before_label)
        preview_layout.addLayout(before_col)

        # After-панель
        after_col = QVBoxLayout()
        after_col.setSpacing(2)
        lbl_after_title = QLabel("После:")
        lbl_after_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        after_col.addWidget(lbl_after_title)
        self.after_label = QLabel()
        self.after_label.setFixedHeight(200)
        self.after_label.setMinimumWidth(150)
        self.after_label.setScaledContents(True)
        self.after_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.after_label.setStyleSheet("background: #1a1a1a; border: 1px solid #444;")
        after_col.addWidget(self.after_label)
        preview_layout.addLayout(after_col)

        root_layout.addWidget(preview_zone, stretch=1)

    # ------------------------------------------------------------------ #
    #  Слоты                                                               #
    # ------------------------------------------------------------------ #

    def _on_file_selected(self) -> None:
        """Открыть диалог выбора файла и загрузить изображение."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбрать изображение",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp)",
        )
        if not path:
            # Пользователь отменил диалог
            return

        frame = cv2.imread(path)
        if frame is None:
            # Файл повреждён или формат не поддерживается
            self.show_error("Не удалось прочитать изображение")
            return

        # Скрыть предыдущую ошибку
        self._lbl_error.hide()

        # Сохранить кадр и показать before-preview
        self._current_frame = frame

        # Показать имя файла (только базовое имя)
        import os

        basename = os.path.basename(path)
        self._lbl_filename.setText(basename)
        self._lbl_filename.setStyleSheet("color: white;")

        # Показать before-preview
        pixmap = _numpy_bgr_to_pixmap(frame)
        if pixmap is not None:
            self.before_label.setPixmap(pixmap)

        # Активировать кнопку «Применить»
        self._btn_apply.setEnabled(True)

    def _on_apply_clicked(self) -> None:
        """Применить плагин к текущему кадру (синхронно, QThread в Task 6.3)."""
        if self._current_frame is None:
            return

        self.set_running(True)
        try:
            result = self._presenter.run_once(
                self._plugin_name,
                self._current_frame,
                {},
            )

            if result is None:
                # Плагин не вернул результат — сообщение без ошибки
                self._lbl_error.setText("нет результата")
                self._lbl_error.setStyleSheet("color: orange;")
                self._lbl_error.show()
            else:
                # Успех — показать результат
                self._lbl_error.hide()
                self.show_result(self._current_frame, result)

        finally:
            self.set_running(False)

    # ------------------------------------------------------------------ #
    #  ISandboxView — публичный API (Protocol)                             #
    # ------------------------------------------------------------------ #

    def show_result(self, before: np.ndarray, after: np.ndarray | None) -> None:
        """Показать before и after кадры в preview-зонах.

        Args:
            before: исходный BGR кадр.
            after: результирующий BGR кадр или None.
        """
        # Before всегда показываем
        pixmap_before = _numpy_bgr_to_pixmap(before)
        if pixmap_before is not None:
            self.before_label.setPixmap(pixmap_before)

        # After — только если есть результат
        if after is not None:
            pixmap_after = _numpy_bgr_to_pixmap(after)
            if pixmap_after is not None:
                self.after_label.setPixmap(pixmap_after)
        # after=None — after_label остаётся как есть (пустым или со старым кадром)

    def show_error(self, msg: str) -> None:
        """Показать сообщение об ошибке красным цветом.

        Args:
            msg: текст ошибки (может быть пустым — label просто скроется).
        """
        if msg:
            self._lbl_error.setText(msg)
            self._lbl_error.setStyleSheet("color: red;")
            self._lbl_error.show()
        else:
            self._lbl_error.hide()

    def set_running(self, is_running: bool) -> None:
        """Переключить состояние «выполняется» на кнопке «Применить».

        Args:
            is_running: True — disable + «Применяется…»; False — enable + «Применить».
        """
        if is_running:
            self._btn_apply.setEnabled(False)
            self._btn_apply.setText("Применяется…")
        else:
            self._btn_apply.setEnabled(self._current_frame is not None)
            self._btn_apply.setText("Применить")
