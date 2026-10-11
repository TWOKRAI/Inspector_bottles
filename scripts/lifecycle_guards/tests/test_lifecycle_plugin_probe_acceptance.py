"""Слепая приёмка (0.5b): pytest-плагин lifecycle (G3, G4) и раннер пробы abort.

RED до кода. Контракт — решения лида (DESIGN брифа), не реализация.

Все проверки поведения идут в ПОДПРОЦЕССЕ: мини-проект тестов строится под ``tmp_path``,
плагин подключается ключом ``-p scripts.lifecycle_guards.pytest_plugin``. Ожидаемые числа и
строки — литералы. У каждого поведенческого случая есть парный контроль, который НЕ должен
попасть в отчёт (закрытый корень, поток с ``/`` в имени, выживший прогон и т. п.).

Раннер пробы строит «приманку» под ``tmp``: ``logger_module/test_x.py`` с импортом ``PySide6``.
Чтобы импорт ``PySide6`` был только от самого проекта, а не от ``pytest-qt`` (он грузит PySide6 при
настройке), подпроцессам пробы передаётся ``PYTEST_ADDOPTS=-p no:pytest-qt`` (проверено вручную:
иначе ``"PySide6" in sys.modules`` истинно в пустом проекте).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN = "scripts.lifecycle_guards.pytest_plugin"
REPORT_TITLE = "lifecycle-guards report"


# ---------------------------------------------------------------------------
# Общие помощники
# ---------------------------------------------------------------------------


def _base_env(extra: dict[str, str | None] | None = None) -> dict[str, str]:
    """Копия окружения без чужих ручек lifecycle/pytest; ``None`` в extra удаляет ключ."""
    env = dict(os.environ)
    for key in ("LIFECYCLE_G3", "LIFECYCLE_G4", "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "CRASHPROBE_LOG"):
        env.pop(key, None)
    env.update({"PYTHONPATH": str(REPO_ROOT), "PYTHONUTF8": "1", "QT_QPA_PLATFORM": "offscreen"})
    for key, value in (extra or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _write(root: Path, rel: str, source: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def _run_plugin_project(
    tmp: Path,
    files: dict[str, str],
    *,
    g3: str | None = None,
    g4: str | None = None,
) -> tuple[int, str]:
    """Мини-проект в ``tmp``: pytest в подпроцессе с плагином; ``None`` = ручка не задана."""
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    for rel, source in files.items():
        _write(tmp, rel, source)
    cmd = [
        sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "-c", str(tmp / "pytest.ini"), "-p", PLUGIN, str(tmp),
    ]  # fmt: skip
    env = _base_env({"LIFECYCLE_G3": g3, "LIFECYCLE_G4": g4})
    return _run(cmd, cwd=tmp, env=env, timeout=120)


def _section(out: str) -> str:
    """Хвост вывода начиная с раздела отчёта; пусто, если раздела нет."""
    idx = out.find(REPORT_TITLE)
    return "" if idx < 0 else out[idx:]


# Мини-проекты G3 -----------------------------------------------------------

G3_LEAK_HELD = """
    from multiprocess_framework.modules.base_manager import open_scope

    KEEP = []

    def test_leak():
        KEEP.append(open_scope("leaky", budget_s=1.0))
"""

G3_CLOSED = """
    from multiprocess_framework.modules.base_manager import open_scope

    def test_closed():
        root = open_scope("tidy", budget_s=1.0)
        root.close()
"""

G3_DROPPED = """
    import gc
    from multiprocess_framework.modules.base_manager import open_scope

    def test_dropped():
        root = open_scope("dropped", budget_s=1.0)
        del root
        gc.collect()
"""

# Мини-проекты G4 -----------------------------------------------------------

G4_ROGUE = """
    import threading

    STOP = threading.Event()

    def test_rogue():
        threading.Thread(target=STOP.wait, name="rogue-1", daemon=True).start()

    def test_scoped():
        threading.Thread(target=STOP.wait, name="r/tab/w", daemon=True).start()

    def test_finished():
        t = threading.Thread(target=lambda: None, name="done-1")
        t.start()
        t.join()

    def test_plain():
        pass
