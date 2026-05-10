"""Константы для дерева процессов вкладки «Процессы».

Формат унифицирован с sources_tab/constants.py:
4 колонки, ROLE_* для идентификации, списки параметров.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

# --- Индексы колонок (4 штуки, как в Sources) ---
COL_NAME = 0       # Имя элемента с иконками
COL_VAL = 1        # Значение / Статус
COL_COMMENT = 2    # Описание / комментарий
COL_SUMMARY = 3    # Сводка

# --- Заголовки колонок ---
COLUMN_HEADERS: list[str] = ["Элемент", "Значение", "Комментарий", "Сводка"]

# --- Обратная совместимость: старые имена колонок ---
COL_STATUS = COL_VAL
COL_PID = COL_COMMENT
COL_UPTIME = COL_SUMMARY
COL_HEARTBEAT = COL_SUMMARY  # был 4-й, теперь mapped на 3-й

# --- Роли для QStandardItem.data() ---
ROLE_TYPE = Qt.ItemDataRole.UserRole + 1    # "process"|"worker"|"param_group"|"param"
ROLE_PROC = Qt.ItemDataRole.UserRole + 2    # ключ процесса
ROLE_WORKER = Qt.ItemDataRole.UserRole + 3  # ключ воркера (только для worker-узлов и их параметров)
ROLE_PARAM = Qt.ItemDataRole.UserRole + 4   # ключ параметра (только для param-узлов)

# --- Параметры процесса для отображения в дереве ---
# (param_key, display_name, description)
PROC_PARAMS: list[tuple[str, str, str]] = [
    ("class_path",  "Класс",      "Класс процесса"),
    ("priority",    "Приоритет",   "low / normal / high / urgent"),
    ("pid",         "PID",         "ID процесса"),
    ("auto_start",  "Автозапуск",  "Запуск при старте системы"),
    ("alive",       "Alive",       "Процесс жив"),
]

# Параметры процесса, которые берутся из monitor (runtime)
PROC_RUNTIME_PARAMS: frozenset[str] = frozenset({"pid", "alive"})

# Параметры процесса, которые берутся из editor (config)
PROC_CONFIG_PARAMS: frozenset[str] = frozenset({"class_path", "priority", "auto_start"})

# --- Параметры воркера для отображения в дереве ---
# (param_key, display_name, description)
WORKER_PARAMS: list[tuple[str, str, str]] = [
    ("worker_type",        "Тип",       "Тип воркера"),
    ("target_interval_ms", "Интервал",  "Целевой интервал цикла, мс"),
    ("cycle_duration_ms",  "Цикл",      "Фактическое время цикла, мс"),
    ("effective_hz",       "Частота",   "Эффективная частота"),
    ("sleep_ms",           "Задержка",  "Smart sleep, мс"),
    ("restart_count",      "Рестарты",  "Количество рестартов"),
]

# Параметры воркера, которые берутся из monitor (runtime)
WORKER_RUNTIME_PARAMS: frozenset[str] = frozenset({
    "cycle_duration_ms", "effective_hz", "sleep_ms", "restart_count",
})

# Параметры воркера, которые берутся из editor (config)
WORKER_CONFIG_PARAMS: frozenset[str] = frozenset({
    "worker_type", "target_interval_ms",
})

# --- Цвета статусов (HEX-строки) ---
STATUS_COLORS: dict[str, str] = {
    "running":       "#27ae60",
    "stopped":       "#95a5a6",
    "crashed":       "#e74c3c",
    "unresponsive":  "#e67e22",
    "failed":        "#c0392b",
    "initializing":  "#3498db",
    "ready":         "#2ecc71",
    "stopping":      "#f39c12",
    "error":         "#e74c3c",
    "created":       "#9b59b6",
    "paused":        "#f1c40f",
}

# --- Цвета статусов воркеров (HEX-строки) ---
WORKER_STATUS_COLORS: dict[str, str] = {
    "running":  "#27ae60",
    "stopped":  "#95a5a6",
    "paused":   "#f1c40f",
    "error":    "#e74c3c",
    "created":  "#9b59b6",
}

# --- Иконки статусов ---
STATUS_ICONS: dict[str, str] = {
    "running":       "\u25cf",  # ●
    "stopped":       "\u25cb",  # ○
    "crashed":       "\u2716",  # ✖
    "unresponsive":  "\u25cb",  # ○
    "configured":    "\u25cb",  # ○
    "paused":        "\u25cb",  # ○
}

__all__ = [
    "COL_NAME", "COL_VAL", "COL_COMMENT", "COL_SUMMARY",
    "COL_STATUS", "COL_PID", "COL_UPTIME", "COL_HEARTBEAT",
    "COLUMN_HEADERS",
    "ROLE_TYPE", "ROLE_PROC", "ROLE_WORKER", "ROLE_PARAM",
    "PROC_PARAMS", "PROC_RUNTIME_PARAMS", "PROC_CONFIG_PARAMS",
    "WORKER_PARAMS", "WORKER_RUNTIME_PARAMS", "WORKER_CONFIG_PARAMS",
    "STATUS_COLORS", "WORKER_STATUS_COLORS", "STATUS_ICONS",
]
