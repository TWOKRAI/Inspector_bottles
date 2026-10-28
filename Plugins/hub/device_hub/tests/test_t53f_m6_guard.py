"""Сторож H-A (T5.3f, f1.5): защёлка по поколению движения держит оба механизма — сброс после JOG_CONT и обход.

Purpose:
    ``test_t53r2_stop_hazards.py::test_rehold_after_failed_release_stop_then_process_stop_writes`` пропускает мутацию
    M6 (без сброса защёлки после ``JOG_CONT`` и без обхода защёлки для jog): ``request_stop`` в нём — первый вызов,
    а первый вызов сам открывает новое поколение защёлки (``RobotState.request_stop_begin`` зовёт
    ``_latch_reset_locked``), так что к моменту ``process_stop_plan`` защёлка пуста и оба механизма H-A не нужны.
    Этот тест доводит до пути, где они нужны: ``request_stop`` начался (защёлка сброшена, ``shutdown``), но ждёт
    замок перехода jog, который держит ``jog_hold``; пока замок занят, ``jog_hold`` пишет стоп прежнего jog (защёлка
    ``latch_level`` = SOFT, не упала) и запускает новое движение. Стоп процесса для нового движения обязан лечь:
    стоп прежнего jog его не покрывает.

Public API:
    Только тесты ``test_*``.

Stability: lite

Правила файла: ожидаемые значения — литералы; порядок шагов задают события (без таймингов); блокирующий вызов —
в daemon-потоке с дедлайном; область потоков теста закрывается в конце теста.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from Services.device_hub.tests.conftest import ClientRecorder

from Plugins.hub.device_hub.tests.test_t53r2_stop_hazards import (
    _CALL_S,
    _CONNECT_S,
    _JOG,
    _Rec,
    _Rig,
    _driver,
    _jog_moving,
    _moving,
    _quiet,
    _scope,
    _until,
    bounded,
)

_STEP_S = 10.0


def test_rehold_after_failed_release_new_generation_gets_process_stop() -> None:
    """H-A: стоп прежнего jog (rehold), записанный после начала ``request_stop`` и до его записи, не закрывает
    защёлку для нового движения: стоп процесса пишется. Записей после метки ровно две: стоп prev и стоп процесса."""
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        clients = ClientRecorder()
        drv = _driver(rig, rec, scope.spawn, clients=clients)
        try:
            _jog_moving(drv, rig)
            rig.journal.fail_stops = 1  # стоп release отклонён: у prev stop_sent False, stop_requested True
            assert bounded(lambda: drv.call("jog_release", {}), _CALL_S)["status"] == "error"
            if not drv.is_connected:  # отказ записи транспорт считает обрывом: связь поднимается заново
                assert bounded(drv.connect, _CONNECT_S) is True

            client = clients.last
            real_issue_stop = client.issue_stop
            armed = [True]  # шов: первая запись стопа после этого места — стоп prev внутри jog_hold
            arm_lock = threading.Lock()
            in_prev_stop = threading.Event()
            go = threading.Event()

            def gated_issue_stop(level: int) -> int:
                with arm_lock:
                    mine = armed[0]
                    armed[0] = False
                if mine:
                    in_prev_stop.set()
                    assert go.wait(_STEP_S), "шов не отпущен: request_stop не начался"
                return real_issue_stop(level)

            client.issue_stop = gated_issue_stop  # type: ignore[method-assign]

            hold_box: dict[str, Any] = {}
            hold = threading.Thread(
                target=lambda: hold_box.setdefault("r", drv.call("jog_hold", dict(_JOG))), daemon=True
            )
            hold.start()
            assert in_prev_stop.wait(_STEP_S), "jog_hold не дошёл до стопа prev"
            assert drv.state.view().shutdown is False  # request_stop ещё не начался

            mark = time.perf_counter()
            stop = threading.Thread(target=lambda: drv.request_stop(time.monotonic() + 8.0), daemon=True)
            stop.start()
            _until(lambda: drv.state.view().shutdown, _STEP_S, "request_stop не начался")
            go.set()  # теперь jog_hold: стоп prev -> JOG_CONT -> jog_started -> замок перехода свободен

            hold.join(_STEP_S)
            stop.join(_STEP_S)
            assert not hold.is_alive()
            assert not stop.is_alive()
            assert hold_box["r"]["status"] == "ok", hold_box  # JOG_CONT лёг до плана стопа процесса

            assert rig.journal.count(mark) == 2, rig.journal.stamps()
            _until(lambda: _moving(rig) == 0, 2.0, "новый jog не остановлен")
        finally:
            _quiet(drv.disconnect)
