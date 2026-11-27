"""C-36, брошенная очередь: независимый акцептанс ДО реализации (строки A1–A4, A6).

Процесс положил сообщения в очередь соседа, соседа перезапустили со свежими очередями, писатель снял
брошенную очередь из своего реестра (``routing.refresh``, ADR-PMM-054). Писатель обязан выйти.

Настоящие: spawn, ``run_process_function`` (штатный выход с ``release_queues_at_exit``), реестр состояний и
реестр очередей из bundle, команда ``routing.refresh``, ``QueueChannel``, ``RouterManager``.
Двойник один: ``services`` для регистрации команды ``routing.refresh``.

Очереди соседей принадлежат тест-процессу: он держит read-конец и не читает, как держат его братья писателя.
Сценарий гоняется один раз (module-фикстура), тест проверяет одно свойство. Дочерний процесс только пишет
наблюдения в файл; все ``assert`` — в тест-процессе. Каждое ожидание имеет срок; убивается только свой ребёнок.

Windows: 40 сообщений по 1024 байта не помещаются в pipe, feeder писателя встаёт. Это проверяется явно
(``feeder_stuck``): на ОС с большим pipe сценарий не воспроизведётся и фикстура упадёт, а не позеленеет.
"""

from __future__ import annotations

import json
import multiprocessing
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.router_module.channels.queue_channel import QueueChannel
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager

from .. import QueueRegistry

_PAYLOAD = b"x" * 1024
_COUNT = 40
_EXIT_DEADLINE_S = 5.0
_SCENARIO_DEADLINE_S = 40.0  # spawn + импорт фреймворка + шаги сценария
_STILL_WAITING_S = 3.0


# ---------------------------------------------------------------------------
# Дочерний процесс (top-level: spawn пиклит класс по dotted-пути)
# ---------------------------------------------------------------------------


class _RefreshServices:
    """Минимальные ``services`` для настоящего обработчика ``routing.refresh``."""

    def __init__(self, name: str, shared_resources: Any) -> None:
        self.name = name
        self.shared_resources = shared_resources
        self.command_manager = self
        self.error_manager = None
        self.handlers: dict[str, Any] = {}

    def register_command(self, name: str, handler: Any, metadata: Any = None, tags: Any = None) -> None:
        self.handlers[name] = handler

    def send_to_process(self, target: str, message: Any) -> bool:
        return True

    def _log_debug(self, *args: Any, **kwargs: Any) -> None: ...
    def _log_info(self, *args: Any, **kwargs: Any) -> None: ...
    def _log_warning(self, *args: Any, **kwargs: Any) -> None: ...
    def _log_error(self, *args: Any, **kwargs: Any) -> None: ...


