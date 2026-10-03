"""Acceptance-тесты хука agent-journal.sh (Task 5.1): session_id, branch, SessionStart.

Хук запускается как `bash <script>` с одним JSON-объектом на stdin и дописывает
ОДНУ JSON-строку в <AGENT_JOURNAL_DIR>/agent-journal.jsonl. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]
CLAUDE_DIR = PLUGIN_DIR.parents[1]
SCRIPT = (PLUGIN_DIR / "hooks" / "agent-journal.sh").as_posix()
SETTINGS = CLAUDE_DIR / "settings.json"
PLUGIN_JSON = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
JOURNAL_MARK = "hooks/agent-journal.sh"
GIT_ID = ["-c", "user.email=a@b", "-c", "user.name=t"]


def _git_bash() -> str:
    """Git Bash, а не WSL-`bash` из System32 (subprocess подхватывает тот первым)."""
    git = shutil.which("git")
    for parent in Path(git).resolve().parents if git else []:
        if (parent / "bin" / "bash.exe").is_file():
            return str(parent / "bin" / "bash.exe")
    return "bash"  # POSIX-машина


BASH = _git_bash()


def _git(repo: Path, *args: str, ceiling: bool = False) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if ceiling:
        env["GIT_CEILING_DIRECTORIES"] = repo.parent.as_posix()
    return subprocess.run(
        ["git", *GIT_ID, "-C", str(repo), *args],
        capture_output=True, text=True, env=env, timeout=30,
    )


def make_repo(root: Path, name: str, branch: str) -> Path:
    repo = root / name
    repo.mkdir()
    assert _git(repo, "init", "-q").returncode == 0
    assert _git(repo, "commit", "-q", "--allow-empty", "-m", "x").returncode == 0
    assert _git(repo, "checkout", "-q", "-b", branch).returncode == 0
    return repo


def run_hook(journal_dir: Path, payload, run_cwd: Path, ceiling: Path | None = None):
    """Запускает хук. payload: dict -> JSON, str -> как есть (битый stdin)."""
    stdin = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    env = dict(os.environ)
    env["AGENT_JOURNAL_DIR"] = journal_dir.as_posix()
    if ceiling is not None:
        env["GIT_CEILING_DIRECTORIES"] = ceiling.as_posix()
    return subprocess.run(
        [BASH, SCRIPT], input=stdin.encode("utf-8"), cwd=str(run_cwd),
        env=env, capture_output=True, timeout=30,
    )


def read_records(journal_dir: Path) -> list[dict]:
    raw = (journal_dir / "agent-journal.jsonl").read_bytes().decode("utf-8")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


@pytest.fixture
def jdir(tmp_path: Path) -> Path:
    d = tmp_path / "journal"
    d.mkdir()
    return d


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    return make_repo(tmp_path, "repo_x", "branch-x"), make_repo(tmp_path, "repo_y", "feat/branch-y")


def start_payload(cwd, **extra) -> dict:
    p = {"hook_event_name": "SubagentStart", "session_id": "sess-1", "agent_type": "tester",
         "agent_id": "ag-1", "cwd": str(cwd)}
    p.update(extra)
    return p


# --- A1, A2 ---------------------------------------------------------------

def test_subagent_start_record_has_session_id_and_branch_keys(jdir, repos):
    x, _ = repos
    assert run_hook(jdir, start_payload(x), x).returncode == 0
    rec = read_records(jdir)[0]
    assert rec["event"] == "SubagentStart"
    assert rec["session_id"] == "sess-1"
    assert rec["branch"] == "branch-x"


def test_branch_comes_from_input_cwd_not_hook_process_cwd(jdir, repos):
    x, y = repos
    assert run_hook(jdir, start_payload(y), x).returncode == 0
    assert read_records(jdir)[0]["branch"] == "feat/branch-y"


# --- A3 -------------------------------------------------------------------

def test_detached_head_gives_empty_branch_and_exit_zero(jdir, repos):
    x, _ = repos
    assert _git(x, "checkout", "-q", "--detach").returncode == 0
    assert _git(x, "branch", "--show-current").stdout.strip() == ""
    assert run_hook(jdir, start_payload(x), x).returncode == 0
    rec = read_records(jdir)[0]
    assert rec["session_id"] == "sess-1"  # запись есть, не пропала
    assert rec["branch"] == ""


def test_cwd_outside_git_repo_gives_empty_branch_and_exit_zero(jdir, repos, tmp_path):
    x, _ = repos
    plain = tmp_path / "plain"
    plain.mkdir()
    # tmp_path может лежать внутри чужого git-репо -> потолок поиска .git
    assert _git(plain, "rev-parse", "--git-dir", ceiling=True).returncode != 0
    assert run_hook(jdir, start_payload(plain), x, ceiling=tmp_path).returncode == 0
    rec = read_records(jdir)[0]
    assert rec["session_id"] == "sess-1"
    assert rec["branch"] == ""


def test_missing_cwd_key_gives_empty_branch_and_exit_zero(jdir, repos):
    x, _ = repos  # процесс хука стоит в репо x: ветку нельзя брать оттуда
    payload = start_payload(x)
    del payload["cwd"]
    assert run_hook(jdir, payload, x).returncode == 0
    rec = read_records(jdir)[0]
    assert rec["agent_id"] == "ag-1"
    assert rec["branch"] == ""


def test_missing_session_id_gives_empty_session_id(jdir, repos):
    x, _ = repos
    payload = start_payload(x)
    del payload["session_id"]
    assert run_hook(jdir, payload, x).returncode == 0
    rec = read_records(jdir)[0]
    assert rec["agent_id"] == "ag-1"
    assert rec["session_id"] == ""


# --- A4 -------------------------------------------------------------------

def test_session_start_event_is_recorded_with_session_cwd_and_branch(jdir, repos):
    x, y = repos
    payload = {"hook_event_name": "SessionStart", "session_id": "sess-9",
               "cwd": str(y), "source": "startup"}
    assert run_hook(jdir, payload, x).returncode == 0
    recs = read_records(jdir)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["event"] == "SessionStart"
    assert rec["session_id"] == "sess-9"
    assert rec["cwd"] == str(y)
    assert rec["branch"] == "feat/branch-y"


# --- A5 -------------------------------------------------------------------

@pytest.mark.parametrize("garbage", ["this is not json {{{", ""], ids=["not-json", "empty"])
def test_broken_stdin_exit_zero_keeps_journal_valid_and_old_lines_intact(jdir, repos, garbage):
    x, _ = repos
    assert run_hook(jdir, start_payload(x), x).returncode == 0
    path = jdir / "agent-journal.jsonl"
    before = path.read_bytes()
    assert before.count(b"\n") == 1  # предусловие: одна честная запись
    assert run_hook(jdir, garbage, x).returncode == 0
    after = path.read_bytes()
    assert after.startswith(before)
    for line in after.decode("utf-8").splitlines():
        json.loads(line)


# --- A6, A7 ---------------------------------------------------------------

def test_three_calls_append_three_lines_in_call_order(jdir, repos):
    x, _ = repos
    for i in (1, 2, 3):
        assert run_hook(jdir, start_payload(x, agent_id=f"ag-{i}"), x).returncode == 0
    assert [r["agent_id"] for r in read_records(jdir)] == ["ag-1", "ag-2", "ag-3"]


def test_subagent_stop_tail_is_last_300_chars_of_message(jdir, repos):
    x, _ = repos
    msg = "HEADMARK" + "a" * 484 + "TAILMARK"  # ровно 500 символов
    assert len(msg) == 500
    payload = start_payload(x, hook_event_name="SubagentStop", last_assistant_message=msg)
    assert run_hook(jdir, payload, x).returncode == 0
    rec = read_records(jdir)[0]
    assert rec["event"] == "SubagentStop"
    assert rec["tail"] == "a" * 292 + "TAILMARK"
    assert len(rec["tail"]) == 300
    assert "HEADMARK" not in rec["tail"]


def test_russian_message_survives_round_trip_and_file_is_utf8(jdir, repos):
    x, _ = repos
    msg = "Готово: проверено 3 теста, всё зелёное"
    payload = start_payload(x, hook_event_name="SubagentStop", last_assistant_message=msg)
    assert run_hook(jdir, payload, x).returncode == 0
    raw = (jdir / "agent-journal.jsonl").read_bytes()
    assert read_records(jdir)[0]["tail"] == msg
    raw.decode("utf-8")  # не UTF-8 -> UnicodeDecodeError
    assert b"\xef\xbf\xbd" not in raw  # нет U+FFFD: кириллица не превратилась в «?»-мусор


# --- A8: проводка ---------------------------------------------------------

def _commands(section) -> list[str]:
    return [h.get("command", "") for group in section for h in group.get("hooks", [])]


@pytest.mark.parametrize("event", ["SessionStart", "SubagentStart", "SubagentStop"])
def test_plugin_json_wires_journal_hook_for_event(event):
    hooks = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["hooks"]
    assert event in hooks, f"plugin.json hooks has no {event}"
    assert any(JOURNAL_MARK in c for c in _commands(hooks[event]))


@pytest.mark.parametrize("event", ["SessionStart", "SubagentStart", "SubagentStop"])
def test_settings_json_wires_journal_hook_for_event(event):
    hooks = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]
    assert event in hooks, f"settings.json hooks has no {event}"
    assert any(JOURNAL_MARK in c for c in _commands(hooks[event]))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
