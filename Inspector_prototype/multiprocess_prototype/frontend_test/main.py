# -*- coding: utf-8 -*-
"""
Точка входа для теста только фронтенда.

Запускает окно с виджетами из frontend_module (SliderControl, CheckboxControl)
без процессов и бэкенда. RegistersManager с shared_registers.DrawRegisters.

Режимы:
  - Без аргументов: простой тест (виджеты + RegistersManager)
  - --coordinator: полный скелет (ApplicationCoordinator + FrontendManager)

Запуск из корня Inspector_prototype:
  python multiprocess_prototype/frontend_test/main.py
  python multiprocess_prototype/frontend_test/main.py --coordinator
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent
_modules = _root / "multiprocess_framework" / "refactored" / "modules"
for _p in (_root, _modules):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def main_simple() -> int:
    from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QScrollArea
    from PyQt5.QtCore import Qt

    from shared_registers import DrawRegisters
    from registers_module import RegistersManager
    from frontend_module import create_default_registry, compose_layout

    app = QApplication(sys.argv)
    app.setApplicationName("Frontend Test")

    rm = RegistersManager({"draw": DrawRegisters()})
    registry = create_default_registry()

    descriptors = [
        {"widget_type": "checkbox", "register_name": "draw", "field_name": "draw"},
        {"widget_type": "checkbox", "register_name": "draw", "field_name": "circles"},
        {"widget_type": "checkbox", "register_name": "draw", "field_name": "rectangles"},
        {"widget_type": "slider", "register_name": "draw", "field_name": "dp"},
        {"widget_type": "slider", "register_name": "draw", "field_name": "minDist"},
        {"widget_type": "slider", "register_name": "draw", "field_name": "param1"},
        {"widget_type": "slider", "register_name": "draw", "field_name": "param2"},
    ]

    central = QWidget()
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(central)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    central.registers_manager = rm
    central.access_level = 1

    compose_layout(central, descriptors, registry, rm, orientation="vertical", spacing=12)

    window = QMainWindow()
    window.setWindowTitle("Frontend Test — DrawRegisters")
    window.resize(480, 520)
    window.setCentralWidget(scroll)

    window.show()
    return app.exec_()


def main_with_coordinator() -> int:
    """Полный скелет: Coordinator + FrontendManager + регистры + конфиг."""
    from PyQt5.QtWidgets import QMainWindow, QWidget, QScrollArea
    from PyQt5.QtCore import Qt

    from shared_registers import DrawRegisters
    from registers_module import RegistersManager
    from frontend_module import (
        ApplicationCoordinator,
        create_default_registry,
        compose_layout,
    )

    config = {
        "window": {
            "window_min_width": 400,
            "window_min_height": 500,
        },
    }
    registers = RegistersManager({"draw": DrawRegisters()})
    connection_map = {}  # без бэкенда — пусто

    coordinator = ApplicationCoordinator(config=config)
    if not coordinator.initialize(registers=registers, connection_map=connection_map):
        return 1

    wm = coordinator.window_manager
    registry = create_default_registry()
    descriptors = [
        {"widget_type": "checkbox", "register_name": "draw", "field_name": "draw"},
        {"widget_type": "checkbox", "register_name": "draw", "field_name": "circles"},
        {"widget_type": "slider", "register_name": "draw", "field_name": "dp"},
        {"widget_type": "slider", "register_name": "draw", "field_name": "minDist"},
    ]

    def create_main_window(**kwargs):
        central = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(central)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        central.registers_manager = coordinator.registers
        central.access_level = 1
        compose_layout(central, descriptors, registry, coordinator.registers, orientation="vertical", spacing=12)
        win = QMainWindow()
        win.setWindowTitle("Frontend Test — Coordinator + FrontendManager")
        win.resize(420, 400)
        win.setCentralWidget(scroll)
        return win

    wm.register("main", create_main_window)
    return coordinator.run(initial_window="main")


def main() -> int:
    use_coordinator = "--coordinator" in sys.argv
    if use_coordinator:
        return main_with_coordinator()
    return main_simple()


if __name__ == "__main__":
    sys.exit(main())
