"""Heartbeat подпакет — периодическая отправка heartbeat-сообщений ProcessManager-у.

``ProcessHeartbeat`` отдаётся лениво (PEP 562): пакет не тянет ``process_heartbeat`` при
собственном импорте, поэтому ``from ...heartbeat import telemetry`` (и прочие подмодули) не
запускает загрузку цепочки ``process_heartbeat`` -> ``cpu_clock`` из чужого потока (C-92).
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .process_heartbeat import ProcessHeartbeat

__all__ = ["ProcessHeartbeat"]


def __getattr__(name: str) -> object:
    if name == "ProcessHeartbeat":
        from .process_heartbeat import ProcessHeartbeat

        return ProcessHeartbeat
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
