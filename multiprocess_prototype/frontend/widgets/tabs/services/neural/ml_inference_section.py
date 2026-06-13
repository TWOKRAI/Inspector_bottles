# -*- coding: utf-8 -*-
"""Секция «Модели (инференс)» — каталог data/models глазами ml_inference.

Read-only таблица моделей (id, имя, задача, backend, вход, метки) из
ModelRegistry — той же, что наполняет выпадающий список ноды ml_inference
в Pipeline. Сам инференс выполняется нодой в пайплайне, не здесь.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec
from multiprocess_prototype.main import PROJECT_ROOT

_MODELS_DIR = PROJECT_ROOT / "data" / "models"
_COLUMNS = ("ID", "Имя", "Задача", "Backend", "Вход (H×W)", "Метки")


class MlInferenceWidget(QWidget):
    """Каталог моделей инференса (data/models)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        hint = QLabel(
            "Модели каталога <b>data/models</b> (веса + sidecar YAML). Этот же список видит "
            "нода <b>ml_inference</b> во вкладке «Пайплайн» — инференс выполняется там. "
            "Новые модели появляются после экспорта из секции «Обучение» или вручную."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Обновить")
        refresh_btn.setObjectName("nn_models_refresh")
        refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(refresh_btn)
        open_btn = QPushButton("Открыть папку моделей")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(_MODELS_DIR))))
        btn_row.addWidget(open_btn)
        btn_row.addStretch()
        self.count_label = QLabel()
        btn_row.addWidget(self.count_label)
        layout.addLayout(btn_row)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setObjectName("nn_models_table")
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, stretch=1)

    def refresh(self) -> None:
        """Пересканировать каталог моделей (numpy+yaml, ML-стек не нужен)."""
        from Services.ml_inference.core.registry import ModelRegistry

        registry = ModelRegistry(_MODELS_DIR)
        specs = registry.scan()
        self.table.setRowCount(len(specs))
        for r, (model_id, spec) in enumerate(sorted(specs.items())):
            labels = spec.load_labels()
            values = (
                model_id,
                spec.name,
                spec.task,
                spec.backend,
                f"{spec.input_size[0]}×{spec.input_size[1]}",
                f"{len(labels)} классов" if labels else "—",
            )
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(value))
        self.count_label.setText(f"Моделей: {len(specs)}")


class _MlInferenceSection:
    """SectionProtocol: «Модели (инференс)»."""

    def __init__(self) -> None:
        self._widget: MlInferenceWidget | None = None

    @property
    def key(self) -> str:
        return "__nn_ml_inference__"

    @property
    def title(self) -> str:
        return "Модели (инференс)"

    def widget(self) -> QWidget:
        if self._widget is None:
            self._widget = MlInferenceWidget()
        return self._widget

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None:
        if self._widget is not None:
            self._widget.refresh()

    def on_deactivated(self) -> None: ...


def build_ml_inference_section(_services: Any, _runtime: Any, *, parent_key: str) -> SectionSpec:
    """SectionSpec секции «Модели (инференс)» (lazy)."""
    section = _MlInferenceSection()
    return SectionSpec(
        key=section.key,
        title=section.title,
        factory=lambda _ctx_arg: section,
        parent_key=parent_key,
        lazy=True,
    )
