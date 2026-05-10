"""ValidationPanel — панель отображения результатов валидации blueprint."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ValidationPanel(QWidget):
    """Панель валидации blueprint.

    Содержит read-only QTextEdit для вывода ошибок/OK
    и кнопку "Validate", которая испускает сигнал validate_requested.
    Фактическую валидацию выполняет presenter по этому сигналу,
    после чего вызывает show_results().
    """

    # Пользователь нажал кнопку Validate
    validate_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        """Построить UI панели."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Область вывода результатов
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText("Нажмите 'Validate' для проверки blueprint...")
        layout.addWidget(self._output)

        # Кнопка Validate
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._btn_validate = QPushButton("Validate")
        self._btn_validate.clicked.connect(self.validate_requested)
        btn_layout.addWidget(self._btn_validate)
        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------ #
    #  Публичный API                                                       #
    # ------------------------------------------------------------------ #

    def show_results(self, errors: list[str]) -> None:
        """Отобразить результаты валидации.

        Если errors пустой — зелёный текст "OK".
        Иначе — красный список ошибок.
        """
        if not errors:
            self._output.setStyleSheet("color: green;")
            self._output.setPlainText("OK — ошибок не найдено")
        else:
            self._output.setStyleSheet("color: red;")
            text = f"Найдено ошибок: {len(errors)}\n\n"
            text += "\n".join(f"• {err}" for err in errors)
            self._output.setPlainText(text)

    def clear(self) -> None:
        """Сбросить содержимое панели."""
        self._output.setStyleSheet("")
        self._output.clear()