"""

# Контроль: только потоки, которые НЕ запись (путь с «/», завершившийся до конца теста).
G4_CLEAN = """
    import threading

    STOP = threading.Event()

    def test_scoped():
        threading.Thread(target=STOP.wait, name="r/tab/w", daemon=True).start()

    def test_finished():
        t = threading.Thread(target=lambda: None, name="done-1")
        t.start()
        t.join()
"""

MIXED = """
    import threading
    from multiprocess_framework.modules.base_manager import open_scope

    KEEP = []
    STOP = threading.Event()

    def test_leak():
        KEEP.append(open_scope("leaky", budget_s=1.0))

    def test_rogue():
        threading.Thread(target=STOP.wait, name="rogue-1", daemon=True).start()
"""

FAILING = """
    def test_broken():
        assert 1 == 2
"""


# ---------------------------------------------------------------------------
# G3
# ---------------------------------------------------------------------------

_G3_CASES = [
    # id, проект, G3, ожидаемый rc, ожидаемое N, ожидаемая строка корня (regex) или None
    pytest.param(G3_LEAK_HELD, "report", 0, 1, r"^  leaky \(open\)\s*$", id="leak-report"),
    pytest.param(G3_LEAK_HELD, "fail", 1, 1, r"^  leaky \(open\)\s*$", id="leak-fail"),
    pytest.param(G3_LEAK_HELD, None, 0, 1, r"^  leaky \(open\)\s*$", id="leak-default-is-report"),
    pytest.param(G3_LEAK_HELD, "bogus", 0, 1, r"^  leaky \(open\)\s*$", id="leak-unknown-is-report"),
    pytest.param(G3_DROPPED, "report", 0, 1, r"^  dropped \(abandoned\)\s*$", id="dropped-report"),
    pytest.param(G3_DROPPED, "fail", 1, 1, r"^  dropped \(abandoned\)\s*$", id="dropped-fail"),
    # контроли: закрытый корень в отчёт не попадает
    pytest.param(G3_CLOSED, "report", 0, 0, None, id="closed-report"),
    pytest.param(G3_CLOSED, "fail", 0, 0, None, id="closed-fail"),
]


@pytest.mark.parametrize(("source", "g3", "want_rc", "want_n", "want_line"), _G3_CASES)
def test_g3_unclosed_root_report_and_fail(
    tmp_path: Path, source: str, g3: str | None, want_rc: int, want_n: int, want_line: str | None
) -> None:
    rc, out = _run_plugin_project(tmp_path, {"test_g3.py": source}, g3=g3, g4="off")
    section = _section(out)
    assert section, f"нет раздела '{REPORT_TITLE}':\n{out}"
    assert f"G3 unclosed roots: {want_n}" in section, out
    if want_line is None:
        assert not re.search(r"^  \S+ \((open|abandoned)\)\s*$", section, re.M), out
        assert "tidy" not in section, out
    else:
        assert re.search(want_line, section, re.M), out
    assert "1 passed" in out, out  # тест зелёный: код возврата зависит только от ручки
    assert rc == want_rc, out
    if g3 == "bogus":
        assert "bogus" in out, f"нет предупреждения о неизвестном значении:\n{out}"


def test_g3_off_has_no_g3_output_and_no_section_when_both_off(tmp_path: Path) -> None:
    # off/off: раздела нет вообще, код 0 при утечке (контроль к режимам report/fail выше).
    rc, out = _run_plugin_project(tmp_path, {"test_g3.py": G3_LEAK_HELD}, g3="off", g4="off")
    assert "1 passed" in out, out
    assert REPORT_TITLE not in out, out
    assert "G3 unclosed roots" not in out, out
    assert rc == 0, out
    # off только для G3 (G4 по умолчанию report): строки G3 нет, утечка не валит прогон.
    rc, out = _run_plugin_project(tmp_path / "g4on", {"test_g3.py": G3_LEAK_HELD}, g3="off", g4=None)
    assert "G3 unclosed roots" not in out, out
    assert rc == 0, out


# ---------------------------------------------------------------------------
# G4
# ---------------------------------------------------------------------------

_ROGUE_LINE = r"^  test_g4\.py::test_rogue :: rogue-1\s*$"

_G4_CASES = [
    pytest.param(G4_ROGUE, "report", 0, 1, id="rogue-report"),
    pytest.param(G4_ROGUE, "fail", 1, 1, id="rogue-fail"),
    pytest.param(G4_ROGUE, None, 0, 1, id="rogue-default-is-report"),
    pytest.param(G4_ROGUE, "bogus", 0, 1, id="rogue-unknown-is-report"),
    # контроли: поток с путём («/») и завершившийся до конца теста — не записи
    pytest.param(G4_CLEAN, "report", 0, 0, id="clean-report"),
    pytest.param(G4_CLEAN, "fail", 0, 0, id="clean-fail"),
]


@pytest.mark.parametrize(("source", "g4", "want_rc", "want_n"), _G4_CASES)
def test_g4_unowned_thread_report_and_fail(
    tmp_path: Path, source: str, g4: str | None, want_rc: int, want_n: int
) -> None:
    rc, out = _run_plugin_project(tmp_path, {"test_g4.py": source}, g3="off", g4=g4)
    section = _section(out)
    assert section, f"нет раздела '{REPORT_TITLE}':\n{out}"
    assert f"G4 threads without scope path: {want_n}" in section, out
    if want_n:
        assert re.search(_ROGUE_LINE, section, re.M), out
    # парные контроли не попадают в отчёт ни при каком N
    assert "r/tab/w" not in section, out
    assert "done-1" not in section, out
    assert "test_scoped ::" not in section, out
    assert "test_finished ::" not in section, out
    # поток rogue-1 живёт до конца сессии, но «новый» он только в test_rogue: ровно одна запись
    assert len(re.findall(r"^  \S+ :: \S+\s*$", section, re.M)) == want_n, out
    assert rc == want_rc, out
    if g4 == "bogus":
        assert "bogus" in out, f"нет предупреждения о неизвестном значении:\n{out}"


def test_g4_off_has_no_g4_output(tmp_path: Path) -> None:
    rc, out = _run_plugin_project(tmp_path, {"test_g4.py": G4_ROGUE}, g3="off", g4="off")
    assert "4 passed" in out, out
    assert REPORT_TITLE not in out, out
    assert "G4 threads without scope path" not in out, out
    assert rc == 0, out


# ---------------------------------------------------------------------------
# Код возврата
# ---------------------------------------------------------------------------

_EXIT_CASES = [
    # id, проект, G3, G4, ожидаемый rc
    pytest.param(MIXED, "report", "report", 0, id="both-violations-report-keeps-0"),
    pytest.param(MIXED, "fail", "fail", 1, id="both-violations-fail-gives-1"),
    pytest.param(MIXED, "fail", "report", 1, id="g3-fail-g4-report-g3-decides"),
    pytest.param(MIXED, "report", "fail", 1, id="g3-report-g4-fail-g4-decides"),
    pytest.param(MIXED, "off", "off", 0, id="both-off-keeps-0"),
    # контроли: fail без нарушений своего охранника не валит прогон
    pytest.param(G4_ROGUE, "fail", "report", 0, id="g3-fail-without-g3-violations-keeps-0"),
    pytest.param(G3_LEAK_HELD, "report", "fail", 0, id="g4-fail-without-g4-violations-keeps-0"),
    pytest.param(G4_CLEAN, "fail", "fail", 0, id="fail-fail-clean-session-keeps-0"),
    # report/off не маскируют настоящий красный тест
    pytest.param(FAILING, "report", "report", 1, id="real-failure-not-masked-by-report"),
    pytest.param(FAILING, "off", "off", 1, id="real-failure-not-masked-by-off"),
]


@pytest.mark.parametrize(("source", "g3", "g4", "want_rc"), _EXIT_CASES)
def test_report_mode_keeps_exit_code(tmp_path: Path, source: str, g3: str, g4: str, want_rc: int) -> None:
    rc, out = _run_plugin_project(tmp_path, {"test_exit.py": source}, g3=g3, g4=g4)
    # тесты мини-проекта реально прошли (иначе rc=1 от ошибки загрузки плагина дал бы ложный зелёный)
    assert re.search(r"\d+ (passed|failed)", out), out
    assert rc == want_rc, out
    if (g3, g4) != ("off", "off"):
        assert REPORT_TITLE in out, f"раздел отчёта обязан быть и при {g3}/{g4}:\n{out}"
    if source is MIXED and (g3, g4) != ("off", "off"):
        # раздел показывает нарушения независимо от кода возврата
        if g3 != "off":
            assert "G3 unclosed roots: 1" in out, out
        if g4 != "off":
            assert "G4 threads without scope path: 1" in out, out


# ---------------------------------------------------------------------------
# Раннер пробы
# ---------------------------------------------------------------------------

_SUMMARY = re.compile(
    r"^probe offmain_gc: survived (\d+)/(\d+), crashed (\d+), failed (\d+), "
    r"not-triggered (\d+), wrappers (\S+) \(secs ([^)]*)\)\s*$",
    re.M,
)

_TEST_A = """
    from pathlib import Path
    {import_line}

    def test_a():
        with open(Path(__file__).parents[1] / "{log}", "a", encoding="utf-8") as fh:
            fh.write("run\\n")
