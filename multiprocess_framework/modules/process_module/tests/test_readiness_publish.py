# -*- coding: utf-8 -*-
"""Task 1.2 (system-run-state) — слепой приёмочный тест публикации готовности полем heartbeat-сообщения.

Контракт — DESIGN п.4 ``plans/2026-10-27_system-run-state/tasks/1.2.md``:
``heartbeat_msg["readiness"] = <последний снимок>`` (``ProcessHeartbeat._send_heartbeat``);
heartbeat только читает готовый dict (копию), никакого расчёта на своём потоке;
в сообщении только bool/str/list/dict/float (Dict at Boundary) — оно переживает pickle через настоящую очередь.

Стенд — настоящий ``ProcessHeartbeat`` (``start()`` -> воркер ``heartbeat_sender`` настоящего ``WorkerManager``,
``heartbeat_interval = 0.2``), настоящая ``multiprocessing.Queue`` spawn-контекста; носитель — минимальный фейк
(образец ``test_heartbeat_sender_survives_pause_all.py``), его ``send_message`` кладёт сообщение в очередь.
Сообщение приходит из очереди уже после pickle-раунда. Чтение очереди — в daemon-потоке с join-дедлайном.

Решение тестера (``# ASSUMPTION``), вынесено в отчёт «ВОПРОС ЛИДУ»: DESIGN не называет атрибут носителя, из которого
heartbeat берёт готовый снимок (в ``process_module.py`` он «атрибут снимка»). Тест кладёт снимок в
``_readiness_snapshot`` носителя; имя вынесено в константу ``_SNAPSHOT_ATTR`` — переименование правится в одном месте.
"""

from __future__ import annotations

import multiprocessing
import queue
import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import ProcessHeartbeat
from multiprocess_framework.modules.worker_module import WorkerManager

#: ASSUMPTION: имя атрибута носителя со снимком готовности (DESIGN его не называет).
_SNAPSHOT_ATTR = "_readiness_snapshot"
_DEADLINE_S = 20.0

_FIRST = {
    "ready": False,
    "reasons": [
        {"node": "rp_proc.rp_camera", "severity": "failure", "reason": "камера не отвечает", "source": "readiness"},
        {"node": "rp_proc.rp_light", "severity": "out_of_spec", "reason": "переподключение", "source": "readiness"},
    ],
    "paused": True,
    "at": 1234.5,
}
_SECOND = {"ready": True, "reasons": [], "paused": False, "at": 1240.25}


class _Services:
    """Минимальный носитель ``ProcessHeartbeat``; ``send_message`` пишет в настоящую очередь."""

    def __init__(self, worker_manager: WorkerManager, out_queue: Any) -> None:
        self.name = "rp_proc"
        self.worker_manager = worker_manager
        self._out = out_queue
        self._config = {"heartbeat_interval": 0.2}

    def get_config(self, key: str, default=None):
        return self._config.get(key, default)

    def send_message(self, target: str, message: dict) -> bool:
        self._out.put(message)
        return True

    def log_info(self, msg: str, **kw) -> None: ...

    def log_debug(self, msg: str, **kw) -> None: ...

    def log_warning(self, msg: str, **kw) -> None: ...

    def log_error(self, msg: str, **kw) -> None: ...


def _heartbeats_until(out_queue: Any, predicate, deadline_s: float) -> list[dict]:
    """Читать очередь в daemon-потоке, пока ``predicate(накопленные heartbeat)`` не истинен или не вышел срок."""
    got: list[dict] = []
    done = threading.Event()

    def pump() -> None:
        end = time.monotonic() + deadline_s
        while time.monotonic() < end and not done.is_set():
            try:
                msg = out_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if isinstance(msg, dict) and msg.get("command") == "heartbeat":
                got.append(msg)
                if predicate(got):
                    return

    thread = threading.Thread(target=pump, daemon=True, name="rp-queue-pump")
    thread.start()
    thread.join(deadline_s + 5.0)
    done.set()
    assert not thread.is_alive(), "чтение очереди зависло"
    return got


@pytest.mark.timeout(90)
def test_heartbeat_message_carries_readiness() -> None:
    """Каждое heartbeat-сообщение несёт ``readiness`` — последний снимок как есть (литерал), и следует за его сменой."""
    out_queue = multiprocessing.get_context("spawn").Queue()
    wm = WorkerManager(manager_name="wm_readiness_publish")
    wm.initialize()
    services = _Services(wm, out_queue)
    setattr(services, _SNAPSHOT_ATTR, dict(_FIRST))
    heartbeat = ProcessHeartbeat(services)
    heartbeat.start()
    try:
        first = _heartbeats_until(out_queue, lambda msgs: len(msgs) >= 3, _DEADLINE_S)
        assert len(first) >= 3, f"heartbeat-сообщений меньше трёх за {_DEADLINE_S} с: {len(first)}"
        for msg in first:
            assert msg.get("readiness") == _FIRST, f"поле readiness не равно снимку: {msg.get('readiness')!r}"

        # снимок сменился -> heartbeat читает ПОСЛЕДНИЙ (не залипает на первом)
        setattr(services, _SNAPSHOT_ATTR, dict(_SECOND))
        later = _heartbeats_until(out_queue, lambda msgs: msgs[-1].get("readiness") == _SECOND, _DEADLINE_S)
        assert later and later[-1].get("readiness") == _SECOND, [m.get("readiness") for m in later]
    finally:
        wm.stop_all_workers()
        out_queue.close()
        out_queue.cancel_join_thread()
