"""Тесты опасностей формы итога: CRLF, маркер в середине строки, BOM, версия адаптера, хук (Task 1.9a).

Purpose: тесты автора по REDS «Developer» брифа plans/2026-10-04_atlas/tasks/1.9a.md: каждая гарантия имеет тест,
    краснеющий при её снятии. Парсер `result_form` вызывается напрямую (чистая функция), CLI и pack — через `atlas`
    conftest, хук — Git Bash с таймаутом.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидаемые значения — литералы. Хук запускается копией дерева или обёрткой `CLAUDE_PYTHON_BIN`, чтобы воспроизвести
сбой импорта и гонку с `autofix-text.sh` без ожидания реальной гонки.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas import result_form
from scripts.atlas.adapters import plans as plans_adapter
from scripts.atlas.tests.conftest import GitRepo, RepoFactory

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_HOOK = _ROOT / ".claude" / "plugins" / "dev" / "hooks" / "lint-result.sh"
_PYTHON_BIN = _ROOT / ".claude" / "plugins" / "core" / "hooks" / "_lib" / "python-bin.sh"

_GOOD = (
    "# Task 1.1 — итог\n\n## Сделано\n- а\n\n## Осталось\n- нет\n\n## Не проверено\n- б\n\n## Файлы\n- в\n\n"
    "## SHA\n- abc1234 тема\n\n## Инъекции\n| инъекция | предсказано красных | наблюдалось | тест |\n"
    "|---|---|---|---|\n| нет | 0 | 0 | — |\n\n## Кому передано\n- лиду\n"
)
# нет «## Осталось» и «## Файлы»
_BAD = _GOOD.replace("## Осталось\n- нет\n\n", "").replace("## Файлы\n- в\n\n", "")
_BAD_LINT = ["нет раздела «## Осталось»", "нет раздела «## Файлы»"]

# все три формы раздела: `## T`, `**T:**`, `**T.**`
_MIXED = "# Итог\n\n**Осталось:** x\n  продолжение\n\n## Не проверено\n- б\n\n**Для следующего брифа.** в\n"


def _crlf(text: str) -> str:
    return text.replace("\n", "\r\n")


# ---------------------------------------------------------------- CRLF = LF


def test_crlf_equals_lf_in_section_and_lint() -> None:
    for text in (_MIXED, _GOOD, _BAD):
        lf, crlf = text.split("\n"), _crlf(text).split("\n")
        for title in (*result_form.REQUIRED, *result_form.TAILS):
            assert result_form.section(crlf, title) == result_form.section(lf, title), title
        assert result_form.lint(_crlf(text)) == result_form.lint(text)
    assert result_form.lint(_crlf(_BAD)) == _BAD_LINT
    assert result_form.section(_crlf(_MIXED).split("\n"), "Осталось") == ("**Осталось:**", ["x продолжение"])


def test_crlf_file_lints_like_lf_through_cli(tmp_path: Path, atlas: Any) -> None:
    (tmp_path / "bad.result.md").write_bytes(_crlf(_BAD).encode("utf-8"))
    res = atlas(GitRepo(tmp_path), "lint-result", "bad.result.md")
    assert (res.code, res.out.splitlines(), res.err) == (
        1,
        ["  нет раздела «## Осталось»", "  нет раздела «## Файлы»", "lint-result: нарушений 2"],
        "",
    )


def test_bom_before_first_heading_is_stripped(tmp_path: Path, atlas: Any) -> None:
    """Файл с BOM, первая строка — `## Сделано`: без utf-8-sig раздел «Сделано» не нашёлся бы."""
    text = _GOOD.split("\n", 2)[2]
    assert text.startswith("## Сделано\n")
    (tmp_path / "bom.result.md").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    res = atlas(GitRepo(tmp_path), "lint-result", "bom.result.md")
    assert (res.code, res.out.splitlines(), res.err) == (0, ["lint-result: нарушений 0"], "")


_MODULES = (
    'version: 1\nmodules:\n  - id: m\n    paths: ["m/"]\n    layer: framework\n    tier: null\n    docs: []\n'
    "    parent: null\n"
)


def _tail_block(lines: list[str], task: str) -> list[str]:
    heading = next(index for index, line in enumerate(lines) if line.startswith(f"  {task} ("))
    block: list[str] = []
    for line in lines[heading + 1 :]:
        if not line.startswith("    "):
            break
        block.append(line)
    return block


def test_crlf_result_prints_the_same_tails_as_lf_in_pack(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repo_factory.create("crlf")
    repo.git("config", "core.autocrlf", "false")  # иначе git add сам превратит CRLF в LF и тест ничего не проверит
    (repo.path / ".git" / "info" / "exclude").write_text("data/\n", encoding="utf-8")
    done = "[DONE 2026-10-01]"
    repo.write("modules.yaml", _MODULES)
    rows = f"- Task 1.1: one {done}\n- Task 1.2: two {done}\n- Task 1.3: three [PENDING]\n"
    plan = "# Alpha\n\n## Порядок выполнения\n\n" + rows
    repo.write("plans/2026-10-01_alpha/plan.md", plan)
    tasks = repo.path / "plans" / "2026-10-01_alpha" / "tasks"
    tasks.mkdir(parents=True)
    tail = "# Итог\n\n**Осталось:** x\n\n## Не проверено\n- б\n\n## Для следующего брифа\n- в\n"
    (tasks / "1.1.result.md").write_bytes(tail.encode("utf-8"))
    (tasks / "1.2.result.md").write_bytes(_crlf(tail).encode("utf-8"))
    for stamp, subject, trailer in (
        ("2026-09-30", "init", None),
        ("2026-10-01", "task 1.1", "Task: alpha#1.1"),
        ("2026-10-02", "task 1.2", "Task: alpha#1.2"),
    ):
        monkeypatch.setenv("GIT_AUTHOR_DATE", f"{stamp}T10:00:00+0000")
        monkeypatch.setenv("GIT_COMMITTER_DATE", f"{stamp}T10:00:00+0000")
        if trailer:
            repo.write(f"m/{subject[-3:]}.py", f"x = '{stamp}'\n")
        repo.commit(subject + (f"\n\n{trailer}" if trailer else ""))
    blob = subprocess.run(
        ["git", "-C", str(repo.path), "show", "HEAD:plans/2026-10-01_alpha/tasks/1.2.result.md"],
        capture_output=True,
        check=True,
        timeout=60,
    ).stdout
    assert b"\r\n" in blob, "предусловие: в blob остался CRLF"

    res = atlas(repo, "pack", "alpha#1.3", "--ref", "main", "--main-ref", "main")
    assert (res.code, res.err) == (0, ""), res.err
    lines = res.out.splitlines()
    expected = ["    Осталось:", "      x", "    Не проверено:", "      - б", "    Для следующего брифа:", "      - в"]
    assert _tail_block(lines, "alpha#1.1") == expected
    assert _tail_block(lines, "alpha#1.2") == expected


# ---------------------------------------------------------------- заголовок `## T` выигрывает у абзаца


def test_heading_wins_over_an_earlier_paragraph() -> None:
    text = "## Сделано\n- x\n**Осталось:** ничего по DESIGN 3\n\n## Осталось\n- хук в plugin.json (О4)\n"
    assert result_form.section(text.split("\n"), "Осталось") == ("## Осталось", ["- хук в plugin.json (О4)"])
    assert not [m for m in result_form.lint(text) if "Осталось" in m]
    # среди абзацев выигрывает первый
    two = ["**Осталось:** первый", "", "**Осталось.** второй"]
    assert result_form.section(two, "Осталось") == ("**Осталось:**", ["первый"])


# ---------------------------------------------------------------- маркер в середине строки — не раздел


def test_marker_in_the_middle_of_a_line_is_not_a_section() -> None:
    lines = ["# Итог", "", "см. **Осталось:** x в другом месте", "- пункт **Осталось.** y", ""]
    assert result_form.section(lines, "Осталось") is None
    text = "\n".join([*lines, "## Не проверено", "- а"])
    assert "нет раздела «## Осталось»" in result_form.lint(text)
    # а тот же маркер в начале строки (после отступа) — раздел
    assert result_form.section(["  **Осталось:** x"], "Осталось") == ("**Осталось:**", ["x"])


# ---------------------------------------------------------------- версия PlansAdapter хеширует result_form.py


def test_plans_adapter_version_tracks_result_form_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    version = plans_adapter.PlansAdapter().version
    assert version >> 48 == 2
    assert version % 2**48 != 0  # хеш посчитан: оба файла читаются
    copy = tmp_path / "result_form.py"
    copy.write_bytes(plans_adapter.RESULT_FORM_PY.read_bytes())
    monkeypatch.setattr(plans_adapter, "RESULT_FORM_PY", copy)
    assert plans_adapter.PlansAdapter().version == version  # хеш — от байт, не от пути
    copy.write_bytes(copy.read_bytes() + b"# x\n")
    changed = plans_adapter.PlansAdapter().version
    assert changed != version
    assert changed >> 48 == 2
    # plans_progress входит в тот же ключ: байты одного result_form.py версию не фиксируют
    progress = tmp_path / "plans_progress.py"
    progress.write_bytes(plans_adapter.PLANS_PROGRESS.read_bytes() + b"# y\n")
    monkeypatch.setattr(plans_adapter, "PLANS_PROGRESS", progress)
    assert plans_adapter.PlansAdapter().version not in (version, changed)


# ---------------------------------------------------------------- хук lint-result.sh


def _git_bash() -> str:
    """Git Bash, а не WSL-`bash` из System32 (subprocess подхватывает тот первым)."""
    git = shutil.which("git")
    for parent in Path(git).resolve().parents if git else []:
        if (parent / "bin" / "bash.exe").is_file():
            return str(parent / "bin" / "bash.exe")
    return "bash"  # POSIX-машина


def _run_hook(hook: Path, file_path: str, env_extra: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update({"PYTHONUTF8": "1", **env_extra})
    payload = {"tool_name": "Write", "tool_input": {"file_path": file_path, "content": "x"}}
    return subprocess.run(
        [_git_bash(), hook.as_posix()],
        input=json.dumps(payload).encode("utf-8"),
        cwd=str(cwd),
        env=env,
        capture_output=True,
        timeout=90,
        check=False,
    )


def _result_file(tmp_path: Path, text: str, name: str = "x.result.md") -> Path:
    folder = tmp_path / "plans" / "2026-10-04_alpha" / "tasks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(text.encode("utf-8"))
    return path


@pytest.mark.skipif(os.name != "nt", reason="обратные слэши в пути — Windows")
def test_hook_accepts_a_backslash_path(tmp_path: Path) -> None:
    bad = _result_file(tmp_path, _BAD)
    assert "\\" in str(bad)
    proc = _run_hook(_HOOK, str(bad), {"CLAUDE_PYTHON_BIN": sys.executable}, tmp_path)
    err = proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == 2, err
    assert "нет раздела «## Осталось»" in err


def test_hook_ignores_a_result_file_outside_plans_tasks(tmp_path: Path) -> None:
    """`*.result.md` вне `plans/**/tasks/`: предфильтр `case` пропускает, отсекает только регулярка пути."""
    folder = tmp_path / "notes"
    folder.mkdir()
    bad = folder / "bad.result.md"
    bad.write_bytes(_BAD.encode("utf-8"))
    proc = _run_hook(_HOOK, bad.as_posix(), {"CLAUDE_PYTHON_BIN": sys.executable}, tmp_path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"", b"")


def test_hook_stays_silent_on_exit_1_without_the_violation_line(tmp_path: Path) -> None:
    """Сбой импорта (`No module named scripts.atlas`) тоже exit 1, но не нарушение формы: хук молчит."""
    fake_root = tmp_path / "noatlas"
    hook = fake_root / ".claude" / "plugins" / "dev" / "hooks" / "lint-result.sh"
    lib = fake_root / ".claude" / "plugins" / "core" / "hooks" / "_lib" / "python-bin.sh"
    hook.parent.mkdir(parents=True)
    lib.parent.mkdir(parents=True)
    shutil.copyfile(_HOOK, hook)
    shutil.copyfile(_PYTHON_BIN, lib)
    bad = _result_file(tmp_path, _BAD)
    env = {"CLAUDE_PYTHON_BIN": sys.executable}
    # предусловие: в копии дерева Атласа нет, линт падает с exit 1 и пустым stdout
    probe = subprocess.run(
        [sys.executable, "-m", "scripts.atlas", "lint-result", str(bad)],
        cwd=str(fake_root),
        env={**{k: v for k, v in os.environ.items() if k != "PYTHONPATH"}, "PYTHONUTF8": "1"},
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert (probe.returncode, probe.stdout) == (1, b""), probe.stderr
    assert b"No module named" in probe.stderr
    proc = _run_hook(hook, bad.as_posix(), env, tmp_path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"", b"")


def _flip_wrapper(tmp_path: Path, target: Path, second: str) -> Path:
    """Обёртка интерпретатора: после первого `-m`-прогона подменяет `target` содержимым `second` (гонка с autofix)."""
    full = tmp_path / "second.md"
    full.write_bytes(second.encode("utf-8"))
    wrapper = tmp_path / "py-flip.sh"
    wrapper.write_bytes(
        (
            "#!/usr/bin/env bash\n"
            f'"{Path(sys.executable).as_posix()}" "$@"\n'
            "rc=$?\n"
            f'if [ "$1" = "-m" ] && [ ! -e "{(tmp_path / "state").as_posix()}" ]; then\n'
            f'  : > "{(tmp_path / "state").as_posix()}"\n'
            f'  cp "{full.as_posix()}" "{target.as_posix()}"\n'
            "fi\n"
            "exit $rc\n"
        ).encode("utf-8")
    )
    wrapper.chmod(0o755)
    return wrapper


def test_hook_ignores_a_violation_that_vanishes_on_the_second_run(tmp_path: Path) -> None:
    """Файл пуст при первом прогоне и полон при втором (autofix-text.sh дописал): хук не сообщает."""
    target = _result_file(tmp_path, "")
    wrapper = _flip_wrapper(tmp_path, target, _GOOD)
    proc = _run_hook(_HOOK, target.as_posix(), {"CLAUDE_PYTHON_BIN": wrapper.as_posix()}, tmp_path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"", b"")
    assert (tmp_path / "state").exists(), "обёртка не сработала: второго прогона не было"


def test_hook_ignores_two_different_violation_outputs(tmp_path: Path) -> None:
    """Оба прогона — нарушения, но разные (файл дописывали): сообщают только при равных выводах."""
    target = _result_file(tmp_path, "")
    wrapper = _flip_wrapper(tmp_path, target, _BAD)
    proc = _run_hook(_HOOK, target.as_posix(), {"CLAUDE_PYTHON_BIN": wrapper.as_posix()}, tmp_path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"", b"")
    assert (tmp_path / "state").exists()
