# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 1.9a: развилка ``CommandManager`` и роутер (REDS R7-R10, R13).

Написаны независимым тестером ТОЛЬКО по публичному контракту (D1/D3/D4 и раздел REDS
``plans/lifecycle-stop-ownership/tasks/T1.9a.md``); устройство исполнителя и развилки
тестеру не показывалось.

Ожидание до реализации: R7, R8, R9, R13 красные (нет ``KeyedExecutor`` / ``DEFERRED`` /
kwarg ``executor``); R10 — страж: первая точка (команда без исполнителя на потоке
``receive()``) зелёная и до, и после; вторая точка красная до реализации ТОЛЬКО по
``TypeError`` на незнакомый kwarg ``reply``, тест целиком красный по той же причине.

Новые имена импортируются внутри помощников, а не на уровне модуля: каждый тест
докладывает свой красный, а не один ошибкой сбора на весь файл.

R7 и R10 (точка 1) строят НАСТОЯЩИЕ ``RouterManager`` + ``CommandManager``; ``process`` у
роутера — минимальная оболочка с ``name`` и ``command_manager``. Каждый ждущий вызов — в
daemon-потоке с дедлайном ``join``. WARNING менеджеров ловятся через слот ``logger``
конструктора ``CommandManager`` (публичный шов; ``CommandManager`` не пишет в stdlib logging).
"""

from __future__ import annotations

import threading
import time
from queue import Queue
from typing import Any, Callable

import pytest

from multiprocess_framework.modules.command_module.core.command_manager import CommandManager
from multiprocess_framework.modules.router_module.channels.queue_channel import QueueChannel
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.worker_module import WorkerManager

# ---------------------------------------------------------------------------
# Стенд
# ---------------------------------------------------------------------------


def run_bounded(fn: Callable[[], Any], timeout: float = 5.0) -> tuple[Any, int]:
    """Выполнить ``fn`` в daemon-потоке; вернуть ``(результат, ident потока)``; не уложилась — провал."""
    box: dict[str, Any] = {}

    def target() -> None:
        box["ident"] = threading.get_ident()
        try:
            box["ret"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в потоке теста
            box["exc"] = exc

    t = threading.Thread(target=target, name="recv-probe", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        pytest.fail(f"вызов не вернулся за {timeout} с (зависание)")
    if "exc" in box:
        raise box["exc"]
    return box.get("ret"), box["ident"]


class LogRec:
    """Слот ``logger`` менеджера: запоминает записи по уровням."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: list[tuple[str, str]] = []

    def _add(self, level: str, message: Any) -> None:
        with self._lock:
            self.records.append((level, str(message() if callable(message) else message)))

    def debug(self, message: Any, **kw: Any) -> None:
        self._add("debug", message)

    def info(self, message: Any, **kw: Any) -> None:
        self._add("info", message)

    def warning(self, message: Any, **kw: Any) -> None:
        self._add("warning", message)

    def error(self, message: Any, **kw: Any) -> None:
        self._add("error", message)

    def warnings(self) -> list[str]:
        with self._lock:
            return [m for lvl, m in self.records if lvl == "warning"]


def make_cm(name: str = "seg") -> tuple[CommandManager, LogRec]:
    log = LogRec()
    cm = CommandManager(manager_name=name, managers={"logger": log})
    cm.initialize()
    return cm, log


def registered_names(cm: CommandManager) -> list[str]:
    return [c.get("key") for c in cm.get_commands()]


class StubExecutor:
    """Минимальный исполнитель: нужен только как объект для проверок регистрации (ничего не исполняет)."""

    def submit(self, action, key, reply, *, inline_if_idle: bool = False) -> bool:
        reply(action())
        return False

    def request_stop(self) -> None:
        return None

    def join_until(self, deadline: float) -> bool:
        return True

    def shutdown(self, deadline: float) -> bool:
        return True


