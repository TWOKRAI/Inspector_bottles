#!/usr/bin/env python3
"""Retry qex incremental indexing until it completes.

qex has a hard-coded 10 s timeout per embedding batch (no env knob), so a single
`index_codebase` run can fail on some batch. A retry moves forward ONLY once a
snapshot exists: qex writes `snapshot.json` + the dense vectors at the very end
of a successful run, so until the first full index completes every attempt
starts from zero ("No previous snapshot found, performing full index"). Never
run two of these against one Ollama: alone a batch takes ~2 s, two competing
runs take 8-10 s each and time each other out forever (2026-09-18). Complements
``reindex_progress.py`` (model warm-up + live progress): this script drives
``index_codebase`` over MCP JSON-RPC in a bounded retry loop and keeps the qex
stderr of every attempt — a bare "timeout" verdict without the server log is
what made 15 consecutive failures undiagnosable once.

Usage:
    python .claude/plugins/mcp-qex/reindex_retry.py [--project PATH] [--attempts N]

Logs: <project>/.claude/.qex/logs/reindex_retry/attempt_NN.log (gitignored).
Exit: 0 — indexed; 1 — attempts exhausted; 2 — launcher not found.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

LAUNCHER_REL = Path(".claude") / "plugins" / "mcp-qex" / "qex-launcher.py"
LOG_REL = Path(".claude") / ".qex" / "logs" / "reindex_retry"


def rpc(proc: subprocess.Popen, method: str, params: dict, req_id: int) -> dict | None:
    """Send one JSON-RPC request and wait for the reply with the same id."""
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(
        json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        + "\n"
    )
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == req_id:
            return msg


def attempt(project: Path, launcher: Path, log_dir: Path, n: int) -> dict | None:
    log_dir.mkdir(parents=True, exist_ok=True)
    # One log file per attempt: the next run must not overwrite the failed one.
    with open(log_dir / f"attempt_{n:02d}.log", "w", encoding="utf-8") as err:
        proc = subprocess.Popen(
            [sys.executable, str(launcher)],
            cwd=project,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=err,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            rpc(
                proc,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "qex-reindex-retry", "version": "1"},
                },
                1,
            )
            assert proc.stdin is not None
            proc.stdin.write(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
                + "\n"
            )
            proc.stdin.flush()
            return rpc(
                proc,
                "tools/call",
                {"name": "index_codebase", "arguments": {"path": str(project)}},
                2,
            )
        finally:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()


def main(argv: list[str] | None = None) -> int:
    # Windows-консоль по умолчанию cp1251/cp866: без этого русский вывод и
    # символы вроде -> x -- роняют скрипт с UnicodeEncodeError ещё до работы.
    # Тот же приём, что в mcp-graphify/scripts/graph_slice.py.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Retry qex incremental indexing until it completes."
    )
    parser.add_argument(
        "--project", type=Path, default=Path.cwd(), help="project root (default: cwd)"
    )
    parser.add_argument(
        "--attempts", type=int, default=12, help="max attempts (default: 12)"
    )
    args = parser.parse_args(argv)
    project = args.project.resolve()
    launcher = project / LAUNCHER_REL
    if not launcher.is_file():
        print(
            f"[reindex_retry] launcher not found: {launcher} — is plugin mcp-qex enabled and synced?",
            file=sys.stderr,
        )
        return 2
    log_dir = project / LOG_REL
    for i in range(1, args.attempts + 1):
        started = time.time()
        reply = attempt(project, launcher, log_dir, i)
        took = time.time() - started
        if reply is None:
            print(
                f"[{i}] server closed silently after {took:.0f} s (see {log_dir})",
                flush=True,
            )
            continue
        if "error" in reply:
            print(f"[{i}] {took:.0f} s — {reply['error'].get('message')}", flush=True)
            continue
        text = json.dumps(reply.get("result", {}), ensure_ascii=False)[:400]
        print(f"[{i}] OK in {took:.0f} s: {text}", flush=True)
        return 0
    print(
        f"[reindex_retry] {args.attempts} attempts exhausted — logs: {log_dir}",
        flush=True,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
