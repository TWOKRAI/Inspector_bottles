"""
Размер буфера SharedMemory camera_frame (максимум для всех режимов).

Должен совпадать с CameraConfig.memory и с ресайзом перед записью в SHM.
"""

CAMERA_SHM_HEIGHT = 1080
CAMERA_SHM_WIDTH = 1920
