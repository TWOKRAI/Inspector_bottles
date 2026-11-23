"""Слепые приёмочные тесты R2d2-C104: отказ задания роботу виден (robot_io).

Контракт (из брифа, не из реализации):
- отказ хаба (``status != ok``) и исключение запроса вызывают
  ``ctx.health.report_error(exc, context=..., throttle=0.0, job=<подпись>)``
  на КАЖДЫЙ отказ; ``ctx.log_error`` НЕ вызывается (один разъём на точку);
- подпись задания укладки: ``буква 'М', ячейка 0`` (из ``char``, ``slot``);
  у задания возврата и без подписи — имя команды;
- регистры (readonly): ``last_dropped_job`` (``"<подпись>: <причина>"``,
  при успехе НЕ очищается) и ``forward_ok`` (False на отказе, True на успехе);
- те же поля и ``jobs_dropped`` уходят в ``ctx.state_proxy.merge`` по пути
  ``processes.<process_name>.state.robot_io``; сбой/отсутствие state_proxy
  форвардер не останавливает;
- служебный ключ ``_label`` не уходит в хаб.

Форвардер гоняем реальным ``plugin._forwarder_loop`` в daemon-потоке с
join-дедлайном (тест не может зависнуть). Все ожидаемые значения — литералы.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from multiprocess_framework.modules.error_module.interfaces import ResourceUnavailable
from Plugins.io.robot_io.plugin import RobotIoPlugin

STATE_PATH = "processes.layout.state.robot_io"
SERVO_OFF = {"status": "error", "message": "робот остановлен: включите серво"}


# ------------------------------------------------------------------ #
# Фейковые клиенты (оба пишут calls — по ним форвардер ждём)
# ------------------------------------------------------------------ #


class ScriptedClient:
    """request() отдаёт ответы по очереди; кончились — ``{"status": "ok"}``."""

    def __init__(self, responses: list[dict] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[tuple[str, dict]] = []

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        self.calls.append((command, dict(args or {})))
        if self._responses:
            return self._responses.pop(0)
        return {"status": "ok"}


class RaisingClient:
    """request() бросает заданное исключение на каждом вызове."""

    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.calls: list[tuple[str, dict]] = []

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        self.calls.append((command, dict(args or {})))
        raise self._error


# ------------------------------------------------------------------ #
# Сборка и прогон
# ------------------------------------------------------------------ #


def build(client, *, state_proxy="mock") -> tuple[RobotIoPlugin, MagicMock]:
    """Плагин с фейковым клиентом; process_name и state_proxy ставим ДО configure."""
    plugin = RobotIoPlugin()
    ctx = MagicMock()
    ctx.config = {"device_id": "robot_main", "forward_deque_maxlen": 64}
    ctx.registers = None
    ctx.process_name = "layout"
    ctx.state_proxy = MagicMock() if state_proxy == "mock" else state_proxy
    ctx.worker_manager.create_worker = MagicMock()
    plugin.configure(ctx)
    with patch("Plugins.io.robot_io.plugin.DeviceHubClient", return_value=client):
        plugin.start(ctx)
    plugin._client = client
    return plugin, ctx


def layout_job(char: str, slot: int) -> dict:
    """Исходное задание укладки word_layout (как в item["robot_job"])."""
    return {
        "pick_x_mm": 100.0,
        "pick_y_mm": -50.0,
        "place_x_mm": 300.0,
        "place_y_mm": 200.0,
        "char": char,
        "slot": slot,
    }


def run_forwarder(plugin: RobotIoPlugin, client, expected_calls: int) -> None:
    """Гонять форвардер, пока клиент не получил expected_calls запросов; затем остановить."""
    stop = threading.Event()
    pause = threading.Event()
    worker = threading.Thread(target=plugin._forwarder_loop, args=(stop, pause), daemon=True)
    worker.start()
    for _ in range(300):
        if len(client.calls) >= expected_calls and not plugin._deque:
            break
        threading.Event().wait(0.01)
    stop.set()
    worker.join(timeout=2.0)
    assert not worker.is_alive(), "форвардер завис или упал не завершившись"
    assert len(client.calls) == expected_calls


def report_calls(ctx: MagicMock) -> list:
    return ctx.health.report_error.call_args_list


def exc_of(call) -> BaseException:
    return call.args[0] if call.args else call.kwargs["exc"]


def context_of(call):
    if "context" in call.kwargs:
        return call.kwargs["context"]
    return call.args[1] if len(call.args) > 1 else None


def state_dicts(ctx: MagicMock) -> list[dict]:
    """Словари всех merge по пути STATE_PATH, в порядке вызовов."""
    out = []
    for c in ctx.state_proxy.merge.call_args_list:
        path = c.args[0] if c.args else c.kwargs.get("path")
        if path == STATE_PATH:
            out.append(c.args[1] if len(c.args) > 1 else c.kwargs["data"])
    return out


# ------------------------------------------------------------------ #
# RED: приёмка
# ------------------------------------------------------------------ #


def test_refused_job_reports_label_and_reason_and_not_log_error() -> None:
    """Отказ хаба: report_error с ResourceUnavailable, подписью и причиной; log_error молчит."""
    client = ScriptedClient([SERVO_OFF])
    plugin, ctx = build(client)
    plugin.process([{"robot_job": layout_job("М", 0)}])

    run_forwarder(plugin, client, 1)

    calls = report_calls(ctx)
    assert len(calls) == 1
    exc = exc_of(calls[0])
    assert isinstance(exc, ResourceUnavailable)
    assert str(exc) == "hub отказ (буква 'М', ячейка 0): робот остановлен: включите серво"
    assert context_of(calls[0]) == "robot_io.forward.refused"
    assert calls[0].kwargs["throttle"] == 0.0
    assert calls[0].kwargs["job"] == "буква 'М', ячейка 0"
    ctx.log_error.assert_not_called()


def test_refused_job_sets_visible_status_and_state() -> None:
    """Отказ: регистры last_dropped_job/forward_ok и state_proxy.merge по пути процесса."""
    client = ScriptedClient([SERVO_OFF])
    plugin, ctx = build(client)
    plugin.process([{"robot_job": layout_job("М", 0)}])

    run_forwarder(plugin, client, 1)

    assert plugin._reg.last_dropped_job == "буква 'М', ячейка 0: робот остановлен: включите серво"
    assert plugin._reg.forward_ok is False
    states = state_dicts(ctx)
    assert states, f"нет merge по пути {STATE_PATH}: {ctx.state_proxy.merge.call_args_list}"
    assert states[-1]["jobs_dropped"] == 1
    assert states[-1]["forward_ok"] is False


def test_exception_branch_reports_label_every_time() -> None:
    """Исключение клиента: report_error с тем же исключением, подписью, throttle=0.0; регистры."""
    boom = RuntimeError("таймаут IPC")
    client = RaisingClient(boom)
    plugin, ctx = build(client)
    plugin.process([{"robot_job": layout_job("М", 0)}])

    run_forwarder(plugin, client, 1)

    calls = report_calls(ctx)
    assert len(calls) == 1
    assert exc_of(calls[0]) is boom
    assert isinstance(context_of(calls[0]), str) and context_of(calls[0])
    assert calls[0].kwargs["throttle"] == 0.0
    assert calls[0].kwargs["job"] == "буква 'М', ячейка 0"
    assert plugin._reg.forward_ok is False
    assert plugin._reg.last_dropped_job == "буква 'М', ячейка 0: таймаут IPC"
    ctx.log_error.assert_not_called()
    assert state_dicts(ctx)[-1]["forward_ok"] is False


def test_two_refusals_in_a_row_two_reports_and_last_dropped_updated() -> None:
    """Два отказа подряд -> два report_error (не раз на переход); last_dropped_job — от второго."""
    client = ScriptedClient(
        [
            SERVO_OFF,
            {"status": "error", "message": "очередь робота полна"},
        ]
    )
    plugin, ctx = build(client)
    plugin.process([{"robot_job": layout_job("М", 0)}])
    plugin.process([{"robot_job": layout_job("А", 1)}])

    run_forwarder(plugin, client, 2)

    calls = report_calls(ctx)
    assert len(calls) == 2
    assert [c.kwargs["job"] for c in calls] == ["буква 'М', ячейка 0", "буква 'А', ячейка 1"]
    assert [c.kwargs["throttle"] for c in calls] == [0.0, 0.0]
    assert plugin._reg.last_dropped_job == "буква 'А', ячейка 1: очередь робота полна"
    assert plugin._reg.jobs_dropped == 2


def test_return_job_label_is_command_name() -> None:
    """Задание возврата (без слота укладки): подпись — имя команды robot_return_job."""
    client = ScriptedClient([SERVO_OFF])
    plugin, ctx = build(client)
    plugin.process([{"robot_return_jobs": [{"x_mm": 5.0, "y_mm": 1.0, "z_mm": -90.0, "char": "К"}]}])

    run_forwarder(plugin, client, 1)

    assert client.calls[0][0] == "robot_return_job"
    calls = report_calls(ctx)
    assert len(calls) == 1
    assert calls[0].kwargs["job"] == "robot_return_job"
    assert str(exc_of(calls[0])) == "hub отказ (robot_return_job): робот остановлен: включите серво"
    assert plugin._reg.last_dropped_job == "robot_return_job: робот остановлен: включите серво"


def test_legacy_job_without_label_uses_command_name() -> None:
    """Legacy-задание только {x_mm, y_mm}: подпись — имя команды robot_enqueue_job."""
    client = ScriptedClient([SERVO_OFF])
    plugin, ctx = build(client)
    plugin.process([{"robot_job": {"x_mm": 10.0, "y_mm": -5.0}}])

    run_forwarder(plugin, client, 1)

    assert client.calls[0][0] == "robot_enqueue_job"
    calls = report_calls(ctx)
    assert len(calls) == 1
    assert calls[0].kwargs["job"] == "robot_enqueue_job"
    assert plugin._reg.last_dropped_job == "robot_enqueue_job: робот остановлен: включите серво"


def test_success_after_refusal_restores_forward_ok_keeps_last_dropped() -> None:
    """Успех после отказа: forward_ok True, last_dropped_job сохраняется; в state forward_ok True."""
    client = ScriptedClient([SERVO_OFF, {"status": "ok"}])
    plugin, ctx = build(client)
    plugin.process([{"robot_job": layout_job("М", 0)}])
    plugin.process([{"robot_job": layout_job("А", 1)}])

    run_forwarder(plugin, client, 2)

    assert plugin._reg.forward_ok is True
    assert plugin._reg.last_dropped_job == "буква 'М', ячейка 0: робот остановлен: включите серво"
    assert plugin._reg.jobs_forwarded == 1
    states = state_dicts(ctx)
    assert states[-1]["forward_ok"] is True
    assert states[-1]["jobs_dropped"] == 1
    assert len(report_calls(ctx)) == 1  # успех не порождает report_error


def test_state_proxy_none_does_not_stop_forwarder() -> None:
    """state_proxy = None: отказ виден через report_error, форвардер идёт к следующему заданию."""
    client = ScriptedClient([SERVO_OFF, {"status": "ok"}])
    plugin, ctx = build(client, state_proxy=None)
    plugin.process([{"robot_job": layout_job("М", 0)}])
    plugin.process([{"robot_job": layout_job("А", 1)}])

    run_forwarder(plugin, client, 2)

    assert len(report_calls(ctx)) == 1
    assert report_calls(ctx)[0].kwargs["job"] == "буква 'М', ячейка 0"
    assert plugin._reg.jobs_forwarded == 1
    assert plugin._reg.forward_ok is True


def test_state_merge_raising_does_not_stop_forwarder() -> None:
    """state_proxy.merge бросает: отказ всё равно отчитан, следующее задание форвардится."""
    client = ScriptedClient([SERVO_OFF, {"status": "ok"}])
    plugin, ctx = build(client)
    ctx.state_proxy.merge.side_effect = RuntimeError("state недоступен")
    plugin.process([{"robot_job": layout_job("М", 0)}])
    plugin.process([{"robot_job": layout_job("А", 1)}])

    run_forwarder(plugin, client, 2)

    assert len(report_calls(ctx)) == 1
    assert report_calls(ctx)[0].kwargs["job"] == "буква 'М', ячейка 0"
    assert plugin._reg.jobs_forwarded == 1
    assert plugin._reg.last_dropped_job == "буква 'М', ячейка 0: робот остановлен: включите серво"


def test_label_never_reaches_hub_and_job_forwarded_with_label() -> None:
    """Подпись считается (отказ отчитан с job), но служебный _label не уходит в args хаба.

    Два задания: первое отказано, второе принято — _label нет ни у одного.
    """
    client = ScriptedClient([SERVO_OFF, {"status": "ok"}])
    plugin, ctx = build(client)
    plugin.process([{"robot_job": layout_job("М", 0)}])
    plugin.process([{"robot_job": layout_job("А", 1)}])

    run_forwarder(plugin, client, 2)

    # подпись существует и доходит до отчёта (иначе проверка «не утекла» тривиальна)
    assert [c.kwargs["job"] for c in report_calls(ctx)] == ["буква 'М', ячейка 0"]
    for command, args in client.calls:
        assert command == "robot_enqueue_job"
        assert "_label" not in args
        assert "_command" not in args
        assert args["x_mm"] == 100.0  # задание дошло до хаба с полезной нагрузкой
        assert args["y_mm"] == -50.0
    assert plugin._reg.jobs_forwarded == 1
