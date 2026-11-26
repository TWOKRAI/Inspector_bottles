"""Hazard-тесты автора задачи 2.6: порядок, гонки, отказы и границы импорта.

Только ``offscreen``, свои сокеты ``127.0.0.1:0``; настоящие дети гасятся в ``finally``.
"""

from __future__ import annotations

import ast
import os
import re
import socket
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from multiprocess_prototype.splash import launcher
from multiprocess_prototype.splash.protocol import decode, send_leaf

_ROOT = Path(__file__).resolve().parents[3]
_APP_YAML = _ROOT / "multiprocess_prototype" / "app.yaml"


def _call(fn, timeout: float = 20.0):
    box: dict = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), f"вызов не вернулся за {timeout} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


@pytest.fixture(autouse=True)
def _clean_holder():
    launcher.stop_splash()
    yield
    launcher.stop_splash()


class _PipeProcess:
    """Дублёр ``Popen`` с настоящей трубой stdout: тест сам решает, когда придёт строка порта."""

    def __init__(self, *, exits_on_eof: bool = True) -> None:
        self.events: list[str] = []
        read_fd, self._write_fd = os.pipe()
        self._exits_on_eof = exits_on_eof
        self._dead = False
        events = self.events

        class _Stdin:
            def close(self) -> None:
                events.append("stdin.close")

        class _Stdout:
            def fileno(self) -> int:
                return read_fd

            def close(self) -> None:
                events.append("stdout.close")
                os.close(read_fd)

        self.stdin = _Stdin()
        self.stdout = _Stdout()

    def write(self, data: bytes) -> None:
        os.write(self._write_fd, data)

    def die(self) -> None:
        if not self._dead:
            self._dead = True
            os.close(self._write_fd)

    def wait(self, timeout: float | None = None) -> int:
        self.events.append("wait")
        if not self._exits_on_eof and "kill" not in self.events:
            raise subprocess.TimeoutExpired("splash", timeout)
        self.die()
        return 0

    def kill(self) -> None:
        self.events.append("kill")


def _start(process: _PipeProcess, env: dict) -> Any:
    return launcher.start_splash(True, environ=env, title="t", popen=lambda *a, **k: process)


# --------------------------------------------------------------------------- #
# Порт, отложенный лист, close
# --------------------------------------------------------------------------- #


def test_report_before_port_keeps_last_leaf_and_sends_it_when_port_arrives() -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    process = _PipeProcess()
    env: dict = {}
    try:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(5.0)
        link = _start(process, env)
        link.report({"percent": 10, "label": "первый", "done": False})
        link.report({"percent": 50, "label": "последний", "done": False})
        process.write(f"{receiver.getsockname()[1]}\n".encode())

        assert decode(receiver.recv(65535)) == {"id": "launch", "percent": 50, "label": "последний", "done": False}
        assert _call(lambda: link.publish_port(env, wait_s=5.0)) is True
        assert env["INSPECTOR_SPLASH_PORT"] == str(receiver.getsockname()[1])
        receiver.settimeout(0.2)
        with pytest.raises(TimeoutError):
            receiver.recv(65535)  # первый лист не досылается
    finally:
        _call(launcher.stop_splash)
        process.die()
        receiver.close()


def test_close_order_stdin_wait_kill_wait_then_stdout() -> None:
    process = _PipeProcess(exits_on_eof=False)
    link = _start(process, {})
    _call(link.close)
    _call(link.close)  # идемпотентно

    assert process.events == ["stdin.close", "wait", "kill", "wait", "stdout.close"]


def test_stdout_stays_open_while_reader_is_blocked() -> None:
    """Ребёнок «умер», но пишущий конец трубы жив (внук за трамплином): закрытие stdout повисло бы."""
    process = _PipeProcess()
    process.wait = lambda timeout=None: 0  # конец трубы не закрывается
    try:
        link = _start(process, {})
        _call(link.close, timeout=5.0)
        assert "stdout.close" not in process.events
    finally:
        process.die()


def test_publish_port_without_line_kills_child_and_leaves_env(capsys: pytest.CaptureFixture) -> None:
    """Настоящий ребёнок молчит и stdin не читает: ``publish_port`` -> ``False``, ребёнок добит вместе с трубой."""
    spawned: list = []

    def _popen(argv, **kwargs):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], **kwargs)
        spawned.append(child)
        return child

    env = dict(os.environ)
    env.pop("INSPECTOR_SPLASH", None)
    try:
        link = _call(lambda: launcher.start_splash(True, environ=env, title="t", popen=_popen))
        assert _call(lambda: link.publish_port(env, wait_s=0.1)) is False
        assert "INSPECTOR_SPLASH_PORT" not in env
        assert spawned[0].wait(timeout=5.0) is not None
        link._reader.join(5.0)
        # Поток чтения вышел -> пишущих концов трубы не осталось, то есть погашен и настоящий интерпретатор.
        assert not link._reader.is_alive()
        assert "[run] заставка: порт не пришёл — без заставки" in capsys.readouterr().err
    finally:
        for child in spawned:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5.0)


