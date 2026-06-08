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
    "filter": "#ff6b9d",  # фильтрация координат (virtual line и т.п.)
    "output": "#ff9800",
    "rendering": "#e91e63",
    "control": "#9c27b0",
    "utility": "#9e9e9e",
    "service": "#00bcd4",
    "io": "#795548",  # драйверы/шина (Modbus и т.п.)
    "sink": "#607d8b",  # приёмники-стоки (вывод данных наружу)
}

# Цвета wire
WIRE_COLOR = "#aaaaaa"
WIRE_COLOR_HOVER = "#ffffff"
WIRE_WIDTH = 2.0

# Grid / Layout
GRID_SPACING_X = 220
GRID_SPACING_Y = 100

# Цвет узла Display (SHM-канал)
DISPLAY_CATEGORY_COLOR = "#2e7d32"

# Process-контейнер (рамка вокруг плагин-нод одного процесса, D.1)
CONTAINER_PADDING = 16  # отступ рамки от bounding-rect плагин-нод
CONTAINER_HEADER_H = 24  # высота заголовка (имя процесса) над нодами
CONTAINER_INNER_GAP = 40  # горизонтальный зазор между плагинами в цепочке
CONTAINER_CORNER_RADIUS = 10
CONTAINER_FILL = "#1e2730"  # полупрозрачная заливка (через alpha в коде)
CONTAINER_BORDER = "#5a6b7a"
CONTAINER_TITLE_COLOR = "#cfd8e0"