class _Writer:
    """Писатель: выполняет сценарий в ``run()``, потом штатно ждёт свой ``stop_event``."""

    def __init__(self, name: str, shared_resources: Any, config: dict) -> None:
        self.name = name
        self.shared_resources = shared_resources

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        custom = self.shared_resources.get_process_data(self.name).custom
        report: dict[str, Any] = {}
        try:
            getattr(self, f"_scenario_{custom['t_scenario']}")(custom, report)
        except BaseException:  # noqa: BLE001 — переносим в тест через отчёт
            report["error"] = traceback.format_exc()
        Path(custom["t_report"]).write_text(json.dumps(report), encoding="utf-8")
        custom["t_done"].set()

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    # -- шаги ----------------------------------------------------------------

    def _registry(self) -> Any:
        return self.shared_resources.queue_registry

    def _queue(self, target: str) -> Any:
        return self.shared_resources.process_state_registry.get_queue(target, "data")

    def _stats(self) -> dict[str, int]:
        section = self._registry().get_stats()["queues"]
        return {key: value for key, value in section.items() if type(value) is int}

    def _refresh(self, incarnations: dict[str, int]) -> dict:
        services = _RefreshServices(self.name, self.shared_resources)
        BuiltinCommands(services)._register_routing_commands()
        snapshot = {name: {"incarnation": inc} for name, inc in incarnations.items()}
        data = {"epoch": 1, "hub": "ProcessManager", "reason": "test", "processes": snapshot}
        return services.handlers["routing.refresh"](data)

    def _fill_peer(self, report: dict) -> None:
        """40 × 1024 байта продовым путём в очередь 'Peer'; её никто не читает."""
        queue = self._queue("Peer")
        report["sent"] = [self._registry().send_to_queue("Peer", "data", _PAYLOAD) for _ in range(_COUNT)]
        time.sleep(0.5)
        report["feeder_stuck"] = len(queue._buffer) > 0  # предусловие: pipe полон, feeder не дописал

    # -- сценарии ------------------------------------------------------------

    def _scenario_drop_written(self, custom: dict, report: dict) -> None:
        self._fill_peer(report)
        custom["t_written"].set()
        assert custom["t_go"].wait(30.0), "тест не дал команду на сброс очереди"
        report["reader_gone_before_drop"] = self._queue("Peer").is_reader_gone()
        report["refresh"] = self._refresh({"Peer": 1})
        report["peer_queue_after_drop_is_none"] = self._queue("Peer") is None
        # Срок на случай отложенного учёта; ключа нет — ждём весь срок и отдаём что есть.
        deadline = time.monotonic() + 2.0
        while self._stats().get("queues_retired", 0) < 1 and time.monotonic() < deadline:
            time.sleep(0.05)
        report["stats"] = self._stats()

    def _scenario_drop_unwritten(self, custom: dict, report: dict) -> None:
        report["refresh"] = self._refresh({"Peer": 1})
        report["peer_queue_after_drop_is_none"] = self._queue("Peer") is None
        time.sleep(0.2)
        report["stats"] = self._stats()

    def _scenario_put_after_drop(self, custom: dict, report: dict) -> None:
        # Ссылка, которую держит вызывающий: так живут каналы ``{target}_{qtype}`` (ADR-PMM-054, kind-каналы).
        held = self._queue("Peer")
        router = RouterManager("c36_put_after_drop")
        assert router.register_channel(QueueChannel("Peer_data", held))

        def message() -> dict:
            return {"channel": "Peer_data", "type": "data", "data": {"i": 1}, "sender": self.name}

        report["by_name_before"] = self._registry().send_to_queue("Peer", "data", message())
        report["router_before"] = router.send(message()).get("status")
        report["refresh"] = self._refresh({"Peer": 1})

        errors_0 = router.get_stats()["router"]["errors"]
        report["router_after"] = router.send(message()).get("status")
        report["router_errors_delta"] = router.get_stats()["router"]["errors"] - errors_0

        try:
            held.put_nowait(message())
            report["held_put"] = "accepted"
        except Exception as exc:  # noqa: BLE001 — любой отказ годится, молчаливый успех нет
            report["held_put"] = f"refused: {type(exc).__name__}"

        before = self._stats()
        report["by_name_after"] = self._registry().send_to_queue("Peer", "data", message())
        after = self._stats()
        report["by_name_errors_delta"] = sum(
            after.get(key, 0) - before.get(key, 0) for key in ("errors", "queue_missing")
        )

    def _scenario_keep(self, custom: dict, report: dict) -> None:
        """'Peer' остаётся в реестре; сбрасывается только сосед 'Other'."""
        self._fill_peer(report)
        report["sent_other"] = self._registry().send_to_queue("Other", "data", _PAYLOAD)
        report["refresh"] = self._refresh({"Peer": 0, "Other": 1})
        report["peer_queue_still_registered"] = self._queue("Peer") is not None


# ---------------------------------------------------------------------------
# Обвязка тест-процесса
# ---------------------------------------------------------------------------


class _Child:
    """Spawn-писатель с очередями соседей, которые никто не читает."""

    def __init__(self, tmp: Path, scenario: str, peers: tuple[str, ...] = ("Peer",)) -> None:
        ctx = multiprocessing.get_context("spawn")
        self.queues = {name: QueueRegistry().create_queues({"data": {}})["data"] for name in peers}
        self.stop, self.written, self.go, self.done = (ctx.Event() for _ in range(4))
        self._report = tmp / "report.json"
        bundle = {
            "queues": {},
            "config": {},
            "custom": {
                "t_scenario": scenario,
                "t_report": str(self._report),
                "t_written": self.written,
                "t_go": self.go,
                "t_done": self.done,
            },
            "routing_map": {name: {"data": q} for name, q in self.queues.items()},
        }
        class_path = f"{_Writer.__module__}.{_Writer.__qualname__}"
        self.proc = ctx.Process(
            target=run_process_function, args=(class_path, "Writer", self.stop, bundle, None), daemon=True
        )
        self.proc.start()

    def report(self) -> dict:
        assert self.done.wait(_SCENARIO_DEADLINE_S), (
            f"сценарий писателя не закончился за {_SCENARIO_DEADLINE_S} с, exitcode={self.proc.exitcode}"
        )
        report = json.loads(self._report.read_text(encoding="utf-8"))
        assert "error" not in report, report["error"]
        return report

    def stop_and_join(self, timeout_s: float = _EXIT_DEADLINE_S) -> int | None:
        """Штатный стоп писателя; ``None`` — за срок не вышел."""
        self.stop.set()
        self.proc.join(timeout_s)
        return self.proc.exitcode

    def close(self) -> None:
        if self.proc.is_alive():
            self.proc.terminate()
            self.proc.join(5.0)
        if self.proc.is_alive():
            self.proc.kill()
            self.proc.join(5.0)
        for q in self.queues.values():
            q.cancel_join_thread()
            q.close()


def _drain(queue: Any, count: int, deadline_s: float = 15.0) -> list[Any]:
    """Прочитать ``count`` сообщений в daemon-потоке; повисший ``get`` — красный тест, а не повисший прогон."""
    got: list[Any] = []

    def _run() -> None:
        for _ in range(count):
            got.append(queue.get(timeout=10.0))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(deadline_s)
    return got


def _check_filled(report: dict) -> None:
    assert report["sent"] == [True] * 40, "предусловие: все 40 сообщений приняты в очередь"
    assert report["feeder_stuck"] is True, "предусловие: feeder писателя встал на полном pipe"