"""

_CONFTEST_STATUS = """
    def pytest_sessionfinish(session):
        session.exitstatus = {status}
        {text_line}
"""


def _decoy(
    tmp: Path,
    *,
    subdir: str = "logger_module",
    import_pyside: bool = True,
    test_b: str = "",
    conftest_status: int | None = None,
    conftest_text: str | None = None,
) -> str:
    """Проект-приманка пробы: ``<subdir>/test_x.py`` с зелёным ``test_a`` (+ ``test_b``)."""
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    source = textwrap.dedent(_TEST_A).format(
        import_line="import PySide6  # noqa: F401" if import_pyside else "", log="runs.log"
    )
    if test_b:
        source += "\n" + textwrap.dedent(test_b)
    _write(tmp, f"{subdir}/test_x.py", source)
    if conftest_status is not None:
        text_line = f"session.config.get_terminal_writer().line({conftest_text!r})" if conftest_text else "pass"
        _write(
            tmp,
            "conftest.py",
            _CONFTEST_STATUS.format(status=conftest_status, text_line=text_line),
        )
    return f"{subdir}/test_x.py"


def _run_probe(
    tmp: Path,
    args: list[str],
    *,
    env_extra: dict[str, str | None] | None = None,
    timeout: int = 300,
) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "scripts.lifecycle_guards.probe", *args]
    extra: dict[str, str | None] = {"PYTEST_ADDOPTS": "-p no:pytest-qt"}
    extra.update(env_extra or {})
    return _run(cmd, cwd=REPO_ROOT, env=_base_env(extra), timeout=timeout)


def _summary(out: str) -> tuple[int, int, int, int, int, str]:
    found = _SUMMARY.findall(out)
    assert len(found) == 1, f"ожидалась ровно одна итоговая строка 'probe offmain_gc: ...':\n{out}"
    s, n, c, f, t, w, _secs = found[0]
    return int(s), int(n), int(c), int(f), int(t), w


def _count_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


_FATAL = "Fatal Python error: simulated crash"
_ACCESS = "Windows fatal exception: access violation"

# id, test_b, статус conftest, текст conftest, флаги раннера, (S, N, C, F, T), rc==0?
_CLASS_CASES = [
    pytest.param("", None, None, [], (1, 1, 0, 0, 0), True, id="survived"),
    pytest.param(
        "import os\ndef test_b():\n    os._exit(3221225477)\n",
        None, None, [], (0, 1, 1, 0, 0), False, id="crashed-code-3221225477-no-text",
    ),
    pytest.param(
        "import os\ndef test_b():\n    os._exit(3221225725)\n",
        None, None, [], (0, 1, 1, 0, 0), False, id="crashed-code-3221225725",
    ),
    pytest.param(
        "import os\ndef test_b():\n    os._exit(3221226505)\n",
        None, None, [], (0, 1, 1, 0, 0), False, id="crashed-code-3221226505",
    ),
    pytest.param(
        "import os\ndef test_b():\n    os._exit(139)\n",
        None, None, [], (0, 1, 1, 0, 0), False, id="crashed-code-139",
    ),
    pytest.param(
        "import os\ndef test_b():\n    os._exit(134)\n",
        None, None, [], (0, 1, 1, 0, 0), False, id="crashed-code-134",
    ),
    # код 1, но в выводе признак падения интерпретатора: crashed, не failed
    pytest.param("", 1, _FATAL, [], (0, 1, 1, 0, 0), False, id="crashed-rc1-with-fatal-text"),
    pytest.param("", 1, _ACCESS, [], (0, 1, 1, 0, 0), False, id="crashed-rc1-with-access-violation"),
    # контроли: код 1 без текста и обычный красный тест — failed
    pytest.param("", 1, None, [], (0, 1, 0, 1, 0), False, id="failed-rc1-no-text"),
    pytest.param(
        "def test_b():\n    assert 1 == 2\n",
        None, None, [], (0, 1, 0, 1, 0), False, id="failed-assertion",
    ),
    # код 3 (INTERNAL_ERROR pytest) — failed, не crashed
    pytest.param("", 3, None, [], (0, 1, 0, 1, 0), False, id="failed-rc3-internal-error"),
    # --no-conftest: тот же conftest с кодом 3 игнорируется, прогон выживает
    pytest.param("", 3, None, ["--no-conftest"], (1, 1, 0, 0, 0), True, id="no-conftest-ignores-conftest"),
]  # fmt: skip


@pytest.mark.parametrize(("test_b", "conf_status", "conf_text", "flags", "want", "want_rc0"), _CLASS_CASES)
def test_probe_runner_classification(
    tmp_path: Path,
    test_b: str,
    conf_status: int | None,
    conf_text: str | None,
    flags: list[str],
    want: tuple[int, int, int, int, int],
    want_rc0: bool,
) -> None:
    target = _decoy(tmp_path, test_b=test_b, conftest_status=conf_status, conftest_text=conf_text)
    rc, out = _run_probe(
        tmp_path,
        ["run", "--mode", "offmain_gc", "--runs", "1", "--targets", target,
         "--cwd", str(tmp_path), "--skip-axis", *flags],
    )  # fmt: skip
    assert _summary(out)[:5] == want, out
    assert (rc == 0) is want_rc0, f"rc={rc}\n{out}"


def test_probe_runner_runs_n_times_over_all_targets(tmp_path: Path) -> None:
    target = _decoy(tmp_path)
    _write(tmp_path, "other/test_y.py", _TEST_A.format(import_line="", log="other.log"))
    rc, out = _run_probe(
        tmp_path,
        ["run", "--mode", "offmain_gc", "--runs", "2", "--targets", target, "other/test_y.py",
         "--cwd", str(tmp_path), "--skip-axis"],
    )  # fmt: skip
    s, n, c, f, t, wrappers = _summary(out)
    assert (s, n, c, f, t) == (2, 2, 0, 0, 0), out
    assert re.fullmatch(r"\d+", wrappers), f"W — целое число, получено {wrappers!r}\n{out}"
    assert rc == 0, out
    assert _count_lines(tmp_path / "runs.log") == 2, "первая цель обязана выполниться ровно 2 раза"
    assert _count_lines(tmp_path / "other.log") == 2, "вторая цель обязана выполниться ровно 2 раза"


_STALE_LOG = (
    "[offmain_gc] at first logger test: gc-tracked QWidget/QWindow wrappers alive-or-garbage = 7\n"
    "[offmain_gc] collected 3 objects on thread Thread-9\n"
)

_COND_IMPORT_TEST = """
    from pathlib import Path

    _MARK = Path(__file__).parents[1] / "seen"
    if not _MARK.exists():
        _MARK.write_text("1", encoding="utf-8")
        import PySide6  # noqa: F401

    def test_a():
        pass
