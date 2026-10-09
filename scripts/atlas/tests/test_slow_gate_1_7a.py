"""Приёмка Task 1.7a: маркер `slow` пропускается по умолчанию, job `atlas` в CI (RED до кода).

Purpose: слепая приёмка A1-A6 из plans/2026-10-04_atlas/tasks/1.7a.md. A1-A4 гоняют
    СИНТЕТИЧЕСКИЙ файл (тест с `@pytest.mark.slow`, без маркера и с параметризацией
    id `slow`) подпроцессом pytest с загруженными хуками conftest.py
    (`-p scripts.atlas.tests.conftest`); три настоящих медленных теста не исполняются.
    A5 собирает (--collect-only) настоящий каталог по `-m slow`. A6 читает
    `.github/workflows/ci.yml` как YAML.
Public API: нет (модуль тестов).
Stability: lite

Env подпроцесса задаётся явно: режимы «без env» идут с удалённым `ATLAS_SLOW`
(CI гоняет этот самый файл с `ATLAS_SLOW=1`), режим env выставляет его сам.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

__all__ = []

_ROOT = Path(__file__).resolve().parents[3]
_CI_YML = _ROOT / ".github" / "workflows" / "ci.yml"
_CALL_DEADLINE_S = 25.0

_SYNTHETIC = """\
import pytest


@pytest.mark.slow
def test_marked():
    assert True


def test_plain():
    assert True


@pytest.mark.parametrize("speed", ["fast", "slow"])
def test_param(speed):
    assert speed in ("fast", "slow")
