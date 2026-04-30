"""Константы pipeline_tab — размеры thumbnail, FPS throttle и т.д."""

# ---------------------------------------------------------------------------
# Thumbnail (live-preview в нодах)
# ---------------------------------------------------------------------------
# Размер thumbnail'а в пикселях (ширина x высота).
# NodePreviewBridge масштабирует кадр до этих размеров перед отправкой в ноду.
THUMBNAIL_WIDTH = 160
THUMBNAIL_HEIGHT = 120

# Интервал обновления thumbnail в миллисекундах (throttle).
# 100 мс ~ 10 FPS — компромисс между отзывчивостью и нагрузкой на CPU.
THUMBNAIL_UPDATE_INTERVAL_MS = 100

# Минимальный интервал (максимальный FPS) — 200 мс ~ 5 FPS.
THUMBNAIL_MIN_INTERVAL_MS = 200

# Z-слой thumbnail overlay относительно ноды.
# Должен быть ниже портов, но выше фона ноды.
THUMBNAIL_Z_OFFSET = -0.5