"""


def test_probe_not_triggered_is_not_survived(tmp_path: Path) -> None:
    # Контроль: тот же раннер на проекте, где проба срабатывает, даёт survived (см. test_probe_runner_classification).
    cases: dict[str, tuple[list[str], dict[str, str | None], tuple[int, int, int, int, int]]] = {}

    # 1. зелёный тест с PySide6, но в nodeid нет logger_module
    p1 = tmp_path / "p1"
    t1 = _decoy(p1, subdir="other_dir")
    cases["no-logger-module-in-nodeid"] = (["--runs", "1", "--targets", t1, "--cwd", str(p1)], {}, (0, 1, 0, 0, 1))

    # 2. logger_module есть, но PySide6 не загружен: плагин пробы молчит
    p2 = tmp_path / "p2"
    t2 = _decoy(p2, import_pyside=False)
    cases["pyside6-not-loaded"] = (["--runs", "1", "--targets", t2, "--cwd", str(p2)], {}, (0, 1, 0, 0, 1))

    # 3. чужой журнал в CRASHPROBE_LOG с «сработавшей» строкой: раннер ставит свежий файл
    p3 = tmp_path / "p3"
    t3 = _decoy(p3, subdir="other_dir")
    stale = tmp_path / "stale.log"
    stale.write_text(_STALE_LOG, encoding="utf-8")
    cases["stale-log-is-not-reused"] = (
        ["--runs", "1", "--targets", t3, "--cwd", str(p3)],
        {"CRASHPROBE_LOG": str(stale)},
        (0, 1, 0, 0, 1),
    )

    # 4. два прогона: в первом PySide6 загружен (срабатывает), во втором нет; журнал не переиспользуется
    p4 = tmp_path / "p4"
    (p4).mkdir(parents=True)
    (p4 / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    _write(p4, "logger_module/test_x.py", _COND_IMPORT_TEST)
    cases["fresh-log-per-run"] = (
        ["--runs", "2", "--targets", "logger_module/test_x.py", "--cwd", str(p4)],
        {},
        (1, 2, 0, 0, 1),
    )

    failures: list[str] = []
    for name, (args, env_extra, want) in cases.items():
        cwd_arg = args[args.index("--cwd") + 1]
        rc, out = _run_probe(Path(cwd_arg), ["run", "--mode", "offmain_gc", "--skip-axis", *args], env_extra=env_extra)
        found = _SUMMARY.findall(out)
        got = tuple(int(x) for x in found[0][:5]) if len(found) == 1 else None
        if got != want or rc == 0:
            failures.append(f"{name}: want={want} got={got} rc={rc}\n{out}")
    assert not failures, "\n---\n".join(failures)


# ---------------------------------------------------------------------------
# Ось пробы
# ---------------------------------------------------------------------------

_AXIS_HEAD = """
    import os, sys
    from pathlib import Path

    mode = sys.argv[1] if len(sys.argv) > 1 else "?"
    with open(Path(__file__).with_name("calls.log"), "a", encoding="utf-8") as _fh:
        _fh.write(mode + " " + os.environ.get("QT_QPA_PLATFORM", "-") + "\\n")
    if mode not in ("thread", "main"):
        sys.exit(9)