"""

# режим -> (дополнительные аргументы pytest, значение ATLAS_SLOW или None = ключ удалён)
_MODES: dict[str, tuple[tuple[str, ...], str | None]] = {
    "default": ((), None),
    "flag": (("--atlas-slow",), None),
    "env": ((), "1"),
    "not_slow": (("-m", "not slow"), None),
    "only_slow": (("-m", "slow"), None),
}

_SLOW_NODE_IDS = {
    "scripts/atlas/tests/test_views_pinned.py::test_card_on_origin_main_pin",
    "scripts/atlas/tests/test_reference_pinned.py::test_ref_on_origin_main_pin",
    "scripts/atlas/tests/test_review_1_6c.py::test_pin_p1_findings_are_visible_in_ref_and_card",
}


@dataclass
class Outcome:
    """Итог одного подпроцесса pytest: исходы по имени теста + сырой вывод."""

    returncode: int
    stdout: str
    stderr: str
    results: dict[str, tuple[str, str]] = field(default_factory=dict)  # имя -> (исход, причина)

    def describe(self) -> str:
        return f"rc={self.returncode}\n--- stdout ---\n{self.stdout}\n--- stderr ---\n{self.stderr}"

    def status(self, name: str) -> str:
        """passed | skipped | failed | absent (не исполнялся: deselected / не собран)."""
        return self.results.get(name, ("absent", ""))[0]

    def reason(self, name: str) -> str:
        return self.results.get(name, ("absent", ""))[1]

    def deselected(self) -> int:
        match = re.search(r"(\d+) deselected", self.stdout)
        return int(match.group(1)) if match else 0


def _clean_env(atlas_slow: str | None) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("ATLAS_SLOW", None)
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    if atlas_slow is not None:
        env["ATLAS_SLOW"] = atlas_slow
    env["PYTHONPATH"] = str(_ROOT)
    env["PYTHONUTF8"] = "1"
    return env


def _call(argv: list[str], cwd: Path, atlas_slow: str | None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=_clean_env(atlas_slow),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CALL_DEADLINE_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"подпроцесс завис: нет ответа за {_CALL_DEADLINE_S} с: {argv}")


def _run_synthetic(workdir: Path, extra: tuple[str, ...], atlas_slow: str | None) -> Outcome:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "test_synthetic_slow.py").write_text(_SYNTHETIC, encoding="utf-8")
    junit = workdir / "junit.xml"
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "test_synthetic_slow.py",
        "-p",
        "scripts.atlas.tests.conftest",
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=",
        "-o",
        "markers=slow: synthetic",
        "--junitxml",
        str(junit),
        "-q",
        *extra,
    ]
    proc = _call(argv, workdir, atlas_slow)
    results: dict[str, tuple[str, str]] = {}
    if junit.exists():
        for case in ET.parse(junit).getroot().iter("testcase"):
            name = case.get("name", "")
            skipped = case.find("skipped")
            if skipped is not None:
                results[name] = ("skipped", skipped.get("message", ""))
            elif case.find("failure") is not None or case.find("error") is not None:
                results[name] = ("failed", "")
            else:
                results[name] = ("passed", "")
    return Outcome(proc.returncode, proc.stdout, proc.stderr, results)


class _Runs:
    """Кэш прогонов по режимам: каждый подпроцесс исполняется один раз на модуль."""

    def __init__(self, base: Path) -> None:
        self._base = base
        self._cache: dict[str, Outcome] = {}

    def get(self, mode: str) -> Outcome:
        if mode not in self._cache:
            extra, atlas_slow = _MODES[mode]
            self._cache[mode] = _run_synthetic(self._base / mode, extra, atlas_slow)
        return self._cache[mode]


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> _Runs:
    return _Runs(tmp_path_factory.mktemp("slow_gate"))


def _expect(outcome: Outcome, name: str, status: str) -> None:
    got = outcome.status(name)
    assert got == status, f"{name}: ожидали {status}, получили {got}\n{outcome.describe()}"


# --------------------------------------------------------------------------- A1


def test_a1_default_run_skips_slow_test(runs: _Runs) -> None:
    _expect(runs.get("default"), "test_marked", "skipped")


def test_a1_default_run_skip_reason_names_atlas_slow_env(runs: _Runs) -> None:
    out = runs.get("default")
    _expect(out, "test_marked", "skipped")
    assert "ATLAS_SLOW=1" in out.reason("test_marked"), f"причина: {out.reason('test_marked')!r}\n{out.describe()}"


# --------------------------------------------------------------------------- A2


def test_a2_atlas_slow_flag_runs_slow_test(runs: _Runs) -> None:
    _expect(runs.get("flag"), "test_marked", "passed")


def test_a2_atlas_slow_env_runs_slow_test(runs: _Runs) -> None:
    _expect(runs.get("env"), "test_marked", "passed")


# --------------------------------------------------------------------------- A3


def test_a3_explicit_not_slow_deselects_slow_test_not_skips(runs: _Runs) -> None:
    out = runs.get("not_slow")
    _expect(out, "test_marked", "absent")  # ни passed, ни skipped
    assert out.deselected() == 1, out.describe()


def test_a3_explicit_slow_runs_slow_test(runs: _Runs) -> None:
    _expect(runs.get("only_slow"), "test_marked", "passed")


# --------------------------------------------------------------------------- A4


@pytest.mark.parametrize("mode", ["default", "flag", "env", "not_slow"])
def test_a4_unmarked_test_runs_in_every_mode(runs: _Runs, mode: str) -> None:
    _expect(runs.get(mode), "test_plain", "passed")


def test_a4_unmarked_test_is_deselected_under_explicit_slow(runs: _Runs) -> None:
    out = runs.get("only_slow")
    _expect(out, "test_plain", "absent")
    assert out.deselected() == 3, out.describe()  # test_plain + два параметра


@pytest.mark.parametrize("mode", ["default", "flag", "env", "not_slow"])
@pytest.mark.parametrize("name", ["test_param[fast]", "test_param[slow]"])
def test_a4_param_id_slow_without_marker_is_never_skipped(runs: _Runs, mode: str, name: str) -> None:
    _expect(runs.get(mode), name, "passed")


# --------------------------------------------------------------------------- A5


def test_a5_slow_marker_is_registered_and_sits_on_exactly_three_tests() -> None:
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "scripts/atlas/tests",
        "-m",
        "slow",
        "--strict-markers",
        "--collect-only",
        "-q",  # при addopts="" -q даёт node id; -qq дал бы «файл: N» (корневой addopts -v гасит один -q)
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=",
    ]
    proc = _call(argv, _ROOT, None)
    ids = {line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if "::" in line}
    detail = f"rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert proc.returncode == 0, detail
    assert ids == _SLOW_NODE_IDS, detail


# --------------------------------------------------------------------------- A6


def _load_job() -> dict[str, Any]:
    workflow = yaml.safe_load(_CI_YML.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs", {})
    assert "atlas" in jobs, f"в ci.yml нет job `atlas`; есть: {sorted(jobs)}"
    return jobs["atlas"]


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return list(job.get("steps", []))


def _env_of(job: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    return {**(job.get("env") or {}), **(step.get("env") or {})}


def _step_text(step: dict[str, Any]) -> str:
    """run + if + значения env шага: всё, где может жить логика выбора базы."""
    env = step.get("env") or {}
    return "\n".join([str(step.get("run", "")), str(step.get("if", "")), *(str(v) for v in env.values())])


def _pytest_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        s for s in _steps(job) if "pytest" in str(s.get("run", "")) and "scripts/atlas/tests" in str(s.get("run", ""))
    ]


def _check_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in _steps(job) if re.search(r"scripts\.atlas check\b", str(s.get("run", "")))]


def _check_invocations(job: dict[str, Any]) -> list[str]:
    """Аргументы каждого вызова `python -m scripts.atlas check ...` (до `;`, `&&` или конца строки)."""
    found: list[str] = []
    for step in _check_steps(job):
        for match in re.finditer(r"scripts\.atlas check\b([^;\n&|]*)", str(step.get("run", ""))):
            found.append(match.group(1).strip())
    return found


def test_a6_ci_has_job_atlas() -> None:
    _load_job()


def test_a6_atlas_checkout_has_full_history() -> None:
    checkouts = [s for s in _steps(_load_job()) if str(s.get("uses", "")).startswith("actions/checkout")]
    assert checkouts, "в job atlas нет шага actions/checkout"
    depth = (checkouts[0].get("with") or {}).get("fetch-depth")
    assert str(depth) == "0" and not isinstance(depth, bool), f"fetch-depth: {depth!r}"


def test_a6_atlas_pytest_step_sets_atlas_slow_to_one() -> None:
    job = _load_job()
    steps = _pytest_steps(job)
    assert steps, "в job atlas нет шага pytest scripts/atlas/tests"
    value = _env_of(job, steps[0]).get("ATLAS_SLOW")
    assert value == "1" and isinstance(value, str), f"ATLAS_SLOW: {value!r}"


def test_a6_atlas_pytest_step_has_no_m_or_k_selection() -> None:
    steps = _pytest_steps(_load_job())
    assert steps, "в job atlas нет шага pytest scripts/atlas/tests"
    tokens = str(steps[0]["run"]).split()
    bad = [
        tok
        for i, tok in enumerate(tokens)
        if (tok.startswith("-k") or tok.startswith("-m"))
        and not tok.startswith("--")
        and not (tok == "-m" and i > 0 and tokens[i - 1].startswith("python"))  # `python -m pytest`
    ]
    assert not bad, f"в run шага pytest найден отбор тестов: {bad}"


def test_a6_atlas_check_on_push_uses_event_before_as_base() -> None:
    job = _load_job()
    steps = _check_steps(job)
    assert steps, "в job atlas нет шага `python -m scripts.atlas check`"
    with_base = [arg for arg in _check_invocations(job) if "--base" in arg]
    assert with_base, f"нет вызова check с --base: {_check_invocations(job)}"
    value = with_base[0].split("--base", 1)[1].strip().strip("=").split()[0].strip("\"'")
    env = _env_of(job, steps[0])
    var = re.fullmatch(r"\$\{?(\w+)\}?", value)
    resolved = str(env.get(var.group(1), "")) if var else value
    assert "github.event.before" in resolved, f"--base {value!r} не ведёт к github.event.before (env: {env})"
    gate = "\n".join(_step_text(s) for s in steps)
    assert "github.event_name" in gate and "push" in gate, "выбор базы не привязан к событию push"


def test_a6_atlas_check_off_push_has_no_base() -> None:
    job = _load_job()
    invocations = _check_invocations(job)
    assert invocations, "в job atlas нет шага `python -m scripts.atlas check`"
    assert any("--base" not in arg for arg in invocations), f"нет вызова check без --base: {invocations}"


def test_a6_atlas_job_never_pins_base_origin_main() -> None:
    job = _load_job()
    assert _steps(job), "в job atlas нет шагов"
    runs = "\n".join(str(s.get("run", "")) for s in _steps(job))
    assert "--base origin/main" not in runs, runs


def test_a6_atlas_runs_index_check() -> None:
    runs = [str(s.get("run", "")) for s in _steps(_load_job())]
    assert any(re.search(r"scripts\.atlas index --check\b", r) for r in runs), runs


def test_a6_atlas_job_and_steps_are_never_continue_on_error() -> None:
    job = _load_job()
    assert _steps(job), "в job atlas нет шагов"
    offenders = [job.get("continue-on-error")] + [s.get("continue-on-error") for s in _steps(job)]
    assert all(v in (None, False, "false") for v in offenders), offenders
