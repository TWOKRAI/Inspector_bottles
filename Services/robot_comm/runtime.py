"""Process-local holder клиента робота — модель владельца соединения.

Один TCP-master на процесс: владелец (плагин robot_io) в start() создаёт
RobotClient, коннектит и публикует здесь; в shutdown() — disconnect + clear().
Потребители (vfd_control, robot_draw, calibration) берут get_client() и
НИКОГДА не создают/не закрывают клиент сами.

Holder НЕ бизнес-логика и НЕ singleton-паттерн: это явная точка передачи
одного экземпляра внутри ОДНОГО процесса. Через границу процессов не виден —
все плагины-потребители обязаны жить в одном process_name рецепта с владельцем
(мульти-процессный шаринг робота — IPC-канал, отдельная фаза).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from Services.robot_comm.errors import RobotNotConnectedError

if TYPE_CHECKING:
    from Services.robot_comm.core.client import RobotClient

_lock = threading.Lock()
_client: "RobotClient | None" = None


def set_client(client: "RobotClient") -> None:
    """Опубликовать клиент (только владелец, в start()).

    Raises:
        RuntimeError: клиент уже опубликован — в процессе может быть только
            один владелец (второй robot_io в том же процессе — ошибка рецепта).
    """
    global _client
    with _lock:
        if _client is not None:
            raise RuntimeError("RobotClient уже опубликован — в процессе допустим только один владелец (robot_io)")
        _client = client


def get_client() -> "RobotClient":
    """Получить опубликованный клиент (потребители, read-only владение).

    Raises:
        RobotNotConnectedError: владелец ещё не стартовал. Частая причина —
            плагин-потребитель оказался в другом процессе рецепта, чем robot_io.
    """
    with _lock:
        if _client is None:
            raise RobotNotConnectedError(
                "RobotClient не опубликован: плагин-владелец robot_io не стартовал. "
                "Проверьте, что robot_io и плагины-потребители (vfd_control, robot_draw) "
                "находятся в ОДНОМ process_name рецепта."
            )
        return _client


def peek_client() -> "RobotClient | None":
    """Клиент или None без исключения (для статуса/диагностики)."""
    with _lock:
        return _client


def clear() -> None:
    """Снять публикацию (только владелец, в shutdown()). Идемпотентно."""
    global _client
    with _lock:
        _client = None
