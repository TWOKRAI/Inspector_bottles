"""Слепые acceptance-тесты 4.8a: CLI `python -m scripts.capacity_bench`.

Источник истины — `plans/transport-single-policy/task-4.8.md`, п. 8 и первый пункт acceptance.
Стенд НЕ поднимается: только `--dry-run`, `--help` и неизвестный профиль (всегда с
`--dry-run`, чтобы ошибка реализации не запустила замер). Всё — подпроцессом с жёстким
`timeout=`; cwd и PYTHONPATH = корень дерева.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _require_main_module():
    """Якорь RED: нет `__main__.py` -> ModuleNotFoundError, а не неопознанный rc подпроцесса."""
    try:
        spec = importlib.util.find_spec("scripts.capacity_bench.__main__")
    except ModuleNotFoundError:
        spec = None
    if spec is None:
        raise ModuleNotFoundError("No module named 'scripts.capacity_bench.__main__'")


def _run(args, timeout=20):
    _require_main_module()
    env = dict(os.environ, PYTHONPATH=str(REPO))
    return subprocess.run(
        [sys.executable, "-m", "scripts.capacity_bench", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    ).stdout.strip()


def _dry_run(tmp_path):
    t0 = time.monotonic()
    proc = _run(["--profile", "quick", "--dry-run", "--out", str(tmp_path)])
    return proc, time.monotonic() - t0


def test_dry_run_quick_writes_report(tmp_path):
    proc, elapsed = _dry_run(tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert elapsed < 20
    assert len(list(tmp_path.glob("*.md"))) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_dry_run_json_commit_cases_and_selfcheck(tmp_path):
    proc, _ = _dry_run(tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    (json_path,) = tmp_path.glob("*.json")
    data = json.loads(json_path.read_bytes().decode("utf-8"))
    assert data["passport"]["commit"] == _git_head()
    assert data["cases"] == []
    assert data["selfcheck"]["ok"] is True
    assert data["profile"] == "quick"
    assert data["tests"] is None


def test_dry_run_markdown_carries_commit(tmp_path):
    proc, _ = _dry_run(tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    (md_path,) = tmp_path.glob("*.md")
    assert _git_head() in md_path.read_bytes().decode("utf-8")


def test_unknown_profile_exits_with_rc_2(tmp_path):
    proc = _run(["--profile", "nope", "--dry-run", "--out", str(tmp_path)])
    assert proc.returncode == 2
    assert list(tmp_path.iterdir()) == []


def test_help_lists_documented_options():
    proc = _run(["--help"])
    assert proc.returncode == 0, proc.stderr[-2000:]
    for option in ("--profile", "--tests", "--baseline", "--port", "--out", "--dry-run"):
        assert option in proc.stdout


def test_help_shows_default_port_8775():
    """Допущение: дефолт порта видно в --help (argparse `%(default)s`)."""
    proc = _run(["--help"])
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "8775" in proc.stdout
