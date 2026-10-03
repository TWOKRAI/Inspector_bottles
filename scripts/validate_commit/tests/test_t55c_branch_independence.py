"""Task 5.5c — набор test_validate_commit.py не зависит от текущей ветки / HEAD.

Приёмка: «test_validate_commit.py не зависит от текущей ветки: зелёный на
detached HEAD и на ветке с планом».

Механизм. Валидатор находит репозиторий по CWD (`find_repo_root`), ветку — через
`git symbolic-ref` (`current_branch`), план — по слагу ветки (`plan_for_branch`).
Поэтому существующий файл тестов прогоняется подпроцессом pytest с CWD внутри
одноразового git-репозитория: валидатор видит именно его, а не рабочее дерево
разработчика.

Одноразовый репозиторий: один коммит с `plans/<slug>.md`, ветка `feat/<slug>`
(вариант «ветка с планом») и тот же репозиторий в detached HEAD (вариант-контроль).
Ожидаемые значения — литералы: ровно эти два теста должны быть PASSED.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SLUG = "t55c-demo"
_VALIDATOR_TESTS = Path(__file__).resolve().parent / "test_validate_commit.py"
_MUST_PASS = (
    "test_single_line_trailers_ok",
    "test_body_paragraph_not_swallowed_as_trailers",
)


def _clean_env() -> dict[str, str]:
    """Окружение без GIT_*: переменные хука/родительского git не должны указывать на чужой репозиторий."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.hooksPath=", *args],
        cwd=repo,
        env=_clean_env(),
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _make_repo(root: Path, *, detached: bool) -> Path:
    """Репозиторий с одним коммитом, содержащим plans/<slug>.md; ветка feat/<slug> или detached HEAD."""
    repo = root / ("detached" if detached else "planbranch")
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "checkout", "-q", "-b", f"feat/{_SLUG}")
    (repo / "plans").mkdir()
    (repo / "plans" / f"{_SLUG}.md").write_text("# План\n", encoding="utf-8")
    _git(repo, "add", "plans")
    _git(repo, "commit", "-q", "-m", "init")
    if detached:
        _git(repo, "checkout", "-q", "--detach")
    return repo


def _run_validator_tests_in(repo: Path) -> subprocess.CompletedProcess[str]:
    """Два существующих теста валидатора (по node id), CWD = одноразовый репозиторий.

    Именно два, а не весь файл: test_wrapped_*_value в этом дереве красны по
    независимой причине (parse_message без фолдинга) и замусорили бы вердикт о ветке.
    """
    empty_ini = repo / "_empty_pytest.ini"
    empty_ini.write_text("[pytest]\n", encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *(f"{_VALIDATOR_TESTS}::{name}" for name in _MUST_PASS),
            "-v",
            "--tb=short",
            "-p",
            "no:cacheprovider",
            "-c",
            str(empty_ini),
            f"--rootdir={repo}",
        ],
        cwd=repo,
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _assert_suite_green(proc: subprocess.CompletedProcess[str]) -> None:
    out = proc.stdout + proc.stderr
    failed = " FAILED" in out or " ERROR" in out or proc.returncode != 0
    if failed:
        # pytest.fail, а не assert: assert-сообщение pytest обрезает, а причина (требование Refs) в хвосте.
        refs_lines = [ln.strip() for ln in out.splitlines() if "Refs:" in ln and "missing" in ln]
        pytest.fail(
            f"тесты test_validate_commit.py красны в одноразовом репозитории "
            f"(returncode={proc.returncode}); validator demands: {refs_lines[:1]}\n"
            f"{out[-2500:]}",
            pytrace=False,
        )
    for name in _MUST_PASS:
        assert f"{name} PASSED" in out, f"{name} не PASSED:\n{out[-2500:]}"


@pytest.fixture
def plan_branch_repo(tmp_path: Path) -> Path:
    return _make_repo(tmp_path, detached=False)


@pytest.fixture
def detached_repo(tmp_path: Path) -> Path:
    return _make_repo(tmp_path, detached=True)


def test_fixture_plan_branch_really_arms_refs_gate(plan_branch_repo: Path) -> None:
    """Контроль стенда: в репозитории «ветка с планом» валидатор действительно требует Refs.

    Без этого зелёный прогон ниже ничего не доказывал бы — стенд мог бы не
    «заряжать» гейт вовсе.
    """
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from validate_commit import validate;"
        "r = validate('docs(x): тема\\n\\nWhy: причина\\nLayer: tests');"
        "print('OK=' + str(r.ok)); print('ERRORS=' + repr(r.errors))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, str(_VALIDATOR_TESTS.parents[1])],
        cwd=plan_branch_repo,
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "OK=False" in proc.stdout, proc.stdout + proc.stderr
    assert "Refs" in proc.stdout, proc.stdout


def test_fixture_detached_head_does_not_arm_refs_gate(detached_repo: Path) -> None:
    """Контроль стенда: на detached HEAD тот же коммит-месседж проходит без Refs."""
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from validate_commit import validate;"
        "r = validate('docs(x): тема\\n\\nWhy: причина\\nLayer: tests');"
        "print('OK=' + str(r.ok))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, str(_VALIDATOR_TESTS.parents[1])],
        cwd=detached_repo,
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "OK=True" in proc.stdout, proc.stdout + proc.stderr


def test_validator_suite_green_on_detached_head(detached_repo: Path) -> None:
    _assert_suite_green(_run_validator_tests_in(detached_repo))


def test_validator_suite_green_on_branch_with_plan(plan_branch_repo: Path) -> None:
    """Главное: на ветке feat/<slug> при существующем plans/<slug>.md набор не зависит от ветки."""
    _assert_suite_green(_run_validator_tests_in(plan_branch_repo))