def test_report_after_splash_death_is_silent(capsys: pytest.CaptureFixture) -> None:
    process = _PipeProcess()
    env: dict = {}
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    dead_port = probe.getsockname()[1]
    probe.close()
    try:
        link = _start(process, env)
        process.write(f"{dead_port}\n".encode())
        assert _call(lambda: link.publish_port(env, wait_s=5.0)) is True
        process.die()
        for _ in range(3):
            _call(lambda: link.report({"percent": 100, "done": True}))
        assert capsys.readouterr().err == ""
    finally:
        _call(launcher.stop_splash)


def test_request_close_while_main_thread_holds_lock_does_not_deadlock(monkeypatch: pytest.MonkeyPatch) -> None:
    """SIGINT приходит в главный поток между байткодами, в том числе под замком ``poll``."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from multiprocess_prototype.splash.window import SplashController

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    try:
        controller = SplashController(window=SimpleNamespace(), sock=sock)

        def _reenter() -> str | None:
            with controller._lock:
                controller.request_close("sigint")
            return controller.poll()

        assert _call(_reenter, timeout=5.0) == "sigint"
    finally:
        sock.close()


def test_live_holder_keeps_env_and_refusals_keep_holder() -> None:
    """Решение лида 1: повтор — тот же объект без правки env; отказ снимает порт и держатель не трогает."""
    process = _PipeProcess()
    try:
        link = _start(process, {})

        env = {"INSPECTOR_SPLASH_PORT": "7"}
        assert launcher.start_splash(True, environ=env, title="t") is link
        assert env == {"INSPECTOR_SPLASH_PORT": "7"}

        assert launcher.start_splash(False, environ=env, title="t") is None
        assert env == {}
        assert launcher.start_splash(True, environ={}, title="t") is link
    finally:
        process.die()
        _call(launcher.stop_splash)


def test_decode_truncates_long_label_and_rejects_wrong_types() -> None:
    """Решение лида 2."""
    long_label = b'{"id": "boot", "percent": 5, "label": "' + b"x" * 300 + b'"}'

    assert decode(long_label)["label"] == "x" * 200
    assert decode(b'{"id": "boot", "percent": -1}') is None
    assert decode(b'{"id": "boot", "percent": 5, "label": 1}') is None
    assert decode(b'{"id": "boot", "percent": 5, "done": 1}') is None


def test_real_process_prints_exactly_two_lines(capfd: pytest.CaptureFixture) -> None:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    env.pop("INSPECTOR_SPLASH", None)
    try:
        link = _call(lambda: launcher.start_splash(True, environ=env, title="t"))
        assert _call(lambda: link.publish_port(env, wait_s=5.0)) is True
        assert send_leaf("gui", {"percent": 100, "done": True}, env) is True
        assert link.process.wait(timeout=10.0) == 0
    finally:
        _call(launcher.stop_splash)

    lines = [line for line in capfd.readouterr().err.splitlines() if line.startswith("[splash]")]
    assert len(lines) == 2, lines
    assert lines[0] == "[splash] shown"
    assert re.fullmatch(r"\[splash\] closed reason=gui_done after \d+\.\d s percent=40", lines[1]), lines


# --------------------------------------------------------------------------- #
# Границы импорта
# --------------------------------------------------------------------------- #


def test_window_import_does_not_pull_framework() -> None:
    code = (
        "import sys, multiprocess_prototype.splash.window as w;"
        "print(w.__file__);"
        "print(sorted(m for m in sys.modules if m.startswith('multiprocess_framework')))"
    )
    env = dict(os.environ, PYTHONPATH=str(_ROOT))
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=str(_ROOT), env=env, capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stderr
    path, framework = out.stdout.strip().splitlines()
    assert Path(path).resolve().is_relative_to(_ROOT)
    assert framework == "[]"


def test_interface_imports_only_typing() -> None:
    tree = ast.parse((_ROOT / "multiprocess_prototype" / "splash" / "interface.py").read_text(encoding="utf-8"))
    imported = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported == {"typing"}


# --------------------------------------------------------------------------- #
# main() и фабрика
# --------------------------------------------------------------------------- #


def _run_main(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> dict:
    from multiprocess_framework.modules import app_module
    from multiprocess_prototype import main as proto_main

    specs: list = []
    monkeypatch.setattr(app_module, "run_app", lambda spec: specs.append(spec) or 0)
    monkeypatch.setattr(app_module, "apply_env_aliases", lambda: None)
    assert proto_main.main(None, **kwargs) == 0
    return specs[0].launcher_factory.keywords


@pytest.mark.parametrize(
    ("headless", "switch", "expected"),
    [
        (True, None, {"headless": True, "autostart": None}),
        (False, "0", {"headless": False, "autostart": None}),
        (False, None, {"headless": False, "autostart": None, "splash": True}),
    ],
    ids=["headless", "switched-off", "window"],
)
def test_main_passes_splash_only_when_allowed(
    monkeypatch: pytest.MonkeyPatch, headless: bool, switch: str | None, expected: dict
) -> None:
    monkeypatch.delenv("INSPECTOR_SPLASH", raising=False)
    if switch is not None:
        monkeypatch.setenv("INSPECTOR_SPLASH", switch)
    monkeypatch.setenv("INSPECTOR_SPLASH_PORT", "1")

    assert _run_main(monkeypatch, headless=headless) == expected
    assert "INSPECTOR_SPLASH_PORT" not in os.environ  # строка C: чужой порт не наследуется


def _factory(monkeypatch: pytest.MonkeyPatch, link: Any, *, splash: bool) -> tuple[Any, list]:
    from multiprocess_prototype import main as proto_main
    from multiprocess_prototype.backend import launch

    calls: list = []

    class _Builder:
        presentation_window_expected = True

        def build(self) -> str:
            calls.append("build")
            return "built"

    def _from_manifest(*a: Any, **k: Any) -> _Builder:
        calls.append(("from_manifest", k))
        return _Builder()

    def _start_splash(expected: bool, **k: Any) -> Any:
        calls.append(("start_splash", expected, k["title"]))
        return link

    monkeypatch.setattr(launch.SystemBuilder, "from_manifest", _from_manifest)
    monkeypatch.setattr(launcher, "start_splash", _start_splash)
    monkeypatch.setattr(proto_main, "build_launcher", lambda *a, **k: calls.append("build_launcher") or "plain")
    result = proto_main._prototype_launcher_factory(
        SimpleNamespace(source=_APP_YAML), None, headless=False, splash=splash
    )
    return result, calls


def test_factory_without_splash_uses_build_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _factory(monkeypatch, None, splash=False)

    assert result == "plain"
    assert calls == ["build_launcher"]


def test_factory_with_splash_but_no_link_only_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Строка A: ``start_splash`` -> ``None``, к ссылке обращений нет."""
    result, calls = _factory(monkeypatch, None, splash=True)

    assert result == "built"
    assert calls == [
        ("from_manifest", {"include_presentation": True, "run_autostart": None}),
        ("start_splash", True, "Inspector Bottles"),
        "build",
    ]


