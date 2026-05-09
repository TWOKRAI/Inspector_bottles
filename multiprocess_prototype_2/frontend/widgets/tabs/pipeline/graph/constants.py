"""Визуальные константы для графа pipeline."""

# Размеры узлов
NODE_WIDTH = 160
NODE_HEIGHT = 60
NODE_CORNER_RADIUS = 6
PORT_RADIUS = 5
PORT_SPACING = 20

# Цвета по категориям плагинов
CATEGORY_COLORS: dict[str, str] = {
    "source": "#4caf50",
    "processing": "#2196f3",
    "output": "#ff9800",
    "rendering": "#e91e63",
    "control": "#9c27b0",
    "utility": "#9e9e9e",
    "service": "#00bcd4",
}

# Цвета wire
WIRE_COLOR = "#aaaaaa"
WIRE_COLOR_HOVER = "#ffffff"
WIRE_WIDTH = 2.0

# Grid / Layout
GRID_SPACING_X = 220
GRID_SPACING_Y = 100
