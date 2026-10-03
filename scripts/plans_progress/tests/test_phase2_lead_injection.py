"""Тест лида, закрывающий живого мутанта инъекции S16 (Tasks 2.2+2.3).

S16: сравнение блока без `rstrip("\\r")` — на `main` свежий блок в CRLF-файле читался бы как устаревший.
Тестер проверил CRLF только для `--sync-order` (B3), а дрейф на `main` — только для LF.
"""

# ruff: noqa: E501

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROGRESS = Path(__file__).resolve().parents[1] / "plans_progress.py"

PLAN = "# T\n\n## Порядок выполнения\n\n- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n"
ORDER_CRLF = "# Порядок\r\n\r\n<!-- progress:begin -->\r\nстарое\r\n<!-- progress:end -->\r\n\r\nхвост\r\n"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, timeout=60)


def test_fresh_crlf_block_on_main_is_not_stale(make_root, progress):
    root = make_root({"plans/2026-10-02_x.md": PLAN, "plans/queue/progress-baseline.txt": ""})
    order = root / "plans" / "queue" / "ORDER.md"
    order.parent.mkdir(parents=True, exist_ok=True)
    order.write_bytes(ORDER_CRLF.encode("utf-8"))
    for args in (
        ("init", "-q"),
        ("symbolic-ref", "HEAD", "refs/heads/main"),
        ("config", "user.email", "t@example.invalid"),
        ("config", "user.name", "lead"),
        ("config", "core.autocrlf", "false"),
        ("config", "commit.gpgsign", "false"),
    ):
        _git(root, *args)
    sync = progress(root, "--sync-order")
    assert sync.returncode == 0, (sync.stdout + sync.stderr)[-400:]
    raw = order.read_bytes()
    assert b"- 2026-10-02_x \xe2\x80\x94 1 \xd0\xb8\xd0\xb7 2 \xc2\xb7 50%\r\n" in raw, raw[-300:]
    assert b"\n" not in raw.replace(b"\r\n", b""), "в файле остался одиночный LF"
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "snap")
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(root.parent), "PYTHONIOENCODING": "utf-8"}
    cp = subprocess.run(
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
        text=True,
        encoding="utf-8",
        timeout=60,
        env=env,
    )
    assert cp.returncode == 0, (cp.stdout + cp.stderr)[-500:]
    assert "ORDER_BLOCK_" not in cp.stdout + cp.stderr
