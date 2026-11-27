registry: defects.md

| C-NN | **В `.venv` Windows-машины загружается `cv2 5.0.0`, хотя `pyproject.toml:22` требует `opencv-python>=4.13,<5`** — рядом стоят `opencv-python 4.13` и `opencv-contrib-python 5.0.0` (тянет `mediapipe`), побеждает вторая | `python -c "import cv2; print(cv2.__version__)"` → `5.0.0`, 2026-11-27; на замер букв влияние ≤ 1 кадра из 1056 | открыто; влияние на остальное приложение не проверено |
