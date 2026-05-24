"""manager_setup.py -- Вспомогательные функции для настройки StateStoreManager.

Содержит default throttle-правила и утилиты для bootstrap StateStore.
"""

from __future__ import annotations


def build_throttle_rules() -> dict[str, float]:
    """Собрать throttle-правила по умолчанию для StateStoreManager.

    Правила ограничивают частоту обновлений высокочастотных метрик,
    чтобы не перегружать StateStore и IPC.

    Returns:
        dict вида {glob_pattern: min_interval_sec}.
    """
    return {
        # fps -- максимум 1 обновление в секунду
        "processes.**.state.fps": 1.0,
        # frame_count -- максимум 1 обновление в 2 секунды
        "processes.**.state.frame_count": 2.0,
        # drops -- максимум 1 обновление в 5 секунд (редкая метрика)
        "processes.**.state.drops": 5.0,
    }
