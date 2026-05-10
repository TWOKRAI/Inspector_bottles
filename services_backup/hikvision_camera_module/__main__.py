# -*- coding: utf-8 -*-
"""
Точка входа: python -m hikvision_camera_module

Запускает оригинальное окно SDK (Clean Camera Test).
"""

import sys
from pathlib import Path

# Добавляем корень проекта в путь
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def main():
    from hikvision_camera_module.sdk_app.clean_camera_test import main as sdk_main
    sdk_main()


if __name__ == "__main__":
    main()
