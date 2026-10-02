# -*- coding: utf-8 -*-
"""Task 4.7d-4 — слепые приёмочные тесты: отбраковщик принимает маркер ``not_inspected``.

Источник — только acceptance подзадачи 4.7d-4 плана ``plans/transport-single-policy/task-4.7.md``.
Реализации маркера на момент написания нет; тесты красные по построению.

Маркер строится ЛИТЕРАЛЬНЫМ словарём по контракту (модуль маркера — другая подзадача, не импортируется).
Проверяются наблюдаемые эффекты: ``inspection_result`` item'а, документы вердиктов и широкие записи
в фейковом ``PluginContext``, счётчики плагина, длительность ``process``. Ожидаемые значения — литералы.

Где в красном сегодня НЕ было бы падения (маркер-item без детекций сегодня уходит как обычный ``pass``),
тест держит якорь существования — ``action == ожидаемого`` — иначе «ничего не записано» было бы зелёным
на пустом месте.

Любой вызов, способный блокироваться (задержка отбраковки, исполнитель в потоке), идёт в daemon-потоке
с дедлайном на ``join``.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable, Dict, List

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from Plugins.control.robot_control.plugin import RobotControlPlugin
from Plugins.control.robot_control.registers import RobotControlRegisters


class _Ctx:
    """PluginContext в объёме, который использует плагин. Пишет всё, что дали."""

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        self.config: Dict[str, Any] = dict(config or {})
        self.registers = None
        self.command_manager = None
        self.process_name = "inspector"
        self.plugin_name = "robot_control"
        self.events: List[Dict[str, Any]] = []
        self.flights: List[Dict[str, Any]] = []
        self.documents: List[Dict[str, Any]] = []

    def flight_dump(self, reason: str = "", /, **fields: Any) -> bool:
        self.flights.append({"reason": reason, **fields})
        return True

    def write_document(self, kind: str, summary: str = "", /, **fields: Any) -> bool:
        self.documents.append({"kind": kind, "summary": summary, **fields})
        return True

    def write_event(
        self,
        kind: str,
        summary: str = "",
        /,
        *,
        unit: Any = None,
        decisive: bool = False,
        **fields: Any,
    ) -> bool:
        self.events.append({"kind": kind, "summary": summary, "decisive": decisive, "unit": unit, **fields})
        return True

    def log_info(self, message: str, **kwargs: Any) -> None: ...

    def log_error(self, message: str, **kwargs: Any) -> None: ...


def _plugin(config: Dict[str, Any] | None = None) -> tuple[RobotControlPlugin, _Ctx]:
    ctx = _Ctx(config)
    p = RobotControlPlugin()
    p.configure(ctx)
    return p, ctx


def _marker(reason: str = "lag", trace: str = "t1") -> dict:
    """Маркер дословно по контракту 4.7d-1 (ровно эти ключи; ни кадра, ни SHM-ключей)."""
    return {
        "inspection_status": "not_inspected",
        "overflow_marker": True,
        "reason": reason,
        "source": "processor_0",
        "trace_id": trace,
        "capture_ts": 12.5,
    }


def _defect_item(area: int = 900, trace: str = "d1") -> dict:
    return {
        "frame": np.zeros((8, 8, 3), dtype=np.uint8),
        "detections": [{"bbox": [1, 1, 5, 5], "center": [3, 3], "area": area}],
        "trace_id": trace,
    }


def _result(out: list) -> dict:
    assert len(out) == 1, f"process вернул {len(out)} item'ов вместо одного"
    return out[0].get("inspection_result", {})


def _not_inspected_count(p: RobotControlPlugin) -> Any:
    """``total_not_inspected``: спека называет счётчик, но не поверхность — читаем get_stats, затем атрибут."""
    stats = p.cmd_get_stats({})
    if "total_not_inspected" in stats:
        return stats["total_not_inspected"]
    return getattr(p, "_total_not_inspected", None)


def _bounded(fn: Callable[[], Any], timeout: float = 10.0) -> Any:
    """Вызов в daemon-потоке с дедлайном на join: зависание = падение, а не висящий прогон."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробросим в поток теста
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        pytest.fail(f"вызов не завершился за {timeout} с (зависание)")
    if "error" in box:
        raise box["error"]
    return box.get("value")


# --- Класс и регистр ---------------------------------------------------------------------------


