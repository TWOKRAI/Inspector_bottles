# ruff: noqa: E501  -- литералы-фикстуры планов и ожидания в одну строку, форматтер их не переносит
"""Приёмка Task 2.2 + 2.3 (слепые тесты) по плану plans/2026-10-02_plans-progress-dashboard.md.

(A) scripts/validate.py: шаг `check_plans_progress()` — запуск `plans_progress.py --check --baseline`.
(B) `plans_progress.py --sync-order`: блок прогресса между маркерами в ORDER.md и находки
    `ORDER_BLOCK_STALE` / `ORDER_BLOCK_MISSING` в `--check` только на ветке `main`.

Только наблюдаемый эффект: код возврата, stdout/stderr, байты файлов. Ожидаемые значения — литералы.
Всё, что может зависнуть, ходит через subprocess с timeout.

Договорённости чтения (в плане не уточнены, см. отчёт тестера):
- имя плана в `--json` и в строке блока — без `.md` (`conftest._norm_key` терпит оба);
- без архива строка счётчика всё равно печатается: `в архиве: 0`;
- в строке с нулём задач процента нет: `- <план> — 0 из 0`; при total > 0 процент есть всегда, и `0 из 3 · 0%`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATE_PY = REPO_ROOT / "scripts" / "validate.py"
PROGRESS = REPO_ROOT / "scripts" / "plans_progress" / "plans_progress.py"

CALL_TIMEOUT = 60
BEGIN = "<!-- progress:begin -->"
END = "<!-- progress:end -->"

HEAD = ["# Порядок работ", "", "Текст до блока.  ", "## Прогресс", ""]
TAIL = ["", "## Дальше", "| a | б |", "|---|---|", "| ✓ | ё |"]
STALE = ["- 2026-10-02_x — 9 из 9 · 100%", "", "ручная правка", "в архиве: 7"]

PLAN_X = "# X\n\n## Порядок выполнения\n\n- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n- Task 1.3: c [PENDING]\n"
PLAN_Y = "# Y\n\n## Порядок выполнения\n\n- Task 1.1: a [DONE]\n- Task 1.2: b [DONE]\n"
PLAN_Z = "# Z\n\n## Порядок выполнения\n\n- Task 1.1: a [DONE]\n"
LIVE_LINES = {
    "2026-10-02_x": "- 2026-10-02_x — 1 из 3 · 33%",
    "2026-10-02_y": "- 2026-10-02_y — 2 из 2 · 100%",
}


# ---------------------------------------------------------------- helpers


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, timeout=CALL_TIMEOUT, env=_env())


def _git_ok(cwd: Path, *args: str, ceiling: bool = False) -> bool:
    env = _env()
    if ceiling:
        env["GIT_CEILING_DIRECTORIES"] = str(cwd.parent)
    cp = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, timeout=CALL_TIMEOUT, env=env)
    return cp.returncode == 0


def _init_git_main(root: Path) -> None:
    """git-репозиторий на ветке main с одним коммитом всего дерева."""
    _git(root, "init", "-q")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "tester")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "commit.gpgsign", "false")
    _commit_all(root)


def _commit_all(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "snap")


def _compose(nl: str, head: list[str], block: list[str], tail: list[str], *, final_newline: bool = True) -> str:
    lines = [*head, BEGIN, *block, END, *tail]
    return nl.join(lines) + (nl if final_newline else "")


def _expected_block(live: list[str], archived: int) -> list[str]:
    return [*live, f"в архиве: {archived}"]


def _sync_files(order_text: str) -> dict[str, str]:
    """Два живых плана + один архивный + ORDER.md (+ пустая база для `--check`)."""
    return {
        "plans/2026-10-02_x.md": PLAN_X,
        "plans/2026-10-02_y.md": PLAN_Y,
        "plans/_archive/2026-Q3/2026-07-01_z.md": PLAN_Z,
        "plans/queue/ORDER.md": order_text,
        "plans/queue/progress-baseline.txt": "",
    }


def _order_path(root: Path) -> Path:
    return root / "plans" / "queue" / "ORDER.md"


def _snapshot(root: Path) -> dict[str, bytes | None]:
    snap: dict[str, bytes | None] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if ".git" in rel.parts:
            continue
        snap[rel.as_posix()] = None if p.is_dir() else p.read_bytes()
    return snap


def _out(cp: subprocess.CompletedProcess) -> str:
    return f"{cp.stdout}\n{cp.stderr}"


def _check(root: Path) -> subprocess.CompletedProcess:
    """`--check` в subprocess; GIT_CEILING_DIRECTORIES не даёт git искать репозиторий выше tmp-корня
    (на машине владельца C:/Users/INNOTECH — сам git-репозиторий на main, и «не-git» tmp-каталог им не был)."""
    env = _env()
    env["GIT_CEILING_DIRECTORIES"] = str(root.parent)
    return subprocess.run(
        [
            sys.executable,
            str(PROGRESS),
            "--root",
            str(root),
            "--check",
            "--baseline",
            str(root / "plans" / "queue" / "progress-baseline.txt"),
        ],
        capture_output=True,
        timeout=CALL_TIMEOUT,
        env=env,
        encoding="utf-8",
        errors="replace",
    )


def _assert_sync_ok(cp: subprocess.CompletedProcess) -> None:
    assert "unrecognized arguments" not in cp.stderr, f"--sync-order не реализован: {cp.stderr[:300]!r}"
    assert cp.returncode == 0, (
        f"--sync-order exit {cp.returncode}\nstdout={cp.stdout[:300]!r}\nstderr={cp.stderr[:300]!r}"
    )


def _assert_refused(cp: subprocess.CompletedProcess, *, names: tuple[str, ...]) -> None:
    assert "unrecognized arguments" not in cp.stderr, f"--sync-order не реализован: {cp.stderr[:300]!r}"
    assert cp.returncode == 2, f"ожидался exit 2, получен {cp.returncode}\nstderr={cp.stderr[:300]!r}"
    assert any(n in cp.stderr for n in names), f"stderr не называет {names}: {cp.stderr[:300]!r}"


# ---------------------------------------------------------------- (A) validate.py


class _TimedSubprocess:
    """Подмена `validate.subprocess`: всё как в stdlib, но `run` не виснет дольше 120 с."""

    def __getattr__(self, name):
        return getattr(subprocess, name)

    @staticmethod
    def run(*args, **kwargs):
        kwargs.setdefault("timeout", 120)
        return subprocess.run(*args, **kwargs)


@pytest.fixture(scope="module")
def validate_mod():
    """validate.py из ЭТОГО дерева (по пути файла), а не из случайного sys.path."""
    spec = importlib.util.spec_from_file_location("validate_under_test_phase2", VALIDATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tmp_base(tmp_path: Path, validate_mod, monkeypatch):
    """BASE -> tmp-корень с одним живым планом и пустой базой; errors -> пустой список."""
    root = tmp_path / "base"
    (root / "plans" / "queue").mkdir(parents=True)
    (root / "plans" / "2026-10-02_t.md").write_bytes(
        "# T\n\n## Порядок выполнения\n\n- Task 1.1: a [PENDING]\n".encode()
    )
    (root / "plans" / "queue" / "progress-baseline.txt").write_bytes(b"")
    monkeypatch.setattr(validate_mod, "BASE", root)
    monkeypatch.setattr(validate_mod, "subprocess", _TimedSubprocess())
    monkeypatch.setattr(validate_mod, "errors", [])
    return root


def _write_dup_plan(root: Path) -> None:
    text = "# T\n\n## Порядок выполнения\n\n- Task 1.1: a [PENDING]\n- Task 1.1: a [PENDING]\n"
    (root / "plans" / "2026-10-02_t.md").write_bytes(text.encode("utf-8"))


def test_a1_real_tree_is_green(validate_mod, monkeypatch, capsys):
    monkeypatch.setattr(validate_mod, "errors", [])
    monkeypatch.setattr(validate_mod, "subprocess", _TimedSubprocess())
    validate_mod.check_plans_progress()
    out = capsys.readouterr().out
    assert validate_mod.errors == [], f"errors={validate_mod.errors!r}\nout={out[-600:]}"
    assert "[OK]" in out
    assert "[FAIL]" not in out


def test_a2_clean_tmp_root_is_ok(validate_mod, tmp_base, capsys):
    validate_mod.check_plans_progress()
    out = capsys.readouterr().out
    assert validate_mod.errors == [], f"errors={validate_mod.errors!r}\nout={out[-600:]}"
    assert "[OK]" in out
    assert "[FAIL]" not in out


def test_a3_new_blocking_finding_appends_exactly_one_error(validate_mod, tmp_base, capsys):
    _write_dup_plan(tmp_base)
    validate_mod.errors.append("prior")
    validate_mod.check_plans_progress()
    out = capsys.readouterr().out
    assert len(validate_mod.errors) == 2, f"errors={validate_mod.errors!r}\nout={out[-600:]}"
    assert validate_mod.errors[0] == "prior"
    assert "[FAIL]" in out
    assert "[OK]" not in out


def test_a4_finding_in_baseline_does_not_fail(validate_mod, tmp_base, capsys):
    _write_dup_plan(tmp_base)
    (tmp_base / "plans" / "queue" / "progress-baseline.txt").write_bytes(b"2026-10-02_t:DUP_ID:1.1\n")
    validate_mod.check_plans_progress()
    out = capsys.readouterr().out
    assert validate_mod.errors == [], f"errors={validate_mod.errors!r}\nout={out[-600:]}"
    assert "[OK]" in out


def test_a5_missing_baseline_file_is_an_error(validate_mod, tmp_base, capsys):
    (tmp_base / "plans" / "queue" / "progress-baseline.txt").unlink()
    validate_mod.check_plans_progress()
    out = capsys.readouterr().out
    assert len(validate_mod.errors) == 1, f"errors={validate_mod.errors!r}\nout={out[-600:]}"
    assert "[FAIL]" in out


def test_a6_main_calls_the_step_after_check_adr_sync(validate_mod):
    import inspect

    src = inspect.getsource(validate_mod.main)
    adr = src.find("check_adr_sync()")
    step = src.find("check_plans_progress()")
    assert adr != -1, "main() не вызывает check_adr_sync()"
    assert step != -1, "main() не вызывает check_plans_progress()"
    assert step > adr, "check_plans_progress() должен идти после check_adr_sync()"


COMMAND_PAIRS = [
    (".claude/plugins/dev/commands/ship.md", ".claude/commands/dev/ship.md"),
    (".claude/plugins/dev/commands/plan-status.md", ".claude/commands/dev/plan-status.md"),
]


def _lf_text(rel: str) -> str:
    return (REPO_ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


@pytest.mark.parametrize("rel", [p for pair in COMMAND_PAIRS for p in pair])
def test_a7_command_mentions_the_check(rel):
    assert "plans_progress.py --check" in _lf_text(rel)


@pytest.mark.parametrize(("source", "mirror"), COMMAND_PAIRS)
def test_a7_source_equals_mirror(source, mirror):
    assert _lf_text(source) == _lf_text(mirror)


# ---------------------------------------------------------------- (B) --sync-order


@pytest.mark.parametrize("final_newline", [True, False], ids=["nl-at-eof", "no-nl-at-eof"])
@pytest.mark.parametrize("nl", ["\n", "\r\n"], ids=["LF", "CRLF"])
@pytest.mark.parametrize("stale", [STALE, []], ids=["stale-body", "empty-body"])
def test_b1_sync_rewrites_only_the_block_byte_exact(make_root, progress, plans_json, nl, final_newline, stale):
    root = make_root(_sync_files(_compose(nl, HEAD, stale, TAIL, final_newline=final_newline)))
    recs = plans_json(root)
    live = [n for n, r in recs.items() if not r["archived"]]
    assert sorted(live) == sorted(LIVE_LINES), f"предусловие: живые планы {live}"
    assert sum(1 for r in recs.values() if r["archived"]) == 1, "предусловие: один архивный план"

    cp = progress(root, "--sync-order")
    _assert_sync_ok(cp)

    expected = _compose(nl, HEAD, _expected_block([LIVE_LINES[n] for n in live], 1), TAIL, final_newline=final_newline)
    got = _order_path(root).read_bytes()
    assert got == expected.encode("utf-8"), f"got={got!r}"
    if nl == "\r\n":
        assert got.count(b"\n") == got.count(b"\r\n"), "в CRLF-файле появился голый LF"
    else:
        assert b"\r" not in got, "в LF-файле появился CR"


@pytest.mark.parametrize("nl", ["\n", "\r\n"], ids=["LF", "CRLF"])
def test_b2_sync_is_idempotent(make_root, progress, nl):
    root = make_root(_sync_files(_compose(nl, HEAD, STALE, TAIL)))
    _assert_sync_ok(progress(root, "--sync-order"))
    first = _order_path(root).read_bytes()
    assert first != _compose(nl, HEAD, STALE, TAIL).encode("utf-8"), "предусловие: первый прогон изменил файл"
    _assert_sync_ok(progress(root, "--sync-order"))
    assert _order_path(root).read_bytes() == first


def _single_plan_files(tasks: list[tuple[str, str]], order_text: str) -> dict[str, str]:
    body = "".join(f"- Task {tid}: задача {tid} [{st}]\n" for tid, st in tasks)
    return {
        "plans/2026-10-02_p.md": f"# P\n\n## Порядок выполнения\n\n{body}",
        "plans/queue/ORDER.md": order_text,
    }


def _done_pending(done: int, pending: int) -> list[tuple[str, str]]:
    return [(f"1.{i + 1}", "DONE") for i in range(done)] + [(f"1.{done + i + 1}", "PENDING") for i in range(pending)]


@pytest.mark.parametrize(
    ("tasks", "line"),
    [
        (_done_pending(1, 7), "- 2026-10-02_p — 1 из 8 · 13%"),  # 12.5 -> 13: округление половины вверх, не банковское
        (_done_pending(5, 3), "- 2026-10-02_p — 5 из 8 · 63%"),  # 62.5 -> 63
        (_done_pending(2, 1), "- 2026-10-02_p — 2 из 3 · 67%"),
        (_done_pending(0, 3), "- 2026-10-02_p — 0 из 3 · 0%"),
        ([("1.1", "DONE"), ("1.2", "DEFERRED")], "- 2026-10-02_p — 1 из 1 · 100%"),
        ([("1.1", "DONE"), ("1.2", "SUPERSEDED"), ("1.3", "PENDING")], "- 2026-10-02_p — 1 из 2 · 50%"),
        ([("1.1", "DEFERRED"), ("1.2", "DEFERRED")], "- 2026-10-02_p — 0 из 0"),
        ([], "- 2026-10-02_p — 0 из 0"),
    ],
    ids=["1of8", "5of8", "2of3", "0of3", "done+deferred", "done+superseded+pending", "all-deferred", "no-tasks"],
)
def test_b4_line_format_and_rounding(make_root, progress, tasks, line):
    root = make_root(_single_plan_files(tasks, _compose("\n", HEAD, STALE, TAIL)))
    _assert_sync_ok(progress(root, "--sync-order"))
    expected = _compose("\n", HEAD, [line, "в архиве: 0"], TAIL)
    assert _order_path(root).read_bytes() == expected.encode("utf-8")


MARKER_CASES = {
    "absent": [*HEAD, *TAIL],
    "only-begin": [*HEAD, BEGIN, *STALE, *TAIL],
    "only-end": [*HEAD, *STALE, END, *TAIL],
    "end-before-begin": [*HEAD, END, *STALE, BEGIN, *TAIL],
    "begin-twice": [*HEAD, BEGIN, *STALE, BEGIN, *STALE, END, *TAIL],
    "end-twice": [*HEAD, BEGIN, *STALE, END, *TAIL, END],
    "two-blocks": [*HEAD, BEGIN, END, *TAIL, BEGIN, END],
    "begin-embedded-in-prose": [*HEAD, "текст " + BEGIN + " текст", *STALE, END, *TAIL],
}


@pytest.mark.parametrize("lines", list(MARKER_CASES.values()), ids=list(MARKER_CASES))
def test_b5_bad_markers_refuse_and_leave_bytes_alone(make_root, progress, lines):
    root = make_root(_sync_files("\n".join(lines) + "\n"))
    before = _order_path(root).read_bytes()
    snap = _snapshot(root)
    cp = progress(root, "--sync-order")
    _assert_refused(cp, names=("progress:begin", "progress:end"))
    assert _order_path(root).read_bytes() == before
    assert _snapshot(root) == snap


def test_b6_missing_order_file_refuses_and_creates_nothing(make_root, progress):
    files = _sync_files("")
    del files["plans/queue/ORDER.md"]
    root = make_root(files)
    snap = _snapshot(root)
    cp = progress(root, "--sync-order")
    _assert_refused(cp, names=("progress:begin", "progress:end", "ORDER"))
    assert _snapshot(root) == snap
    assert not _order_path(root).exists()


def test_b6_explicit_order_path_is_the_one_rewritten(make_root, progress, plans_json):
    custom = _compose("\n", HEAD, STALE, TAIL)
    files = _sync_files("не тронуть: это ORDER по умолчанию, маркеров в нём нет\n")
    files["elsewhere/my_order.md"] = custom
    root = make_root(files)
    default_before = _order_path(root).read_bytes()
    cp = progress(root, "--order", str(root / "elsewhere" / "my_order.md"), "--sync-order")
    _assert_sync_ok(cp)
    expected = _compose("\n", HEAD, _expected_block(list(LIVE_LINES.values()), 1), TAIL)
    got = (root / "elsewhere" / "my_order.md").read_bytes()
    assert sorted(got.decode("utf-8").splitlines()) == sorted(expected.splitlines()), f"got={got!r}"
    assert _order_path(root).read_bytes() == default_before


def test_b9_sync_touches_only_order_md(make_root, progress):
    files = _sync_files(_compose("\n", HEAD, STALE, TAIL))
    files["plans/queue/backlog.md"] = "# backlog\n"
    files["plans/README.md"] = "# plans\n"
    root = make_root(files)
    before = _snapshot(root)
    _assert_sync_ok(progress(root, "--sync-order"))
    after = _snapshot(root)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert changed == ["plans/queue/ORDER.md"], f"изменились: {changed}"


def test_b10_sync_with_json_keeps_stdout_valid_json(make_root, progress):
    root = make_root(_sync_files(_compose("\n", HEAD, STALE, TAIL)))
    cp = progress(root, "--sync-order", "--json")
    _assert_sync_ok(cp)
    data = json.loads(cp.stdout)
    assert isinstance(data, list)
    names = sorted(str(rec["plan"]).removesuffix(".md") for rec in data)
    assert names == ["2026-07-01_z", "2026-10-02_x", "2026-10-02_y"]
    assert "2026-10-02_x — 1 из 3 · 33%" in _order_path(root).read_text(encoding="utf-8"), "блок не обновлён"


# ---------------------------------------------------------------- (B) --check: дрейф блока только на main


def test_b7_stale_block_on_main_fails_check(make_root, progress):
    root = make_root(_sync_files(_compose("\n", HEAD, STALE, TAIL)))
    _init_git_main(root)
    cp = _check(root)
    assert cp.returncode == 0, f"exit {cp.returncode}\n{_out(cp)[-500:]}"  # Task 2.5: блок — info
    assert any(ln.startswith("ORDER_BLOCK_STALE ") and " info " in ln for ln in _out(cp).splitlines()), _out(cp)[-500:]


def test_b7_fresh_block_on_main_passes_check(make_root, progress):
    root = make_root(_sync_files(_compose("\n", HEAD, STALE, TAIL)))
    _init_git_main(root)
    _assert_sync_ok(progress(root, "--sync-order"))
    _commit_all(root)
    cp = _check(root)
    assert cp.returncode == 0, f"exit {cp.returncode}\n{_out(cp)[-500:]}"
    assert "ORDER_BLOCK_" not in _out(cp)


def test_b7_status_change_after_sync_makes_block_stale(make_root, progress):
    root = make_root(_sync_files(_compose("\n", HEAD, STALE, TAIL)))
    _init_git_main(root)
    _assert_sync_ok(progress(root, "--sync-order"))
    _commit_all(root)
    assert _check(root).returncode == 0, "предусловие: свежий блок проходит"
    plan = root / "plans" / "2026-10-02_x.md"
    plan.write_bytes(plan.read_bytes().replace(b"Task 1.2: b [PENDING]", b"Task 1.2: b [DONE]"))
    cp = _check(root)
    assert cp.returncode == 0, f"exit {cp.returncode}\n{_out(cp)[-500:]}"  # Task 2.5: блок — info
    assert any(ln.startswith("ORDER_BLOCK_STALE ") and " info " in ln for ln in _out(cp).splitlines()), _out(cp)[-500:]


def test_b7_text_outside_the_block_is_not_drift(make_root, progress):
    root = make_root(_sync_files(_compose("\n", HEAD, STALE, TAIL)))
    _init_git_main(root)
    _assert_sync_ok(progress(root, "--sync-order"))
    order = _order_path(root)
    order.write_bytes(order.read_bytes().replace("Текст до блока.".encode(), "Другой текст до блока.".encode()))
    order.write_bytes(order.read_bytes() + "\nДописано в хвост.\n".encode())
    cp = _check(root)
    assert cp.returncode == 0, f"exit {cp.returncode}\n{_out(cp)[-500:]}"
    assert "ORDER_BLOCK_" not in _out(cp)


def test_b7_missing_markers_on_main_fail_check(make_root, progress):
    root = make_root(_sync_files("\n".join([*HEAD, *TAIL]) + "\n"))
    _init_git_main(root)
    cp = _check(root)
    assert cp.returncode == 0, f"exit {cp.returncode}\n{_out(cp)[-500:]}"  # Task 2.5: блок — info
    assert any(ln.startswith("ORDER_BLOCK_MISSING ") and " info " in ln for ln in _out(cp).splitlines()), _out(cp)[
        -500:
    ]


_BLOCK_STATES = {
    "stale": ("\n".join(_compose("\n", HEAD, STALE, TAIL).splitlines()) + "\n", "ORDER_BLOCK_STALE"),
    "missing": ("\n".join([*HEAD, *TAIL]) + "\n", "ORDER_BLOCK_MISSING"),
}


@pytest.mark.parametrize("state", list(_BLOCK_STATES))
@pytest.mark.parametrize("where", ["feature-branch", "detached-head", "not-a-git-dir"])
def test_b8_off_main_does_not_check_the_block(make_root, progress, where, state):
    order_text, code = _BLOCK_STATES[state]
    root = make_root(_sync_files(order_text))
    if where == "not-a-git-dir":
        assert not _git_ok(root, "rev-parse", "--git-dir", ceiling=True), (
            "предусловие: каталог не внутри git-репозитория"
        )
    else:
        _init_git_main(root)
        if where == "feature-branch":
            _git(root, "checkout", "-q", "-b", "feat/x")
        else:
            _git(root, "checkout", "-q", "--detach")

    cp = _check(root)
    assert cp.returncode == 0, f"вне main exit {cp.returncode}\n{_out(cp)[-500:]}"
    assert "ORDER_BLOCK_" not in _out(cp)

    # контроль достижимости: то же дерево на main краснеет, значит «нет находки» выше — не пустой результат
    if where == "not-a-git-dir":
        _init_git_main(root)
    else:
        _git(root, "checkout", "-q", "main")
    control = _check(root)
    assert control.returncode == 0, f"контроль на main exit {control.returncode}\n{_out(control)[-500:]}"
    assert any(ln.startswith(code + " ") and " info " in ln for ln in _out(control).splitlines()), _out(control)[-500:]
