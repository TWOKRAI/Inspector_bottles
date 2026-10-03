# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку
"""Тесты автора на внутренние опасности Task 2.3 (--sync-order, ORDER_BLOCK_*).

Приёмку по критериям пишет слепой тестер (test_acceptance_phase2.py). Здесь — места, видимые только по
устройству механизма: разбор по `\\n` с сохранением `\\r`, байты вне блока, дубль маркера, «main» только
в корне репозитория (решение: корень, вложенный в чужой репозиторий, — не main).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


TIMEOUT = 60
BEGIN = "<!-- progress:begin -->"
END = "<!-- progress:end -->"
PROGRESS = Path(__file__).resolve().parents[1] / "plans_progress.py"
PLAN = "# P\n\n## Порядок выполнения\n\n"


def _env(ceiling: Path | None = None) -> dict[str, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    if ceiling is not None:
        env["GIT_CEILING_DIRECTORIES"] = str(ceiling)
    return env


def _run(args: list[str], cwd: Path | None = None, ceiling: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, timeout=TIMEOUT, env=_env(ceiling), cwd=cwd, encoding="utf-8", errors="replace"
    )


def _sync(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return _run([sys.executable, str(PROGRESS), "--root", str(root), "--sync-order", *extra])


def _plan(done: int, pending: int) -> str:
    items = [f"- Task 1.{i + 1}: a [DONE]\n" for i in range(done)]
    items += [f"- Task 1.{done + i + 1}: b [PENDING]\n" for i in range(pending)]
    return PLAN + "".join(items)


def _write(root: Path, rel: str, data: bytes) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _order_root(tmp_path: Path, order: bytes, name: str = "r") -> tuple[Path, Path]:
    root = tmp_path / name
    _write(root, "plans/2026-10-02_p.md", _plan(3, 5).encode("utf-8"))
    return root, _write(root, "plans/queue/ORDER.md", order)


def test_half_rounds_up_for_37_5_percent(tmp_path):
    root, order = _order_root(tmp_path, f"{BEGIN}\n{END}\n".encode())
    assert _sync(root).returncode == 0
    assert order.read_bytes() == f"{BEGIN}\n- 2026-10-02_p — 3 из 8 · 38%\nв архиве: 0\n{END}\n".encode()


def test_blank_and_stale_lines_inside_block_are_replaced_whole(tmp_path):
    body = "\n\n- старое — 1 из 1 · 100%\n\n  \nмусор\n\n"
    root, order = _order_root(tmp_path, f"до\n{BEGIN}\n{body}{END}\nпосле\n".encode())
    assert _sync(root).returncode == 0
    assert order.read_bytes() == f"до\n{BEGIN}\n- 2026-10-02_p — 3 из 8 · 38%\nв архиве: 0\n{END}\nпосле\n".encode()


def test_duplicate_begin_marker_is_refused_and_file_untouched(tmp_path):
    raw = f"{BEGIN}\nx\n{BEGIN}\ny\n{END}\n".encode()
    root, order = _order_root(tmp_path, raw)
    cp = _sync(root)
    assert cp.returncode == 2 and "progress:begin" in cp.stderr, cp.stderr
    assert order.read_bytes() == raw


def test_marker_with_surrounding_spaces_and_crlf_is_still_a_marker_and_bytes_are_kept(tmp_path):
    raw = f"т\r\n  {BEGIN}  \r\nстарое\r\n{END}\t\r\nхвост".encode()
    root, order = _order_root(tmp_path, raw)
    assert _sync(root).returncode == 0
    want = f"т\r\n  {BEGIN}  \r\n- 2026-10-02_p — 3 из 8 · 38%\r\nв архиве: 0\r\n{END}\t\r\nхвост".encode()
    assert order.read_bytes() == want


def test_non_utf8_bytes_outside_the_block_survive(tmp_path):
    prefix = "Заголовок до блока\n".encode("cp1251")
    raw = prefix + f"{BEGIN}\n{END}\n".encode() + "хвост".encode("cp1251")
    root, order = _order_root(tmp_path, raw)
    assert _sync(root).returncode == 0
    got = order.read_bytes()
    assert got.startswith(prefix) and got.endswith("хвост".encode("cp1251"))


def test_mixed_eol_file_uses_crlf_for_the_block_and_keeps_other_lines(tmp_path):
    raw = f"a\nb\r\n{BEGIN}\r\nx\n{END}\nc\r\n".encode()
    root, order = _order_root(tmp_path, raw)
    assert _sync(root).returncode == 0
    assert (
        order.read_bytes()
        == f"a\nb\r\n{BEGIN}\r\n- 2026-10-02_p — 3 из 8 · 38%\r\nв архиве: 0\r\n{END}\nc\r\n".encode()
    )


def test_second_sync_reports_up_to_date_and_does_not_rewrite(tmp_path):
    root, order = _order_root(tmp_path, f"{BEGIN}\n{END}\n".encode())
    _sync(root)
    before = order.stat().st_mtime_ns
    cp = _sync(root)
    assert cp.returncode == 0 and "актуален" in cp.stdout
    assert order.stat().st_mtime_ns == before


# ---------------------------------------------------------------- «main» только в корне репозитория


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, timeout=TIMEOUT, env=_env())


def _init_main(cwd: Path) -> None:
    _git(cwd, "init", "-q")
    _git(cwd, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(cwd, "config", "user.email", "t@example.invalid")
    _git(cwd, "config", "user.name", "tester")
    _git(cwd, "config", "commit.gpgsign", "false")
    _git(cwd, "add", "-A")
    _git(cwd, "commit", "-q", "-m", "snap")


def _check(root: Path, ceiling: Path | None) -> subprocess.CompletedProcess:
    base = root / "plans" / "queue" / "progress-baseline.txt"
    return _run(
        [sys.executable, str(PROGRESS), "--root", str(root), "--check", "--baseline", str(base)], ceiling=ceiling
    )


def test_root_nested_in_foreign_repo_on_main_is_not_main(tmp_path):
    outer = tmp_path / "outer"
    outer.mkdir()
    _write(outer, "README.md", b"outer repo\n")
    root = outer / "sub"
    _write(root, "plans/2026-10-02_p.md", _plan(3, 5).encode("utf-8"))
    _write(root, "plans/queue/ORDER.md", f"{BEGIN}\nустарело\n{END}\n".encode())
    _write(root, "plans/queue/progress-baseline.txt", b"")
    _init_main(outer)  # внешний репозиторий на main, sub в нём — просто подкаталог
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, text=True, timeout=TIMEOUT
    )
    assert os.path.samefile(top.stdout.strip(), outer), "предусловие: toplevel — внешний репозиторий"

    cp = _check(root, ceiling=None)  # без потолка: git видит внешний репозиторий
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "ORDER_BLOCK_" not in cp.stdout + cp.stderr

    # контроль достижимости: сам root как репозиторий на main с тем же деревом краснеет
    _init_main(root)
    control = _check(root, ceiling=None)
    assert control.returncode == 0 and "ORDER_BLOCK_STALE " in control.stdout, control.stdout + control.stderr


# ---------------------------------------------------------------- ревью: тег main, атомарная запись, хвост stderr


def _stale_root(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    _write(root, "plans/2026-10-02_p.md", _plan(3, 5).encode("utf-8"))
    _write(root, "plans/queue/ORDER.md", f"{BEGIN}\nустарело\n{END}\n".encode())
    _write(root, "plans/queue/progress-baseline.txt", b"")
    _init_main(root)
    return root


def test_tag_named_main_does_not_hide_the_main_branch(tmp_path):
    # `rev-parse --abbrev-ref HEAD` при ветке и теге main отвечает `heads/main` -> проверка блока молча пропускалась
    root = _stale_root(tmp_path, "tagged")
    _git(root, "tag", "main")
    cp = _check(root, ceiling=None)
    assert cp.returncode == 0 and "ORDER_BLOCK_STALE " in cp.stdout, cp.stdout + cp.stderr


def test_tag_named_main_on_detached_head_is_not_main(tmp_path):
    root = _stale_root(tmp_path, "detached")
    _git(root, "tag", "main")
    _git(root, "checkout", "-q", "--detach")
    cp = _check(root, ceiling=None)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "ORDER_BLOCK_" not in cp.stdout + cp.stderr


def _load(name: str, path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_sync_is_atomic_when_replace_fails(tmp_path, monkeypatch):
    import pytest

    pp = _load("pp_author_atomic", PROGRESS)
    raw = f"до\r\n{BEGIN}\r\nстарое\r\n{END}\r\nпосле\r\n".encode()
    root, order = _order_root(tmp_path, raw)
    plans = pp.discover(root)
    before = sorted(p.name for p in order.parent.iterdir())

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(pp.os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        pp.sync_order(order, plans, [])
    assert order.read_bytes() == raw
    assert sorted(p.name for p in order.parent.iterdir()) == before, "остался временный файл"


def test_sync_leaves_no_temp_file_on_success(tmp_path):
    root, order = _order_root(tmp_path, f"{BEGIN}\n{END}\n".encode())
    assert _sync(root).returncode == 0
    assert sorted(p.name for p in order.parent.iterdir()) == ["ORDER.md"]


def test_validate_prints_stderr_tail_when_script_crashes(capsys, monkeypatch):
    from types import SimpleNamespace

    validate = _load("validate_author_tail", Path(__file__).resolve().parents[2] / "validate.py")
    stderr = "\n".join(f"Traceback строка {i}" for i in range(30)) + "\nRuntimeError: упал"
    fake = subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr=stderr)
    monkeypatch.setattr(validate, "subprocess", SimpleNamespace(run=lambda *a, **k: fake))
    monkeypatch.setattr(validate, "errors", [])
    validate.check_plans_progress()
    out = capsys.readouterr().out
    assert "[FAIL]" in out and len(validate.errors) == 1
    assert "RuntimeError: упал" in out and "Traceback строка 29" in out
    assert "Traceback строка 5" not in out, "печатается весь stderr, а не хвост"