def test_class_declares_accepts_markers() -> None:
    assert getattr(RobotControlPlugin, "accepts_markers", None) is True


def test_register_default_is_reject() -> None:
    assert getattr(RobotControlRegisters(), "not_inspected_action", None) == "reject"


def test_register_accepts_pass_and_rejects_other_values() -> None:
    # Сначала успешная ветка: без неё pytest.raises мог бы пройти на «поля нет вовсе».
    assert getattr(RobotControlRegisters(not_inspected_action="pass"), "not_inspected_action", None) == "pass"
    with pytest.raises(ValueError):  # pydantic.ValidationError — подкласс ValueError
        RobotControlRegisters(not_inspected_action="drop")


# --- Решение по маркеру --------------------------------------------------------------------------


def test_marker_is_rejected_with_reason_and_origin() -> None:
    p, _ = _plugin()

    result = _result(p.process([_marker(reason="lag", trace="t1")]))

    assert result.get("action") == "reject"
    assert result.get("reason") == "not_inspected"
    assert result.get("origin") == "lag"


def test_marker_result_carries_source_of_the_marker() -> None:
    p, _ = _plugin()

    result = _result(p.process([_marker(reason="door")]))

    assert result.get("origin") == "door"
    assert result.get("source") == "processor_0"


def test_marker_counts_total_not_inspected() -> None:
    p, _ = _plugin()

    p.process([_marker(trace="t1")])
    p.process([_marker(trace="t2")])

    assert _not_inspected_count(p) == 2


def test_marker_does_not_bump_total_inspected() -> None:
    p, _ = _plugin()

    out = p.process([_marker()])

    assert _result(out).get("action") == "reject"  # якорь: маркер распознан, а не принят за обычный item
    assert p._total_inspected == 0
    assert p.cmd_get_stats({})["total_inspected"] == 0


def test_marker_does_not_bump_total_rejected() -> None:
    p, _ = _plugin()

    out = p.process([_marker()])

    assert _result(out).get("action") == "reject"
    assert p._total_rejected == 0


def test_marker_writes_no_verdict_document() -> None:
    p, ctx = _plugin()

    out = p.process([_marker()])

    assert _result(out).get("action") == "reject"
    assert ctx.documents == []
    assert p._verdicts_written == 0


def test_marker_does_not_clear_the_rejecting_front() -> None:
    """Идёт серия брака (_rejecting=True); маркер посреди неё фронт не сбрасывает."""
    p, ctx = _plugin()
    p.process([_defect_item()])
    assert p._rejecting is True
    docs_before = len(ctx.documents)

    out = p.process([_marker()])

    assert _result(out).get("action") == "reject"
    assert p._rejecting is True
    assert len(ctx.documents) == docs_before


def test_marker_does_not_raise_the_rejecting_front() -> None:
    p, _ = _plugin()
    assert p._rejecting is False

    out = p.process([_marker()])

    assert _result(out).get("action") == "reject"
    assert p._rejecting is False


def test_marker_after_defect_does_not_add_a_second_verdict_or_rejected_count() -> None:
    p, ctx = _plugin()
    p.process([_defect_item()])
    assert (p._total_rejected, p._verdicts_written, len(ctx.documents)) == (1, 1, 1)

    out = p.process([_marker()])

    assert _result(out).get("action") == "reject"
    assert (p._total_rejected, p._verdicts_written, len(ctx.documents)) == (1, 1, 1)
    assert p._total_inspected == 1


# --- Выключенный плагин / действие pass ----------------------------------------------------------


def test_disabled_plugin_passes_marker_as_disabled_and_counts_it() -> None:
    p, _ = _plugin({"enabled": False})

    result = _result(p.process([_marker(reason="lag")]))

    assert result.get("action") == "pass"
    assert result.get("reason") == "disabled"
    assert _not_inspected_count(p) == 1


def test_action_pass_lets_marker_through_but_keeps_reason_and_origin() -> None:
    p, _ = _plugin({"not_inspected_action": "pass"})

    result = _result(p.process([_marker(reason="stale_restore")]))

    assert result.get("action") == "pass"
    assert result.get("reason") == "not_inspected"
    assert result.get("origin") == "stale_restore"
    assert _not_inspected_count(p) == 1


# --- Задержка отбраковки -------------------------------------------------------------------------


