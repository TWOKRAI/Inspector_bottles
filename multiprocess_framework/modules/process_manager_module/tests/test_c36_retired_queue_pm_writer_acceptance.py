"""C-36, брошенная очередь на стороне PM: независимый акцептанс ДО реализации (строка A5).

PM сам положил сообщения в очередь ребёнка, затем перезапустил его со свежими очередями (умолчание
``restart_reuse_queues: false``). Выход процесса PM не должен ждать feeder брошенной очереди.

Роль PM играет отдельный spawn-процесс под ``run_process_function`` (штатный выход PM на системном стопе, с
``release_queues_at_exit``). Внутри него настоящие ``ProcessManagerProcess.restart_process``,
``SharedResourcesManager``, ``ReaderGoneQueue``; двойники те же, что в ``test_c36_restart_queues_acceptance.py``
(реестр OS-процессов из ``make_pm``, ``communication``, логи).

Старые очереди ``cam`` созданы тест-процессом: он держит read-конец и не читает — так держат его выжившие
соседи убитого ребёнка. Дочерний процесс только пишет наблюдения в файл; все ``assert`` — здесь.
"""

from __future__ import annotations

import json
import multiprocessing
import time
import traceback
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function
from multiprocess_framework.modules.shared_resources_module import QueueRegistry

from .conftest import make_pm

_PAYLOAD = b"x" * 1024
_EXIT_DEADLINE_S = 5.0
_SCENARIO_DEADLINE_S = 60.0  # spawn + импорт PM + restart_process

_CAM_CONFIG = {
    "class": "os.getpid",
    "priority": "normal",
    "queues": {"system": {"maxsize": 100}, "data": {"maxsize": 100}},
}


class _PmWriter:
    """Играет PM: пишет в очередь ``cam``, перезапускает ``cam``, ждёт системный стоп и выходит."""

    def __init__(self, name: str, shared_resources: Any, config: dict) -> None:
        self.name = name
        self.shared_resources = shared_resources

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        custom = self.shared_resources.get_process_data(self.name).custom
        report: dict[str, Any] = {}
        try:
            self._restart_after_writes(custom["t_qtype"], custom["t_count"], report)
        except BaseException:  # noqa: BLE001 — переносим в тест через отчёт
            report["error"] = traceback.format_exc()
        Path(custom["t_report"]).write_text(json.dumps(report), encoding="utf-8")
        custom["t_done"].set()

    def _restart_after_writes(self, qtype: str, count: int, report: dict) -> None:
        srm = self.shared_resources
        pm = make_pm({"cam": _CAM_CONFIG}, shared_resources=srm)
        pm.communication = MagicMock()
        pm._process_monitor.get_supervision_snapshot.return_value = {}

        old = srm.queue_registry.get_queue("cam", qtype)
        report["sent"] = [srm.queue_registry.send_to_queue("cam", qtype, _PAYLOAD) for _ in range(count)]
        time.sleep(0.5)
        report["feeder_stuck"] = count > 0 and len(old._buffer) > 0
        report["restart_ok"] = pm.restart_process("cam")
        report["old_marked_reader_gone"] = old.is_reader_gone()
        report["queue_replaced"] = srm.queue_registry.get_queue("cam", qtype) is not old

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _run_pm_writer(tmp: Path, qtype: str, count: int) -> tuple[dict, int | None]:
    """Отчёт PM-писателя и его ``exitcode`` через 5 с после системного стопа (``None`` — не вышел)."""
    ctx = multiprocessing.get_context("spawn")
    old_queues = QueueRegistry().create_queues({"system": {"maxsize": 100}, "data": {"maxsize": 100}})
    system_stop, done = ctx.Event(), ctx.Event()
    report_path = tmp / "report.json"
    bundle = {
        "queues": {},
        "config": {},
        "custom": {"t_qtype": qtype, "t_count": count, "t_report": str(report_path), "t_done": done},
        "routing_map": {"cam": old_queues},
    }
    class_path = f"{_PmWriter.__module__}.{_PmWriter.__qualname__}"
    proc = ctx.Process(
        target=run_process_function, args=(class_path, "ProcessManager", None, bundle, system_stop), daemon=True
    )
    proc.start()
    try:
        assert done.wait(_SCENARIO_DEADLINE_S), f"PM-писатель не закончил сценарий, exitcode={proc.exitcode}"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert "error" not in report, report["error"]
        assert report["restart_ok"] is True
        assert report["queue_replaced"] is True, "предусловие: рестарт дал свежую очередь"
        assert report["old_marked_reader_gone"] is True, "предусловие: брошенная очередь помечена (ADR-PMM-054)"
        system_stop.set()
        proc.join(_EXIT_DEADLINE_S)
        return report, proc.exitcode
    finally:
        if proc.is_alive():
            proc.terminate()
            proc.join(5.0)
        if proc.is_alive():
            proc.kill()
            proc.join(5.0)
        for q in old_queues.values():
            q.cancel_join_thread()
            q.close()


@pytest.mark.parametrize("qtype", ["system", "data"])
def test_a5_pm_exit_does_not_wait_for_feeder_of_abandoned_queue(tmp_path, qtype: str) -> None:
    report, exitcode = _run_pm_writer(tmp_path, qtype, 40)

    assert report["sent"] == [True] * 40
    assert report["feeder_stuck"] is True, "предусловие: feeder PM встал на полном pipe"
    assert exitcode == 0, "PM-писатель не вышел за 5 с (None = всё ещё ждёт feeder брошенной очереди)"


def test_a5_control_pm_that_wrote_nothing_exits_after_restart(tmp_path) -> None:
    """Контроль обвязки (зелёный и до реализации): без записей та же роль PM выходит."""
    report, exitcode = _run_pm_writer(tmp_path, "data", 0)

    assert report["sent"] == []
    assert exitcode == 0
