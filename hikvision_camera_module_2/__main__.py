"""Точка входа: python -m hikvision_camera_module_2

Запускает тестовое GUI-приложение для отладки камеры.
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def main() -> None:
    from hikvision_camera_module_2.sdk_app.camera_test import main as app_main
    app_main()


if __name__ == "__main__":
    main()
