"""state_store_config.py — Доменные правила middleware для StateStoreManager.

Изолирует доменную логику валидации и throttle от инфраструктуры (process.py).
Функции возвращают plain dict — легко тестируются без зависимостей от IPC.

Dict at Boundary: оба метода возвращают dict[str, dict] / dict[str, float],
которые передаются в соответствующие Middleware-конструкторы.
"""

from __future__ import annotations


def build_validation_rules() -> dict[str, dict]:
    """Правила валидации для StateStoreManager.

    Паттерн → {type, min, max, enum}.
    Пути с '*' матчатся через glob в ValidationMiddleware.

    Returns:
        dict с паттернами путей и правилами валидации.
    """
    return {
        # --- Конфигурация камер ---
        "cameras.*.config.fps": {"type": int, "min": 1, "max": 240},
        "cameras.*.config.camera_type": {
            "type": str,
            "enum": ["webcam", "hikvision", "simulator", "file"],
        },
        "cameras.*.config.resolution_width": {"type": int, "min": 1, "max": 7680},
        "cameras.*.config.resolution_height": {"type": int, "min": 1, "max": 4320},
        # --- Состояние камер ---
        "cameras.*.state.status": {
            "type": str,
            "enum": ["stopped", "running", "error", "initialized", "paused"],
        },
        # --- Конфигурация рендерера ---
        # '*' матчит любое поле конфига рендерера (overlay_alpha, width, height и т.д.)
        "renderer.config.*": {"type": (int, float, str, bool)},
    }


def build_throttle_rules() -> dict[str, float]:
    """Правила throttle для StateStoreManager.

    Паттерн → интервал в секундах (0 = полная блокировка).

    Returns:
        dict с паттернами путей и интервалами throttle.
    """
    return {
        # FPS обновляется не чаще 1 раза в секунду — высокочастотная метрика
        "cameras.*.state.actual_fps": 1.0,
        # Счётчик дропов — не чаще 1 раза в 2 секунды
        "cameras.*.state.drops_count": 2.0,
        # Порядковый номер кадра — блокировать полностью, не нужен в StateStore
        "cameras.*.state.last_frame_seq": 0,
    }
