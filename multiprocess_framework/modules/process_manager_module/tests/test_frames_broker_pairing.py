# -*- coding: utf-8 -*-
"""RED-приёмка точечной подписки ``frames.*`` в ``ObservabilitySubscriptionBroker``
(K1, Task 1.3 gui-service, слепой tester).

``ObservabilitySubscriptionBroker`` уже реализован (Task 5.11 / 4.4 — не стаб, тела
настоящие). Недостающая часть Task 1.3 (DESIGN, «Уточнено по DESIGN» п.5, FILES) —
ОДНА строка в ``POINT_COMMANDS``: ``"frames.subscribe": "frames.unsubscribe"``. Без
неё ``frames.subscribe`` не распознаётся как точечная команда: ``note_point``
возвращает ``False`` (см. ``note_point`` — ``if cmd in POINT_COMMANDS: ... return False``
в конце для нераспознанной команды), поэтому namerение не запоминается и
``forget_session`` не шлёт парное снятие.

Видел только тело ``observability_broker.py`` целиком (оно не стаб — обычный
существующий модуль) и текст K1 из задания.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from multiprocess_framework.modules.process_manager_module.process.observability_broker import (
    ObservabilitySubscriptionBroker,
)


def test_k1_frames_subscribe_is_point_command_and_forget_session_unsubscribes() -> None:
    """K1: note_point("gui","frames.subscribe",{"subscriber":"x.abc"}) → True;
    forget_session("abc") шлёт ("gui","frames.unsubscribe",{"subscriber":"x.abc"})."""
    sent: List[Tuple[str, str, Dict[str, Any]]] = []

    def _send_to(target: str, command: str, data: Dict[str, Any]) -> bool:
        sent.append((target, command, data))
        return True

    broker = ObservabilitySubscriptionBroker(
        broadcast=lambda command, data: 0,
        send_to=_send_to,
    )

    noted = broker.note_point("gui", "frames.subscribe", {"subscriber": "x.abc"})
    assert noted is True, "frames.subscribe должна быть точечной командой (POINT_COMMANDS) — note_point вернул False"

    removed = broker.forget_session("abc")
    assert "x.abc" in removed, f"forget_session не отметил 'x.abc' как снятый: {removed}"
    assert ("gui", "frames.unsubscribe", {"subscriber": "x.abc"}) in sent, (
        f"парная frames.unsubscribe не ушла процессу 'gui': {sent}"
    )