def test_factory_with_splash_reports_around_build_then_publishes(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list = []

    class _Link:
        def report(self, leaf: dict) -> None:
            order.append(("report", leaf["percent"], leaf["done"]))

        def publish_port(self, environ: Any) -> bool:
            order.append(("publish_port", environ is os.environ))
            return True

    from multiprocess_prototype import main as proto_main
    from multiprocess_prototype.backend import launch

    builder = SimpleNamespace(presentation_window_expected=True, build=lambda: order.append("build") or "built")
    monkeypatch.setattr(launch.SystemBuilder, "from_manifest", lambda *a, **k: builder)
    monkeypatch.setattr(launcher, "start_splash", lambda expected, **k: _Link())

    proto_main._prototype_launcher_factory(SimpleNamespace(source=_APP_YAML), None, splash=True)

    assert order == [("report", 50, False), "build", ("report", 100, True), ("publish_port", True)]


# --------------------------------------------------------------------------- #
# Признак окна, оркестратор, писатель GUI
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("include", "expected"), [(True, True), (False, False)])
def test_builder_property_follows_presentation_overlay(include: bool, expected: bool) -> None:
    from multiprocess_prototype.backend.config.manifest import load_manifest
    from multiprocess_prototype.backend.launch import SystemBuilder

    app = load_manifest(_APP_YAML).model_copy(
        update={"presentation": _ROOT / "multiprocess_prototype" / "frontend" / "presentation.yaml"}
    )
    builder = SystemBuilder.from_manifest(app, "letter_robot_sim", include_presentation=include)

    assert builder.presentation_window_expected is expected


def test_orchestrator_installs_mirror_after_base_store(monkeypatch: pytest.MonkeyPatch) -> None:
    from multiprocess_framework.modules.app_module.orchestrator import GenericProcessManagerApp
    from multiprocess_prototype import orchestrator

    order: list = []
    monkeypatch.setattr(
        GenericProcessManagerApp, "_setup_state_store", lambda self: setattr(self, "_state_store_manager", "стор")
    )
    monkeypatch.setattr(orchestrator, "install_progress_mirror", order.append)

    app = object.__new__(orchestrator.ProcessManagerProcessApp)
    app._setup_state_store()

    assert order == ["стор"]


def test_for_process_writes_through_state_proxy_and_noops_without_it() -> None:
    from multiprocess_prototype.frontend.startup_progress import GuiStartupProgress

    written: list = []
    warnings: list = []
    proxy = SimpleNamespace(set=lambda path, leaf: written.append((path, leaf["percent"])))
    process = SimpleNamespace(_gui_state_proxy=proxy, _log_warning=lambda text, **k: warnings.append(text))

    GuiStartupProgress.for_process(process).step("qt")
    bare = SimpleNamespace(_log_warning=lambda text, **k: warnings.append(text))
    GuiStartupProgress.for_process(bare).step("qt")

    assert written == [("system.progress.gui", 10)]
    assert warnings == []
