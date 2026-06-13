# -*- coding: utf-8 -*-
"""Секция «Обучение» — UI поверх Services/ml_train.

Обучение запускается ОТДЕЛЬНЫМ процессом (QProcess: python -m Services.ml_train
train <cfg>): GUI-процесс не тянет torch и не блокируется; stdout стримится
в лог. Таблица прогонов — RunRegistry (torch-free, in-process); экспорт
лучшего прогона в ONNX — тоже subprocess.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess, QProcessEnvironment
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec
from multiprocess_prototype.main import PROJECT_ROOT

_RUNS_DIR = PROJECT_ROOT / "data" / "ml_train" / "runs"
_RUN_COLUMNS = ("Прогон", "Архитектура", "Эпоха", "acc", "bal_acc", "angle°")


class MlTrainWidget(QWidget):
    """Форма обучения: конфиг → запуск/лог → таблица прогонов → экспорт."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._build_ui()
        self._reload_configs()
        self.refresh_runs()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        form = QFormLayout()

        cfg_row = QHBoxLayout()
        self.config_combo = QComboBox()
        self.config_combo.setObjectName("nn_train_config")
        cfg_row.addWidget(self.config_combo, stretch=1)
        browse = QPushButton("Обзор…")
        browse.setToolTip("Выбрать свой YAML-конфиг обучения (TrainConfig)")
        browse.clicked.connect(self._on_browse_config)
        cfg_row.addWidget(browse)
        form.addRow("Конфиг:", cfg_row)

        self.run_name_edit = QLineEdit()
        self.run_name_edit.setPlaceholderText("авто: <архитектура>_<время>")
        form.addRow("Имя прогона:", self.run_name_edit)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.train_btn = QPushButton("Обучить")
        self.train_btn.setObjectName("nn_train_start")
        self.train_btn.clicked.connect(self._on_train)
        btn_row.addWidget(self.train_btn)
        self.stop_btn = QPushButton("Остановить")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        self.refresh_btn = QPushButton("Обновить прогоны")
        self.refresh_btn.clicked.connect(self.refresh_runs)
        btn_row.addWidget(self.refresh_btn)
        self.export_btn = QPushButton("Экспорт лучшего в ONNX")
        self.export_btn.setObjectName("nn_train_export")
        self.export_btn.setToolTip("Лучший прогон по balanced_accuracy → data/models (виден в Pipeline)")
        self.export_btn.clicked.connect(self._on_export_best)
        btn_row.addWidget(self.export_btn)
        layout.addLayout(btn_row)

        self.status_label = QLabel("Готово. Обучение запускается отдельным процессом — GUI не блокируется.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("nn_train_log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setPlaceholderText("Лог обучения (stdout процесса)…")
        layout.addWidget(self.log_view, stretch=2)

        self.runs_table = QTableWidget(0, len(_RUN_COLUMNS))
        self.runs_table.setObjectName("nn_train_runs")
        self.runs_table.setHorizontalHeaderLabels(_RUN_COLUMNS)
        self.runs_table.horizontalHeader().setStretchLastSection(True)
        self.runs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.runs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.runs_table, stretch=1)

    # ------------------------------------------------------------------ #
    # Конфиги и прогоны
    # ------------------------------------------------------------------ #

    def _reload_configs(self) -> None:
        from Services.ml_train import PRESETS_DIR

        self.config_combo.clear()
        for path in sorted(PRESETS_DIR.glob("*.yaml")):
            self.config_combo.addItem(path.name, str(path))

    def _select_config(self, path: str) -> None:
        idx = self.config_combo.findData(path)
        if idx < 0:
            self.config_combo.addItem(Path(path).name, path)
            idx = self.config_combo.count() - 1
        self.config_combo.setCurrentIndex(idx)

    def refresh_runs(self) -> None:
        """Перечитать реестр прогонов (torch не нужен)."""
        from Services.ml_train import RunRegistry

        registry = RunRegistry(_RUNS_DIR)
        registry.scan()
        rows = registry.summary()
        self.runs_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = (
                row["run"],
                row["arch"],
                str(row["best_epoch"]),
                _fmt(row["accuracy"]),
                _fmt(row["balanced_accuracy"]),
                _fmt(row["angle_mae_deg"]),
            )
            for c, value in enumerate(values):
                self.runs_table.setItem(r, c, QTableWidgetItem(value))
        best = registry.best()
        self.export_btn.setEnabled(best is not None)
        self._best_checkpoint = str(best.checkpoint) if best is not None else None

    # ------------------------------------------------------------------ #
    # Запуск/остановка subprocess
    # ------------------------------------------------------------------ #

    def _on_browse_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Конфиг обучения", str(PROJECT_ROOT), "YAML (*.yaml *.yml)")
        if path:
            self._select_config(path)

    def _on_train(self) -> None:
        config = self.config_combo.currentData()
        if not config:
            self.status_label.setText("Не выбран конфиг обучения.")
            return
        args = ["-u", "-m", "Services.ml_train", "train", str(config)]
        run_name = self.run_name_edit.text().strip()
        if run_name:
            args += ["--run-name", run_name]
        self._spawn(args, "Обучение запущено…")

    def _on_export_best(self) -> None:
        if not getattr(self, "_best_checkpoint", None):
            self.status_label.setText("Нет прогона с чекпоинтом для экспорта.")
            return
        self._spawn(
            ["-u", "-m", "Services.ml_train", "export", self._best_checkpoint],
            "Экспорт в ONNX…",
        )

    def _spawn(self, args: list[str], status: str) -> None:
        if self._process is not None:
            self.status_label.setText("Уже выполняется процесс — дождитесь завершения или остановите.")
            return
        process = QProcess(self)
        process.setWorkingDirectory(str(PROJECT_ROOT))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")  # кириллица лога без cp1251-каши
        process.setProcessEnvironment(env)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._on_output)
        process.finished.connect(self._on_finished)
        self._process = process
        self.log_view.clear()
        self.status_label.setText(status)
        self.train_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        process.start(sys.executable, args)

    def _on_stop(self) -> None:
        if self._process is not None:
            self._process.kill()
            self.status_label.setText("Процесс остановлен пользователем.")

    def _on_output(self) -> None:
        if self._process is None:
            return
        text = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if text:
            self.log_view.appendPlainText(text.rstrip("\n"))

    def _on_finished(self, exit_code: int, _exit_status: object) -> None:
        self._process = None
        self.train_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText(
            "Готово (exit 0). Таблица прогонов обновлена."
            if exit_code == 0
            else f"Процесс завершился с кодом {exit_code} — см. лог."
        )
        self.refresh_runs()


def _fmt(value: Any) -> str:
    return f"{value:.4f}" if isinstance(value, float) else "—"


class _MlTrainSection:
    """SectionProtocol: «Обучение»."""

    def __init__(self) -> None:
        self._widget: MlTrainWidget | None = None

    @property
    def key(self) -> str:
        return "__nn_ml_train__"

    @property
    def title(self) -> str:
        return "Обучение"

    def widget(self) -> QWidget:
        if self._widget is None:
            self._widget = MlTrainWidget()
        return self._widget

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None:
        if self._widget is not None:
            self._widget.refresh_runs()

    def on_deactivated(self) -> None: ...


def build_ml_train_section(_services: Any, _runtime: Any, *, parent_key: str) -> SectionSpec:
    """SectionSpec секции «Обучение» (lazy)."""
    section = _MlTrainSection()
    return SectionSpec(
        key=section.key,
        title=section.title,
        factory=lambda _ctx_arg: section,
        parent_key=parent_key,
        lazy=True,
    )
