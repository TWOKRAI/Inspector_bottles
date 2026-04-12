# multiprocess_prototype_v3/frontend/launcher.py
"""Запуск простого окна v3: FPS → очередь camera_sim (command register_update)."""

from __future__ import annotations

import os
from typing import Any, Optional


def _send_register(
    shared_resources: Any,
    target_process: str,
    field_name: str,
    value: Any,
) -> None:
    if not shared_resources:
        return
    pd = shared_resources.get_process_data(target_process)
    if not pd:
        return
    q = pd.get_queue("system")
    if not q:
        return
    q.put(
        {
            "command": "register_update",
            "data": {"field_name": field_name, "value": value},
        }
    )


def run_v3_gui(process_ref: Any) -> None:
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QSlider, QWidget, QVBoxLayout

    app = QApplication([])
    win = QMainWindow()
    win.setWindowTitle("Inspector v3")
    central = QWidget()
    layout = QVBoxLayout(central)
    status = QLabel("FPS → camera_sim (register_update)")
    sld = QSlider(Qt.Horizontal)
    sld.setMinimum(1)
    sld.setMaximum(30)
    sld.setValue(10)
    layout.addWidget(status)
    layout.addWidget(sld)
    win.setCentralWidget(central)
    win.resize(420, 120)

    sr = getattr(process_ref, "shared_resources", None)

    def on_change(v: int) -> None:
        _send_register(sr, "camera_sim", "fps", int(v))
        status.setText(f"FPS set to {v} (camera_sim)")

    sld.valueChanged.connect(on_change)

    auto_ms = int(os.environ.get("V3_GUI_AUTOCLOSE_MS", "0") or "0")
    if auto_ms > 0:
        QTimer.singleShot(auto_ms, app.quit)

    win.show()
    app.exec_()
