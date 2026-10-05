# -*- coding: utf-8 -*-
"""
Слепая приёмка Atlas 0.8b: фреймворк запускает процессы методом ``spawn`` на любой ОС.

Контракт ``StubPlatformAdapter.setup_multiprocessing()``:

* Post: ``multiprocessing.get_start_method(allow_none=True) == "spawn"`` на любой ОС;
* идемпотентность: повторный вызов при уже выставленном ``spawn`` не бросает;
* другой метод уже выставлен -> ``RuntimeError`` с текстом
  ``start method already set to <метод>; framework requires spawn``;
* ``SystemLauncher.__init__`` оставляет процесс на ``spawn`` (сегодня его
  ``multiprocessing.Event()`` фиксирует умолчание ОС — на Linux это fork — раньше,
  чем что-либо выставит ``spawn``);
* прогон pytest над ``multiprocess_framework/modules`` идёт на ``spawn``
  (его гарантирует ``modules/conftest.py``).

**Метод запуска — ПРОЦЕССНОЕ состояние, поэтому каждая проверка идёт в СВЕЖЕМ
интерпретаторе** (``subprocess.run([sys.executable, "-c", SCRIPT])``): в самом
процессе pytest ``set_start_method`` не зовётся никогда, а сам прогон не может
«нагреть» метод для соседа. Дочерний скрипт печатает литеральную строку
``RESULT ...``, тест сверяет её с литералом.

**Всегда ``get_start_method(allow_none=True)``.** Без ``allow_none`` сам вызов
фиксирует умолчание ОС, и проверка зеленеет до кода (на Linux — «fork», на Windows —
«spawn»). С ``allow_none=True`` незафиксированный метод виден как ``None``, а
``None != "spawn"`` — красное по существу.

**Подмена платформы.** ``multiprocessing`` и фреймворк импортируются при НАСТОЯЩЕЙ
платформе, и только потом, непосредственно перед вызовом, ``sys.platform`` подменяется
на ``"linux"``/``"darwin"``. Подмена ДО импорта фреймворка невозможна на Windows: при
``sys.platform == "linux"`` импорт ``watchdog`` (его тянет ``config_module``) падает в
``ctypes.CDLL(None)`` — красное по чужой причине, не по контракту. Цена: проверка видит
только то, что ``setup_multiprocessing()`` смотрит на платформу В МОМЕНТ ВЫЗОВА, а не
при импорте модуля (так устроен и сегодняшний код). Так проверяется ветка «не Windows»
на машине с Windows: старый код делал ``spawn`` только при ``sys.platform == "win32"``.

**Тест 4 (``SystemLauncher``) на win32 зелёный ДО кода и не пропускается:** умолчание
ОС там и есть ``spawn``, ``Event()`` его фиксирует. Тест нужен для Linux/CI, где до
кода он красный (fork/forkserver), и как страж от регрессии на Windows.

**Тест 5 (сессия pytest) — выбор дизайна.** ``conftest.py`` действует только на файлы
под ``multiprocess_framework/modules``, а создавать зонд-тест в этом каталоге нельзя
(и порядок «зонд внутри дерева» зависит от рабочего каталога). Поэтому: дочерний
``python -m pytest --collect-only`` с cwd = ``modules``, аргумент — ЭТОТ файл (он под
``modules``, значит ``modules/conftest.py`` грузится штатным путём, как в обычном
прогоне), плюс плагин-зонд из ``tmp_path`` (``-p``). Плагин в ``pytest_sessionstart``
пишет ``get_start_method(allow_none=True)`` в файл. ``pytest_configure`` (где conftest
выставляет ``spawn``) по устройству pytest всегда раньше ``pytest_sessionstart``, так
что результат не зависит от порядка тестов — тестов в прогоне нет вовсе. Файл, а не
stdout: захват вывода pytest не должен прятать результат. До кода зонд видит ``None``.
"""

from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Корень репозитория от места файла, а не от cwd: дочерний `python -c` должен найти
# пакет multiprocess_framework при запуске из любого каталога (в .venv нет
# editable-установки). tests -> process_manager_module -> modules ->
# multiprocess_framework -> корень.
_REPO_ROOT = str(Path(__file__).resolve().parents[3].parent)
_MODULES_DIR = str(Path(__file__).resolve().parents[2])

_CHILD_TIMEOUT_S = 60

_ADAPTER_IMPORT = "from multiprocess_framework.modules.process_manager_module.platforms.base import StubPlatformAdapter"


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = _REPO_ROOT
    env["PYTHONUTF8"] = "1"
    return env


def _run_script(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        env=_child_env(),
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_CHILD_TIMEOUT_S,
    )


def _result_line(proc: subprocess.CompletedProcess[str]) -> str:
    """Последняя строка ``RESULT ...`` из stdout дочернего процесса (или пусто)."""
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    return lines[-1] if lines else ""


def _report(proc: subprocess.CompletedProcess[str]) -> str:
    return f"rc={proc.returncode}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr[-2000:]}"