# ---------------------------------------------------------------------------
# A1 + A2: сброшенная очередь, в которую писали
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=[False, True], ids=["unmarked", "marked_reader_gone"])
def dropped_written(request, tmp_path_factory):
    child = _Child(tmp_path_factory.mktemp("drop_written"), "drop_written")
    try:
        assert child.written.wait(_SCENARIO_DEADLINE_S), f"писатель не записал, exitcode={child.proc.exitcode}"
        if request.param:
            child.queues["Peer"].mark_reader_gone()  # как PM на брошенной очереди, ДО сброса у писателя
        child.go.set()
        report = child.report()
        _check_filled(report)
        assert report["reader_gone_before_drop"] is request.param
        assert report["refresh"]["success"] is True
        assert report["refresh"]["reset"] == ["Peer"]
        assert report["peer_queue_after_drop_is_none"] is True
        yield {"stats": report["stats"], "exitcode": child.stop_and_join()}
    finally:
        child.close()


def test_a1_writer_exits_after_its_written_queue_was_dropped(dropped_written) -> None:
    assert dropped_written["exitcode"] == 0, "писатель не вышел за 5 с (None = всё ещё ждёт feeder)"


def test_a2_one_dropped_written_queue_is_counted_as_retired(dropped_written) -> None:
    assert dropped_written["stats"].get("queues_retired") == 1


def test_a2_stats_expose_buffered_dropped_at_retire(dropped_written) -> None:
    value = dropped_written["stats"].get("buffered_dropped_at_retire")
    assert type(value) is int and value >= 0, f"buffered_dropped_at_retire={value!r}"


# ---------------------------------------------------------------------------
# A3: put после сброса
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def after_drop(tmp_path_factory):
    child = _Child(tmp_path_factory.mktemp("put_after_drop"), "put_after_drop")
    try:
        report = child.report()
        assert report["by_name_before"] is True
        assert report["router_before"] == "success", "предусловие: до сброса канал доставляет"
        assert report["refresh"]["reset"] == ["Peer"]
        yield report
    finally:
        child.close()


def test_a3_channel_holding_dropped_queue_reports_failure(after_drop) -> None:
    assert after_drop["router_after"] == "error"


def test_a3_channel_holding_dropped_queue_grows_error_counter_by_one(after_drop) -> None:
    assert after_drop["router_errors_delta"] == 1


def test_a3_put_through_held_reference_does_not_silently_succeed(after_drop) -> None:
    assert after_drop["held_put"].startswith("refused"), f"put после сброса: {after_drop['held_put']}"


def test_a3_delivery_by_name_after_drop_reports_failure_and_counts_one(after_drop) -> None:
    """Контроль (зелёный и до реализации): имя больше не резолвится в очередь."""
    assert after_drop["by_name_after"] is False
    assert after_drop["by_name_errors_delta"] == 1


# ---------------------------------------------------------------------------
# A4: сброшенная очередь, в которую не писали
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dropped_unwritten(tmp_path_factory):
    child = _Child(tmp_path_factory.mktemp("drop_unwritten"), "drop_unwritten")
    try:
        report = child.report()
        assert report["refresh"]["reset"] == ["Peer"]
        assert report["peer_queue_after_drop_is_none"] is True
        yield {"stats": report["stats"], "exitcode": child.stop_and_join()}
    finally:
        child.close()


def test_a4_writer_exits_after_never_written_queue_was_dropped(dropped_unwritten) -> None:
    assert dropped_unwritten["exitcode"] == 0


def test_a4_never_written_queue_drops_nothing(dropped_unwritten) -> None:
    assert dropped_unwritten["stats"].get("buffered_dropped_at_retire") == 0


# ---------------------------------------------------------------------------
# A6: контроль — НЕ сброшенная очередь ведёт себя на выходе как раньше
# ---------------------------------------------------------------------------


def test_a6_kept_queue_writer_waits_for_slow_reader_and_loses_nothing(tmp_path) -> None:
    child = _Child(tmp_path, "keep", peers=("Peer", "Other"))
    try:
        report = child.report()
        _check_filled(report)
        assert report["refresh"]["reset"] == ["Other"]
        assert report["peer_queue_still_registered"] is True

        assert child.stop_and_join(_STILL_WAITING_S) is None, "писатель вышел, не дописав живую очередь"
        got = _drain(child.queues["Peer"], 40)
        assert got == [b"x" * 1024] * 40, f"получено {len(got)}/40"
        child.proc.join(_EXIT_DEADLINE_S)
        assert child.proc.exitcode == 0
    finally:
        child.close()


def test_a6_kept_queue_marked_reader_gone_writer_exits(tmp_path) -> None:
    child = _Child(tmp_path, "keep", peers=("Peer", "Other"))
    try:
        report = child.report()
        _check_filled(report)
        assert report["refresh"]["reset"] == ["Other"]
        assert report["peer_queue_still_registered"] is True

        child.queues["Peer"].mark_reader_gone()
        assert child.stop_and_join() == 0
    finally:
        child.close()
