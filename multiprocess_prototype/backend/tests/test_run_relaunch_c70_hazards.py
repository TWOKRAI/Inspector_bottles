"""C-70: сторожа разработчика к ``run.default_relaunch`` (HR1, HR2).

Приёмочные тесты тестера (``test_run_relaunch_c70.py``) проверяют код выхода и ветки. Здесь —
то, что они не ловят: Ctrl+C во время ожидания (на Windows ``KeyboardInterrupt`` приходит уже
после выхода ребёнка) и границу знакового кода выхода.

``_thread.interrupt_main`` не используем: из потока сигнал уходит в главный поток и рвёт
сессию pytest. Исключение бросает обёртка над ``Popen.wait`` прямо в потоке вызова.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

import multiprocess_prototype.frontend.run as frun
import multiprocess_prototype.run as run

_windows_only = pytest.mark.skipif(os.name != "nt", reason="HR1: ветка Popen+wait только на Windows")

_REAL_POPEN = subprocess.Popen


def _call_with_deadline(fn, *args, deadline: float = 20.0):
    """Вызвать ``fn`` в daemon-потоке; зависание — красный тест, а не зависший pytest."""
    box: dict[str, object] = {}

    def _run() -> None:
        try:
            box["rc"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 — исключение потока отдаём тесту
            box["exc"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(deadline)
    assert not thread.is_alive(), f"{fn.__name__} не вернулся за {deadline} с"
    if isinstance(box.get("exc"), KeyboardInterrupt):
        # Не пробрасываем как есть: в главном потоке он оборвал бы всю сессию pytest.
        pytest.fail("KeyboardInterrupt вышел из default_relaunch: цикл ожидания не гасит прерывание")
    if "exc" in box:
        raise box["exc"]  # type: ignore[misc]
    return box["rc"]


@_windows_only
def test_hr1_keyboard_interrupt_during_wait_keeps_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Первый ``wait()`` бросает KeyboardInterrupt при живом ребёнке: ждём дальше, код — ребёнка."""
    seen: dict[str, object] = {"killed": False, "poll_at_interrupt": "unset", "waits": 0}

    class _InterruptingPopen:
        def __init__(self, argv: list[str], **kwargs: object) -> None:
            self._real = _REAL_POPEN(argv, **kwargs)

        def wait(self, *args: object, **kwargs: object) -> int:
            seen["waits"] = int(seen["waits"]) + 1  # type: ignore[call-overload]
            if seen["waits"] == 1:
                seen["poll_at_interrupt"] = self._real.poll()
                raise KeyboardInterrupt
            return self._real.wait(*args, **kwargs)

        def kill(self) -> None:
            seen["killed"] = True
            self._real.kill()

        def terminate(self) -> None:
            seen["killed"] = True
            self._real.terminate()

    monkeypatch.setattr(run.subprocess, "Popen", _InterruptingPopen)
    argv = [sys.executable, "-c", "import sys, time; time.sleep(1); sys.exit(6)"]

    rc = _call_with_deadline(run.default_relaunch, sys.executable, argv)

    assert rc == 6
    assert seen["poll_at_interrupt"] is None, "ребёнок уже вышел к моменту прерывания: сторож ничего не проверяет"
    assert seen["killed"] is False
    assert seen["waits"] == 2


@_windows_only
def test_hr3_executable_comes_from_exe_not_from_argv0(tmp_path: Path) -> None:
    """Настоящий ребёнок при ``argv[0] != exe``: без ``executable=exe`` Windows даёт FileNotFoundError."""
    marker = tmp_path / "ran.marker"
    script = tmp_path / "child.py"
    script.write_text(
        textwrap.dedent(
            f"""            import sys
            open({str(marker)!r}, "w").write("ran")
            sys.exit(5)
            """
        ),
        encoding="utf-8",
    )

    rc = _call_with_deadline(run.default_relaunch, sys.executable, ["relaunch-child-name", str(script)])

    assert rc == 5
    assert marker.read_text() == "ran"


@pytest.mark.parametrize(
    "fn",
    [
        pytest.param(run.venv_guard, id="run.venv_guard"),
        pytest.param(run.launch, id="run.launch"),
        pytest.param(frun.launch, id="frontend.launch"),
    ],
)
def test_hr4_seam_default_is_default_relaunch(fn) -> None:
    """Умолчание шва — ``run.default_relaunch`` во всех трёх сигнатурах.

    Все остальные тесты передают ``relaunch=`` явно, поэтому подмену умолчания на ``os.execv``
    (на Windows она возвращает дефект C-70) они не видят. Поведенческий вариант невозможен:
    настоящий ``execv`` на Windows завершил бы сессию pytest.
    """
    assert inspect.signature(fn).parameters["relaunch"].default is run.default_relaunch


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(0, 0, id="zero"),
        pytest.param(3, 3, id="small"),
        pytest.param(0x7FFFFFFF, 2147483647, id="max-positive-stays"),
        pytest.param(0x80000000, -2147483648, id="boundary-becomes-negative"),
        pytest.param(0xC0000005, -1073741819, id="access-violation"),
        pytest.param(0xFFFFFFFF, -1, id="all-ones"),
    ],
)
def test_hr2_unsigned_windows_code_becomes_signed(monkeypatch: pytest.MonkeyPatch, raw: int, expected: int) -> None:
    """Граница знакового преобразования на фейковом ``Popen`` (работает на любой ОС)."""

    class _FakePopen:
        def __init__(self, argv: list[str], **kwargs: object) -> None:
            pass

        def wait(self) -> int:
            return raw

    monkeypatch.setattr(run.subprocess, "Popen", _FakePopen)
    fn = run.default_relaunch  # имя берётся до подмены os.name
    with monkeypatch.context() as mp:
        mp.setattr(os, "name", "nt")
        rc = fn("X", ["X", "s"])

    assert rc == expected