def _foreign_platform_script(platform: str, calls: int) -> str:
    return f"""
import multiprocessing
import sys
{_ADAPTER_IMPORT}
adapter = StubPlatformAdapter()
sys.platform = {platform!r}
for _ in range({calls}):
    adapter.setup_multiprocessing()
print("RESULT platform=" + sys.platform + " start_method=" + str(multiprocessing.get_start_method(allow_none=True)))
"""


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_setup_leaves_spawn_on_non_windows_platform(platform: str) -> None:
    """Post: на «не Windows» ``setup_multiprocessing()`` выставляет ``spawn``.

    Не вакуумно: до кода ветка не-win32 ничего не делает, метод остаётся ``None``
    (``allow_none=True``), и строка ``start_method=None`` не равна литералу.
    """
    proc = _run_script(_foreign_platform_script(platform, calls=1))
    assert _result_line(proc) == f"RESULT platform={platform} start_method=spawn", _report(proc)


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_setup_twice_is_idempotent_on_non_windows_platform(platform: str) -> None:
    """Идемпотентность: второй вызов при уже выставленном ``spawn`` не бросает.

    Строка с результатом печатается только если оба вызова вернулись без исключения
    (исключение = трейсбек и отсутствие ``RESULT``). Метод в конце — ``spawn``, а не
    «не бросило»: вторая половина свойства не даёт пройти коду, который молча
    ничего не делает.
    """
    proc = _run_script(_foreign_platform_script(platform, calls=2))
    assert _result_line(proc) == f"RESULT platform={platform} start_method=spawn", _report(proc)


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(),
    reason="метод fork недоступен на этой ОС (Windows): предустановить его нечем",
)
def test_setup_refuses_when_fork_is_already_set() -> None:
    """Другой метод уже выставлен -> ``RuntimeError`` с текстом из контракта.

    Не вакуумно: до кода на не-Windows ``setup_multiprocessing()`` — no-op, исключения
    нет, и скрипт печатает ``RESULT no-exception``; тест требует именно текст ошибки.
    """
    script = f"""
import multiprocessing
multiprocessing.set_start_method("fork")
{_ADAPTER_IMPORT}
try:
    StubPlatformAdapter().setup_multiprocessing()
except RuntimeError as exc:
    print("RESULT RuntimeError: " + str(exc))
else:
    print("RESULT no-exception start_method=" + str(multiprocessing.get_start_method(allow_none=True)))
"""
    proc = _run_script(script)
    result = _result_line(proc)
    assert result.startswith("RESULT RuntimeError: "), _report(proc)
    assert "start method already set to fork; framework requires spawn" in result, _report(proc)


def test_system_launcher_construction_leaves_spawn() -> None:
    """``SystemLauncher(...)`` без запуска оставляет процесс на ``spawn``.

    На win32 зелёный ДО кода (умолчание ОС — spawn, ``Event()`` его фиксирует) —
    не пропускается, это страж регрессии; красным он бывает на Linux/CI
    (``fork``/``forkserver`` зафиксирован ``Event()`` раньше, чем что-то выставит spawn).
    """
    script = """
import multiprocessing
from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import SystemLauncher
launcher = SystemLauncher()
print("RESULT start_method=" + str(multiprocessing.get_start_method(allow_none=True)))
"""
    proc = _run_script(script)
    assert _result_line(proc) == "RESULT start_method=spawn", _report(proc)


_PROBE_PLUGIN = """
import multiprocessing
import os


def pytest_sessionstart(session):
    with open(os.environ["START_METHOD_PROBE_OUT"], "w", encoding="utf-8") as fh:
        fh.write("RESULT start_method=" + str(multiprocessing.get_start_method(allow_none=True)))
"""


def test_pytest_session_over_modules_runs_on_spawn(tmp_path: Path) -> None:
    """Сессия pytest над ``modules`` идёт на ``spawn`` (его выставляет ``modules/conftest.py``).

    Дочерний pytest: cwd = ``modules``, аргумент — этот файл (под ``modules``, значит
    ``modules/conftest.py`` применяется штатно), ``--collect-only``, плагин-зонд из
    ``tmp_path`` пишет метод в файл на ``pytest_sessionstart``. До кода метод
    не зафиксирован -> ``None`` -> красное по существу.
    """
    (tmp_path / "start_method_probe_plugin.py").write_text(_PROBE_PLUGIN, encoding="utf-8")
    out_file = tmp_path / "probe_out.txt"
    env = _child_env()
    env["PYTHONPATH"] = os.pathsep.join([_REPO_ROOT, str(tmp_path)])
    env["START_METHOD_PROBE_OUT"] = str(out_file)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(Path(__file__).resolve()),
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "start_method_probe_plugin",
        ],
        env=env,
        cwd=_MODULES_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_CHILD_TIMEOUT_S,
    )
    probe = out_file.read_text(encoding="utf-8") if out_file.exists() else "<зонд не отработал>"
    assert probe == "RESULT start_method=spawn", _report(proc)
