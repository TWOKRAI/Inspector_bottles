"""Точка входа: python -m hikvision_camera

Запускает SDK App — автономное GUI для отладки камеры Hikvision.
"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def main() -> None:
    from hikvision_camera.sdk_app.main_window import main as app_main

    app_main()


if __name__ == "__main__":
    main()
