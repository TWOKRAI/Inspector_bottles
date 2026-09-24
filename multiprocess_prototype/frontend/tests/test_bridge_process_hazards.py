# -*- coding: utf-8 -*-
"""Hazard-тест автора ``FrameBridge`` (Task 1.3, gui-service).

(c) Команды ``frames.*`` приходят на потоке ``message_processor``, рассылка — на потоке
    ``data_drain``. Если снятие подписки вклинится посреди рассылки одного кадра, счётчик
    уже снятого адреса упадёт ``KeyError``, а итерация по живому dict — ``RuntimeError:
    dictionary changed size``; и адрес получит push ПОСЛЕ того, как ``unsubscribe`` ему
    ответил. Проверка детерминирована, без шторма потоков: фейковый ``send_async``
    запускает ``cmd_unsubscribe`` в другом потоке ровно посреди рассылки и даёт ему
    0.2 с — под lock'ом он ждёт конца рассылки, без lock'а успевает вклиниться.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

from multiprocess_prototype.frontend.bridge_process import FrameBridge


def _frame_msg(sender: str) -> Dict[str, Any]:
    return {"sender": sender, "data": {"shm_actual_name": "slot0", "shm_index": 0, "shm_seqlock": False}}


def test_c_unsubscribe_from_another_thread_mid_fanout_is_serialized() -> None:
    """Инъекция: убрать ``with self._lock`` вокруг рассылки в ``on_drained`` →
    ``cmd_unsubscribe`` вклинивается → ``KeyError`` из ``on_drained`` → красный."""
    bridge_box: Dict[str, FrameBridge] = {}
    unsub_replies: List[Dict[str, Any]] = []
    pushes: List[str] = []
    racers: List[threading.Thread] = []

    class _RacingRouter:
        def send_async(self, message: Dict[str, Any], priority: str = "normal") -> None:
            pushes.append(message["targets"][0])
            if len(racers) == 0:
                # Посреди рассылки первого кадра снимаем ВТОРОГО подписчика из другого потока.
                t = threading.Thread(
                    target=lambda: unsub_replies.append(bridge_box["b"].cmd_unsubscribe({"subscriber": "p.2"})),
                    daemon=True,
                )
                racers.append(t)
                t.start()
                t.join(0.2)

    bridge = FrameBridge(_RacingRouter(), "gui", seqlock=False, owner_incarnation=False, loan_protocol=False)
    bridge_box["b"] = bridge
    bridge.cmd_subscribe({"subscriber": "p.1"})
    bridge.cmd_subscribe({"subscriber": "p.2"})

    errors: List[BaseException] = []

    def _drain() -> None:
        try:
            bridge.on_drained([_frame_msg("camA")])
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    drain = threading.Thread(target=_drain, daemon=True)
    drain.start()
    drain.join(3.0)
    assert not drain.is_alive(), "рассылка зависла"
    racers[0].join(3.0)
    assert not racers[0].is_alive(), "unsubscribe завис"

    assert errors == [], f"рассылка упала от конкурентного unsubscribe: {errors!r}"
    assert unsub_replies == [{"success": True, "subscriber": "p.2", "removed": True}]
    # Кадр разослан обоим (unsubscribe ждал конца рассылки) и посчитан обоим.
    assert pushes == ["p.1", "p.2"]
    stats = bridge.cmd_stats()
    assert stats["sent"] == {"p.1": 1}
    assert stats["sent_total"] == 2
    assert stats["errors"] == 0

    # После ответа unsubscribe на снятый адрес — ни одного push'а.
    bridge.on_drained([_frame_msg("camA")])
    assert pushes == ["p.1", "p.2", "p.1"]