def test_reject_delay_applies_to_a_rejected_marker() -> None:
    p, _ = _plugin({"reject_delay_ms": 50})
    box: dict = {}

    def call() -> None:
        t0 = time.perf_counter()
        box["out"] = p.process([_marker()])
        box["elapsed"] = time.perf_counter() - t0

    _bounded(call)

    assert _result(box["out"]).get("action") == "reject"
    # 49 мс, а не 50: допуск 1 мс на расхождение часов time.sleep и perf_counter.
    assert box["elapsed"] >= 0.049, f"process занял {box['elapsed'] * 1000:.1f} мс при reject_delay_ms=50"


def test_no_delay_when_marker_action_is_pass() -> None:
    p, _ = _plugin({"reject_delay_ms": 400, "not_inspected_action": "pass"})
    box: dict = {}

    def call() -> None:
        t0 = time.perf_counter()
        box["out"] = p.process([_marker()])
        box["elapsed"] = time.perf_counter() - t0

    _bounded(call)

    result = _result(box["out"])
    assert (result.get("action"), result.get("reason")) == ("pass", "not_inspected")  # якорь
    assert box["elapsed"] < 0.2, f"задержка применена к pass-маркеру: {box['elapsed'] * 1000:.1f} мс"


# --- Широкая запись ------------------------------------------------------------------------------


def test_marker_writes_exactly_one_non_decisive_wide_record_with_its_trace_id() -> None:
    p, ctx = _plugin()

    p.process([_marker(trace="t1")])

    assert len(ctx.events) == 1
    record = ctx.events[0]
    assert record["kind"] == "inspection"
    assert record["decisive"] is False
    assert record["unit"]["trace_id"] == "t1"
    # якорь: запись описывает решение по маркеру, а не обычный pass-кадр
    assert record.get("action") == "reject"
    assert record.get("reason") == "not_inspected"


# --- Существующее поведение (зелёное и сегодня) --------------------------------------------------


def test_regular_item_without_detections_still_passes() -> None:
    p, _ = _plugin()

    out = p.process([{"frame": np.zeros((8, 8, 3), dtype=np.uint8), "detections": []}])

    assert _result(out)["action"] == "pass"
    assert p._total_inspected == 1


def test_regular_item_with_detection_still_rejects() -> None:
    p, _ = _plugin()

    out = p.process([_defect_item(area=900)])

    assert _result(out)["action"] == "reject"
    assert p._total_inspected == 1
    assert p._total_rejected == 1


# --- Связка с 4.7d-2 -----------------------------------------------------------------------------


class _SpyBlobDetector:
    """Звено цепочки «blob_detector»: считает вызовы process, детекций не ставит."""

    name = "blob_detector"
    enabled = True
    inputs: list = []
    outputs: list = []

    def __init__(self) -> None:
        self.calls = 0

    def process(self, items: list[dict]) -> list[dict]:
        self.calls += 1
        return items


class _CountingRobotControl(RobotControlPlugin):
    """Настоящий отбраковщик; считает только вызовы process."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def process(self, items: list[dict]) -> list[dict]:
        self.calls += 1
        return super().process(items)


def test_marker_collection_skips_blob_detector_and_reaches_robot_control() -> None:
    blob = _SpyBlobDetector()
    robot = _CountingRobotControl()
    robot.configure(_Ctx())
    sent: list[tuple[str, dict]] = []
    sent_event = threading.Event()

    def send(target: str, msg: dict) -> None:
        sent.append((target, msg))
        sent_event.set()

    ex = PipelineExecutor(
        plugins=[blob, robot],
        chain_targets=["out"],
        shm_middleware=None,
        send_fn=send,
        node_name="processor_0",
    )
    q: queue.Queue = queue.Queue()
    q.put([_marker()])
    ex.bind_queue(q)
    stop, pause = threading.Event(), threading.Event()
    worker = threading.Thread(target=ex.run, args=(stop, pause), daemon=True)
    worker.start()
    delivered = sent_event.wait(10.0)
    stop.set()
    worker.join(10.0)
    assert not worker.is_alive(), "PipelineExecutor не завершил такт за 10 с"
    assert delivered, "исполнитель ничего не отправил за 10 с"

    assert blob.calls == 0, f"blob_detector.process вызван {blob.calls} раз(а), ожидалось 0"
    assert robot.calls == 1, f"robot_control.process вызван {robot.calls} раз(а), ожидалось 1"
