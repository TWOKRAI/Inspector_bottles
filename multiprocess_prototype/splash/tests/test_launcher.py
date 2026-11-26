"""Слепая приёмка задачи 2.6: запуск заставки из лончера (``splash.launcher``).

Написано до реализации по ``tasks/2.6.md`` (DESIGN п.2–3, 6–7, REDS). Окно — только ``offscreen``.
Блокирующие вызовы идут в daemon-потоке с дедлайном; порождённые процессы гасятся в ``finally``.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time


def _call(fn, timeout: float = 20.0):
    """Вызов в daemon-потоке: зависание — падение с именем, а не стоящий прогон."""
    box: dict = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # перебрасываем в тестовый поток
            box["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), f"вызов не вернулся за {timeout} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _base_env() -> dict:
    env = dict(os.environ)
    env.pop("INSPECTOR_SPLASH", None)
    env.pop("INSPECTOR_SPLASH_PORT", None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    return env


def _reap(process) -> None:
    """Погасить порождённый тестом процесс (только его)."""
    if process is None or process.poll() is not None:
        return
    if process.stdin is not None:
        try:
            process.stdin.close()  # EOF: заставка уходит сама, даже если PID — трамплин uv
        except OSError:
            pass
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5.0)


def test_starts_nothing_and_never_raises():
    from multiprocess_prototype.splash.launcher import start_splash, stop_splash

    def _env(**extra) -> dict:
        env = _base_env()
        env["INSPECTOR_SPLASH_PORT"] = "1"  # чужой порт из родительского env
        env.update(extra)
        return env

    popen_calls: list = []

    def _popen_raising(error):
        def _popen(*args, **kwargs):
            popen_calls.append(args)
            raise error

        return _popen

    _call(stop_splash)
    try:
        forbidden = _popen_raising(OSError("popen не должен был вызываться"))

        env = _env()
        assert _call(lambda: start_splash(False, environ=env, title="t", popen=forbidden)) is None
        assert "INSPECTOR_SPLASH_PORT" not in env
        assert popen_calls == []

        env = _env(INSPECTOR_SPLASH="0")
        assert _call(lambda: start_splash(True, environ=env, title="t", popen=forbidden)) is None
        assert "INSPECTOR_SPLASH_PORT" not in env
        assert popen_calls == []

        for error in (OSError("нет интерпретатора"), RuntimeError("popen сломан")):
            popen_calls.clear()
            env = _env()
            popen = _popen_raising(error)
            assert _call(lambda: start_splash(True, environ=env, title="t", popen=popen)) is None
            assert "INSPECTOR_SPLASH_PORT" not in env
            assert len(popen_calls) == 1  # отказ пришёл именно из popen
    finally:
        _call(stop_splash)


def test_dev_probe_env_is_not_passed_to_splash():
    """Проба qt-mcp включается переменной: заставка её не получает, GUI (``environ`` вызывающего) получает."""
    from multiprocess_prototype.splash.launcher import start_splash, stop_splash

    env = _base_env()
    env["QT_MCP_PROBE"] = "1"
    env["QT_MCP_PORT"] = "9142"
    child_env: dict = {}

    def popen(*args, **kwargs):
        child_env.update(kwargs["env"])
        raise OSError("дальше запуска не идём")

    _call(stop_splash)
    try:
        assert _call(lambda: start_splash(True, environ=env, title="t", popen=popen)) is None
        assert child_env  # popen вызван и получил окружение
        assert "QT_MCP_PROBE" not in child_env
        assert child_env["QT_MCP_PORT"] == "9142"
        assert env["QT_MCP_PROBE"] == "1"  # окружение запускающего не тронуто
    finally:
        _call(stop_splash)


def test_real_process_port_and_gui_done():
    from multiprocess_prototype.splash.launcher import start_splash, stop_splash
    from multiprocess_prototype.splash.protocol import send_leaf

    env = _base_env()
    processes: list = []
    _call(stop_splash)
    try:
        link = _call(lambda: start_splash(True, environ=env, title="Inspector Bottles"))
        assert link is not None
        processes.append(link.process)
        assert _call(lambda: link.publish_port(env, wait_s=5.0)) is True
        assert env["INSPECTOR_SPLASH_PORT"].isdigit()

        # Копия env: ``start_splash`` «первым делом» снимает порт из переданного словаря, а для повторного
        # вызова задача не говорит, делает ли он это, — тест не должен зависеть от ответа.
        again = _call(lambda: start_splash(True, environ=dict(env), title="Inspector Bottles"))
        assert again is link

        assert send_leaf("gui", {"percent": 100, "done": True}, env) is True
        assert link.process.wait(timeout=5.0) == 0
        _call(link.close)

        link2 = _call(lambda: start_splash(True, environ=env, title="Inspector Bottles"))
        assert link2 is not None
        processes.append(link2.process)
        assert link2 is not link
        assert _call(lambda: link2.publish_port(env, wait_s=5.0)) is True
        # Порт приходит ДО импорта PySide6: даём окну подняться, чтобы close() судил уход по EOF, а не импорт.
        time.sleep(1.5)
        assert link2.process.poll() is None
        _call(link2.close)
        assert link2.process.poll() == 0
    finally:
        try:
            _call(stop_splash)
        finally:
            for process in processes:
                _reap(process)