def deferred_sentinel() -> Any:
    """Настоящий ``DEFERRED`` или (до реализации) уникальный объект — чтобы красный был по сути проверки."""
    try:
        from multiprocess_framework.modules.command_module import DEFERRED

        return DEFERRED
    except ImportError:
        return object()


@pytest.fixture
def make_executor():
    """Фабрика настоящих ``KeyedExecutor`` с ``WorkerManager`` и уборкой."""
    created: list[tuple[Any, WorkerManager]] = []

    def factory(name: str = "t", **kwargs: Any) -> Any:
        from multiprocess_framework.modules.worker_module.keyed_executor import KeyedExecutor

        wm = WorkerManager(f"wm-{name}-{len(created)}")
        wm.initialize()
        ex = KeyedExecutor(name, worker_manager=wm, **kwargs)
        created.append((ex, wm))
        return ex

    yield factory

    for ex, wm in created:
        try:
            ex.request_stop()
            ex.join_until(time.monotonic() + 2.0)
        except Exception:  # noqa: BLE001 — уборка не маскирует провал теста
            pass
        try:
            wm.shutdown()
        except Exception:  # noqa: BLE001
            pass


class SendRegistry:
    """``queue_registry``-двойник роутера: копит всё, что роутер отправил (граница транспорта)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.sent: list[tuple[str, str, dict]] = []

    def send_to_queue(self, target, qtype, msg, timeout: float = 0.0, on_evict=None) -> bool:
        with self._lock:
            self.sent.append((target, qtype, dict(msg)))
        return True

    def get_queue(self, process, qtype):
        return None

    def by_request(self, request_id: str) -> list[dict]:
        with self._lock:
            return [m for (_t, _q, m) in self.sent if m.get("request_id") == request_id]


class _Proc:
    def __init__(self, name: str, cm: CommandManager) -> None:
        self.name = name
        self.command_manager = cm


class Wired:
    """Настоящие ``RouterManager`` + ``CommandManager``; входящее билет кладётся в system-очередь."""

    def __init__(self, cm: CommandManager) -> None:
        self.cm = cm
        self.q: Queue = Queue()
        self.reg = SendRegistry()
        self.router = RouterManager(manager_name="seg", process=_Proc("seg", cm), queue_registry=self.reg)
        self.router.register_channel(QueueChannel("seg_system", self.q))
        self.router.initialize()

    def deliver(self, command: str, request_id: str, data: dict) -> int:
        """Положить билет и разобрать его одним ``receive()`` на отдельном потоке; вернуть ident этого потока."""
        self.q.put({"type": "command", "command": command, "sender": "gui", "request_id": request_id, "data": data})
        _, ident = run_bounded(lambda: self.router.receive(timeout=0.0, channel_types=["system"]), timeout=5.0)
        return ident

    def wait_replies(self, request_id: str, timeout: float = 3.0) -> list[dict]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            got = self.reg.by_request(request_id)
            if got:
                return got
            time.sleep(0.01)
        return self.reg.by_request(request_id)

    def close(self) -> None:
        threading.Thread(target=lambda: self._safe_shutdown(), daemon=True).start()

    def _safe_shutdown(self) -> None:
        try:
            self.router.shutdown()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def wired():
    made: list[Wired] = []

    def factory(cm: CommandManager) -> Wired:
        w = Wired(cm)
        made.append(w)
        return w

    yield factory
    for w in made:
        w.close()


def echo_handler(data: dict) -> dict:
    """Общий обработчик R7: режим выбирает результат (успех / отказ прикладного уровня)."""
    if data.get("mode") == "bad":
        return {"success": False, "reason": "nope"}
    return {"success": True, "v": 7}


# ---------------------------------------------------------------------------
# R7: отложенная команда через настоящие RouterManager + CommandManager
# ---------------------------------------------------------------------------


def test_deferred_command_gets_one_reply_same_envelope(make_executor, wired):
    """R7: команда с исполнителем — ровно один ответ; конверт и success те же, что у той же команды без исполнителя."""
    ex = make_executor("r7")
    cm, _log = make_cm("seg")
    assert cm.register_command("echo.plain", echo_handler) is True
    assert cm.register_command("echo.exec", echo_handler, executor=ex, key_from="process_name") is True
    w = wired(cm)

    verdicts: list[str] = []
    for mode, expected_success in (("ok", True), ("bad", False)):
        plain_id, exec_id = f"plain-{mode}", f"exec-{mode}"
        w.deliver("echo.plain", plain_id, {"process_name": "p1", "mode": mode})
        w.deliver("echo.exec", exec_id, {"process_name": "p1", "mode": mode})

        plain = w.wait_replies(plain_id)
        got = w.wait_replies(exec_id)
        time.sleep(0.3)  # лишний второй ответ должен успеть проявиться
        got = w.reg.by_request(exec_id)
        plain = w.reg.by_request(plain_id)

        if len(plain) != 1:
            verdicts.append(f"{mode}: у команды без исполнителя {len(plain)} ответов (опора стенда сломана)")
            continue
        if len(got) != 1:
            verdicts.append(f"{mode}: у команды с исполнителем {len(got)} ответов, ожидали ровно 1")
            continue
        if got[0].get("success") is not expected_success:
            verdicts.append(f"{mode}: success={got[0].get('success')!r}, ожидали {expected_success!r}")
        strip = lambda env: {k: v for k, v in env.items() if k != "request_id"}  # noqa: E731
        if strip(got[0]) != strip(plain[0]):
            verdicts.append(f"{mode}: конверт отличается: с исполнителем {strip(got[0])!r}, без {strip(plain[0])!r}")

    assert not verdicts, "нарушения:\n" + "\n".join(verdicts)


# ---------------------------------------------------------------------------
# R8: без reply никогда не DEFERRED
# ---------------------------------------------------------------------------


def test_handle_command_without_reply_never_returns_deferred(make_executor):
    """R8: команда с исполнителем, вызов без reply — dict обработчика, не DEFERRED; один WARNING на имя за 3 вызова."""
    deferred = deferred_sentinel()
    try:
        ex = make_executor("r8")
    except ImportError:
        ex = StubExecutor()  # до реализации: красный должен быть по WARNING, а не по импорту
    cm, log = make_cm("seg")
    handler_threads: dict[str, list[int]] = {"cmd.one": [], "cmd.two": []}

    def make_handler(name: str):
        def handler(data: dict) -> dict:
            handler_threads[name].append(threading.get_ident())
            return {"success": True, "v": 1}

        return handler

    for name in ("cmd.one", "cmd.two"):
        assert cm.register_command(name, make_handler(name), executor=ex, key_from="process_name") is True, (
            f"регистрация {name} с executor+key_from отвергнута"
        )

    verdicts: list[str] = []
    for name in ("cmd.one", "cmd.two"):
        for i in range(3):
            result, caller = run_bounded(
                lambda name=name: cm.handle_command({"command": name, "data": {"process_name": "p1"}})
            )
            if result is deferred:
                verdicts.append(f"{name}#{i}: вернулся DEFERRED без reply")
            elif result != {"success": True, "v": 1}:
                verdicts.append(f"{name}#{i}: результат {result!r}, ожидали {{'success': True, 'v': 1}}")
            if handler_threads[name][-1:] != [caller]:
                verdicts.append(f"{name}#{i}: обработчик исполнен не на вызывающем потоке")

    for name in ("cmd.one", "cmd.two"):
        mine = [w for w in log.warnings() if name in w]
        if len(mine) != 1:
            verdicts.append(f"{name}: WARNING про имя {len(mine)} шт. за 3 вызова, ожидали ровно 1: {mine!r}")
        elif "исполнено вне очереди ключа" not in mine[0]:
            verdicts.append(f"{name}: текст WARNING без «исполнено вне очереди ключа»: {mine[0]!r}")

    assert not verdicts, "нарушения:\n" + "\n".join(verdicts)


# ---------------------------------------------------------------------------
# R9: пропавший ключ — громкий отказ
# ---------------------------------------------------------------------------


def test_missing_key_field_is_refused_loudly(make_executor):
    """R9: key_from="process_name"; нет поля/None/""/123 — key_missing, обработчик не вызван, значения в тексте нет."""
    deferred = deferred_sentinel()
    try:
        ex = make_executor("r9")
    except ImportError:
        ex = StubExecutor()  # до реализации: красный должен быть по отказу, а не по импорту
    cm, log = make_cm("seg")
    calls: list[Any] = []

    def handler(data: dict) -> dict:
        calls.append(data)
        return {"success": True}

    assert cm.register_command("needs.key", handler, executor=ex, key_from="process_name") is True

    cases: list[tuple[str, dict, str | None]] = [
        ("поля нет", {}, None),
        ("None", {"process_name": None}, None),
        ("пустая строка", {"process_name": ""}, None),
        ("int 987654", {"process_name": 987654}, "987654"),
        ("list", {"process_name": ["leak-me"]}, "leak-me"),
    ]
    verdicts: list[str] = []
    for label, data, secret in cases:
        replies: list[Any] = []
        warn_before = len(log.warnings())
        try:
            ret, _ = run_bounded(
                lambda data=data, replies=replies: cm.handle_command(
                    {"command": "needs.key", "data": data}, reply=replies.append
                )
            )
        except TypeError as exc:
            verdicts.append(f"{label}: handle_command(reply=...) -> TypeError: {exc}")
            continue
        delivered = ([] if ret is deferred else [ret]) + replies
        if len(delivered) != 1:
            verdicts.append(
                f"{label}: отказ доставлен {len(delivered)} раз(а), ожидали 1 (ret={ret!r}, reply={replies!r})"
            )
            continue
        refusal = delivered[0]
        if not (
            isinstance(refusal, dict)
            and refusal.get("success") is False
            and refusal.get("error") == "key_missing"
            and refusal.get("command") == "needs.key"
        ):
            verdicts.append(
                f"{label}: отказ {refusal!r}, ожидали success=False, error='key_missing', command='needs.key'"
            )
        if secret is not None:
            texts = [repr(refusal), *log.warnings()[warn_before:]]
            if any(secret in t for t in texts):
                verdicts.append(f"{label}: значение поля {secret!r} просочилось в отказ или WARNING: {texts!r}")
        if len(log.warnings()) <= warn_before:
            verdicts.append(f"{label}: отказ без WARNING")

    time.sleep(0.2)
    if calls:
        verdicts.append(f"обработчик вызван {len(calls)} раз(а): {calls!r}")

    assert not verdicts, "нарушения по точкам:\n" + "\n".join(verdicts)


# ---------------------------------------------------------------------------
# R10: страж — команда без исполнителя ведёт себя как раньше
# ---------------------------------------------------------------------------


def test_command_without_executor_runs_on_receive_thread_as_before(wired):
    """R10: без новых аргументов — поток receive(), прежний авто-ответ; handle_command(reply=r) — dict, r не зван."""
    verdicts: list[str] = []

    # Точка 1: настоящие роутер + CommandManager, регистрация БЕЗ новых аргументов.
    cm, _log = make_cm("seg")
    handler_threads: list[int] = []

    def handler(data: dict) -> dict:
        handler_threads.append(threading.get_ident())
        return {"success": True, "v": 7}

    assert cm.register_command("legacy.cmd", handler) is True
    w = wired(cm)
    recv_ident = w.deliver("legacy.cmd", "cid-r10", {"process_name": "p1"})
    replies = w.wait_replies("cid-r10")
    time.sleep(0.2)
    replies = w.reg.by_request("cid-r10")

    if handler_threads != [recv_ident]:
        verdicts.append(
            f"точка 1: обработчик исполнен на потоках {handler_threads!r}, ожидали [{recv_ident}] (поток receive)"
        )
    expected_envelope = {
        "type": "response",
        "command": "command.response",
        "sender": "seg",
        "targets": ["gui"],
        "queue_type": "system",
        "request_id": "cid-r10",
        "success": True,
        "result": {"success": True, "v": 7},
    }
    if replies != [expected_envelope]:
        verdicts.append(f"точка 1: авто-ответ {replies!r}, ожидали ровно [{expected_envelope!r}]")

    # Точка 2: прямой вызов с reply для команды без исполнителя.
    cm2, _log2 = make_cm("seg2")
    threads2: list[int] = []

    def handler2(data: dict) -> dict:
        threads2.append(threading.get_ident())
        return {"success": True, "v": 9}

    assert cm2.register_command("legacy.cmd", handler2) is True
    r_calls: list[Any] = []
    try:
        result, caller = run_bounded(
            lambda: cm2.handle_command({"command": "legacy.cmd", "data": {}}, reply=r_calls.append)
        )
    except TypeError as exc:
        verdicts.append(f"точка 2: handle_command(msg, reply=r) -> TypeError: {exc}")
    else:
        if result != {"success": True, "v": 9}:
            verdicts.append(f"точка 2: результат {result!r}, ожидали dict обработчика {{'success': True, 'v': 9}}")
        if threads2 != [caller]:
            verdicts.append(f"точка 2: обработчик исполнен на потоках {threads2!r}, ожидали вызывающий [{caller}]")
        if r_calls:
            verdicts.append(f"точка 2: reply вызван {len(r_calls)} раз(а): {r_calls!r}")

    assert not verdicts, "нарушения по точкам:\n" + "\n".join(verdicts)


# ---------------------------------------------------------------------------
# R13: отказы регистрации
# ---------------------------------------------------------------------------


def test_register_with_executor_refuses_bad_combinations(make_executor):
    """R13: плохие сочетания executor с key_from, targets, manages_own_reply — False, команда не зарегистрирована."""
    cm, log = make_cm("seg")
    stub = StubExecutor()

    def handler(data: dict) -> dict:
        return {"success": True}

    bad: list[tuple[str, dict]] = [
        ("executor без key_from и без targets", {"executor": stub}),
        ("executor с key_from и targets='all'", {"executor": stub, "key_from": "process_name", "targets": "all"}),
        ("targets='some'", {"executor": stub, "targets": "some"}),
        (
            "manages_own_reply=True",
            {"executor": stub, "key_from": "process_name", "metadata": {"manages_own_reply": True}},
        ),
    ]
    verdicts: list[str] = []
    for i, (label, kwargs) in enumerate(bad):
        name = f"bad.{i}"
        warn_before = len(log.warnings())
        try:
            ok = cm.register_command(name, handler, **kwargs)
        except Exception as exc:  # noqa: BLE001 — отказ должен быть значением False, а не исключением
            verdicts.append(f"{label}: исключение {type(exc).__name__}: {exc}")
            continue
        if ok is not False:
            verdicts.append(f"{label}: register_command вернул {ok!r}, ожидали False")
        if name in registered_names(cm):
            verdicts.append(f"{label}: команда {name} оказалась зарегистрирована")
        if len(log.warnings()) <= warn_before:
            verdicts.append(f"{label}: отказ без WARNING")

    # Контроль: допустимые сочетания не отвергаются (иначе «всё отвергать» прошло бы тест).
    try:
        real = make_executor("r13")
    except ImportError as exc:
        verdicts.append(f"контроль: настоящий KeyedExecutor недоступен ({exc})")
    else:
        for name, kwargs in (
            ("ok.key_from", {"executor": real, "key_from": "process_name"}),
            ("ok.targets_all", {"executor": real, "targets": "all"}),
        ):
            if cm.register_command(name, handler, **kwargs) is not True:
                verdicts.append(f"контроль: допустимая регистрация {name} с {sorted(kwargs)} отвергнута")

    assert not verdicts, "нарушения по точкам:\n" + "\n".join(verdicts)