"""


def _axis_script(tmp: Path, thread_body: str, main_body: str, name: str = "repro.py") -> Path:
    src = (
        textwrap.dedent(_AXIS_HEAD)
        + "if mode == 'thread':\n"
        + textwrap.indent(textwrap.dedent(thread_body), "    ")
        + "\nelse:\n"
        + textwrap.indent(textwrap.dedent(main_body), "    ")
        + "\n"
    )
    return _write(tmp, name, src)


_CRASH_CODE = "os._exit(3221225477)\n"
_SURVIVE = "print('SURVIVED main')\nsys.exit(0)\n"

_AXIS_CASES = [
    # id, thread_body, main_body, ожидаемая строка, rc
    pytest.param(_CRASH_CODE, _SURVIVE, "axis: alive", 0, id="alive-thread-crashes-by-code"),
    pytest.param(
        "sys.stderr.write('Fatal Python error: boom\\n')\nsys.exit(1)\n",
        _SURVIVE, "axis: alive", 0, id="alive-thread-crashes-by-text-rc1",
    ),
    pytest.param(
        "sys.exit(0)\n", _SURVIVE,
        "axis: dead (thread crashed 0/2, main survived 2/2)", 2, id="dead-thread-does-not-crash",
    ),
    pytest.param(
        _CRASH_CODE, "os._exit(3221225477)\n",
        "axis: dead (thread crashed 2/2, main survived 0/2)", 2, id="dead-main-crashes",
    ),
    pytest.param(
        _CRASH_CODE, "sys.exit(0)\n",
        "axis: dead (thread crashed 2/2, main survived 0/2)", 2, id="dead-main-rc0-without-survived-text",
    ),
    pytest.param(
        _CRASH_CODE, "print('SURVIVED main')\nsys.exit(1)\n",
        "axis: dead (thread crashed 2/2, main survived 0/2)", 2, id="dead-main-survived-text-but-rc1",
    ),
    pytest.param(
        "m = Path(__file__).with_name('thread_seen')\n"
        "if m.exists():\n    sys.exit(0)\n"
        "m.write_text('1')\nos._exit(3221225477)\n",
        _SURVIVE,
        "axis: dead (thread crashed 1/2, main survived 2/2)", 2, id="dead-thread-crashes-only-once",
    ),
]  # fmt: skip


@pytest.mark.parametrize(("thread_body", "main_body", "want_line", "want_rc"), _AXIS_CASES)
def test_probe_axis_alive_and_dead(
    tmp_path: Path, thread_body: str, main_body: str, want_line: str, want_rc: int
) -> None:
    script = _axis_script(tmp_path, thread_body, main_body)
    rc, out = _run_probe(
        tmp_path,
        ["axis", "--runs", "2", "--script", str(script)],
        env_extra={"QT_QPA_PLATFORM": None},
    )
    lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("axis:")]
    assert lines == [want_line], out
    assert rc == want_rc, out
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines()
    # каждый режим запущен ровно runs раз, аргумент — слово thread / main, платформа offscreen
    assert sorted(calls) == ["main offscreen"] * 2 + ["thread offscreen"] * 2, calls


def test_probe_run_with_default_axis_is_consistent(tmp_path: Path) -> None:
    """Без --skip-axis набор запускается ТОЛЬКО при живой оси (штатный репродуктор не подменить).

    Слабая проверка: ветка выбирается платформой. Мёртвая ось: слова 'ось не живая', код 2,
    итоговой строки и прогонов набора нет. Живая: итоговая строка и survived 1/1.
    """
    target = _decoy(tmp_path)
    rc, out = _run_probe(
        tmp_path,
        ["run", "--mode", "offmain_gc", "--runs", "1", "--targets", target, "--cwd", str(tmp_path)],
    )
    if "ось не живая" in out:
        assert rc == 2, out
        assert not _SUMMARY.search(out), out
        assert _count_lines(tmp_path / "runs.log") == 0, "набор не должен запускаться при мёртвой оси"
    else:
        assert _summary(out)[:5] == (1, 1, 0, 0, 0), out
        assert rc == 0, out
        assert _count_lines(tmp_path / "runs.log") == 1, out


# ---------------------------------------------------------------------------
# Штатный раннер без PYTHONPATH
# ---------------------------------------------------------------------------


def test_runner_works_without_pythonpath() -> None:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTEST_ADDOPTS", None)
    env.update({"PYTHONUTF8": "1", "QT_QPA_PLATFORM": "offscreen"})
    rc, out = _run(
        [sys.executable, "scripts/run_framework_tests.py", "base_manager/tests", "-q"],
        cwd=REPO_ROOT,
        env=env,
        timeout=600,
    )
    assert rc == 0, out[-3000:]
    assert REPORT_TITLE in out, out[-3000:]
