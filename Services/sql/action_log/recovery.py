"""
ActionLogRecovery -- восстановление состояния из action_log при старте.

Читает последние N Actions из таблицы action_log,
фильтрует undoable=True и не-reverted, применяет через handlers.
Применение до показа UI -- состояние восстановлено до открытия окна.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_framework.modules.actions_module.bus import ActionBus, IRegistersManagerGui
    from .repository import ActionLogRepository

logger = logging.getLogger(__name__)


class ActionLogRecovery:
    """Восстановление состояния приложения из персистентного лога действий."""

    def __init__(
        self,
        repository: ActionLogRepository,
        bus: ActionBus,
        rm: IRegistersManagerGui,
        *,
        max_age_hours: float = 24.0,
    ) -> None:
        self._repository = repository
        self._bus = bus
        self._rm = rm
        self._max_age_hours = max_age_hours

    def recover(self, max_actions: int = 200) -> int:
        """Восстановить состояние. Возвращает количество применённых Actions.

        Алгоритм:
        1. Читаем последние max_actions из лога
        2. Сортируем по timestamp ASC (от старых к новым)
        3. Фильтруем: только undoable=True
        4. Фильтруем: исключаем actions старше max_age_hours
        5. Компенсируем UNDO-записи: если description начинается с "[UNDO]",
           находим и удаляем соответствующую пару
        6. Применяем каждый action через handler.apply(action, rm)
        7. Ошибки при apply -- log warning, skip, continue
        """
        try:
            actions = self._repository.find_recent(max_actions)
        except Exception:
            logger.exception("Ошибка чтения action_log для recovery")
            return 0

        if not actions:
            return 0

        # Сортируем по timestamp ASC
        actions.sort(key=lambda a: a.timestamp)

        # Фильтр: только undoable
        actions = [a for a in actions if a.undoable]

        # Фильтр: не старше max_age_hours
        cutoff = time.time() - self._max_age_hours * 3600
        actions = [a for a in actions if a.timestamp >= cutoff]

        if not actions:
            return 0

        # Компенсация UNDO-записей
        actions = self._compensate_undos(actions)

        # Применяем через handlers
        applied = 0
        for action in actions:
            handler = self._bus._handlers.get(action.action_type)
            if handler is None:
                logger.warning(
                    "Recovery: handler не найден для %s, пропуск action_id=%s",
                    action.action_type,
                    action.action_id,
                )
                continue

            try:
                handler.apply(action, self._rm)
                applied += 1
            except Exception:
                logger.warning(
                    "Recovery: ошибка apply для action_id=%s, пропуск",
                    action.action_id,
                    exc_info=True,
                )

        return applied

    def dry_run(self, max_actions: int = 200) -> bool:
        """Проверить детерминированность recovery без реального применения.

        Returns:
            True если все actions корректны и handlers найдены.
        """
        try:
            actions = self._repository.find_recent(max_actions)
        except Exception:
            return False

        actions.sort(key=lambda a: a.timestamp)
        actions = [a for a in actions if a.undoable]
        cutoff = time.time() - self._max_age_hours * 3600
        actions = [a for a in actions if a.timestamp >= cutoff]
        actions = self._compensate_undos(actions)

        for action in actions:
            if self._bus._handlers.get(action.action_type) is None:
                return False
            # Проверяем наличие необходимых данных
            if not action.forward_patch:
                return False

        return True

    @staticmethod
    def _compensate_undos(actions: list) -> list:
        """Убрать UNDO-записи и соответствующие им оригиналы.

        Если description начинается с "[UNDO] " -- ищем последний action
        с тем же coalesce_key (или description без [UNDO] prefix) и удаляем оба.
        """
        # Индексы для удаления
        to_remove: set[int] = set()

        for i, action in enumerate(actions):
            if i in to_remove:
                continue
            desc = action.description or ""
            if not desc.startswith("[UNDO] "):
                continue
            # Это UNDO-запись -- ищем оригинал (последний matching перед ним)
            original_desc = desc[len("[UNDO] "):]
            for j in range(i - 1, -1, -1):
                if j in to_remove:
                    continue
                if (actions[j].description or "") == original_desc:
                    to_remove.add(i)
                    to_remove.add(j)
                    break
            else:
                # Оригинал не найден -- просто удалить UNDO-запись
                to_remove.add(i)

        return [a for idx, a in enumerate(actions) if idx not in to_remove]
